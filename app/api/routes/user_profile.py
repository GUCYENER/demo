"""
VYRA L1 Support API - User Profile Routes
===========================================
Self-service profil yönetimi endpoint'leri.
"""

from __future__ import annotations

from typing import Dict, Any

import bcrypt
from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db_conn
from app.api.routes.auth import get_current_user
from app.api.schemas.user_schemas import (
    ProfileResponse, UpdateProfileRequest, UpdateAvatarRequest, ChangePasswordRequest
)


router = APIRouter()


# ---------------------------------------------------------
#  Password Helpers
# ---------------------------------------------------------

def hash_password(password: str) -> str:
    """Şifreyi bcrypt ile hashler"""
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Düz metin şifreyi hash ile karşılaştırır"""
    pwd_bytes = plain_password.encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hash_bytes)


# ---------------------------------------------------------
#  Profile Routes
# ---------------------------------------------------------

@router.get("/me", response_model=ProfileResponse)
def get_my_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Mevcut kullanıcının profilini döndürür."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.*, r.name as role_name
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE u.id = %s
        """, (current_user['id'],))
        user = cur.fetchone()
    finally:
        conn.close()
    
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    
    return ProfileResponse(
        id=user['id'],
        full_name=user['full_name'],
        username=user['username'],
        email=user['email'],
        phone=user['phone'],
        avatar=user.get('avatar'),
        role_name=user['role_name'] or 'user',
        is_admin=user['is_admin'],
        is_approved=user['is_approved'],
        created_at=str(user['created_at']),
        auth_type=user.get('auth_type', 'local'),
        domain=user.get('domain'),
        department=user.get('department'),
        title=user.get('title'),
        organization=user.get('organization'),
    )


@router.get("/me/organizations")
def get_my_organizations(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Kullanıcının atanmış organizasyonlarını döndürür.
    
    🔒 GÜVENLİK: is_active durumunu da döndürür, 
    frontend bu bilgiyi kullanarak pasif org uyarısı gösterebilir.
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT o.id, o.org_code, o.org_name, o.is_active
            FROM user_organizations uo
            JOIN organization_groups o ON uo.org_id = o.id
            WHERE uo.user_id = %s
            ORDER BY o.org_code
        """, (current_user['id'],))
        orgs = cur.fetchall()
    finally:
        conn.close()
    
    return [
        {
            "id": org['id'],
            "org_code": org['org_code'],
            "org_name": org['org_name'],
            "is_active": org['is_active']
        }
        for org in orgs
    ]


@router.put("/me/avatar")
def update_my_avatar(
    payload: UpdateAvatarRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kullanıcının avatar'ını günceller."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users SET avatar = %s WHERE id = %s
        """, (payload.avatar, current_user['id']))
        conn.commit()
    finally:
        conn.close()
    
    return {"success": True, "message": "Avatar güncellendi"}


@router.put("/me")
def update_my_profile(
    payload: UpdateProfileRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kullanıcının profilini günceller. LDAP kullanıcıları düzenleyemez."""
    if current_user.get('auth_type') == 'ldap':
        raise HTTPException(status_code=403, detail="LDAP kullanıcıları profil bilgilerini değiştiremez.")
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        updates = []
        params = []
        
        if payload.full_name:
            updates.append("full_name = %s")
            params.append(payload.full_name)
        
        if payload.email:
            # Check if email is taken
            cur.execute("SELECT id FROM users WHERE email = %s AND id != %s", 
                       (payload.email, current_user['id']))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kullanılıyor")
            updates.append("email = %s")
            params.append(payload.email)
        
        if payload.phone:
            updates.append("phone = %s")
            params.append(payload.phone)
        
        if not updates:
            raise HTTPException(status_code=400, detail="Güncellenecek alan belirtilmedi")
        
        params.append(current_user['id'])
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"
        cur.execute(query, tuple(params))
        conn.commit()
        
    finally:
        conn.close()
    
    return {"message": "Profil güncellendi"}


@router.post("/me/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kullanıcının şifresini değiştirir. LDAP kullanıcıları şifre değiştiremez."""
    if current_user.get('auth_type') == 'ldap':
        raise HTTPException(status_code=403, detail="LDAP kullanıcıları şifre değiştiremez. Şifrenizi Active Directory üzerinden değiştirebilirsiniz.")
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Get current password hash
        cur.execute("SELECT password FROM users WHERE id = %s", (current_user['id'],))
        user = cur.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Verify current password
        if not verify_password(payload.current_password, user['password']):
            raise HTTPException(status_code=400, detail="Mevcut şifre yanlış")
        
        # Update password
        new_hashed = hash_password(payload.new_password)
        cur.execute("UPDATE users SET password = %s WHERE id = %s", 
                   (new_hashed, current_user['id']))
        conn.commit()
        
    finally:
        conn.close()
    
    return {"message": "Şifre değiştirildi"}
