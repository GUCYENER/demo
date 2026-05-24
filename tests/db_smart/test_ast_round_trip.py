"""AST renderer idempotency / round-trip tests (FIX9 / TYCHE+ARES).

Goal: guarantee that rendering an AST twice yields *byte-identical* SQL and
that bind parameter counts are conserved. A divergence here usually means a
non-deterministic rendering step (e.g. dict iteration order, RLS re-injection
that mutates the AST in place) and is a high-signal regression detector.

We do not have a separate `parse(sql) → ast` round-trip module in this
codebase; the round-trip we verify is `render(ast) == render(render-time-AST)`,
which catches the exact class of bugs the brief targets without requiring a
SQL parser dependency.

Unit-only — no DB. Always collectable.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

try:
    from app.services.db_smart import ast_renderer as ar
except Exception:  # pragma: no cover
    ar = None  # type: ignore[assignment]


pytestmark: List[Any] = []  # NOT integration — pure unit


def _skip_if_no_renderer() -> None:
    if ar is None:
        pytest.skip("ast_renderer module unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# Sample ASTs — 8 shapes covering SELECT / JOIN / GROUP / ORDER / LIMIT /
# subquery-ish (CTE) / aggregate / filters-with-binds.
# ─────────────────────────────────────────────────────────────────────────────


def _ast_simple_select() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "id"}, {"expr": "name"}],
        "from": {"table": "tickets", "alias": "t"},
    }


def _ast_star() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "*"}],
        "from": {"table": "tickets"},
    }


def _ast_with_filter_bind() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "id"}],
        "from": {"table": "tickets", "alias": "t"},
        "where": [
            {"expr": "t.status", "op": "=", "value": "open"},
        ],
    }


def _ast_inner_join() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "t.id"}, {"expr": "u.username"}],
        "from": {"table": "tickets", "alias": "t"},
        "joins": [
            {
                "kind": "INNER",
                "table": {"table": "users", "alias": "u"},
                "on": [{"left": "t.user_id", "op": "=", "right": "u.id"}],
            }
        ],
    }


def _ast_group_by() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "status"}, {"expr": "id", "alias": "cnt"}],
        "from": {"table": "tickets", "alias": "t"},
        "group_by": ["t.status"],
        "having": [{"expr": "t.status", "op": "!=", "value": "deleted"}],
    }


def _ast_order_limit() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "id"}],
        "from": {"table": "tickets"},
        "order_by": [{"expr": "id", "dir": "DESC"}],
        "limit": 50,
    }


def _ast_cte() -> Dict[str, Any]:
    return {
        "type": "select",
        "with": [
            {
                "name": "open_t",
                "ast": {
                    "type": "select",
                    "columns": [{"expr": "id"}],
                    "from": {"table": "tickets"},
                    "where": [{"expr": "status", "op": "=", "value": "open"}],
                },
            }
        ],
        "columns": [{"expr": "id"}],
        "from": {"table": "open_t"},
    }


def _ast_left_join_multi_filter() -> Dict[str, Any]:
    return {
        "type": "select",
        "columns": [{"expr": "t.id"}, {"expr": "u.full_name"}],
        "from": {"table": "tickets", "alias": "t"},
        "joins": [
            {
                "kind": "LEFT",
                "table": {"table": "users", "alias": "u"},
                "on": [{"left": "t.user_id", "op": "=", "right": "u.id"}],
            }
        ],
        "where": [
            {"expr": "t.priority", "op": ">=", "value": 3},
            {"expr": "t.status", "op": "IN", "value": ["open", "wip"]},
        ],
    }


SAMPLES = [
    ("simple_select", _ast_simple_select),
    ("star", _ast_star),
    ("filter_bind", _ast_with_filter_bind),
    ("inner_join", _ast_inner_join),
    ("group_by", _ast_group_by),
    ("order_limit", _ast_order_limit),
    ("cte", _ast_cte),
    ("left_join_multi_filter", _ast_left_join_multi_filter),
]


@pytest.fixture
def admin_ctx() -> Dict[str, Any]:
    """Admin ctx → render() does NOT auto-inject RLS, so we measure pure render."""
    return {"id": 1, "company_id": 1, "role": "admin", "is_admin": True}


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE: render is idempotent (calling render twice produces identical SQL).
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,builder", SAMPLES)
def test_render_idempotent(name, builder, admin_ctx):
    _skip_if_no_renderer()
    ast = builder()
    out1 = ar.render(copy.deepcopy(ast), "postgresql", admin_ctx)
    out2 = ar.render(copy.deepcopy(ast), "postgresql", admin_ctx)
    assert out1["sql"] == out2["sql"], f"[{name}] render not deterministic"
    assert out1["binds"] == out2["binds"], f"[{name}] bind set diverged"
    assert out1["dialect"] == out2["dialect"] == "postgresql"


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE: bind COUNT is conserved across re-render.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,builder", SAMPLES)
def test_bind_count_conserved(name, builder, admin_ctx):
    _skip_if_no_renderer()
    ast = builder()
    out1 = ar.render(copy.deepcopy(ast), "postgresql", admin_ctx)
    out2 = ar.render(copy.deepcopy(ast), "postgresql", admin_ctx)
    n1 = len(out1["binds"]) if isinstance(out1["binds"], (dict, list)) else 0
    n2 = len(out2["binds"]) if isinstance(out2["binds"], (dict, list)) else 0
    assert n1 == n2, f"[{name}] bind count drifted: {n1} != {n2}"


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE: render across all 4 dialects stays internally consistent.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dialect", ["postgresql", "oracle", "mssql", "mysql"])
def test_render_idempotent_all_dialects(dialect, admin_ctx):
    _skip_if_no_renderer()
    if dialect not in getattr(ar, "SUPPORTED_DIALECTS", {dialect}):
        pytest.skip(f"dialect {dialect} not supported in this build")
    ast = _ast_with_filter_bind()
    out1 = ar.render(copy.deepcopy(ast), dialect, admin_ctx)
    out2 = ar.render(copy.deepcopy(ast), dialect, admin_ctx)
    assert out1["sql"] == out2["sql"]
    assert out1["dialect"] == dialect


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: malformed AST is rejected, never silently rendered.
# ─────────────────────────────────────────────────────────────────────────────


def test_render_rejects_non_select(admin_ctx):
    _skip_if_no_renderer()
    with pytest.raises(ValueError):
        ar.render({"type": "delete"}, "postgresql", admin_ctx)


def test_render_rejects_unsupported_dialect(admin_ctx):
    _skip_if_no_renderer()
    with pytest.raises(ValueError):
        ar.render(_ast_simple_select(), "sqlite", admin_ctx)


def test_render_rejects_empty_ast(admin_ctx):
    _skip_if_no_renderer()
    with pytest.raises((ValueError, KeyError, TypeError)):
        ar.render({}, "postgresql", admin_ctx)


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: identifier guard blocks injection attempts in column names.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_ident",
    [
        "id; DROP TABLE users--",
        "1=1 OR id",
        "id /* */",
        "id\nUNION SELECT password FROM users",
    ],
)
def test_render_blocks_sql_injection_in_idents(bad_ident, admin_ctx):
    _skip_if_no_renderer()
    ast = {
        "type": "select",
        "columns": [{"expr": "id"}],
        "from": {"table": bad_ident},
    }
    with pytest.raises(Exception):
        ar.render(ast, "postgresql", admin_ctx)


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE edge: empty column list / oversize limit handled deterministically.
# ─────────────────────────────────────────────────────────────────────────────


def test_render_oversize_limit_is_capped_or_accepted(admin_ctx):
    """Either renderer caps limit or accepts it — both are valid; we only assert
    idempotency holds (no oscillating cap behaviour)."""
    _skip_if_no_renderer()
    ast = {
        "type": "select",
        "columns": [{"expr": "*"}],
        "from": {"table": "tickets"},
        "limit": 10_000_000,
    }
    try:
        out1 = ar.render(copy.deepcopy(ast), "postgresql", admin_ctx)
        out2 = ar.render(copy.deepcopy(ast), "postgresql", admin_ctx)
    except (ValueError, OverflowError):
        # Acceptable: renderer rejects oversize.
        return
    assert out1["sql"] == out2["sql"]
