"""
VYRA L1 Support API - User Admin Routes
=========================================
Admin kullanıcı yönetimi endpoint'leri.
"""

from __future__ import annotations

from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db import get_db_conn
from app.api.routes.auth import get_current_admin
from app.api.schemas.user_schemas import (
    ApproveUserRequest, RejectUserRequest, UpdateUserOrgsRequest,
    RolesResponse
)


router = APIRouter()


@router.get("/list")
def list_users(
    pending_only: bool = False,
    page: int = Query(1, ge=1, le=10000),
    per_page: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Tüm kullanıcıları listeler (Admin yetkisi gerekli)."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Where koşulları
        where_conditions = []
        params = []
        
        if pending_only:
            where_conditions.append("u.is_approved = FALSE")
        
        if search:
            where_conditions.append("(u.username ILIKE %s OR u.full_name ILIKE %s OR u.email ILIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        # Count query
        count_query = f"SELECT COUNT(*) as cnt FROM users u {where_clause}"
        cur.execute(count_query, params)
        total = cur.fetchone()['cnt']
        
        # Base query with pagination
        query = f"""
            SELECT u.*, r.name as role_name, r.description as role_desc
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            {where_clause}
        """
        
        query += " ORDER BY u.created_at DESC"
        query += " LIMIT %s OFFSET %s"
        params.extend([per_page, (page - 1) * per_page])
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Her kullanıcı için org gruplarını çek
        user_orgs_map = {}
        cur.execute("""
            SELECT uo.user_id, og.org_code
            FROM user_organizations uo
            JOIN organization_groups og ON uo.org_id = og.id
            WHERE og.is_active = TRUE
        """)
        for org_row in cur.fetchall():
            user_id = org_row['user_id']
            if user_id not in user_orgs_map:
                user_orgs_map[user_id] = []
            user_orgs_map[user_id].append(org_row['org_code'])
        
        # Pending count
        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_approved = FALSE")
        pending_result = cur.fetchone()
        pending_count = pending_result['cnt'] if pending_result else 0
        
    finally:
        conn.close()
    
    users = []
    for row in rows:
        user_id = row['id']
        users.append({
            "id": user_id,
            "full_name": row['full_name'],
            "username": row['username'],
            "email": row['email'],
            "phone": row['phone'],
            "role_id": row['role_id'] or 2,
            "role_name": row['role_name'] or 'user',
            "is_admin": row['is_admin'],
            "is_approved": row['is_approved'],
            "is_active": row.get('is_active', True),
            "approved_at": str(row['approved_at']) if row['approved_at'] else None,
            "created_at": str(row['created_at']),
            "orgs": user_orgs_map.get(user_id, [])  # Kullanıcının org grupları
        })
    
    return {
        "users": users,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pending_count": pending_count
    }


@router.post("/approve")
def approve_user(
    payload: ApproveUserRequest,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Kullanıcıyı onaylar, rol atar ve organizasyon gruplarına ekler (Admin yetkisi gerekli)."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # User exists?
        cur.execute("SELECT id FROM users WHERE id = %s", (payload.user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Update user
        cur.execute("""
            UPDATE users 
            SET is_approved = TRUE, 
                role_id = %s, 
                is_admin = %s,
                approved_by = %s,
                approved_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (payload.role_id, payload.is_admin, admin['id'], payload.user_id))
        
        # Assign to organization groups
        if payload.org_ids:
            # Önce mevcut org atamalarını temizle
            cur.execute("DELETE FROM user_organizations WHERE user_id = %s", (payload.user_id,))
            
            # Yeni org atamalarını ekle
            for org_id in payload.org_ids:
                cur.execute("""
                    INSERT INTO user_organizations (user_id, org_id, assigned_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, org_id) DO NOTHING
                """, (payload.user_id, org_id, admin['id']))
        
        conn.commit()
        
    finally:
        conn.close()
    
    return {
        "message": "Kullanıcı onaylandı ve organizasyon gruplarına atandı", 
        "user_id": payload.user_id,
        "org_count": len(payload.org_ids)
    }


@router.post("/reject")
def reject_user(
    payload: RejectUserRequest,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Kullanıcıyı reddeder ve siler (Admin yetkisi gerekli)."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # User exists and not approved?
        cur.execute("SELECT id, is_approved FROM users WHERE id = %s", (payload.user_id,))
        user = cur.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        if user['is_approved']:
            raise HTTPException(status_code=400, detail="Onaylanmış kullanıcı silinemez")
        
        # Delete user
        cur.execute("DELETE FROM users WHERE id = %s", (payload.user_id,))
        conn.commit()
        
    finally:
        conn.close()
    
    return {"message": "Kullanıcı reddedildi ve silindi", "user_id": payload.user_id}


@router.patch("/{user_id}/organizations")
def update_user_organizations(
    user_id: int,
    payload: UpdateUserOrgsRequest,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Kullanıcının org gruplarını günceller (Admin yetkisi gerekli)."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # User exists?
        cur.execute("SELECT id, full_name FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        # Mevcut org atamalarını temizle
        cur.execute("DELETE FROM user_organizations WHERE user_id = %s", (user_id,))
        
        # Yeni org atamalarını ekle
        for org_id in payload.org_ids:
            cur.execute("""
                INSERT INTO user_organizations (user_id, org_id, assigned_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, org_id) DO NOTHING
            """, (user_id, org_id, admin['id']))
        
        conn.commit()
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        from app.services.logging_service import log_error
        log_error(f"Org güncelleme hatası: {e}", "auth")
        raise HTTPException(status_code=500, detail="Güncelleme sırasında bir hata oluştu.")
    finally:
        conn.close()
    
    return {
        "message": f"Kullanıcı org grupları güncellendi: {user['full_name']}", 
        "user_id": user_id,
        "org_count": len(payload.org_ids)
    }


@router.put("/{user_id}/toggle-active")
def toggle_user_active(
    user_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Kullanıcıyı aktif/pasif yapar (Admin yetkisi gerekli)."""
    from app.services.logging_service import log_system_event

    # Kendi hesabını pasife alamaz
    if admin["id"] == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kendi hesabınızı pasife alamazsınız."
        )

    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, is_active FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

        new_status = not user["is_active"]
        cur.execute("UPDATE users SET is_active = %s WHERE id = %s", (new_status, user_id))
        conn.commit()

        action = "aktif" if new_status else "pasif"
        log_system_event(
            "INFO",
            f"[Admin] Kullanıcı {user['username']} {action} yapıldı (by {admin.get('username', 'admin')})",
            "auth"
        )

        return {"message": f"Kullanıcı {action} yapıldı.", "is_active": new_status}
    finally:
        conn.close()


@router.get("/roles", response_model=RolesResponse)
def get_roles(admin: Dict[str, Any] = Depends(get_current_admin)):
    """Tüm rolleri listeler (Admin yetkisi gerekli)."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, description FROM roles ORDER BY id")
        rows = cur.fetchall()
    finally:
        conn.close()

    return {"roles": [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]}
