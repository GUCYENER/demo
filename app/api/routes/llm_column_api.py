"""VYRA v3.37.0 — LLM Column Suggest API (B5b).

Endpoint:
    POST /api/db/smart/llm/column-suggest

Step 3 (Filtre/Kolon) — seçili metrik için anlamlı kolonları LLM öner.
2 kategori:
    1) metric_bound        — metriğe direkt katkı veren kolonlar
    2) related_dimensions  — boyut/grup kırılımı için anlamlı kolonlar

Auth: Bearer JWT (get_current_user).
Cache: Redis TTL 15dk (llm_column_service içinde).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from app.api.routes.auth import get_current_user
from app.services import llm_column_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db/smart/llm", tags=["llm-smart-discovery"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────

class MetricInfo(BaseModel):
    metric_name: str = Field(..., min_length=1, max_length=200)
    agg: Optional[str] = Field(default=None, max_length=40)
    formula: Optional[str] = Field(default=None, max_length=2000)


class ColumnInfo(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    type: Optional[str] = Field(default=None, max_length=64)


class ColumnSuggestRequest(BaseModel):
    source_id: int = Field(..., ge=1)
    table: str = Field(..., min_length=1, max_length=128)
    metric: MetricInfo
    available_columns: List[ColumnInfo] = Field(..., min_items=1, max_items=200)

    @validator("available_columns")
    def _unique_columns(cls, v: List[ColumnInfo]) -> List[ColumnInfo]:
        seen = set()
        for c in v:
            if c.name in seen:
                raise ValueError(f"Tekrar eden kolon adı: {c.name}")
            seen.add(c.name)
        return v


class SuggestedColumn(BaseModel):
    column: str
    rationale: str = ""
    confidence: float = 0.0
    suggested_grain: Optional[str] = None


class ColumnSuggestResponse(BaseModel):
    metric_bound: List[SuggestedColumn]
    related_dimensions: List[SuggestedColumn]
    cache_hit: bool
    model: str


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _require_user_id(current_user: Dict[str, Any]) -> int:
    uid = current_user.get("id") if current_user else None
    if uid is None:
        raise HTTPException(status_code=401, detail="Kullanıcı kimliği belirlenemedi.")
    return int(uid)


# ─────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────

@router.post("/column-suggest", response_model=ColumnSuggestResponse)
def column_suggest(
    body: ColumnSuggestRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ColumnSuggestResponse:
    """Metrik bazlı kolon önerisi (2 kategori)."""
    _require_user_id(current_user)

    try:
        result = llm_column_service.suggest_columns(
            source_id=body.source_id,
            table=body.table,
            metric=body.metric.dict(),
            columns=[c.dict() for c in body.available_columns],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[llm_column_api] suggest_columns failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"LLM kolon önerisi alınamadı: {e}",
        )

    return ColumnSuggestResponse(
        metric_bound=[SuggestedColumn(**x) for x in result.get("metric_bound", [])],
        related_dimensions=[SuggestedColumn(**x) for x in result.get("related_dimensions", [])],
        cache_hit=bool(result.get("cache_hit", False)),
        model=str(result.get("model", "unknown")),
    )
