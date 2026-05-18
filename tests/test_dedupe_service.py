"""VYRA v3.27.0 — Dedupe Service Tests (A.END.1).

Pure-function tests:
  - canonicalize_sql (literal/whitespace/case)
  - sql_hash (stable, dedupes literal-only-differences)
  - jaccard (set similarity)
  - build_schema_signature (sorted unique csv)
  - normalize_question (whitespace squash + lowercase)
  - check_duplicate (Layer 1/2/3 with mocked cursor)
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning.dedupe_service import (
    build_schema_signature,
    canonicalize_sql,
    check_duplicate,
    jaccard,
    normalize_question,
    sql_hash,
)


class TestCanonicalizeSql:
    def test_lowercases_and_strips_whitespace(self):
        assert canonicalize_sql("  SELECT  *\nFROM t  ") == canonicalize_sql("select * from t")

    def test_masks_string_literals_to_same_hash(self):
        a = "SELECT * FROM users WHERE name = 'Alice'"
        b = "SELECT * FROM users WHERE name = 'Bob'"
        assert sql_hash(a) == sql_hash(b)

    def test_different_columns_produce_different_hash(self):
        a = "SELECT name FROM users"
        b = "SELECT email FROM users"
        assert sql_hash(a) != sql_hash(b)

    def test_empty_input(self):
        assert canonicalize_sql("") == ""
        assert canonicalize_sql(None) == ""  # type: ignore[arg-type]


class TestSqlHash:
    def test_deterministic(self):
        h1 = sql_hash("SELECT 1 FROM dual")
        h2 = sql_hash("select 1 from dual")
        assert h1 == h2

    def test_hex_64_chars(self):
        h = sql_hash("SELECT 1")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestJaccard:
    def test_identical_sets(self):
        assert jaccard({"a", "b"}, {"a", "b"}) == pytest.approx(1.0)

    def test_disjoint_sets(self):
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        # |A ∩ B| = 1, |A ∪ B| = 3 → 1/3
        assert jaccard({"a", "b"}, {"a", "c"}) == pytest.approx(1.0 / 3.0)

    def test_empty_both(self):
        # convention: two empty sets are vacuously identical → 1.0
        assert jaccard(set(), set()) == 1.0

    def test_empty_one_side(self):
        assert jaccard(set(), {"a"}) == 0.0
        assert jaccard({"a"}, set()) == 0.0


class TestBuildSchemaSignature:
    def test_sorted_unique_lowercased(self):
        sig = build_schema_signature(["Sales.Orders", "public.customers", "sales.orders"])
        # case-insensitive de-dupe + sort
        assert sig == "public.customers,sales.orders"

    def test_empty_input(self):
        assert build_schema_signature([]) == ""
        assert build_schema_signature([" ", "", None]) == ""  # type: ignore[list-item]


class TestNormalizeQuestion:
    def test_lowercase_and_squash_whitespace(self):
        assert normalize_question("  Hello   World  ") == "hello world"

    def test_handles_none_empty(self):
        # normalize_question expects a string; guard with empty
        assert normalize_question("") == ""


# ─────────────────────────────────────────────────────────────
# check_duplicate — mocked cursor
# ─────────────────────────────────────────────────────────────


class _Row(dict):
    """RealDictRow-like: dict access + int access by position."""

    def __init__(self, mapping):
        super().__init__(mapping)
        self._values = list(mapping.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _mk_cursor():
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []
    return cur


class TestCheckDuplicateLayer1:
    def test_returns_match_when_hash_found(self):
        cur = _mk_cursor()
        cur.fetchone.return_value = _Row({"id": 42})
        m = check_duplicate(cur, source_id=1, sql="SELECT 1", question="x")
        assert m is not None
        assert m.existing_id == 42
        assert m.layer == 1
        assert m.reason == "sql_hash"

    def test_returns_none_when_no_match(self):
        cur = _mk_cursor()
        m = check_duplicate(cur, source_id=1, sql="SELECT 1", question="x")
        assert m is None


class TestCheckDuplicateLayer3:
    def test_jaccard_match_above_threshold(self):
        cur = _mk_cursor()
        # Layer 1 + 2 → no match
        # Layer 3 → fetchall returns one row with identical schema signature
        cur.fetchall.return_value = [
            _Row({"id": 7, "schema_signature": "public.orders,public.customers"})
        ]
        m = check_duplicate(
            cur,
            source_id=1,
            sql="SELECT 1",
            question="x",
            schema_signature="public.orders,public.customers",
        )
        assert m is not None
        assert m.existing_id == 7
        assert m.layer == 3
        assert m.similarity >= 0.85

    def test_no_match_when_signatures_disjoint(self):
        cur = _mk_cursor()
        cur.fetchall.return_value = [
            _Row({"id": 9, "schema_signature": "sales.invoices"})
        ]
        m = check_duplicate(
            cur,
            source_id=1,
            sql="SELECT 1",
            question="x",
            schema_signature="public.customers,public.orders",
        )
        assert m is None
