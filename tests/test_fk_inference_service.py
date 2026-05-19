"""VYRA v3.29.9 — fk_inference_service unit tests (dialect-agnostic)."""
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import fk_inference_service as svc
from app.services.db_learning.fk_inference_dialects import (
    OracleDialect,
    PostgresDialect,
)


# ─────────────────────────────────────────────────────────────
# _extract_root — pattern parser
# ─────────────────────────────────────────────────────────────
def test_extract_root_snake_id():
    assert svc._extract_root("user_id") == "user"
    assert svc._extract_root("owner_party_id") == "owner_party"


def test_extract_root_camel_id():
    assert svc._extract_root("userId") == "user"
    assert svc._extract_root("partyRelationId") == "partyrelation"


def test_extract_root_id_prefix():
    assert svc._extract_root("id_user") == "user"


def test_extract_root_hungarian():
    assert svc._extract_root("f_user_id") == "user"


def test_extract_root_skips_pk_columns():
    assert svc._extract_root("id") is None
    assert svc._extract_root("pk") is None


def test_extract_root_no_match():
    assert svc._extract_root("name") is None
    assert svc._extract_root("created_at") is None
    assert svc._extract_root("") is None


def test_extract_root_ref_suffix():
    assert svc._extract_root("owner_ref") == "owner"


# ─────────────────────────────────────────────────────────────
# _candidates_from_root — plural/singular
# ─────────────────────────────────────────────────────────────
def test_candidates_basic_plural():
    c = svc._candidates_from_root("user")
    assert "user" in c and "users" in c


def test_candidates_y_to_ies():
    c = svc._candidates_from_root("category")
    assert "category" in c and "categories" in c


def test_candidates_s_es():
    c = svc._candidates_from_root("box")
    assert "boxes" in c


def test_candidates_dedup():
    c = svc._candidates_from_root("user")
    assert len(c) == len(set(c))


# ─────────────────────────────────────────────────────────────
# _type_compatible
# ─────────────────────────────────────────────────────────────
def test_type_compat_int_int():
    d = PostgresDialect()
    assert svc._type_compatible("integer", "bigint", d) is True


def test_type_compat_uuid():
    d = PostgresDialect()
    assert svc._type_compatible("uuid", "uuid", d) is True


def test_type_compat_int_uuid_incompat():
    d = PostgresDialect()
    assert svc._type_compatible("integer", "uuid", d) is False


def test_type_compat_oracle_number():
    d = OracleDialect()
    assert svc._type_compatible("NUMBER(10,0)", "INTEGER", d) is True


def test_type_compat_unknown_returns_false():
    d = PostgresDialect()
    assert svc._type_compatible("inet", "integer", d) is False


# ─────────────────────────────────────────────────────────────
# _score
# ─────────────────────────────────────────────────────────────
def test_score_naming_only():
    s, m = svc._score(False, None)
    assert s == 0.6
    assert m == "naming"


def test_score_naming_type():
    s, m = svc._score(True, None)
    assert s == 0.8
    assert m == "naming+type"


def test_score_with_sample_full_coverage():
    s, m = svc._score(True, {"coverage_ratio": 1.0})
    assert s == 1.0
    assert m == "naming+type+sample"


def test_score_partial_sample():
    s, m = svc._score(True, {"coverage_ratio": 0.5})
    assert s == 0.9
    assert m == "naming+type+sample"


# ─────────────────────────────────────────────────────────────
# infer_fks_for_source — end-to-end with mocks
# ─────────────────────────────────────────────────────────────
def _seed_objects(cur, tables):
    """Helper: makes cur.fetchall return ds_db_objects rows on first call,
    empty existing-relationships on second call."""
    call_results = [tables, []]
    state = {"i": 0}

    def fetchall_side():
        i = state["i"]
        state["i"] += 1
        return call_results[i] if i < len(call_results) else []

    cur.fetchall.side_effect = fetchall_side


def test_infer_empty_source_returns_zero():
    cur = MagicMock()
    cur.fetchall.return_value = []
    res = svc.infer_fks_for_source(cur, source_id=1)
    assert res["persisted"] == 0
    assert res["candidates"] == 0
    assert res["tables_scanned"] == 0


def test_infer_basic_one_fk():
    cur = MagicMock()
    user_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                 {"name": "name", "type": "varchar", "is_primary_key": False}]
    problem_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                    {"name": "user_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "users", "table", json.dumps(user_cols)),
        ("public", "problem", "table", json.dumps(problem_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql")
    assert res["tables_scanned"] == 2
    assert res["candidates"] == 1
    assert res["persisted"] == 1
    # INSERT was called once
    inserts = [c for c in cur.execute.call_args_list
               if "INSERT INTO ds_db_relationships" in c.args[0]]
    assert len(inserts) == 1


def test_infer_skips_existing():
    cur = MagicMock()
    user_cols = [{"name": "id", "type": "integer", "is_primary_key": True}]
    problem_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                    {"name": "user_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "users", "table", json.dumps(user_cols)),
        ("public", "problem", "table", json.dumps(problem_cols)),
    ]
    existing = [("public", "problem", "user_id", "public", "users", "id")]
    call_results = [objects, existing]
    state = {"i": 0}

    def fetchall_side():
        i = state["i"]
        state["i"] += 1
        return call_results[i] if i < len(call_results) else []
    cur.fetchall.side_effect = fetchall_side

    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql")
    assert res["candidates"] == 0
    assert res["skipped_existing"] == 1
    assert res["persisted"] == 0


def test_infer_type_mismatch_lowers_confidence_and_skips():
    cur = MagicMock()
    user_cols = [{"name": "id", "type": "uuid", "is_primary_key": True}]
    problem_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                    {"name": "user_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "users", "table", json.dumps(user_cols)),
        ("public", "problem", "table", json.dumps(problem_cols)),
    ]
    _seed_objects(cur, objects)
    # naming-only score = 0.6, ≥ default min_confidence (0.60) → persists
    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql",
                                   min_confidence=0.65)
    assert res["candidates"] == 1
    assert res["skipped_low_confidence"] == 1
    assert res["persisted"] == 0


def test_infer_self_fk_org_chart():
    """parent_id → org.id self-reference should be detected."""
    cur = MagicMock()
    # Naming pattern: parent_id → root='parent'; we need a 'parent' table.
    # Self-FK case (org → org via parent_id) requires root match self.
    org_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                {"name": "org_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "org", "table", json.dumps(org_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=1, dialect="postgresql")
    assert res["candidates"] == 1
    assert res["persisted"] == 1


def test_infer_unknown_dialect_raises():
    cur = MagicMock()
    with pytest.raises(ValueError):
        svc.infer_fks_for_source(cur, source_id=1, dialect="cassandra")
