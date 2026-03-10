"""
VYRA L1 Support API - Domain Organization Permissions API
==========================================================
Domain ↔ Organizasyon yetki yönetimi CRUD endpoint'leri.

Bu tablo, hangi domain'de hangi organizasyonların login yapabileceğini belirler.
v2.46.0
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.db import get_db_context
from app.api.routes.auth import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/domain-org-permissions", tags=["domain-org-permissions"])


# ─── Models ───

class DomainOrgCreate(BaseModel):
    domain: str
    org_code: str
    description: Optional[str] = None


class DomainOrgOut(BaseModel):
    id: int
    domain: str
    org_code: str
    description: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None


# ─── Endpoints ───

@router.get("", response_model=List[DomainOrgOut])
def list_domain_org_permissions(
    current_user: Dict[str, Any] = Depends(get_current_admin),
):
    """Tüm domain-org yetki kayıtlarını listele."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, domain, org_code, description, is_active,
                   created_at::text as created_at
            FROM domain_org_permissions
            WHERE is_active = TRUE
            ORDER BY domain, org_code
        """)
        rows = cur.fetchall()

    return [DomainOrgOut(**dict(row)) for row in rows]


@router.post("", status_code=201)
def create_domain_org_permission(
    payload: DomainOrgCreate,
    current_user: Dict[str, Any] = Depends(get_current_admin),
):
    """Yeni domain-org yetki kaydı oluştur. org_code ';' ile ayrılmışsa her biri ayrı kayıt olur."""
    domain = payload.domain.upper().strip()
    raw_orgs = payload.org_code.strip()

    if not domain or not raw_orgs:
        raise HTTPException(status_code=400, detail="Domain ve organizasyon alanları zorunludur.")

    # ';' ile birden fazla org destekle
    org_codes = [o.strip().upper() for o in raw_orgs.split(";") if o.strip()]

    if not org_codes:
        raise HTTPException(status_code=400, detail="En az bir organizasyon girilmelidir.")

    created = []
    skipped = []

    with get_db_context() as conn:
        cur = conn.cursor()

        for org_code in org_codes:
            # Duplicate kontrolü
            cur.execute(
                "SELECT id FROM domain_org_permissions WHERE domain = %s AND org_code = %s AND is_active = TRUE",
                (domain, org_code),
            )
            if cur.fetchone():
                skipped.append(org_code)
                continue

            cur.execute("""
                INSERT INTO domain_org_permissions (domain, org_code, description, is_active)
                VALUES (%s, %s, %s, TRUE)
                RETURNING id, domain, org_code, description, is_active, created_at::text as created_at
            """, (domain, org_code, payload.description or ""))
            row = cur.fetchone()
            created.append(DomainOrgOut(**dict(row)))

        conn.commit()

    if not created and skipped:
        raise HTTPException(status_code=409, detail=f"Tüm organizasyonlar zaten tanımlı: {', '.join(skipped)}")

    logger.info(f"[DomainOrg] {len(created)} yetki eklendi, {len(skipped)} atlandı: {domain} (user={current_user.get('username')})")

    # Tek kayıt → tek obje, çoklu → liste döndür
    if len(created) == 1:
        return created[0]
    return created


@router.put("/{permission_id}", response_model=DomainOrgOut)
def update_domain_org_permission(
    permission_id: int,
    payload: DomainOrgCreate,
    current_user: Dict[str, Any] = Depends(get_current_admin),
):
    """Domain-org yetki kaydını güncelle."""
    domain = payload.domain.upper().strip()
    org_code = payload.org_code.upper().strip()

    if not domain or not org_code:
        raise HTTPException(status_code=400, detail="Domain ve organizasyon alanları zorunludur.")

    with get_db_context() as conn:
        cur = conn.cursor()

        # Duplicate kontrolü (kendisi hariç)
        cur.execute(
            "SELECT id FROM domain_org_permissions WHERE domain = %s AND org_code = %s AND is_active = TRUE AND id != %s",
            (domain, org_code, permission_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail=f"'{domain}' / '{org_code}' zaten tanımlı.")

        cur.execute("""
            UPDATE domain_org_permissions
            SET domain = %s, org_code = %s, description = %s
            WHERE id = %s AND is_active = TRUE
            RETURNING id, domain, org_code, description, is_active, created_at::text as created_at
        """, (domain, org_code, payload.description or "", permission_id))
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")

    logger.info(f"[DomainOrg] Yetki güncellendi: {domain}/{org_code} (user={current_user.get('username')})")
    return DomainOrgOut(**dict(row))


@router.delete("/{permission_id}", status_code=204)
def delete_domain_org_permission(
    permission_id: int,
    current_user: Dict[str, Any] = Depends(get_current_admin),
):
    """Domain-org yetki kaydını sil (soft delete)."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE domain_org_permissions SET is_active = FALSE WHERE id = %s AND is_active = TRUE RETURNING id",
            (permission_id,),
        )
        deleted = cur.fetchone()
        conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")

    logger.info(f"[DomainOrg] Yetki silindi: id={permission_id} (user={current_user.get('username')})")
