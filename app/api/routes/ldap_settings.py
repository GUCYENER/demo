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

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.routes.auth import get_current_admin
from app.core.db import get_db_context
from app.core.encryption import encrypt_password
from app.services.logging_service import log_exception

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
    company_id: Optional[int] = None


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
        "company_id": row.get("company_id"),  # v3.59.0: edit modalında firma ön-seçili gelsin
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
    company_id: Optional[int] = None,
    include_deleted: bool = False,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """LDAP ayarlarını listeler. company_id ile filtrelenebilir.
    include_deleted=True → soft-delete edilmiş kayıtlar da döner (UI'da görünür/geri yüklenebilir)."""
    clauses = []
    params: list = []
    if not include_deleted:
        clauses.append("is_deleted = FALSE")
    if company_id:
        clauses.append("company_id = %s")
        params.append(company_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    # include_deleted'te aktifler önce gelsin (is_deleted ASC), sonra domain
    order = "ORDER BY is_deleted, domain" if include_deleted else "ORDER BY domain"

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM ldap_settings {where} {order}", tuple(params))
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

    # Boş bind_password → encrypt() ValueError fırlatır; net 400 ile karşıla (yakalanmamış 500 yerine)
    if not payload.bind_password or not payload.bind_password.strip():
        raise HTTPException(
            status_code=400,
            detail="Bind password (servis hesabı şifresi) zorunludur.",
        )

    try:
        with get_db_context() as conn:
            cur = conn.cursor()

            # Aktif (silinmemiş) duplicate → net 400
            cur.execute(
                "SELECT id FROM ldap_settings WHERE domain = %s AND is_deleted = FALSE",
                (domain,),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail=f"'{domain}' domain adı zaten kayıtlı.")

            # bind_password şifrele
            encrypted_password = encrypt_password(payload.bind_password)

            # Soft-delete edilmiş aynı domain var mı? UNIQUE constraint (ldap_settings_domain_key) domain'i
            # kapsar ama is_deleted'i DEĞİL → silinmiş kayıt INSERT'i UniqueViolation ile patlatır (500) ve
            # liste is_deleted=FALSE filtrelediğinden ekranda görünmez. Varsa CANLANDIR: un-delete + güncelle.
            cur.execute(
                "SELECT id FROM ldap_settings WHERE domain = %s AND is_deleted = TRUE",
                (domain,),
            )
            dead = cur.fetchone()

            if dead:
                # NOT: created_at bilinçli olarak DOKUNULMAZ (orijinal oluşturma tarihi korunur) —
                # UPDATE olduğundan mevcut değer aynen kalır; yalnız updated_at=NOW() güncellenir.
                cur.execute(
                    """
                    UPDATE ldap_settings SET
                        display_name = %s, url = %s, bind_dn = %s, bind_password = %s,
                        search_base = %s, search_filter = %s, allowed_orgs = %s,
                        enabled = %s, use_ssl = %s, timeout = %s,
                        company_id = %s, created_by = %s, updated_by = %s,
                        is_deleted = FALSE, updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        payload.display_name, payload.url.strip(),
                        payload.bind_dn.strip(), encrypted_password,
                        payload.search_base.strip(), payload.search_filter.strip(),
                        payload.allowed_orgs,
                        payload.enabled, payload.use_ssl, payload.timeout,
                        payload.company_id, current_admin["id"], current_admin["id"],
                        dead["id"],
                    ),
                )
                new_row = cur.fetchone()
                conn.commit()
                logger.info(
                    f"[LDAP Settings] Revived soft-deleted: {domain} by {current_admin.get('username', 'admin')}"
                )
                return {
                    "success": True,
                    "message": f"LDAP ayarı '{domain}' yeniden etkinleştirildi.",
                    "setting": _safe_setting_dict(new_row),
                }

            cur.execute(
                """
                INSERT INTO ldap_settings (
                    domain, display_name, url, bind_dn, bind_password,
                    search_base, search_filter, allowed_orgs,
                    enabled, use_ssl, timeout,
                    created_by, company_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    domain, payload.display_name, payload.url.strip(),
                    payload.bind_dn.strip(), encrypted_password,
                    payload.search_base.strip(), payload.search_filter.strip(),
                    payload.allowed_orgs,
                    payload.enabled, payload.use_ssl, payload.timeout,
                    current_admin["id"], payload.company_id,
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
    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation:
        # Nadir yarış (eşzamanlı aynı domain) → ham 500 yerine net 400
        raise HTTPException(status_code=400, detail=f"'{domain}' domain adı zaten kayıtlı.")
    except Exception as exc:
        log_exception(
            exc,
            module="ldap_settings",
            request_path="/api/ldap-settings",
            request_method="POST",
            user_id=current_admin.get("id"),
            context={"action": "create", "domain": domain},
        )
        raise HTTPException(status_code=500, detail=f"LDAP ayarı kaydedilemedi: {exc}")


@router.put("/{setting_id}")
def update_ldap_setting(
    setting_id: int,
    payload: LdapSettingUpdate,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """LDAP ayarını günceller."""
    try:
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
    except HTTPException:
        raise
    except Exception as exc:
        log_exception(
            exc,
            module="ldap_settings",
            request_path=f"/api/ldap-settings/{setting_id}",
            request_method="PUT",
            user_id=current_admin.get("id"),
            context={"action": "update", "setting_id": setting_id},
        )
        raise HTTPException(status_code=500, detail=f"LDAP ayarı güncellenemedi: {exc}")


@router.delete("/{setting_id}")
def delete_ldap_setting(
    setting_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """LDAP ayarını soft delete yapar."""
    try:
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
    except HTTPException:
        raise
    except Exception as exc:
        log_exception(
            exc,
            module="ldap_settings",
            request_path=f"/api/ldap-settings/{setting_id}",
            request_method="DELETE",
            user_id=current_admin.get("id"),
            context={"action": "delete", "setting_id": setting_id},
        )
        raise HTTPException(status_code=500, detail=f"LDAP ayarı silinemedi: {exc}")


@router.post("/{setting_id}/restore")
def restore_ldap_setting(
    setting_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """Soft-delete edilmiş LDAP ayarını geri yükler (is_deleted=FALSE)."""
    try:
        with get_db_context() as conn:
            cur = conn.cursor()

            cur.execute(
                "SELECT domain FROM ldap_settings WHERE id = %s AND is_deleted = TRUE",
                (setting_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Geri yüklenecek (silinmiş) LDAP ayarı bulunamadı.")
            domain = row["domain"]

            # Aynı domain'de AKTİF kayıt varsa UNIQUE constraint çakışır → net 400
            cur.execute(
                "SELECT id FROM ldap_settings WHERE domain = %s AND is_deleted = FALSE",
                (domain,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"'{domain}' için zaten aktif bir kayıt var; geri yüklenemez.",
                )

            cur.execute(
                "UPDATE ldap_settings SET is_deleted = FALSE, updated_at = NOW(), updated_by = %s "
                "WHERE id = %s RETURNING *",
                (current_admin["id"], setting_id),
            )
            restored = cur.fetchone()
            conn.commit()

        logger.info(f"[LDAP Settings] Restored: {domain} by {current_admin.get('username', 'admin')}")

        return {
            "success": True,
            "message": f"LDAP ayarı '{domain}' geri yüklendi.",
            "setting": _safe_setting_dict(restored),
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_exception(
            exc,
            module="ldap_settings",
            request_path=f"/api/ldap-settings/{setting_id}/restore",
            request_method="POST",
            user_id=current_admin.get("id"),
            context={"action": "restore", "setting_id": setting_id},
        )
        raise HTTPException(status_code=500, detail=f"LDAP ayarı geri yüklenemedi: {exc}")


@router.post("/{setting_id}/test")
def test_ldap_connection_endpoint(
    setting_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    """3 aşamalı LDAP bağlantı testi: TCP → Server Init → Service Bind."""
    from app.services.ldap_auth import test_ldap_connection

    try:
        result = test_ldap_connection(setting_id)

        logger.info(
            f"[LDAP Settings] Connection test: id={setting_id}, success={result['success']}"
        )

        return result
    except HTTPException:
        raise
    except Exception as exc:
        log_exception(
            exc,
            module="ldap_settings",
            request_path=f"/api/ldap-settings/{setting_id}/test",
            request_method="POST",
            user_id=current_admin.get("id"),
            context={"action": "test", "setting_id": setting_id},
        )
        raise HTTPException(status_code=500, detail=f"LDAP bağlantı testi başarısız: {exc}")
