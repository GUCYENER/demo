"""
NGSSAI Widget API Routes (v2.60.0)
====================================
Web widget entegrasyon anahtarı yönetimi ve token endpoint'i.

Akış:
  1. Admin panelinde yeni widget key oluşturulur (POST /api/widget/keys)
  2. Sistem arka planda bir widget kullanıcısı oluşturur, orga atar
  3. Müşteri sitesi <script data-key="ngssai_..."> yükler
  4. Widget JS: POST /api/widget/token  → kısa ömürlü JWT alır
  5. JWT ile normal dialog/mesaj endpoint'leri kullanılır
"""

import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.db import get_db_context
from app.api.routes.auth import get_current_user, create_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["widget"])

security = HTTPBearer(auto_error=False)

# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class WidgetKeyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    org_id: int
    allowed_domains: List[str] = Field(default_factory=list)
    is_active: bool = True


class WidgetKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    allowed_domains: Optional[List[str]] = None
    is_active: Optional[bool] = None


class WidgetTokenRequest(BaseModel):
    api_key: str = Field(..., min_length=20)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_raw_key() -> tuple[str, str]:
    """(raw_key, prefix) döndürür. raw_key yalnızca bir kez gösterilir."""
    token = secrets.token_urlsafe(32)
    raw_key = f"ngssai_{token}"
    prefix = raw_key[:12]
    return raw_key, prefix


def _create_or_get_widget_user(conn, org_id: int, key_name: str, created_by: int) -> int:
    """Widget key'e bağlı sistem kullanıcısını oluşturur veya var olanı döndürür."""
    import bcrypt

    username = f"widget__{secrets.token_hex(6)}"
    email = f"{username}@widget.internal"
    full_name = f"Widget: {key_name}"
    dummy_pw = secrets.token_urlsafe(32)
    pw_hash = bcrypt.hashpw(dummy_pw.encode(), bcrypt.gensalt()).decode()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (full_name, username, email, phone, password,
                           role_id, is_admin, is_approved, approved_at)
        VALUES (%s, %s, %s, %s, %s, 2, FALSE, TRUE, NOW())
        RETURNING id
    """, (full_name, username, email, "0000000000", pw_hash))
    user_id = cur.fetchone()['id']

    # Orga ata
    cur.execute("""
        INSERT INTO user_organizations (user_id, org_id, assigned_at, assigned_by)
        VALUES (%s, %s, NOW(), %s)
        ON CONFLICT DO NOTHING
    """, (user_id, org_id, created_by))

    conn.commit()
    return user_id


# ------------------------------------------------------------------
# Public endpoint — widget token al (auth gerektirmez)
# ------------------------------------------------------------------

@router.post("/widget/token")
async def get_widget_token(body: WidgetTokenRequest, request: Request):
    """
    Widget API key ile kısa ömürlü JWT üretir.
    Bu endpoint herkese açıktır (auth gerektirmez).
    Domain whitelist kontrolü yapılır.
    """
    key_hash = _hash_key(body.api_key)
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT wk.id, wk.org_id, wk.allowed_domains, wk.is_active, wk.widget_user_id,
                   og.org_code
            FROM widget_api_keys wk
            JOIN organization_groups og ON og.id = wk.org_id
            WHERE wk.key_hash = %s
        """, (key_hash,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Geçersiz API anahtarı")

    key_id = row["id"]
    org_id = row["org_id"]
    allowed_domains = row["allowed_domains"]
    is_active = row["is_active"]
    widget_user_id = row["widget_user_id"]
    org_code = row["org_code"]

    if not is_active:
        raise HTTPException(status_code=403, detail="Bu API anahtarı devre dışı")

    # Domain whitelist kontrolü (boşsa herkese izin ver)
    if allowed_domains:
        request_domain = ""
        if origin:
            from urllib.parse import urlparse
            request_domain = urlparse(origin).netloc
        elif referer:
            from urllib.parse import urlparse
            request_domain = urlparse(referer).netloc

        if request_domain and not any(
            request_domain == d or request_domain.endswith("." + d)
            for d in allowed_domains
        ):
            raise HTTPException(status_code=403, detail="Bu domain için erişim izni yok")

    # Last used güncelle
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE widget_api_keys SET last_used_at = NOW() WHERE id = %s", (key_id,))
        conn.commit()

    # Widget JWT — 8 saatlik erişim token'ı
    token = create_token(
        data={
            "sub": str(widget_user_id),
            "role": "user",
            "widget": True,
            "org_id": org_id,
            "org_code": org_code,
        },
        expires_delta=timedelta(hours=8),
        token_type="access",
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "org_code": org_code,
        "expires_in": 28800,
    }


# ------------------------------------------------------------------
# Admin endpoints — key yönetimi
# ------------------------------------------------------------------

@router.get("/widget/keys")
async def list_widget_keys(current_user=Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Yalnızca admin erişebilir")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT wk.id, wk.name, wk.key_prefix, wk.org_id,
                   og.org_name, og.org_code, wk.allowed_domains,
                   wk.is_active, wk.created_at, wk.last_used_at,
                   u.full_name AS created_by_name
            FROM widget_api_keys wk
            JOIN organization_groups og ON og.id = wk.org_id
            LEFT JOIN users u ON u.id = wk.created_by
            ORDER BY wk.created_at DESC
        """)
        rows = cur.fetchall()

    return [
        {
            "id": r["id"],
            "name": r["name"],
            "key_prefix": r["key_prefix"],
            "org_id": r["org_id"],
            "org_name": r["org_name"],
            "org_code": r["org_code"],
            "allowed_domains": r["allowed_domains"] or [],
            "is_active": r["is_active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "created_by_name": r["created_by_name"],
        }
        for r in rows
    ]


@router.post("/widget/keys", status_code=201)
async def create_widget_key(body: WidgetKeyCreate, current_user=Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Yalnızca admin erişebilir")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, org_name FROM organization_groups WHERE id = %s AND is_active = TRUE", (body.org_id,))
        org = cur.fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="Organizasyon bulunamadı")

    raw_key, prefix = _generate_raw_key()
    key_hash = _hash_key(raw_key)

    with get_db_context() as conn:
        widget_user_id = _create_or_get_widget_user(conn, body.org_id, body.name, current_user["id"])

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO widget_api_keys
                (name, key_prefix, key_hash, widget_user_id, org_id,
                 allowed_domains, is_active, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (
            body.name, prefix, key_hash, widget_user_id, body.org_id,
            __import__('json').dumps(body.allowed_domains),
            body.is_active, current_user["id"]
        ))
        row_created = cur.fetchone()
        key_id = row_created["id"]
        created_at = row_created["created_at"]
        conn.commit()

    logger.info(f"[Widget] Yeni API key oluşturuldu: {body.name} (id={key_id}, org={body.org_id})")

    return {
        "id": key_id,
        "name": body.name,
        "key_prefix": prefix,
        "api_key": raw_key,
        "org_id": body.org_id,
        "allowed_domains": body.allowed_domains,
        "is_active": body.is_active,
        "created_at": created_at.isoformat(),
        "note": "Bu anahtar yalnızca bir kez gösterilmektedir. Güvenli bir yerde saklayın.",
    }


@router.put("/widget/keys/{key_id}")
async def update_widget_key(
    key_id: int,
    body: WidgetKeyUpdate,
    current_user=Depends(get_current_user),
):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Yalnızca admin erişebilir")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM widget_api_keys WHERE id = %s", (key_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Widget key bulunamadı")

        updates = []
        params = []
        if body.name is not None:
            updates.append("name = %s")
            params.append(body.name)
        if body.allowed_domains is not None:
            updates.append("allowed_domains = %s")
            params.append(__import__('json').dumps(body.allowed_domains))
        if body.is_active is not None:
            updates.append("is_active = %s")
            params.append(body.is_active)

        if updates:
            params.append(key_id)
            cur.execute(
                f"UPDATE widget_api_keys SET {', '.join(updates)} WHERE id = %s",
                params
            )
            conn.commit()

    return {"message": "Widget key güncellendi"}


@router.delete("/widget/keys/{key_id}", status_code=204)
async def delete_widget_key(key_id: int, current_user=Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Yalnızca admin erişebilir")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT widget_user_id FROM widget_api_keys WHERE id = %s", (key_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Widget key bulunamadı")

        widget_user_id = row["widget_user_id"]
        cur.execute("DELETE FROM widget_api_keys WHERE id = %s", (key_id,))
        # Widget kullanıcısını da sil
        if widget_user_id:
            cur.execute("DELETE FROM users WHERE id = %s", (widget_user_id,))
        conn.commit()

    logger.info(f"[Widget] API key silindi: id={key_id}")
