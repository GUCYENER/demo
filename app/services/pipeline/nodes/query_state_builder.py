"""
v3.28.3 G4 — Query State → SQL builder
======================================
Pre-execute Drag-Drop Query Builder backend yardımcısı.

Kullanıcı drag-drop UI ile bir "query state" oluşturur:
    {
        "source_id": 5,
        "schema": "public",
        "table": "orders",
        "dialect": "postgresql",
        "selected_columns": ["id", "customer_id", "total"],   # SELECT clause sırası
        "filters": [                                          # WHERE (AND birleştirilir)
            {"column": "status", "op": "=", "value": "PAID"},
            {"column": "total", "op": ">", "value": 100},
        ],
        "order_by": {"column": "created_at", "direction": "DESC"},
        "limit": 50
    }

build_sql_from_state(state) → {"sql": str, "params": list, "dialect": str, "warnings": [str]}

Güvenlik:
    - SADECE whitelist'lenmiş operatörler: = != < <= > >= LIKE ILIKE IS NULL IS NOT NULL IN
    - Identifier (table/schema/column) için _is_safe_identifier() — alfanumerik + _
    - Values parametrize (psycopg2 %s / sqlglot benzeri) — string concat yok
    - LIMIT [1..10000] clamp
    - Sadece SELECT üretir (DML yasak; bu modül başka SQL üretmez)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.pipeline.nodes.ast_query_builder import (
    _format_limit,
    _format_table,
    _quote_identifier,
)

# Whitelist
_ALLOWED_OPS = {
    "=", "!=", "<>", "<", "<=", ">", ">=",
    "LIKE", "ILIKE", "NOT LIKE",
    "IS NULL", "IS NOT NULL",
    "IN", "NOT IN",
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_MAX_COLUMNS = 50
_MAX_FILTERS = 20
_MIN_LIMIT, _MAX_LIMIT = 1, 10000
_DEFAULT_LIMIT = 100


def _is_safe_identifier(name: Any) -> bool:
    """SQL identifier whitelist — alfanumerik + underscore, max 63 char."""
    if not isinstance(name, str):
        return False
    return bool(_IDENT_RE.match(name))


def _normalize_op(op: Any) -> Optional[str]:
    if not isinstance(op, str):
        return None
    norm = op.strip().upper()
    if norm in _ALLOWED_OPS:
        return norm
    return None


def _validate_filter(f: Dict[str, Any], warnings: List[str], idx: int) -> Optional[Tuple[str, str, Any]]:
    """Tek filter doğrula — (column, op, value) veya None."""
    if not isinstance(f, dict):
        warnings.append(f"filter[{idx}]: dict bekleniyor")
        return None
    col = f.get("column")
    op = _normalize_op(f.get("op"))
    if not _is_safe_identifier(col):
        warnings.append(f"filter[{idx}]: geçersiz kolon adı")
        return None
    if op is None:
        warnings.append(f"filter[{idx}]: geçersiz operatör '{f.get('op')}'")
        return None
    val = f.get("value")
    # IS NULL / IS NOT NULL — value gereksiz
    if op in ("IS NULL", "IS NOT NULL"):
        return (col, op, None)
    # IN / NOT IN — list bekleniyor
    if op in ("IN", "NOT IN"):
        if not isinstance(val, (list, tuple)) or not val:
            warnings.append(f"filter[{idx}]: {op} için non-empty list gerekir")
            return None
        if len(val) > 100:
            warnings.append(f"filter[{idx}]: {op} listesi >100 → 100'e kırpıldı")
            val = list(val)[:100]
        return (col, op, list(val))
    # Diğerleri: scalar
    if val is None:
        warnings.append(f"filter[{idx}]: '{op}' için value gerekli")
        return None
    if isinstance(val, (dict, list, tuple)):
        warnings.append(f"filter[{idx}]: scalar value bekleniyor")
        return None
    return (col, op, val)


def _build_where(filters: List[Dict[str, Any]], dialect: str, warnings: List[str]) -> Tuple[str, List[Any]]:
    """WHERE clause + params list üretir."""
    if not filters:
        return "", []
    if len(filters) > _MAX_FILTERS:
        warnings.append(f"filters: >{_MAX_FILTERS} → ilk {_MAX_FILTERS} alındı")
        filters = filters[:_MAX_FILTERS]

    parts: List[str] = []
    params: List[Any] = []
    for i, f in enumerate(filters):
        v = _validate_filter(f, warnings, i)
        if not v:
            continue
        col, op, val = v
        qc = _quote_identifier(col, dialect)
        if op in ("IS NULL", "IS NOT NULL"):
            parts.append(f"{qc} {op}")
        elif op in ("IN", "NOT IN"):
            placeholders = ", ".join(["%s"] * len(val))
            parts.append(f"{qc} {op} ({placeholders})")
            params.extend(val)
        else:
            parts.append(f"{qc} {op} %s")
            params.append(val)

    if not parts:
        return "", []
    return "WHERE " + " AND ".join(parts), params


def _build_select_list(columns: List[Any], dialect: str, warnings: List[str]) -> str:
    if not columns:
        return "*"
    if len(columns) > _MAX_COLUMNS:
        warnings.append(f"selected_columns: >{_MAX_COLUMNS} → ilk {_MAX_COLUMNS} alındı")
        columns = columns[:_MAX_COLUMNS]
    safe: List[str] = []
    for c in columns:
        if _is_safe_identifier(c):
            safe.append(_quote_identifier(c, dialect))
        else:
            warnings.append(f"selected_columns: geçersiz kolon '{c}' atlandı")
    return ", ".join(safe) if safe else "*"


def _build_order(order_by: Optional[Dict[str, Any]], dialect: str, warnings: List[str]) -> Optional[str]:
    if not order_by or not isinstance(order_by, dict):
        return None
    col = order_by.get("column")
    direction = (order_by.get("direction") or "ASC").upper()
    if direction not in ("ASC", "DESC"):
        warnings.append(f"order_by.direction: geçersiz '{order_by.get('direction')}', ASC kullanılıyor")
        direction = "ASC"
    if not _is_safe_identifier(col):
        warnings.append(f"order_by.column: geçersiz '{col}' atlandı")
        return None
    return f"ORDER BY {_quote_identifier(col, dialect)} {direction}"


def _clamp_limit(limit: Any, warnings: List[str]) -> int:
    try:
        n = int(limit) if limit is not None else _DEFAULT_LIMIT
    except (TypeError, ValueError):
        warnings.append(f"limit: sayı değil ({limit!r}), default {_DEFAULT_LIMIT} kullanıldı")
        return _DEFAULT_LIMIT
    if n < _MIN_LIMIT:
        warnings.append(f"limit: <{_MIN_LIMIT} → {_MIN_LIMIT}")
        return _MIN_LIMIT
    if n > _MAX_LIMIT:
        warnings.append(f"limit: >{_MAX_LIMIT} → {_MAX_LIMIT}")
        return _MAX_LIMIT
    return n


def build_sql_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Drag-Drop UI'dan gelen query state → parametrize SELECT SQL.

    Returns:
        {
            "sql": str,                  # Parametrize SQL (psycopg2 %s)
            "params": List[Any],         # Filter değerleri sırayla
            "dialect": str,              # 'postgresql' | 'mssql' | 'mysql' | 'oracle'
            "warnings": List[str],       # Kullanıcıya gösterilecek non-fatal uyarılar
            "valid": bool,               # True iff sql üretildi
        }
    """
    warnings: List[str] = []

    if not isinstance(state, dict):
        return {"sql": None, "params": [], "dialect": None, "warnings": ["state: dict bekleniyor"], "valid": False}

    table = state.get("table")
    schema = state.get("schema")
    dialect = (state.get("dialect") or "postgresql").lower()

    if not _is_safe_identifier(table):
        return {"sql": None, "params": [], "dialect": dialect,
                "warnings": ["table: geçersiz veya eksik tablo adı"], "valid": False}
    if schema is not None and schema != "" and not _is_safe_identifier(schema):
        return {"sql": None, "params": [], "dialect": dialect,
                "warnings": ["schema: geçersiz şema adı"], "valid": False}

    select_list = _build_select_list(state.get("selected_columns") or [], dialect, warnings)
    table_ref = _format_table(schema if schema else None, table, dialect)
    where_clause, params = _build_where(state.get("filters") or [], dialect, warnings)
    order_clause = _build_order(state.get("order_by"), dialect, warnings)
    limit = _clamp_limit(state.get("limit"), warnings)

    parts = [f"SELECT {select_list}", f"FROM {table_ref}"]
    if where_clause:
        parts.append(where_clause)
    if order_clause:
        parts.append(order_clause)
        parts.append(_format_limit(limit, dialect))
    else:
        if dialect == "mssql":
            parts.append("ORDER BY (SELECT NULL)")
        parts.append(_format_limit(limit, dialect))

    sql = "\n".join(parts)
    return {"sql": sql, "params": params, "dialect": dialect, "warnings": warnings, "valid": True}
