"""VYRA v3.27.0 — Few-Shot Pruner Tests (A.END.1)."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import few_shot_pruner as pruner


class _Row(dict):
    """RealDictRow-like: dict + int-position access."""

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
    c.rowcount = 0
    return c


class TestListBuckets:
    def test_returns_normalized_dicts(self):
        cur = _cur()
        cur.fetchall.return_value = [
            {"company_id": 1, "source_id": 10, "intent": "list", "cnt": 50},
            {"company_id": 1, "source_id": 10, "intent": None, "cnt": 30},
        ]
        out = pruner._list_buckets(cur, company_id=1)
        assert len(out) == 2
        assert out[0]["company_id"] == 1
        assert out[0]["cnt"] == 50

    def test_returns_empty_when_no_rows(self):
        cur = _cur()
        out = pruner._list_buckets(cur, company_id=1)
        assert out == []


class TestPruneBucket:
    def test_no_keep_ids_means_no_delete(self):
        cur = _cur()
        # Top-N select returns nothing → keep_ids empty → no DELETE issued
        cur.fetchall.return_value = []
        deleted = pruner._prune_bucket(
            cur, company_id=1, source_id=10, intent="list", top_n=100
        )
        assert deleted == 0

    def test_deletes_what_exceeds_top_n(self):
        cur = _cur()
        # Select top-N → 2 keepers; DELETE rowcount=7
        cur.fetchall.return_value = [{"id": 1}, {"id": 2}]
        cur.rowcount = 7
        deleted = pruner._prune_bucket(
            cur, company_id=1, source_id=10, intent="list", top_n=2
        )
        assert deleted == 7


class TestDeleteStaleZeroUsage:
    def test_returns_rowcount(self):
        cur = _cur()
        cur.rowcount = 3
        n = pruner._delete_stale_zero_usage(cur, company_id=1, stale_days=90)
        assert n == 3


class TestPruneOrchestration:
    def test_summary_includes_bucket_count_and_delete_totals(self):
        cur = _cur()
        # _list_buckets fetchall returns 2 buckets;
        # then for each bucket _prune_bucket does fetchall (keep_ids) + delete;
        # then _delete_stale_zero_usage does no fetch, just rowcount.
        cur.fetchall.side_effect = [
            # _list_buckets
            [
                {"company_id": 1, "source_id": 10, "intent": "list", "cnt": 50},
                {"company_id": 1, "source_id": 20, "intent": None, "cnt": 30},
            ],
            # _prune_bucket #1 top-N keepers
            [{"id": 1}, {"id": 2}],
            # _prune_bucket #2 top-N keepers
            [{"id": 3}],
        ]
        # Each cur.execute followed by cur.rowcount returns the same value;
        # we set rowcount=5 → both DELETE bucket calls report 5,
        # final stale DELETE also reports 5.
        cur.rowcount = 5

        summary = pruner.prune(cur, company_id=1, top_n=2, stale_days=90)
        assert summary.buckets_scanned == 2
        # 5 (bucket1) + 5 (bucket2) = 10 LRU deletes
        assert summary.deleted_lru == 10
        assert summary.deleted_stale == 5

    def test_handles_bucket_exception_without_aborting(self):
        cur = _cur()
        cur.fetchall.side_effect = [
            [{"company_id": 1, "source_id": 10, "intent": None, "cnt": 5}],
            # _prune_bucket raises on the second fetchall
            RuntimeError("oops"),
        ]
        summary = pruner.prune(cur, company_id=1, top_n=10, stale_days=30)
        assert summary.buckets_scanned == 1
        assert summary.deleted_lru == 0  # bucket failure ate the count
