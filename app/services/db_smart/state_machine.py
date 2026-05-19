"""DB Smart Wizard — 9-node LangGraph state machine (v3.30.0 FAZ 0).

Adımlar (Prompt D — db_smart_prompts.md):
    0. init            — oturum açılır, source seçimi alınır, RLS context set edilir
    1. domain_select   — kullanıcı doğal dilde domain arar, top-K tablo önerilir
    2. tables_select   — multi-select + FK genişletme + junction tespiti
    3. date_select     — tarih kolonu seçimi + aralık (preset/custom)
    4. filter_apply    — chip-style filter + ds_code_values dropdown
    5. metric_choose   — eligible metric listesi + bandit exploration + custom
    6. output_define   — kolon seçimi + sıralama + LIMIT
    7. preview_refine  — SQL render + EXPLAIN + drag-drop AST manipulation
    8. execute_recommend — sonuç + insight + viz öneri + save/share

Conditional edges:
    ambiguity      → clarification modal
    permission_denied → fallback (read-only metadata)
    empty_result   → recovery suggestion
    timeout        → cancel
    back_nav       → her node'dan önceki node'a sorunsuz dönüş

Bu modül FAZ 0'da yalnızca **iskelet**tir: tüm node fonksiyonları stub döner
ve `run_wizard_step` 501 davranışı simüle eder (gerçek implementasyon FAZ 1).
LangGraph kuruluysa compile edilir; değilse sequential fallback runner kullanılır
(mevcut [app/services/pipeline/graph.py:74](../pipeline/graph.py) pattern'i).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import StateGraph, START, END  # type: ignore
    _HAS_LANGGRAPH = True
except Exception:
    _HAS_LANGGRAPH = False
    logger.info("[db_smart] LangGraph yuklu degil — sequential fallback aktif")


# ---------------------------------------------------------------------------
# Node sırası (immutable kontrat — UI stepper bu sırayla render eder)
# ---------------------------------------------------------------------------
WIZARD_NODES: Tuple[str, ...] = (
    "init",
    "domain_select",
    "tables_select",
    "date_select",
    "filter_apply",
    "metric_choose",
    "output_define",
    "preview_refine",
    "execute_recommend",
)

# Her node için kullanıcıya gösterilecek başlık (UI için)
WIZARD_NODE_LABELS_TR: Dict[str, str] = {
    "init":              "Başla",
    "domain_select":     "Konu / Domain",
    "tables_select":     "Tablolar",
    "date_select":       "Tarih",
    "filter_apply":      "Filtre",
    "metric_choose":     "Metrik",
    "output_define":     "Çıktı",
    "preview_refine":    "Önizleme",
    "execute_recommend": "Çalıştır & Öneri",
}


# ---------------------------------------------------------------------------
# Stub node implementasyonları — FAZ 0 (gerçek mantık FAZ 1 G1.1+)
# ---------------------------------------------------------------------------
def _stub_node(name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Generate a no-op node that records its visit and passes state through."""

    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        visited: List[str] = list(state.get("_visited", []))
        visited.append(name)
        return {**state, "_visited": visited, "_last_node": name}

    _node.__name__ = f"node_{name}"
    return _node


# Bütün node'lar şimdilik aynı stub — FAZ 1'de teker teker gerçeklenir
_NODE_IMPLS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    name: _stub_node(name) for name in WIZARD_NODES
}


# ---------------------------------------------------------------------------
# Conditional edge router'ları (FAZ 0 stub — gerçek mantık FAZ 1)
# ---------------------------------------------------------------------------
def _route_after_domain(state: Dict[str, Any]) -> str:
    """domain_select sonrası: ambiguity varsa clarification, yoksa tables."""
    if state.get("ambiguity"):
        return "clarification"
    return "tables_select"


def _route_after_preview(state: Dict[str, Any]) -> str:
    """preview_refine sonrası: cost > threshold ise uyarı, yoksa execute."""
    if state.get("explain_cost_warn"):
        return "preview_refine"  # kullanıcı onayı için aynı node'da kal
    return "execute_recommend"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def build_wizard_graph(checkpointer: Any = None) -> Any:
    """Compile and return LangGraph state machine.

    Args:
        checkpointer: optional LangGraph checkpointer for persistence
            (FAZ 1'de Redis L1 + dbsmart_sessions üzerinden hookalanacak).

    Returns:
        Compiled graph (LangGraph) ya da `_SequentialRunner` (fallback).
    """
    if not _HAS_LANGGRAPH:
        return _SequentialRunner(WIZARD_NODES, _NODE_IMPLS)

    g = StateGraph(dict)
    for name, fn in _NODE_IMPLS.items():
        g.add_node(name, fn)

    # Linear backbone (init → ... → execute_recommend → END)
    g.add_edge(START, "init")
    g.add_edge("init", "domain_select")

    # domain_select'ten sonra opsiyonel clarification yan dalı
    # FAZ 0'da 'clarification' fiziksel olarak ayrı node değil — ileride eklenecek
    # G0.3 itibariyle conditional edge stub'ı testte koşturulabilir.
    g.add_conditional_edges("domain_select", _route_after_domain, {
        "clarification": "tables_select",  # FAZ 0: clarification yok, doğrudan
        "tables_select": "tables_select",
    })
    g.add_edge("tables_select", "date_select")
    g.add_edge("date_select", "filter_apply")
    g.add_edge("filter_apply", "metric_choose")
    g.add_edge("metric_choose", "output_define")
    g.add_edge("output_define", "preview_refine")
    g.add_conditional_edges("preview_refine", _route_after_preview, {
        "execute_recommend": "execute_recommend",
        "preview_refine": "preview_refine",  # uyarı sonrası kullanıcı tekrar düzenler
    })
    g.add_edge("execute_recommend", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


class _SequentialRunner:
    """Minimal sequential fallback (LangGraph YOKKEN devreye girer).

    LangGraph compile'a verilen graf'ın `invoke(state)` arayüzünü taklit eder.
    Conditional edge'leri linearize eder (en güvenli yol).
    """

    def __init__(self, nodes: Tuple[str, ...], impls: Dict[str, Callable]):
        self._nodes = nodes
        self._impls = impls

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        st = dict(state)
        for name in self._nodes:
            st = self._impls[name](st)
        return st


# ---------------------------------------------------------------------------
# Public dispatcher (FAZ 0: 501-vari stub; FAZ 1'de session_manager + node call)
# ---------------------------------------------------------------------------
def run_wizard_step(
    session_uid: str,
    step: int,
    payload: Optional[Dict[str, Any]] = None,
    user_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tek bir wizard adımını çalıştır ve durumu güncelle.

    FAZ 0 davranışı:
        Yalnızca node adını ve next_step önerisini döner; veritabanı yazımı,
        eligibility/metric çağrıları FAZ 1'de eklenir.

    Returns:
        {
            "session_uid": str,
            "current_step": int,
            "next_step": int | None,
            "node": str,
            "result": dict,   # FAZ 0'da boş
            "status": "stub" | "ok" | "ambiguity" | "completed",
        }
    """
    if step < 0 or step >= len(WIZARD_NODES):
        return {
            "session_uid": session_uid,
            "current_step": step,
            "next_step": None,
            "node": None,
            "result": {},
            "status": "invalid_step",
        }

    node = WIZARD_NODES[step]
    next_step = step + 1 if step + 1 < len(WIZARD_NODES) else None
    status = "stub" if step + 1 < len(WIZARD_NODES) else "completed"

    logger.info(
        "[db_smart] step %s node=%s session=%s payload_keys=%s",
        step, node, session_uid, list((payload or {}).keys()),
    )

    return {
        "session_uid": session_uid,
        "current_step": step,
        "next_step": next_step,
        "node": node,
        "node_label_tr": WIZARD_NODE_LABELS_TR.get(node),
        "result": {},
        "status": status,
    }
