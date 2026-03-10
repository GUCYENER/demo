"""
VYRA L1 Support API - LDAP Settings CRUD Routes
==================================================
Admin panelinden LDAP sunucu ayarlarının yönetimi.

Endpoints:
  GET    /api/ldap-settings          → Tüm LDAP ayarlarını listele
  POST   /api/ldap-settings          → Yeni LDAP ayarı ekle
  PUT    /api/ldap-settings/{id}     → LDAP ayarını güncelle
  DELETE /api/ldap-settings/{id}     → Soft delete
  POST   /api/ldap-settings/{id}/test → 3 aşamalı bağlantı testi

Version: 1.0.0 (v2.46.0)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.routes.auth import get_current_admin
from app.core.db import get_db_context
from app.core.encryption import encrypt_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ldap-settings", tags=["ldap"])


# ---------------------------------------------------------
#  Pydantic Schemas
# ---------------------------------------------------------

class LdapSettingCreate(BaseModel):
    domain: str
    display_name: str
    url: str
    bind_dn: str
    bind_password: str
    search_base: str
    search_filter: str = "(sAMAccountName={{username}})"
    allowed_orgs: List[str] = ["ICT-AO-MD"]
    enabled: bool = True
    use_ssl: bool = False
    timeout: int = 10


class LdapSettingUpdate(BaseModel):
    display_name: Optional[str] = None
    url: Optional[str] = None
    bind_dn: Optional[str] = None
    bind_password: Optional[str] = None  # Boşsa mevcut korunur
    search_base: Optional[str] = None
    search_filter: Optional[str] = None
    allowed_orgs: Optional[List[str]] = None
    enabled: Optional[bool] = None
    use_ssl: Optional[bool] = None
    timeout: Optional[int] = None


# ---------------------------------------------------------
#  Helper: Safe dict (bind_password gizle)
# ---------------------------------------------------------

def _safe_setting_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """bind_password'ü API response'da GİZLER."""
    return {
        "id": row["id"],
        "domain": row["domain"],
        "display_name": row["display_name"],
        "url": row["url"],
        "bind_dn": row["bind_dn"],
        "bind_password_set": bool(row.get("bind_password")),
        "search_base": row["search_base"],
        "search_filter": row["search_filter"],
        "allowed_orgs": row.get("allowed_orgs", []),
        "enabled": row["enabled"],
        "use_ssl": row["use_ssl"],
        "timeout": row["timeout"],
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
        "is_deleted": row.get("is_deleted", False),
    }


# ---------------------------------------------------------
#  CRUD Endpoints
# ---------------------------------------------------------

@router.get("")
def list_ldap_settings(
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """Tüm aktif LDAP ayarlarını listeler."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM ldap_settings 
            WHERE is_deleted = FALSE 
            ORDER BY domain
        """)
        rows = cur.fetchall()

    return {
        "settings": [_safe_setting_dict(row) for row in rows],
        "total": len(rows),
    }


@router.post("")
def create_ldap_setting(
    payload: LdapSettingCreate,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """Yeni LDAP ayarı oluşturur."""
    domain = payload.domain.upper().strip()

    with get_db_context() as conn:
        cur = conn.cursor()

        # Duplicate kontrol
        cur.execute(
            "SELECT id FROM ldap_settings WHERE domain = %s AND is_deleted = FALSE",
            (domain,),
        )
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"'{domain}' domain adı zaten kayıtlı.")

        # bind_password şifrele
        encrypted_password = encrypt_password(payload.bind_password)

        cur.execute(
            """
            INSERT INTO ldap_settings (
                domain, display_name, url, bind_dn, bind_password,
                search_base, search_filter, allowed_orgs,
                enabled, use_ssl, timeout,
                created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                domain, payload.display_name, payload.url.strip(),
                payload.bind_dn.strip(), encrypted_password,
                payload.search_base.strip(), payload.search_filter.strip(),
                payload.allowed_orgs,
                payload.enabled, payload.use_ssl, payload.timeout,
                current_admin["id"],
            ),
        )
        new_row = cur.fetchone()
        conn.commit()

    logger.info(f"[LDAP Settings] Created: {domain} by {current_admin.get('username', 'admin')}")

    return {
        "success": True,
        "message": f"LDAP ayarı '{domain}' başarıyla oluşturuldu.",
        "setting": _safe_setting_dict(new_row),
    }


@router.put("/{setting_id}")
def update_ldap_setting(
    setting_id: int,
    payload: LdapSettingUpdate,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """LDAP ayarını günceller."""
    with get_db_context() as conn:
        cur = conn.cursor()

        # Mevcut kayıt kontrolü
        cur.execute(
            "SELECT * FROM ldap_settings WHERE id = %s AND is_deleted = FALSE",
            (setting_id,),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="LDAP ayarı bulunamadı.")

        # Güncellenecek alanları oluştur
        updates = []
        params = []

        if payload.display_name is not None:
            updates.append("display_name = %s")
            params.append(payload.display_name)

        if payload.url is not None:
            updates.append("url = %s")
            params.append(payload.url.strip())

        if payload.bind_dn is not None:
            updates.append("bind_dn = %s")
            params.append(payload.bind_dn.strip())

        if payload.bind_password is not None and payload.bind_password.strip():
            # Sadece girilmişse güncelle
            updates.append("bind_password = %s")
            params.append(encrypt_password(payload.bind_password))

        if payload.search_base is not None:
            updates.append("search_base = %s")
            params.append(payload.search_base.strip())

        if payload.search_filter is not None:
            updates.append("search_filter = %s")
            params.append(payload.search_filter.strip())

        if payload.allowed_orgs is not None:
            updates.append("allowed_orgs = %s")
            params.append(payload.allowed_orgs)

        if payload.enabled is not None:
            updates.append("enabled = %s")
            params.append(payload.enabled)

        if payload.use_ssl is not None:
            updates.append("use_ssl = %s")
            params.append(payload.use_ssl)

        if payload.timeout is not None:
            updates.append("timeout = %s")
            params.append(payload.timeout)

        if not updates:
            raise HTTPException(status_code=400, detail="Güncellenecek alan belirtilmedi.")

        updates.append("updated_at = NOW()")
        updates.append("updated_by = %s")
        params.append(current_admin["id"])
        params.append(setting_id)

        query = f"UPDATE ldap_settings SET {', '.join(updates)} WHERE id = %s RETURNING *"
        cur.execute(query, tuple(params))
        updated_row = cur.fetchone()
        conn.commit()

    logger.info(f"[LDAP Settings] Updated: id={setting_id} by {current_admin.get('username', 'admin')}")

    return {
        "success": True,
        "message": "LDAP ayarı güncellendi.",
        "setting": _safe_setting_dict(updated_row),
    }


@router.delete("/{setting_id}")
def delete_ldap_setting(
    setting_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """LDAP ayarını soft delete yapar."""
    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM ldap_settings WHERE id = %s AND is_deleted = FALSE",
            (setting_id,),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="LDAP ayarı bulunamadı.")

        cur.execute(
            "UPDATE ldap_settings SET is_deleted = TRUE, updated_at = NOW(), updated_by = %s WHERE id = %s",
            (current_admin["id"], setting_id),
        )
        conn.commit()

    logger.info(f"[LDAP Settings] Deleted: {existing['domain']} by {current_admin.get('username', 'admin')}")

    return {
        "success": True,
        "message": f"LDAP ayarı '{existing['domain']}' silindi.",
    }


@router.post("/{setting_id}/test")
def test_ldap_connection_endpoint(
    setting_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """3 aşamalı LDAP bağlantı testi: TCP → Server Init → Service Bind."""
    from app.services.ldap_auth import test_ldap_connection

    result = test_ldap_connection(setting_id)

    logger.info(
        f"[LDAP Settings] Connection test: id={setting_id}, success={result['success']}"
    )

    return result
