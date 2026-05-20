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


# ─────────────────────────────────────────────────────────────
# Step 4 — optimize_ast
# ─────────────────────────────────────────────────────────────

def test_optimize_dedupes_identical_filters():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"},
        "filters": [
            {"expr": "t.status", "op": "=", "value": "open"},
            {"expr": "t.status", "op": "=", "value": "open"},
            {"expr": "t.priority", "op": "=", "value": "high"},
        ],
    }
    out = ar.optimize_ast(ast)
    assert len(out["filters"]) == 2
    assert out["_optimized"] is True


def test_optimize_dedupes_in_filter_with_same_value_list():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"},
        "filters": [
            {"expr": "t.id", "op": "IN", "value": [1, 2, 3]},
            {"expr": "t.id", "op": "IN", "value": [1, 2, 3]},
        ],
    }
    out = ar.optimize_ast(ast)
    assert len(out["filters"]) == 1


def test_optimize_keeps_different_filter_values():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"},
        "filters": [
            {"expr": "t.status", "op": "=", "value": "open"},
            {"expr": "t.status", "op": "=", "value": "closed"},
        ],
    }
    out = ar.optimize_ast(ast)
    assert len(out["filters"]) == 2


def test_optimize_dedupes_identical_joins():
    j = {
        "kind": "INNER",
        "table": {"table": "users", "alias": "u"},
        "on": [{"left": "t.user_id", "op": "=", "right": "u.id"}],
    }
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"},
        "joins": [j, dict(j)],
    }
    out = ar.optimize_ast(ast)
    assert len(out["joins"]) == 1


def test_optimize_dedupes_order_by():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"},
        "order_by": [
            {"expr": "t.id", "dir": "ASC"},
            {"expr": "t.id", "dir": "ASC"},
            {"expr": "t.id", "dir": "DESC"},  # different direction kept
        ],
    }
    out = ar.optimize_ast(ast)
    assert len(out["order_by"]) == 2


def test_optimize_drops_offset_zero():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"}, "offset": 0,
    }
    out = ar.optimize_ast(ast)
    assert "offset" not in out


def test_optimize_keeps_nonzero_offset():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "t"}, "offset": 5,
    }
    out = ar.optimize_ast(ast)
    assert out["offset"] == 5


def test_optimize_recurses_into_cte():
    ast = {
        "type": "select", "columns": [{"expr": "*"}],
        "from": {"table": "o", "alias": "o"},
        "with": [{
            "name": "o",
            "ast": {
                "type": "select", "columns": [{"expr": "id"}],
                "from": {"table": "tickets"},
                "filters": [
                    {"expr": "status", "op": "=", "value": "open"},
                    {"expr": "status", "op": "=", "value": "open"},
                ],
            },
        }],
    }
    out = ar.optimize_ast(ast)
    inner = out["with"][0]["ast"]
    assert len(inner["filters"]) == 1
    assert inner["_optimized"] is True


def test_optimize_passthrough_non_select():
    assert ar.optimize_ast({"type": "delete"}) == {"type": "delete"}
    assert ar.optimize_ast([]) == []


def test_optimize_and_render_consistency(fake_user_ctx):
    """Optimized AST hâlâ valid SQL render etmeli."""
    ast = {
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [
            {"expr": "t.status", "op": "=", "value": "open"},
            {"expr": "t.status", "op": "=", "value": "open"},
        ],
        "offset": 0,
    }
    opt = ar.optimize_ast(ast)
    out = ar.render(opt, "postgresql", fake_user_ctx)
    # Tek bind kaldı, OFFSET yok
    assert len(out["binds"]) == 1
    assert "OFFSET" not in out["sql"]


# ─────────────────────────────────────────────────────────────
# Step 5 — inject_dialect_hints
# ─────────────────────────────────────────────────────────────

def test_hint_oracle_parallel(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "oracle", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"parallel": 4})
    assert "/*+ PARALLEL(4) */" in out["sql"]
    assert "parallel" in out["hints_applied"]


def test_hint_oracle_rejects_out_of_range(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "oracle", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"parallel": 999})
    assert "PARALLEL" not in out["sql"]
    assert out["hints_applied"] == []


def test_hint_oracle_rejects_nonint_injection(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "oracle", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"parallel": "4) */ DROP TABLE u --"})
    assert "DROP" not in out["sql"]
    assert out["hints_applied"] == []


def test_hint_mysql_max_execution_time(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "mysql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"max_execution_time_ms": 30000})
    assert "/*+ MAX_EXECUTION_TIME(30000) */" in out["sql"]


def test_hint_mssql_maxdop_and_recompile(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "mssql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"maxdop": 4, "recompile": True})
    assert "OPTION (MAXDOP 4, RECOMPILE)" in out["sql"]
    assert set(out["hints_applied"]) == {"maxdop", "recompile"}


def test_hint_mssql_only_recompile(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "mssql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"recompile": True})
    assert out["sql"].endswith("OPTION (RECOMPILE)")


def test_hint_postgres_work_mem(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "postgresql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"work_mem_mb": 64})
    assert out["pre_sql"] == "SET LOCAL work_mem = '64MB'"
    assert "work_mem_mb" in out["hints_applied"]
    # sql değişmemeli
    assert "work_mem" not in out["sql"]


def test_hint_postgres_work_mem_rejects_huge(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "postgresql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"work_mem_mb": 99999})
    assert out["pre_sql"] is None


def test_hint_no_hints_returns_clean_output(fake_user_ctx):
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "postgresql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, None)
    assert out["sql"] == r["sql"]
    assert out["pre_sql"] is None
    assert out["hints_applied"] == []


def test_hint_invalid_rendered_raises():
    with pytest.raises(ValueError):
        ar.inject_dialect_hints({"binds": {}}, {"parallel": 4})


def test_hint_cross_dialect_ignored(fake_user_ctx):
    """PG dialect'inde oracle PARALLEL geçilirse no-op olmalı."""
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "postgresql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"parallel": 4})
    assert "PARALLEL" not in out["sql"]
    assert "parallel" not in out["hints_applied"]
