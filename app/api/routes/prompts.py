"""
VYRA L1 Support API - Prompt Templates Routes
==============================================
Prompt şablonu yönetimi endpoint'leri.
"""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.api.routes.auth import get_current_admin
from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error

router = APIRouter()


class PromptCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50000)
    description: Optional[str] = Field(None, max_length=500)
    company_id: Optional[int] = None


class PromptUpdate(BaseModel):
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=50000)
    description: Optional[str] = Field(None, max_length=500)
    company_id: Optional[int] = None


class PromptOut(BaseModel):
    id: int
    category: str
    title: str
    content: str
    is_active: bool
    description: Optional[str]
    company_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


@router.get("/", response_model=List[PromptOut])
def list_prompts(
    company_id: Optional[int] = None,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    """Prompt'ları listele. company_id ile filtrelenebilir."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        if company_id:
            cur.execute("SELECT * FROM prompt_templates WHERE company_id = %s ORDER BY created_at DESC", (company_id,))
        else:
            cur.execute("SELECT * FROM prompt_templates ORDER BY created_at DESC")
        rows = cur.fetchall()
        
        log_system_event("INFO", "Prompt listesi görüntülendi", "prompts", user_id=admin["id"])
        return [dict(row) for row in rows]
    except Exception as e:
        log_error(f"Prompt listesi hatası: {str(e)}", "prompts", error_detail=str(e))
        raise HTTPException(500, "Prompt listesi alınamadı")
    finally:
        conn.close()


@router.post("/", response_model=PromptOut)
def create_prompt(payload: PromptCreate, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Yeni prompt oluştur. İlk kayıt ise otomatik aktif yapar."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Mevcut kayıt sayısını kontrol et
        cur.execute("SELECT COUNT(*) as cnt FROM prompt_templates")
        count_row = cur.fetchone()
        existing_count = count_row['cnt'] if count_row else 0
        
        # İlk kayıt ise otomatik aktif yap
        is_first_record = existing_count == 0
        
        cur.execute("""
            INSERT INTO prompt_templates (category, title, content, description, is_active, company_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (payload.category, payload.title, payload.content, payload.description, is_first_record, payload.company_id))
        row = cur.fetchone()
        conn.commit()
        
        log_system_event("INFO", f"Yeni prompt oluşturuldu: {payload.title}", "prompts", user_id=admin["id"])
        return dict(row)
    except Exception as e:
        conn.rollback()
        log_error(f"Prompt oluşturma hatası: {str(e)}", "prompts", error_detail=str(e))
        raise HTTPException(500, "Prompt oluşturulamadı")
    finally:
        conn.close()


@router.put("/{prompt_id}", response_model=PromptOut)
def update_prompt(prompt_id: int, payload: PromptUpdate, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Prompt güncelle"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        updates = []
        params = []
        if payload.category is not None:
            updates.append("category = %s")
            params.append(payload.category)
        if payload.title is not None:
            updates.append("title = %s")
            params.append(payload.title)
        if payload.content is not None:
            updates.append("content = %s")
            params.append(payload.content)
        if payload.description is not None:
            updates.append("description = %s")
            params.append(payload.description)
        if payload.company_id is not None:
            updates.append("company_id = %s")
            params.append(payload.company_id)
        
        if not updates:
            raise HTTPException(400, "Güncellenecek alan belirtilmedi")
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(prompt_id)
        
        cur.execute(f"UPDATE prompt_templates SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
        
        cur.execute("SELECT * FROM prompt_templates WHERE id = %s", (prompt_id,))
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(404, "Prompt bulunamadı")
        
        log_system_event("INFO", f"Prompt güncellendi: ID {prompt_id}", "prompts", user_id=admin["id"])
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log_error(f"Prompt güncelleme hatası: {str(e)}", "prompts", error_detail=str(e))
        raise HTTPException(500, "Prompt güncellenemedi")
    finally:
        conn.close()


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Prompt sil"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Aktif prompt silinemez
        cur.execute("SELECT is_active FROM prompt_templates WHERE id = %s", (prompt_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Prompt bulunamadı")
        
        if row["is_active"]:
            raise HTTPException(400, "Aktif prompt silinemez. Önce başka bir prompt'u aktif edin.")
        
        cur.execute("DELETE FROM prompt_templates WHERE id = %s", (prompt_id,))
        conn.commit()
        
        log_system_event("WARNING", f"Prompt silindi: ID {prompt_id}", "prompts", user_id=admin["id"])
        return {"message": "Prompt başarıyla silindi"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log_error(f"Prompt silme hatası: {str(e)}", "prompts", error_detail=str(e))
        raise HTTPException(500, "Prompt silinemedi")
    finally:
        conn.close()


@router.post("/{prompt_id}/activate")
def activate_prompt(prompt_id: int, admin: Dict[str, Any] = Depends(get_current_admin)):
    """Prompt'u aktif et (diğerlerini pasif yap)"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Prompt var mı kontrol et
        cur.execute("SELECT id FROM prompt_templates WHERE id = %s", (prompt_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Prompt bulunamadı")
        
        # Tüm prompt'ları pasif yap (aynı firma scope'unda)
        cur.execute("""
            UPDATE prompt_templates SET is_active = FALSE
            WHERE company_id = (SELECT company_id FROM prompt_templates WHERE id = %s)
               OR (company_id IS NULL AND (SELECT company_id FROM prompt_templates WHERE id = %s) IS NULL)
        """, (prompt_id, prompt_id))
        
        # Seçili prompt'u aktif et
        cur.execute("UPDATE prompt_templates SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (prompt_id,))
        conn.commit()
        
        log_system_event("INFO", f"Prompt aktif edildi: ID {prompt_id}", "prompts", user_id=admin["id"])
        return {"message": "Prompt başarıyla aktif edildi"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log_error(f"Prompt aktifleme hatası: {str(e)}", "prompts", error_detail=str(e))
        raise HTTPException(500, "Prompt aktif edilemedi")
    finally:
        conn.close()
