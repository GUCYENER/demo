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

def _auto_detect_company_scoped_aliases(ast: Dict[str, Any]) -> List[str]:
    """AST'in from + joins yapısından alias listesi türet (defansif RLS için).

    F-021 (ARES KRİTİK) — defansif derinlik: caller `inject_rls`'i atlasa bile
    `render()` non-admin için otomatik enjekte etsin. Heuristic: tüm tablo
    alias'larını company-scoped say (over-restrictive ama güvenli). is_admin
    user için `inject_rls` zaten no-op döner.
    """
    aliases: List[str] = []
    if not isinstance(ast, dict):
        return aliases
    src = ast.get("from")
    if isinstance(src, dict):
        a = src.get("alias") or src.get("table")
        if isinstance(a, str) and a:
            aliases.append(a)
    joins = ast.get("joins") or []
    if isinstance(joins, list):
        for j in joins:
            if not isinstance(j, dict):
                continue
            tbl = j.get("table")
            if isinstance(tbl, dict):
                a = tbl.get("alias") or tbl.get("table")
            else:
                a = j.get("alias") or (tbl if isinstance(tbl, str) else None)
            if isinstance(a, str) and a:
                aliases.append(a)
    # Dedup, preserve order
    seen: set = set()
    out: List[str] = []
    for a in aliases:
        if a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def render(
    ast: Dict[str, Any],
    dialect: str,
    user_ctx: Optional[Dict[str, Any]] = None,
    *,
    _rls_already_injected: bool = False,
) -> Dict[str, Any]:
    """AST → {sql, binds, dialect}. (FAZ 0 imzasından geri-uyumlu değiştirildi —
    eski caller `render(...)`'dan dict bekleyecek.)

    F-021 (ARES KRİTİK) — defense-in-depth: non-admin user_ctx için render
    `inject_rls`'i otomatik çağırır (caller'ın eklediği `_rls_injected=True`
    marker'ı varsa veya `_rls_already_injected=True` kwarg'ı verildiyse atlar).
    inject_rls idempotent — double-inject güvenli (predicate-set dedup'ı
    `optimize_ast` veya DB tarafında zaten gerçekleşir; burada koruyucu skip
    flag bağlamı için kullanılır).
    """
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(f"Unsupported dialect: {dialect}")
    if not isinstance(ast, dict) or ast.get("type") != "select":
        raise ValueError("AST root must be type=select")

    # Defense-in-depth RLS auto-injection.
    # Skip cases:
    #   1. Explicit kwarg `_rls_already_injected=True` (caller pre-injected,
    #      e.g. db_smart_api.py /ast/patch render_preview path).
    #   2. AST already carries `_rls_injected=True` marker from a prior
    #      inject_rls call (idempotency guard).
    #   3. user_ctx missing / admin / role=admin → inject_rls itself no-ops.
    # If skip conditions not met, call inject_rls with heuristic alias list.
    if (
        not _rls_already_injected
        and not ast.get("_rls_injected")
        and isinstance(user_ctx, dict)
        and not (user_ctx.get("is_admin") or user_ctx.get("role") == "admin")
    ):
        aliases = _auto_detect_company_scoped_aliases(ast)
        if aliases and user_ctx.get("company_id") is not None:
            ast = inject_rls(ast, user_ctx, company_scoped_tables=aliases)

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
            # CTE inner render: outer'da RLS auto-injected oldu; CTE'nin kendi
            # AST'i de defansif olarak işlensin — ama recursion guard için
            # `_rls_already_injected` flag'ini *forward etmiyoruz* (CTE
            # bağımsız AST). inject_rls idempotent.
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
    # Idempotency: predicate-level dedup. Same (alias.company_id = value)
    # triple already present → skip (double-inject safe).
    company_id_int = int(company_id)
    existing_keys = {
        (
            (f.get("expr") or f.get("column") or ""),
            (f.get("op") or "=").strip().upper(),
            f.get("value"),
        )
        for f in filters
        if isinstance(f, dict)
    }
    for alias in company_scoped_tables:
        if not _QUALIFIED_RE.match(alias):
            continue
        expr = f"{alias}.company_id"
        key = (expr, "=", company_id_int)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        # alias.company_id = <company_id>
        filters.append({
            "expr": expr,
            "op": "=",
            "value": company_id_int,
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


# ─────────────────────────────────────────────────────────────
# FAZ 2 G2.1 — AST manipulation API (drag-drop refinement)
# ─────────────────────────────────────────────────────────────
# Bu API frontend drag-drop tarafından çağrılacak. Tüm fonksiyonlar:
#   - immutable (yeni dict döner, kaynağa dokunmaz)
#   - identifier whitelist guard'ından geçer (_validate_ident)
#   - alias-bazlı silme/yer-değiştirme — collision'da ValueError
#   - state machine context'iyle uyumlu (dbsmart_sessions.context.ast snapshot)

def _require_select(ast: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(ast, dict) or ast.get("type") != "select":
        raise ValueError("AST root must be type=select")
    return dict(ast)


def add_column(
    ast: Dict[str, Any],
    column: Dict[str, Any],
) -> Dict[str, Any]:
    """SELECT listesine sütun ekle (duplicate-safe, immutable)."""
    new_ast = _require_select(ast)
    expr = column.get("expr") or column.get("column")
    if not expr:
        raise ValueError("add_column: 'expr' zorunlu")
    _validate_ident(expr, allow_star=True)
    alias = column.get("alias")
    if alias:
        _validate_ident(alias)
    cols = list(new_ast.get("columns") or [])
    # Aynı expr+alias varsa no-op
    key = (expr, alias)
    if any((c.get("expr") or c.get("column"), c.get("alias")) == key for c in cols):
        return new_ast
    cols.append({"expr": expr, **({"alias": alias} if alias else {})})
    new_ast["columns"] = cols
    return new_ast


def remove_column(
    ast: Dict[str, Any],
    *,
    expr: Optional[str] = None,
    alias: Optional[str] = None,
) -> Dict[str, Any]:
    """SELECT'ten sütun çıkar. expr veya alias eşleşmesi yeterli."""
    if not expr and not alias:
        raise ValueError("remove_column: expr veya alias verilmeli")
    new_ast = _require_select(ast)
    cols = list(new_ast.get("columns") or [])
    if not cols:
        return new_ast
    kept = []
    for c in cols:
        c_expr = c.get("expr") or c.get("column")
        c_alias = c.get("alias")
        if (expr and c_expr == expr) or (alias and c_alias == alias):
            continue
        kept.append(c)
    # Son sütun da silinemez — render boş SELECT'i reddediyor.
    if not kept:
        raise ValueError("remove_column: en az bir sütun kalmalı")
    new_ast["columns"] = kept
    return new_ast


def add_filter(
    ast: Dict[str, Any],
    filt: Dict[str, Any],
) -> Dict[str, Any]:
    """WHERE listesine filtre ekle. Mevcut optimize_ast dedup'ı sonraki adımda zaten çalışır."""
    if not isinstance(filt, dict):
        raise ValueError("add_filter: filt dict olmalı")
    expr = filt.get("expr") or filt.get("column")
    if not expr:
        raise ValueError("add_filter: 'expr' zorunlu")
    _validate_ident(expr)
    _validate_op(filt.get("op", "="))
    new_ast = _require_select(ast)
    fl = list(new_ast.get("filters") or [])
    fl.append(filt)
    new_ast["filters"] = fl
    return new_ast


def remove_filter(
    ast: Dict[str, Any],
    *,
    expr: Optional[str] = None,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    """Filtre sil — expr (tüm eşleşenler) veya index ile."""
    if expr is None and index is None:
        raise ValueError("remove_filter: expr veya index verilmeli")
    new_ast = _require_select(ast)
    fl = list(new_ast.get("filters") or [])
    if index is not None:
        if index < 0 or index >= len(fl):
            raise ValueError(f"remove_filter: index {index} out of range")
        fl.pop(index)
    else:
        fl = [f for f in fl if (f.get("expr") or f.get("column")) != expr]
    new_ast["filters"] = fl
    return new_ast


def modify_join(
    ast: Dict[str, Any],
    alias: str,
    *,
    kind: Optional[str] = None,
    on: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """JOIN'in kind veya ON koşullarını değiştir (alias'a göre)."""
    if not alias:
        raise ValueError("modify_join: alias zorunlu")
    _validate_ident(alias)
    new_ast = _require_select(ast)
    joins = list(new_ast.get("joins") or [])
    if not joins:
        raise ValueError(f"modify_join: '{alias}' JOIN bulunamadı")
    found = False
    new_joins = []
    for j in joins:
        tbl = j.get("table") or {}
        if tbl.get("alias") == alias:
            nj = dict(j)
            if kind is not None:
                nj["kind"] = _validate_join_kind(kind)
            if on is not None:
                if not isinstance(on, list) or not on:
                    raise ValueError("modify_join: 'on' boş olamaz")
                for c in on:
                    if not c.get("left") or not c.get("right"):
                        raise ValueError("modify_join: ON left+right zorunlu")
                    _validate_ident(c["left"])
                    _validate_ident(c["right"])
                    _validate_op(c.get("op", "="))
                nj["on"] = list(on)
            new_joins.append(nj)
            found = True
        else:
            new_joins.append(j)
    if not found:
        raise ValueError(f"modify_join: alias '{alias}' bulunamadı")
    new_ast["joins"] = new_joins
    return new_ast


def reorder_by(
    ast: Dict[str, Any],
    order_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """ORDER BY'i tamamen değiştir (frontend drag-drop replace pattern'i)."""
    if not isinstance(order_list, list):
        raise ValueError("reorder_by: order_list list olmalı")
    new_ast = _require_select(ast)
    valid = []
    for o in order_list:
        if not isinstance(o, dict):
            continue
        expr = o.get("expr") or o.get("column")
        if not expr:
            raise ValueError("reorder_by: 'expr' zorunlu")
        _validate_ident(expr)
        direction = (o.get("dir") or "ASC").strip().upper()
        if direction not in ("ASC", "DESC"):
            raise ValueError(f"reorder_by: invalid dir {direction!r}")
        valid.append({"expr": expr, "dir": direction})
    new_ast["order_by"] = valid
    return new_ast


def reorder_columns(
    ast: Dict[str, Any],
    order: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """SELECT listesini yeniden sırala (drag-drop için).

    `order` her item'i `{expr?, alias?}` formatında; mevcut SELECT
    kolonlarıyla `expr` veya `alias` üzerinden eşleştirilir. Hiçbir
    kolon eklenmez / silinmez — eşleşmeyen item atlanır; mevcut SELECT'te
    kalan ama `order`'da bulunmayan kolonlar sona eklenir (stable).

    immutable: kaynak `ast` değişmez.
    """
    if not isinstance(order, list):
        raise ValueError("reorder_columns: order list olmalı")
    new_ast = _require_select(ast)
    cols = list(new_ast.get("columns") or [])
    if not cols:
        return new_ast

    def _key(c: Dict[str, Any]) -> Tuple[str, str]:
        return (c.get("expr") or c.get("column") or "", c.get("alias") or "")

    # Index-based remaining tracker — duplicate (expr,alias) key'lere karşı dayanıklı
    # (add_column idempotent guard'ı bunu engellese de defensive).
    remaining_idx: List[int] = list(range(len(cols)))
    new_cols: List[Dict[str, Any]] = []
    for item in order:
        if not isinstance(item, dict):
            continue
        k_expr = item.get("expr") or item.get("column") or ""
        k_alias = item.get("alias") or ""
        # Exact match (expr+alias) öncelikli; alias verilmediyse expr eşleşmesi
        match_idx = None
        for i in remaining_idx:
            ck = _key(cols[i])
            if ck == (k_expr, k_alias) or (not k_alias and ck[0] == k_expr):
                match_idx = i
                break
        if match_idx is not None:
            new_cols.append(cols[match_idx])
            remaining_idx.remove(match_idx)
    # Eksik kalanları orijinal sırayla sona ekle (stable)
    for i in remaining_idx:
        new_cols.append(cols[i])
    if not new_cols:
        raise ValueError("reorder_columns: en az bir sütun kalmalı")
    new_ast["columns"] = new_cols
    return new_ast


def set_limit(
    ast: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """LIMIT/OFFSET ata. None → temizle. Negatif değer → ValueError."""
    new_ast = _require_select(ast)
    if limit is not None:
        if not isinstance(limit, int) or limit < 0:
            raise ValueError("set_limit: limit non-negative int olmalı")
        new_ast["limit"] = limit
    else:
        new_ast.pop("limit", None)
    if offset is not None:
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("set_limit: offset non-negative int olmalı")
        new_ast["offset"] = offset
    else:
        new_ast.pop("offset", None)
    return new_ast


# ─────────────────────────────────────────────────────────────
# Step 4 — Safe AST optimizations
# ─────────────────────────────────────────────────────────────

def _filter_key(f: Dict[str, Any]) -> Tuple:
    """Hashable key for filter dedup. value/list → tuple for IN/BETWEEN."""
    expr = f.get("expr") or f.get("column") or ""
    op = (f.get("op") or "=").strip().upper()
    val = f.get("value")
    if isinstance(val, list):
        val = ("__list__", tuple(val))
    elif isinstance(val, dict):
        val = ("__dict__", tuple(sorted(val.items())))
    return (expr, op, val)


def _join_key(j: Dict[str, Any]) -> Tuple:
    """Hashable key for join dedup (kind + table ref + ON conds)."""
    kind = (j.get("kind") or "INNER").strip().upper()
    tbl = j.get("table") or {}
    tref = (tbl.get("schema") or "", tbl.get("table") or "", tbl.get("alias") or "")
    on = j.get("on") or []
    on_key = tuple(
        ((c.get("left") or ""), (c.get("op") or "=").strip().upper(), (c.get("right") or ""))
        for c in on
    )
    return (kind, tref, on_key)


def _order_key(o: Dict[str, Any]) -> Tuple:
    expr = o.get("expr") or o.get("column") or ""
    direction = (o.get("dir") or "ASC").strip().upper()
    return (expr, direction)


def optimize_ast(ast: Dict[str, Any], dialect: Optional[str] = None) -> Dict[str, Any]:
    """AST üzerinde güvenli, reversible optimizasyonlar uygular.

    Adımlar (immutable — yeni dict döner):
        1. Identical filter dedup (expr+op+value)
        2. Identical join dedup (kind+table+ON)
        3. ORDER BY dedup (expr+dir) — ilk geçen kalır
        4. OFFSET=0 → drop
        5. WITH (CTE) recursive optimize
        6. _optimized=True marker

    Not: Bu fonksiyon AST'i yalnız basitleştirir. Subquery↔join veya EXISTS↔IN
    gibi semantik dönüşümler mevcut flat AST modelinde temsil edilmediği için
    sonraki bir faza ertelenmiştir; bu bilinçli bir scope kısıtıdır.
    """
    if not isinstance(ast, dict):
        return ast
    if ast.get("type") != "select":
        return ast

    new_ast: Dict[str, Any] = dict(ast)

    # 1. Filter dedup (preserve order)
    filters = ast.get("filters") or []
    seen_f = set()
    dedup_f = []
    for f in filters:
        if not isinstance(f, dict):
            continue
        k = _filter_key(f)
        if k in seen_f:
            continue
        seen_f.add(k)
        dedup_f.append(f)
    if dedup_f != filters:
        new_ast["filters"] = dedup_f

    # 2. Join dedup
    joins = ast.get("joins") or []
    seen_j = set()
    dedup_j = []
    for j in joins:
        if not isinstance(j, dict):
            continue
        k = _join_key(j)
        if k in seen_j:
            continue
        seen_j.add(k)
        dedup_j.append(j)
    if dedup_j != joins:
        new_ast["joins"] = dedup_j

    # 3. ORDER BY dedup
    order = ast.get("order_by") or []
    seen_o = set()
    dedup_o = []
    for o in order:
        if not isinstance(o, dict):
            continue
        k = _order_key(o)
        if k in seen_o:
            continue
        seen_o.add(k)
        dedup_o.append(o)
    if dedup_o != order:
        new_ast["order_by"] = dedup_o

    # 4. OFFSET=0 → drop
    if ast.get("offset") in (0, "0"):
        new_ast.pop("offset", None)

    # 5. WITH (CTE) recursive
    with_list = ast.get("with") or []
    if with_list:
        new_ast["with"] = [
            {**cte, "ast": optimize_ast(cte.get("ast") or {}, dialect)}
            if isinstance(cte, dict) else cte
            for cte in with_list
        ]

    new_ast["_optimized"] = True
    return new_ast


# ─────────────────────────────────────────────────────────────
# Step 5 — Dialect hint injection
# ─────────────────────────────────────────────────────────────

# Hint güvenlik sınırları (denial-of-service ve syntax-error guard'ı):
_HINT_MAX_PARALLEL = 64        # Oracle PARALLEL(n)
_HINT_MAX_MAXDOP = 64          # MSSQL MAXDOP
_HINT_MAX_MET_MS = 600_000     # MySQL MAX_EXECUTION_TIME 10dk
_HINT_MAX_WORK_MEM_MB = 4096   # PG work_mem advisory (4GB üst limit)


def _safe_int(v: Any, lo: int, hi: int) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n < lo or n > hi:
        return None
    return n


def inject_dialect_hints(
    rendered: Dict[str, Any],
    hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Render edilmiş SQL'e dialect-spesifik hint yorumları ekle.

    Args:
        rendered: render() çıktısı (sql/binds/dialect).
        hints: opsiyonel hint dict.
            - parallel: int — Oracle `/*+ PARALLEL(n) */`
            - max_execution_time_ms: int — MySQL `/*+ MAX_EXECUTION_TIME(ms) */` (8.0+)
            - maxdop: int — MSSQL `OPTION (MAXDOP n)`
            - recompile: bool — MSSQL `OPTION (RECOMPILE)` (maxdop ile birleşebilir)
            - work_mem_mb: int — PG `SET LOCAL work_mem = 'NMB';` (ayrı pre_sql alanında döner)

    Tüm hint değerleri integer kontrolü ve aralık doğrulamasından geçer; geçersiz
    olanlar sessizce yok sayılır (SQL injection / DoS guard).

    Returns:
        Yeni dict: {"sql": ..., "binds": ..., "dialect": ..., "pre_sql": str|None,
                    "hints_applied": [list of applied hint keys]}
    """
    if not isinstance(rendered, dict) or "sql" not in rendered:
        raise ValueError("inject_dialect_hints: rendered dict bekleniyor")
    sql = rendered.get("sql") or ""
    dialect = rendered.get("dialect")
    out = dict(rendered)
    out["pre_sql"] = None
    applied: List[str] = []

    if not hints:
        out["hints_applied"] = []
        return out

    if dialect == "oracle":
        n = _safe_int(hints.get("parallel"), 1, _HINT_MAX_PARALLEL)
        if n is not None and sql.startswith("SELECT "):
            sql = "SELECT " + f"/*+ PARALLEL({n}) */ " + sql[len("SELECT "):]
            applied.append("parallel")

    elif dialect == "mysql":
        n = _safe_int(hints.get("max_execution_time_ms"), 1, _HINT_MAX_MET_MS)
        if n is not None and sql.startswith("SELECT "):
            sql = "SELECT " + f"/*+ MAX_EXECUTION_TIME({n}) */ " + sql[len("SELECT "):]
            applied.append("max_execution_time_ms")

    elif dialect == "mssql":
        opts: List[str] = []
        n = _safe_int(hints.get("maxdop"), 0, _HINT_MAX_MAXDOP)
        if n is not None:
            opts.append(f"MAXDOP {n}")
            applied.append("maxdop")
        if bool(hints.get("recompile")):
            opts.append("RECOMPILE")
            applied.append("recompile")
        if opts:
            sql = sql + " OPTION (" + ", ".join(opts) + ")"

    elif dialect == "postgresql":
        n = _safe_int(hints.get("work_mem_mb"), 1, _HINT_MAX_WORK_MEM_MB)
        if n is not None:
            # Caller transaction içinde set edilecek; SET LOCAL → tx kapanınca düşer.
            out["pre_sql"] = f"SET LOCAL work_mem = '{n}MB'"
            applied.append("work_mem_mb")

    out["sql"] = sql
    out["hints_applied"] = applied
    return out


# ─────────────────────────────────────────────────────────────
# AST diff (v3.30.0 FAZ 3 P19 G3.4) — drag-drop "what changed" payload
# ─────────────────────────────────────────────────────────────

def _col_key(c: Dict[str, Any]) -> Tuple[str, str]:
    return (c.get("expr") or c.get("column") or "", c.get("alias") or "")


def _join_dict(j: Dict[str, Any]) -> Tuple[str, str, str]:
    tbl = j.get("table") or {}
    return (
        tbl.get("alias") or tbl.get("table") or "",
        (j.get("kind") or "INNER").strip().upper(),
        (tbl.get("schema") or "") + "." + (tbl.get("table") or ""),
    )


def diff_ast(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """İki AST snapshot arasındaki yapısal farkı döndürür.

    Drag-drop UI tarafında "ne değişti?" preview rozeti, undo/redo summary ve
    audit log için kullanılır. AST'lerin SELECT root olması beklenir.

    Returns:
        {
            "columns": {"added": [...], "removed": [...], "reordered": bool},
            "filters": {"added": [...], "removed": [...]},
            "joins":   {"added": [...], "removed": [...], "modified": [...]},
            "order_by": {"changed": bool, "before": [...], "after": [...]},
            "limit":   {"before": int|None, "after": int|None, "changed": bool},
            "offset":  {"before": int|None, "after": int|None, "changed": bool},
            "from":    {"changed": bool, "before": str|None, "after": str|None},
            "summary": {"total_changes": int, "changed_sections": [...]},
        }
    """
    a = a or {}
    b = b or {}

    # Columns
    a_cols = [_col_key(c) for c in (a.get("columns") or [])]
    b_cols = [_col_key(c) for c in (b.get("columns") or [])]
    a_set = set(a_cols)
    b_set = set(b_cols)
    col_added = [{"expr": e, "alias": al} for (e, al) in b_cols if (e, al) not in a_set]
    col_removed = [{"expr": e, "alias": al} for (e, al) in a_cols if (e, al) not in b_set]
    col_reordered = a_set == b_set and a_cols != b_cols

    # Filters (positional value-aware)
    a_filt = [_filter_key(f) for f in (a.get("filters") or [])]
    b_filt = [_filter_key(f) for f in (b.get("filters") or [])]
    a_filt_set = list(a_filt)
    b_filt_set = list(b_filt)
    filt_added: List[Dict[str, Any]] = []
    filt_removed: List[Dict[str, Any]] = []
    # multiset diff
    tmp_a = list(a_filt_set)
    for f in b_filt_set:
        if f in tmp_a:
            tmp_a.remove(f)
        else:
            filt_added.append({"expr": f[0], "op": f[1]})
    tmp_b = list(b_filt_set)
    for f in a_filt_set:
        if f in tmp_b:
            tmp_b.remove(f)
        else:
            filt_removed.append({"expr": f[0], "op": f[1]})

    # Joins (alias indexed)
    a_join_by_alias = {_join_dict(j)[0]: j for j in (a.get("joins") or [])}
    b_join_by_alias = {_join_dict(j)[0]: j for j in (b.get("joins") or [])}
    join_added: List[Dict[str, Any]] = []
    join_removed: List[Dict[str, Any]] = []
    join_modified: List[Dict[str, Any]] = []
    for alias, j in b_join_by_alias.items():
        if alias not in a_join_by_alias:
            join_added.append({"alias": alias, "kind": j.get("kind"),
                               "table": (j.get("table") or {}).get("table")})
        elif _join_key(a_join_by_alias[alias]) != _join_key(j):
            join_modified.append({"alias": alias,
                                  "before_kind": a_join_by_alias[alias].get("kind"),
                                  "after_kind": j.get("kind")})
    for alias, j in a_join_by_alias.items():
        if alias not in b_join_by_alias:
            join_removed.append({"alias": alias, "kind": j.get("kind"),
                                 "table": (j.get("table") or {}).get("table")})

    # ORDER BY
    a_ob = [_order_key(o) for o in (a.get("order_by") or [])]
    b_ob = [_order_key(o) for o in (b.get("order_by") or [])]
    ob_changed = a_ob != b_ob

    # LIMIT/OFFSET
    a_lim = a.get("limit") if isinstance(a.get("limit"), int) else None
    b_lim = b.get("limit") if isinstance(b.get("limit"), int) else None
    a_off = a.get("offset") if isinstance(a.get("offset"), int) else None
    b_off = b.get("offset") if isinstance(b.get("offset"), int) else None

    # FROM (table.alias)
    def _from_str(ast: Dict[str, Any]) -> Optional[str]:
        fr = ast.get("from") or {}
        if not isinstance(fr, dict):
            return None
        tbl = fr.get("table") or ""
        ali = fr.get("alias") or ""
        if not tbl:
            return None
        return tbl + ("." + ali if ali else "")

    a_from = _from_str(a)
    b_from = _from_str(b)
    from_changed = a_from != b_from

    changed_sections: List[str] = []
    if col_added or col_removed or col_reordered:
        changed_sections.append("columns")
    if filt_added or filt_removed:
        changed_sections.append("filters")
    if join_added or join_removed or join_modified:
        changed_sections.append("joins")
    if ob_changed:
        changed_sections.append("order_by")
    if a_lim != b_lim:
        changed_sections.append("limit")
    if a_off != b_off:
        changed_sections.append("offset")
    if from_changed:
        changed_sections.append("from")

    total = (len(col_added) + len(col_removed) + (1 if col_reordered else 0)
             + len(filt_added) + len(filt_removed)
             + len(join_added) + len(join_removed) + len(join_modified)
             + (1 if ob_changed else 0)
             + (1 if a_lim != b_lim else 0)
             + (1 if a_off != b_off else 0)
             + (1 if from_changed else 0))

    return {
        "columns": {"added": col_added, "removed": col_removed,
                    "reordered": col_reordered},
        "filters": {"added": filt_added, "removed": filt_removed},
        "joins":   {"added": join_added, "removed": join_removed,
                    "modified": join_modified},
        "order_by": {"changed": ob_changed,
                     "before": [{"expr": e, "dir": d} for (e, d) in a_ob],
                     "after":  [{"expr": e, "dir": d} for (e, d) in b_ob]},
        "limit":   {"before": a_lim, "after": b_lim, "changed": a_lim != b_lim},
        "offset":  {"before": a_off, "after": b_off, "changed": a_off != b_off},
        "from":    {"changed": from_changed, "before": a_from, "after": b_from},
        "summary": {"total_changes": total, "changed_sections": changed_sections},
    }
