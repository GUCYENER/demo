"""
VYRA Query State API — v3.28.3 G4
==================================
Pre-execute Drag-Drop Query Builder backend.

POST /api/query-state/preview
    Drag-drop UI state'inden parametrize SELECT SQL üretir.
    Sample data fetch ETMEZ — sadece sanity SQL döndürür.
    Kullanıcı SQL'i editöre kopyalayıp execute edebilir.

Body örneği:
    {
        "source_id": 5,                 # opsiyonel; dialect inference için
        "schema": "public",
        "table": "orders",
        "dialect": "postgresql",        # opsiyonel; source_id verilirse override
        "selected_columns": ["id", "total"],
        "filters": [{"column": "status", "op": "=", "value": "PAID"}],
        "order_by": {"column": "created_at", "direction": "DESC"},
        "limit": 50
    }
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context
from app.services.pipeline.nodes.query_state_builder import build_sql_from_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/query-state", tags=["query_state"])


class FilterClause(BaseModel):
    column: str = Field(..., max_length=63)
    op: str = Field(..., max_length=20)
    value: Optional[Any] = None


class OrderByClause(BaseModel):
    column: str = Field(..., max_length=63)
    direction: str = Field("ASC", pattern=r"^(?i)(ASC|DESC)$")


class QueryStateRequest(BaseModel):
    source_id: Optional[int] = Field(None, ge=1)
    schema: Optional[str] = Field(None, max_length=63)
    table: str = Field(..., min_length=1, max_length=63)
    dialect: Optional[str] = Field(None, pattern=r"^(postgresql|mssql|mysql|oracle)$")
    selected_columns: List[str] = Field(default_factory=list)
    filters: List[FilterClause] = Field(default_factory=list)
    order_by: Optional[OrderByClause] = None
    limit: Optional[int] = Field(None, ge=1, le=10000)


def _resolve_dialect(source_id: Optional[int], requested: Optional[str]) -> str:
    """source_id verilirse DB'den db_type oku — yoksa requested ya da postgresql."""
    if source_id:
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT db_type FROM data_sources WHERE id = %s", (source_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        return str(row[0]).lower()
        except Exception as e:
            logger.warning("[query_state] dialect lookup failed for source %s: %s", source_id, e)
    return (requested or "postgresql").lower()


@router.post("/preview")
def preview_query_state(
    req: QueryStateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Query state → SQL preview.

    Sample data fetch ETMEZ — yalnızca parametrize SELECT SQL döner.
    Frontend bu SQL'i editöre yapıştırır veya execute path'ine yönlendirir.
    """
    dialect = _resolve_dialect(req.source_id, req.dialect)

    state: Dict[str, Any] = {
        "schema": req.schema,
        "table": req.table,
        "dialect": dialect,
        "selected_columns": list(req.selected_columns or []),
        "filters": [f.model_dump() for f in (req.filters or [])],
        "order_by": req.order_by.model_dump() if req.order_by else None,
        "limit": req.limit,
    }

    try:
        result = build_sql_from_state(state)
    except Exception as e:
        logger.exception("[query_state] build failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sorgu inşa hatası: {e}")

    if not result.get("valid"):
        # 400: kullanıcının düzeltebileceği warnings döner
        return {
            "valid": False,
            "sql": None,
            "params": [],
            "dialect": dialect,
            "warnings": result.get("warnings", []),
        }

    return {
        "valid": True,
        "sql": result["sql"],
        "params": result.get("params", []),
        "dialect": dialect,
        "warnings": result.get("warnings", []),
    }
