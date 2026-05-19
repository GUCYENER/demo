"""VYRA v3.29.8 L1 — multi_signal_rank_node signal_breakdown event emit testleri.

`multi_signal_rank_node` çağrıldığında pipeline_events tablosuna
`signal_breakdown` event'i emit eder. Bu test, emit_event'in beklenen
metadata ile çağrıldığını doğrular (cursor mock).
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.nodes.multi_signal_rank import multi_signal_rank_node


@pytest.fixture
def state_with_candidates():
    return {
        "question": "son 5 problem kaydını listele",
        "candidates": [
            {
                "schema_name": "public",
                "table_name": "problem",
                "business_name_tr": "Problem",
                "semantic_score": 0.85,
            },
            {
                "schema_name": "public",
                "table_name": "party",
                "business_name_tr": "Taraf",
                "semantic_score": 0.55,
            },
            {
                "schema_name": "public",
                "table_name": "workflow_status",
                "semantic_score": 0.40,
            },
        ],
        "_pipeline_run_id": "test-run-l1-001",
    }


def test_signal_breakdown_emitted(state_with_candidates):
    """Node çağrıldığında signal_breakdown event emit edilmeli."""
    with patch("app.services.pipeline.observability.emit_event") as mock_emit:
        result = multi_signal_rank_node(state_with_candidates)

    assert "ranked_candidates" in result
    # signal_breakdown event çağrısını bul
    breakdown_calls = [
        c for c in mock_emit.call_args_list
        if c.args and c.args[1] == "signal_breakdown"
    ]
    assert len(breakdown_calls) == 1, "signal_breakdown event tam 1 kez emit edilmeli"


def test_signal_breakdown_metadata_structure(state_with_candidates):
    """Emit edilen metadata weights + top + candidate_count içermeli."""
    with patch("app.services.pipeline.observability.emit_event") as mock_emit:
        multi_signal_rank_node(state_with_candidates)

    breakdown_call = next(
        c for c in mock_emit.call_args_list
        if c.args and c.args[1] == "signal_breakdown"
    )
    meta = breakdown_call.kwargs.get("metadata") or {}
    assert "weights" in meta
    assert "top" in meta
    assert "candidate_count" in meta
    assert meta["candidate_count"] == 3
    assert len(meta["top"]) <= 3
    # Her top entry: schema, table, final_score, signals
    for entry in meta["top"]:
        assert "schema" in entry
        assert "table" in entry
        assert "final_score" in entry
        assert "signals" in entry
        # 7 sinyal hepsi mevcut
        assert "semantic_score" in entry["signals"]
        assert "glossary_match_score" in entry["signals"]


def test_signal_breakdown_node_name(state_with_candidates):
    """node_name 'multi_signal_rank' olmalı."""
    with patch("app.services.pipeline.observability.emit_event") as mock_emit:
        multi_signal_rank_node(state_with_candidates)

    breakdown_call = next(
        c for c in mock_emit.call_args_list
        if c.args and c.args[1] == "signal_breakdown"
    )
    assert breakdown_call.kwargs.get("node_name") == "multi_signal_rank"


def test_signal_breakdown_emit_failure_safe():
    """emit_event Exception fırlatırsa node yine de ranked_candidates dönmeli."""
    state = {
        "question": "test",
        "candidates": [{"schema_name": "s", "table_name": "t", "semantic_score": 0.5}],
    }
    with patch(
        "app.services.pipeline.observability.emit_event",
        side_effect=RuntimeError("DB down"),
    ):
        result = multi_signal_rank_node(state)
    assert "ranked_candidates" in result
    assert len(result["ranked_candidates"]) == 1


def test_signal_breakdown_empty_candidates():
    """Boş candidate listesinde event emit edilse de top boş kalmalı."""
    state = {"question": "test", "candidates": []}
    with patch("app.services.pipeline.observability.emit_event") as mock_emit:
        result = multi_signal_rank_node(state)

    assert result["ranked_candidates"] == []
    breakdown_calls = [
        c for c in mock_emit.call_args_list
        if c.args and c.args[1] == "signal_breakdown"
    ]
    # Boş candidates → event yine emit edilir ama top=[]
    assert len(breakdown_calls) == 1
    meta = breakdown_calls[0].kwargs.get("metadata") or {}
    assert meta["candidate_count"] == 0
    assert meta["top"] == []
