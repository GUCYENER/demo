"""VYRA v3.27.0 — Result Fingerprint Cache Tests (C.G7).

Fingerprint stability + set/get round-trip + quality gates.
Cache backend is mocked via monkey-patching _get_cache.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import result_cache as rc
from app.services.safe_sql_executor import SQLResult


# ─────────────────────────────────────────────────────────────
# In-memory mock cache
# ─────────────────────────────────────────────────────────────

class _MockCache:
    def __init__(self):
        self.store = {}
        self.last_ttl = None

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value
        self.last_ttl = ttl

    def clear(self):
        self.store.clear()

    def get_stats(self):
        return {"size": len(self.store), "backend": "mock"}


@pytest.fixture(autouse=True)
def _patch_cache(monkeypatch):
    mock = _MockCache()
    monkeypatch.setattr(rc, "_get_cache", lambda: mock)
    return mock


# ─────────────────────────────────────────────────────────────
# Fingerprint
# ─────────────────────────────────────────────────────────────

class TestFingerprint:
    def test_same_sql_same_key(self):
        k1 = rc._fingerprint("SELECT * FROM t", 1)
        k2 = rc._fingerprint("SELECT * FROM t", 1)
        assert k1 == k2

    def test_whitespace_canonicalized(self):
        k1 = rc._fingerprint("SELECT * FROM t", 1)
        k2 = rc._fingerprint("  SELECT   *  FROM  t  ", 1)
        assert k1 == k2  # canonicalize_sql normalize eder

    def test_source_id_differs(self):
        k1 = rc._fingerprint("SELECT 1", 1)
        k2 = rc._fingerprint("SELECT 1", 2)
        assert k1 != k2

    def test_format(self):
        k = rc._fingerprint("SELECT 1", 42)
        assert k.startswith("sql_result:")
        assert k.endswith(":42")


# ─────────────────────────────────────────────────────────────
# get/set
# ─────────────────────────────────────────────────────────────

class TestSetGet:
    def test_round_trip_success(self, _patch_cache):
        result = SQLResult(success=True, data=[{"id": 1}], columns=["id"], row_count=1)
        ok = rc.set_cached_result("SELECT 1", 5, result)
        assert ok is True
        cached = rc.get_cached_result("SELECT 1", 5)
        assert cached is not None
        assert cached.row_count == 1

    def test_skip_failed_result(self, _patch_cache):
        result = SQLResult(success=False, error="boom")
        ok = rc.set_cached_result("SELECT 1", 5, result)
        assert ok is False
        assert rc.get_cached_result("SELECT 1", 5) is None

    def test_skip_truncated_result(self, _patch_cache):
        result = SQLResult(success=True, data=[{"x": 1}], row_count=100, truncated=True)
        ok = rc.set_cached_result("SELECT 1", 5, result)
        assert ok is False

    def test_miss_returns_none(self, _patch_cache):
        assert rc.get_cached_result("SELECT 999", 99) is None

    def test_ttl_passed_through(self, _patch_cache):
        result = SQLResult(success=True, data=[], row_count=0)
        rc.set_cached_result("SELECT 1", 1, result, ttl=42)
        assert _patch_cache.last_ttl == 42


class TestFlushStats:
    def test_flush_clears_and_returns_stats(self, _patch_cache):
        result = SQLResult(success=True, data=[{"x": 1}], row_count=1)
        rc.set_cached_result("SELECT 1", 1, result)
        assert _patch_cache.store
        out = rc.flush_all()
        assert out["ok"] is True
        assert not _patch_cache.store

    def test_stats_available(self, _patch_cache):
        s = rc.stats()
        assert s["available"] is True
        assert s["backend"] == "mock"


class TestCacheUnavailable:
    def test_get_returns_none(self, monkeypatch):
        monkeypatch.setattr(rc, "_get_cache", lambda: None)
        assert rc.get_cached_result("SELECT 1", 1) is None

    def test_set_returns_false(self, monkeypatch):
        monkeypatch.setattr(rc, "_get_cache", lambda: None)
        result = SQLResult(success=True, row_count=1)
        assert rc.set_cached_result("SELECT 1", 1, result) is False

    def test_flush_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr(rc, "_get_cache", lambda: None)
        out = rc.flush_all()
        assert out["ok"] is False
        assert out["reason"] == "cache_unavailable"
