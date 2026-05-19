"""
clarification — Faz 3e
======================
Ambiguity_gate `needs_clarification=True` döndüğünde graph buraya yönlenir.

LangGraph interrupt pattern:
    - Bu node bir 'interrupt' noktasıdır — graph state'i checkpointer'a yazılır
    - SSE event `clarification_needed` (Faz 3g) ile UI'a payload gönderilir
    - Kullanıcı seçim yapınca `resume` API'siyle graph devam eder
    - `user_choice` state alanı doldurulur → graph sql_generate'e devam eder

Bu modül runtime'da iki rolde çalışır:
    1) Pre-interrupt: clarification_payload'u UI için son haline getir
    2) Post-resume: state.user_choice → state.selected_tables map'le
"""
from __future__ import annotations

from typing import Any, Dict


def clarification_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pre-interrupt: clarification_payload'u SSE event için son haline getir.
    Post-resume: user_choice -> selected_tables.
    """
    # Post-resume yolu: user_choice doldurulmuşsa map'le
    user_choice = state.get("user_choice")
    if user_choice:
        # user_choice: {"selected_indices": [0], "selected_tables": [...]}
        if user_choice.get("selected_tables"):
            return {"selected_tables": user_choice["selected_tables"]}
        idx = user_choice.get("selected_indices") or []
        candidates = (state.get("clarification_payload") or {}).get("candidates", [])
        chosen = [candidates[i] for i in idx if 0 <= i < len(candidates)]
        if chosen:
            return {"selected_tables": chosen}
        # Hiçbiri seçilmediyse top1'i otomatik al
        if candidates:
            return {"selected_tables": [candidates[0]]}
        return {"selected_tables": []}

    # Pre-interrupt: payload'u zenginleştir (Faz 3g SSE event burada hazırlanır)
    payload = state.get("clarification_payload") or {}
    # UI'ın beklediği şekle hafifçe normalize et
    candidates_norm = []
    for c in payload.get("candidates", []):
        candidates_norm.append({
            "schema_name": c.get("schema_name") or "",
            "table_name": c.get("table_name") or "",
            "business_name_tr": c.get("business_name_tr") or "",
            "final_score": float(c.get("final_score") or 0.0),
            "semantic_score": float(c.get("semantic_score") or 0.0),
        })
    payload_out = dict(payload)
    payload_out["candidates"] = candidates_norm
    return {"clarification_payload": payload_out, "_interrupt": True}
