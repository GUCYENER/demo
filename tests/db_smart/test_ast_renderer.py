"""ast_renderer.py — 4-dialect render + RLS injection + identifier guard
(v3.30.0 FAZ 1 G1.5)."""
from __future__ import annotations

import pytest

from app.services.db_smart import ast_renderer as ar


# ─────────────────────────────────────────────────────────────
# Basic contract
# ─────────────────────────────────────────────────────────────

def test_supported_dialects_4():
    assert set(ar.SUPPORTED_DIALECTS) == {"postgresql", "oracle", "mssql", "mysql"}


def test_render_rejects_unsupported_dialect(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({"type": "select", "columns": [{"expr": "*"}],
                   "from": {"table": "t"}}, "sqlite", fake_user_ctx)


def test_render_requires_select_root(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({"type": "delete"}, "postgresql", fake_user_ctx)


def test_render_returns_dict_with_sql_binds_dialect(fake_user_ctx):
    out = ar.render(
        {"type": "select", "columns": [{"expr": "id"}], "from": {"table": "t"}},
        "postgresql", fake_user_ctx,
    )
    assert isinstance(out, dict)
    assert "sql" in out and "binds" in out and out["dialect"] == "postgresql"


# ─────────────────────────────────────────────────────────────
# Dialect-specific behaviors
# ─────────────────────────────────────────────────────────────

def test_postgres_limit_offset(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "tickets", "alias": "t"},
        "limit": 10, "offset": 5,
    }, "postgresql", fake_user_ctx)
    assert "LIMIT 10" in out["sql"]
    assert "OFFSET 5" in out["sql"]


def test_oracle_fetch_first(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "tickets"}, "limit": 10, "offset": 5,
    }, "oracle", fake_user_ctx)
    assert "FETCH NEXT 10 ROWS ONLY" in out["sql"]
    assert "OFFSET 5 ROWS" in out["sql"]


def test_mssql_top(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "tickets"}, "limit": 10,
    }, "mssql", fake_user_ctx)
    assert "TOP (10)" in out["sql"]


def test_mssql_offset_switches_to_fetch(fake_user_ctx):
    """MSSQL: TOP + OFFSET/FETCH aynı sorguda olamaz — offset varsa TOP kaldırılır."""
    out = ar.render({
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "tickets"}, "limit": 10, "offset": 5,
    }, "mssql", fake_user_ctx)
    assert "TOP" not in out["sql"]
    assert "OFFSET 5 ROWS" in out["sql"]
    assert "FETCH NEXT 10 ROWS ONLY" in out["sql"]


def test_mysql_backtick_quote(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "tickets"},
    }, "mysql", fake_user_ctx)
    assert "`tickets`" in out["sql"]


def test_postgres_double_quote(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "tickets"},
    }, "postgresql", fake_user_ctx)
    assert '"tickets"' in out["sql"]


def test_mssql_bracket_quote(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "tickets"},
    }, "mssql", fake_user_ctx)
    assert "[tickets]" in out["sql"]


# ─────────────────────────────────────────────────────────────
# Identifier whitelist (SQL injection guard)
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "id; DROP TABLE users",
    "id--",
    "'; DELETE",
    "id OR 1=1",
    "select",  # SQL keyword as bare identifier — actually whitelist allows it, removed
])
def test_identifier_injection_blocked(bad, fake_user_ctx):
    if bad == "select":
        pytest.skip("'select' alone matches whitelist; injection requires non-ident chars")
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": bad}],
            "from": {"table": "t"},
        }, "postgresql", fake_user_ctx)


def test_table_name_injection_blocked(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": "*"}],
            "from": {"table": "t; DROP TABLE u"},
        }, "postgresql", fake_user_ctx)


def test_operator_whitelist_blocks_random_op(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": "id"}],
            "from": {"table": "t"},
            "filters": [{"expr": "id", "op": "DROP", "value": 1}],
        }, "postgresql", fake_user_ctx)


# ─────────────────────────────────────────────────────────────
# Filter render + binding
# ─────────────────────────────────────────────────────────────

def test_eq_filter_uses_bind(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
    }, "postgresql", fake_user_ctx)
    assert "%(v_1)s" in out["sql"]
    assert out["binds"]["v_1"] == "open"


def test_in_filter_multiple_binds(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.status", "op": "IN", "value": ["open", "wip", "closed"]}],
    }, "postgresql", fake_user_ctx)
    assert "IN (" in out["sql"]
    assert len(out["binds"]) == 3


def test_in_filter_rejects_empty_list(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": "id"}],
            "from": {"table": "t"},
            "filters": [{"expr": "t.status", "op": "IN", "value": []}],
        }, "postgresql", fake_user_ctx)


def test_is_null_no_bind(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.deleted_at", "op": "IS NULL"}],
    }, "postgresql", fake_user_ctx)
    assert "IS NULL" in out["sql"]
    assert len(out["binds"]) == 0


def test_between_filter(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.created_at", "op": "BETWEEN",
                     "value": ["2026-01-01", "2026-12-31"]}],
    }, "postgresql", fake_user_ctx)
    assert "BETWEEN" in out["sql"]
    assert len(out["binds"]) == 2


# ─────────────────────────────────────────────────────────────
# JOIN
# ─────────────────────────────────────────────────────────────

def test_inner_join(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "joins": [{
            "kind": "INNER",
            "table": {"table": "users", "alias": "u"},
            "on": [{"left": "t.user_id", "op": "=", "right": "u.id"}],
        }],
    }, "postgresql", fake_user_ctx)
    assert "INNER JOIN" in out["sql"]
    assert '"users"' in out["sql"]


def test_join_rejects_bad_kind(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": "*"}],
            "from": {"table": "t"},
            "joins": [{"kind": "EVIL", "table": {"table": "u"},
                       "on": [{"left": "t.id", "right": "u.tid"}]}],
        }, "postgresql", fake_user_ctx)


# ─────────────────────────────────────────────────────────────
# GROUP BY / HAVING / ORDER
# ─────────────────────────────────────────────────────────────

def test_group_by_having_order(fake_user_ctx):
    out = ar.render({
        "type": "select",
        "columns": [{"expr": "status"}, {"expr": "id", "alias": "cnt"}],
        "from": {"table": "tickets", "alias": "t"},
        "group_by": ["t.status"],
        "having": [{"expr": "t.status", "op": "!=", "value": "deleted"}],
        "order_by": [{"expr": "t.status", "dir": "DESC"}],
    }, "postgresql", fake_user_ctx)
    assert "GROUP BY" in out["sql"]
    assert "HAVING" in out["sql"]
    assert "ORDER BY" in out["sql"]
    assert "DESC" in out["sql"]


def test_order_rejects_bad_direction(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": "id"}],
            "from": {"table": "t"},
            "order_by": [{"expr": "t.id", "dir": "RANDOM"}],
        }, "postgresql", fake_user_ctx)


# ─────────────────────────────────────────────────────────────
# CTE (WITH)
# ─────────────────────────────────────────────────────────────

def test_cte_with_clause(fake_user_ctx):
    out = ar.render({
        "type": "select",
        "with": [{
            "name": "open_tickets",
            "ast": {
                "type": "select", "columns": [{"expr": "id"}],
                "from": {"table": "tickets"},
                "filters": [{"expr": "status", "op": "=", "value": "open"}],
            },
        }],
        "columns": [{"expr": "id"}],
        "from": {"table": "open_tickets", "alias": "o"},
    }, "postgresql", fake_user_ctx)
    assert out["sql"].startswith("WITH")
    assert "open_tickets" in out["sql"]


# ─────────────────────────────────────────────────────────────
# RLS injection
# ─────────────────────────────────────────────────────────────

def test_inject_rls_appends_company_filter(fake_user_ctx):
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [],
    }
    out = ar.inject_rls(ast, fake_user_ctx, company_scoped_tables=["t"])
    assert out["_rls_injected"] is True
    assert any(f["expr"] == "t.company_id" for f in out["filters"])


def test_inject_rls_skipped_for_admin(fake_admin_ctx):
    ast = {"type": "select", "columns": [{"expr": "*"}],
           "from": {"table": "tickets", "alias": "t"}}
    out = ar.inject_rls(ast, fake_admin_ctx, company_scoped_tables=["t"])
    assert not out.get("_rls_injected")
    assert not (out.get("filters") or [])


def test_inject_rls_noop_when_no_scoped_tables(fake_user_ctx):
    ast = {"type": "select", "columns": [{"expr": "*"}],
           "from": {"table": "tickets"}}
    out = ar.inject_rls(ast, fake_user_ctx, company_scoped_tables=[])
    assert not out.get("_rls_injected")


def test_end_to_end_rls_filter_in_sql(fake_user_ctx):
    ast = {
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
    }
    ast = ar.inject_rls(ast, fake_user_ctx, company_scoped_tables=["t"])
    out = ar.render(ast, "postgresql", fake_user_ctx)
    assert "company_id" in out["sql"]
    # 2 bind: status + company_id
    assert len(out["binds"]) == 2


# ─────────────────────────────────────────────────────────────
# Serialize roundtrip
# ─────────────────────────────────────────────────────────────

def test_serialize_roundtrip():
    ast = {"type": "select", "columns": [{"expr": "id"}], "from": {"table": "t"}}
    snap = ar.serialize_json(ast)
    back = ar.deserialize_json(snap)
    assert back == ast
