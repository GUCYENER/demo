"""state_machine.py smoke tests (FAZ 0 — gerçek logic FAZ 1'de)."""
from __future__ import annotations

import pytest

from app.services.db_smart.state_machine import (
    WIZARD_NODES,
    WIZARD_NODE_LABELS_TR,
    build_wizard_graph,
    run_wizard_step,
)


def test_wizard_nodes_have_9_steps():
    assert len(WIZARD_NODES) == 9
    assert WIZARD_NODES[0] == "init"
    assert WIZARD_NODES[-1] == "execute_recommend"


def test_all_nodes_have_tr_label():
    missing = [n for n in WIZARD_NODES if n not in WIZARD_NODE_LABELS_TR]
    assert not missing, f"TR label eksik: {missing}"


def test_build_wizard_graph_returns_object():
    g = build_wizard_graph()
    assert g is not None
    # invoke arayüzü hem LangGraph hem fallback runner için var olmalı
    assert hasattr(g, "invoke")


def test_sequential_runner_visits_all_nodes(monkeypatch):
    # LangGraph yokmuş gibi davran
    monkeypatch.setattr("app.services.db_smart.state_machine._HAS_LANGGRAPH", False)
    g = build_wizard_graph()
    out = g.invoke({"source_id": 1})
    assert out["_last_node"] == "execute_recommend"
    assert out["_visited"] == list(WIZARD_NODES)


@pytest.mark.parametrize("step,expected_node", [
    (0, "init"),
    (1, "domain_select"),
    (5, "metric_choose"),
    (8, "execute_recommend"),
])
def test_run_wizard_step_returns_correct_node(step, expected_node, fake_user_ctx):
    result = run_wizard_step("test-uid", step, payload={}, user_ctx=fake_user_ctx)
    assert result["node"] == expected_node
    assert result["current_step"] == step


def test_run_wizard_step_invalid_step(fake_user_ctx):
    result = run_wizard_step("test-uid", 99, payload={}, user_ctx=fake_user_ctx)
    assert result["status"] == "invalid_step"
    assert result["node"] is None


def test_run_wizard_step_last_step_is_completed(fake_user_ctx):
    result = run_wizard_step("test-uid", 8, payload={}, user_ctx=fake_user_ctx)
    assert result["next_step"] is None
    assert result["status"] == "completed"
