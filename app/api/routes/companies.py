"""
VYRA L1 Support API - Companies Routes
========================================
Multi-tenant firma yönetimi CRUD endpoint'leri.
v2.53.0
"""

import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user, get_current_admin
from app.core.db import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/companies", tags=["companies"])


# --- Pydantic Models ---

class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    tax_type: str = Field("vd", pattern=r'^(vd|tckn)$')
    tax_number: str = Field(..., min_length=1, max_length=11)
    address_il: Optional[str] = Field(None, max_length=100)
    address_ilce: Optional[str] = Field(None, max_length=100)
    address_mahalle: Optional[str] = Field(None, max_length=200)
    address_text: Optional[str] = None
    phone: str = Field(..., min_length=1, max_length=20)
    email: str = Field(..., min_length=1, max_length=255)
    website: Optional[str] = Field(None, max_length=500)
    contact_name: str = Field(..., min_length=1, max_length=100)
    contact_surname: str = Field(..., min_length=1, max_length=100)


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    tax_type: Optional[str] = Field(None, pattern=r'^(vd|tckn)$')
    tax_number: Optional[str] = Field(None, min_length=1, max_length=11)
    address_il: Optional[str] = Field(None, max_length=100)
    address_ilce: Optional[str] = Field(None, max_length=100)
    address_mahalle: Optional[str] = Field(None, max_length=200)
    address_text: Optional[str] = None
    phone: Optional[str] = Field(None, min_length=1, max_length=20)
    email: Optional[str] = Field(None, min_length=1, max_length=255)
    website: Optional[str] = Field(None, max_length=500)
    contact_name: Optional[str] = Field(None, min_length=1, max_length=100)
    contact_surname: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


# --- Endpoints ---

@router.get("/by-url")
def get_company_by_url(url: str = Query(..., description="Eşleştirilecek URL")):
    """
    URL'den firma eşleştirme. Auth gerektirmez (login ekranı için).
    Host:port bazlı eşleşme — path kısmı yok sayılır.
    """
    import re

    # URL'den host:port çıkar (protocol ve path hariç)
    match = re.match(r'https?://([^/]+)', url)
    if not match:
        return {"found": False, "company": None}

    request_host = match.group(1).lower()  # örn: "localhost:5500"

    with get_db_context() as conn:
        cur = conn.cursor()
        # DB'deki website'lardan da host:port çıkarıp eşleştir
        cur.execute("""
            SELECT id, name, website, (logo_data IS NOT NULL) as has_logo
            FROM companies
            WHERE website IS NOT NULL 
              AND website != ''
              AND is_active = TRUE
        """)
        rows = cur.fetchall()

    # Python tarafında host:port eşleşmesi
    for row in rows:
        db_match = re.match(r'https?://([^/]+)', row["website"] or "")
        if db_match and db_match.group(1).lower() == request_host:
            return {
                "found": True,
                "company": {
                    "id": row["id"],
                    "name": row["name"],
                    "has_logo": row["has_logo"],
                    "logo_url": f"/api/companies/{row['id']}/logo" if row["has_logo"] else None
                }
            }

    return {"found": False, "company": None}

@router.get("/")
def get_companies(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Firma listesi.
    Admin: Tüm firmalar.
    User: Sadece kendi firması.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        if is_admin:
            cur.execute("""
                SELECT id, name, tax_type, tax_number,
                       address_il, address_ilce, address_mahalle, address_text,
                       phone, email, website, contact_name, contact_surname,
                       is_active, created_at, updated_at,
                       (logo_data IS NOT NULL) as has_logo
                FROM companies
                ORDER BY name
            """)
        else:
            company_id = current_user.get("company_id")
            if not company_id:
                return []
            cur.execute("""
                SELECT id, name, tax_type, tax_number,
                       address_il, address_ilce, address_mahalle, address_text,
                       phone, email, website, contact_name, contact_surname,
                       is_active, created_at, updated_at,
                       (logo_data IS NOT NULL) as has_logo
                FROM companies
                WHERE id = %s
            """, (company_id,))

        rows = cur.fetchall()
        return [dict(row) for row in rows]


@router.get("/{company_id}")
def get_company(company_id: int, current_user: Dict[str, Any] = Depends(get_current_user)):
    """Firma detayı."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    # Admin değilse sadece kendi firmasını görebilir
    if not is_admin and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Bu firmayı görüntüleme yetkiniz yok.")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, tax_type, tax_number,
                   address_il, address_ilce, address_mahalle, address_text,
                   phone, email, website, contact_name, contact_surname,
                   is_active, created_at, updated_at,
                   (logo_data IS NOT NULL) as has_logo
            FROM companies WHERE id = %s
        """, (company_id,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Firma bulunamadı.")

    return dict(row)


@router.post("/")
def create_company(
    company: CompanyCreate,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Yeni firma oluşturur. Sadece admin."""
    with get_db_context() as conn:
        cur = conn.cursor()

        # Aynı vergi numarası ile kayıt var mı?
        cur.execute(
            "SELECT id FROM companies WHERE tax_number = %s",
            (company.tax_number,)
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Bu vergi numarası ile kayıtlı bir firma zaten mevcut."
            )

        cur.execute("""
            INSERT INTO companies (
                name, tax_type, tax_number,
                address_il, address_ilce, address_mahalle, address_text,
                phone, email, website, contact_name, contact_surname,
                created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, tax_type, tax_number,
                      address_il, address_ilce, address_mahalle, address_text,
                      phone, email, website, contact_name, contact_surname,
                      is_active, created_at, updated_at
        """, (
            company.name, company.tax_type, company.tax_number,
            company.address_il, company.address_ilce,
            company.address_mahalle, company.address_text,
            company.phone, company.email, company.website,
            company.contact_name, company.contact_surname,
            admin["id"]
        ))
        row = cur.fetchone()
        conn.commit()

    logger.info(f"[Companies] Yeni firma oluşturuldu: {company.name} (id={row['id']})")
    return dict(row)


@router.put("/{company_id}")
def update_company(
    company_id: int,
    company: CompanyUpdate,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Firma bilgilerini günceller. Sadece admin."""
    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id FROM companies WHERE id = %s", (company_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Firma bulunamadı.")

        update_data = company.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Güncellenecek veri yok.")

        # Vergi numarası benzersizlik kontrolü
        if "tax_number" in update_data:
            cur.execute(
                "SELECT id FROM companies WHERE tax_number = %s AND id != %s",
                (update_data["tax_number"], company_id)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail="Bu vergi numarası başka bir firmada kullanılıyor."
                )

        set_parts = []
        values = []
        for key, value in update_data.items():
            set_parts.append(f"{key} = %s")
            values.append(value)

        values.append(company_id)
        set_clause = ", ".join(set_parts)

        cur.execute(
            f"UPDATE companies SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            values
        )
        conn.commit()

        cur.execute("""
            SELECT id, name, tax_type, tax_number,
                   address_il, address_ilce, address_mahalle, address_text,
                   phone, email, website, contact_name, contact_surname,
                   is_active, created_at, updated_at,
                   (logo_data IS NOT NULL) as has_logo
            FROM companies WHERE id = %s
        """, (company_id,))
        row = cur.fetchone()

    logger.info(f"[Companies] Firma güncellendi: id={company_id}")
    return dict(row)


@router.delete("/{company_id}")
def delete_company(
    company_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Firma siler (soft delete — is_active=FALSE). Sadece admin."""
    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, name FROM companies WHERE id = %s", (company_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Firma bulunamadı.")

        # Firmaya bağlı aktif kullanıcı var mı?
        cur.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE company_id = %s AND is_approved = TRUE",
            (company_id,)
        )
        user_count = cur.fetchone()["cnt"]
        if user_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Bu firmada {user_count} aktif kullanıcı var. Önce kullanıcıları başka firmaya taşıyın."
            )

        cur.execute(
            "UPDATE companies SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (company_id,)
        )
        conn.commit()

    logger.info(f"[Companies] Firma deaktif edildi: {row['name']} (id={company_id})")
    return {"message": "Firma başarıyla deaktif edildi."}


# --- Logo Endpoints ---

@router.get("/{company_id}/logo")
def get_company_logo(company_id: int):
    """Firma logosunu binary olarak döndürür. Auth gerektirmez (login ekranı için)."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT logo_data, logo_mime FROM companies WHERE id = %s",
            (company_id,)
        )
        row = cur.fetchone()

    if not row or not row["logo_data"]:
        raise HTTPException(status_code=404, detail="Logo bulunamadı.")

    return Response(
        content=bytes(row["logo_data"]),
        media_type=row["logo_mime"] or "image/png"
    )


@router.post("/{company_id}/logo")
async def upload_company_logo(
    company_id: int,
    file: UploadFile = File(...),
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Firma logosu yükler (BLOB). Sadece admin."""
    # MIME type kontrolü
    allowed_types = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya türü. İzin verilenler: {', '.join(allowed_types)}"
        )

    # Dosya boyutu kontrolü (max 2MB)
    file_data = await file.read()
    if len(file_data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo dosyası 2MB'dan büyük olamaz.")

    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id FROM companies WHERE id = %s", (company_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Firma bulunamadı.")

        cur.execute("""
            UPDATE companies
            SET logo_data = %s, logo_mime = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (file_data, file.content_type, company_id))
        conn.commit()

    logger.info(f"[Companies] Logo yüklendi: company_id={company_id}, size={len(file_data)}")
    return {"message": "Logo başarıyla yüklendi."}


@router.delete("/{company_id}/logo")
def delete_company_logo(
    company_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Firma logosunu siler. Sadece admin."""
    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id FROM companies WHERE id = %s", (company_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Firma bulunamadı.")

        cur.execute("""
            UPDATE companies
            SET logo_data = NULL, logo_mime = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (company_id,))
        conn.commit()

    return {"message": "Logo silindi."}
