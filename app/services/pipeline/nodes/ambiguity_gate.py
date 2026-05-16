"""
ambiguity_gate — Faz 3c
=======================
Sıralanmış adayları inceler ve `clarification` gerekip gerekmediğine karar verir.

Master plan §3 (ARTEMIS-ML) heuristic:
    - Eğer top1 < 0.6 → clarification (below_threshold)
    - top1 - top2 < 0.20 → clarification (top1_top2_tight)
    - Aksi takdirde → auto-select (top1_dominant)

CatBoost-tabanlı detector Faz 5'te entegre edilir.

Çıktı şekli (`AmbiguityDecision`):
    {
        "needs_clarification": bool,
        "confidence": float,  # 1 - tightness gap veya top1 score
        "reason": "top1_dominant" | "top1_top2_tight" | "below_threshold" | "no_candidates",
        "candidates_for_user": [top-K aday]  # sadece clarification durumunda
    }

Routing yardımcısı `route_after_ambiguity()` LangGraph conditional edge için.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Master plan eşikleri — system_settings'ten override edilebilir
DEFAULT_TOP1_MIN = 0.6
DEFAULT_GAP_MIN = 0.20
DEFAULT_CLARIFY_TOP_K = 3


def detect_ambiguity(
    ranked_candidates: List[Dict[str, Any]],
    top1_min: float = DEFAULT_TOP1_MIN,
    gap_min: float = DEFAULT_GAP_MIN,
    top_k: int = DEFAULT_CLARIFY_TOP_K,
) -> Dict[str, Any]:
    """
    Heuristic ambiguity detector.

    Args:
        ranked_candidates: multi_signal_rank çıktısı (final_score DESC)
        top1_min: top1 final_score bu eşiğin altındaysa clarification
        gap_min: top1 - top2 farkı bu eşiğin altındaysa clarification
        top_k: clarification durumunda kullanıcıya gösterilecek aday sayısı

    Returns:
        AmbiguityDecision dict
    """
    if not ranked_candidates:
        return {
            "needs_clarification": False,
            "confidence": 0.0,
            "reason": "no_candidates",
            "candidates_for_user": [],
        }

    top1 = ranked_candidates[0]
    top1_score = float(top1.get("final_score") or 0.0)

    if len(ranked_candidates) == 1:
        # Tek aday: confidence = top1_score, threshold check
        if top1_score < top1_min:
            return {
                "needs_clarification": True,
                "confidence": top1_score,
                "reason": "below_threshold",
                "candidates_for_user": [top1],
            }
        return {
            "needs_clarification": False,
            "confidence": top1_score,
            "reason": "top1_dominant",
            "candidates_for_user": [],
        }

    top2 = ranked_candidates[1]
    top2_score = float(top2.get("final_score") or 0.0)
    gap = top1_score - top2_score

    # Eşikler — sıralı kontrol (öncelik: threshold > gap)
    if top1_score < top1_min:
        return {
            "needs_clarification": True,
            "confidence": top1_score,
            "reason": "below_threshold",
            "candidates_for_user": ranked_candidates[:top_k],
        }

    if gap < gap_min:
        return {
            "needs_clarification": True,
            "confidence": gap,  # küçük gap → düşük confidence
            "reason": "top1_top2_tight",
            "candidates_for_user": ranked_candidates[:top_k],
        }

    return {
        "needs_clarification": False,
        "confidence": top1_score,
        "reason": "top1_dominant",
        "candidates_for_user": [],
    }


def ambiguity_gate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — pure dict in/out."""
    ranked = state.get("ranked_candidates") or []
    settings = state.get("ambiguity_settings") or {}
    decision = detect_ambiguity(
        ranked,
        top1_min=settings.get("top1_min", DEFAULT_TOP1_MIN),
        gap_min=settings.get("gap_min", DEFAULT_GAP_MIN),
        top_k=settings.get("top_k", DEFAULT_CLARIFY_TOP_K),
    )
    out = {"ambiguity": decision}
    # Kullanıcıya gösterilecek payload (Faz 3g SSE event için hazır)
    if decision["needs_clarification"]:
        out["clarification_payload"] = {
            "reason": decision["reason"],
            "confidence": decision["confidence"],
            "candidates": decision["candidates_for_user"],
            "question": state.get("question", ""),
        }
    else:
        # Otomatik seçim — top1
        if ranked:
            out["selected_tables"] = [ranked[0]]
    return out


def route_after_ambiguity(state: Dict[str, Any]) -> str:
    """
    LangGraph conditional edge — sonraki node adını döndürür.
        - 'clarification' → kullanıcıya soracağız (interrupt)
        - 'sql_generate'  → otomatik devam
    """
    amb = state.get("ambiguity") or {}
    return "clarification" if amb.get("needs_clarification") else "sql_generate"
