"""
metric_clarification — TEMA-2 Dilim-2 (v3.79.0)
================================================
metric_ambiguity_gate `needs_clarification=True` → graph buraya yönlenir.
clarification.py'nin metrik-eşi (interrupt pattern aynı):
    1) Pre-interrupt: clarification_payload (kind:"metric") hazır; _interrupt set
    2) Post-resume: state.user_choice → state.chosen_metric

GÜVENLİK: yalnız METRİK anahtarı taşıyan user_choice'u tüketir (chosen_metric / metric_index);
tablo-seçimi anahtarı (selected_tables/selected_indices) görürse "henüz seçim yok" → interrupt.
Re-run non-determinism'e karşı: FE gerçek aday OBJESİNİ (chosen_metric) gönderir (index değil).
"""
from __future__ import annotations

from typing import Any, Dict


def _has_metric_choice(user_choice: Dict[str, Any]) -> bool:
    return bool(user_choice) and (
        user_choice.get("chosen_metric") is not None
        or user_choice.get("metric_index") is not None
    )


def metric_clarification_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-interrupt: payload finalize + _interrupt. Post-resume: user_choice -> chosen_metric."""
    user_choice = state.get("user_choice") or {}
    if _has_metric_choice(user_choice):
        candidates = (state.get("clarification_payload") or {}).get("candidates", [])
        chosen = user_choice.get("chosen_metric")
        if not chosen:
            mi = user_choice.get("metric_index")
            if isinstance(mi, int) and 0 <= mi < len(candidates):
                chosen = candidates[mi]
        if not chosen and candidates:
            chosen = candidates[0]  # fallback: top aday (kullanıcıyı boşa düşürme)
        return {"chosen_metric": chosen}

    # Pre-interrupt: payload metric_ambiguity_gate'te kind:"metric" ile hazırlandı.
    return {"_interrupt": True}
