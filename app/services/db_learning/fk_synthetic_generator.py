"""VYRA v3.27.0 — FK Synthetic Query Generator (G1).

ds_db_relationships içindeki her FK için 2 örnek SQL üret-execute-öğret:

  1) FK satırlarını oku (per source_id)
  2) Her FK için LOOKUP_JOIN + AGGREGATE_COUNT render et
     (kullanıcı kuralı: '2 örnek yeter')
  3) UNIQUE(source_id, relationship_id, template_kind) → idempotent
     (önceden başarıyla execute edilmişse atla)
  4) SafeSQLExecutor ile hedef DB'de execute et
  5) Başarılı + row_count > 0 → learned_db_queries'e yaz
     (source='synthetic', dedupe ile)
  6) ds_synthetic_query_runs'a audit (success/fail + elapsed)

Hatalar:
  * Single FK error pipeline'ı durdurmaz — devam edilir
  * Tüm batch için final özet döner: {total, success, skipped, failed}
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from app.services.db_learning.dedupe_service import sql_hash
from app.services.db_learning.learned_queries_service import (
    record_successful_query,
)
from app.services.db_learning.synthetic_templates import (
    COMPLEXITY_BY_KIND,
    Relationship,
    RenderedQuery,
    TEMPLATE_KINDS,
    render,
    render_junction_n2m,
)
from app.services.db_learning.synthetic_dialect import (
    CAT_NUMERIC,
    CAT_TEMPORAL,
    CAT_TEXT,
    classify_data_type,
)
from app.services.db_learning.synthetic_errors import classify_synthetic_error

# v3.29.2 G3: tek-Relationship temelli ("per-FK") render edilebilen kinds.
# Chain-only kinds (CHAIN_JOIN_*, CTE_LATEST_N_PER_GROUP, LATERAL_TOP_K,
# JUNCTION_N2M) ayrı bir orchestrator gerektirir (fk_graph_resolver tabanlı).
SINGLE_REL_KINDS: tuple = (
    "LOOKUP_JOIN",
    "AGGREGATE_COUNT",
    # v3.45.0 P2 (G6) — tip-farkında, 4-dialect per-FK
    "AGGREGATE_STATS",
    "EXISTS_ANTI_JOIN",
    "DISTINCT_COUNT",
    "STRING_AGG_DETAILS",
    "TIME_SERIES_GENERATE",
    "WINDOW_RUNNING_TOTAL",
)

# v3.45.0 P2: 1:1 ilişkide agregasyon (her parent için N child) mantıksız → bu kind'ler
# 1:1'de elenir (AGGREGATE_COUNT zaten eleniyordu, STATS/ANTI_JOIN/DISTINCT de aynı sınıf).
_AGGREGATE_KINDS_SKIP_ON_1TO1 = frozenset({
    "AGGREGATE_COUNT", "AGGREGATE_STATS", "EXISTS_ANTI_JOIN",
    "DISTINCT_COUNT", "STRING_AGG_DETAILS", "WINDOW_RUNNING_TOTAL",
})
# Default kind seti (caller template_kinds vermezse): "2 örnek yeter" → v3.45.0'da tip-farkında
# STATS + orphan ANTI_JOIN (P2a) + koşan-toplam WINDOW (P2b, 4-dialect) ile 5'e çıktı (1:N FK'ler;
# 1:1'de yalnız LOOKUP_JOIN). DISTINCT_COUNT/STRING_AGG_DETAILS/TIME_SERIES opt-in (caller isterse).
_DEFAULT_KINDS = [
    "LOOKUP_JOIN", "AGGREGATE_COUNT", "AGGREGATE_STATS", "EXISTS_ANTI_JOIN", "WINDOW_RUNNING_TOTAL",
]

# v3.45.0 P2b: tip-bağımlı kind → child tablodan GEREKEN col_ctx anahtarları (hepsi mevcut
# olmalı, yoksa skipped_no_column). Generator tek yerde keşfeder; render() defansif ValueError ile
# yedekler. Burada OLMAYAN kind tip-bağımsızdır (LOOKUP/COUNT/ANTI_JOIN).
_KIND_COL_REQUIREMENTS: Dict[str, tuple] = {
    "AGGREGATE_STATS": ("numeric",),
    "DISTINCT_COUNT": ("text",),
    "STRING_AGG_DETAILS": ("text",),          # order_column (temporal) opsiyonel
    "WINDOW_RUNNING_TOTAL": ("numeric", "temporal"),
    "TIME_SERIES_GENERATE": ("temporal",),
}
# PG-spesifik kind'ler (takvim CTE GENERATE_SERIES) — non-PG'de ATLA (bozuk SQL üretme).
# 4-dialect takvim (CONNECT BY / recursive CTE) sonraki faza ertelendi.
_PG_ONLY_KINDS = frozenset({"TIME_SERIES_GENERATE"})
_PG_DIALECTS = frozenset({"postgresql", "postgres", "pg"})
# Tek-tablo (fact-level) kind'ler: FK başına değil TABLO başına 1 kez render (aynı fact'in
# birden çok FK'sinde tekrar execute edilmesin → hedef DB yükü). NOT: WINDOW_RUNNING_TOTAL artık
# FK kolonuyla PARTITION BY edilip İLİŞKİ-düzeyli olduğundan burada DEĞİL (her FK farklı/anlamlı).
# Yalnız TIME_SERIES_GENERATE gerçekten tek-tablo (FK kullanmaz).
_TABLE_LEVEL_KINDS = frozenset({"TIME_SERIES_GENERATE"})
# v3.29.2 G3: yeni v2 template'ler — template_version=2 işaretlenir.
V2_KINDS: frozenset = frozenset({
    "CHAIN_JOIN_3HOP", "CHAIN_JOIN_NHOP", "CTE_LATEST_N_PER_GROUP",
    "LATERAL_TOP_K", "STRING_AGG_DETAILS", "JUNCTION_N2M",
    "TIME_SERIES_GENERATE", "WINDOW_RUNNING_TOTAL",
})

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DTO
# ─────────────────────────────────────────────────────────────

@dataclass
class GenerationSummary:
    source_id: int
    dialect: str
    total_fks: int = 0
    total_attempts: int = 0       # FK × template_kinds (idempotent skip dahil)
    success: int = 0
    skipped_existing: int = 0     # zaten başarılı bir UNIQUE satır vardı
    failed_execute: int = 0
    failed_learn: int = 0
    elapsed_ms: int = 0
    errors: List[str] = None      # type: ignore
    # v3.32.0 G1: yeni sayaçlar
    skipped_empty: int = 0              # row_count=0 → öğretmedik
    skipped_recent_failure: int = 0     # circuit breaker (son 24h fail)
    skipped_cardinality: int = 0        # 1:1 için AGGREGATE_COUNT atlandı vb.
    junction_attempts: int = 0
    junction_success: int = 0
    promoted_few_shot: int = 0          # v3.44.0 P1: few_shot_examples'a terfi edilen sentetik örnek
    skipped_no_column: int = 0          # v3.45.0 P2: tip-bağımlı kind için uygun kolon yok (örn. STATS sayısal kolon)
    skipped_dialect: int = 0            # v3.45.0 P2b: PG-only kind non-PG kaynakta atlandı (TIME_SERIES)
    skipped_table_dup: int = 0          # v3.45.0 P2b: tek-tablo kind aynı fact için tekrar (WINDOW/TIME_SERIES)

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

# v3.44.0 (P0): Sistem/extension şemaları sentetik üretimden DIŞLA. Bunlar config/metadata
# tabloları (örn. pg_partman.part_config — TEXT kolonlar tablo adı tutar, gerçek FK değil) →
# anlamsız JOIN'ler render+execute edilip başarısız/boş denemeye ve gürültüye yol açıyordu.
# Tümü LOWERCASE (karşılaştırma LOWER() ile). 4 dialect sistem şemaları + yaygın extension'lar.
_EXCLUDED_SCHEMAS = sorted({
    # PostgreSQL sistem + yaygın extension
    "pg_catalog", "information_schema", "pg_toast", "pg_temp_1", "pg_toast_temp_1",
    "partman", "pglogical", "cron", "repack", "pg_repack",
    "_timescaledb_catalog", "_timescaledb_internal", "timescaledb_information",
    "topology", "tiger", "tiger_data",
    # Oracle sistem
    "sys", "system", "sysaux", "outln", "dbsnmp", "appqossys", "ctxsys",
    "xdb", "mdsys", "ordsys", "ordeleem", "wmsys", "audsys", "lbacsys",
    "gsmadmin_internal", "dvsys", "olapsys", "exfsys",
    # MSSQL
    "guest", "db_owner", "db_accessadmin", "sys",
    # MySQL
    "mysql", "performance_schema", "sys",
})

# v3.44.0 (P0): inferred FK'ler bu confidence eşiğinin altındaysa sentetik üretime girmez
# (declared FK'ler — is_inferred=FALSE — her zaman geçer). pg_partman naming-skoru ~0.80 → elenir.
_MIN_INFERRED_CONFIDENCE = 0.85


# v3.45.0 P2: AGGREGATE_STATS ölçü-kolonu seçiminde tercih edilen isim ipuçları (TR+EN).
# Sayısal-ama-anahtar (id/no/code) kolonlar ölçü değildir → elenir.
_MEASURE_NAME_HINTS = (
    "amount", "tutar", "price", "fiyat", "total", "toplam", "qty", "quantity",
    "miktar", "adet", "cost", "maliyet", "balance", "bakiye", "sum", "value", "deger",
)


def _load_table_columns(cur, source_id: int, schema: Optional[str], table: str) -> List[Dict[str, Any]]:
    """ds_db_objects.columns_json → [{name, data_type, cat}]. JSONB psycopg2'de list/str
    gelebilir → ikisi de ele alınır. Hata/yokluk → boş liste (tip-bağımlı kind skip edilir)."""
    try:
        cur.execute(
            """
            SELECT columns_json FROM ds_db_objects
            WHERE source_id = %s
              AND COALESCE(LOWER(schema_name), '') = COALESCE(LOWER(%s), '')
              AND LOWER(object_name) = LOWER(%s)
            LIMIT 1
            """,
            (source_id, schema, table),
        )
        row = cur.fetchone()
    except Exception as e:
        logger.debug("[fk_gen.cols] %s.%s yüklenemedi: %s", schema, table, e)
        return []
    if not row:
        return []
    raw = row.get("columns_json") if hasattr(row, "get") else row[0]
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        dt = c.get("data_type")
        out.append({
            "name": name,
            "data_type": dt,
            "cat": classify_data_type(dt),
            "is_pk": bool(c.get("is_pk")),   # discovery doldurur (4 dialect)
        })
    return out


def _is_keyish_name(name: str) -> bool:
    nl = (name or "").lower()
    return nl == "id" or nl.endswith("_id") or nl.endswith("_no") or nl.endswith("_code")


# v3.45.0 P2: ölçü kolonu adı güvenlik guard'ı. _quote_identifier zaten tırnaklar; bu guard
# SADECE tırnak-kaçışı/kontrol baytı/ayraç içeren PATOLOJİK adları eler. Unicode harfler
# (Türkçe ş/ı/ğ/ö/ç/ü) İZİNLİDİR — hedef kitle TR şemaları (is_safe_identifier ASCII-only
# olduğundan 'değer'/'işlem_tutarı' gibi gerçek ölçü kolonlarını yanlışlıkla eliyordu).
_UNSAFE_MEASURE_CHARS = re.compile(r'[\x00-\x1f"\'`;\[\]\\]')


def _safe_measure_name(name: str) -> bool:
    if not name or not isinstance(name, str) or len(name) > 128:
        return False
    return not _UNSAFE_MEASURE_CHARS.search(name)


# v3.46.0 P3: ds_synthetic_query_runs.error_kind kolonu (mig 052) var mı — yalnız-pozitif cache
# (mig süreç ayaktayken uygulanırsa bir sonraki çağrı yeniden sorgular; kalıcı-False kilidi yok).
_HAS_ERROR_KIND_COL: Optional[bool] = None


def _has_error_kind_col(cur) -> bool:
    global _HAS_ERROR_KIND_COL
    if _HAS_ERROR_KIND_COL:
        return True
    try:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'ds_synthetic_query_runs' AND column_name = 'error_kind'
            LIMIT 1
            """
        )
        if cur.fetchone():
            _HAS_ERROR_KIND_COL = True
            return True
    except Exception:
        pass
    return False


def _pick_numeric_measure(cols: List[Dict[str, Any]], exclude_names: List[str]) -> Optional[str]:
    """Child tablodan agregasyona uygun SAYISAL ÖLÇÜ kolonu seç. Elenenler: FK kolonları,
    PK (is_pk — discovery'den, otoriter), id/no/code benzeri anahtar adları, patolojik adlar.
    İsim ipucu (amount/tutar/...) varsa öncelikli. **Temiz ölçü yoksa None** (keyish/PK'ya
    DÜŞMEZ — 'sipariş_id toplamı' gibi anlamsız SUM önlenir → AGGREGATE_STATS skip)."""
    excl = {(e or "").lower() for e in (exclude_names or [])}
    candidates = [
        c for c in cols
        if c.get("cat") == CAT_NUMERIC
        and (c["name"] or "").lower() not in excl
        and not c.get("is_pk")
        and not _is_keyish_name(c["name"])
        and _safe_measure_name(c["name"])
    ]
    if not candidates:
        return None
    for c in candidates:
        if any(h in (c["name"] or "").lower() for h in _MEASURE_NAME_HINTS):
            return c["name"]
    return candidates[0]["name"]


# v3.45.0 P2b: tarih/etiket kolonu isim ipuçları (sıralama/gruplama anlamlılığı için tercih).
_TEMPORAL_NAME_HINTS = (
    "created", "updated", "date", "tarih", "zaman", "time", "_at", "kayit", "islem", "tdate",
)
# Etiket/kategori ipuçları — STRING_AGG/DISTINCT_COUNT için KATEGORİK/kısa kolon tercih edilir.
# Serbest-metin (desc/aciklama/note) BİLİNÇLİ olarak yok: STRING_AGG'de dev hücre, DISTINCT_COUNT'ta
# satır-sayısına yakın anlamsız sonuç üretir (yalnız son-çare ilk-text kolonu olarak seçilebilir).
_TEXT_LABEL_HINTS = (
    "name", "ad", "title", "baslik", "label", "etiket", "status", "durum", "type", "tip",
    "code", "kod", "category", "kategori",
)


def _pick_typed_column(
    cols: List[Dict[str, Any]], exclude_names: List[str], cat: str, hints: tuple
) -> Optional[str]:
    """Verilen kategoride (temporal/text) uygun kolon seç. FK kolonları + PK + keyish + patolojik
    adlar elenir; isim ipucu varsa öncelikli; yoksa ilk uygun. Hiç yoksa None."""
    excl = {(e or "").lower() for e in (exclude_names or [])}
    candidates = [
        c for c in cols
        if c.get("cat") == cat
        and (c["name"] or "").lower() not in excl
        and not c.get("is_pk")
        and not _is_keyish_name(c["name"])
        and _safe_measure_name(c["name"])
    ]
    if not candidates:
        return None
    for c in candidates:
        if any(h in (c["name"] or "").lower() for h in hints):
            return c["name"]
    return candidates[0]["name"]


def _promote_to_few_shot(
    cur, *, source_id: int, company_id: Optional[int],
    rq: "RenderedQuery", kind: str, summary: "GenerationSummary",
) -> None:
    """v3.44.0 P1 — doğrulanmış sentetik sorguyu few_shot_examples'a terfi et (origin='synthetic_fk').

    İcrayı few_shot_auto_populator.promote_synthetic'e devreder → mevcut dedup (L1+L2 cosine),
    canonical embedding ve schema_signature altyapısı yeniden kullanılır (çift insert yolu yok).
    Yalnız learned_db_queries'e YENİ eklenen (status='inserted') sorgular için çağrılır; ayrıca
    populator'ın kendi dedup'ı farklı FK/kind'lerin ürettiği aynı soruyu da bump'a indirir.

    Dayanıklılık: kendi SAVEPOINT'i içinde çalışır → embedding/INSERT hatası ne FK-loop'u ne ana
    txn'ı bozar (best-effort). company_id None ise (admin/global) terfi edilmez — few_shot_examples.
    company_id NOT NULL.
    """
    if company_id is None:
        return  # few_shot_examples.company_id NOT NULL → firma bağlamsız sentetik terfi edilemez
    _sp = "sp_fewshot_promote"
    try:
        cur.execute(f"SAVEPOINT {_sp}")
    except Exception:
        return
    try:
        from app.services.db_learning.few_shot_auto_populator import promote_synthetic

        res = promote_synthetic(
            cur,
            company_id=company_id,
            source_id=source_id,
            question=rq.question_tr,
            sql=rq.sql,
            tables=rq.tables,
            origin="synthetic_fk",
            intent=None,  # sentetik intent gerçek niyetle eşleşmez → yapay mismatch cezasını önle
            created_by=None,
        )
        cur.execute(f"RELEASE SAVEPOINT {_sp}")
        if res.get("status") == "inserted":
            summary.promoted_few_shot += 1
    except Exception as e:
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {_sp}")
            cur.execute(f"RELEASE SAVEPOINT {_sp}")
        except Exception:
            pass
        logger.warning("[fk_gen.fewshot_promote] kind=%s rel-promote atlandı: %s", kind, e)


def _fetch_relationships(
    cur, source_id: int,
    excluded_schemas: Optional[List[str]] = None,
    min_inferred_confidence: float = _MIN_INFERRED_CONFIDENCE,
) -> List[Relationship]:
    """ds_db_relationships'tan FK satırlarını çek.

    v3.32.0 G1:
      1. Composite FK gruplama — aynı ``constraint_name`` altındaki satırlar
         tek ``Relationship`` (from_columns / to_columns listeleri) olur.
         ``constraint_name`` NULL ise her satır kendi id'siyle ayrı kalır.
      2. Declared/inferred dedupe — aynı canonical pair için en yüksek
         ``confidence_score`` (NULL'lar 1.0 sayılır, declared yüksek) tutulur.
      3. Cardinality / is_junction alanları (mevcutsa) Relationship'e geçirilir.

    Satır şeması (defansif okuma; kolon yoksa default'a düşer):
        (id, from_schema, from_table, from_column,
         to_schema, to_table, to_column,
         [constraint_name], [fk_position], [confidence_score],
         [cardinality_from], [cardinality_to], [is_junction])

    Mock cursor / DictRow / tuple — hepsi desteklenir.
    """
    # Tek SELECT — gerçek DB'de tüm meta kolonları döner; mock cursor'da
    # sadece pattern match ile sağlanan kolonlar gelir. Defansif row okuma.
    _excl = [s.lower() for s in (excluded_schemas if excluded_schemas is not None else _EXCLUDED_SCHEMAS)]
    cur.execute(
        """
        SELECT id, from_schema, from_table, from_column,
               to_schema, to_table, to_column,
               constraint_name, fk_position, confidence_score,
               cardinality_from, cardinality_to, is_junction
        FROM ds_db_relationships
        WHERE source_id = %s
          AND from_table IS NOT NULL AND from_table <> ''
          AND to_table IS NOT NULL AND to_table <> ''
          AND from_column IS NOT NULL AND from_column <> ''
          AND to_column IS NOT NULL AND to_column <> ''
          -- v3.44.0 (P0): sistem/extension şema dışla + düşük-confidence inferred FK ele +
          -- admin-reddedilen FK'yi atla (anlamsız sentetik üretimi/gürültü önleme).
          -- Admin DOĞRULADIYSA (admin_verified) düşük confidence olsa da TUTULUR (admin "gerçek" dedi).
          AND LOWER(COALESCE(from_schema, '')) <> ALL(%s)
          AND LOWER(COALESCE(to_schema, '')) <> ALL(%s)
          AND (is_inferred = FALSE OR COALESCE(confidence_score, 1.0) >= %s OR admin_verified = TRUE)
          AND rejected_at IS NULL
          -- v3.48.0: sentetik sorgu YALNIZ keşfedilen (ds_db_objects'te kayıtlı) tablolar
          -- için üretilir. Her iki FK ucu da keşif çıktısında bulunmalı; aksi halde
          -- keşfedilmemiş tabloya sorgu = anlamsız/yetkisiz gürültü. Şema eşleşmesi
          -- NULL-tolerant (tablo adı eşit + şema yalnız iki tarafta da doluysa eşit) →
          -- geçerli keşfedilmiş tablo over-filter edilmez. Aynı scoped cur (source/company
          -- GUC) → ds_db_objects EXISTS de aynı RLS'e tabi.
          AND EXISTS (
              SELECT 1 FROM ds_db_objects o
              WHERE o.source_id = ds_db_relationships.source_id
                AND LOWER(o.object_name) = LOWER(ds_db_relationships.from_table)
                AND (ds_db_relationships.from_schema IS NULL OR o.schema_name IS NULL
                     OR LOWER(o.schema_name) = LOWER(ds_db_relationships.from_schema))
          )
          AND EXISTS (
              SELECT 1 FROM ds_db_objects o2
              WHERE o2.source_id = ds_db_relationships.source_id
                AND LOWER(o2.object_name) = LOWER(ds_db_relationships.to_table)
                AND (ds_db_relationships.to_schema IS NULL OR o2.schema_name IS NULL
                     OR LOWER(o2.schema_name) = LOWER(ds_db_relationships.to_schema))
          )
        ORDER BY source_id, COALESCE(constraint_name, ''),
                 COALESCE(fk_position, 1), id
        """,
        (source_id, _excl, _excl, float(min_inferred_confidence)),
    )
    rows = cur.fetchall() or []

    def _get(row, key: str, idx: int, default=None):
        # Mock _MockCursor scripts'i tuple döner; gerçek DictCursor'sa get()'i destekler.
        if hasattr(row, "get"):
            try:
                v = row.get(key, None)
                if v is not None:
                    return v
            except Exception:
                pass
        try:
            return row[idx]
        except (IndexError, KeyError, TypeError):
            return default

    # 1) Composite FK gruplama: key = (source_id, constraint_name or f"__id_{id}")
    groups: Dict[str, List[Any]] = {}
    group_order: List[str] = []
    for r in rows:
        rid = _get(r, "id", 0)
        cname = _get(r, "constraint_name", 7, None)
        # NULL/boş constraint_name → singleton (kendi id'siyle)
        if cname is None or (isinstance(cname, str) and cname.strip() == ""):
            key = f"__id_{rid}"
        else:
            key = f"cn::{cname}"
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(r)

    raw_rels: List[Relationship] = []
    for key in group_order:
        members = groups[key]
        # fk_position varsa ona göre sırala; yoksa id sırası (zaten ORDER BY ile)
        members.sort(key=lambda r: (
            int(_get(r, "fk_position", 8, 1) or 1),
            int(_get(r, "id", 0) or 0),
        ))
        first = members[0]
        from_cols = [str(_get(m, "from_column", 3)) for m in members]
        to_cols = [str(_get(m, "to_column", 6)) for m in members]
        # canonical id = gruptaki MIN id (deterministik audit FK key)
        canonical_id = min(int(_get(m, "id", 0) or 0) for m in members)

        # Confidence: gruptaki MAX (declared yüksek; NULL → 1.0 say)
        confs = []
        for m in members:
            c = _get(m, "confidence_score", 9, None)
            if c is None:
                confs.append(1.0)
            else:
                try:
                    confs.append(float(c))
                except (TypeError, ValueError):
                    confs.append(1.0)
        confidence = max(confs) if confs else None

        # is_junction: gruptaki herhangi biri TRUE ise TRUE
        is_junction = False
        for m in members:
            v = _get(m, "is_junction", 12, False)
            if v:
                is_junction = True
                break

        # Cardinality alanları — composite içinde aynı olmalı; ilk satırdan al
        c_from = _get(first, "cardinality_from", 10, None)
        c_to = _get(first, "cardinality_to", 11, None)
        cname = _get(first, "constraint_name", 7, None)

        rel = Relationship(
            id=canonical_id,
            from_schema=_get(first, "from_schema", 1),
            from_table=str(_get(first, "from_table", 2)),
            from_column=from_cols[0],
            to_schema=_get(first, "to_schema", 4),
            to_table=str(_get(first, "to_table", 5)),
            to_column=to_cols[0],
            cardinality_from=c_from if c_from in (None, "1", "N") else None,
            cardinality_to=c_to if c_to in (None, "1", "N") else None,
            is_junction=bool(is_junction),
            from_columns=from_cols,
            to_columns=to_cols,
            constraint_name=(str(cname) if cname not in (None, "") else None),
            confidence_score=confidence,
        )
        raw_rels.append(rel)

    # 2) Declared / inferred dedupe — aynı canonical pair (from→to columns)
    # için en yüksek confidence (sonra en küçük id) tutulur.
    def _canon_pair(rel: Relationship) -> tuple:
        return (
            (rel.from_schema or "").lower(),
            (rel.from_table or "").lower(),
            tuple(c.lower() for c in rel.from_columns),
            (rel.to_schema or "").lower(),
            (rel.to_table or "").lower(),
            tuple(c.lower() for c in rel.to_columns),
        )

    best: Dict[tuple, Relationship] = {}
    for rel in raw_rels:
        key = _canon_pair(rel)
        prev = best.get(key)
        if prev is None:
            best[key] = rel
            continue
        # Daha yüksek confidence_score kazanır (NULL → 1.0 say)
        prev_c = prev.confidence_score if prev.confidence_score is not None else 1.0
        cur_c = rel.confidence_score if rel.confidence_score is not None else 1.0
        if cur_c > prev_c:
            best[key] = rel
        elif cur_c == prev_c and rel.id < prev.id:
            best[key] = rel
        # else: prev korunur

    # Orijinal sırayı (group_order yoluyla) koru
    out: List[Relationship] = []
    seen: set = set()
    for rel in raw_rels:
        key = _canon_pair(rel)
        if key in seen:
            continue
        seen.add(key)
        out.append(best[key])
    return out


def _already_succeeded(cur, source_id: int, relationship_id: int, template_kind: str) -> bool:
    """Bu (FK, template) için daha önce başarılı çalıştırma var mı?

    Geriye uyumluluk için korunan eski helper. Yeni kod ``_should_skip``
    kullanmalı (circuit breaker dahil).
    """
    try:
        cur.execute(
            """
            SELECT 1 FROM ds_synthetic_query_runs
            WHERE source_id = %s
              AND relationship_id = %s
              AND template_kind = %s
              AND success = TRUE
            LIMIT 1
            """,
            (source_id, relationship_id, template_kind),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


# v3.32.0 G1.7 — Circuit breaker decision constants
_SKIP_REASON_NONE = "none"
_SKIP_REASON_ALREADY_SUCCESS = "already_success"
_SKIP_REASON_RECENT_FAILURE = "recent_failure"


def _should_skip(
    cur,
    source_id: int,
    relationship_id: int,
    template_kind: str,
) -> str:
    """Bir (FK, template) denemesini atlamak gerekir mi?

    Döner: skip reason string'i.
      - ``"already_success"`` : son başarılı çalıştırma var (idempotent).
      - ``"recent_failure"``  : son 24 saat içinde başarısız oldu
        (transient olabilir; yarın tekrar dene → circuit breaker).
      - ``"none"``            : devam et, denemek serbest.

    Mock cursor durumunda sorgu boş döner → "none" döner (mevcut testler
    bozulmaz, _MockCursor pattern eşleşme ile davranışı kontrol eder).
    """
    # 1) Daha önce başarılı?
    try:
        cur.execute(
            """
            SELECT 1 FROM ds_synthetic_query_runs
            WHERE source_id = %s
              AND relationship_id = %s
              AND template_kind = %s
              AND success = TRUE
            LIMIT 1
            """,
            (source_id, relationship_id, template_kind),
        )
        if cur.fetchone() is not None:
            return _SKIP_REASON_ALREADY_SUCCESS
    except Exception:
        # DB hatasında skip etme — denemeye değer
        return _SKIP_REASON_NONE

    # 2) Son 24 saat içinde failure? (transient olabilir, yarın dene)
    try:
        cur.execute(
            """
            SELECT 1 FROM ds_synthetic_query_runs
            WHERE source_id = %s
              AND relationship_id = %s
              AND template_kind = %s
              AND success = FALSE
              AND executed_at > NOW() - INTERVAL '24 hours'
            LIMIT 1
            """,
            (source_id, relationship_id, template_kind),
        )
        if cur.fetchone() is not None:
            return _SKIP_REASON_RECENT_FAILURE
    except Exception:
        return _SKIP_REASON_NONE

    return _SKIP_REASON_NONE


def _audit_run(
    cur,
    source_id: int,
    company_id: Optional[int],
    rel: Relationship,
    rq: RenderedQuery,
    success: bool,
    row_count: Optional[int],
    elapsed_ms: int,
    error_message: Optional[str],
    learned_query_id: Optional[int],
) -> None:
    """ds_synthetic_query_runs'a audit kaydı (UNIQUE varsa upsert)."""
    # v3.29.2 G3: template versioning meta
    _tv = 2 if rq.template_kind in V2_KINDS else 1
    _cs = getattr(rq, "complexity_score", None) or COMPLEXITY_BY_KIND.get(rq.template_kind, 1)
    _jp = list(getattr(rq, "join_path", None) or rq.tables or [])

    # v3.46.0 P3: hata sınıflandırma (error_kind) — YALNIZ gerçek başarısızlık için (success=False).
    # 'empty_result_skipped_learn' bir başarı marker'ı (success=True) → sınıflanmaz, NULL kalır.
    # Kolon mig 052 ile gelir; yoksa (cache False) INSERT'e EKLENMEZ (audit satırı yine yazılır,
    # graceful). TEK statement → ayrı UPDATE'in savepoint-poison riski yok.
    _ek = (classify_synthetic_error(error_message, rq.dialect)
           if (error_message and not success) else None)
    _use_ek = _has_error_kind_col(cur)
    _ek_col = ", error_kind" if _use_ek else ""
    _ek_val = ", %s" if _use_ek else ""
    _ek_upd = ", error_kind = EXCLUDED.error_kind" if _use_ek else ""

    _params: List[Any] = [
        source_id, company_id, rel.id,
        rel.from_schema, rel.from_table, rel.from_column,
        rel.to_schema, rel.to_table, rel.to_column,
        rq.template_kind, rq.dialect, rq.sql, sql_hash(rq.sql),
        success, row_count, elapsed_ms, error_message, learned_query_id,
        _tv, _cs, _jp,
    ]
    if _use_ek:
        _params.append(_ek)

    try:
        cur.execute(
            f"""
            INSERT INTO ds_synthetic_query_runs
                (source_id, company_id, relationship_id,
                 from_schema, from_table, from_column,
                 to_schema, to_table, to_column,
                 template_kind, dialect, rendered_sql, sql_hash,
                 success, row_count, elapsed_ms, error_message, learned_query_id,
                 template_version, complexity_score, join_path{_ek_col})
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s{_ek_val})
            ON CONFLICT (source_id, relationship_id, template_kind)
              DO UPDATE SET
                rendered_sql = EXCLUDED.rendered_sql,
                sql_hash = EXCLUDED.sql_hash,
                dialect = EXCLUDED.dialect,
                executed_at = NOW(),
                success = EXCLUDED.success,
                row_count = EXCLUDED.row_count,
                elapsed_ms = EXCLUDED.elapsed_ms,
                error_message = EXCLUDED.error_message,
                learned_query_id = COALESCE(EXCLUDED.learned_query_id, ds_synthetic_query_runs.learned_query_id),
                template_version = EXCLUDED.template_version,
                complexity_score = EXCLUDED.complexity_score,
                join_path = EXCLUDED.join_path{_ek_upd}
            """,
            tuple(_params),
        )
    except Exception as e:
        logger.warning("[fk_gen.audit] %s", e)


def _build_executor(source_id: int, dialect: str, company_id: Optional[int]):
    """SafeSQLExecutor + source_dict çift döndür (wiring helper'a benzer)."""
    from app.services.safe_sql_executor import SafeSQLExecutor
    from app.services.pipeline.wiring import _load_source_dict
    from app.core.db import get_db_context
    source_dict = None
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            source_dict = _load_source_dict(cur, source_id, company_id=company_id)
        finally:
            cur.close()
    if source_dict is None:
        raise RuntimeError(f"data source bulunamadı: source_id={source_id}")
    executor = SafeSQLExecutor()
    return executor, source_dict


# ─────────────────────────────────────────────────────────────
# Public
# ─────────────────────────────────────────────────────────────

def generate_for_source(
    cur,
    source_id: int,
    *,
    dialect: str = "postgresql",
    company_id: Optional[int] = None,
    max_fks: Optional[int] = None,
    skip_existing: bool = True,
    template_kinds: Optional[List[str]] = None,
) -> GenerationSummary:
    """source_id altındaki tüm FK'lar için sentetik sorgu üret-çalıştır-öğret.

    Args:
        cur: RLS scoped DictCursor (caller'da app.current_company_id + app.current_source_id)
        source_id: data_sources.id
        dialect: hedef DB lehçesi
        company_id: tenant id (audit + RLS için)
        max_fks: opsiyonel cap (None → tümü). Hızlı smoke run için.
        skip_existing: True ise daha önce başarılı çalıştırılan (FK, template) atlanır
        template_kinds: ['LOOKUP_JOIN', 'AGGREGATE_COUNT'] (None → ikisi de)

    Returns:
        GenerationSummary
    """
    _started = time.perf_counter()
    summary = GenerationSummary(source_id=source_id, dialect=dialect)
    # v3.29.2 G3: default G1 davranışını koru (LOOKUP_JOIN + AGGREGATE_COUNT).
    # Caller ister tek-FK temelli G3 kinds (STRING_AGG_DETAILS, TIME_SERIES_*,
    # WINDOW_*) ekleyebilir. Chain-only kinds bu loop'tan üretilmez.
    caller_provided_kinds = template_kinds is not None
    kinds = template_kinds or list(_DEFAULT_KINDS)
    # Render() çağrılabilir olmayan chain-only kinds'i sessizce filtrele
    kinds = [k for k in kinds if k in SINGLE_REL_KINDS]

    rels = _fetch_relationships(cur, source_id)
    if max_fks is not None:
        rels = rels[:max_fks]
    summary.total_fks = len(rels)

    if not rels:
        summary.elapsed_ms = int((time.perf_counter() - _started) * 1000)
        return summary

    # Hedef DB executor
    try:
        executor, source_dict = _build_executor(source_id, dialect, company_id)
    except Exception as e:
        summary.errors.append(f"executor_init: {e}")
        summary.elapsed_ms = int((time.perf_counter() - _started) * 1000)
        return summary

    # v3.32.0 G1.5 — Junction (N:M) bridge tablolarını topla.
    # Bir bridge tablo için tam 2 FK satırı olmalı (FROM bridge → diğer iki
    # tablo). is_junction=TRUE ve confidence_score >= 0.7 koşulu.
    junction_groups: Dict[tuple, List[Relationship]] = {}
    for rel in rels:
        if not rel.is_junction:
            continue
        conf = rel.confidence_score if rel.confidence_score is not None else 1.0
        if conf < 0.7:
            continue
        key = ((rel.from_schema or "").lower(), (rel.from_table or "").lower())
        junction_groups.setdefault(key, []).append(rel)

    # Her FK × template
    # v3.28.9 Paket C: her iterasyon SAVEPOINT ile izole edilir. Aksi halde
    # bir INSERT hatası (örn. embedding column tipi cast, FK violation)
    # PostgreSQL transaction'ı poison eder → kalan tüm iterasyonlar
    # "current transaction is aborted" alır ve sessizce başarısız olur.
    _sp_counter = 0

    def _cardinality_aware_kinds(rel_: Relationship) -> List[str]:
        """v3.32.0 G1.9 — Cardinality bilgisine göre kind listesi.

        - Caller explicit kind verdiyse o öncelikli (override).
        - 1:1 → sadece LOOKUP_JOIN (AGGREGATE_COUNT 1:1'de mantıksız).
        - 1:N / N:1 / NULL → tam liste (default).
        """
        if caller_provided_kinds:
            return list(kinds)
        cf = (rel_.cardinality_from or "").strip()
        ct = (rel_.cardinality_to or "").strip()
        if cf == "1" and ct == "1":
            return [k for k in kinds if k not in _AGGREGATE_KINDS_SKIP_ON_1TO1]
        return list(kinds)

    # v3.45.0 P2: tip-keşfi — child tablo kolonları tablo-bazında cache'lenir (aynı child
    # birden çok FK'de gelebilir → tek SELECT). col_ctx tip-bağımlı template'lere kolon sağlar.
    _col_cache: Dict[tuple, List[Dict[str, Any]]] = {}
    _table_level_done: set = set()   # (from_table, kind) → tek-tablo kind tekrarını engelle

    def _build_col_ctx(rel_: Relationship) -> Dict[str, Optional[str]]:
        """Child (rel.from) tablosundan numeric/temporal/text aday kolonları seç (cache'li).
        Hepsi opsiyonel; gereklilik kontrolü _KIND_COL_REQUIREMENTS ile yapılır."""
        ckey = ((rel_.from_schema or "").lower(), (rel_.from_table or "").lower())
        if ckey not in _col_cache:
            _col_cache[ckey] = _load_table_columns(cur, source_id, rel_.from_schema, rel_.from_table)
        cols = _col_cache[ckey]
        exclude = list(rel_.from_columns or ([rel_.from_column] if rel_.from_column else []))
        return {
            "numeric": _pick_numeric_measure(cols, exclude),
            "temporal": _pick_typed_column(cols, exclude, CAT_TEMPORAL, _TEMPORAL_NAME_HINTS),
            "text": _pick_typed_column(cols, exclude, CAT_TEXT, _TEXT_LABEL_HINTS),
        }

    for rel in rels:
        per_rel_kinds = _cardinality_aware_kinds(rel)
        # Cardinality filter sonucu kind'lar azaldıysa farkı say
        if not caller_provided_kinds and len(per_rel_kinds) < len(kinds):
            summary.skipped_cardinality += (len(kinds) - len(per_rel_kinds))
        for kind in per_rel_kinds:
            summary.total_attempts += 1
            _sp_counter += 1
            _sp_name = f"sp_fkgen_{_sp_counter}"

            try:
                cur.execute(f"SAVEPOINT {_sp_name}")
            except Exception as _sp_err:
                logger.warning("[fk_gen.savepoint] %s", _sp_err)

            if skip_existing:
                _reason = _should_skip(cur, source_id, rel.id, kind)
                if _reason == _SKIP_REASON_ALREADY_SUCCESS:
                    summary.skipped_existing += 1
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue
                if _reason == _SKIP_REASON_RECENT_FAILURE:
                    summary.skipped_recent_failure += 1
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue

            # v3.45.0 P2b: PG-only kind (takvim CTE) non-PG kaynakta atlanır (bozuk SQL üretme).
            if kind in _PG_ONLY_KINDS and dialect.lower() not in _PG_DIALECTS:
                summary.skipped_dialect += 1
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

            # v3.45.0 P2b: tek-tablo (fact-level) kind aynı fact için yalnız 1 kez (FK başına
            # tekrar execute etme — dedup zaten öğrenmede tekrarı engeller ama hedef DB yükü kalır).
            if kind in _TABLE_LEVEL_KINDS:
                _tkey = ((rel.from_schema or "").lower(), (rel.from_table or "").lower(), kind)
                if _tkey in _table_level_done:
                    summary.skipped_table_dup += 1
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue

            # v3.45.0 P2: tip-bağımlı kind'ler için kolon context'i. Gerekli kolon(lar) yoksa
            # (örn. STATS için child'da sayısal ölçü yok) RENDER ETME → skipped_no_column.
            col_ctx: Optional[Dict[str, str]] = None
            _req = _KIND_COL_REQUIREMENTS.get(kind)
            if _req:
                col_ctx = _build_col_ctx(rel)
                if any(not col_ctx.get(k) for k in _req):
                    summary.skipped_no_column += 1
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue

            # Render
            try:
                rq = render(rel, kind, dialect=dialect, col_ctx=col_ctx)
            except Exception as e:
                summary.failed_execute += 1
                if len(summary.errors) < 50:
                    summary.errors.append(f"render rel={rel.id} kind={kind}: {e}")
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

            # Execute on target DB (read-only, timeout aware)
            _exec_start = time.perf_counter()
            row_count: Optional[int] = None
            err_msg: Optional[str] = None
            try:
                res = executor.execute(rq.sql, source=source_dict, dialect=dialect)
                exec_ms = int((time.perf_counter() - _exec_start) * 1000)
                if not res.success:
                    err_msg = res.error or "execute failed"
                    summary.failed_execute += 1
                    if len(summary.errors) < 50:
                        summary.errors.append(
                            f"execute rel={rel.id} kind={kind}: {err_msg[:200]}"
                        )
                    # v3.28.9: target DB hatası metadata cur'ı bozmaz, ama audit
                    # öncesi safe — savepoint'i rollback'leme gerek yok.
                    _audit_run(cur, source_id, company_id, rel, rq,
                               success=False, row_count=None,
                               elapsed_ms=exec_ms, error_message=err_msg,
                               learned_query_id=None)
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue
                row_count = int(res.row_count or 0)
                # v3.45.0 P2b: tek-tablo kind BAŞARIYLA execute oldu → tabloyu işaretle (kardeş
                # FK'ler skipped_table_dup). İşaret execute SONRASI → transient execute hatası
                # kardeş FK denemesini bastırmaz (FIX: önce işaretleniyordu).
                if kind in _TABLE_LEVEL_KINDS:
                    _table_level_done.add(
                        ((rel.from_schema or "").lower(), (rel.from_table or "").lower(), kind)
                    )
                # v3.32.0 G1.6 — row_count > 0 enforcement.
                # Boş sonuç: tablo var, sorgu compile oluyor, ama veri yok →
                # öğretmiyoruz (kullanıcıya "0 row" bir yanıt önermek değersiz).
                # Audit yine yazılır (success=TRUE + empty marker), summary'de
                # skipped_empty sayacı artar.
                if row_count == 0:
                    summary.skipped_empty += 1
                    _audit_run(
                        cur, source_id, company_id, rel, rq,
                        success=True, row_count=0,
                        elapsed_ms=exec_ms,
                        error_message="empty_result_skipped_learn",
                        learned_query_id=None,
                    )
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue
            except Exception as e:
                exec_ms = int((time.perf_counter() - _exec_start) * 1000)
                err_msg = str(e)[:500]
                summary.failed_execute += 1
                if len(summary.errors) < 50:
                    summary.errors.append(
                        f"execute rel={rel.id} kind={kind} exception: {err_msg[:200]}"
                    )
                _audit_run(cur, source_id, company_id, rel, rq,
                           success=False, row_count=None,
                           elapsed_ms=exec_ms, error_message=err_msg,
                           learned_query_id=None)
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

            # Başarılı + row_count >= 0 → öğret (boş sonuç da öğretici: tablo var, ilişki çalışıyor)
            # v3.28.9 Paket C: learn fail durumunda success counter YANLIŞ artıyordu.
            # Artık her dalda doğru sayım + hata mesajı korunur.
            learned_id: Optional[int] = None
            learn_failed = False
            learn_err_msg: Optional[str] = None
            try:
                rec = record_successful_query(
                    cur,
                    source_id=source_id,
                    company_id=company_id,
                    question=rq.question_tr,
                    sql=rq.sql,
                    intent="synthetic_" + kind.lower(),
                    tables=rq.tables,
                    columns_meta=rq.columns_meta,
                    source="synthetic",
                    created_by_user_id=None,
                    # v3.29.2 G3
                    template_version=2 if kind in V2_KINDS else 1,
                    complexity_score=getattr(rq, "complexity_score", None) or COMPLEXITY_BY_KIND.get(kind, 1),
                    join_path=getattr(rq, "join_path", None) or rq.tables,
                )
                _st = rec.get("status")
                if _st in ("inserted", "duplicate"):
                    learned_id = rec.get("id")
                else:
                    learn_failed = True
                    learn_err_msg = (
                        f"learn rel={rel.id} kind={kind} status={_st} "
                        f"err={(rec.get('error') or rec.get('reason') or 'unknown')[:200]}"
                    )
            except Exception as e:
                learn_failed = True
                learn_err_msg = f"learn rel={rel.id} kind={kind} exception: {str(e)[:200]}"

            if learn_failed:
                summary.failed_learn += 1
                if learn_err_msg and len(summary.errors) < 50:
                    summary.errors.append(learn_err_msg)
                # v3.28.9 Paket C: record_successful_query INSERT/dedupe sırasında
                # patladığında cur'ın transaction'ı poison olabilir → audit_run
                # öncesi savepoint'e rollback et, sonra audit'i temiz txn'da çalıştır.
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                _audit_run(cur, source_id, company_id, rel, rq,
                           success=False, row_count=row_count,
                           elapsed_ms=exec_ms, error_message=learn_err_msg,
                           learned_query_id=None)
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                # ÖNEMLİ: success counter ARTMAZ — bu deneme öğretilemedi.
                continue

            # Audit (true success path)
            _audit_run(cur, source_id, company_id, rel, rq,
                       success=True, row_count=row_count,
                       elapsed_ms=exec_ms, error_message=None,
                       learned_query_id=learned_id)
            summary.success += 1
            # v3.44.0 P1: yalnız YENİ öğrenilen (inserted) sorgu few-shot'a terfi → re-run'da tekrar yok
            if _st == "inserted":
                _promote_to_few_shot(
                    cur, source_id=source_id, company_id=company_id,
                    rq=rq, kind=kind, summary=summary,
                )
            try:
                cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────
    # v3.32.0 G1.5 — Junction (N:M) template path
    # ─────────────────────────────────────────────────────────
    # Bridge tablo (is_junction=TRUE, conf>=0.7) için 2 FK satırı:
    #   junction = FK1 (bridge → side A)
    #   other_side = FK2 (bridge → side B)
    # JUNCTION_N2M template render edilir, execute + audit + learn.
    # relationship_id = min(fk1.id, fk2.id) → deterministik audit anahtarı.
    for jkey, jrels in junction_groups.items():
        if len(jrels) != 2:
            # Bridge tablonun TAM 2 FK'si olmalı; aksi halde skip
            continue
        summary.junction_attempts += 1
        # Deterministik sıra: id küçük olan junction, büyük olan other_side
        jrels_sorted = sorted(jrels, key=lambda r: r.id)
        fk1, fk2 = jrels_sorted[0], jrels_sorted[1]
        canonical_id = fk1.id

        _sp_counter += 1
        _sp_name = f"sp_fkgen_j_{_sp_counter}"
        try:
            cur.execute(f"SAVEPOINT {_sp_name}")
        except Exception as _sp_err:
            logger.warning("[fk_gen.savepoint.junction] %s", _sp_err)

        # Idempotent skip (junction için de aynı _should_skip mantığı)
        if skip_existing:
            _reason = _should_skip(cur, source_id, canonical_id, "JUNCTION_N2M")
            if _reason == _SKIP_REASON_ALREADY_SUCCESS:
                summary.skipped_existing += 1
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue
            if _reason == _SKIP_REASON_RECENT_FAILURE:
                summary.skipped_recent_failure += 1
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

        # Render
        try:
            rq = render_junction_n2m(fk1, fk2, dialect=dialect)
        except Exception as e:
            summary.failed_execute += 1
            if len(summary.errors) < 50:
                summary.errors.append(
                    f"render junction bridge={jkey} fk1={fk1.id} fk2={fk2.id}: {e}"
                )
            try:
                cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
            except Exception:
                pass
            continue

        # canonical_id audit FK key'i — Relationship.id alanını geçici override
        # etmek yerine yeni bir Relationship referansı kullanıyoruz: fk1 ZATEN
        # min id; audit _audit_run rel.id ile yazıyor.
        _exec_start = time.perf_counter()
        try:
            res = executor.execute(rq.sql, source=source_dict, dialect=dialect)
            exec_ms = int((time.perf_counter() - _exec_start) * 1000)
            if not res.success:
                err_msg = res.error or "execute failed"
                summary.failed_execute += 1
                if len(summary.errors) < 50:
                    summary.errors.append(
                        f"execute junction bridge={jkey}: {err_msg[:200]}"
                    )
                _audit_run(cur, source_id, company_id, fk1, rq,
                           success=False, row_count=None,
                           elapsed_ms=exec_ms, error_message=err_msg,
                           learned_query_id=None)
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue
            row_count = int(res.row_count or 0)
        except Exception as e:
            exec_ms = int((time.perf_counter() - _exec_start) * 1000)
            err_msg = str(e)[:500]
            summary.failed_execute += 1
            if len(summary.errors) < 50:
                summary.errors.append(
                    f"execute junction bridge={jkey} exception: {err_msg[:200]}"
                )
            _audit_run(cur, source_id, company_id, fk1, rq,
                       success=False, row_count=None,
                       elapsed_ms=exec_ms, error_message=err_msg,
                       learned_query_id=None)
            try:
                cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
            except Exception:
                pass
            continue

        # row_count=0 → skip learn
        if row_count == 0:
            summary.skipped_empty += 1
            _audit_run(cur, source_id, company_id, fk1, rq,
                       success=True, row_count=0, elapsed_ms=exec_ms,
                       error_message="empty_result_skipped_learn",
                       learned_query_id=None)
            try:
                cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
            except Exception:
                pass
            continue

        # Learn
        learned_id: Optional[int] = None
        learn_failed = False
        learn_err_msg: Optional[str] = None
        try:
            rec = record_successful_query(
                cur,
                source_id=source_id,
                company_id=company_id,
                question=rq.question_tr,
                sql=rq.sql,
                intent="synthetic_junction_n2m",
                tables=rq.tables,
                columns_meta=rq.columns_meta,
                source="synthetic",
                created_by_user_id=None,
                template_version=2,
                complexity_score=getattr(rq, "complexity_score", None) or COMPLEXITY_BY_KIND.get("JUNCTION_N2M", 3),
                join_path=getattr(rq, "join_path", None) or rq.tables,
            )
            _st = rec.get("status")
            if _st in ("inserted", "duplicate"):
                learned_id = rec.get("id")
            else:
                learn_failed = True
                learn_err_msg = (
                    f"learn junction bridge={jkey} status={_st} "
                    f"err={(rec.get('error') or rec.get('reason') or 'unknown')[:200]}"
                )
        except Exception as e:
            learn_failed = True
            learn_err_msg = f"learn junction bridge={jkey} exception: {str(e)[:200]}"

        if learn_failed:
            summary.failed_learn += 1
            if learn_err_msg and len(summary.errors) < 50:
                summary.errors.append(learn_err_msg)
            try:
                cur.execute(f"ROLLBACK TO SAVEPOINT {_sp_name}")
            except Exception:
                pass
            _audit_run(cur, source_id, company_id, fk1, rq,
                       success=False, row_count=row_count,
                       elapsed_ms=exec_ms, error_message=learn_err_msg,
                       learned_query_id=None)
            try:
                cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
            except Exception:
                pass
            continue

        _audit_run(cur, source_id, company_id, fk1, rq,
                   success=True, row_count=row_count,
                   elapsed_ms=exec_ms, error_message=None,
                   learned_query_id=learned_id)
        summary.junction_success += 1
        # v3.44.0 P1: junction sentetiği de few-shot'a terfi (yalnız yeni eklenen)
        if _st == "inserted":
            _promote_to_few_shot(
                cur, source_id=source_id, company_id=company_id,
                rq=rq, kind="JUNCTION_N2M", summary=summary,
            )
        try:
            cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
        except Exception:
            pass

    summary.elapsed_ms = int((time.perf_counter() - _started) * 1000)
    return summary


__all__ = [
    "GenerationSummary",
    "generate_for_source",
]
