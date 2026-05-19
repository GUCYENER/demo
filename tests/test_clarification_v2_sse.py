"""VYRA v3.29.7 G2 — clarification_v2 SSE adapter testleri."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.sse_adapter import (
    format_sse,
    state_to_clarification_event,
    state_to_clarification_v2_event,
    stream_clarification,
)


@pytest.fixture
def state_with_cards():
    return {
        "question": "L1 problemleri listele",
        "clarification_payload": {
            "reason": "top1_top2_tight",
            "candidates": [
                {"schema_name": "public", "table_name": "problem",
                 "business_name_tr": "Problem Kaydı", "final_score": 0.78},
                {"schema_name": "hr", "table_name": "problem",
                 "business_name_tr": "İK Problem", "final_score": 0.74},
            ],
            "confidence": 0.62,
            "question": "L1 problemleri listele",
        },
        "clarification_cards": [
            {
                "schema": "public", "table": "problem",
                "label_tr": "Problem Kaydı", "score": 0.78,
                "matched_terms": ["L1", "problem"],
                "row_count_estimate": 1240,
                "preview_sql": 'SELECT * FROM "problem" LIMIT 3',
                "sample_rows": [{"id": 1, "title": "test"}],
                "masked_columns": ["email"],
                "join_paths_to_target": [["public.problem", "public.party"]],
                "truncated": False,
            },
            {
                "schema": "hr", "table": "problem",
                "label_tr": "İK Problem", "score": 0.74,
                "matched_terms": ["problem"],
                "row_count_estimate": 50,
                "preview_sql": 'SELECT * FROM "hr"."problem" LIMIT 3',
                "sample_rows": [],
                "masked_columns": [],
                "join_paths_to_target": [],
                "truncated": False,
            },
        ],
    }


class TestClarificationV2:
    def test_v2_event_type(self, state_with_cards):
        evt = state_to_clarification_v2_event(state_with_cards)
        assert evt["type"] == "clarification_v2"

    def test_v2_cards_present(self, state_with_cards):
        evt = state_to_clarification_v2_event(state_with_cards)
        cards = evt["data"]["cards"]
        assert len(cards) == 2
        assert cards[0]["table"] == "problem"
        assert cards[0]["row_count_estimate"] == 1240
        assert "sample_rows" in cards[0]
        assert "join_paths_to_target" in cards[0]
        assert "masked_columns" in cards[0]

    def test_v2_message_reason(self, state_with_cards):
        evt = state_to_clarification_v2_event(state_with_cards)
        assert evt["data"]["reason"] == "top1_top2_tight"
        assert "Birden fazla" in evt["data"]["message"]

    def test_v2_confidence_propagated(self, state_with_cards):
        evt = state_to_clarification_v2_event(state_with_cards)
        assert abs(evt["data"]["confidence"] - 0.62) < 0.001

    def test_v2_empty_cards_fallback(self):
        state = {
            "clarification_payload": {"reason": "below_threshold", "candidates": []},
        }
        evt = state_to_clarification_v2_event(state)
        assert evt["data"]["cards"] == []

    def test_v2_cards_from_payload_fallback(self):
        state = {
            "clarification_payload": {
                "reason": "below_threshold",
                "cards": [{"table": "x"}],
            }
        }
        evt = state_to_clarification_v2_event(state)
        assert evt["data"]["cards"] == [{"table": "x"}]


class TestBackwardCompat:
    def test_v1_event_still_works(self, state_with_cards):
        evt = state_to_clarification_event(state_with_cards)
        assert evt["type"] == "clarification"
        assert len(evt["data"]["candidates"]) == 2

    def test_stream_emits_both_when_cards(self, state_with_cards):
        events = list(stream_clarification(state_with_cards))
        # SSE wire format string'leri
        assert len(events) == 2
        e1 = json.loads(events[0].replace("data: ", "").strip())
        e2 = json.loads(events[1].replace("data: ", "").strip())
        assert e1["type"] == "clarification"
        assert e2["type"] == "clarification_v2"

    def test_stream_only_v1_when_no_cards(self):
        state = {
            "clarification_payload": {"reason": "below_threshold", "candidates": []},
        }
        events = list(stream_clarification(state))
        assert len(events) == 1
        e1 = json.loads(events[0].replace("data: ", "").strip())
        assert e1["type"] == "clarification"


class TestFormatSSE:
    def test_format_sse_includes_data_prefix(self):
        s = format_sse({"type": "x", "data": {"a": 1}})
        assert s.startswith("data: ")
        assert s.endswith("\n\n")

    def test_format_sse_turkish_chars(self):
        s = format_sse({"type": "x", "data": {"msg": "İşlem başarılı çğşı"}})
        assert "İşlem başarılı çğşı" in s  # ensure_ascii=False
