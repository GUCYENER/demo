"""VYRA v3.27.0 — Schema Drift Detector Tests (B.END.2).

apply_drift orchestration + helper functions. Mocked cursor, no DB.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning.schema_drift_detector import (
    DriftActionSummary,
    _collect_removed_columns,
    _drop_column_embeddings,
    _emit_drift_event,
    _invalidate_learned_for_tables,
    _penalize_few_shot_for_tables,
    _table_keys,
    apply_drift,
)


# ─────────────────────────────────────────────────────────────
# Mock cursor
# ─────────────────────────────────────────────────────────────

class _MockCursor:
    """Minimal psycopg2 cursor stand-in capturing executed SQL + params."""

    def __init__(self, rowcounts=None):
        self.executed = []  # list of (sql, params)
        self._rowcounts = list(rowcounts or [])
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)
        else:
            self.rowcount = 0

    def close(self):
        pass


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

class TestTableKeys:
    def test_string_items(self):
        assert _table_keys(["Public.Orders", "Sales.Items"]) == ["public.orders", "sales.items"]

    def test_dict_items(self):
        items = [
            {"schema": "public", "table": "orders"},
            {"schema_name": "sales", "table_name": "items"},
        ]
        assert _table_keys(items) == ["public.orders", "sales.items"]

    def test_table_only_no_schema(self):
        assert _table_keys([{"table": "orders"}]) == ["orders"]

    def test_empty_input(self):
        assert _table_keys(None) == []
        assert _table_keys([]) == []


class TestCollectRemovedColumns:
    def test_string_columns(self):
        modified = [{"schema": "public", "table": "orders", "removed_columns": ["status", "note"]}]
        out = _collect_removed_columns(modified)
        assert len(out) == 2
        assert out[0]["column_name"] == "status"
        assert out[0]["table_name"] == "orders"
        assert out[0]["schema_name"] == "public"

    def test_dict_columns(self):
        modified = [{"schema": "public", "table": "orders",
                     "removed_columns": [{"name": "status"}, {"column_name": "note"}]}]
        out = _collect_removed_columns(modified)
        assert {c["column_name"] for c in out} == {"status", "note"}

    def test_alt_key_removed_cols(self):
        modified = [{"table": "orders", "removed_cols": ["x"]}]
        out = _collect_removed_columns(modified)
        assert out[0]["column_name"] == "x"

    def test_empty(self):
        assert _collect_removed_columns([]) == []


# ─────────────────────────────────────────────────────────────
# Invalidation actions
# ─────────────────────────────────────────────────────────────

class TestInvalidateLearned:
    def test_no_tables_returns_zero(self):
        cur = _MockCursor()
        assert _invalidate_learned_for_tables(cur, 1, []) == 0
        assert cur.executed == []

    def test_executes_one_query_per_table(self):
        cur = _MockCursor(rowcounts=[3, 2])
        n = _invalidate_learned_for_tables(cur, 7, ["public.orders", "public.items"])
        assert n == 5
        assert len(cur.executed) == 2
        sql0, params0 = cur.executed[0]
        assert "UPDATE learned_db_queries" in sql0
        assert "is_active = FALSE" in sql0
        assert params0 == (7, "%public.orders%")


class TestPenalizeFewShot:
    def test_no_tables_returns_zero(self):
        cur = _MockCursor()
        assert _penalize_few_shot_for_tables(cur, 1, []) == 0
        assert cur.executed == []

    def test_penalizes_each_table(self):
        cur = _MockCursor(rowcounts=[4])
        n = _penalize_few_shot_for_tables(cur, 9, ["public.orders"])
        assert n == 4
        sql, params = cur.executed[0]
        assert "UPDATE few_shot_examples" in sql
        assert "success_rate * 0.5" in sql
        assert params == (9, "%public.orders%")


class TestDropColumnEmbeddings:
    def test_no_cols_returns_zero(self):
        cur = _MockCursor()
        assert _drop_column_embeddings(cur, 1, []) == 0

    def test_deletes_one_per_column(self):
        cols = [
            {"schema_name": "public", "table_name": "orders", "column_name": "status"},
            {"schema_name": "public", "table_name": "orders", "column_name": "note"},
        ]
        cur = _MockCursor(rowcounts=[1, 1])
        n = _drop_column_embeddings(cur, 3, cols)
        assert n == 2
        assert len(cur.executed) == 2
        sql0, params0 = cur.executed[0]
        assert "DELETE FROM ds_column_embeddings" in sql0
        assert params0 == (3, "public", "orders", "status")


class TestEmitDriftEvent:
    def test_inserts_pipeline_event(self):
        cur = _MockCursor()
        summary = DriftActionSummary(source_id=5, invalidated_learned=3)
        _emit_drift_event(cur, source_id=5, company_id=11, summary=summary)
        assert len(cur.executed) == 1
        sql, params = cur.executed[0]
        assert "INSERT INTO pipeline_events" in sql
        assert "schema_drift" in sql
        # params: (company_id, source_id, metadata_json)
        assert params[0] == 11
        assert params[1] == 5
        import json as _json
        meta = _json.loads(params[2])
        assert meta["invalidated_learned"] == 3


# ─────────────────────────────────────────────────────────────
# apply_drift orchestration
# ─────────────────────────────────────────────────────────────

class TestApplyDrift:
    def test_invalid_diff_skipped(self):
        cur = _MockCursor()
        s = apply_drift(cur, source_id=1, company_id=2, diff="not a dict")
        assert s.skipped is True
        assert s.reason == "invalid_diff"
        assert cur.executed == []

    def test_no_change_skipped(self):
        cur = _MockCursor()
        s = apply_drift(cur, source_id=1, company_id=2,
                       diff={"added_tables": [], "removed_tables": [], "modified_tables": []})
        assert s.skipped is True
        assert s.reason == "no_change"
        assert cur.executed == []

    def test_added_only_no_invalidation(self):
        # added → no invalidation; sadece event emit beklenir (1 execute)
        cur = _MockCursor()
        s = apply_drift(cur, source_id=1, company_id=2,
                       diff={"added_tables": [{"schema": "public", "table": "newt"}]})
        assert s.skipped is False
        assert s.added_tables == ["public.newt"]
        assert s.invalidated_learned == 0
        assert s.penalized_few_shot == 0
        # event insert tek beklenen
        assert any("pipeline_events" in sql for sql, _ in cur.executed)

    def test_removed_triggers_invalidate_and_penalize(self):
        cur = _MockCursor(rowcounts=[5, 2])  # learned UPDATE=5, few_shot UPDATE=2
        diff = {
            "added_tables": [],
            "removed_tables": [{"schema": "public", "table": "old"}],
            "modified_tables": [],
        }
        s = apply_drift(cur, source_id=10, company_id=3, diff=diff)
        assert s.invalidated_learned == 5
        assert s.penalized_few_shot == 2
        assert s.removed_tables == ["public.old"]

    def test_modified_with_removed_columns_drops_embeddings(self):
        # invalidate=1, penalize=0, drop_embeddings=1, event=1
        cur = _MockCursor(rowcounts=[1, 0, 1])
        diff = {
            "modified_tables": [
                {"schema": "public", "table": "orders", "removed_columns": ["status"]}
            ]
        }
        s = apply_drift(cur, source_id=8, company_id=4, diff=diff)
        assert s.modified_tables == ["public.orders"]
        assert s.dropped_column_embeddings == 1
