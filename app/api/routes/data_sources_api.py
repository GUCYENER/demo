"""
VYRA L1 Support API - Data Sources Routes
===========================================
Veri kaynakları CRUD endpoint'leri.
v2.55.0
"""

import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-sources", tags=["data_sources"])


# --- Pydantic Models ---

class DataSourceCreate(BaseModel):
    company_id: int
    name: str = Field(..., min_length=2, max_length=200)
    source_type: str = Field(..., pattern=r'^(database|file_server|manual_file|ftp|sharepoint)$')
    db_type: Optional[str] = Field(None, pattern=r'^(postgresql|mssql|mysql|oracle|ftp|ftps|sftp)$')
    host: Optional[str] = Field(None, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    db_name: Optional[str] = Field(None, max_length=200)
    db_user: Optional[str] = Field(None, max_length=200)
    db_password: Optional[str] = Field(None, max_length=500)
    file_server_path: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = None
    is_active: bool = True


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    source_type: Optional[str] = Field(None, pattern=r'^(database|file_server|manual_file|ftp|sharepoint)$')
    db_type: Optional[str] = Field(None, pattern=r'^(postgresql|mssql|mysql|oracle|ftp|ftps|sftp)$')
    host: Optional[str] = Field(None, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    db_name: Optional[str] = Field(None, max_length=200)
    db_user: Optional[str] = Field(None, max_length=200)
    db_password: Optional[str] = Field(None, max_length=500)
    file_server_path: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = None
    is_active: Optional[bool] = None


# --- Helpers ---

def _encrypt_password(plain: str) -> str:
    """Basit şifreleme (Fernet yoksa base64 fallback)."""
    try:
        from cryptography.fernet import Fernet
        import os
        key = os.environ.get("VYRA_ENCRYPT_KEY")
        if key:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.encrypt(plain.encode()).decode()
    except ImportError:
        pass
    # Fallback: base64
    import base64
    return "b64:" + base64.b64encode(plain.encode()).decode()


def _mask_password(encrypted: str) -> str:
    """Şifreyi maskeleyerek döndürür."""
    if not encrypted:
        return None
    return "••••••••"


# --- Endpoints ---

@router.get("/")
def list_data_sources(
    company_id: Optional[int] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Veri kaynağı listesi.
    Admin: Tüm firmalar veya company_id ile filtreli.
    User: Sadece kendi firması.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        if is_admin:
            if company_id:
                cur.execute("""
                    SELECT ds.*, c.name as company_name
                    FROM data_sources ds
                    JOIN companies c ON c.id = ds.company_id
                    WHERE ds.company_id = %s
                    ORDER BY ds.name
                """, (company_id,))
            else:
                cur.execute("""
                    SELECT ds.*, c.name as company_name
                    FROM data_sources ds
                    JOIN companies c ON c.id = ds.company_id
                    ORDER BY c.name, ds.name
                """)
        else:
            user_company_id = current_user.get("company_id")
            if not user_company_id:
                return []
            cur.execute("""
                SELECT ds.*, c.name as company_name
                FROM data_sources ds
                JOIN companies c ON c.id = ds.company_id
                WHERE ds.company_id = %s
                ORDER BY ds.name
            """, (user_company_id,))

        rows = cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            # Şifreyi maskele
            item["db_password_encrypted"] = _mask_password(item.get("db_password_encrypted"))
            result.append(item)
        return result


@router.post("/")
def create_data_source(
    data: DataSourceCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Yeni veri kaynağı oluşturur."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    # Admin değilse sadece kendi firmasına ekleyebilir
    if not is_admin:
        user_company_id = current_user.get("company_id")
        if not user_company_id or user_company_id != data.company_id:
            raise HTTPException(status_code=403, detail="Bu firmaya kaynak ekleme yetkiniz yok.")

    # Firma kontrolü
    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id FROM companies WHERE id = %s AND is_active = TRUE", (data.company_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Firma bulunamadı.")

        # Şifreyi şifrele
        encrypted_pw = None
        if data.db_password:
            encrypted_pw = _encrypt_password(data.db_password)

        cur.execute("""
            INSERT INTO data_sources (
                company_id, name, source_type, db_type,
                host, port, db_name, db_user, db_password_encrypted,
                file_server_path, description, is_active, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, company_id, name, source_type, db_type,
                      host, port, db_name, db_user,
                      file_server_path, description, is_active,
                      created_at, updated_at, created_by
        """, (
            data.company_id, data.name, data.source_type, data.db_type,
            data.host, data.port, data.db_name, data.db_user, encrypted_pw,
            data.file_server_path, data.description, data.is_active,
            current_user["id"]
        ))
        row = cur.fetchone()
        conn.commit()

    logger.info(f"[DataSources] Yeni kaynak oluşturuldu: {data.name} (id={row['id']})")
    result = dict(row)
    result["db_password_encrypted"] = _mask_password(encrypted_pw)
    return result


@router.put("/{source_id}")
def update_data_source(
    source_id: int,
    data: DataSourceUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Veri kaynağını günceller."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

        # Yetki kontrolü
        if not is_admin and current_user.get("company_id") != existing["company_id"]:
            raise HTTPException(status_code=403, detail="Bu kaynağı düzenleme yetkiniz yok.")

        update_data = data.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Güncellenecek veri yok.")

        # Şifre güncelleme
        if "db_password" in update_data:
            pw = update_data.pop("db_password")
            if pw:
                update_data["db_password_encrypted"] = _encrypt_password(pw)

        set_parts = []
        values = []
        for key, value in update_data.items():
            set_parts.append(f"{key} = %s")
            values.append(value)

        values.append(source_id)
        set_clause = ", ".join(set_parts)

        cur.execute(
            f"UPDATE data_sources SET {set_clause}, updated_at = NOW() WHERE id = %s",
            values
        )
        conn.commit()

        cur.execute("""
            SELECT ds.*, c.name as company_name
            FROM data_sources ds
            JOIN companies c ON c.id = ds.company_id
            WHERE ds.id = %s
        """, (source_id,))
        row = cur.fetchone()

    logger.info(f"[DataSources] Kaynak güncellendi: id={source_id}")
    result = dict(row)
    result["db_password_encrypted"] = _mask_password(result.get("db_password_encrypted"))
    return result


@router.delete("/{source_id}")
def delete_data_source(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Veri kaynağını siler."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, name, company_id FROM data_sources WHERE id = %s", (source_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

        # Yetki kontrolü
        if not is_admin and current_user.get("company_id") != existing["company_id"]:
            raise HTTPException(status_code=403, detail="Bu kaynağı silme yetkiniz yok.")

        cur.execute("DELETE FROM data_sources WHERE id = %s", (source_id,))
        conn.commit()

    logger.info(f"[DataSources] Kaynak silindi: {existing['name']} (id={source_id})")
    return {"message": f"\"{existing['name']}\" kaynağı silindi."}
