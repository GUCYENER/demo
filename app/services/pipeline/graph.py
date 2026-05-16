"""
LangGraph state machine for the agentic SQL pipeline (Faz 3f).

LangGraph kurulu ise compiled StateGraph döner.
Yoksa: pure-Python sequential runner fallback'i devreye girer (test ve
       dev'de bağımlılıksız çalışmaya devam eder).

Graph şeması:

    intent_extract
        ↓
    query_expand
        ↓
    retrieve
        ↓
    multi_signal_rank
        ↓
    ambiguity_gate ──► (cond)
        │              │
        │ (clarify)    │ (auto)
        ▼              │
    clarification      │
        │ (interrupt)  │
        ▼              │
    [resume]           │
        └──────┬───────┘
               ▼
        sql_generate
               ↓
        validate ──► (cond)
               │       │
               │       └─► sql_generate (self-heal, max 2)
               ▼
            execute
               ↓
            [END]

Kullanım (LangGraph yokken):
    from app.services.pipeline.graph import run_pipeline
    final_state = run_pipeline(initial_state, mode="sync")
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from .state import QueryState  # noqa: F401  (re-export için)
from .nodes import (
    intent_extract_node,
    query_expand_node,
    retrieve_node,
    multi_signal_rank_node,
    ambiguity_gate_node,
    route_after_ambiguity,
    clarification_node,
    sql_generate_node,
    validate_node,
    route_after_validate,
    execute_node,
    self_heal_node,
    route_after_self_heal,
)

logger = logging.getLogger(__name__)

# LangGraph opsiyonel import
try:
    from langgraph.graph import StateGraph, START, END  # type: ignore
    _HAS_LANGGRAPH = True
except Exception:
    _HAS_LANGGRAPH = False
    logger.info("[Pipeline] LangGraph yuklu degil — sequential fallback kullanilacak")


def build_query_graph(checkpointer=None):
    """LangGraph compiled state graph. Sadece langgraph kuruluysa çalışır."""
    if not _HAS_LANGGRAPH:
        raise NotImplementedError(
            "LangGraph yuklu degil. `pip install langgraph` veya "
            "run_pipeline(state) sequential fallback'ini kullanin."
        )

    g = StateGraph(dict)  # State tipi dict (TypedDict QueryState)
    g.add_node("intent_extract", intent_extract_node)
    g.add_node("query_expand", query_expand_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("multi_signal_rank", multi_signal_rank_node)
    g.add_node("ambiguity_gate", ambiguity_gate_node)
    g.add_node("clarification", clarification_node)
    g.add_node("sql_generate", sql_generate_node)
    g.add_node("validate", validate_node)
    g.add_node("self_heal", self_heal_node)
    g.add_node("execute", execute_node)

    g.add_edge(START, "intent_extract")
    g.add_edge("intent_extract", "query_expand")
    g.add_edge("query_expand", "retrieve")
    g.add_edge("retrieve", "multi_signal_rank")
    g.add_edge("multi_signal_rank", "ambiguity_gate")

    # Conditional: ambiguity_gate -> clarification | sql_generate
    g.add_conditional_edges("ambiguity_gate", route_after_ambiguity, {
        "clarification": "clarification",
        "sql_generate": "sql_generate",
    })
    g.add_edge("clarification", "sql_generate")

    g.add_edge("sql_generate", "validate")

    # Conditional: validate -> execute | self_heal (Faz 4d)
    g.add_conditional_edges("validate", route_after_validate, {
        "execute": "execute",
        "sql_generate": "self_heal",  # validate fail → self_heal classifies & re-routes
    })
    # self_heal -> sql_generate (rewrite) | execute (give up) | END (abort)
    g.add_conditional_edges("self_heal", route_after_self_heal, {
        "sql_generate": "sql_generate",
        "execute": "execute",
        "abort": END,
    })
    g.add_edge("execute", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


# ---------------------------------------------------------------------------
# Sequential fallback runner — LangGraph YOKKEN devreye girer
# ---------------------------------------------------------------------------

def run_pipeline(state: Dict[str, Any], mode: str = "auto") -> Dict[str, Any]:
    """
    Pure-Python sequential pipeline.

    Mode:
        "auto"   → ambiguity'de clarification'a girer, _interrupt bayrağı set olur
                   ve return edilir (caller resume etmeli)
        "force"  → clarification olsa bile top1 ile devam et (test/CI)
        "sync"   → "auto" ile aynı (geriye uyumlu)

    Returns: final state dict
    """
    def _merge(s: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
        if not delta:
            return s
        out = dict(s)
        for k, v in delta.items():
            # Special merge: errors listesi append
            if k == "errors" and isinstance(out.get("errors"), list) and isinstance(v, list):
                out["errors"] = out["errors"] + [e for e in v if e not in out["errors"]]
            else:
                out[k] = v
        return out

    state = _merge(state, intent_extract_node(state))
    state = _merge(state, query_expand_node(state))
    state = _merge(state, retrieve_node(state))
    state = _merge(state, multi_signal_rank_node(state))
    state = _merge(state, ambiguity_gate_node(state))

    # Ambiguity routing
    route = route_after_ambiguity(state)
    if route == "clarification":
        state = _merge(state, clarification_node(state))
        if mode == "force" or state.get("user_choice"):
            # force veya zaten kullanıcı seçimi var → devam et
            if not state.get("selected_tables"):
                # user_choice yoksa top1 al
                ranked = state.get("ranked_candidates") or []
                if ranked:
                    state["selected_tables"] = [ranked[0]]
        else:
            # Interrupt — caller SSE event göndermeli ve resume etmeli
            state["_interrupt"] = True
            return state

    # SQL generate + validate + self-heal loop (Faz 4d)
    max_retries = 2
    for attempt in range(max_retries + 1):
        state = _merge(state, sql_generate_node(state))
        state = _merge(state, validate_node(state))
        if state.get("validation_passed"):
            break
        if attempt == max_retries:
            break
        # Self-heal: classify error & decide
        state = _merge(state, self_heal_node(state))
        action = state.get("retry_action")
        if action == "abort":
            # Permission error vs. — execute etmeden döndür
            return state
        if action != "rewrite":
            break
        # retry_count self_heal'de zaten artırıldı

    state = _merge(state, execute_node(state))
    return state


def resume_pipeline(state: Dict[str, Any], user_choice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interrupted state'i kullanıcı seçimi ile sürdür.

    user_choice: {"selected_indices": [0]} veya {"selected_tables": [...]}
    """
    state = dict(state)
    state["user_choice"] = user_choice
    state.pop("_interrupt", None)

    # clarification_node post-resume yolunu çalıştır
    state.update(clarification_node(state))

    # SQL üretim ve sonrası (self-heal aware)
    max_retries = 2
    for attempt in range(max_retries + 1):
        state.update(sql_generate_node(state))
        state.update(validate_node(state))
        if state.get("validation_passed"):
            break
        if attempt == max_retries:
            break
        state.update(self_heal_node(state))
        action = state.get("retry_action")
        if action == "abort":
            return state
        if action != "rewrite":
            break
    state.update(execute_node(state))
    return state
