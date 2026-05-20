"""AST node tree + 4 dialect render + RLS guard (v3.30.0 FAZ 1 G1.5).

AST yapısı (JSON-safe — dbsmart_sessions.context snapshot için):
    {
      "type": "select",
      "with": [ {"name": "...", "ast": {...}}, ... ],          # opsiyonel CTE
      "columns": [ {"expr": "...", "alias": "..."}, ... ],
      "from": {"schema": "...", "table": "...", "alias": "..."},
      "joins": [ {"kind": "INNER|LEFT|RIGHT|FULL",
                  "table": {"schema": "...", "table": "...", "alias": "..."},
                  "on": [ {"left": "a.id", "op": "=", "right": "b.a_id"} ]}, ... ],
      "filters": [ {"expr": "...", "op": "=|!=|>|<|>=|<=|LIKE|IN|IS NULL|...",
                    "value": <Python> | placeholder, "bind": "name"}, ... ],
      "group_by": ["col", ...],
      "having": [ ... aynı filtre yapısı ... ],
      "order_by": [ {"expr": "...", "dir": "ASC|DESC"} ],
      "limit": int | None,
      "offset": int | None,
    }

GÜVENLİK:
    1. Identifier whitelist: [A-Za-z_][A-Za-z0-9_]* + nokta (schema.table.col).
    2. Operatör whitelist: ALLOWED_OPS (SQL-injection guard).
    3. Değerler ASLA string-concat ile yerleştirilmez — sadece named bind (%(name)s).
    4. inject_rls atlanamaz; final SQL üretiminden hemen önce çağrılır.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SUPPORTED_DIALECTS = ("postgresql", "oracle", "mssql", "mysql")

# Identifier ve operatör whitelist'leri (SQL injection guard)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUALIFIED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")

ALLOWED_OPS = {
    "=", "!=", "<>", "<", "<=", ">", ">=",
    "LIKE", "ILIKE", "NOT LIKE", "NOT ILIKE",
    "IN", "NOT IN",
    "IS NULL", "IS NOT NULL",
    "BETWEEN", "NOT BETWEEN",
}

ALLOWED_JOINS = {"INNER", "LEFT", "RIGHT", "FULL", "LEFT OUTER", "RIGHT OUTER", "FULL OUTER"}


# ─────────────────────────────────────────────────────────────
# Dialect dictionary
# ─────────────────────────────────────────────────────────────

_DIALECT = {
    "postgresql": {
        "quote_open": '"', "quote_close": '"',
        "limit_style": "limit_offset",   # LIMIT n OFFSET m
        "param_style": "pyformat",       # %(name)s
    },
    "mysql": {
        "quote_open": "`", "quote_close": "`",
        "limit_style": "limit_offset",
        "param_style": "pyformat",
    },
    "oracle": {
        "quote_open": '"', "quote_close": '"',
        "limit_style": "fetch_first",    # OFFSET m ROWS FETCH NEXT n ROWS ONLY
        "param_style": "named",          # :name
    },
    "mssql": {
        "quote_open": "[", "quote_close": "]",
        "limit_style": "top",            # TOP (n) — basit; OFFSET/FETCH 2012+
        "param_style": "named",          # @name
    },
}


# ─────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────

def _validate_ident(ident: str, *, allow_star: bool = False) -> str:
    """Identifier whitelist guard. allow_star=True ise '*' veya 'tbl.*' geçer."""
    if not isinstance(ident, str) or not ident.strip():
        raise ValueError(f"Invalid identifier (empty)")
    s = ident.strip()
    if allow_star:
        if s == "*":
            return s
        if s.endswith(".*"):
            head = s[:-2]
            if _QUALIFIED_RE.match(head):
                return s
    if not _QUALIFIED_RE.match(s):
        raise ValueError(f"Invalid identifier: {ident!r}")
    return s


def _validate_op(op: str) -> str:
    norm = op.strip().upper()
    if norm not in ALLOWED_OPS:
        raise ValueError(f"Operator not allowed: {op!r}")
    return norm


def _validate_join_kind(kind: str) -> str:
    norm = (kind or "INNER").strip().upper()
    if norm not in ALLOWED_JOINS:
        raise ValueError(f"Join kind not allowed: {kind!r}")
    return norm


def _q(dialect: str, ident: str) -> str:
    """Identifier quoting (whitelist'ten geçmiş ident için)."""
    d = _DIALECT[dialect]
    parts = ident.split(".")
    return ".".join(f"{d['quote_open']}{p}{d['quote_close']}" if p != "*" else "*" for p in parts)


def _placeholder(dialect: str, name: str) -> str:
    style = _DIALECT[dialect]["param_style"]
    if style == "pyformat":
        return f"%({name})s"
    if style == "named":
        # Oracle :name, MSSQL @name → backend katmanı normalize eder
        prefix = ":" if dialect == "oracle" else "@"
        return f"{prefix}{name}"
    raise ValueError(f"Unknown param_style: {style}")


# ─────────────────────────────────────────────────────────────
# Bind counter helper
# ─────────────────────────────────────────────────────────────

class _RenderCtx:
    def __init__(self, dialect: str, user_ctx: Optional[Dict[str, Any]] = None):
        self.dialect = dialect
        self.user_ctx = user_ctx or {}
        self.binds: Dict[str, Any] = {}
        self._counter = 0

    def add_bind(self, value: Any, *, hint: str = "p") -> str:
        self._counter += 1
        name = f"{hint}_{self._counter}"
        self.binds[name] = value
        return _placeholder(self.dialect, name)


# ─────────────────────────────────────────────────────────────
# Render parts
# ─────────────────────────────────────────────────────────────

def _render_table_ref(d: str, ref: Dict[str, Any]) -> str:
    schema = ref.get("schema")
    table = ref.get("table")
    alias = ref.get("alias")
    if not table:
        raise ValueError("Table ref missing 'table'")
    _validate_ident(table)
    if schema:
        _validate_ident(schema)
        base = f"{_q(d, schema)}.{_q(d, table)}"
    else:
        base = _q(d, table)
    if alias:
        _validate_ident(alias)
        base = f"{base} {_q(d, alias)}"
    return base


def _render_column(d: str, col: Dict[str, Any]) -> str:
    expr = col.get("expr") or col.get("column")
    if not expr:
        raise ValueError("Column missing 'expr'")
    _validate_ident(expr, allow_star=True)
    out = _q(d, expr) if expr != "*" and not expr.endswith(".*") else expr
    alias = col.get("alias")
    if alias:
        _validate_ident(alias)
        out = f"{out} AS {_q(d, alias)}"
    return out


def _render_filter(ctx: _RenderCtx, f: Dict[str, Any]) -> str:
    d = ctx.dialect
    expr = f.get("expr") or f.get("column")
    if not expr:
        raise ValueError("Filter missing 'expr'")
    _validate_ident(expr)
    op = _validate_op(f.get("op", "="))

    if op in ("IS NULL", "IS NOT NULL"):
        return f"{_q(d, expr)} {op}"

    if op in ("IN", "NOT IN"):
        values = f.get("value")
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError("IN/NOT IN requires non-empty list value")
        placeholders = [ctx.add_bind(v, hint="in") for v in values]
        return f"{_q(d, expr)} {op} ({', '.join(placeholders)})"

    if op in ("BETWEEN", "NOT BETWEEN"):
        value = f.get("value")
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("BETWEEN requires [lo, hi] list value")
        a = ctx.add_bind(value[0], hint="lo")
        b = ctx.add_bind(value[1], hint="hi")
        return f"{_q(d, expr)} {op} {a} AND {b}"

    # Standard binary op
    value = f.get("value")
    ph = ctx.add_bind(value, hint="v")
    return f"{_q(d, expr)} {op} {ph}"


def _render_join(ctx: _RenderCtx, j: Dict[str, Any]) -> str:
    d = ctx.dialect
    kind = _validate_join_kind(j.get("kind", "INNER"))
    table_sql = _render_table_ref(d, j.get("table") or {})
    on = j.get("on") or []
    if not on:
        raise ValueError("JOIN missing 'on' clauses")
    conds: List[str] = []
    for c in on:
        left = c.get("left")
        right = c.get("right")
        cop = _validate_op(c.get("op", "="))
        if not left or not right:
            raise ValueError("JOIN ON requires left+right identifiers")
        _validate_ident(left)
        _validate_ident(right)
        conds.append(f"{_q(d, left)} {cop} {_q(d, right)}")
    return f"{kind} JOIN {table_sql} ON {' AND '.join(conds)}"


def _render_order(d: str, o: Dict[str, Any]) -> str:
    expr = o.get("expr") or o.get("column")
    if not expr:
        raise ValueError("ORDER BY missing 'expr'")
    _validate_ident(expr)
    direction = (o.get("dir") or "ASC").strip().upper()
    if direction not in ("ASC", "DESC"):
        raise ValueError(f"Invalid order direction: {direction!r}")
    return f"{_q(d, expr)} {direction}"


def _render_limit_offset(d: str, limit: Optional[int], offset: Optional[int]) -> Tuple[str, str]:
    """Return (top_clause_for_mssql, suffix_clause).

    MSSQL kuralı: TOP ve OFFSET/FETCH aynı sorguda kullanılamaz.
        offset yoksa  → `TOP (n)`
        offset varsa  → `OFFSET m ROWS FETCH NEXT n ROWS ONLY` (gerekiyorsa ORDER BY caller'da).
    """
    style = _DIALECT[d]["limit_style"]
    top = ""
    suffix = ""
    if style == "limit_offset":
        if limit is not None:
            suffix = f" LIMIT {int(limit)}"
        if offset:
            suffix += f" OFFSET {int(offset)}"
    elif style == "fetch_first":
        if offset:
            suffix = f" OFFSET {int(offset)} ROWS"
        if limit is not None:
            suffix += f" FETCH NEXT {int(limit)} ROWS ONLY"
    elif style == "top":
        # MSSQL: TOP ile OFFSET/FETCH karıştırılamaz → offset varsa OFFSET/FETCH'e geç
        if offset:
            suffix = f" OFFSET {int(offset)} ROWS"
            if limit is not None:
                suffix += f" FETCH NEXT {int(limit)} ROWS ONLY"
        elif limit is not None:
            top = f"TOP ({int(limit)}) "
    return top, suffix


# ─────────────────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────────────────

def render(
    ast: Dict[str, Any],
    dialect: str,
    user_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """AST → {sql, binds, dialect}. (FAZ 0 imzasından geri-uyumlu değiştirildi —
    eski caller `render(...)`'dan dict bekleyecek.)
    """
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(f"Unsupported dialect: {dialect}")
    if not isinstance(ast, dict) or ast.get("type") != "select":
        raise ValueError("AST root must be type=select")

    ctx = _RenderCtx(dialect, user_ctx)
    parts: List[str] = []

    # WITH (CTE)
    with_list = ast.get("with") or []
    if with_list:
        cte_strs = []
        for cte in with_list:
            name = cte.get("name")
            if not name:
                raise ValueError("CTE missing 'name'")
            _validate_ident(name)
            inner = render(cte["ast"], dialect, user_ctx)
            cte_strs.append(f"{_q(dialect, name)} AS ({inner['sql']})")
            ctx.binds.update(inner["binds"])
        parts.append("WITH " + ", ".join(cte_strs))

    # SELECT [TOP n] cols
    top, limit_suffix = _render_limit_offset(dialect, ast.get("limit"), ast.get("offset"))
    cols = ast.get("columns") or []
    if not cols:
        raise ValueError("SELECT requires at least one column")
    col_sqls = [_render_column(dialect, c) for c in cols]
    parts.append(f"SELECT {top}" + ", ".join(col_sqls))

    # FROM
    from_ref = ast.get("from")
    if not from_ref:
        raise ValueError("AST missing 'from'")
    parts.append(f"FROM {_render_table_ref(dialect, from_ref)}")

    # JOINs
    for j in ast.get("joins") or []:
        parts.append(_render_join(ctx, j))

    # WHERE
    filters = ast.get("filters") or []
    if filters:
        where_parts = [_render_filter(ctx, f) for f in filters]
        parts.append("WHERE " + " AND ".join(where_parts))

    # GROUP BY
    gb = ast.get("group_by") or []
    if gb:
        for g in gb:
            _validate_ident(g)
        parts.append("GROUP BY " + ", ".join(_q(dialect, g) for g in gb))

    # HAVING
    having = ast.get("having") or []
    if having:
        having_parts = [_render_filter(ctx, f) for f in having]
        parts.append("HAVING " + " AND ".join(having_parts))

    # ORDER BY
    ob = ast.get("order_by") or []
    if ob:
        parts.append("ORDER BY " + ", ".join(_render_order(dialect, o) for o in ob))

    # LIMIT/OFFSET (TOP zaten SELECT'te)
    sql = " ".join(parts) + limit_suffix

    return {"sql": sql, "binds": ctx.binds, "dialect": dialect}


# ─────────────────────────────────────────────────────────────
# RLS injection
# ─────────────────────────────────────────────────────────────

def inject_rls(
    ast: Dict[str, Any],
    user_ctx: Dict[str, Any],
    company_scoped_tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """LLM atlamış olsa bile son adımda RLS predicate'ini AST'e enjekte et.

    - `company_scoped_tables`: caller'ın belirlediği (örn. column-meta'dan tespit
      edilmiş) `company_id` kolonu bulunan tablo alias listesi.
    - is_admin=True ise predicate eklenmez (admin tüm tenant'ları görebilir).
    - Eğer hiçbir tablo company-scoped değilse no-op.
    """
    if not isinstance(ast, dict):
        return ast
    if user_ctx.get("is_admin") or user_ctx.get("role") == "admin":
        return ast
    company_id = user_ctx.get("company_id")
    if company_id is None or not company_scoped_tables:
        return ast

    filters = list(ast.get("filters") or [])
    for alias in company_scoped_tables:
        if not _QUALIFIED_RE.match(alias):
            continue
        # alias.company_id = <company_id>
        filters.append({
            "expr": f"{alias}.company_id",
            "op": "=",
            "value": int(company_id),
        })
    new_ast = dict(ast)
    new_ast["filters"] = filters
    new_ast["_rls_injected"] = True
    return new_ast


# ─────────────────────────────────────────────────────────────
# Serialize/deserialize
# ─────────────────────────────────────────────────────────────

def serialize_json(ast: Dict[str, Any]) -> Dict[str, Any]:
    """dbsmart_sessions.context içine snapshot için JSON-safe çıktı."""
    return ast or {}


def deserialize_json(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot'tan AST geri yükle."""
    return snapshot or {}
