"""v3.29.9 — FK Inference Service (dialect-agnostic core).

Inference layer for databases that do NOT declare FK constraints at the DB
level (common with ORM/app-layer enforcement, e.g. OnedeskTest with 2138
tables and only 29 declared FKs).

Pipeline:
    1. Load discovered tables/columns from ds_db_objects.
    2. For each non-PK column matching naming pattern (`*_id`, `*Id`, `id_*`,
       `f_*_id`), parse a "root" → candidate target table name(s).
    3. Validate type compatibility (INT↔INT/BIGINT, UUID↔UUID, ...).
    4. (Optional) Sample-validate: query LEFT JOIN coverage on a bounded
       sample to confirm referential plausibility.
    5. Score: 0.6 naming + 0.2 type + up to 0.2 sample coverage.
    6. UPSERT into ds_db_relationships with is_inferred=TRUE,
       admin_verified=FALSE.

Public API:
    - infer_fks_for_source(cur, source_id, *, sample_validate, sample_rows,
        min_confidence, dialect) -> Dict[str, Any]

RLS: caller must apply company scope BEFORE invoking.
SECURITY: Identifiers used in sample validation SQL are guarded by
`is_safe_identifier` from `fk_inference_dialects`; non-conforming names
cause that candidate to be skipped (logged at INFO).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.services.db_learning.fk_inference_dialects import (
    FKInferenceDialect,
    get_dialect,
    is_safe_identifier,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Scoring weights
# ─────────────────────────────────────────────────────────────
SCORE_NAMING = 0.60       # full-root tablo eşleşmesi (user_id → users)
SCORE_NAMING_HEAD = 0.45  # v3.60.0: head-noun (rol-önekli) eşleşme (CreateUserId → user) — daha spekülatif,
                          # tek başına min_confidence(0.60) altında kalır → ancak tip uyumuyla (0.45+0.20=0.65) persist
SCORE_TYPE = 0.20
SCORE_SAMPLE_MAX = 0.20  # multiplied by coverage_ratio

DEFAULT_MIN_CONFIDENCE = 0.60   # below this we skip persisting
DEFAULT_SAMPLE_ROWS = 200
DEFAULT_PK_COL_NAMES = ("id", "pk", "uuid")


# ─────────────────────────────────────────────────────────────
# Naming pattern parser
# ─────────────────────────────────────────────────────────────
# Patterns (case-insensitive, applied to normalized ident):
#   suffix _id        → user_id     → root='user'
#   suffix _ref       → owner_ref   → root='owner' (cardinality hint)
#   suffix Id         → userId      → root='user' (CamelCase)
#   prefix id_        → id_user     → root='user'
#   f_<root>_id       → f_user_id   → root='user'  (Hungarian)
# v3.60.0: Unicode (re.UNICODE) → Türkçe kolon adları (müşteri_id, sipariş_ref) yakalanır.
# [^\W\d_] = bir Unicode HARF (ç/ğ/ı/ö/ş/ü dahil); \w = harf/rakam/_ (Unicode). Eski [a-z] Türkçe'yi atıyordu.
_NAMING_RES = [
    re.compile(r"^f_(?P<root>[^\W\d_][\w]*?)_id$", re.UNICODE),
    re.compile(r"^id_(?P<root>[^\W\d_][\w]*)$", re.UNICODE),
    re.compile(r"^(?P<root>[^\W\d_][\w]*?)_id$", re.UNICODE),
    re.compile(r"^(?P<root>[^\W\d_][\w]*?)_ref$", re.UNICODE),
]
# CamelCase / ayraçsız ID — ORIJİNAL ad üzerinde (normalize ÖNCESİ). v3.60.0: [Ii][Dd] → Id/ID/iD/id
# (eski yalnız 'Id'; ALL-CAPS PARTYID + ayraçsız userid kaçıyordu). Unicode → MüşteriId yakalanır.
# [^\W\d_] = Unicode harf, [\w] underscore içerir ama '_id' zaten _NAMING_RES'te (bu AYRAÇSIZ son-ek içindir).
_CAMEL_ID_RE = re.compile(r"^(?P<root>[^\W\d_][^\W_]*?)[Ii][Dd]$", re.UNICODE)

# v3.60.0: CamelCase/PascalCase sınırı (büyük harf öncesi) — Türkçe büyükler dahil.
# Head-noun (son anlamlı entity token) çıkarımı için: 'CreateUser'→['Create','User'], son='User'.
_CAMEL_SPLIT_RE = re.compile(r"(?<=.)(?=[A-ZÇĞİÖŞÜ])", re.UNICODE)
# FK son-ekini ORİJİNAL adtan at (camel 'Id' / snake '_id' / caps 'ID' / 'ref'/'fk'); Unicode.
_FK_SUFFIX_STRIP_RE = re.compile(r"(?:[_\s]?(?:[Ii][Dd]|[Rr][Ee][Ff]|[Ff][Kk]))$", re.UNICODE)


def _head_noun_from_name(col_name: str) -> Optional[str]:
    """v3.60.0: rol-önekli/bileşik FK kolonundan HEAD-NOUN (gerçek hedef entity) çıkar.

    'CreateUserId'→'user', 'PADCompanyId'→'company', 'create_user_id'→'user',
    'ParentPartyId'→'party', 'MüşteriId'→'müşteri'. Hedef tablo genelde son anlamlı token'dır
    (önek = rol/sıfat: Create/Modify/Parent/PAD...). Döndürülen lower; PK adıysa None.
    """
    raw = (col_name or "").strip()
    if not raw:
        return None
    stem = _FK_SUFFIX_STRIP_RE.sub("", raw).strip(" _-./")
    if not stem:
        return None
    pieces = [p for p in re.split(r"[\s_\-./]+", stem) if p]
    if not pieces:
        return None
    last_piece = pieces[-1]
    # All-caps (PARTYID) veya all-lower (party): camelCase sınırı yok → bütün parça.
    # Yalnız KARIŞIK kasa (PADCompany, CreateUser) camelCase-bölünür → son entity ('Company','User').
    # Aksi halde 'PARTY' → P|A|R|T|Y → 'y' gibi yanlış token üretirdi.
    if last_piece.upper() == last_piece or last_piece.lower() == last_piece:
        tok = last_piece.lower()
    else:
        camel = [w for w in _CAMEL_SPLIT_RE.split(last_piece) if w]
        tok = (camel[-1] if camel else last_piece).lower()
    if not tok or tok in DEFAULT_PK_COL_NAMES:
        return None
    return tok

# v3.60.0: tanılama amaçlı — kolon adı bir referans/FK'ya benziyor mu (kalıba uymasa bile)?
# 'PARTYID'/'STATUS_CODE'/'OWNERREF' gibi adları Hata İzleme'de yüzeye çıkarmak için (kök neden).
_REF_ISH_SUFFIXES = ("id", "ref", "code", "key", "no", "fk")


def _looks_reference_ish(col_name: str) -> bool:
    low = (col_name or "").strip().lower()
    if not low or low in DEFAULT_PK_COL_NAMES:
        return False
    return low.endswith(_REF_ISH_SUFFIXES)


def _extract_root(col_name: str) -> Optional[str]:
    """Extract candidate target-table root from FK column name.

    Returns the root (lowercase) on success; None if no pattern matches or
    the column is a PK column itself (e.g. just `id` or `pk`).
    """
    if not col_name:
        return None
    raw = col_name.strip()
    if not raw:
        return None

    # PK column itself — skip.
    low = raw.lower()
    if low in DEFAULT_PK_COL_NAMES:
        return None

    # Try CamelCase first on original casing.
    cm = _CAMEL_ID_RE.match(raw)
    if cm:
        root = cm.group("root")
        if root and root.lower() not in DEFAULT_PK_COL_NAMES:
            return root.lower()

    # Then snake_case / prefix patterns on lowercased.
    for rx in _NAMING_RES:
        m = rx.match(low)
        if m:
            root = m.group("root")
            if root and root not in DEFAULT_PK_COL_NAMES:
                return root
    return None


# ─────────────────────────────────────────────────────────────
# Singular/plural normalization
# ─────────────────────────────────────────────────────────────
def _candidates_from_root(root: str) -> List[str]:
    """Produce plausible target table names from a root.

    e.g. root='user' → ['user', 'users']
         root='party' → ['party', 'parties']
         root='category' → ['category', 'categories']
    """
    if not root:
        return []
    out = [root]
    # naive plural rules
    if root.endswith("y") and len(root) > 1 and root[-2] not in "aeiou":
        out.append(root[:-1] + "ies")
    elif root.endswith(("s", "x", "z", "ch", "sh")):
        out.append(root + "es")
    else:
        out.append(root + "s")
    # also single-trim if root already plural (best-effort)
    if root.endswith("s") and len(root) > 1:
        out.append(root[:-1])
    # dedupe preserving order
    seen: Set[str] = set()
    uniq: List[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


# ─────────────────────────────────────────────────────────────
# Type compatibility
# ─────────────────────────────────────────────────────────────
def _type_compatible(t_from: str, t_to: str, dialect: FKInferenceDialect) -> bool:
    """Compare normalized type categories."""
    nf = dialect.normalize_type(t_from or "")
    nt = dialect.normalize_type(t_to or "")
    if nf == "other" or nt == "other":
        return False
    return nf == nt


# ─────────────────────────────────────────────────────────────
# Schema loader
# ─────────────────────────────────────────────────────────────
@dataclass
class _TableInfo:
    schema: str
    name: str
    norm_name: str        # dialect-normalized for matching
    columns: List[Dict[str, Any]] = field(default_factory=list)
    pk_columns: List[str] = field(default_factory=list)


def _load_schema(
    cur,
    source_id: int,
    dialect: FKInferenceDialect,
) -> Dict[Tuple[str, str], _TableInfo]:
    """Read ds_db_objects → dict keyed by (norm_schema, norm_name)."""
    cur.execute(
        """
        SELECT schema_name, object_name, object_type, columns_json
          FROM ds_db_objects
         WHERE source_id = %s
           AND object_type IN ('table','TABLE','view','VIEW')
        """,
        (source_id,),
    )
    rows = cur.fetchall()
    out: Dict[Tuple[str, str], _TableInfo] = {}
    for r in rows:
        # support both tuple and dict row factories
        if isinstance(r, dict):
            schema = r["schema_name"]
            name = r["object_name"]
            cols_raw = r["columns_json"]
        else:
            schema, name, _otype, cols_raw = r[0], r[1], r[2], r[3]
        try:
            cols = cols_raw if isinstance(cols_raw, list) else json.loads(cols_raw or "[]")
        except Exception:
            cols = []
        pk_cols: List[str] = []
        for c in cols:
            # v3.56.0 KÖK fix: detect_objects columns_json'a `is_pk` yazıyor (ds_learning_service);
            # burada `is_primary_key` okunuyordu → pk_cols HEP BOŞ → inference hedef PK'yı 'id'ye
            # düşürüp XxxId PK'lı şemalarda candidate üretemiyordu. is_pk öncelik + eski key fallback.
            if isinstance(c, dict) and (c.get("is_pk") or c.get("is_primary_key")):
                pk_cols.append(c.get("name", ""))
        ns = dialect.normalize_ident(schema)
        nn = dialect.normalize_ident(name)
        out[(ns, nn)] = _TableInfo(
            schema=schema,
            name=name,
            norm_name=nn,
            columns=cols,
            pk_columns=pk_cols,
        )
    return out


def _load_existing_relationships(
    cur,
    source_id: int,
    dialect: FKInferenceDialect,
) -> Set[Tuple[str, str, str, str, str, str]]:
    """Active (not rejected) rels — used to skip duplicates."""
    cur.execute(
        """
        SELECT from_schema, from_table, from_column,
               to_schema, to_table, to_column
          FROM ds_db_relationships
         WHERE source_id = %s
           AND (rejected_at IS NULL)
        """,
        (source_id,),
    )
    out: Set[Tuple[str, str, str, str, str, str]] = set()
    for r in cur.fetchall():
        if isinstance(r, dict):
            key = (
                dialect.normalize_ident(r["from_schema"] or ""),
                dialect.normalize_ident(r["from_table"] or ""),
                dialect.normalize_ident(r["from_column"] or ""),
                dialect.normalize_ident(r["to_schema"] or ""),
                dialect.normalize_ident(r["to_table"] or ""),
                dialect.normalize_ident(r["to_column"] or ""),
            )
        else:
            key = (
                dialect.normalize_ident(r[0] or ""),
                dialect.normalize_ident(r[1] or ""),
                dialect.normalize_ident(r[2] or ""),
                dialect.normalize_ident(r[3] or ""),
                dialect.normalize_ident(r[4] or ""),
                dialect.normalize_ident(r[5] or ""),
            )
        out.add(key)
    return out


# ─────────────────────────────────────────────────────────────
# Sample validation
# ─────────────────────────────────────────────────────────────
def _validate_sample(
    cur,
    from_schema: str,
    from_table: str,
    from_column: str,
    to_schema: str,
    to_table: str,
    to_column: str,
    sample_rows: int,
    dialect: FKInferenceDialect,
) -> Optional[Dict[str, Any]]:
    """Run dialect-built coverage probe. Returns dict or None on error/skip.

    Caller must wrap this with try/except — sample validation MUST NOT
    block FK inference; failures are logged and the candidate falls back
    to naming+type only.
    """
    for ident in (from_schema, from_table, from_column, to_schema, to_table, to_column):
        if not is_safe_identifier(ident):
            logger.info(
                "[fk_inference] unsafe ident, skipping sample validation: %r",
                ident,
            )
            return None
    sql, params = dialect.build_sample_validate_sql(
        from_schema, from_table, from_column,
        to_schema, to_table, to_column,
        sample_rows,
    )
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
    except Exception as e:
        logger.info(
            "[fk_inference] sample validate failed %s.%s.%s→%s.%s.%s: %s",
            from_schema, from_table, from_column, to_schema, to_table, to_column,
            str(e)[:200],
        )
        return None
    if not row:
        return None
    if isinstance(row, dict):
        distinct_from = int(row.get("distinct_from", 0) or 0)
        covered = int(row.get("covered", 0) or 0)
    else:
        distinct_from = int(row[0] or 0)
        covered = int(row[1] or 0)
    ratio = (covered / distinct_from) if distinct_from > 0 else 0.0
    return {
        "distinct_from": distinct_from,
        "covered": covered,
        "coverage_ratio": round(ratio, 4),
        "sample_size": sample_rows,
    }


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
@dataclass
class _Candidate:
    from_schema: str
    from_table: str
    from_column: str
    from_type: str
    to_schema: str
    to_table: str
    to_column: str
    to_type: str
    naming_pattern: str   # the regex pattern that matched
    root: str
    confidence: float
    evidence: Dict[str, Any]
    method: str           # 'naming' | 'naming+type' | 'naming+type+sample'


def _column_dict(t: _TableInfo, name_lower: str, dialect: FKInferenceDialect) -> Optional[Dict[str, Any]]:
    for c in t.columns:
        if isinstance(c, dict) and dialect.normalize_ident(c.get("name", "")) == name_lower:
            return c
    return None


def _iter_fk_candidates(
    tables: Dict[Tuple[str, str], _TableInfo],
    dialect: FKInferenceDialect,
    diag: Optional[List[Dict[str, Any]]] = None,
) -> Iterable[Tuple[_TableInfo, Dict[str, Any], str, str, _TableInfo, Dict[str, Any]]]:
    """Yield (from_table, from_col, root, pattern_name, to_table, to_col).

    Iterates every non-PK column across all tables, parses naming pattern,
    and emits potential targets via singular/plural matching against
    other tables in the source.

    v3.60.0: `diag` verilirse, FK üretilemeyen "yakın-ıska" kolonlar (root çıkmadı ama
    referans-benzeri / hedef tablo bulunamadı / hedef PK yok) tablo+şema+kolon+sebep ile
    kaydedilir → çağıran bunları Hata İzleme'ye tablo-aranabilir şekilde yazar (kök neden).
    """
    # Build name → list[_TableInfo] index for fast plural/singular lookup.
    by_norm_name: Dict[str, List[_TableInfo]] = {}
    # v3.56.0 KÖK fix: PREFIX-TOLERANT eşleştirme. Kurumsal şemalar tabloları modül prefix'iyle
    # adlandırır (T_WF_INSTANCE, T_ORG_USER). Eski kod root'u TAM ada eşliyordu → "instance" ≠
    # "t_wf_instance" → candidate üretmiyordu (FK İLİŞKİLERİ ~0). Son "_"-token indeksi: norm_name'in
    # son token'ı → tablo ("t_wf_instance"→"instance", "t_org_user"→"user"). Exact match ÖNCE,
    # son-token fallback SONRA (false-positive confidence + admin_verified ile sınırlı).
    by_last_token: Dict[str, List[_TableInfo]] = {}
    for t in tables.values():
        by_norm_name.setdefault(t.norm_name, []).append(t)
        _toks = [x for x in str(t.norm_name).split("_") if x]
        if len(_toks) > 1:
            by_last_token.setdefault(_toks[-1], []).append(t)

    for t in tables.values():
        for col in t.columns:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name") or ""
            if not col_name:
                continue
            # Skip PKs (auto-generated id columns aren't FKs to themselves).
            # v3.56.0: is_pk öncelik (columns_json key'i), is_primary_key eski-fallback.
            if col.get("is_pk") or col.get("is_primary_key"):
                continue
            root = _extract_root(col_name)
            if not root:
                # Tanılama: kalıba uymadı ama referans-benzeri (PARTYID/STATUS_CODE) → kaydet.
                if diag is not None and _looks_reference_ish(col_name):
                    diag.append({
                        "schema": t.schema, "table": t.name, "column": col_name,
                        "reason": "no_pattern_match",
                        "hint": "kolon adı FK kalıbına uymadı (_id/Id/_ref vb. çıkarılamadı)",
                    })
                continue
            # Aday hedef tablo adları — ÖNCE full root (yüksek güven), SONRA head-noun (rol-önekli, düşük güven).
            # v3.60.0: 'CreateUserId' root='createuser' (hiçbir tabloya uymaz) ama head='user' → T_ORG_USER.
            head = _head_noun_from_name(col_name)
            name_cands: List[Tuple[str, str]] = [(c, "full") for c in _candidates_from_root(root)]
            if head and head != root:
                for c in _candidates_from_root(head):
                    name_cands.append((c, "head"))

            target_tbl: Optional[_TableInfo] = None
            match_kind = "full"
            for cand, kind in name_cands:
                cand_norm = dialect.normalize_ident(cand)
                # Exact ad eşleşmesi öncelikli; yoksa prefix-tolerant son-token eşleşmesi.
                hits = by_norm_name.get(cand_norm) or by_last_token.get(cand_norm)
                if not hits:
                    continue
                # Prefer same schema if multiple.
                same_schema = [h for h in hits if dialect.normalize_ident(h.schema) == dialect.normalize_ident(t.schema)]
                # v3.56.0 code-review: birden çok aday (özellikle son-token çakışması) →
                # norm_name'e göre DETERMİNİSTİK seç (dict-iterasyon sırasına bağlı kalma →
                # re-keşif idempotent, aynı inferred FK üretilir).
                cand_tbl = sorted(same_schema or hits, key=lambda h: h.norm_name)[0]
                # Self-FK head eşleşmesi gürültüsünü ele: head 'user' + tablo kendisi T_ORG_USER ise
                # (kolon kendi tablosunun head'i) gerçek FK değil; full root self-FK'ya izin verir (parent_id).
                if kind == "head" and dialect.normalize_ident(cand_tbl.name) == dialect.normalize_ident(t.name):
                    continue
                target_tbl = cand_tbl
                match_kind = kind
                break
            if target_tbl is None:
                # Tanılama: root/head çıktı ama hedef tablo bulunamadı (prefix/adlandırma uyumsuzluğu).
                if diag is not None:
                    diag.append({
                        "schema": t.schema, "table": t.name, "column": col_name,
                        "root": root, "head": head, "reason": "no_target_table",
                        "tried": [c for c, _ in name_cands],
                        "hint": "root/head'den üretilen aday tablo adları hiçbir tabloya (tam/son-token) eşleşmedi",
                    })
                continue
            # Self-FK is allowed (org chart parent_id → org.id).
            # Find target PK column.
            if not target_tbl.pk_columns:
                # No PK declared in metadata; fall back to convention 'id'.
                target_pk_name = "id"
            else:
                target_pk_name = target_tbl.pk_columns[0]
            target_col = _column_dict(target_tbl, dialect.normalize_ident(target_pk_name), dialect)
            if target_col is None:
                # Tanılama: hedef tablo bulundu ama PK kolonu metadata'da yok (columns_json/is_pk eksik).
                if diag is not None:
                    diag.append({
                        "schema": t.schema, "table": t.name, "column": col_name,
                        "root": root, "reason": "target_pk_not_found",
                        "target": f"{target_tbl.schema}.{target_tbl.name}",
                        "target_pk_tried": target_pk_name,
                        "hint": "hedef tablonun PK kolonu metadata'da yok → eşleştirilemedi",
                    })
                continue
            yield t, col, root, match_kind, target_tbl, target_col


def _score(
    match_kind: str,
    type_ok: bool,
    sample_info: Optional[Dict[str, Any]],
) -> Tuple[float, str]:
    # v3.60.0: head-noun eşleşmesi (rol-önekli) full root'tan daha spekülatif → daha düşük taban.
    base = SCORE_NAMING if match_kind != "head" else SCORE_NAMING_HEAD
    score = base
    method = f"naming:{match_kind}"
    if type_ok:
        score += SCORE_TYPE
        method = f"naming:{match_kind}+type"
    if sample_info is not None:
        score += SCORE_SAMPLE_MAX * float(sample_info.get("coverage_ratio", 0.0))
        method = f"naming:{match_kind}+type+sample" if type_ok else f"naming:{match_kind}+sample"
    if score > 1.0:
        score = 1.0
    return round(score, 4), method


def infer_fks_for_source(
    cur,
    source_id: int,
    *,
    sample_validate: bool = False,
    sample_rows: int = DEFAULT_SAMPLE_ROWS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    dialect: str | None = None,
    target_cur=None,
) -> Dict[str, Any]:
    """Infer FKs and UPSERT inferred rows.

    Args:
        cur: VYRA DB cursor (reads ds_db_objects, writes ds_db_relationships).
            RLS scope already applied.
        source_id: data source row id.
        sample_validate: if True, run coverage probe via `target_cur`.
        sample_rows: cap on distinct FK values probed.
        min_confidence: candidates below this score are dropped (not persisted).
        dialect: 'postgresql' | 'oracle' | 'mssql' | 'mysql' (None → PG default).
        target_cur: cursor against the TARGET database (where the user's
            data lives). Required when sample_validate=True. Must be a
            short-lived cursor with statement_timeout already applied by
            the caller.

    Returns:
        dict with counts and a list of inferred rows (capped at 200 for
        observability).
    """
    d = get_dialect(dialect or "postgresql")
    tables = _load_schema(cur, source_id, d)
    if not tables:
        return {
            "source_id": source_id,
            "dialect": d.name,
            "tables_scanned": 0,
            "candidates": 0,
            "persisted": 0,
            "skipped_existing": 0,
            "skipped_low_confidence": 0,
            "unresolved_count": 0,
            "unresolved": [],
            "sample": [],
        }

    existing = _load_existing_relationships(cur, source_id, d)
    candidates: List[_Candidate] = []
    unresolved: List[Dict[str, Any]] = []  # v3.60.0: FK üretilemeyen yakın-ıska kolonlar (tanılama)
    skipped_existing = 0
    for t_from, col_from, root, pattern, t_to, col_to in _iter_fk_candidates(tables, d, diag=unresolved):
        from_schema = t_from.schema
        from_table = t_from.name
        from_col = col_from.get("name") or ""
        to_schema = t_to.schema
        to_table = t_to.name
        to_col = col_to.get("name") or ""
        key = (
            d.normalize_ident(from_schema),
            d.normalize_ident(from_table),
            d.normalize_ident(from_col),
            d.normalize_ident(to_schema),
            d.normalize_ident(to_table),
            d.normalize_ident(to_col),
        )
        if key in existing:
            skipped_existing += 1
            continue
        from_type = col_from.get("type") or col_from.get("data_type") or ""
        to_type = col_to.get("type") or col_to.get("data_type") or ""
        type_ok = _type_compatible(from_type, to_type, d)

        sample_info: Optional[Dict[str, Any]] = None
        if sample_validate and target_cur is not None and type_ok:
            sample_info = _validate_sample(
                target_cur,
                from_schema, from_table, from_col,
                to_schema, to_table, to_col,
                sample_rows, d,
            )

        score, method = _score(pattern, type_ok, sample_info)
        evidence = {
            "naming_pattern": pattern,
            "match_kind": pattern,
            "root": root,
            "from_type": from_type,
            "to_type": to_type,
            "type_match": type_ok,
        }
        if sample_info is not None:
            evidence["sample"] = sample_info
        candidates.append(_Candidate(
            from_schema=from_schema, from_table=from_table, from_column=from_col,
            from_type=from_type,
            to_schema=to_schema, to_table=to_table, to_column=to_col,
            to_type=to_type,
            naming_pattern=pattern, root=root,
            confidence=score, evidence=evidence, method=method,
        ))

    # Persist
    persisted = 0
    skipped_low = 0
    sample_out: List[Dict[str, Any]] = []
    for c in candidates:
        if c.confidence < min_confidence:
            skipped_low += 1
            continue
        try:
            cur.execute(
                """
                INSERT INTO ds_db_relationships
                    (source_id, from_schema, from_table, from_column,
                     to_schema, to_table, to_column, constraint_name,
                     is_inferred, inference_method, evidence_json,
                     admin_verified, confidence_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        TRUE, %s, %s::jsonb, FALSE, %s)
                """,
                (
                    source_id, c.from_schema, c.from_table, c.from_column,
                    c.to_schema, c.to_table, c.to_column,
                    f"inferred_{c.from_table}_{c.from_column}",
                    c.method, json.dumps(c.evidence), c.confidence,
                ),
            )
            persisted += 1
            if len(sample_out) < 200:
                sample_out.append({
                    "from": f"{c.from_schema}.{c.from_table}.{c.from_column}",
                    "to": f"{c.to_schema}.{c.to_table}.{c.to_column}",
                    "method": c.method,
                    "confidence": c.confidence,
                })
        except Exception as e:
            # v3.60.0: persist hatası system_logs'a (Hata İzleme) tablo-aranabilir şekilde — eskiden
            # yalnız logger.warning idi (UI'da görünmüyordu). Şifre/hassas veri yok; tablo+kolon bağlamı.
            try:
                from app.services.logging_service import log_exception
                log_exception(
                    e, module="fk_inference.persist",
                    context={
                        "source_id": source_id, "dialect": d.name,
                        "schema": c.from_schema, "table": c.from_table,
                        "column": c.from_column,
                        "to_table": f"{c.to_schema}.{c.to_table}",
                    },
                )
            except Exception:
                logger.warning(
                    "[fk_inference] persist failed for %s.%s.%s: %s",
                    c.from_schema, c.from_table, c.from_column, str(e)[:200],
                )

    return {
        "source_id": source_id,
        "dialect": d.name,
        "tables_scanned": len(tables),
        "candidates": len(candidates),
        "persisted": persisted,
        "skipped_existing": skipped_existing,
        "skipped_low_confidence": skipped_low,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved[:200],
        "sample": sample_out,
    }
