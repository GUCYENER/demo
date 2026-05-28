"""VYRA v3.37.0 — LLM Metrik Oneri API (METIS).

Endpoint:
    POST /api/db/smart/llm/metric-suggest

Smart Discovery Wizard Step 2 (Metrik) icin dinamik metrik onerisi.
Statik metric_library yerine LLM ile tabloya/kolonlara ozel oneriler.

Auth: Depends(get_current_user) — Bearer token (mevcut db_smart pattern).
Service: app.services.llm_metric_service.suggest_metrics
Cache: Redis L1, TTL 15 dk (servis tarafinda).
Rate limit: slowapi `limiter` decorator (10/dakika per IP).

Hata akisi:
    - LLMConnectionError / LLMConfigError -> 503
    - LLMResponseError -> 502
    - Bos columns -> 400
    - Auth eksik -> 401
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.llm import LLMConfigError, LLMConnectionError, LLMResponseError
from app.core.rate_limiter import limiter
from app.services.llm_metric_service import suggest_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db-smart/llm", tags=["llm-smart-discovery"])


# -------------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------------

class ColumnInfo(BaseModel):
    """Kolon meta — name + type."""
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., min_length=1, max_length=60)


class MetricSuggestRequest(BaseModel):
    source_id: int = Field(..., ge=1)
    table: str = Field(..., min_length=1, max_length=200)
    # Bulgular3 / Bulgu 4: TR'de öğrenilmiş tablo adı. LLM rationale ve metric_name
    # için bu adı kullanır; frontend chip'inde TR ad gösterilir, SQL identifier
    # tooltip'te kalır. None ise eski davranış (table SQL adıyla render).
    table_label: Optional[str] = Field(default=None, max_length=200)
    columns: List[ColumnInfo] = Field(default_factory=list, max_length=50)
    user_intent: Optional[str] = Field(default=None, max_length=500)


class MetricSuggestionItem(BaseModel):
    metric_name: str
    agg: str
    formula: str
    rationale: str = ""
    confidence: float = 0.5
    # Bulgular3 / Bulgu 4: frontend "Table:" üstüne TR ad, tooltip'e orijinal.
    table_name_tr: Optional[str] = None
    table_object_name: Optional[str] = None


class MetricSuggestResponse(BaseModel):
    suggestions: List[MetricSuggestionItem] = Field(default_factory=list)
    cache_hit: bool = False
    model: str = "unknown"


# -------------------------------------------------------------
# Endpoint
# -------------------------------------------------------------

@router.post("/metric-suggest", response_model=MetricSuggestResponse)
@limiter.limit("10/minute")
def post_metric_suggest(
    request: Request,
    response: Response,
    body: MetricSuggestRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> MetricSuggestResponse:
    """LLM tabanli dinamik metrik onerisi.

    Body: source_id, table, columns[], user_intent (opsiyonel)
    Response: suggestions[], cache_hit, model
    """
    # 1) Defensive validation — bos columns
    if not body.columns:
        raise HTTPException(
            status_code=400,
            detail="En az bir kolon gerekli (columns bos olamaz).",
        )

    # 2) User context kontrol
    if not current_user.get("id"):
        raise HTTPException(status_code=401, detail="Kullanici kimligi belirlenemedi.")

    # 3) Service cagrisi
    try:
        result = suggest_metrics(
            source_id=int(body.source_id),
            table=body.table,
            columns=[c.model_dump() for c in body.columns],
            user_intent=body.user_intent,
            table_label=body.table_label,
        )
    except (LLMConnectionError, LLMConfigError) as e:
        logger.warning("[llm_metric_api] LLM connection/config error: %s", e)
        raise HTTPException(
            status_code=503,
            detail=f"LLM servisine ulasilamadi: {e}",
        )
    except LLMResponseError as e:
        logger.warning("[llm_metric_api] LLM response parse error: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"LLM gecersiz cevap dondu: {e}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[llm_metric_api] unexpected error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Metrik onerisi uretilirken beklenmeyen hata olustu.",
        )

    # 4) Response build
    return MetricSuggestResponse(
        suggestions=[
            MetricSuggestionItem(**item) for item in (result.get("suggestions") or [])
        ],
        cache_hit=bool(result.get("cache_hit", False)),
        model=str(result.get("model") or "unknown"),
    )
