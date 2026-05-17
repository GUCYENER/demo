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
    load_prefs_node,
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
from .observability import (
    ensure_run_id, instrument_node, pipeline_start, pipeline_end, emit_event,
)
from .result_size_predictor import predict_size_node

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
    # Tüm node'lar instrument_node ile sarmalanır — sequential ve LangGraph
    # yollarında aynı pipeline_events çıktısı üretilir. Aksi takdirde prod'da
    # LangGraph aktifken observability sessizce devre dışı kalıyordu.
    g.add_node("load_prefs", instrument_node("load_prefs", load_prefs_node))
    g.add_node("intent_extract", instrument_node("intent_extract", intent_extract_node))
    g.add_node("query_expand", instrument_node("query_expand", query_expand_node))
    g.add_node("retrieve", instrument_node("retrieve", retrieve_node))
    g.add_node("multi_signal_rank", instrument_node("multi_signal_rank", multi_signal_rank_node))
    g.add_node("ambiguity_gate", instrument_node("ambiguity_gate", ambiguity_gate_node))
    g.add_node("clarification", instrument_node("clarification", clarification_node))
    g.add_node("sql_generate", instrument_node("sql_generate", sql_generate_node))
    g.add_node("validate", instrument_node("validate", validate_node))
    g.add_node("self_heal", instrument_node("self_heal", self_heal_node))
    g.add_node("predict_size", instrument_node("predict_size", predict_size_node))
    g.add_node("execute", instrument_node("execute", execute_node))

    g.add_edge(START, "load_prefs")
    g.add_edge("load_prefs", "intent_extract")
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
    # predict_size her execute öncesinde state.result_size_prediction üretir.
    # validate -> execute geçişinde önce predict_size çalışır.
    # (Sequential runner aynı sıralamayı manuel uygular.)
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

    import time as _t
    _started = _t.perf_counter()
    ensure_run_id(state)
    pipeline_start(state, mode=mode)

    state = _merge(state, instrument_node("load_prefs", load_prefs_node)(state))
    state = _merge(state, instrument_node("intent_extract", intent_extract_node)(state))
    state = _merge(state, instrument_node("query_expand", query_expand_node)(state))
    state = _merge(state, instrument_node("retrieve", retrieve_node)(state))
    state = _merge(state, instrument_node("multi_signal_rank", multi_signal_rank_node)(state))
    state = _merge(state, instrument_node("ambiguity_gate", ambiguity_gate_node)(state))

    # Ambiguity routing
    route = route_after_ambiguity(state)
    if route == "clarification":
        state = _merge(state, instrument_node("clarification", clarification_node)(state))
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
            emit_event(state, "interrupt", metadata={"reason": (state.get("clarification_payload") or {}).get("reason")})
            pipeline_end(state, int((_t.perf_counter() - _started) * 1000))
            return state

    # SQL generate + validate + self-heal loop (Faz 4d)
    max_retries = 2
    for attempt in range(max_retries + 1):
        state = _merge(state, instrument_node("sql_generate", sql_generate_node)(state))
        state = _merge(state, instrument_node("validate", validate_node)(state))
        if state.get("validation_passed"):
            break
        if attempt == max_retries:
            break
        # Self-heal: classify error & decide
        state = _merge(state, instrument_node("self_heal", self_heal_node)(state))
        action = state.get("retry_action")
        if action == "abort":
            # Permission error vs. — execute etmeden döndür
            pipeline_end(state, int((_t.perf_counter() - _started) * 1000))
            return state
        if action != "rewrite":
            break
        # retry_count self_heal'de zaten artırıldı

    # Faz 6a — sonuç boyut tahmini (execute öncesi)
    state = _merge(state, instrument_node("predict_size", predict_size_node)(state))

    state = _merge(state, instrument_node("execute", execute_node)(state))

    # Faz 5a — feedback satırlarını agentic_query_feedback'e yaz (best-effort)
    _persist_feedback_if_possible(state)

    pipeline_end(state, int((_t.perf_counter() - _started) * 1000))
    return state


def _persist_feedback_if_possible(state: Dict[str, Any]) -> None:
    """Pipeline sonunda feedback rows yazımı (training data). Sessizce başarısız."""
    cur = state.get("_cursor")
    if cur is None or not state.get("company_id"):
        return
    try:
        from app.services.ml.feature_extractor import collect_feedback_rows, persist_feedback
        rows = collect_feedback_rows(state)
        if rows:
            persist_feedback(cur, rows)
    except Exception:
        pass


def resume_pipeline(state: Dict[str, Any], user_choice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Interrupted state'i kullanıcı seçimi ile sürdür.

    user_choice: {"selected_indices": [0]} veya {"selected_tables": [...]}
    """
    import time as _t
    _started = _t.perf_counter()
    state = dict(state)
    state["user_choice"] = user_choice
    state.pop("_interrupt", None)
    ensure_run_id(state)
    emit_event(state, "resume", metadata={"selected": user_choice})

    # clarification_node post-resume yolunu çalıştır
    state.update(instrument_node("clarification", clarification_node)(state))

    # SQL üretim ve sonrası (self-heal aware)
    max_retries = 2
    for attempt in range(max_retries + 1):
        state.update(instrument_node("sql_generate", sql_generate_node)(state))
        state.update(instrument_node("validate", validate_node)(state))
        if state.get("validation_passed"):
            break
        if attempt == max_retries:
            break
        state.update(instrument_node("self_heal", self_heal_node)(state))
        action = state.get("retry_action")
        if action == "abort":
            pipeline_end(state, int((_t.perf_counter() - _started) * 1000))
            return state
        if action != "rewrite":
            break

    state.update(instrument_node("predict_size", predict_size_node)(state))
    state.update(instrument_node("execute", execute_node)(state))

    # Faz 5a — feedback rows
    _persist_feedback_if_possible(state)

    pipeline_end(state, int((_t.perf_counter() - _started) * 1000))
    return state
