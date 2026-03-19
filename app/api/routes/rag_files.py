"""
VYRA L1 Support API - RAG Files Routes
========================================
Dosya listeleme, indirme, silme ve org güncelleme endpoint'leri.
"""

from __future__ import annotations

from typing import Optional, Dict, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.db import get_db_conn
from app.api.routes.auth import get_current_user, get_current_admin
from app.api.schemas.rag_schemas import FileListItem, UpdateFileOrgsRequest
from app.services.logging_service import log_system_event
from app.services.document_processors import SUPPORTED_EXTENSIONS


router = APIRouter()


@router.get("/files")
async def list_files(
    page: int = Query(1, ge=1, le=10000),
    per_page: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    company_id: Optional[int] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Yüklenen dosyaları listeler (org grupları ile)"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Count query
        where_clauses = []
        count_params = []
        
        if search:
            where_clauses.append("f.file_name ILIKE %s")
            count_params.append(f"%{search}%")
        
        if company_id is not None:
            where_clauses.append("f.company_id = %s")
            count_params.append(company_id)
        
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
            
        cur.execute(f"SELECT COUNT(*) as cnt FROM uploaded_files f {where_sql}", count_params)
        total = cur.fetchone()['cnt']
        
        # Dosya listesini al (pagination ile)
        query = """
            SELECT f.id, f.file_name, f.file_type, f.file_size_bytes, f.chunk_count, 
                   f.uploaded_at, f.uploaded_by, u.full_name as uploaded_by_name,
                   f.maturity_score, f.status
            FROM uploaded_files f
            LEFT JOIN users u ON f.uploaded_by = u.id
        """
        params = list(count_params)  # Same WHERE params
        
        if where_sql:
            query += f" {where_sql}"
            
        query += " ORDER BY f.uploaded_at DESC"
        query += " LIMIT %s OFFSET %s"
        params.extend([per_page, (page - 1) * per_page])

        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Her dosya için org gruplarını al
        files = []
        for row in rows:
            file_id = row["id"]
            
            # Bu dosyaya atanmış org kodlarını al
            cur.execute(
                """
                SELECT og.org_code
                FROM document_organizations doc_org
                JOIN organization_groups og ON doc_org.org_id = og.id
                WHERE doc_org.file_id = %s
                ORDER BY og.org_code
                """,
                (file_id,)
            )
            org_rows = cur.fetchall()
            org_codes = [org_row["org_code"] for org_row in org_rows]
            
            files.append(FileListItem(
                id=row["id"],
                file_name=row["file_name"],
                file_type=row["file_type"],
                file_size_bytes=row["file_size_bytes"],
                chunk_count=row["chunk_count"] or 0,
                uploaded_at=str(row["uploaded_at"]),
                uploaded_by=row["uploaded_by"],
                uploaded_by_name=row["uploaded_by_name"],
                org_groups=org_codes,
                maturity_score=row["maturity_score"],
                status=row.get("status", "completed")
            ))
            
    finally:
        conn.close()
    
    return {
        "files": files,
        "total": total,
        "page": page,
        "per_page": per_page,
        "supported_extensions": SUPPORTED_EXTENSIONS
    }


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Dosyayı indirir"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT file_name, file_type, file_content FROM uploaded_files WHERE id = %s",
            (file_id,)
        )
        row = cur.fetchone()
    finally:
        conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    
    # Content type belirleme
    content_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain"
    }
    
    content_type = content_types.get(row["file_type"], "application/octet-stream")
    
    # Türkçe karakterler için RFC 5987 uyumlu encoding
    file_name = row["file_name"]
    encoded_filename = quote(file_name, safe='')
    
    return Response(
        content=bytes(row["file_content"]),
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.get("/download/{file_name:path}")
async def download_file_by_name(
    file_name: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Dosya adı ile indirir - Dialog chat içinden çözüm dokümanlarını indirmek için.
    
    🔒 GÜVENLİK: Kullanıcının yetkili olduğu org gruplarına bakılmalı (gelecekte eklenebilir)
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, file_name, file_type, file_content FROM uploaded_files WHERE file_name = %s",
            (file_name,)
        )
        row = cur.fetchone()
    finally:
        conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    
    # Content type belirleme
    content_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain"
    }
    
    content_type = content_types.get(row["file_type"], "application/octet-stream")
    
    # Türkçe karakterler için RFC 5987 uyumlu encoding
    encoded_filename = quote(row["file_name"], safe='')
    
    log_system_event("INFO", f"Dosya indirildi: {row['file_name']}", "rag", user_id=user["id"])
    
    return Response(
        content=bytes(row["file_content"]),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin),
):
    """Dosyayı ve chunk'larını veritabanından siler"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Dosya bilgisini al
        cur.execute("SELECT file_name FROM uploaded_files WHERE id = %s", (file_id,))
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Dosya bulunamadi")
        
        file_name = row["file_name"]
        
        # Transaction ile sil (önce chunk'lar, sonra dosya)
        cur.execute("DELETE FROM rag_chunks WHERE file_id = %s", (file_id,))
        cur.execute("DELETE FROM uploaded_files WHERE id = %s", (file_id,))
        
        conn.commit()
        
        log_system_event("INFO", f"Dosya silindi: {file_name}", "rag", user_id=admin["id"])
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        log_system_event("ERROR", f"Dosya silme hatası: {e}", "rag")
        raise HTTPException(status_code=500, detail="Dosya silme sırasında bir hata oluştu.")
    finally:
        conn.close()
    
    return {"message": f"Dosya silindi: {file_name}"}


@router.patch("/files/{file_id}/organizations")
async def update_file_organizations(
    file_id: int,
    request: UpdateFileOrgsRequest,
    admin: Dict[str, Any] = Depends(get_current_admin),
):
    """Dosyanın org gruplarını günceller"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Dosya var mı kontrol et
        cur.execute("SELECT id, file_name FROM uploaded_files WHERE id = %s", (file_id,))
        file_row = cur.fetchone()
        if not file_row:
            raise HTTPException(status_code=404, detail="Dosya bulunamadı")
        
        # Önce mevcut atamları sil
        cur.execute("DELETE FROM document_organizations WHERE file_id = %s", (file_id,))
        
        # Yeni atamları ekle
        for org_id in request.org_ids:
            cur.execute(
                """
                INSERT INTO document_organizations (file_id, org_id, assigned_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (file_id, org_id) DO NOTHING
                """,
                (file_id, org_id, admin["id"])
            )
        
        conn.commit()
        
        log_system_event("INFO", f"Dosya org grupları güncellendi: {file_row['file_name']}", "rag", user_id=admin["id"])
        
        return {"message": "Org grupları güncellendi", "file_id": file_id, "org_count": len(request.org_ids)}
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        log_system_event("ERROR", f"Org güncelleme hatası: {e}", "rag")
        raise HTTPException(status_code=500, detail="Güncelleme sırasında bir hata oluştu.")
    finally:
        conn.close()
