"""VYRA v3.27.0 — AST Shortcut Node (B.G2).

LLM-bypass for *simple* questions. Genişletilmiş pattern seti:

  - COUNT       : "kaç ... var", "... sayısı", "toplam ... kaydı"
                  → SELECT COUNT(*) FROM t
  - TOP-N       : "en çok ...", "ilk N ...", "top N ..."
                  → SELECT * FROM t ORDER BY <metric> DESC LIMIT N
  - LATEST      : "en yeni ...", "son ... kayıt", "en güncel ..."
                  → SELECT * FROM t ORDER BY <date_col> DESC LIMIT 1|N
  - FILTER-EQ   : "X=5 olan ...", "<ad>=<deger> ..."
                  → SELECT * FROM t WHERE col = 'val' LIMIT N
  - GROUP-BY    : "<X> başına <Y> sayısı"
                  → SELECT x, COUNT(*) FROM t GROUP BY x LIMIT N

Kurallar (kullanıcı şartı):
  * confidence ≥ 0.85
  * tek tablo (selected_tables length=1)
  * tek filter (FILTER-EQ için maks. 1 koşul)

Dialect-aware limit: ast_query_builder._format_limit reuse edilir.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.pipeline.nodes.ast_query_builder import (
    DEFAULT_ROW_LIMIT,
    _format_limit,
    _format_table,
    _norm,
    _quote_identifier,
)

logger = logging.getLogger(__name__)


# Pattern thresholds
MIN_CONFIDENCE = 0.85

# Date column adı için heuristic
DATE_COL_HINTS = (
    "date", "tarih", "tarihi", "created", "created_at", "updated_at",
    "olusturma", "guncelleme", "_at", "_dt", "timestamp",
)

# Numeric (sortable) kolon adı hint
NUMERIC_HINTS = ("amount", "total", "tutar", "miktar", "fiyat", "price", "qty", "miktari", "count", "sayi")

# ID kolon adı hint
ID_HINTS = ("id", "kod", "code", "no", "_id")


# ─────────────────────────────────────────────────────────────
# Yardımcılar — kolon seçimi
# ─────────────────────────────────────────────────────────────

def _pick_column_by_hint(columns: List[Dict[str, Any]], hints: tuple) -> Optional[str]:
    """columns içinde adı `hints`'tan birini içeren ilk kolonu döndür."""
    for col in columns:
        name = (col.get("column_name") or col.get("name") or "").lower()
        if not name:
            continue
        for h in hints:
            if h in name:
                return name
    return None


def _pick_column_by_name(columns: List[Dict[str, Any]], wanted: str) -> Optional[str]:
    """Tam eşleşme/lower eşleşme veya partial match."""
    wanted_l = wanted.strip().lower()
    if not wanted_l:
        return None
    # Önce tam eşleşme
    for col in columns:
        name = (col.get("column_name") or col.get("name") or "")
        if name.lower() == wanted_l:
            return name
    # Sonra startswith / contains
    for col in columns:
        name = (col.get("column_name") or col.get("name") or "")
        nl = name.lower()
        if nl.startswith(wanted_l) or wanted_l in nl:
            return name
    return None


# ─────────────────────────────────────────────────────────────
# Regex pattern bank — confidence ile birlikte
# ─────────────────────────────────────────────────────────────

# COUNT: "kaç X var", "toplam X sayısı", "X kaydı sayısı"
_COUNT_RE = re.compile(
    r"\b(kac|kaç|toplam|sayisi|sayısı|count|adet|adedi)\b",
    re.IGNORECASE,
)

# TOP-N: "ilk 10", "top 5", "en yuksek 20", "en cok ... 50"
_TOPN_RE = re.compile(
    r"\b(ilk|top|en\s+(yuksek|büyük|buyuk|cok|çok|fazla))\b.*?(\d{1,4})",
    re.IGNORECASE | re.DOTALL,
)
_TOPN_FALLBACK_RE = re.compile(
    r"\b(en\s+(yuksek|büyük|buyuk|cok|çok|fazla))\b",
    re.IGNORECASE,
)

# LATEST: "en yeni", "son", "latest", "recent"
_LATEST_RE = re.compile(
    r"\b(en\s+(yeni|son|guncel|güncel)|son|latest|recent)\b",
    re.IGNORECASE,
)

# FILTER-EQ: "X=5", "X = 'abc'", "X eşit 5", "X olan 5"
_FILTER_EQ_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]{1,40})\s*[=:]\s*([\"']?)([A-Za-z0-9_\-\.]+)\2",
)

# GROUP-BY (basic): "<X> başına ... sayısı"
_GROUP_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]{1,40})\s+(basina|başına|per|göre|gore)\b",
    re.IGNORECASE,
)

# limit sayısı yakalama: "ilk 10", "top 5"
_NUMBER_RE = re.compile(r"\b(\d{1,5})\b")


# ─────────────────────────────────────────────────────────────
# Pattern detector — confidence ile birlikte
# ─────────────────────────────────────────────────────────────

def _detect_pattern(question: str) -> Tuple[Optional[str], float, Dict[str, Any]]:
    """Soruya en uygun pattern + confidence + ek parametreler.

    Returns:
      (pattern_name, confidence, params)
      pattern_name: 'COUNT' | 'TOP_N' | 'LATEST' | 'FILTER_EQ' | 'GROUP_BY' | None
    """
    q = _norm(question)
    if not q:
        return None, 0.0, {}

    # COUNT
    if _COUNT_RE.search(q):
        # "X kaç" / "kaç X" — count
        return "COUNT", 0.90, {}

    # TOP-N (with explicit number)
    m = _TOPN_RE.search(q)
    if m:
        try:
            n = int(m.group(3))
            if 1 <= n <= 10000:
                return "TOP_N", 0.92, {"n": n}
        except Exception:
            pass

    # LATEST
    if _LATEST_RE.search(q):
        n_match = _NUMBER_RE.search(q)
        n = int(n_match.group(1)) if n_match else 1
        n = max(1, min(n, 10000))
        return "LATEST", 0.88, {"n": n}

    # TOP_N fallback (en çok/en yüksek but no number) — use default
    if _TOPN_FALLBACK_RE.search(q):
        return "TOP_N", 0.86, {"n": DEFAULT_ROW_LIMIT}

    # GROUP_BY
    gm = _GROUP_RE.search(q)
    if gm:
        return "GROUP_BY", 0.86, {"group_col_hint": gm.group(1)}

    # FILTER_EQ (single equality)
    fm = _FILTER_EQ_RE.findall(q)
    # Birden fazla "x=y" yakalanırsa kullanıcı şartı tek-filter ihlal → atla
    if fm and len(fm) == 1:
        col_hint, _q, val = fm[0]
        return "FILTER_EQ", 0.87, {"col_hint": col_hint, "value": val}

    return None, 0.0, {}


# ─────────────────────────────────────────────────────────────
# SQL builders — pattern-spesifik
# ─────────────────────────────────────────────────────────────

def _build_count(table_ref: str, dialect: str) -> str:
    return f"SELECT COUNT(*) AS cnt FROM {table_ref}"


def _build_top_n(
    table_ref: str,
    columns: List[Dict[str, Any]],
    dialect: str,
    n: int,
) -> str:
    metric = (
        _pick_column_by_hint(columns, NUMERIC_HINTS)
        or _pick_column_by_hint(columns, DATE_COL_HINTS)
        or _pick_column_by_hint(columns, ID_HINTS)
    )
    if not metric:
        # Fallback: ilk kolonu sırala
        first = (columns[0].get("column_name") or columns[0].get("name")) if columns else None
        metric = first
    if not metric:
        # column metadata yok → ORDER BY atla
        if dialect == "mssql":
            return f"SELECT TOP {int(n)} * FROM {table_ref} ORDER BY (SELECT NULL)"
        return f"SELECT * FROM {table_ref} {_format_limit(int(n), dialect)}"

    qcol = _quote_identifier(metric, dialect)
    if dialect == "mssql":
        return f"SELECT TOP {int(n)} * FROM {table_ref} ORDER BY {qcol} DESC"
    return f"SELECT * FROM {table_ref} ORDER BY {qcol} DESC {_format_limit(int(n), dialect)}"


def _build_latest(
    table_ref: str,
    columns: List[Dict[str, Any]],
    dialect: str,
    n: int,
) -> str:
    date_col = _pick_column_by_hint(columns, DATE_COL_HINTS)
    if not date_col:
        # date kolonu yoksa AST shortcut'a uygun değil
        raise ValueError("LATEST için date kolonu bulunamadı")
    qcol = _quote_identifier(date_col, dialect)
    if dialect == "mssql":
        return f"SELECT TOP {int(n)} * FROM {table_ref} ORDER BY {qcol} DESC"
    return f"SELECT * FROM {table_ref} ORDER BY {qcol} DESC {_format_limit(int(n), dialect)}"


def _build_filter_eq(
    table_ref: str,
    columns: List[Dict[str, Any]],
    dialect: str,
    col_hint: str,
    value: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> str:
    col = _pick_column_by_name(columns, col_hint)
    if not col:
        raise ValueError(f"FILTER_EQ için kolon bulunamadı: {col_hint}")
    qcol = _quote_identifier(col, dialect)
    # Değer tipi: integer-like ise quote'suz, aksi halde quoted
    is_num = bool(re.fullmatch(r"-?\d+(\.\d+)?", value))
    safe_val = value if is_num else "'" + value.replace("'", "''") + "'"
    where = f"WHERE {qcol} = {safe_val}"
    if dialect == "mssql":
        return f"SELECT TOP {int(row_limit)} * FROM {table_ref} {where} ORDER BY (SELECT NULL)"
    return f"SELECT * FROM {table_ref} {where} {_format_limit(int(row_limit), dialect)}"


def _build_group_by(
    table_ref: str,
    columns: List[Dict[str, Any]],
    dialect: str,
    group_col_hint: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> str:
    col = _pick_column_by_name(columns, group_col_hint)
    if not col:
        raise ValueError(f"GROUP_BY için kolon bulunamadı: {group_col_hint}")
    qcol = _quote_identifier(col, dialect)
    if dialect == "mssql":
        return (
            f"SELECT TOP {int(row_limit)} {qcol} AS grp, COUNT(*) AS cnt "
            f"FROM {table_ref} GROUP BY {qcol} ORDER BY cnt DESC"
        )
    return (
        f"SELECT {qcol} AS grp, COUNT(*) AS cnt "
        f"FROM {table_ref} GROUP BY {qcol} ORDER BY cnt DESC "
        f"{_format_limit(int(row_limit), dialect)}"
    )


# ─────────────────────────────────────────────────────────────
# Node interface
# ─────────────────────────────────────────────────────────────

def is_shortcut_eligible(state: Dict[str, Any]) -> bool:
    """Tek tablo + kullanıcının `force_ast_shortcut=False` flag'i yoksa devreye girer."""
    if state.get("disable_ast_shortcut") is True:
        return False
    selected = state.get("selected_tables") or []
    if len(selected) != 1:
        return False
    cand = selected[0]
    if not cand.get("table_name"):
        return False
    return True


def ast_shortcut_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — pattern uyumu yakalanırsa SQL üret, aksi halde no-op.

    Returns state delta:
      * eşleşti → {'sql': str, 'sql_source': 'ast_shortcut',
                   'ast_pattern': str, 'ast_confidence': float}
      * eşleşmedi → {}
    """
    if not is_shortcut_eligible(state):
        return {}

    question = state.get("question") or ""
    pattern, confidence, params = _detect_pattern(question)
    if pattern is None or confidence < MIN_CONFIDENCE:
        return {}

    cand = (state.get("selected_tables") or [])[0]
    schema = cand.get("schema_name")
    table = cand.get("table_name")
    columns = cand.get("columns") or []
    dialect = (state.get("db_dialect") or "postgresql").lower()

    table_ref = _format_table(schema, table, dialect)

    try:
        if pattern == "COUNT":
            sql = _build_count(table_ref, dialect)
        elif pattern == "TOP_N":
            sql = _build_top_n(table_ref, columns, dialect, n=int(params.get("n", DEFAULT_ROW_LIMIT)))
        elif pattern == "LATEST":
            sql = _build_latest(table_ref, columns, dialect, n=int(params.get("n", 1)))
        elif pattern == "FILTER_EQ":
            sql = _build_filter_eq(
                table_ref, columns, dialect,
                col_hint=str(params.get("col_hint", "")),
                value=str(params.get("value", "")),
            )
        elif pattern == "GROUP_BY":
            sql = _build_group_by(
                table_ref, columns, dialect,
                group_col_hint=str(params.get("group_col_hint", "")),
            )
        else:
            return {}
    except ValueError as ve:
        # eksik kolon vs. → şanssız, normal pipeline'a düş
        logger.debug("[ast_shortcut] skip pattern=%s: %s", pattern, ve)
        return {}
    except Exception as e:
        logger.warning("[ast_shortcut] hata pattern=%s: %s", pattern, e)
        return {}

    return {
        "sql": sql,
        "sql_source": "ast_shortcut",
        "ast_pattern": pattern,
        "ast_confidence": confidence,
    }


__all__ = [
    "ast_shortcut_node",
    "is_shortcut_eligible",
    "MIN_CONFIDENCE",
]
