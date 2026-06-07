"""
metric_ambiguity_gate — TEMA-2 Dilim-2 (v3.79.0)
=================================================
Table-clarify ÇÖZÜLDÜKTEN sonra, sql_generate'ten ÖNCE metrik belirsizliğini gate'ler.
ambiguity_gate.py'nin metrik-eşi (aynı desen: detect → node → route).

GÜVENLİK (çalışanı bozma):
  - table de belirsizse (ambiguity.needs_clarification=True) metric-clarify ATLANIR →
    iki ardışık interrupt'tan kaçın (user_choice bayatlamaz, çalışan table-clarify'a 0 risk).
    O durumda metrik LLM-seçer (mevcut davranış, regresyon yok).
  - chosen_metric zaten set'liyse (resume sonrası) no-op (idempotent).
"""
from __future__ import annotations

from typing import Any, Dict

from app.services.pipeline.nodes.metric_ambiguity import detect_metric_ambiguity

# TEMA-2 Dilim-2 FEATURE FLAG — FE metrik-kart + re-send wiring (T6) tamamlanıp doğrulanana
# kadar OFF. OFF iken gate detect eder (gözlem/test) ama run_pipeline INTERRUPT ETMEZ →
# sql_generate'e düşer = MEVCUT davranış (LLM metrik seçer) → çalışan akışa SIFIR risk.
# T6 (FE) doğrulanınca True yapılır (tek satır, redeploy).
METRIC_CLARIFY_ENABLED = False


def metric_ambiguity_gate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — pure dict in/out."""
    # Resume sonrası metrik zaten seçilmiş → tekrar tespit etme
    if state.get("chosen_metric"):
        return {"metric_ambiguity": {"needs_clarification": False, "reason": "already_chosen"}}

    # GÜVENLİ guard: table belirsizdiyse iki-interrupt'tan kaçın (metrik LLM-seçer)
    amb = state.get("ambiguity") or {}
    if amb.get("needs_clarification"):
        return {"metric_ambiguity": {"needs_clarification": False, "reason": "table_clarify_active"}}

    selected = state.get("selected_tables") or state.get("ranked_candidates", [])[:3]
    decision = detect_metric_ambiguity(state.get("question", ""), selected)
    out: Dict[str, Any] = {"metric_ambiguity": decision}
    if decision["needs_clarification"]:
        out["clarification_payload"] = {
            "kind": "metric",
            "reason": decision["reason"],
            "candidates": decision["candidates"],
            "question": state.get("question", ""),
        }
    return out


def route_after_metric_ambiguity(state: Dict[str, Any]) -> str:
    """LangGraph conditional edge:
        - 'metric_clarification' → kullanıcıya metrik soracağız (interrupt)
        - 'sql_generate'         → otomatik devam (metrik net/dominant/atlandı)
    """
    m = state.get("metric_ambiguity") or {}
    return "metric_clarification" if m.get("needs_clarification") else "sql_generate"
