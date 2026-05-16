"""
intent_extract — Faz 3e
=======================
Sorgu niyetini sınıflandırır: lookup / aggregate / report / follow_up / unknown.

Şu an heuristic (keyword-based). Faz 5'te CatBoost-tabanlı sınıflayıcı.
LLM'e gitmeden ucuz bir prefiltre — pipeline'ı dallandırır:
    - follow_up → history bağlamı önemli
    - aggregate → GROUP BY ipucu sql_generate'e
"""
from __future__ import annotations

from typing import Any, Dict
import re

_AGG_WORDS = (
    "topla", "toplam", "sum", "say", "kac", "kaç", "count", "ortalama", "avg",
    "ort", "max", "min", "en yuksek", "en duşuk", "en cok", "en az",
)
_REPORT_WORDS = ("rapor", "report", "ozet", "özet", "dashboard", "grafik")
_FOLLOWUP_WORDS = (
    "bunlar", "bunu", "sunu", "şunu", "onun", "bunlardan",
    "ekle", "filtrele", "sirala", "sıralama", "ayrica", "ayrıca",
    "yukaridakiler", "yukarıdakiler", "ustteki", "üstteki",
)
_LOOKUP_WORDS = ("listele", "goster", "göster", "bul", "ara", "getir")


def _normalize(text: str) -> str:
    text = (text or "").lower()
    # TR diakritik basitleştirme
    return text.replace("ı", "i").replace("ş", "s").replace("ğ", "g") \
               .replace("ü", "u").replace("ö", "o").replace("ç", "c")


def detect_intent(question: str, has_history: bool = False) -> Dict[str, Any]:
    """Heuristic intent + confidence."""
    if not question:
        return {"intent": "unknown", "intent_confidence": 0.0}

    q = _normalize(question)
    scores = {"lookup": 0.0, "aggregate": 0.0, "report": 0.0, "follow_up": 0.0}

    for w in _AGG_WORDS:
        if w in q:
            scores["aggregate"] += 1
    for w in _REPORT_WORDS:
        if w in q:
            scores["report"] += 1
    for w in _FOLLOWUP_WORDS:
        if w in q:
            scores["follow_up"] += 1
    for w in _LOOKUP_WORDS:
        if w in q:
            scores["lookup"] += 1

    # History bağlamı varsa follow_up'a hafif ağırlık
    if has_history:
        scores["follow_up"] += 0.5

    # Hiç sinyal yoksa → lookup default (TR "X listesi" gibi tipik)
    if max(scores.values()) == 0:
        return {"intent": "lookup", "intent_confidence": 0.4}

    best = max(scores.items(), key=lambda kv: kv[1])
    total = sum(scores.values()) or 1.0
    return {"intent": best[0], "intent_confidence": float(best[1] / total)}


def intent_extract_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — intent + confidence ekler."""
    has_history = bool(state.get("history"))
    return detect_intent(state.get("question", ""), has_history=has_history)
