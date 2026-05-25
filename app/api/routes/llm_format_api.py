"""VYRA v3.37.0 — LLM Format Suggest API (B8 / METIS-FORMAT).

Endpoint:
    POST /api/db/smart/llm/format-suggest

Step 4 (Önizleme) → "Hazır rapor formatı öner" butonu → LLM 3-5 hazır
rapor kartı (chart_type + title + group_by) önerir.

Auth: Depends(get_current_user) — Bearer token.
Service: app.services.llm_format_service.suggest_formats

NOT: Bu router app/api/main.py'a METIS-METRIC agent tarafından dahil
edilecektir (3 router tek seferde include). Bu dosya main.py'a DOKUNMAZ.

Owner: METIS-FORMAT
Brief: .agents/in_flight/2026-05-25_2242_v3370_llm_format_suggest.md
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.services.llm_format_service import suggest_formats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db/smart/llm", tags=["llm-smart-discovery"])


# ──────────────────────────────────────────────────────────────────
# Pydantic kontratları
# ──────────────────────────────────────────────────────────────────

class MetricInfo(BaseModel):
    """LLM format-suggest girişinde kullanılan metrik bilgisi."""
    metric_name: str = Field(..., description="Metrik adı, ör. 'Toplam Satış'")
    agg: Optional[str] = Field(default=None, description="Aggregation: SUM/AVG/COUNT...")
    formula: Optional[str] = Field(default=None, description="SQL formül, ör. SUM(tutar)")
    unit: Optional[str] = Field(default=None, description="Birim (TL, adet vb.)")

    class Config:
        extra = "allow"  # metric şeması ileride genişleyebilir


class FormatSuggestRequest(BaseModel):
    metric: MetricInfo
    columns: List[str] = Field(default_factory=list)
    user_intent: Optional[str] = None


class FormatCard(BaseModel):
    id: str
    title: str
    chart_type: str  # whitelist: line/bar/pie/table/kpi/area
    group_by: List[str] = Field(default_factory=list)
    order_by: List[str] = Field(default_factory=list)
    rationale: str = ""


class FormatSuggestResponse(BaseModel):
    format_cards: List[FormatCard]
    cache_hit: bool = False
    model: str = "unknown/unknown"


# ──────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────

@router.post(
    "/format-suggest",
    response_model=FormatSuggestResponse,
    summary="LLM rapor format galerisi — 3-5 hazır kart önerir",
)
def post_format_suggest(
    payload: FormatSuggestRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> FormatSuggestResponse:
    """Metrik + kolonlar + niyet bilgisinden LLM ile 3-5 rapor format kartı üret.

    Cache: TTL 900 sn (15 dk).
    """
    try:
        metric_dict = payload.metric.dict()
    except AttributeError:  # pragma: no cover - pydantic v2
        metric_dict = payload.metric.model_dump()

    try:
        result = suggest_formats(
            metric=metric_dict,
            columns=payload.columns or [],
            user_intent=payload.user_intent,
        )
    except Exception as exc:
        logger.exception("format-suggest service hatası")
        raise HTTPException(status_code=500, detail=f"LLM format suggest hatası: {exc}")

    return FormatSuggestResponse(
        format_cards=[FormatCard(**c) for c in result.get("format_cards", [])],
        cache_hit=bool(result.get("cache_hit", False)),
        model=str(result.get("model", "unknown/unknown")),
    )
