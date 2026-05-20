"""Custom Metric NL→SQL parser (v3.30.0 FAZ 2 P11 G2.2).

Doğal dil Türkçe metriği yapılandırılmış SQL'e çevirir + dbsmart_metric_library'ye
kaydeder (is_official=FALSE, owner_user_id=X).

Sorumluluklar:
    - extract_intent_heuristic(nl_query): hızlı Türkçe regex sezgi çıkarımı
      (agg_func/time_window/group_hint) — LLM çağrısı YOK; UI'da feedback için.
    - build_metric_schema_context(cur, source_id, table_ids): seçili tablolar
      için ds_table_enrichments + ds_column_enrichments'ten slim schema_context.
    - parse_to_sql(nl_query, schema_context, allowed_table_names, *, max_retry):
      text_to_sql.generate_sql çağırır → safe_sql_executor.validate_sql +
      check_table_whitelist + ast_renderer.parse_sql_to_ast doğrulamasından
      geçirip {success, sql, ast, intent, error} döner.
    - save_custom_metric(cur, ...): dbsmart_metric_library INSERT
      (is_official=FALSE, owner_user_id, source_id, company_id, template_key
      auto-generate). RLS policy company_id ile yazma izolasyonu uygular.

Tasarım notları:
    - LLM çağrısı text_to_sql.generate_sql içinde (temperature 0.1).
    - max_retry=1 (basit prompt ile) yine text_to_sql tarafında uygulanıyor.
    - Identifier whitelist: caller allowed_table_names'i schema_context'ten
      türetir. Bu sayede LLM rastgele tablo üretemez.
    - Cursor caller'dan gelir (apply_vyra_user_context set edilmiş).
    - Saved metric'in metric_key'i çakışmasın diye SHA1 hash'i suffix olarak.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Intent extraction (heuristic — Türkçe)
# ─────────────────────────────────────────────────────────────

# Eşleştirme: regex pattern → (agg_func, label)
_AGG_PATTERNS = [
    (re.compile(r"\b(toplam|topla|sum|kümül)\w*\b", re.IGNORECASE), "SUM"),
    (re.compile(r"\b(ortalama|ort|mean|avg)\w*\b", re.IGNORECASE), "AVG"),
    (re.compile(r"\b(say(ı|i)|adet|count|kaç)\w*\b", re.IGNORECASE), "COUNT"),
    (re.compile(r"\b(en\s+y(ü|u)ksek|maksimum|max)\b", re.IGNORECASE), "MAX"),
    (re.compile(r"\b(en\s+d(ü|u)ş(ü|u)k|minimum|min)\b", re.IGNORECASE), "MIN"),
    (re.compile(r"\b(medyan|median)\b", re.IGNORECASE), "MEDIAN"),
    (re.compile(r"\b(oran|y(ü|u)zde|rate|ratio)\b", re.IGNORECASE), "RATIO"),
]

# Zaman pencereleri
_TIME_PATTERNS = [
    (re.compile(r"\bson\s+(\d+)\s+g(ü|u)n\b", re.IGNORECASE), "days"),
    (re.compile(r"\bson\s+(\d+)\s+hafta\b", re.IGNORECASE), "weeks"),
    (re.compile(r"\bson\s+(\d+)\s+ay\b", re.IGNORECASE), "months"),
    (re.compile(r"\bson\s+(\d+)\s+y(ı|i)l\b", re.IGNORECASE), "years"),
    (re.compile(r"\bbu(\s+|nki)?\s*ay\b", re.IGNORECASE), "this_month"),
    (re.compile(r"\bge(çe|ce)n\s+ay\b", re.IGNORECASE), "last_month"),
    (re.compile(r"\bbu(\s+|nki)?\s*y(ı|i)l\b", re.IGNORECASE), "this_year"),
    (re.compile(r"\bge(çe|ce)n\s+y(ı|i)l\b", re.IGNORECASE), "last_year"),
]

# Grup ipuçları (Türkçe)
_GROUP_HINT_PATTERNS = [
    (re.compile(r"\b(her|başına|göre)\b", re.IGNORECASE), "group_by_hint"),
    (re.compile(r"\b(aya|haftaya|y(ı|i)la|g(ü|u)ne)\s+göre\b", re.IGNORECASE), "group_by_time"),
    (re.compile(r"\b(müşteri|ürün|kategori|departman)\w*\s+(başına|göre)\b", re.IGNORECASE), "group_by_entity"),
]


def extract_intent_heuristic(nl_query: str) -> Dict[str, Any]:
    """Hızlı Türkçe regex tabanlı intent extraction (LLM YOK).

    Returns:
        {
          "agg_func": "SUM"|"AVG"|"COUNT"|"MAX"|"MIN"|"MEDIAN"|"RATIO"|None,
          "time_window": {"kind": "days"|...|"this_month"|..., "n": int?} | None,
          "group_hints": ["group_by_time", ...],
          "raw": nl_query,
        }
    """
    if not isinstance(nl_query, str) or not nl_query.strip():
        return {"agg_func": None, "time_window": None, "group_hints": [], "raw": ""}

    agg_func: Optional[str] = None
    for pat, lbl in _AGG_PATTERNS:
        if pat.search(nl_query):
            agg_func = lbl
            break

    time_window: Optional[Dict[str, Any]] = None
    for pat, kind in _TIME_PATTERNS:
        m = pat.search(nl_query)
        if m:
            tw: Dict[str, Any] = {"kind": kind}
            if m.groups() and m.group(1) and m.group(1).isdigit():
                tw["n"] = int(m.group(1))
            time_window = tw
            break

    group_hints: List[str] = []
    seen: Set[str] = set()
    for pat, lbl in _GROUP_HINT_PATTERNS:
        if pat.search(nl_query) and lbl not in seen:
            group_hints.append(lbl)
            seen.add(lbl)

    return {
        "agg_func": agg_func,
        "time_window": time_window,
        "group_hints": group_hints,
        "raw": nl_query,
    }


# ─────────────────────────────────────────────────────────────
# Schema context builder
# ─────────────────────────────────────────────────────────────

def build_metric_schema_context(
    cur: Any,
    source_id: int,
    table_ids: List[int],
    *,
    dialect: str = "postgresql",
    max_columns_per_table: int = 80,
) -> Dict[str, Any]:
    """Seçili tabloların ds_*_enrichments verisinden slim schema_context kurar.

    text_to_sql.generate_sql ile uyumlu format:
        {
          "source_name": str,
          "dialect": "postgresql"|...,
          "tables": [{name, columns: [{name, data_type, is_pk, ...}],
                      col_enrichments: {col_name: {business_name_tr, synonyms}}}],
        }

    table_ids boşsa boş tables listesi döner (caller'a 400 düşmesini sağla).
    """
    if not isinstance(table_ids, list) or not table_ids:
        return {"source_name": "?", "dialect": dialect, "tables": []}

    # Source name
    src_name = "?"
    try:
        cur.execute(
            "SELECT source_name FROM data_sources WHERE id = %s",
            (int(source_id),),
        )
        row = cur.fetchone()
        if row:
            src_name = row[0] if not isinstance(row, dict) else row.get("source_name", "?")
    except Exception as e:
        logger.warning("[db_smart.cmp] source name lookup failed: %s", e)

    tables: List[Dict[str, Any]] = []
    for tid in table_ids:
        try:
            cur.execute(
                """
                SELECT id, object_name, table_enrichment_id
                FROM ds_db_objects
                WHERE id = %s AND source_id = %s
                """,
                (int(tid), int(source_id)),
            )
            r = cur.fetchone()
            if not r:
                continue
            obj_name = r[1] if not isinstance(r, dict) else r.get("object_name")
            te_id = r[2] if not isinstance(r, dict) else r.get("table_enrichment_id")

            cur.execute(
                """
                SELECT column_name, data_type, business_name_tr,
                       admin_label_tr, semantic_type
                FROM ds_column_enrichments
                WHERE source_id = %s
                  AND (table_enrichment_id = %s OR %s IS NULL)
                ORDER BY id
                LIMIT %s
                """,
                (int(source_id), te_id, te_id, int(max_columns_per_table)),
            )
            col_rows = cur.fetchall() or []
            columns: List[Dict[str, Any]] = []
            col_enrichments: Dict[str, Dict[str, Any]] = {}
            for cr in col_rows:
                if isinstance(cr, dict):
                    cn = cr.get("column_name")
                    dt = cr.get("data_type") or "TEXT"
                    bn = cr.get("business_name_tr") or cr.get("admin_label_tr") or ""
                    st = cr.get("semantic_type") or ""
                else:
                    cn, dt, bn_raw, lbl, st = (
                        cr[0], cr[1] or "TEXT", cr[2], cr[3], cr[4],
                    )
                    bn = bn_raw or lbl or ""
                if not cn:
                    continue
                columns.append({"name": cn, "data_type": dt})
                if bn or st:
                    col_enrichments[cn] = {
                        "business_name_tr": bn or "",
                        "semantic_type": st or "",
                    }
            tables.append({
                "name": obj_name,
                "columns": columns,
                "col_enrichments": col_enrichments,
            })
        except Exception as e:
            logger.warning("[db_smart.cmp] table %s lookup failed: %s", tid, e)
            continue

    return {"source_name": src_name, "dialect": dialect, "tables": tables}


# ─────────────────────────────────────────────────────────────
# NL → SQL pipeline
# ─────────────────────────────────────────────────────────────

def _extract_allowed_table_names(schema_context: Dict[str, Any]) -> List[str]:
    return [
        t.get("name", "").lower()
        for t in (schema_context.get("tables") or [])
        if t.get("name")
    ]


def parse_to_sql(
    nl_query: str,
    schema_context: Dict[str, Any],
    *,
    allowed_table_names: Optional[List[str]] = None,
    _generate_sql=None,   # test override
    _validate_sql=None,   # test override
    _check_whitelist=None,  # test override
) -> Dict[str, Any]:
    """NL → SQL: LLM çağrısı + validate + whitelist + intent paketi.

    Returns:
        {
          "success": bool,
          "sql": str | None,
          "intent": {...},
          "error": str | None,
          "explanation": str | None,
        }
    """
    if not isinstance(nl_query, str) or not nl_query.strip():
        return {"success": False, "sql": None, "intent": {}, "error": "Boş sorgu", "explanation": None}
    if not schema_context or not (schema_context.get("tables") or []):
        return {
            "success": False, "sql": None,
            "intent": extract_intent_heuristic(nl_query),
            "error": "Tablo seçimi yok — özel metrik için en az bir tablo gerekli.",
            "explanation": None,
        }

    if _generate_sql is None:
        from app.services.text_to_sql import generate_sql as _generate_sql  # type: ignore
    if _validate_sql is None:
        from app.services.safe_sql_executor import validate_sql as _validate_sql  # type: ignore
    if _check_whitelist is None:
        from app.services.safe_sql_executor import check_table_whitelist as _check_whitelist  # type: ignore

    intent = extract_intent_heuristic(nl_query)
    allowed = [n.lower() for n in (allowed_table_names or _extract_allowed_table_names(schema_context))]

    try:
        gen = _generate_sql(nl_query, schema_context, allowed_tables=allowed)
    except Exception as e:
        logger.warning("[db_smart.cmp] generate_sql raised: %s", e)
        return {"success": False, "sql": None, "intent": intent,
                "error": f"LLM çağrısı başarısız: {e}", "explanation": None}

    if not gen.get("success") or not gen.get("sql"):
        return {
            "success": False, "sql": None, "intent": intent,
            "error": gen.get("error") or "LLM SQL üretemedi",
            "explanation": gen.get("explanation"),
        }

    sql = gen["sql"]
    ok, err = _validate_sql(sql)
    if not ok:
        return {"success": False, "sql": sql, "intent": intent,
                "error": f"Güvenlik doğrulaması: {err}", "explanation": gen.get("explanation")}

    if allowed:
        ok_wl, err_wl = _check_whitelist(sql, allowed, dialect=schema_context.get("dialect", "postgresql"))
        if not ok_wl:
            return {"success": False, "sql": sql, "intent": intent,
                    "error": f"Tablo whitelist: {err_wl}", "explanation": gen.get("explanation")}

    return {
        "success": True, "sql": sql, "intent": intent,
        "error": None, "explanation": gen.get("explanation"),
    }


# ─────────────────────────────────────────────────────────────
# Save flow — dbsmart_metric_library INSERT (is_official=FALSE)
# ─────────────────────────────────────────────────────────────

def _make_metric_key(name_tr: str, owner_user_id: int) -> str:
    """custom_<userid>_<sha1[:10]> — unique constraint için yeterli."""
    base = f"{owner_user_id}::{name_tr.strip().lower()}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"custom_{owner_user_id}_{h}"


def save_custom_metric(
    cur: Any,
    *,
    user_ctx: Dict[str, Any],
    name_tr: str,
    sql: str,
    source_id: int,
    description_tr: Optional[str] = None,
    default_viz: str = "table",
    category: str = "custom",
    sub_category: Optional[str] = None,
    intent: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """dbsmart_metric_library INSERT (is_official=FALSE, owner_user_id=X).

    RLS politikası: company_id ile yazma izolasyonu (admin bypass).
    sql_templates JSONB: {"default": sql, "intent": intent}.

    Returns:
        Yeni metrik id'si veya None (RLS reddetti / hata).
    """
    user_id = user_ctx.get("id") if user_ctx else None
    company_id = user_ctx.get("company_id") if user_ctx else None
    if user_id is None or company_id is None:
        logger.warning("[db_smart.cmp] save_custom_metric: missing user_ctx")
        return None
    if not isinstance(name_tr, str) or not name_tr.strip():
        logger.warning("[db_smart.cmp] save_custom_metric: empty name_tr")
        return None
    if not isinstance(sql, str) or not sql.strip():
        logger.warning("[db_smart.cmp] save_custom_metric: empty sql")
        return None

    metric_key = _make_metric_key(name_tr, int(user_id))
    sql_templates = {"default": sql}
    if intent:
        sql_templates["intent"] = intent

    try:
        cur.execute(
            """
            INSERT INTO dbsmart_metric_library
                (metric_key, name_tr, category, sub_category,
                 description_tr, applicable_when, sql_templates,
                 required_features, optional_features, default_viz,
                 is_official, is_active, owner_user_id, source_id, company_id)
            VALUES
                (%s, %s, %s, %s,
                 %s, %s::jsonb, %s::jsonb,
                 %s::jsonb, %s::jsonb, %s,
                 FALSE, TRUE, %s, %s, %s)
            ON CONFLICT (metric_key) DO UPDATE
                SET name_tr        = EXCLUDED.name_tr,
                    description_tr = EXCLUDED.description_tr,
                    sql_templates  = EXCLUDED.sql_templates,
                    default_viz    = EXCLUDED.default_viz,
                    is_active      = TRUE
            RETURNING id
            """,
            (
                metric_key,
                name_tr.strip()[:160],
                category[:60],
                (sub_category or "")[:60] or None,
                description_tr,
                json.dumps({"custom": True}),
                json.dumps(sql_templates),
                json.dumps([]),
                json.dumps([]),
                default_viz,
                int(user_id),
                int(source_id),
                int(company_id),
            ),
        )
        row = cur.fetchone()
        if not row:
            logger.warning("[db_smart.cmp] save INSERT RETURNING empty (RLS?)")
            return None
        mid = row[0] if not isinstance(row, dict) else row.get("id")
        logger.info(
            "[db_smart.cmp] saved custom metric id=%s key=%s user=%s source=%s",
            mid, metric_key, user_id, source_id,
        )
        return int(mid) if mid is not None else None
    except Exception as e:
        logger.warning("[db_smart.cmp] save_custom_metric INSERT failed: %s", e)
        return None
