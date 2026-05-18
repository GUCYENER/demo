"""
VYRA - Synthetic DB Q/SQL Pair Generator (v3.28.0 - Faz 5 G2)
==============================================================
Onaylı (admin_approved) tablolar için LLM ile Türkçe doğal dil
soru ve karşılığı çalışan SQL çiftleri üretir; üç katmanlı dedupe
uygular ve `few_shot_examples` tablosuna yazar.

Akış
----
1. `ds_table_enrichments` üzerinden onaylı tablolar listelenir.
2. Her tablo için kompakt "table card" oluşturulur (kolon listesi,
   örnek satır, FK ilişkileri) - kaynak: `ds_db_objects`,
   `ds_db_samples`, `ds_db_relationships`.
3. LLM (app.core.llm.call_llm_api) tablo kartı ile çağrılır; soru/SQL
   pair'ler JSON olarak istenir.
4. Üç katmanlı dedupe:
   - L1: Canonical SQL'in SHA256 hash'i (mevcut few_shot_examples ile)
   - L2: Soru embedding cosine benzerliği >= 0.92 ise reddet
   - L3: schema_signature Jaccard >= 0.85 + SQL hash prefix eşleşmesi
5. Günlük LLM bütçe kontrolü (settings.MAX_LLM_DAILY_BUDGET_USD).
6. Kalan pair'ler `few_shot_examples`'a INSERT edilir.

Tüm dış bağımlılıklar (LLM, EmbeddingManager) graceful-fallback'lidir:
- LLM hatası -> ilgili tablo atlanır, diğerlerine devam.
- Embedding yüklenemezse L2 dedupe pasif geçer (loglanır).

Bu modül salt synthetic veri üretir; production query execution'da
DOĞRUDAN kullanılmaz. Pipeline bu pair'leri few-shot context olarak
sql_generate node'da retrieval ile çeker (014_v3230_few_shot_examples).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Bütçe yönetimi (in-process daily counter)
# ============================================================
# Not: Multi-worker prod ortamında Redis tabanlı counter'a geçilmeli;
# bu modül CLI/admin endpoint'ten manuel tetiklendiği için worker-local
# state şimdilik yeterli.

_LLM_DAILY_BUDGET_STATE: Dict[str, Any] = {
    "date": None,
    "calls": 0,
    "estimated_cost_usd": 0.0,
}
# Kaba tahmin - gpt-4o-mini ~ $0.5/M input + $1.5/M output.
# 1 çağrı ~ 600 input + 400 output token -> ~$0.00090. Yuvarladık.
_PER_CALL_COST_USD = 0.001


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _budget_reset_if_new_day() -> None:
    today = _today_iso()
    st = _LLM_DAILY_BUDGET_STATE
    if st["date"] != today:
        st["date"] = today
        st["calls"] = 0
        st["estimated_cost_usd"] = 0.0


def _check_budget(max_daily_usd: float, n_calls_planned: int = 1) -> Tuple[bool, str]:
    _budget_reset_if_new_day()
    st = _LLM_DAILY_BUDGET_STATE
    projected = st["estimated_cost_usd"] + (n_calls_planned * _PER_CALL_COST_USD)
    if max_daily_usd > 0 and projected > max_daily_usd:
        return (
            False,
            f"daily_budget_exceeded: projected ${projected:.4f} > cap ${max_daily_usd:.4f}",
        )
    return True, "ok"


def _record_call() -> None:
    _budget_reset_if_new_day()
    st = _LLM_DAILY_BUDGET_STATE
    st["calls"] += 1
    st["estimated_cost_usd"] += _PER_CALL_COST_USD


def reset_budget_state() -> None:
    """Test/debug için bütçe sayacını sıfırlar."""
    _LLM_DAILY_BUDGET_STATE["date"] = None
    _LLM_DAILY_BUDGET_STATE["calls"] = 0
    _LLM_DAILY_BUDGET_STATE["estimated_cost_usd"] = 0.0


def get_budget_state() -> Dict[str, Any]:
    """Mevcut günlük bütçe durumunu döner (test/observability)."""
    _budget_reset_if_new_day()
    return dict(_LLM_DAILY_BUDGET_STATE)


# ============================================================
# Yardımcılar
# ============================================================

_SQL_SEMI_RE = re.compile(r"\s*;\s*$")
_SQL_WS_RE = re.compile(r"\s+")


def _canonical_sql(sql: str) -> str:
    """Whitespace+case normalize - semantiği değiştirmez."""
    s = (sql or "").strip().lower()
    s = _SQL_WS_RE.sub(" ", s)
    s = _SQL_SEMI_RE.sub("", s)
    return s


def _sql_hash(sql: str) -> str:
    return hashlib.sha256(_canonical_sql(sql).encode("utf-8")).hexdigest()


def _schema_signature(tables: List[Tuple[str, str]]) -> str:
    """Alfabetik 'schema.table,...' string."""
    parts = sorted({f"{s}.{t}" if s else t for s, t in tables if t})
    return ",".join(parts)


def _jaccard(a: str, b: str) -> float:
    sa = {x for x in (a or "").split(",") if x}
    sb = {x for x in (b or "").split(",") if x}
    if not sa and not sb:
        return 1.0
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return len(sa & sb) / union


def _cosine(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2:
        return 0.0
    n = min(len(v1), len(v2))
    if n == 0:
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for i in range(n):
        a = v1[i]
        b = v2[i]
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))


def _parse_embedding_field(raw: Any) -> Optional[List[float]]:
    """pgvector text repr veya list -> List[float]."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [float(x) for x in arr]
            except Exception:
                return None
    return None


# ============================================================
# LLM yanıt parse
# ============================================================

_VALID_INTENTS = {"lookup", "aggregate", "report", "follow_up"}


def _parse_llm_pairs(raw: str) -> List[Dict[str, str]]:
    """
    LLM çıktısından JSON array'i toleranslı şekilde çıkarır.
    Markdown fence, baş/son metni temizler. Geçersiz item'ları eler.
    """
    if not raw:
        return []
    text = raw.strip()
    # markdown fence soyma
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()
    i = text.find("[")
    j = text.rfind("]")
    if i < 0 or j <= i:
        return []
    try:
        arr = json.loads(text[i : j + 1])
    except Exception:
        return []
    out: List[Dict[str, str]] = []
    if not isinstance(arr, list):
        return []
    for it in arr:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or "").strip()
        sql = str(it.get("sql") or it.get("sql_query") or "").strip()
        intent = str(it.get("intent") or "lookup").strip().lower()
        if intent not in _VALID_INTENTS:
            intent = "lookup"
        if q and sql and len(q) >= 3 and len(sql) >= 5:
            out.append({"question": q, "sql": sql, "intent": intent})
    return out


# ============================================================
# Table card builder (kompakt LLM bağlamı)
# ============================================================

def _build_table_card(
    schema: str,
    table: str,
    bname: str,
    desc: str,
    cols: List[Dict[str, Any]],
    sample_rows: List[Dict[str, Any]],
    fks_from: List[Dict[str, Any]],
    max_cols: int = 30,
    max_sample_rows: int = 2,
) -> str:
    full = f"{schema}.{table}" if schema and schema not in ("", "public") else table
    lines = [f"TABLO: {full}"]
    if bname and bname != table:
        lines.append(f"Iş Adı: {bname}")
    if desc:
        lines.append(f"Açıklama: {desc}")
    if cols:
        pk = [c.get("name") for c in cols if c.get("is_pk") and c.get("name")]
        if pk:
            lines.append(f"Primary Key: {', '.join(pk)}")
        lines.append("Sütunlar:")
        for c in cols[:max_cols]:
            n = c.get("name") or ""
            dt = c.get("data_type") or ""
            mark = " [PK]" if c.get("is_pk") else ""
            if not n:
                continue
            lines.append(f"  - {n} ({dt}){mark}")
    if fks_from:
        lines.append("İlişkiler (FK çıkan):")
        for r in fks_from[:10]:
            lines.append(
                f"  - {r.get('from_column')} -> {r.get('to_schema')}.{r.get('to_table')}.{r.get('to_column')}"
            )
    if sample_rows:
        lines.append(f"Örnek satır(lar) (ilk {min(len(sample_rows), max_sample_rows)}):")
        for row in sample_rows[:max_sample_rows]:
            try:
                lines.append(f"  {json.dumps(row, ensure_ascii=False, default=str)[:240]}")
            except Exception:
                lines.append(f"  {str(row)[:240]}")
    return "\n".join(lines)


# ============================================================
# LLM çağrısı
# ============================================================

_LLM_SYSTEM_PROMPT_TR = (
    "Sen bir SQL örnek üretici aracısın. Verilen tek tablonun şemasından "
    "Türkçe doğal dil soru + karşılığı çalışan SQL pair'leri üret. "
    "Çıktın SADECE bir JSON array olmalı; her eleman şu şemada bir obje: "
    '{{"question": "...", "sql": "...", "intent": "lookup|aggregate|report"}}. '
    "Hedef SQL dialekti: {dialect}. SQL'ler bu tabloyu hedeflemeli ve "
    "syntactically valid olmalı. Markdown, açıklama veya kod fence kullanma."
)


def _llm_generate_batch(
    table_card: str,
    target_n: int,
    dialect: str,
    *,
    llm_func=None,
) -> List[Dict[str, str]]:
    """
    Tek bir tablo kartı için LLM'den N adet Q/SQL pair ister.
    `llm_func` test edilebilirlik için inject edilebilir.
    """
    if llm_func is None:
        from app.core.llm import call_llm_api  # geç bağlama (test mock kolaylaşır)
        llm_func = call_llm_api

    system_msg = _LLM_SYSTEM_PROMPT_TR.format(dialect=dialect)
    user_msg = (
        f"Tablo şeması:\n{table_card}\n\n"
        f"Bu tablo için {target_n} farklı soru/SQL örneği üret. "
        "Soruları çeşitli intent'lere dağıt (lookup/aggregate/report). "
        "Yalnızca JSON array döndür."
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    raw = llm_func(messages, 0.7)
    return _parse_llm_pairs(raw or "")


# ============================================================
# Main entry point
# ============================================================

def generate_db_query_pairs(
    cur,
    source_id: int,
    company_id: int,
    target_count: int = 30,
    batch_size: int = 5,
    dry_run: bool = False,
    created_by: Optional[int] = None,
    *,
    llm_func=None,
    embedding_manager=None,
    max_daily_budget_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Synthetic DB Q/SQL pair generator.

    Args:
        cur: psycopg cursor (dict-row uyumlu).
        source_id: data_sources.id
        company_id: tenant scope
        target_count: toplam pair hedefi (1-200 önerilir)
        batch_size: tablo başına LLM'den istenecek pair sayısı
        dry_run: True ise DB'ye yazmaz; üretilen pair'leri response'da döner
        created_by: kullanıcı id (audit)
        llm_func: test injection — (messages, temperature) -> str
        embedding_manager: test injection — .get_embedding(text) -> List[float]
        max_daily_budget_usd: None ise settings'ten alınır

    Returns: stats dict
    """
    # Bütçe limiti
    if max_daily_budget_usd is None:
        try:
            from app.core.config import settings
            max_daily_budget_usd = float(
                getattr(settings, "MAX_LLM_DAILY_BUDGET_USD", 1.0) or 1.0
            )
        except Exception:
            max_daily_budget_usd = 1.0

    stats = {
        "success": False,
        "generated": 0,
        "inserted": 0,
        "skipped_l1_sql_hash": 0,
        "skipped_l2_embedding": 0,
        "skipped_l3_schema_sig": 0,
        "llm_errors": 0,
        "llm_calls_used": 0,
        "estimated_cost_usd": 0.0,
        "budget_cap_usd": max_daily_budget_usd,
        "dialect": "postgresql",
        "tables_processed": 0,
        "dry_run": dry_run,
    }

    # 1) Onaylı tablolar
    cur.execute(
        """
        SELECT te.id AS te_id, te.schema_name, te.table_name,
               te.admin_label_tr, te.business_name_tr, te.description_tr
        FROM ds_table_enrichments te
        WHERE te.source_id = %s AND te.is_active = TRUE AND te.admin_approved = TRUE
        ORDER BY te.table_name
        """,
        (source_id,),
    )
    approved = cur.fetchall() or []
    if not approved:
        stats["error"] = "no_approved_tables"
        return stats

    approved_names = [r["table_name"] for r in approved]

    # 2) Dialect tespiti
    try:
        cur.execute("SELECT db_type FROM data_sources WHERE id = %s", (source_id,))
        src_row = cur.fetchone()
        dialect = ((src_row or {}).get("db_type") or "postgresql").lower()
    except Exception:
        dialect = "postgresql"
    if dialect not in ("postgresql", "mysql", "mssql", "oracle"):
        dialect = "postgresql"
    stats["dialect"] = dialect

    # 3) Kolon + örnek + FK haritaları
    cur.execute(
        """
        SELECT schema_name, object_name, columns_json
        FROM ds_db_objects
        WHERE source_id = %s AND object_type = 'table'
        """,
        (source_id,),
    )
    obj_map: Dict[Tuple[str, str], Dict[str, Any]] = {
        (r["schema_name"] or "", r["object_name"]): r for r in (cur.fetchall() or [])
    }

    samples_by_table: Dict[str, List[Dict[str, Any]]] = {}
    if approved_names:
        ph = ",".join(["%s"] * len(approved_names))
        try:
            cur.execute(
                f"""
                SELECT o.object_name, s.sample_data
                FROM ds_db_samples s
                JOIN ds_db_objects o ON s.object_id = o.id
                WHERE s.source_id = %s AND o.object_name IN ({ph})
                """,
                [source_id] + approved_names,
            )
            for r in cur.fetchall() or []:
                sd = r["sample_data"]
                if isinstance(sd, str):
                    try:
                        sd = json.loads(sd)
                    except Exception:
                        sd = []
                samples_by_table[r["object_name"]] = sd if isinstance(sd, list) else []
        except Exception as e:
            logger.warning("[SyntheticQ] sample sorgusu hata: %s", e)

    try:
        cur.execute(
            """
            SELECT from_schema, from_table, from_column,
                   to_schema, to_table, to_column
            FROM ds_db_relationships
            WHERE source_id = %s
            """,
            (source_id,),
        )
        fks_all = list(cur.fetchall() or [])
    except Exception as e:
        logger.warning("[SyntheticQ] FK sorgusu hata: %s", e)
        fks_all = []

    # 4) Mevcut few_shot_examples (dedupe için)
    try:
        cur.execute(
            """
            SELECT id, question, sql_query, intent, schema_signature, embedding
            FROM few_shot_examples
            WHERE company_id = %s
              AND (source_id IS NULL OR source_id = %s)
            """,
            (company_id, source_id),
        )
        existing = list(cur.fetchall() or [])
    except Exception as e:
        logger.warning("[SyntheticQ] mevcut few-shot okuma hata: %s", e)
        existing = []

    existing_hashes = {_sql_hash(r["sql_query"]) for r in existing if r.get("sql_query")}
    existing_embs: List[Dict[str, Any]] = []
    for r in existing:
        emb = _parse_embedding_field(r.get("embedding"))
        if emb:
            existing_embs.append({"emb": emb, "sig": r.get("schema_signature") or ""})

    # 5) Embedding manager
    emb_mgr = embedding_manager
    if emb_mgr is None:
        try:
            from app.services.rag.embedding import EmbeddingManager
            emb_mgr = EmbeddingManager()
        except Exception as e:
            logger.warning("[SyntheticQ] EmbeddingManager yüklenemedi; L2 dedupe pasif: %s", e)
            emb_mgr = None

    # 6) Tablo bazında LLM üret + dedupe
    per_table = max(1, target_count // max(1, len(approved)))
    per_table = min(per_table, batch_size)

    generated: List[Dict[str, Any]] = []
    pairs_to_insert: List[Dict[str, Any]] = []

    for tab in approved:
        if len(generated) >= target_count:
            break

        ok, msg = _check_budget(max_daily_budget_usd, n_calls_planned=1)
        if not ok:
            logger.warning("[SyntheticQ] %s", msg)
            stats["error"] = msg
            break

        schema = tab["schema_name"] or ""
        tname = tab["table_name"]
        bname = (tab.get("admin_label_tr") or tab.get("business_name_tr") or tname)
        desc = tab.get("description_tr") or ""

        # Kolon listesi
        obj = (
            obj_map.get((schema, tname))
            or obj_map.get(("", tname))
            or obj_map.get(("public", tname))
        )
        cols: List[Dict[str, Any]] = []
        if obj:
            cr = obj.get("columns_json")
            if isinstance(cr, str):
                try:
                    cols = json.loads(cr) or []
                except Exception:
                    cols = []
            elif isinstance(cr, list):
                cols = cr

        sample = samples_by_table.get(tname, [])
        fks_from = [r for r in fks_all if r.get("from_table") == tname]

        card = _build_table_card(schema, tname, bname, desc, cols, sample, fks_from)

        try:
            _record_call()
            stats["llm_calls_used"] += 1
            pairs = _llm_generate_batch(card, per_table, dialect, llm_func=llm_func)
        except Exception as e:
            stats["llm_errors"] += 1
            logger.warning("[SyntheticQ] LLM hata (%s.%s): %s", schema, tname, e)
            continue

        stats["tables_processed"] += 1
        sig = _schema_signature([(schema, tname)])

        for p in pairs:
            if len(generated) >= target_count:
                break
            sql = p["sql"]
            q = p["question"]
            intent = p["intent"]

            # L1 — SHA256
            h = _sql_hash(sql)
            if h in existing_hashes:
                stats["skipped_l1_sql_hash"] += 1
                continue

            # L2 — embedding cosine
            emb = None
            if emb_mgr is not None:
                try:
                    emb = emb_mgr.get_embedding(q)
                    if emb is not None and not isinstance(emb, list):
                        emb = list(emb)
                except Exception as e:
                    logger.debug("[SyntheticQ] embedding hata: %s", e)
                    emb = None
            if emb and existing_embs:
                dup_l2 = False
                for ex in existing_embs:
                    if _cosine(emb, ex["emb"]) >= 0.92:
                        dup_l2 = True
                        break
                if dup_l2:
                    stats["skipped_l2_embedding"] += 1
                    continue

            # L3 — schema_signature Jaccard + SQL prefix
            dup_l3 = False
            h_prefix = h[:12]
            for ex in existing:
                ex_sig = ex.get("schema_signature") or ""
                if not ex_sig:
                    continue
                if _jaccard(sig, ex_sig) >= 0.85:
                    ex_hash = _sql_hash(ex.get("sql_query") or "")
                    if ex_hash[:12] == h_prefix:
                        dup_l3 = True
                        break
            if dup_l3:
                stats["skipped_l3_schema_sig"] += 1
                continue

            existing_hashes.add(h)
            if emb:
                existing_embs.append({"emb": emb, "sig": sig})

            pair = {
                "question": q,
                "sql_query": sql,
                "intent": intent,
                "schema_signature": sig,
                "embedding": emb,
            }
            generated.append(pair)
            pairs_to_insert.append(pair)

    # 7) Insert
    inserted = 0
    if not dry_run and pairs_to_insert:
        for g in pairs_to_insert:
            try:
                cur.execute(
                    """
                    INSERT INTO few_shot_examples
                        (company_id, source_id, question, sql_query, intent,
                         schema_signature, embedding, usage_count, success_rate, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 1.0, %s)
                    """,
                    (
                        company_id,
                        source_id,
                        g["question"],
                        g["sql_query"],
                        g["intent"],
                        g["schema_signature"],
                        g["embedding"],
                        created_by,
                    ),
                )
                inserted += 1
            except Exception as e:
                logger.warning("[SyntheticQ] insert hata: %s", e)

    stats["success"] = True
    stats["generated"] = len(generated)
    stats["inserted"] = inserted
    stats["estimated_cost_usd"] = round(
        _LLM_DAILY_BUDGET_STATE.get("estimated_cost_usd", 0.0), 6
    )
    if dry_run:
        # dry_run'da embedding hariç pair listesi response'a eklenir
        stats["pairs"] = [
            {k: v for k, v in p.items() if k != "embedding"} for p in generated
        ]
    return stats
