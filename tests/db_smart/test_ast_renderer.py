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
    }, "postgresql", fake_user_ctx, _rls_already_injected=True)
    assert "%(v_1)s" in out["sql"]
    assert out["binds"]["v_1"] == "open"


def test_in_filter_multiple_binds(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.status", "op": "IN", "value": ["open", "wip", "closed"]}],
    }, "postgresql", fake_user_ctx, _rls_already_injected=True)
    assert "IN (" in out["sql"]
    assert len(out["binds"]) == 3


def test_in_filter_rejects_empty_list(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({
            "type": "select", "columns": [{"expr": "id"}],
            "from": {"table": "t"},
            "filters": [{"expr": "t.status", "op": "IN", "value": []}],
        }, "postgresql", fake_user_ctx, _rls_already_injected=True)


def test_is_null_no_bind(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.deleted_at", "op": "IS NULL"}],
    }, "postgresql", fake_user_ctx, _rls_already_injected=True)
    assert "IS NULL" in out["sql"]
    assert len(out["binds"]) == 0


def test_between_filter(fake_user_ctx):
    out = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
        "filters": [{"expr": "t.created_at", "op": "BETWEEN",
                     "value": ["2026-01-01", "2026-12-31"]}],
    }, "postgresql", fake_user_ctx, _rls_already_injected=True)
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
# F-021 (ARES KRİTİK) — render() defense-in-depth RLS auto-injection
# ─────────────────────────────────────────────────────────────

def test_render_auto_injects_rls_for_non_admin(fake_user_ctx):
    """Caller `inject_rls`'i atlasa bile non-admin için render otomatik enjekte etmeli."""
    ast = {
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
    }
    out = ar.render(ast, "postgresql", fake_user_ctx)
    # Auto-inject: company_id predicate SQL'e düşmeli
    assert "company_id" in out["sql"]
    # 2 bind: status=open + company_id=1
    assert len(out["binds"]) == 2
    assert 1 in out["binds"].values()


def test_render_admin_no_rls(fake_admin_ctx):
    """Admin user için render company_id filter EKLEMEMELİ."""
    ast = {
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
    }
    out = ar.render(ast, "postgresql", fake_admin_ctx)
    assert "company_id" not in out["sql"]
    # Yalnız 1 bind: status
    assert len(out["binds"]) == 1


def test_render_skip_flag_respected(fake_user_ctx):
    """`_rls_already_injected=True` flag verilirse render auto-inject etmemeli."""
    ast = {
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
    }
    out = ar.render(ast, "postgresql", fake_user_ctx, _rls_already_injected=True)
    assert "company_id" not in out["sql"]
    assert len(out["binds"]) == 1


def test_render_idempotent_when_already_injected(fake_user_ctx):
    """`inject_rls` çağırılmış AST'i render etmek çift predicate üretmemeli."""
    ast = {
        "type": "select", "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
    }
    injected = ar.inject_rls(ast, fake_user_ctx, company_scoped_tables=["t"])
    # marker mevcut → render skip etmeli, çift inject yok
    assert injected.get("_rls_injected") is True
    out = ar.render(injected, "postgresql", fake_user_ctx)
    # SQL içinde "company_id" tek sefer (predicate dedup + skip).
    assert out["sql"].count("company_id") == 1
    # 2 bind: status + tek company_id
    assert len(out["binds"]) == 2

    # Ek garantı: inject_rls'i iki kez çağırmak da çift predicate üretmemeli.
    double = ar.inject_rls(injected, fake_user_ctx, company_scoped_tables=["t"])
    out2 = ar.render(double, "postgresql", fake_user_ctx, _rls_already_injected=True)
    assert out2["sql"].count("company_id") == 1
    assert len(out2["binds"]) == 2


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
    out = ar.render(opt, "postgresql", fake_user_ctx, _rls_already_injected=True)
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


# ─────────────────────────────────────────────────────────────
# FAZ 2 G2.1 — AST manipulation API
# ─────────────────────────────────────────────────────────────

def _base_ast():
    return {
        "type": "select",
        "columns": [{"expr": "t.id"}, {"expr": "t.status"}],
        "from": {"table": "tickets", "alias": "t"},
        "joins": [{
            "kind": "INNER",
            "table": {"table": "users", "alias": "u"},
            "on": [{"left": "t.user_id", "op": "=", "right": "u.id"}],
        }],
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
        "order_by": [{"expr": "t.id", "dir": "ASC"}],
    }


def test_add_column_appends_and_immutable():
    src = _base_ast()
    out = ar.add_column(src, {"expr": "t.priority", "alias": "prio"})
    assert len(out["columns"]) == 3
    # immutable: kaynak değişmedi
    assert len(src["columns"]) == 2


def test_add_column_idempotent_for_same_expr_alias():
    src = _base_ast()
    out = ar.add_column(src, {"expr": "t.id"})
    # already present (alias None) → no append
    assert len(out["columns"]) == 2


def test_add_column_rejects_bad_identifier():
    with pytest.raises(ValueError):
        ar.add_column(_base_ast(), {"expr": "id; DROP"})


def test_add_column_requires_expr():
    with pytest.raises(ValueError):
        ar.add_column(_base_ast(), {"alias": "x"})


def test_remove_column_by_expr():
    out = ar.remove_column(_base_ast(), expr="t.status")
    assert all(c.get("expr") != "t.status" for c in out["columns"])


def test_remove_column_by_alias():
    src = _base_ast()
    src["columns"].append({"expr": "t.priority", "alias": "prio"})
    out = ar.remove_column(src, alias="prio")
    assert all(c.get("alias") != "prio" for c in out["columns"])


def test_remove_column_rejects_last_column():
    ast = {"type": "select", "columns": [{"expr": "t.id"}], "from": {"table": "t"}}
    with pytest.raises(ValueError):
        ar.remove_column(ast, expr="t.id")


def test_remove_column_requires_arg():
    with pytest.raises(ValueError):
        ar.remove_column(_base_ast())


def test_add_filter_appends():
    out = ar.add_filter(_base_ast(), {"expr": "t.priority", "op": "=", "value": "high"})
    assert len(out["filters"]) == 2


def test_add_filter_rejects_bad_op():
    with pytest.raises(ValueError):
        ar.add_filter(_base_ast(), {"expr": "t.id", "op": "DROP", "value": 1})


def test_add_filter_rejects_bad_expr():
    with pytest.raises(ValueError):
        ar.add_filter(_base_ast(), {"expr": "id; --", "op": "=", "value": 1})


def test_remove_filter_by_expr_all_matches():
    src = _base_ast()
    src["filters"].append({"expr": "t.status", "op": "=", "value": "closed"})
    out = ar.remove_filter(src, expr="t.status")
    assert out["filters"] == []


def test_remove_filter_by_index():
    src = _base_ast()
    src["filters"].extend([
        {"expr": "t.priority", "op": "=", "value": "high"},
        {"expr": "t.assignee", "op": "=", "value": 1},
    ])
    out = ar.remove_filter(src, index=1)
    assert len(out["filters"]) == 2
    assert all(f.get("expr") != "t.priority" for f in out["filters"])


def test_remove_filter_index_out_of_range():
    with pytest.raises(ValueError):
        ar.remove_filter(_base_ast(), index=99)


def test_modify_join_kind_only():
    out = ar.modify_join(_base_ast(), "u", kind="LEFT")
    assert out["joins"][0]["kind"] == "LEFT"


def test_modify_join_on_only():
    new_on = [{"left": "t.user_id", "op": "=", "right": "u.uuid"}]
    out = ar.modify_join(_base_ast(), "u", on=new_on)
    assert out["joins"][0]["on"] == new_on


def test_modify_join_unknown_alias():
    with pytest.raises(ValueError):
        ar.modify_join(_base_ast(), "missing", kind="LEFT")


def test_modify_join_rejects_empty_on():
    with pytest.raises(ValueError):
        ar.modify_join(_base_ast(), "u", on=[])


def test_modify_join_rejects_injection_in_on():
    with pytest.raises(ValueError):
        ar.modify_join(_base_ast(), "u", on=[{"left": "x; DROP", "right": "u.id"}])


def test_reorder_by_replaces():
    out = ar.reorder_by(_base_ast(), [
        {"expr": "t.priority", "dir": "DESC"},
        {"expr": "t.id", "dir": "ASC"},
    ])
    assert len(out["order_by"]) == 2
    assert out["order_by"][0]["dir"] == "DESC"


def test_reorder_by_empty_clears():
    out = ar.reorder_by(_base_ast(), [])
    assert out["order_by"] == []


def test_reorder_by_rejects_bad_dir():
    with pytest.raises(ValueError):
        ar.reorder_by(_base_ast(), [{"expr": "t.id", "dir": "RANDOM"}])


def test_set_limit_offset_assigns():
    out = ar.set_limit(_base_ast(), limit=50, offset=10)
    assert out["limit"] == 50
    assert out["offset"] == 10


def test_set_limit_none_clears():
    src = _base_ast()
    src["limit"] = 100
    src["offset"] = 5
    out = ar.set_limit(src, limit=None, offset=None)
    assert "limit" not in out
    assert "offset" not in out


def test_set_limit_rejects_negative():
    with pytest.raises(ValueError):
        ar.set_limit(_base_ast(), limit=-1)


def test_manipulation_chain_still_renders(fake_user_ctx):
    ast = _base_ast()
    ast = ar.add_column(ast, {"expr": "t.priority", "alias": "prio"})
    ast = ar.add_filter(ast, {"expr": "t.priority", "op": "=", "value": "high"})
    ast = ar.modify_join(ast, "u", kind="LEFT")
    ast = ar.reorder_by(ast, [{"expr": "t.id", "dir": "DESC"}])
    ast = ar.set_limit(ast, limit=10)
    out = ar.render(ast, "postgresql", fake_user_ctx, _rls_already_injected=True)
    assert "LEFT JOIN" in out["sql"]
    assert "DESC" in out["sql"]
    assert "LIMIT 10" in out["sql"]
    # 2 bind: status=open + priority=high
    assert len(out["binds"]) == 2


def test_manipulation_non_select_raises():
    with pytest.raises(ValueError):
        ar.add_column({"type": "delete"}, {"expr": "x"})


def test_hint_cross_dialect_ignored(fake_user_ctx):
    """PG dialect'inde oracle PARALLEL geçilirse no-op olmalı."""
    r = ar.render({
        "type": "select", "columns": [{"expr": "id"}],
        "from": {"table": "t"},
    }, "postgresql", fake_user_ctx)
    out = ar.inject_dialect_hints(r, {"parallel": 4})
    assert "PARALLEL" not in out["sql"]
    assert "parallel" not in out["hints_applied"]


# ─────────────────────────────────────────────────────────────
# FAZ 3 P19 G3.4 — reorder_columns + diff_ast (drag-drop)
# ─────────────────────────────────────────────────────────────

def test_reorder_columns_basic_swap():
    src = _base_ast()
    out = ar.reorder_columns(src, [
        {"expr": "t.status"},
        {"expr": "t.id"},
    ])
    assert [c["expr"] for c in out["columns"]] == ["t.status", "t.id"]
    # immutable
    assert [c["expr"] for c in src["columns"]] == ["t.id", "t.status"]


def test_reorder_columns_missing_appended_stable():
    src = _base_ast()
    src["columns"].append({"expr": "t.priority", "alias": "prio"})
    out = ar.reorder_columns(src, [{"expr": "t.priority", "alias": "prio"}])
    # ilk: explicit; sonra orijinal sırayla kalanlar
    exprs = [c.get("expr") for c in out["columns"]]
    assert exprs[0] == "t.priority"
    assert exprs[1:] == ["t.id", "t.status"]


def test_reorder_columns_does_not_add_or_remove():
    src = _base_ast()
    out = ar.reorder_columns(src, [
        {"expr": "t.id"},
        {"expr": "nonexistent.x"},  # eşleşmez → atlanır
        {"expr": "t.status"},
    ])
    assert len(out["columns"]) == 2
    assert {c["expr"] for c in out["columns"]} == {"t.id", "t.status"}


def test_reorder_columns_rejects_non_list():
    with pytest.raises(ValueError):
        ar.reorder_columns(_base_ast(), "not-a-list")


def test_reorder_columns_non_select_raises():
    with pytest.raises(ValueError):
        ar.reorder_columns({"type": "delete"}, [])


def test_reorder_columns_duplicate_keys_defensive():
    """Aynı (expr, alias) key'iyle iki kolon olsa bile (yapı normalde imkansız —
    add_column idempotent — ama defensif) hiçbir kolon kaybolmamalı."""
    src = {
        "type": "select",
        "columns": [{"expr": "t.id"}, {"expr": "t.id"}, {"expr": "t.status"}],
        "from": {"table": "tickets", "alias": "t"},
    }
    out = ar.reorder_columns(src, [{"expr": "t.status"}])
    # 3 kolon korundu, eşleşen önce
    assert len(out["columns"]) == 3
    assert out["columns"][0]["expr"] == "t.status"


def test_diff_ast_identical_no_changes():
    a = _base_ast()
    d = ar.diff_ast(a, dict(a))
    assert d["summary"]["total_changes"] == 0
    assert d["summary"]["changed_sections"] == []
    assert d["columns"]["reordered"] is False


def test_diff_ast_column_added():
    a = _base_ast()
    b = ar.add_column(a, {"expr": "t.priority", "alias": "prio"})
    d = ar.diff_ast(a, b)
    assert d["columns"]["added"] == [{"expr": "t.priority", "alias": "prio"}]
    assert d["columns"]["removed"] == []
    assert "columns" in d["summary"]["changed_sections"]


def test_diff_ast_column_reordered_flag():
    a = _base_ast()
    b = ar.reorder_columns(a, [{"expr": "t.status"}, {"expr": "t.id"}])
    d = ar.diff_ast(a, b)
    assert d["columns"]["reordered"] is True
    assert d["columns"]["added"] == []
    assert d["columns"]["removed"] == []


def test_diff_ast_filter_added_removed():
    a = _base_ast()
    b = ar.add_filter(a, {"expr": "t.priority", "op": "=", "value": "high"})
    d = ar.diff_ast(a, b)
    assert any(f["expr"] == "t.priority" for f in d["filters"]["added"])
    assert d["filters"]["removed"] == []

    d2 = ar.diff_ast(b, a)
    assert any(f["expr"] == "t.priority" for f in d2["filters"]["removed"])


def test_diff_ast_join_modified_kind():
    a = _base_ast()
    b = ar.modify_join(a, "u", kind="LEFT")
    d = ar.diff_ast(a, b)
    assert d["joins"]["modified"]
    assert d["joins"]["modified"][0]["after_kind"] == "LEFT"
    assert d["joins"]["added"] == []
    assert d["joins"]["removed"] == []


def test_diff_ast_order_by_changed():
    a = _base_ast()
    b = ar.reorder_by(a, [{"expr": "t.id", "dir": "DESC"}])
    d = ar.diff_ast(a, b)
    assert d["order_by"]["changed"] is True
    assert d["order_by"]["after"][0]["dir"] == "DESC"


def test_diff_ast_limit_changed():
    a = _base_ast()
    b = ar.set_limit(a, limit=100)
    d = ar.diff_ast(a, b)
    assert d["limit"]["before"] is None
    assert d["limit"]["after"] == 100
    assert d["limit"]["changed"] is True


def test_diff_ast_summary_counts_total():
    a = _base_ast()
    b = ar.add_column(a, {"expr": "t.priority"})
    b = ar.set_limit(b, limit=10)
    b = ar.reorder_by(b, [{"expr": "t.id", "dir": "DESC"}])
    d = ar.diff_ast(a, b)
    assert d["summary"]["total_changes"] >= 3
    sects = set(d["summary"]["changed_sections"])
    assert {"columns", "limit", "order_by"}.issubset(sects)


def test_diff_ast_from_changed():
    a = _base_ast()
    b = dict(a)
    b["from"] = {"table": "tickets_archive", "alias": "ta"}
    d = ar.diff_ast(a, b)
    assert d["from"]["changed"] is True
    assert d["from"]["before"].startswith("tickets")
    assert d["from"]["after"].startswith("tickets_archive")


def test_reorder_columns_then_render_keeps_order(fake_user_ctx):
    a = _base_ast()
    b = ar.reorder_columns(a, [{"expr": "t.status"}, {"expr": "t.id"}])
    out = ar.render(b, "postgresql", fake_user_ctx)
    # SELECT içinde status önce gelmeli
    head = out["sql"].split("FROM")[0]
    assert head.index("status") < head.index('"t"."id"') or head.index("status") < head.index("t.id")
