"""
VYRA - SQL Audit API
=====================
Admin panelden SQL audit loglarını izlemek için API endpoint'leri.

Endpoint'ler:
- GET /api/admin/sql-audit         → Sayfalı log listesi
- GET /api/admin/sql-audit/stats   → İstatistik özeti

Version: 2.58.0
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.api.routes.auth import get_current_user
from app.services.sql_audit_log import get_sql_audit_logs, get_sql_audit_stats

router = APIRouter(prefix="/api/admin/sql-audit", tags=["sql_audit"])


@router.get("")
async def list_sql_audit_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    source_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Sayfalı SQL audit log listesi (admin only)."""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")

    result = get_sql_audit_logs(
        page=page,
        per_page=per_page,
        status_filter=status,
        source_id_filter=source_id,
    )

    return result


@router.get("/stats")
async def sql_audit_statistics(
    current_user: dict = Depends(get_current_user),
):
    """SQL audit istatistik özeti (admin only)."""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")

    stats = get_sql_audit_stats()
    return stats
