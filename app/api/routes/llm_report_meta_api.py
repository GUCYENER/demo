"""VYRA v3.37.4 — LLM Report Meta Oneri API.

Endpoint: POST /api/db-smart/llm/report-meta-suggest
Save modal'da kullanilan baslik+aciklama icin LLM onerisi.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api._llm_error_handling import handle_llm_errors
from app.api.routes.auth import get_current_user
from app.core.rate_limiter import limiter
from app.services.llm_report_meta_service import suggest_report_meta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db-smart/llm", tags=["llm-smart-discovery"])


class ReportMetaSuggestRequest(BaseModel):
    table_label: Optional[str] = Field(default=None, max_length=200)
    metric_names: List[str] = Field(default_factory=list, max_length=20)
    columns: List[str] = Field(default_factory=list, max_length=50)
    filters_count: int = Field(default=0, ge=0, le=200)
    user_intent: Optional[str] = Field(default=None, max_length=500)


class ReportMetaSuggestResponse(BaseModel):
    title: str
    description: str = ""
    cache_hit: bool = False
    model: str = "unknown"


@router.post("/report-meta-suggest", response_model=ReportMetaSuggestResponse)
@limiter.limit("15/minute")
@handle_llm_errors(logger)
def post_report_meta_suggest(
    request: Request,
    response: Response,
    body: ReportMetaSuggestRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ReportMetaSuggestResponse:
    if not current_user.get("id"):
        raise HTTPException(status_code=401, detail="Kullanici kimligi belirlenemedi.")
    result = suggest_report_meta(
        table_label=body.table_label,
        metric_names=body.metric_names or [],
        columns=body.columns or [],
        filters_count=int(body.filters_count or 0),
        user_intent=body.user_intent,
    )
    return ReportMetaSuggestResponse(
        title=str(result.get("title") or ""),
        description=str(result.get("description") or ""),
        cache_hit=bool(result.get("cache_hit", False)),
        model=str(result.get("model") or "unknown"),
    )
