"""query_assembler.py — orchestrator + metric template substitution
(v3.30.0 FAZ 1 G1.5)."""
from __future__ import annotations

import pytest

from app.services.db_smart import query_assembler as qa


# ─────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────

def test_validate_requires_source_id():
    errs = qa.validate({"dialect": "postgresql",
                        "base_table": {"table": "t"},
                        "selected_columns": [{"expr": "*"}]})
    assert "source_id missing" in errs


def test_validate_requires_base_table():
    errs = qa.validate({"source_id": 1, "dialect": "postgresql",
                        "selected_columns": [{"expr": "*"}]})
    assert any("base_table" in e for e in errs)


def test_validate_requires_columns_or_metric():
    errs = qa.validate({"source_id": 1, "dialect": "postgresql",
                        "base_table": {"table": "t"}})
    assert any("selected_columns or metric" in e for e in errs)


def test_validate_rejects_bad_dialect():
    errs = qa.validate({"source_id": 1, "dialect": "sqlite",
                        "base_table": {"table": "t"},
                        "selected_columns": [{"expr": "*"}]})
    assert any("dialect" in e for e in errs)


def test_validate_passes_minimal():
    errs = qa.validate({"source_id": 1, "dialect": "postgresql",
                        "base_table": {"table": "t"},
                        "selected_columns": [{"expr": "*"}]})
    assert errs == []


# ─────────────────────────────────────────────────────────────
# assemble — free-form AST path
# ─────────────────────────────────────────────────────────────

def test_assemble_returns_sql_and_binds(fake_user_ctx):
    # Tenant-scoped path requires company_scoped_aliases post H-fix.
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets", "alias": "t"},
        "selected_columns": [{"expr": "t.id"}, {"expr": "t.status"}],
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
        "company_scoped_aliases": ["t"],
        "limit": 50,
    }, fake_user_ctx)
    assert out["errors"] == []
    assert out["sql"]
    assert out["binds"]
    assert out["source"] == "ast"


def test_assemble_injects_rls_with_alias(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets", "alias": "t"},
        "selected_columns": [{"expr": "t.id"}],
        "company_scoped_aliases": ["t"],
    }, fake_user_ctx)
    assert "company_id" in out["sql"]
    assert out["ast_json"].get("_rls_injected") is True


def test_assemble_raises_when_no_rls_alias_for_nonadmin(fake_user_ctx):
    # Hardened behaviour (post ARES YÜKSEK fix): non-admin caller without
    # company_scoped_aliases must NOT receive tenant-unfiltered SQL — assemble()
    # raises instead of silently warning + continuing.
    with pytest.raises(qa.RLSContextError):
        qa.assemble({
            "source_id": 1, "dialect": "postgresql",
            "base_table": {"table": "tickets", "alias": "t"},
            "selected_columns": [{"expr": "t.id"}],
        }, fake_user_ctx)


def test_assemble_admin_skips_rls_warning(fake_admin_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets", "alias": "t"},
        "selected_columns": [{"expr": "t.id"}],
    }, fake_admin_ctx)
    assert not any("rls_not_applied" in w for w in out["warnings"])


# ─────────────────────────────────────────────────────────────
# ARES YÜKSEK fix: RLS hard-fail + bypass_rls opt-in (H-fix, 2026-05-20)
# ─────────────────────────────────────────────────────────────

def test_rls_missing_raises(fake_user_ctx):
    """Non-admin caller without company_scoped_aliases → RLSContextError.

    Previously this path silently appended a warning and emitted tenant-unfiltered
    SQL; the hardened behaviour refuses to render.
    """
    with pytest.raises(qa.RLSContextError) as ei:
        qa.assemble({
            "source_id": 1, "dialect": "postgresql",
            "base_table": {"table": "tickets", "alias": "t"},
            "selected_columns": [{"expr": "t.id"}],
        }, fake_user_ctx)
    msg = str(ei.value)
    assert "RLS" in msg
    assert "non-admin" in msg or "company_scoped_aliases" in msg


def test_bypass_rls_kwarg_requires_admin(fake_user_ctx, fake_admin_ctx):
    """bypass_rls=True must be paired with admin user_ctx; otherwise raise."""
    # Non-admin trying to bypass → must raise
    with pytest.raises(qa.RLSContextError):
        qa.assemble(
            {
                "source_id": 1, "dialect": "postgresql",
                "base_table": {"table": "tickets", "alias": "t"},
                "selected_columns": [{"expr": "t.id"}],
            },
            fake_user_ctx,
            bypass_rls=True,
        )
    # Admin with bypass → permitted, SQL emitted, audit warning surfaced
    out = qa.assemble(
        {
            "source_id": 1, "dialect": "postgresql",
            "base_table": {"table": "tickets", "alias": "t"},
            "selected_columns": [{"expr": "t.id"}],
        },
        fake_admin_ctx,
        bypass_rls=True,
    )
    assert out["sql"]
    assert out["errors"] == []
    assert any("rls_bypassed_admin" in w for w in out["warnings"])


def test_normal_path_unchanged(fake_user_ctx):
    """Happy path with company_scoped_aliases still renders SQL with RLS injected.

    Confirms the H-fix did not regress the standard tenant-scoped flow.
    """
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets", "alias": "t"},
        "selected_columns": [{"expr": "t.id"}, {"expr": "t.status"}],
        "filters": [{"expr": "t.status", "op": "=", "value": "open"}],
        "company_scoped_aliases": ["t"],
        "limit": 50,
    }, fake_user_ctx)
    assert out["errors"] == []
    assert out["sql"]
    assert "company_id" in out["sql"]
    assert out["ast_json"].get("_rls_injected") is True
    assert out["source"] == "ast"
    # No RLS warning should appear in the normal path
    assert not any("rls_not_applied" in w for w in out["warnings"])
    assert not any("rls_bypassed" in w for w in out["warnings"])


def test_assemble_propagates_render_errors(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets; DROP TABLE u"},
        "selected_columns": [{"expr": "*"}],
    }, fake_user_ctx)
    assert out["sql"] is None
    assert any("render_error" in e for e in out["errors"])


# ─────────────────────────────────────────────────────────────
# assemble — metric template path
# ─────────────────────────────────────────────────────────────

def test_metric_template_substitution(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets"},
        "metric": {
            "metric_key": "helpdesk.oldest_open",
            "sql_template": "SELECT * FROM {{table}} WHERE {{status_col}} = 'open' LIMIT {{limit}}",
            "placeholders": {"table": "tickets", "status_col": "status", "limit": "10"},
        },
    }, fake_user_ctx)
    assert out["errors"] == []
    assert out["source"] == "metric_template"
    assert "tickets" in out["sql"]
    assert "LIMIT 10" in out["sql"]


def test_metric_template_blocks_unknown_placeholder(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets"},
        "metric": {
            "metric_key": "test.bad",
            "sql_template": "SELECT * FROM {{evil_col}}",
            "placeholders": {"evil_col": "users"},
        },
    }, fake_user_ctx)
    assert out["sql"] is None
    assert any("metric_template_error" in e for e in out["errors"])


def test_metric_template_blocks_injection_in_value(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets"},
        "metric": {
            "metric_key": "test.bad",
            "sql_template": "SELECT * FROM {{table}}",
            "placeholders": {"table": "users; DROP TABLE x"},
        },
    }, fake_user_ctx)
    assert out["sql"] is None
    assert any("metric_template_error" in e for e in out["errors"])


def test_metric_template_blocks_non_integer_limit(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets"},
        "metric": {
            "metric_key": "test.bad",
            "sql_template": "SELECT * FROM {{table}} LIMIT {{limit}}",
            "placeholders": {"table": "tickets", "limit": "10; DROP"},
        },
    }, fake_user_ctx)
    assert out["sql"] is None


def test_metric_template_missing_placeholder(fake_user_ctx):
    out = qa.assemble({
        "source_id": 1, "dialect": "postgresql",
        "base_table": {"table": "tickets"},
        "metric": {
            "metric_key": "test.bad",
            "sql_template": "SELECT * FROM {{table}}",
            "placeholders": {},
        },
    }, fake_user_ctx)
    assert out["sql"] is None


# ─────────────────────────────────────────────────────────────
# decide_streaming_strategy (G1.5 Step 7)
# ─────────────────────────────────────────────────────────────

def test_streaming_default_when_both_none():
    assert qa.decide_streaming_strategy(cost=None, estimated_rows=None) == "direct"


def test_streaming_rows_direct_under_1k():
    assert qa.decide_streaming_strategy(estimated_rows=999) == "direct"
    assert qa.decide_streaming_strategy(estimated_rows=0) == "direct"


def test_streaming_rows_cursor_between_1k_100k():
    assert qa.decide_streaming_strategy(estimated_rows=1_000) == "cursor"
    assert qa.decide_streaming_strategy(estimated_rows=50_000) == "cursor"
    assert qa.decide_streaming_strategy(estimated_rows=100_000) == "cursor"


def test_streaming_rows_sse_over_100k():
    assert qa.decide_streaming_strategy(estimated_rows=100_001) == "sse_chunk"
    assert qa.decide_streaming_strategy(estimated_rows=10_000_000) == "sse_chunk"


def test_streaming_cost_direct_under_1k():
    assert qa.decide_streaming_strategy(cost=0.0) == "direct"
    assert qa.decide_streaming_strategy(cost=999.99) == "direct"


def test_streaming_cost_cursor_between_1k_100k():
    assert qa.decide_streaming_strategy(cost=1_000.0) == "cursor"
    assert qa.decide_streaming_strategy(cost=99_999.0) == "cursor"
    assert qa.decide_streaming_strategy(cost=100_000.0) == "cursor"


def test_streaming_cost_sse_over_100k():
    assert qa.decide_streaming_strategy(cost=100_001.0) == "sse_chunk"
    assert qa.decide_streaming_strategy(cost=5_000_000.0) == "sse_chunk"


def test_streaming_rows_takes_precedence_over_cost():
    # rows < 1k → direct, even when cost is huge
    assert qa.decide_streaming_strategy(cost=999_999.0, estimated_rows=10) == "direct"
    # rows > 100k → sse_chunk, even when cost says direct
    assert qa.decide_streaming_strategy(cost=10.0, estimated_rows=500_000) == "sse_chunk"
