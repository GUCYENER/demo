"""VYRA v3.27.0 — Reasoning Trace Writer Tests (C.G9).

State → row mapping + INSERT mock + skip conditions.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning.trace_writer import _build_row, fetch_trace, write_trace


class _Row(dict):
    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


class _MockCursor:
    def __init__(self, fetch=None):
        self.executed = []
        self._fetch = fetch
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetch


# ─────────────────────────────────────────────────────────────
# _build_row
# ─────────────────────────────────────────────────────────────

class TestBuildRow:
    def test_minimal_state(self):
        s = {"question": "kaç sipariş", "source_id": 1, "run_id": "r1"}
        row = _build_row(s)
        assert row["question"] == "kaç sipariş"
        assert row["source_id"] == 1
        assert row["run_id"] == "r1"
        assert row["cache_hit"] is False
        assert row["ast_shortcut_used"] is False
        assert row["self_heal_iterations"] == 0

    def test_cache_hit_flag(self):
        s = {"question": "q", "source_id": 1, "run_id": "r1", "_cache_hit": True, "cache_hit_id": 99}
        row = _build_row(s)
        assert row["cache_hit"] is True
        assert row["cache_hit_id"] == 99

    def test_ast_shortcut_flag(self):
        s = {"question": "q", "source_id": 1, "run_id": "r1", "sql_source": "ast_shortcut"}
        row = _build_row(s)
        assert row["ast_shortcut_used"] is True

    def test_validation_errors_strings_to_dicts(self):
        s = {"question": "q", "source_id": 1, "run_id": "r1", "validation_errors": ["err1", "err2"]}
        row = _build_row(s)
        decoded = json.loads(row["validation_errors"])
        assert decoded == [{"message": "err1"}, {"message": "err2"}]

    def test_validation_errors_dicts_passthrough(self):
        errs = [{"code": "E1", "message": "x"}]
        s = {"question": "q", "source_id": 1, "run_id": "r1", "validation_errors": errs}
        row = _build_row(s)
        assert json.loads(row["validation_errors"]) == errs

    def test_few_shot_ids_int_coercion(self):
        s = {"question": "q", "source_id": 1, "run_id": "r1",
             "few_shot_used_ids": [1, "2", 3.0, "bad"]}
        row = _build_row(s)
        assert row["few_shot_ids"] == [1, 2, 3]

    def test_candidates_jsonified(self):
        s = {"question": "q", "source_id": 1, "run_id": "r1",
             "ranked_tables": [{"table": "orders", "score": 0.9}]}
        row = _build_row(s)
        decoded = json.loads(row["candidates_json"])
        assert decoded[0]["table"] == "orders"

    def test_question_truncated(self):
        s = {"question": "x" * 9000, "source_id": 1, "run_id": "r1"}
        row = _build_row(s)
        assert len(row["question"]) == 8000


# ─────────────────────────────────────────────────────────────
# write_trace
# ─────────────────────────────────────────────────────────────

class TestWriteTrace:
    def test_skip_missing_question(self):
        cur = _MockCursor()
        assert write_trace(cur, {"source_id": 1, "run_id": "r1"}) is None
        assert cur.executed == []

    def test_skip_missing_source_id(self):
        cur = _MockCursor()
        assert write_trace(cur, {"question": "q", "run_id": "r1"}) is None

    def test_skip_missing_run_id(self):
        cur = _MockCursor()
        assert write_trace(cur, {"question": "q", "source_id": 1}) is None

    def test_inserts_and_returns_id(self):
        cur = _MockCursor(fetch=_Row({"id": 42}))
        tid = write_trace(cur, {"question": "q", "source_id": 1, "run_id": "r1"})
        assert tid == 42
        assert len(cur.executed) == 1
        sql, params = cur.executed[0]
        assert "INSERT INTO pipeline_traces" in sql
        assert params["run_id"] == "r1"

    def test_returns_id_tuple_row(self):
        cur = _MockCursor(fetch=(99,))
        tid = write_trace(cur, {"question": "q", "source_id": 1, "run_id": "r1"})
        assert tid == 99


# ─────────────────────────────────────────────────────────────
# fetch_trace
# ─────────────────────────────────────────────────────────────

class TestFetchTrace:
    def test_neither_param_returns_none(self):
        assert fetch_trace(_MockCursor()) is None

    def test_by_id(self):
        cur = _MockCursor(fetch={"id": 1, "run_id": "r1"})
        out = fetch_trace(cur, trace_id=1)
        assert out == {"id": 1, "run_id": "r1"}
        assert "WHERE id = %s" in cur.executed[0][0]

    def test_by_run_id(self):
        cur = _MockCursor(fetch={"id": 1, "run_id": "abc"})
        out = fetch_trace(cur, run_id="abc")
        assert out["run_id"] == "abc"
        assert "WHERE run_id = %s" in cur.executed[0][0]
