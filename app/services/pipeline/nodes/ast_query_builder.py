"""
ast_query_builder — Faz 5d
==========================
LLM-free deterministic SQL üreteci. `lookup` intent için, seçilen tek tablodan
sınırlı sayıda satır listeler. LLM çağrısından kaçınarak:
    - latency ↓ (LLM round-trip yok)
    - maliyet ↓
    - reproducibility ↑

Yaklaşım:
    AST sözcüğü literal: gerçek SQL parse/build için pglast/sqlglot kullanılabilir;
    bu prototipte dialect-aware parametrik template ile başlıyoruz.
    Eğer sqlglot kuruluysa, son adımda parse-roundtrip yapılır (sanity).

Şartlar — sadece şu durumlarda devreye girer:
    - intent == 'lookup'
    - selected_tables tek tablo
    - LLM-free hint state'te (force_ast=True) ya da config flag

Dışında değilse, sql_generate normal yola devam eder.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)

# Default limit (NIKE perf önerisi)
DEFAULT_ROW_LIMIT = 100

# Türkçe normalize (multi_signal_rank ile aynı)
_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})

# Basit eş anlamlı sözlük — order by / where için kolon yakalama
ORDER_HINTS = {
    "en yeni": "DESC", "yeni": "DESC", "son": "DESC", "latest": "DESC", "recent": "DESC",
    "en eski": "ASC", "eski": "ASC", "earliest": "ASC",
    "en buyuk": "DESC", "en kucuk": "ASC", "max": "DESC", "min": "ASC",
}

DATE_COLUMN_HINTS = ("date", "tarih", "tarihi", "created", "updated", "olusturma", "guncelleme", "_at", "_dt")

# Tek-token sayı pattern (limit override için: "ilk 50", "son 200")
_NUMBER_RE = re.compile(r"\b(\d{1,5})\b")


def _norm(text: str) -> str:
    return (text or "").lower().translate(_TR_MAP)


def _quote_identifier(name: str, dialect: str) -> str:
    """Identifier quoting (multi-dialect)."""
    if not name:
        return name
    if dialect in ("mysql",):
        return f"`{name}`"
    if dialect in ("mssql",):
        return f"[{name}]"
    # PostgreSQL / Oracle / generic
    return f'"{name}"'


def _format_table(schema: Optional[str], table: str, dialect: str) -> str:
    """schema.table format (dialect-aware)."""
    qt = _quote_identifier(table, dialect)
    if schema and schema not in ("", "public"):
        qs = _quote_identifier(schema, dialect)
        return f"{qs}.{qt}"
    return qt


def _detect_limit(query: str, default: int = DEFAULT_ROW_LIMIT) -> int:
    """Soru içinde 'ilk 50' / 'son 200' gibi limit override yakala."""
    nq = _norm(query)
    if not any(k in nq for k in ("ilk", "son", "first", "last", "top")):
        return default
    m = _NUMBER_RE.search(nq)
    if not m:
        return default
    try:
        n = int(m.group(1))
        if 1 <= n <= 10000:
            return n
    except ValueError:
        pass
    return default


def _pick_order_column(columns: List[Dict[str, Any]], query: str) -> Tuple[Optional[str], str]:
    """
    Sorgudan order kolonunu çıkar:
        - Date/timestamp varsa onu kullan
        - 'yeni/son' → DESC, 'eski' → ASC
    """
    nq = _norm(query)
    direction = "DESC"  # default sıralama: son ekleneni
    for kw, dir_ in ORDER_HINTS.items():
        if kw in nq:
            direction = dir_
            break

    # Date kolonu ara
    for col in columns:
        cname = (col.get("column_name") or "").lower()
        ctype = (col.get("data_type") or "").lower()
        if "date" in ctype or "time" in ctype or "timestamp" in ctype:
            return col.get("column_name"), direction
        # İsim heuristic
        if any(h in cname for h in DATE_COLUMN_HINTS):
            return col.get("column_name"), direction

    # PK varsa onu kullan (sıralı id varsayımı)
    for col in columns:
        if col.get("is_pk"):
            return col.get("column_name"), direction

    return None, direction


def _build_select_list(columns: List[Dict[str, Any]], dialect: str, max_cols: int = 20) -> str:
    """SELECT * yerine ilk N kolonu listele (büyük tablolarda perf)."""
    if not columns:
        return "*"
    cols = []
    for col in columns[:max_cols]:
        cname = col.get("column_name")
        if not cname:
            continue
        cols.append(_quote_identifier(cname, dialect))
    if not cols:
        return "*"
    return ", ".join(cols)


def _format_limit(limit: int, dialect: str, offset: int = 0) -> str:
    """LIMIT clause (dialect-aware)."""
    if dialect == "mssql":
        # OFFSET ... FETCH (modern MSSQL — ORDER BY zorunlu)
        return f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
    if dialect == "oracle":
        # FETCH FIRST N ROWS ONLY (12c+); klasik için ROWNUM ama biz modern varsayıyoruz
        return f"FETCH FIRST {limit} ROWS ONLY"
    # PostgreSQL / MySQL / SQLite
    if offset > 0:
        return f"LIMIT {limit} OFFSET {offset}"
    return f"LIMIT {limit}"


def build_lookup_sql(
    schema: Optional[str],
    table: str,
    columns: Optional[List[Dict[str, Any]]],
    query: str,
    dialect: str = "postgresql",
    row_limit: Optional[int] = None,
    max_cols: int = 20,
) -> str:
    """
    Tek tablo lookup için deterministic SQL.
    SELECT [cols] FROM [table] [ORDER BY ...] [LIMIT n]
    """
    columns = columns or []
    select_list = _build_select_list(columns, dialect, max_cols=max_cols)
    table_ref = _format_table(schema, table, dialect)
    order_col, direction = _pick_order_column(columns, query)
    limit = row_limit or _detect_limit(query)

    parts = [f"SELECT {select_list}", f"FROM {table_ref}"]
    if order_col:
        parts.append(f"ORDER BY {_quote_identifier(order_col, dialect)} {direction}")
        parts.append(_format_limit(limit, dialect))
    else:
        # MSSQL ORDER BY zorunlu — pseudo "ORDER BY (SELECT NULL)"
        if dialect == "mssql":
            parts.append("ORDER BY (SELECT NULL)")
            parts.append(_format_limit(limit, dialect))
        else:
            parts.append(_format_limit(limit, dialect))
    return "\n".join(parts)


def is_ast_eligible(state: Dict[str, Any]) -> bool:
    """AST yolunu seçme kriteri."""
    if state.get("force_ast") is True:
        # Zorla — config ile override
        pass
    elif state.get("intent") != "lookup":
        return False

    selected = state.get("selected_tables") or []
    if len(selected) != 1:
        return False

    # Aday tek tablo + yeterli kolon bilgisi
    cand = selected[0]
    if not cand.get("table_name"):
        return False
    return True


def ast_query_builder_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node — eğer is_ast_eligible(state) ise SQL üretir ve `sql` set'ler.
    Aksi halde no-op (state delta = {}).
    """
    if not is_ast_eligible(state):
        return {}

    selected = state.get("selected_tables") or []
    cand = selected[0]
    schema = cand.get("schema_name")
    table = cand.get("table_name")
    columns = cand.get("columns") or []
    dialect = state.get("db_dialect", "postgresql")
    question = state.get("question") or ""

    try:
        sql = build_lookup_sql(schema, table, columns, question, dialect=dialect)
    except Exception as e:
        logger.warning("[ast_query_builder] hata: %s", e)
        return {}

    return {"sql": sql, "sql_source": "ast"}
