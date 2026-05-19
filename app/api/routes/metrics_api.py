"""
metrics_api — v3.26.0 Faz 3 (P1-b)
====================================
metric_definitions CRUD endpoint'leri.

Tenant izolasyonu: tüm endpoint'ler current_user.company_id'ye scope edilir.
Migration 019 PERMISSIVE RLS policy ek defansif katmandır; app-layer filter
yine de zorunlu (best practice).

Endpoints:
    GET    /api/metrics                — list (active by default)
    POST   /api/metrics                — create
    GET    /api/metrics/{id}           — detail
    PATCH  /api/metrics/{id}           — partial update
    DELETE /api/metrics/{id}           — delete
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context, apply_company_scope
from app.services import metric_registry as mr

router = APIRouter()


class MetricCreateIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    display_name: str = Field(..., min_length=2, max_length=256)
    sql_expression: str = Field(..., min_length=10)
    description: Optional[str] = None
    source_id: Optional[int] = None
    base_tables: Optional[List[str]] = None
    dimensions: Optional[List[str]] = None
    filters: Optional[Dict[str, Any]] = None
    unit: Optional[str] = None
    aggregation_type: Optional[str] = None
    synonyms: Optional[List[str]] = None


class MetricUpdateIn(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    sql_expression: Optional[str] = None
    base_tables: Optional[List[str]] = None
    dimensions: Optional[List[str]] = None
    filters: Optional[Dict[str, Any]] = None
    unit: Optional[str] = None
    aggregation_type: Optional[str] = None
    synonyms: Optional[List[str]] = None
    is_active: Optional[bool] = None


@router.get("/api/metrics")
def list_metrics_endpoint(
    source_id: Optional[int] = None,
    include_inactive: bool = False,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            metrics = mr.list_metrics(
                cur, company_id=company_id,
                source_id=source_id, include_inactive=include_inactive,
            )
        finally:
            cur.close()
    return {"metrics": metrics}


@router.post("/api/metrics")
def create_metric_endpoint(
    body: MetricCreateIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    user_id = current_user.get("id") or current_user.get("user_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")

    # SQL expression read-only guard — SELECT/WITH başlamalı, DDL/DML yasak
    expr_upper = body.sql_expression.strip().upper().lstrip("(")
    if not (expr_upper.startswith("SELECT") or expr_upper.startswith("WITH")):
        raise HTTPException(400, "sql_expression SELECT veya WITH ile başlamalı")

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            try:
                new_id = mr.create_metric(
                    cur, company_id=company_id,
                    name=body.name, display_name=body.display_name,
                    sql_expression=body.sql_expression,
                    description=body.description,
                    source_id=body.source_id,
                    base_tables=body.base_tables,
                    dimensions=body.dimensions,
                    filters=body.filters,
                    unit=body.unit,
                    aggregation_type=body.aggregation_type,
                    synonyms=body.synonyms,
                    created_by=user_id,
                )
            except Exception as e:
                conn.rollback()
                msg = str(e).lower()
                if "unique" in msg or "duplicate" in msg:
                    raise HTTPException(409, f"Bu isimde metric zaten var: {body.name}")
                raise HTTPException(500, f"Metric oluşturulamadı: {e}")
            conn.commit()
        finally:
            cur.close()
    return {"success": True, "id": new_id}


@router.get("/api/metrics/{metric_id}")
def get_metric_endpoint(
    metric_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            m = mr.get_metric(cur, metric_id, company_id)
        finally:
            cur.close()
    if not m:
        raise HTTPException(404, "Metric bulunamadı")
    return {"metric": m}


@router.patch("/api/metrics/{metric_id}")
def update_metric_endpoint(
    metric_id: int,
    body: MetricUpdateIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")
    updates = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(400, "Güncellenecek alan yok")
    if "sql_expression" in updates:
        expr_upper = updates["sql_expression"].strip().upper().lstrip("(")
        if not (expr_upper.startswith("SELECT") or expr_upper.startswith("WITH")):
            raise HTTPException(400, "sql_expression SELECT veya WITH ile başlamalı")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            ok = mr.update_metric(cur, metric_id, company_id, **updates)
            conn.commit()
        finally:
            cur.close()
    if not ok:
        raise HTTPException(404, "Metric bulunamadı veya güncelleme başarısız")
    return {"success": True}


@router.delete("/api/metrics/{metric_id}")
def delete_metric_endpoint(
    metric_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            ok = mr.delete_metric(cur, metric_id, company_id)
            conn.commit()
        finally:
            cur.close()
    if not ok:
        raise HTTPException(404, "Metric bulunamadı")
    return {"success": True}
