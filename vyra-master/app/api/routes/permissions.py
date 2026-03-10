"""
Rol Yetkilendirme API Routes
RBAC (Role Based Access Control) sistemi için API endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.core.db import get_db_context
from app.api.routes.auth import get_current_user
from app.services.logging_service import log_system_event, log_error

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


# ============================================
# Pydantic Schemas
# ============================================

class PermissionItem(BaseModel):
    resource_type: str
    resource_id: str
    resource_label: Optional[str] = None
    parent_resource_id: Optional[str] = None
    can_view: bool = False
    can_create: bool = False
    can_update: bool = False
    can_delete: bool = False


class PermissionUpdate(BaseModel):
    permissions: List[PermissionItem]


class RolePermissionsResponse(BaseModel):
    role_name: str
    permissions: List[Dict[str, Any]]


# ============================================
# Helper Functions
# ============================================

def get_all_resources() -> List[Dict[str, Any]]:
    """Sistemdeki tüm menü, sekme ve buton kaynaklarını döndür"""
    return [
        # Menüler
        {"type": "menu", "id": "menuNewTicket", "label": "Ana Sayfa", "parent": None, "icon": "fa-home"},
        {"type": "menu", "id": "menuParameters", "label": "Parametreler", "parent": None, "icon": "fa-sliders"},
        {"type": "menu", "id": "menuKnowledgeBase", "label": "Bilgi Tabanı", "parent": None, "icon": "fa-book-open"},
        {"type": "menu", "id": "menuAuthorization", "label": "Yetkilendirme", "parent": None, "icon": "fa-user-shield"},
        {"type": "menu", "id": "menuOrganizations", "label": "Organizasyonlar", "parent": None, "icon": "fa-building"},
        {"type": "menu", "id": "menuProfile", "label": "Profilim", "parent": None, "icon": "fa-user"},
        
        # Parametreler altındaki sekmeler
        {"type": "tab", "id": "tabLlmConfig", "label": "LLM Tanımları", "parent": "menuParameters", "icon": "fa-microchip"},
        {"type": "tab", "id": "tabPromptDesign", "label": "Prompt Dizayn", "parent": "menuParameters", "icon": "fa-wand-magic-sparkles"},
        {"type": "tab", "id": "tabMLTraining", "label": "Model Eğitim", "parent": "menuParameters", "icon": "fa-brain"},
        {"type": "tab", "id": "tabSystemReset", "label": "Sistem Sıfırlama", "parent": "menuParameters", "icon": "fa-rotate-left"},
    ]


# ============================================
# API Endpoints
# ============================================

@router.get("/roles")
async def get_roles():
    """Mevcut rolleri getir"""
    log_system_event("DEBUG", "[Permissions] GET /roles", "permissions")
    return {
        "success": True,
        "roles": [
            {"name": "admin", "label": "Yönetici", "description": "Tüm yetkilere sahip"},
            {"name": "user", "label": "Kullanıcı", "description": "Kısıtlı yetkiler"}
        ]
    }


@router.get("/resources")
async def get_resources():
    """Sistemdeki tüm kaynakları (menü, sekme, buton) getir"""
    log_system_event("DEBUG", "[Permissions] GET /resources", "permissions")
    resources = get_all_resources()
    
    # Hiyerarşik yapıya dönüştür
    hierarchy = []
    
    # Önce menüleri ekle
    menus = [r for r in resources if r["type"] == "menu"]
    for menu in menus:
        menu_item = {
            "type": menu["type"],
            "id": menu["id"],
            "label": menu["label"],
            "icon": menu["icon"],
            "children": []
        }
        
        # Bu menünün altındaki sekmeleri bul
        tabs = [r for r in resources if r["type"] == "tab" and r["parent"] == menu["id"]]
        for tab in tabs:
            tab_item = {
                "type": tab["type"],
                "id": tab["id"],
                "label": tab["label"],
                "icon": tab["icon"],
                "children": []
            }
            menu_item["children"].append(tab_item)
        
        hierarchy.append(menu_item)
    
    return {
        "success": True,
        "resources": hierarchy
    }


# ÖNEMLİ: /my/permissions route'u /{role_name} route'undan ÖNCE tanımlanmalı
# Aksi halde "my" string'i role_name olarak yakalanır
@router.get("/my/permissions")
async def get_my_permissions(request_user=Depends(get_current_user)):
    """Giriş yapan kullanıcının yetkilerini getir"""
    
    is_admin = request_user.get("is_admin", False)
    role_name = "admin" if is_admin else "user"
    
    log_system_event("DEBUG", f"[Permissions] GET /my/permissions - role: {role_name}", "permissions")
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT resource_type, resource_id, can_view, can_create, can_update, can_delete
                    FROM role_permissions
                    WHERE role_name = %s
                """, (role_name,))
                
                rows = cur.fetchall()
                
                permissions = {}
                for row in rows:
                    permissions[row["resource_id"]] = {
                        "can_view": row["can_view"],
                        "can_create": row["can_create"],
                        "can_update": row["can_update"],
                        "can_delete": row["can_delete"]
                    }
                
                log_system_event("DEBUG", f"[Permissions] Response: {len(permissions)} permissions", "permissions")
                
                return {
                    "success": True,
                    "role": role_name,
                    "is_admin": is_admin,
                    "permissions": permissions
                }
                
    except Exception as e:
        log_error(f"Kullanıcı yetkileri getirme hatası: {e}", "permissions")
        raise HTTPException(status_code=500, detail="Kullanıcı yetkileri getirilemedi.")


@router.get("/{role_name}")
async def get_role_permissions(role_name: str):
    """Belirli bir rolün yetkilerini getir"""
    
    if role_name not in ["admin", "user"]:
        raise HTTPException(status_code=400, detail="Geçersiz rol adı")
    
    log_system_event("DEBUG", f"[Permissions] GET /{role_name}", "permissions")
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT resource_type, resource_id, resource_label, parent_resource_id,
                           can_view, can_create, can_update, can_delete
                    FROM role_permissions
                    WHERE role_name = %s
                    ORDER BY resource_type, resource_id
                """, (role_name,))
                
                rows = cur.fetchall()
                
                permissions = {}
                for row in rows:
                    permissions[row["resource_id"]] = {
                        "resource_type": row["resource_type"],
                        "resource_id": row["resource_id"],
                        "resource_label": row["resource_label"],
                        "parent_resource_id": row["parent_resource_id"],
                        "can_view": row["can_view"],
                        "can_create": row["can_create"],
                        "can_update": row["can_update"],
                        "can_delete": row["can_delete"]
                    }
                
                log_system_event("DEBUG", f"[Permissions] Response: {len(permissions)} permissions for {role_name}", "permissions")
                
                return {
                    "success": True,
                    "role_name": role_name,
                    "permissions": permissions
                }
                
    except Exception as e:
        log_error(f"Rol yetkileri getirme hatası: {e}", "permissions")
        raise HTTPException(status_code=500, detail="Rol yetkileri getirilemedi.")


@router.post("/{role_name}")
async def update_role_permissions(role_name: str, data: PermissionUpdate, request_user=Depends(get_current_user)):
    """Belirli bir rolün yetkilerini güncelle (Sadece admin)"""
    
    log_system_event("INFO", f"[Permissions] POST /{role_name} - {len(data.permissions)} permissions", "permissions")
    
    # Admin kontrolü
    if not request_user.get("is_admin"):
        log_error(f"[Permissions] Yetkisiz erişim denemesi: user_id={request_user.get('user_id')}", "permissions")
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    if role_name not in ["admin", "user"]:
        raise HTTPException(status_code=400, detail="Geçersiz rol adı")
    
    # Admin yetkilerini değiştirmeye izin verme
    if role_name == "admin":
        raise HTTPException(status_code=400, detail="Admin yetkileri değiştirilemez")
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                for perm in data.permissions:
                    cur.execute("""
                        INSERT INTO role_permissions 
                        (role_name, resource_type, resource_id, resource_label, parent_resource_id,
                         can_view, can_create, can_update, can_delete, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (role_name, resource_type, resource_id)
                        DO UPDATE SET
                            can_view = EXCLUDED.can_view,
                            can_create = EXCLUDED.can_create,
                            can_update = EXCLUDED.can_update,
                            can_delete = EXCLUDED.can_delete,
                            updated_at = NOW()
                    """, (
                        role_name,
                        perm.resource_type,
                        perm.resource_id,
                        perm.resource_label,
                        perm.parent_resource_id,
                        perm.can_view,
                        perm.can_create,
                        perm.can_update,
                        perm.can_delete
                    ))
                
                conn.commit()
                
                log_system_event(
                    "INFO",
                    f"Rol yetkileri güncellendi: {role_name} ({len(data.permissions)} kaynak)",
                    "permissions"
                )
                
                return {
                    "success": True,
                    "message": f"{role_name} rolü için {len(data.permissions)} yetki güncellendi"
                }
                
    except Exception as e:
        log_error(f"Rol yetkileri güncelleme hatası: {e}", "permissions")
        raise HTTPException(status_code=500, detail="Rol yetkileri güncellenemedi.")

