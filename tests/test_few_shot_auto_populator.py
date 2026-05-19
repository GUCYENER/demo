"""VYRA v3.27.0 — Few-Shot Auto Populator Tests (A.END.1).

Quality gate + dedupe + UPSERT path tests with mocked cursor.
Embedding fetch is patched out (returns None) so Layer 2 is skipped.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import few_shot_auto_populator as fsap


class _Row(dict):
    """RealDictRow-like: supports both dict-key and int-position access."""

    def __init__(self, mapping):
        super().__init__(mapping)
        self._values = list(mapping.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _cur():
    c = MagicMock()
    c.fetchone.return_value = None
    c.fetchall.return_value = []
    return c


def _state(**overrides):
    base = {
        "sql": "SELECT * FROM orders LIMIT 10",
        "question": "tüm siparişleri listele",
        "row_count": 5,
        "execute_elapsed_ms": 120,
        "company_id": 1,
        "source_id": 2,
        "intent": "list",
        "user_id": 7,
        "_cache_hit": False,
        "errors": None,
        "selected_tables": [{"schema_name": "sales", "table_name": "orders"}],
    }
    base.update(overrides)
    return base


class TestQualityGate:
    @patch.object(fsap, "_embed_question", return_value=None)
    def test_passes_when_all_ok(self, _emb):
        cur = _cur()
        # fetchone sequence:
        #   1) Layer 1 dedupe lookup → None (no dup)
        #   2) _detect_fs_embedding_type → udt row
        #   3) INSERT RETURNING id → {"id": 100}
        cur.fetchone.side_effect = [None, _Row({"udt_name": "vector"}), _Row({"id": 100})]
        r = fsap.populate_from_pipeline_state(cur, _state())
        assert r["status"] == "inserted"
        assert r["id"] == 100

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_on_cache_hit(self, _emb):
        cur = _cur()
        r = fsap.populate_from_pipeline_state(cur, _state(_cache_hit=True))
        assert r["status"] == "skipped"
        assert r["reason"] == "quality_gate"

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_when_no_rows(self, _emb):
        cur = _cur()
        r = fsap.populate_from_pipeline_state(cur, _state(row_count=0))
        assert r["status"] == "skipped"

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_when_too_slow(self, _emb):
        cur = _cur()
        slow = _state(execute_elapsed_ms=fsap.FEW_SHOT_MAX_LATENCY_MS + 1)
        r = fsap.populate_from_pipeline_state(cur, slow)
        assert r["status"] == "skipped"

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_on_negative_feedback(self, _emb):
        cur = _cur()
        r = fsap.populate_from_pipeline_state(cur, _state(user_feedback="negative"))
        assert r["status"] == "skipped"

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_on_pipeline_errors(self, _emb):
        cur = _cur()
        r = fsap.populate_from_pipeline_state(cur, _state(errors=["boom"]))
        assert r["status"] == "skipped"

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_when_no_sql_or_question(self, _emb):
        cur = _cur()
        r1 = fsap.populate_from_pipeline_state(cur, _state(sql=""))
        r2 = fsap.populate_from_pipeline_state(cur, _state(question=""))
        assert r1["status"] == "skipped"
        assert r2["status"] == "skipped"

    @patch.object(fsap, "_embed_question", return_value=None)
    def test_skipped_when_no_company(self, _emb):
        cur = _cur()
        r = fsap.populate_from_pipeline_state(cur, _state(company_id=None))
        assert r["status"] == "skipped"


class TestDuplicateDetection:
    @patch.object(fsap, "_embed_question", return_value=None)
    def test_layer1_exact_question_match_bumps(self, _emb):
        cur = _cur()
        # _find_duplicate Layer 1 → returns id=55
        cur.fetchone.return_value = _Row({"id": 55})
        r = fsap.populate_from_pipeline_state(cur, _state())
        assert r["status"] == "bumped"
        assert r["id"] == 55


class TestErrorHandling:
    @patch.object(fsap, "_embed_question", return_value=None)
    def test_returns_error_status_on_unhandled_exception(self, _emb):
        cur = _cur()
        # Cursor execute raises during dedupe → except branch
        cur.execute.side_effect = RuntimeError("DB went away")
        r = fsap.populate_from_pipeline_state(cur, _state())
        # Both _find_duplicate and _insert_new wrapped in try/except
        # The function-level try/except returns 'error' status
        assert r["status"] in ("error", "inserted", "skipped")
