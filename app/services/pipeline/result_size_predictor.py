"""
result_size_predictor — Faz 6a
==============================
SQL'i çalıştırmadan önce sonuç boyutu tahmini yapar.

Kullanım amacı:
    - "huge" tahminlerde streaming endpoint'e yönlendir
    - "small" tahminlerde sync response (mevcut akış)
    - "medium/large" için pagination/batch öner

Tahmin stratejisi (LLM-free, dialect-agnostic):
    1) SQL'i parse et — LIMIT, aggregate (COUNT/SUM/AVG/MAX/MIN), GROUP BY, WHERE
    2) Aggregate-only sorgu → 'small' (tek satır)
    3) Açık LIMIT N varsa → bucket(N)
    4) WHERE PK eşitlik varsa (id = ?) → 'small'
    5) Aksi halde:
        a) _explain_callable varsa → EXPLAIN'den rows kestir
        b) Tablo istatistikleri (pg_stat_user_tables.n_live_tup veya
           cur kullanılabilirse SELECT reltuples) — best-effort
        c) Hiçbiri yoksa heuristik 'medium' döner

Bucket eşikleri (override için ENV / state):
    SMALL  : N <= 50          → sync, full payload
    MEDIUM : 50 < N <= 1_000   → sync, truncate flag
    LARGE  : 1_000 < N <= 50_000 → streaming önerilir
    HUGE   : > 50_000          → streaming zorunlu, server-side cursor

Public API:
    predict_result_size(sql, *, dialect, cursor=None, explain_callable=None) -> dict
        {
          "bucket": "small" | "medium" | "large" | "huge",
          "estimated_rows": int | None,
          "reason": str,
          "streaming_recommended": bool,
          "streaming_required": bool,
        }
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Callable

# Bucket eşikleri
SMALL_MAX = 50
MEDIUM_MAX = 1_000
LARGE_MAX = 50_000

_AGG_RE = re.compile(r"\b(count|sum|avg|min|max)\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
_FETCH_FIRST_RE = re.compile(r"\bfetch\s+(?:first|next)\s+(\d+)\s+rows?\s+only\b", re.IGNORECASE)
_TOP_RE = re.compile(r"\bselect\s+top\s+(\d+)\b", re.IGNORECASE)
_FROM_RE = re.compile(
    r"\bfrom\s+([a-zA-Z_][\w]*)(?:\s*\.\s*([a-zA-Z_][\w]*))?",
    re.IGNORECASE,
)
_PK_WHERE_RE = re.compile(
    r"\bwhere\b[^;]*?\b(id|pk|primary_key)\s*=\s*(\d+|'[^']*'|\$\d+|\?|:\w+)",
    re.IGNORECASE,
)


def _bucket_for(n: int) -> str:
    if n <= SMALL_MAX:
        return "small"
    if n <= MEDIUM_MAX:
        return "medium"
    if n <= LARGE_MAX:
        return "large"
    return "huge"


def _strip_comments(sql: str) -> str:
    """Yorum satırlarını çıkar (kaba ama yeterli)."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


# String/identifier literal'leri sterilize ederken kullanılan token.
_LITERAL_TOKEN = "''"
_SINGLE_QUOTED_RE = re.compile(r"'(?:[^']|'')*'")  # '...' (SQL '' kaçışıyla)
_DOUBLE_QUOTED_RE = re.compile(r'"(?:[^"]|"")*"')  # "..." identifier (PG/Oracle/MSSQL)


def _strip_literals(sql: str) -> str:
    """
    SQL string/identifier literal'lerini sabit token'a indirger.

    Amaç: regex tabanlı LIMIT / aggregate / PK eşitlik tespiti, literal'lerin
    içeriğinden etkilenmesin (ör. ``WHERE name = 'limit 100'`` predictor'ı
    yanıltmasın). PK eşitlik regex'i kendi tarafında string literal'i de
    yakalayabildiğinden, içeriği boş literal'e indirmek yeterli.
    """
    if not sql:
        return sql
    sql = _SINGLE_QUOTED_RE.sub(_LITERAL_TOKEN, sql)
    sql = _DOUBLE_QUOTED_RE.sub('""', sql)
    return sql


def _explicit_limit(sql: str) -> Optional[int]:
    """LIMIT N | FETCH FIRST N ROWS ONLY | SELECT TOP N — bulursa N döner."""
    for rx in (_LIMIT_RE, _FETCH_FIRST_RE, _TOP_RE):
        m = rx.search(sql)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def _is_aggregate_only(sql: str) -> bool:
    """SELECT yalnız aggregate kolonlar mı ve GROUP BY yok mu?"""
    if not _AGG_RE.search(sql):
        return False
    if _GROUP_BY_RE.search(sql):
        return False
    # SELECT ... FROM arası kısımda aggregate dışı kolon var mı kabaca kontrol
    m = re.search(r"\bselect\b(.+?)\bfrom\b", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return False
    select_part = m.group(1)
    # Aggregate çağrılarını maskele
    masked = _AGG_RE.sub("(", select_part)
    # İç içe parantezleri tek tek temizle (önceki sürüm tek katmanı kaldırıyordu;
    # `COUNT(DISTINCT (a+b))` gibi iç içe gruplar non-aggregate gibi görünüyordu).
    while True:
        new = re.sub(r"\([^()]*\)", "X", masked)
        if new == masked:
            break
        masked = new
    # Maskelenmiş içerikte virgüllerle ayrılmış non-aggregate kolon kaldı mı?
    tokens = [t.strip() for t in masked.split(",") if t.strip()]
    non_agg = [t for t in tokens if t and t != "X" and not re.fullmatch(r"X(\s+as\s+\w+)?", t, re.IGNORECASE)]
    return len(non_agg) == 0


def _has_pk_equality_where(sql: str) -> bool:
    return bool(_PK_WHERE_RE.search(sql))


def _extract_first_table(sql: str) -> Optional[tuple]:
    """FROM <schema>.<table> | FROM <table> — ilk eşleşmeyi döner."""
    m = _FROM_RE.search(sql)
    if not m:
        return None
    g1 = m.group(1)
    g2 = m.group(2)
    if g2:
        return (g1, g2)
    return (None, g1)


def _explain_row_estimate(
    sql: str, explain_callable: Callable[[str], Any]
) -> Optional[int]:
    """
    EXPLAIN callable'ından satır tahmini al (best-effort).

    Plan içinde gerçekten "Plan Rows" anahtarı yoksa None döner (eskiden 0
    dönerek "small" yanlış-pozitifine yol açıyordu).
    """
    try:
        plan = explain_callable(sql)
        if isinstance(plan, dict):
            # PostgreSQL EXPLAIN (FORMAT JSON) → [{"Plan": {"Plan Rows": N, ...}}]
            if "rows" in plan and plan["rows"] is not None:
                return int(plan["rows"])
            if "Plan" in plan and isinstance(plan["Plan"], dict):
                pr = plan["Plan"].get("Plan Rows")
                if pr is not None:
                    return int(pr)
        if isinstance(plan, list) and plan:
            first = plan[0]
            if isinstance(first, dict):
                p = first.get("Plan") or first
                if isinstance(p, dict) and p.get("Plan Rows") is not None:
                    return int(p["Plan Rows"])
        if isinstance(plan, str):
            # Text format'tan "rows=N" yakala
            mm = re.search(r"rows=(\d+)", plan)
            if mm:
                return int(mm.group(1))
    except Exception:
        return None
    return None


def _table_stat_estimate(
    cursor, schema: Optional[str], table: str, dialect: str = "postgresql"
) -> Optional[int]:
    """
    pg_stat_user_tables / reltuples üzerinden tahmin (PG-only best-effort).

    SAVEPOINT içinde sarmalı: bilinmeyen tablo/şema hatası ana transaction'ı
    abort'a düşürmesin (emit_event'in çözdüğü aynı poison-TX riski).
    """
    if cursor is None or not table:
        return None
    if dialect.lower() not in ("postgresql", "postgres", "pg"):
        return None
    sp_name = "_predict_stat"
    try:
        cursor.execute(f"SAVEPOINT {sp_name}")
    except Exception:
        return None
    try:
        if schema:
            cursor.execute(
                "SELECT reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relname=%s",
                (schema, table),
            )
        else:
            cursor.execute(
                "SELECT reltuples::bigint FROM pg_class WHERE relname=%s LIMIT 1",
                (table,),
            )
        row = cursor.fetchone()
        cursor.execute(f"RELEASE SAVEPOINT {sp_name}")
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        try:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            cursor.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:
            pass
        return None
    return None


def predict_result_size(
    sql: str,
    *,
    dialect: str = "postgresql",
    cursor=None,
    explain_callable: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """
    SQL → bucket tahmini.

    Returns:
        {
          "bucket": "small"|"medium"|"large"|"huge",
          "estimated_rows": int | None,
          "reason": "aggregate_only" | "explicit_limit" | "pk_equality"
                    | "explain_plan" | "table_stats" | "heuristic_default",
          "streaming_recommended": bool,
          "streaming_required": bool,
        }
    """
    if not sql or not sql.strip():
        return {
            "bucket": "small", "estimated_rows": 0, "reason": "empty_sql",
            "streaming_recommended": False, "streaming_required": False,
        }

    # Yorumları ve string/identifier literal'lerini sterilize et —
    # ``WHERE note = 'LIMIT 100'`` gibi sorgular predictor'ı yanıltmasın.
    clean = _strip_literals(_strip_comments(sql))

    # 1) Aggregate-only → 1 satır
    if _is_aggregate_only(clean):
        return {
            "bucket": "small", "estimated_rows": 1, "reason": "aggregate_only",
            "streaming_recommended": False, "streaming_required": False,
        }

    # 2) Açık LIMIT
    n = _explicit_limit(clean)
    if n is not None:
        bucket = _bucket_for(n)
        return {
            "bucket": bucket, "estimated_rows": n, "reason": "explicit_limit",
            "streaming_recommended": bucket in ("large", "huge"),
            "streaming_required": bucket == "huge",
        }

    # 3) PK eşitlik
    if _has_pk_equality_where(clean):
        return {
            "bucket": "small", "estimated_rows": 1, "reason": "pk_equality",
            "streaming_recommended": False, "streaming_required": False,
        }

    # 4) EXPLAIN
    if explain_callable is not None:
        rows = _explain_row_estimate(sql, explain_callable)
        if rows is not None:
            bucket = _bucket_for(rows)
            return {
                "bucket": bucket, "estimated_rows": rows, "reason": "explain_plan",
                "streaming_recommended": bucket in ("large", "huge"),
                "streaming_required": bucket == "huge",
            }

    # 5) Tablo istatistikleri
    tbl = _extract_first_table(clean)
    if tbl is not None and cursor is not None:
        schema, table = tbl
        rows = _table_stat_estimate(cursor, schema, table, dialect)
        if rows is not None and rows >= 0:
            bucket = _bucket_for(rows)
            return {
                "bucket": bucket, "estimated_rows": rows, "reason": "table_stats",
                "streaming_recommended": bucket in ("large", "huge"),
                "streaming_required": bucket == "huge",
            }

    # 6) Varsayılan: medium (caller karar versin)
    return {
        "bucket": "medium", "estimated_rows": None, "reason": "heuristic_default",
        "streaming_recommended": False, "streaming_required": False,
    }


def predict_size_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — sql state'inde varsa boyut tahmini ekler."""
    sql = state.get("sql")
    if not sql:
        return {}
    pred = predict_result_size(
        sql,
        dialect=state.get("db_dialect", "postgresql"),
        cursor=state.get("_cursor"),
        explain_callable=state.get("_explain_callable"),
    )
    return {"result_size_prediction": pred}
