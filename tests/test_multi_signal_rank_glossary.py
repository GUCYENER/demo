"""VYRA v3.29.7 G1 — multi_signal_rank glossary_match_score testleri.

Pure-function testler. DB yok; sadece dict in/out.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.nodes.multi_signal_rank import (
    DEFAULT_WEIGHTS,
    _glossary_match_score,
    multi_signal_rank,
)


@pytest.fixture
def candidate_problem():
    return {
        "schema_name": "public",
        "table_name": "problem",
        "business_name_tr": "Problem Kaydı",
        "semantic_score": 0.6,
    }


@pytest.fixture
def candidate_party():
    return {
        "schema_name": "public",
        "table_name": "party",
        "business_name_tr": "Taraf",
        "semantic_score": 0.6,
    }


@pytest.fixture
def hints_l1_verified():
    """Admin onaylı: 'L1' → public.problem"""
    return [
        {
            "term": "L1",
            "term_type": "acronym",
            "expansion_tr": "Level 1 destek kaydı",
            "schema": "public",
            "table": "problem",
            "column": None,
            "mapped_table": None,
            "mapped_columns": [],
            "admin_verified": True,
        }
    ]


@pytest.fixture
def hints_l1_unverified():
    """Admin onayı olmayan: 0.6× indirim"""
    return [
        {
            "term": "L1",
            "schema": "public",
            "table": "problem",
            "admin_verified": False,
        }
    ]


class TestGlossaryMatchScore:
    def test_no_hints_returns_zero(self, candidate_problem):
        assert _glossary_match_score(candidate_problem, None) == 0.0
        assert _glossary_match_score(candidate_problem, []) == 0.0

    def test_verified_table_match_strong(self, candidate_problem, hints_l1_verified):
        score = _glossary_match_score(candidate_problem, hints_l1_verified)
        # 1.0 raw * 1.0 weight_factor * (0.7 + 0.3 * log1p(1)/log1p(3)) ≈ 0.85
        assert 0.7 <= score <= 1.0

    def test_unverified_match_dampened(self, candidate_problem, hints_l1_unverified):
        v = _glossary_match_score(candidate_problem, [{
            "schema": "public", "table": "problem", "admin_verified": True,
        }])
        u = _glossary_match_score(candidate_problem, hints_l1_unverified)
        assert u < v
        assert u > 0.0

    def test_non_match_returns_zero(self, candidate_party, hints_l1_verified):
        assert _glossary_match_score(candidate_party, hints_l1_verified) == 0.0

    def test_mapped_table_match(self, candidate_problem):
        hints = [{
            "term": "ticket",
            "schema": None,
            "table": None,
            "mapped_table": "problem",
            "admin_verified": True,
        }]
        score = _glossary_match_score(candidate_problem, hints)
        assert score > 0.5

    def test_schema_only_weak(self, candidate_problem):
        hints = [{
            "schema": "public",
            "table": None,
            "admin_verified": True,
        }]
        score = _glossary_match_score(candidate_problem, hints)
        # schema-only: 0.3 raw → çıktı zayıf ama >0
        assert 0.0 < score < 0.5

    def test_table_same_schema_different_partial(self, candidate_problem):
        # public.problem aday; hint hr.problem → tablo aynı, schema farklı
        hints = [{
            "schema": "hr",
            "table": "problem",
            "admin_verified": True,
        }]
        score = _glossary_match_score(candidate_problem, hints)
        # 0.5 raw → çıktı orta
        assert 0.3 < score < 0.8

    def test_multiple_hits_log_saturation(self, candidate_problem):
        hint = {"schema": "public", "table": "problem", "admin_verified": True}
        s1 = _glossary_match_score(candidate_problem, [hint])
        s3 = _glossary_match_score(candidate_problem, [hint, hint, hint])
        assert s3 >= s1  # log-saturated boost


class TestMultiSignalRankIntegration:
    def test_glossary_hint_promotes_match(self, candidate_problem, candidate_party,
                                          hints_l1_verified):
        candidates = [candidate_party, candidate_problem]
        # 'L1 ticketları' → glossary hint problem'i hedefler
        ranked = multi_signal_rank(
            candidates, "L1 ticketları",
            glossary_hints=hints_l1_verified,
        )
        # Problem en üste çıkmalı (glossary boost'u var)
        assert ranked[0]["table_name"] == "problem"
        assert ranked[0]["glossary_match_score"] > 0.0
        assert ranked[1]["glossary_match_score"] == 0.0

    def test_no_glossary_hints_no_signal(self, candidate_problem):
        ranked = multi_signal_rank([candidate_problem], "test")
        assert ranked[0]["glossary_match_score"] == 0.0

    def test_default_weights_sum_close_to_one(self):
        total = sum(DEFAULT_WEIGHTS.values())
        assert 0.95 <= total <= 1.05

    def test_glossary_match_weight_present(self):
        assert "glossary_match" in DEFAULT_WEIGHTS
        assert DEFAULT_WEIGHTS["glossary_match"] > 0
