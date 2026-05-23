"""
v3.28.2 G3 — Sample Data Preview Helper
=========================================
Pipeline run sonrası, execute öncesi kullanıcıya gösterilecek "aday tablo +
örnek satırlar" payload'unu hazırlar. Mevcut `ds_db_samples` cache'inden okur,
LLM/DB-side query çalıştırmaz. Cache miss → None döner (frontend graceful).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# SQL'in FROM cümlesinden ilk tabloyu yakalar:
#   FROM schema.table  /  FROM table  /  FROM "schema"."table"  /  FROM [schema].[table]
#   FROM `schema`.`table`
# Karmaşık SQL (subquery, JOIN'siz alt-select) için bu basit regex graceful fail eder.
_FROM_TABLE_RE = re.compile(
    r"\bFROM\s+"
    r"(?:[\"\[`]?(?P<schema>[A-Za-z_][\w]*)[\"\]`]?\.)?"
    r"[\"\[`]?(?P<table>[A-Za-z_][\w]*)[\"\]`]?",
    re.IGNORECASE,
)

# v3.32.0: SQL içindeki TÜM tabloları (FROM + JOIN) yakalar. Preview validation
# için kullanılır: ranker'ın picked table'ı gerçekten SQL'de yer alıyor mu?
_FROM_OR_JOIN_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+"
    r"(?:[\"\[`]?(?P<schema>[A-Za-z_][\w]*)[\"\]`]?\.)?"
    r"[\"\[`]?(?P<table>[A-Za-z_][\w]*)[\"\]`]?",
    re.IGNORECASE,
)


def extract_all_tables_from_sql(sql: str) -> List[Dict[str, Optional[str]]]:
    """SQL içindeki tüm FROM + JOIN tablolarını döner.

    Returns list of ``{"schema": str|None, "table": str}``. Duplicates removed,
    case-preserved as in original SQL. Subquery / CTE içeriği de yakalanır
    (basit regex — semantik analiz değil, validation/heuristic için yeterli).
    """
    if not sql or not isinstance(sql, str):
        return []
    seen: set = set()
    out: List[Dict[str, Optional[str]]] = []
    for m in _FROM_OR_JOIN_TABLE_RE.finditer(sql):
        tbl = m.group("table")
        if not tbl:
            continue
        sch = m.group("schema")
        key = (str(sch).lower() if sch else None, tbl.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"schema": sch, "table": tbl})
    return out


def extract_first_table_from_sql(sql: str) -> Optional[Dict[str, Optional[str]]]:
    """SQL FROM cümlesinden ilk tabloyu yakalar.

    Returns ``{"schema": str|None, "table": str}`` veya None.
    Subquery / CTE / dialect-spesifik notation'larda fail edebilir → graceful.
    """
    if not sql or not isinstance(sql, str):
        return None
    # CTE/WITH başlangıcını strip et — ilk gerçek FROM'u yakalayalım
    body = sql
    # Basit yaklaşım: en son FROM (ana SELECT'in FROM'u genelde daha sonda olur)
    matches = list(_FROM_TABLE_RE.finditer(body))
    if not matches:
        return None
    # CTE'lerin FROM'larını da kapsar; main SELECT genelde en sonda
    m = matches[-1] if len(matches) > 1 else matches[0]
    schema = m.group("schema")
    table = m.group("table")
    if not table:
        return None
    return {"schema": schema, "table": table}


def build_sample_preview(
    cur,
    source_id: int,
    schema: Optional[str],
    table: str,
    limit: int = 5,
) -> Optional[Dict[str, Any]]:
    """`ds_db_samples` cache'inden tek-tablo preview döndürür.

    Args:
        cur: psycopg2 cursor (RealDictCursor varsayılır)
        source_id: data_sources.id
        schema: schema_name (None/boş = IS NULL match)
        table: tablo adı
        limit: kaç satır (1-50)

    Returns:
        ``{schema, table, columns: [{name, type}], rows: [...], row_count,
        business_name_tr, cached: True}`` veya None (cache miss).
    """
    if not table:
        return None
    limit = max(1, min(int(limit or 5), 50))

    try:
        if schema is None or str(schema).strip() == "":
            cur.execute(
                """
                SELECT s.sample_data, s.row_count, s.fetched_at,
                       o.columns_json, o.schema_name, o.object_name
                FROM ds_db_samples s
                JOIN ds_db_objects o ON o.id = s.object_id
                WHERE s.source_id = %s
                  AND o.schema_name IS NULL
                  AND o.object_name = %s
                  AND o.object_type = 'table'
                ORDER BY s.fetched_at DESC
                LIMIT 1
                """,
                (source_id, table),
            )
        else:
            cur.execute(
                """
                SELECT s.sample_data, s.row_count, s.fetched_at,
                       o.columns_json, o.schema_name, o.object_name
                FROM ds_db_samples s
                JOIN ds_db_objects o ON o.id = s.object_id
                WHERE s.source_id = %s
                  AND o.schema_name = %s
                  AND o.object_name = %s
                  AND o.object_type = 'table'
                ORDER BY s.fetched_at DESC
                LIMIT 1
                """,
                (source_id, schema, table),
            )
        row = cur.fetchone()
    except Exception:
        logger.exception("[SamplePreview] DB error reading ds_db_samples")
        return None

    if not row:
        return None
    row = dict(row)

    sample_data = row.get("sample_data") or []
    if not isinstance(sample_data, list):
        sample_data = []

    rows_out = sample_data[:limit]

    columns_meta: List[Dict[str, Any]] = []
    cols_json = row.get("columns_json") or []
    if isinstance(cols_json, list):
        for c in cols_json:
            if isinstance(c, dict):
                cname = c.get("name") or c.get("column_name")
                ctype = c.get("type") or c.get("data_type") or ""
                if cname:
                    columns_meta.append({"name": cname, "type": str(ctype)})

    if not columns_meta and rows_out:
        first = rows_out[0] if isinstance(rows_out[0], dict) else {}
        for k in first.keys():
            columns_meta.append({"name": k, "type": ""})

    business_name_tr: Optional[str] = None
    try:
        if row.get("schema_name") is None:
            cur.execute(
                """
                SELECT business_name_tr FROM ds_table_enrichments
                WHERE source_id = %s AND schema_name IS NULL AND table_name = %s
                LIMIT 1
                """,
                (source_id, row.get("object_name")),
            )
        else:
            cur.execute(
                """
                SELECT business_name_tr FROM ds_table_enrichments
                WHERE source_id = %s AND schema_name = %s AND table_name = %s
                LIMIT 1
                """,
                (source_id, row.get("schema_name"), row.get("object_name")),
            )
        enr = cur.fetchone()
        if enr:
            business_name_tr = dict(enr).get("business_name_tr")
    except Exception:
        pass

    return {
        "schema": row.get("schema_name"),
        "table": row.get("object_name"),
        "business_name_tr": business_name_tr,
        "columns": columns_meta,
        "rows": rows_out,
        "row_count": row.get("row_count") or len(rows_out),
        "fetched_at": row.get("fetched_at").isoformat() if row.get("fetched_at") else None,
        "cached": True,
    }


def pick_top_table_for_preview(final_state: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """Pipeline final state'inden preview için en iyi tabloyu seç.

    Öncelik sırası:
      1. ``selected_tables[0]`` (force veya pipeline final seçimi)
      2. ``ranked_candidates[0]`` (multi_signal_rank çıktısı)

    Returns:
        ``{"schema": str|None, "table": str}`` veya None.
    """
    if not isinstance(final_state, dict):
        return None

    selected = final_state.get("selected_tables") or []
    if isinstance(selected, list) and selected:
        first = selected[0]
        if isinstance(first, dict):
            tbl = first.get("table_name") or first.get("table")
            if tbl:
                return {"schema": first.get("schema_name") or first.get("schema"), "table": tbl}

    ranked = final_state.get("ranked_candidates") or []
    if isinstance(ranked, list) and ranked:
        first = ranked[0]
        if isinstance(first, dict):
            tbl = first.get("table_name") or first.get("table") or first.get("object_name")
            if tbl:
                return {"schema": first.get("schema_name") or first.get("schema"), "table": tbl}

    return None


def pick_preview_table_validated(final_state: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """v3.32.0: Ranker pick'ini final SQL ile cross-check ederek preview tablosunu döner.

    Davranış:
      1. Multi-table JOIN (≥2 tablo) → ``None`` (preview tek-tablo gösterir,
         multi-table sonucunu yanıltıcı şekilde temsil eder).
      2. Single-table SQL → SQL'deki tabloyu döner (ranker pick yanlışsa bile
         doğru tabloyu gösterir — kullanıcı kafa karışıklığı önlenir).
      3. SQL yoksa → eski ``pick_top_table_for_preview`` davranışına fallback.

    Bu senaryo `selected_tables[0]=ABONELIKLER` ama final SQL'in
    ``MUSTERILER ⋈ SIPARISLER ⋈ FATURALAR ⋈ ODEMELER`` olduğu kullanıcı
    raporundan sonra eklendi.
    """
    if not isinstance(final_state, dict):
        return None

    sql = final_state.get("sql") or final_state.get("sql_executed") or ""
    if not sql:
        # SQL henüz üretilmemiş — eski davranışa düş (ranker pick).
        return pick_top_table_for_preview(final_state)

    sql_tables = extract_all_tables_from_sql(sql)
    if not sql_tables:
        # SQL var ama parse edilemedi (CTE/subquery vs.) → ranker pick'e güven.
        return pick_top_table_for_preview(final_state)

    if len(sql_tables) >= 2:
        # Multi-table JOIN — preview yanıltıcı, atla.
        return None

    # Single-table → her zaman SQL'deki tabloyu kullan, ranker pick'i değil.
    only = sql_tables[0]
    return {"schema": only.get("schema"), "table": only.get("table")}
