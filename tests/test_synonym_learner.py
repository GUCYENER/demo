"""VYRA v3.27.0 — Synonym Auto-Learner Tests (C.G5)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import synonym_learner as sl
from app.services.db_learning.synonym_learner import (
    SIM_HIGH,
    SIM_LOW,
    _llm_verdict,
    is_borderline,
    list_pending,
    propose_synonym,
    review,
)


class _Row(dict):
    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


class _MockCursor:
    def __init__(self, fetch_one=None, fetch_all=None, rowcounts=None):
        self.executed = []
        self._fetch_one = fetch_one if isinstance(fetch_one, list) else [fetch_one]
        self._fetch_all = fetch_all or []
        self._rowcounts = list(rowcounts or [])
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._rowcounts:
            self.rowcount = self._rowcounts.pop(0)

    def fetchone(self):
        if self._fetch_one:
            return self._fetch_one.pop(0)
        return None

    def fetchall(self):
        return self._fetch_all


# ─────────────────────────────────────────────────────────────
# Eligibility
# ─────────────────────────────────────────────────────────────

class TestBorderline:
    def test_within_range(self):
        assert is_borderline(0.65) is True
        assert is_borderline(0.70) is True
        assert is_borderline(0.84999) is True

    def test_out_of_range(self):
        assert is_borderline(0.5) is False
        assert is_borderline(0.85) is False
        assert is_borderline(0.95) is False

    def test_invalid_input(self):
        assert is_borderline(None) is False
        assert is_borderline("x") is False


# ─────────────────────────────────────────────────────────────
# LLM verdict
# ─────────────────────────────────────────────────────────────

class TestLlmVerdict:
    def test_no_callable_returns_uncertain(self):
        v, r = _llm_verdict("ad", "", "users", "name", None)
        assert v == "uncertain"
        assert r is None

    def test_match_response(self):
        v, _ = _llm_verdict("ad", "", "users", "name", lambda p: "match")
        assert v == "match"

    def test_turkish_evet(self):
        v, _ = _llm_verdict("ad", "", "users", "name", lambda p: "Evet, eşanlamlı")
        assert v == "match"

    def test_no_match(self):
        v, _ = _llm_verdict("foo", "", "t", "c", lambda p: "no_match")
        assert v == "no_match"

    def test_unknown_returns_uncertain(self):
        v, _ = _llm_verdict("foo", "", "t", "c", lambda p: "belirsiz")
        assert v == "uncertain"

    def test_llm_exception_safe(self):
        def boom(p):
            raise RuntimeError("llm down")
        v, r = _llm_verdict("foo", "", "t", "c", boom)
        assert v == "uncertain"


# ─────────────────────────────────────────────────────────────
# propose_synonym
# ─────────────────────────────────────────────────────────────

class TestProposeSynonym:
    def test_skip_out_of_range(self):
        cur = _MockCursor()
        r = propose_synonym(cur, source_id=1, company_id=2,
                            user_term="ad", schema_name="public",
                            table_name="users", column_name="name",
                            similarity=0.9)
        assert r.status == "skipped"
        assert r.reason == "out_of_range"
        assert cur.executed == []

    def test_skip_missing_fields(self):
        cur = _MockCursor()
        r = propose_synonym(cur, source_id=1, company_id=2,
                            user_term="", schema_name="public",
                            table_name="users", column_name="name",
                            similarity=0.7)
        assert r.status == "skipped"
        assert r.reason == "missing_fields"

    def test_bump_existing(self):
        # existing fetchone → existing row; sonra _bump_observed UPDATE
        existing = _Row({"id": 5, "status": "pending", "observed_count": 2})
        cur = _MockCursor(fetch_one=[existing])
        r = propose_synonym(cur, source_id=1, company_id=2,
                            user_term="ad", schema_name="public",
                            table_name="users", column_name="name",
                            similarity=0.75)
        assert r.status == "bumped"
        assert r.id == 5
        # SELECT + UPDATE
        assert len(cur.executed) == 2
        assert "UPDATE synonym_suggestions" in cur.executed[1][0]

    def test_insert_new_with_llm_match(self):
        # Not exist → INSERT, fetchone(id) döndür
        cur = _MockCursor(fetch_one=[None, _Row({"id": 100})])
        r = propose_synonym(cur, source_id=1, company_id=2,
                            user_term="müşteri", schema_name="public",
                            table_name="customers", column_name="customer_name",
                            similarity=0.72,
                            llm_callable=lambda p: "match")
        assert r.status == "inserted"
        assert r.id == 100
        assert r.verdict == "match"
        # SELECT + INSERT
        assert any("INSERT INTO synonym_suggestions" in sql for sql, _ in cur.executed)

    def test_skip_llm_no_match(self):
        cur = _MockCursor(fetch_one=[None])
        r = propose_synonym(cur, source_id=1, company_id=2,
                            user_term="random", schema_name="public",
                            table_name="t", column_name="c",
                            similarity=0.70,
                            llm_callable=lambda p: "no_match")
        assert r.status == "skipped"
        assert r.verdict == "no_match"
        assert r.reason == "llm_no_match"
        # Only SELECT executed — no INSERT
        assert len(cur.executed) == 1

    def test_insert_uncertain_when_no_llm(self):
        cur = _MockCursor(fetch_one=[None, _Row({"id": 7})])
        r = propose_synonym(cur, source_id=1, company_id=2,
                            user_term="ad", schema_name="public",
                            table_name="users", column_name="name",
                            similarity=0.7)
        assert r.status == "inserted"
        assert r.verdict == "uncertain"


# ─────────────────────────────────────────────────────────────
# list_pending
# ─────────────────────────────────────────────────────────────

class TestListPending:
    def test_global_filter(self):
        rows = [_Row({"id": 1, "user_term": "ad"})]
        cur = _MockCursor(fetch_all=rows)
        out = list_pending(cur, limit=10)
        assert len(out) == 1
        sql = cur.executed[0][0]
        assert "status = 'pending'" in sql
        assert "AND source_id" not in sql

    def test_source_scoped(self):
        cur = _MockCursor(fetch_all=[])
        list_pending(cur, source_id=5, limit=10)
        sql, params = cur.executed[0]
        assert "source_id = %s" in sql
        assert params[0] == 5


# ─────────────────────────────────────────────────────────────
# review
# ─────────────────────────────────────────────────────────────

class TestReview:
    def test_approve_success(self):
        cur = _MockCursor(rowcounts=[1])
        ok = review(cur, 10, decision="approved", reviewer_user_id=99)
        assert ok is True
        sql, params = cur.executed[0]
        assert "UPDATE synonym_suggestions" in sql
        assert params[0] == "approved"
        assert params[1] == 99
        assert params[2] == 10

    def test_reject_success(self):
        cur = _MockCursor(rowcounts=[1])
        assert review(cur, 11, decision="rejected", reviewer_user_id=1) is True

    def test_invalid_decision(self):
        cur = _MockCursor()
        assert review(cur, 1, decision="maybe", reviewer_user_id=1) is False
        assert cur.executed == []

    def test_not_found(self):
        cur = _MockCursor(rowcounts=[0])
        assert review(cur, 999, decision="approved", reviewer_user_id=1) is False
