"""
VYRA L1 Support API - Organization Management Routes
===================================================
Organizasyon grubu yönetimi API endpoint'leri (Admin Only).
"""

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_admin
from app.core.db import get_db_context


router = APIRouter(tags=["organizations"])


# ===========================================================
#  Pydantic Models
# ===========================================================

class OrganizationCreate(BaseModel):
    """Yeni organizasyon oluşturma"""
    org_code: str = Field(..., min_length=3, max_length=50, description="Organizasyon kodu (örn: ORG-IT)")
    org_name: str = Field(..., min_length=3, max_length=255, description="Organizasyon adı")
    description: Optional[str] = Field(None, description="Açıklama")
    is_active: bool = Field(True, description="Aktif mi?")
    company_id: Optional[int] = Field(None, description="Firma ID")


class OrganizationUpdate(BaseModel):
    """Organizasyon güncelleme"""
    org_name: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    company_id: Optional[int] = None


class OrganizationItem(BaseModel):
    """Organizasyon liste öğesi"""
    id: int
    org_code: str
    org_name: str
    description: Optional[str]
    is_active: bool
    user_count: int = 0  # Bu org grubundaki kullanıcı sayısı
    document_count: int = 0  # Bu org grubuna atanmış doküman sayısı
    created_at: str
    created_by: Optional[int]
    updated_at: Optional[str]


class OrganizationListResponse(BaseModel):
    """Organizasyon listesi response"""
    organizations: List[OrganizationItem]
    total: int
    per_page: int
    page: int


class OrganizationDetailResponse(BaseModel):
    """Organizasyon detay response"""
    id: int
    org_code: str
    org_name: str
    description: Optional[str]
    is_active: bool
    user_count: int
    document_count: int
    created_at: str
    created_by: Optional[int]
    created_by_name: Optional[str]
    updated_at: Optional[str]


# ===========================================================
#  Routes
# ===========================================================

@router.get("/organizations", response_model=OrganizationListResponse)
async def list_organizations(
    page: int = Query(1, ge=1, le=10000),
    per_page: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    is_active: Optional[bool] = None,
    company_id: Optional[int] = Query(None),
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Tüm organizasyon gruplarını listeler (Admin yetkisi gerekli).
    
    - **Pagination:** page, per_page parametreleri
    - **Search:** org_code veya org_name'de arama
    - **Filter:** is_active durumuna göre filtreleme
    """
    offset = (page - 1) * per_page
    
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # Base query
        where_clauses = []
        params = []
        
        if search:
            where_clauses.append("(LOWER(og.org_code) LIKE LOWER(%s) OR LOWER(og.org_name) LIKE LOWER(%s))")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])
        
        if is_active is not None:
            where_clauses.append("og.is_active = %s")
            params.append(is_active)
        
        if company_id is not None:
            where_clauses.append("og.company_id = %s")
            params.append(company_id)
        
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        
        # Total count
        count_sql = f"SELECT COUNT(*) as total FROM organization_groups og {where_sql}"
        cur.execute(count_sql, params if params else None)
        total = cur.fetchone()['total']
        
        # List with counts
        list_sql = f"""
            SELECT 
                og.id,
                og.org_code,
                og.org_name,
                og.description,
                og.is_active,
                og.created_at,
                og.created_by,
                og.updated_at,
                COUNT(DISTINCT uo.user_id) as user_count,
                COUNT(DISTINCT doc_org.file_id) as document_count
            FROM organization_groups og
            LEFT JOIN user_organizations uo ON og.id = uo.org_id
            LEFT JOIN document_organizations doc_org ON og.id = doc_org.org_id
            {where_sql}
            GROUP BY og.id, og.org_code, og.org_name, og.description, og.is_active, og.created_at, og.created_by, og.updated_at
            ORDER BY og.created_at DESC
            LIMIT %s OFFSET %s
        """
        list_params = params + [per_page, offset]
        cur.execute(list_sql, list_params)
        organizations = cur.fetchall()
        
        return {
            "organizations": [
                {
                    **org,
                    "created_at": org["created_at"].isoformat() if org["created_at"] else None,
                    "updated_at": org["updated_at"].isoformat() if org["updated_at"] else None,
                }
                for org in organizations
            ],
            "total": total,
            "per_page": per_page,
            "page": page
        }


@router.post("/organizations", status_code=201)
async def create_organization(
    payload: OrganizationCreate,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Yeni organizasyon grubu oluşturur (Admin yetkisi gerekli).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # Duplicate check
        cur.execute("SELECT id FROM organization_groups WHERE org_code = %s", (payload.org_code,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Organizasyon kodu '{payload.org_code}' zaten mevcut")
        
        # Insert
        cur.execute("""
            INSERT INTO organization_groups (org_code, org_name, description, is_active, created_by, company_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, org_code, org_name, created_at
        """, (
            payload.org_code,
            payload.org_name,
            payload.description,
            payload.is_active,
            admin["id"],
            payload.company_id
        ))
        org = cur.fetchone()
        
        return {
            "message": "Organizasyon grubu oluşturuldu",
            "organization": {
                **org,
                "created_at": org["created_at"].isoformat()
            }
        }


@router.get("/organizations/{org_id}", response_model=OrganizationDetailResponse)
async def get_organization(
    org_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Organizasyon grubu detaylarını döndürür (Admin yetkisi gerekli).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                og.id,
                og.org_code,
                og.org_name,
                og.description,
                og.is_active,
                og.created_at,
                og.created_by,
                og.updated_at,
                u.full_name as created_by_name,
                COUNT(DISTINCT uo.user_id) as user_count,
                COUNT(DISTINCT doc_org.file_id) as document_count
            FROM organization_groups og
            LEFT JOIN users u ON og.created_by = u.id
            LEFT JOIN user_organizations uo ON og.id = uo.org_id
            LEFT JOIN document_organizations doc_org ON og.id = doc_org.org_id
            WHERE og.id = %s
            GROUP BY og.id, og.org_code, og.org_name, og.description, og.is_active, og.created_at, og.created_by, og.updated_at, u.full_name
        """, (org_id,))
        org = cur.fetchone()
        
        if not org:
            raise HTTPException(status_code=404, detail="Organizasyon grubu bulunamadı")
        
        return {
            **org,
            "created_at": org["created_at"].isoformat(),
            "updated_at": org["updated_at"].isoformat() if org["updated_at"] else None,
        }


@router.put("/organizations/{org_id}")
async def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Organizasyon grubunu günceller (Admin yetkisi gerekli).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # Exists check
        cur.execute("SELECT id FROM organization_groups WHERE id = %s", (org_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Organizasyon grubu bulunamadı")
        
        # Build update query
        updates = []
        params = []
        
        if payload.org_name is not None:
            updates.append("org_name = %s")
            params.append(payload.org_name)
        
        if payload.description is not None:
            updates.append("description = %s")
            params.append(payload.description)
        
        if payload.is_active is not None:
            updates.append("is_active = %s")
            params.append(payload.is_active)
        
        if payload.company_id is not None:
            updates.append("company_id = %s")
            params.append(payload.company_id)
        
        if not updates:
            raise HTTPException(status_code=400, detail="Güncellenecek alan belirtilmedi")
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(org_id)
        
        cur.execute(f"""
            UPDATE organization_groups 
            SET {", ".join(updates)}
            WHERE id = %s
            RETURNING id, org_code, org_name, updated_at
        """, params)
        org = cur.fetchone()
        
        return {
            "message": "Organizasyon grubu güncellendi",
            "organization": {
                **org,
                "updated_at": org["updated_at"].isoformat()
            }
        }


@router.delete("/organizations/{org_id}", status_code=200)
async def delete_organization(
    org_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Organizasyon grubunu siler (Admin yetkisi gerekli).
    
    ⚠️ UYARI: Cascade deletion - tüm kullanıcı ve doküman ilişkileri de silinir.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # Protected orgs check
        cur.execute("SELECT org_code FROM organization_groups WHERE id = %s", (org_id,))
        org = cur.fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="Organizasyon grubu bulunamadı")
        
        if org['org_code'] in ['ORG-DEFAULT', 'ORG-ADMIN']:
            raise HTTPException(status_code=403, detail="Varsayılan organizasyon grupları silinemez")
        
        # Delete (cascade will handle relations)
        cur.execute("DELETE FROM organization_groups WHERE id = %s", (org_id,))
        
        return {
            "message": "Organizasyon grubu silindi",
            "org_code": org['org_code']
        }


@router.get("/organizations/{org_id}/users")
async def get_organization_users(
    org_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """
    Organizasyon grubundaki kullanıcıları listeler (Admin yetkisi gerekli).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # Org exists check
        cur.execute("SELECT org_code, org_name FROM organization_groups WHERE id = %s", (org_id,))
        org = cur.fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="Organizasyon grubu bulunamadı")
        
        # List users
        cur.execute("""
            SELECT 
                u.id,
                u.username,
                u.full_name,
                u.email,
                r.name as role_name,
                uo.assigned_at
            FROM users u
            JOIN user_organizations uo ON u.id = uo.user_id
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE uo.org_id = %s
            ORDER BY uo.assigned_at DESC
        """, (org_id,))
        users = cur.fetchall()
        
        return {
            "organization": org,
            "users": [
                {
                    **user,
                    "assigned_at": user["assigned_at"].isoformat()
                }
                for user in users
            ],
            "total": len(users)
        }
