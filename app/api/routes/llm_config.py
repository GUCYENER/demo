"""
VYRA L1 Support API - LLM Config Routes
========================================
LLM konfigürasyon yönetimi endpoint'leri.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_admin
from app.core.db import get_db_conn

router = APIRouter(tags=["llm_config"])


# --- Pydantic Models ---

class LLMConfigBase(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=100)
    api_url: str = Field(..., min_length=1, max_length=500)
    api_token: Optional[str] = Field(None, max_length=500)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(1.0, ge=0.0, le=1.0)
    timeout_seconds: int = Field(60, ge=1, le=300)
    description: Optional[str] = Field(None, max_length=500)
    vendor_code: Optional[str] = Field(None, max_length=50)


class LLMConfigCreate(LLMConfigBase):
    company_id: Optional[int] = None


class LLMConfigUpdate(BaseModel):
    provider: Optional[str] = Field(None, min_length=1, max_length=50)
    model_name: Optional[str] = Field(None, min_length=1, max_length=100)
    api_url: Optional[str] = Field(None, min_length=1, max_length=500)
    api_token: Optional[str] = Field(None, max_length=500)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    description: Optional[str] = Field(None, max_length=500)
    vendor_code: Optional[str] = Field(None, max_length=50)
    company_id: Optional[int] = None


class LLMConfigOut(LLMConfigBase):
    id: int
    is_active: bool
    company_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# --- Endpoints ---

@router.get("/", response_model=List[LLMConfigOut])
def get_llm_configs(
    company_id: Optional[int] = None,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """LLM konfigürasyonlarını listeler. company_id ile filtrelenebilir."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        if company_id:
            cur.execute("SELECT * FROM llm_config WHERE company_id = %s ORDER BY id DESC", (company_id,))
        else:
            cur.execute("SELECT * FROM llm_config ORDER BY id DESC")
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.post("/", response_model=LLMConfigOut)
def create_llm_config(config: LLMConfigCreate, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Yeni LLM konfigürasyonu ekler. İlk kayıt ise otomatik aktif yapar."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Mevcut kayıt sayısını kontrol et
        cur.execute("SELECT COUNT(*) as cnt FROM llm_config")
        count_row = cur.fetchone()
        existing_count = count_row['cnt'] if count_row else 0
        
        # İlk kayıt ise otomatik aktif yap
        is_first_record = existing_count == 0
        
        cur.execute("""
            INSERT INTO llm_config (
                vendor_code, provider, model_name, api_url, api_token,
                temperature, top_p, timeout_seconds, description, is_active, company_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            config.vendor_code, config.provider, config.model_name, config.api_url, 
            config.api_token, config.temperature, config.top_p, config.timeout_seconds,
            config.description, is_first_record, config.company_id
        ))
        row = cur.fetchone()
        conn.commit()
        return dict(row)
    finally:
        conn.close()


@router.put("/{llm_id}", response_model=LLMConfigOut)
def update_llm_config(llm_id: int, config: LLMConfigUpdate, admin: Dict[str, Any] = Depends(get_current_admin)):
    """LLM konfigürasyonunu günceller."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Önce kayıt var mı kontrol et
        cur.execute("SELECT * FROM llm_config WHERE id = %s", (llm_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="LLM config not found")

        # Güncellenecek alanları hazırla
        update_data = config.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No data to update")
        
        # PostgreSQL için parameterized query
        set_parts = []
        values = []
        for idx, (key, value) in enumerate(update_data.items(), 1):
            set_parts.append(f"{key} = %s")
            values.append(value)
        
        values.append(llm_id)
        set_clause = ", ".join(set_parts)
        
        cur.execute(
            f"UPDATE llm_config SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            values
        )
        conn.commit()
        
        cur.execute("SELECT * FROM llm_config WHERE id = %s", (llm_id,))
        row = cur.fetchone()
        return dict(row)
    finally:
        conn.close()


@router.delete("/{llm_id}")
def delete_llm_config(llm_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """LLM konfigürasyonunu siler."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Aktif olanı sildirmeyelim
        cur.execute("SELECT is_active FROM llm_config WHERE id = %s", (llm_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="LLM config not found")
            
        if row['is_active']:
            raise HTTPException(status_code=400, detail="Aktif olan LLM silinemez. Önce başka birini aktif yapın.")
        
        cur.execute("DELETE FROM llm_config WHERE id = %s", (llm_id,))
        conn.commit()
        
        return {"message": "LLM config deleted successfully"}
    finally:
        conn.close()


@router.post("/{llm_id}/activate")
def activate_llm_config(llm_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Seçilen LLM'i aktif yapar, diğerlerini pasif yapar."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Kayıt var mı?
        cur.execute("SELECT id FROM llm_config WHERE id = %s", (llm_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="LLM config not found")
        
        # Hepsini pasif yap (aynı firma scope'unda)
        cur.execute("""
            UPDATE llm_config SET is_active = FALSE
            WHERE company_id = (SELECT company_id FROM llm_config WHERE id = %s)
               OR (company_id IS NULL AND (SELECT company_id FROM llm_config WHERE id = %s) IS NULL)
        """, (llm_id, llm_id))
        # Seçileni aktif yap
        cur.execute("UPDATE llm_config SET is_active = TRUE WHERE id = %s", (llm_id,))
        conn.commit()
            
        return {"message": f"LLM config {llm_id} activated successfully"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        from app.services.logging_service import log_error
        log_error(f"LLM aktivasyon hatası: {e}", "llm_config")
        raise HTTPException(status_code=500, detail="LLM aktivasyon sırasında bir hata oluştu.")
    finally:
        conn.close()
