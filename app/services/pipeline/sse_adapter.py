"""
sse_adapter — Faz 3g
====================
Pipeline state'ini frontend'in beklediği SSE event şekline çevirir.

Frontend (dialog_chat.js:753) zaten `case 'clarification'` event'ini handle ediyor:
    eventData = { candidates, query, message }

Pipeline'ın `clarification_payload` çıktısı bu şekle map edilir.

Kullanım (gelecekteki API endpoint):
    if state.get("_interrupt"):
        for evt in stream_clarification_event(state):
            yield evt  # SSE format
"""
from __future__ import annotations

from typing import Any, Dict, Iterator
import json


REASON_MESSAGES = {
    "top1_top2_tight": "Birden fazla tablo eşit derecede uygun görünüyor. Hangisi olduğunu netleştirelim:",
    "below_threshold": "Sorunuza tam uyan bir tablo bulamadım. Aşağıdakilerden hangisini kullanmak istersiniz?",
    "no_candidates": "Sorunuza uygun bir kaynak bulamadım. Veri kaynağını ya da soruyu kontrol edin.",
}


def state_to_clarification_event(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pipeline state → frontend `clarification` SSE event payload.

    Returns:
        {
            "type": "clarification",
            "data": {
                "candidates": [{schema, table, business_name, score}, ...],
                "query": "...",
                "message": "..."
            }
        }
    """
    payload = state.get("clarification_payload") or {}
    reason = payload.get("reason") or "below_threshold"
    candidates = payload.get("candidates") or []

    # Frontend renderDisambiguationCard uyumlu şema
    formatted_candidates = []
    for c in candidates:
        sch = c.get("schema_name") or ""
        tbl = c.get("table_name") or ""
        full = f"{sch}.{tbl}" if sch and sch not in ("", "public") else tbl
        formatted_candidates.append({
            "schema": sch,
            "table": tbl,
            "full_name": full,
            "business_name": c.get("business_name_tr") or "",
            "score": float(c.get("final_score") or 0.0),
        })

    return {
        "type": "clarification",
        "data": {
            "candidates": formatted_candidates,
            "query": payload.get("question") or state.get("question") or "",
            "message": REASON_MESSAGES.get(reason, REASON_MESSAGES["below_threshold"]),
            "reason": reason,
            "confidence": payload.get("confidence", 0.0),
        },
    }


def format_sse(event: Dict[str, Any]) -> str:
    """Dict → SSE wire format ('data: {json}\\n\\n')."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def stream_clarification(state: Dict[str, Any]) -> Iterator[str]:
    """Kullanım kolaylığı için generator wrapper."""
    yield format_sse(state_to_clarification_event(state))
