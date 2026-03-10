"""
VYRA L1 Support API - RAG Rebuild Routes
==========================================
Embedding yeniden oluşturma endpoint'i ve helper fonksiyonları.
"""

from __future__ import annotations

from typing import Dict, Any
import io

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db_conn
from app.api.routes.auth import get_current_admin
from app.api.schemas.rag_schemas import RebuildResponse
from app.services.logging_service import log_system_event, log_error
from app.services.rag_service import get_rag_service
from app.services.document_processors import get_processor_for_extension


router = APIRouter()


@router.post("/rebuild", response_model=RebuildResponse)
async def rebuild_embeddings(
    admin: Dict[str, Any] = Depends(get_current_admin),
):
    """Tüm dosyalar için embedding'leri yeniden oluşturur"""
    try:
        result = process_all_files_for_embeddings()
        
        log_system_event(
            "INFO",
            f"Embedding'ler yeniden olusturuldu: {result['processed_files']} dosya, {result['total_chunks']} chunk",
            "rag",
            user_id=admin["id"]
        )
        
        return RebuildResponse(
            success=result["success"],
            processed_files=result["processed_files"],
            total_chunks=result["total_chunks"],
            failed_files=result["failed_files"],
            errors=result["errors"]
        )
    except Exception as e:
        log_error(f"Rebuild hatasi: {str(e)}", "rag", error_detail=str(e))
        raise HTTPException(status_code=500, detail="Yeniden oluşturma sırasında bir hata oluştu.")


def process_all_files_for_embeddings() -> Dict[str, Any]:
    """
    Tüm dosyaları işler ve embedding'leri oluşturur.
    
    ⚡ DOSYA BAZLI ATOMİK: Her dosya kendi transaction'ında işlenir.
    Bir dosyada hata olursa sadece o dosya etkilenir, diğerleri devam eder.
    """
    result = {
        "success": True,
        "processed_files": 0,
        "total_chunks": 0,
        "failed_files": [],
        "errors": []
    }
    
    rag_service = get_rag_service()
    
    # Tüm dosyaları al (sadece meta bilgi, content lazy load)
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, file_name, file_content, file_type FROM uploaded_files")
        files = cur.fetchall()
    finally:
        conn.close()
    
    log_system_event("INFO", f"Yeniden oluşturma başladı: {len(files)} dosya", "rag")
    
    for file_row in files:
        file_id = file_row["id"]
        file_name = file_row["file_name"]
        file_content = bytes(file_row["file_content"])
        file_type = file_row["file_type"]
        
        # ⚡ HER DOSYA İÇİN AYRI TRANSACTİON
        file_conn = get_db_conn()
        try:
            file_cur = file_conn.cursor()
            
            processor = get_processor_for_extension(file_type)
            if not processor:
                result["failed_files"].append(file_name)
                result["errors"].append(f"İşlemci bulunamadı: {file_type}")
                log_error(f"İşlemci bulunamadı: {file_name} ({file_type})", "rag")
                continue
            
            # BytesIO ile işle
            file_obj = io.BytesIO(file_content)
            processed = processor.process_bytes(file_obj, file_name)
            
            # Chunk'ları hazırla
            chunks = [
                {
                    "text": chunk.text,
                    "metadata": {"source_file": file_name, **chunk.metadata}
                }
                for chunk in processed.chunks
            ]
            
            # ⚠️ 0 chunk üretildiyse uyarı logla ve bu dosyayı atla
            if not chunks:
                result["failed_files"].append(file_name)
                result["errors"].append(f"{file_name}: Dosya hazırlama kurallarına göre dokümanları güncelleyip aktarımı tekrar deneyiniz.")
                log_error(f"0 chunk: {file_name} - Dosya boş veya işlenemedi", "rag")
                continue
            
            # Chunk'ları embedding ile kaydet (AYNI TRANSACTİON İÇİNDE)
            chunk_count = rag_service.add_chunks_with_embeddings(
                file_id, 
                chunks, 
                cursor=file_cur  # Dışarıdan cursor geçir
            )
            
            # ✅ BU DOSYA İÇİN COMMIT
            file_conn.commit()
            
            result["processed_files"] += 1
            result["total_chunks"] += chunk_count
            
            log_system_event(
                "INFO", 
                f"Dosya işlendi: {file_name} ({chunk_count} chunk)", 
                "rag"
            )
            
        except Exception as e:
            # ❌ BU DOSYA İÇİN ROLLBACK (diğer dosyalar etkilenmez)
            file_conn.rollback()
            result["failed_files"].append(file_name)
            result["errors"].append(f"{file_name}: {str(e)}")
            log_error(f"Dosya işleme hatası: {file_name} - {str(e)}", "rag", error_detail=str(e))
            
        finally:
            file_conn.close()
    
    # Sonuç değerlendirmesi
    if result["failed_files"]:
        # En az bir dosya başarılıysa partial success
        result["success"] = result["processed_files"] > 0
    
    log_system_event(
        "INFO" if result["success"] else "WARNING",
        f"Yeniden oluşturma tamamlandı: {result['processed_files']}/{len(files)} dosya, "
        f"{result['total_chunks']} chunk, {len(result['failed_files'])} hata",
        "rag"
    )
    
    return result
