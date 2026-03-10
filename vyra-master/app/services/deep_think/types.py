"""
VYRA Deep Think - Types Module
================================
Intent ve DeepThink veri sınıfları.
v2.30.1: circular import sorununu çözmek için ayrıştırıldı.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum


class IntentType(Enum):
    """Soru tipi kategorileri"""
    LIST_REQUEST = "list_request"      # "X nelerdir?", "Tüm Y'leri listele"
    SINGLE_ANSWER = "single_answer"    # "X ne işe yarar?", "Y nedir?"
    HOW_TO = "how_to"                  # "Nasıl yapılır?", "Adımlar neler?"
    COMPARISON = "comparison"          # "X ile Y arasındaki fark"
    TROUBLESHOOT = "troubleshoot"      # "Çalışmıyor", "Hata alıyorum"
    GENERAL = "general"                # Diğer


@dataclass
class IntentResult:
    """Intent analiz sonucu"""
    intent_type: IntentType
    confidence: float
    suggested_n_results: int
    keywords: List[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class DeepThinkResult:
    """Deep Think pipeline sonucu"""
    synthesized_response: str
    sources: List[str]
    intent: IntentResult
    rag_result_count: int
    processing_time_ms: float = 0.0
    best_score: float = 0.0  # 🆕 v2.49.0: En iyi RAG skoru
    image_ids: List[int] = field(default_factory=list)  # 🆕 v2.37.0: İlgili chunk görsel ID'leri
    heading_images: Dict[str, List[int]] = field(default_factory=dict)  # 🆕 v2.37.1: Heading → image_ids mapping
