"""
VYRA L1 Support API - RAG Upload Routes
=========================================
Dosya yükleme endpoint'i.
Dosya türüne göre uygun processor seçilir.

v2.39.0: Asenkron upload — dosya kaydı senkron, processing background task.
İşlem bitince WebSocket üzerinden kullanıcıya bildirim gönderilir.
v2.42.0: Memory cleanup — büyük dosyalarda processing sonrası GC.
v2.43.0: run_in_executor — CPU-bound işlemler thread pool'da çalışır, event loop bloklanmaz.
"""

from __future__ import annotations

import asyncio
import gc
import functools
from typing import List, Optional, Dict, Any, Tuple
import io
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.core.config import settings
from app.core.db import get_db_conn
from app.api.routes.auth import get_current_user
from app.api.schemas.rag_schemas import FileUploadInfo, FileUploadResponse
from app.services.logging_service import log_system_event, log_error
from app.services.rag_service import get_rag_service
from app.services.document_processors import SUPPORTED_EXTENSIONS, get_processor_for_extension
from app.services.rag.topic_extraction import extract_and_save_topics


router = APIRouter()


@router.post("/upload-files", response_model=FileUploadResponse)
async def upload_files(
    files: List[UploadFile] = File(...),
    org_ids: Optional[str] = None,  # Virgülle ayrılmış org id'leri (örn: "1,2,3")
    maturity_scores: Optional[str] = None,  # Virgülle ayrılmış maturity skorları (örn: "85.3,72.1")
    company_id: Optional[int] = Query(None),  # Firma ID
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Dosya yükler, PostgreSQL'e kaydeder.
    Processing (parsing, embedding, topic extraction) arkaplanda çalışır.
    İşlem bitince WebSocket ile kullanıcıya bildirim gönderilir.

    v2.39.0: Asenkron akış — dosya kaydı senkron, ağır işlemler BackgroundTask.
    
    Desteklenen formatlar:
    - PDF → pdf_processor
    - DOCX → docx_processor
    - XLSX → excel_processor
    - PPTX → pptx_processor
    - TXT → direkt okuma
    """
    saved_files: List[FileUploadInfo] = []
    max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024

    conn = get_db_conn()
    
    try:
        cur = conn.cursor()
        
        # Dosya bilgilerini sakla (background processing için)
        files_to_process = []
        
        for f in files:
            # Dosya uzantısını kontrol et
            ext = f".{f.filename.rsplit('.', 1)[-1].lower()}" if "." in f.filename else ""
            
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Desteklenmeyen dosya formati: {f.filename}. "
                           f"Desteklenen: {', '.join(SUPPORTED_EXTENSIONS)}"
                )

            # Dosya içeriğini oku
            content = await f.read()
            file_size = len(content)
            
            if file_size > max_size_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dosya cok buyuk: {f.filename} ({file_size // (1024*1024)}MB). "
                           f"Maksimum: {settings.MAX_FILE_SIZE_MB}MB"
                )

            # MIME type
            mime_type = f.content_type or "application/octet-stream"

            # Aynı isimli dosya varsa önce chunk'larını sil sonra dosyayı sil
            cur.execute(
                """
                DELETE FROM rag_chunks WHERE file_id IN (
                    SELECT id FROM uploaded_files WHERE file_name = %s
                )
                """,
                (f.filename,)
            )
            cur.execute("DELETE FROM uploaded_files WHERE file_name = %s", (f.filename,))

            # Dosyayı PostgreSQL'e kaydet — status='processing'
            cur.execute(
                """
                INSERT INTO uploaded_files (file_name, file_type, file_size_bytes, file_content, mime_type, uploaded_by, status, company_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'processing', %s)
                RETURNING id
                """,
                (f.filename, ext, file_size, content, mime_type, current_user["id"], company_id),
            )
            file_id = cur.fetchone()["id"]
            
            # Org gruplarına ata (varsa)
            if org_ids:
                org_id_list = [int(x.strip()) for x in org_ids.split(",") if x.strip()]
                for org_id in org_id_list:
                    cur.execute(
                        """
                        INSERT INTO document_organizations (file_id, org_id)
                        VALUES (%s, %s)
                        ON CONFLICT (file_id, org_id) DO NOTHING
                        """,
                        (file_id, org_id)
                    )
            
            # Background processing için dosya bilgilerini sakla
            files_to_process.append({
                "file_id": file_id,
                "file_name": f.filename,
                "file_type": ext,
                "file_content": content,
                "file_size": file_size
            })

            saved_files.append(
                FileUploadInfo(
                    file_name=f.filename,
                    file_type=ext,
                    file_size_bytes=file_size
                )
            )

        # ✅ DOSYA KAYDI COMMIT — processing arkaplanda devam edecek
        conn.commit()
        
        log_system_event(
            "INFO",
            f"Dosya kaydı tamamlandı: {len(saved_files)} dosya (processing başlıyor)",
            "rag",
            user_id=current_user["id"]
        )
        
        # 🔥 Background processing başlat (embedding, image extraction, topic)
        user_id = current_user["id"]
        
        # v2.40.0: Maturity skorlarını index bazlı dict'e çevir (güvenli erişim)
        maturity_score_map = {}
        if maturity_scores:
            try:
                score_list = [float(s.strip()) for s in maturity_scores.split(',') if s.strip()]
                for idx, score_val in enumerate(score_list):
                    if idx < len(files_to_process):
                        maturity_score_map[files_to_process[idx]["file_id"]] = score_val
            except Exception as e:
                log_error(f"Maturity score parse hatası: {e}", "rag")
        
        # Background task'ı güvenli şekilde başlat
        asyncio.ensure_future(
            _process_files_background(files_to_process, user_id, maturity_score_map)
        )
        
    except HTTPException:
        conn.rollback()
        log_error("Dosya yükleme iptal edildi (rollback)", "rag")
        raise
    except Exception as e:
        conn.rollback()
        log_error(f"Dosya yükleme hatası (rollback): {str(e)}", "rag", error_detail=str(e))
        raise HTTPException(status_code=500, detail="Dosya yükleme sırasında bir hata oluştu.")
    finally:
        conn.close()

    return FileUploadResponse(
        message=f"{len(saved_files)} dosya kaydedildi, işleniyor...",
        uploaded_count=len(saved_files),
        files=saved_files,
        embeddings_created=False  # Henüz processing başlamadı
    )


# ═══════════════════════════════════════════════
# BACKGROUND PROCESSING
# ═══════════════════════════════════════════════

# v2.43.0: Thread pool — CPU-bound işlemler event loop'u bloklamaz
_file_processing_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag_worker")


def _process_single_file_sync(
    file_info: dict,
    user_id: int,
    maturity_score_map: dict,
) -> Tuple[int, str, bool]:
    """
    Tek bir dosyayı SENKRON işler (ThreadPoolExecutor'da çalışır).
    CPU-bound: parsing, embedding, image extraction, topic extraction.
    
    v2.43.0: Event loop bloklanmasını önlemek için run_in_executor ile çağrılır.
    
    Returns:
        (chunk_count, file_name, success)
    """
    conn = None
    file_name = file_info["file_name"]
    
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        rag_service = get_rag_service()
        
        # 1. Processor ile dosyayı parse et
        processor = get_processor_for_extension(file_info["file_type"])
        if not processor:
            raise ValueError(f"İşlemci bulunamadı: {file_info['file_type']}")
        
        file_obj = io.BytesIO(file_info["file_content"])
        processed = processor.process_bytes(file_obj, file_info["file_name"])
        
        # 2. Chunk'ları hazırla
        chunks = [
            {
                "text": chunk.text,
                "metadata": {"source_file": file_info["file_name"], **chunk.metadata}
            }
            for chunk in processed.chunks
        ]
        
        # ❌ 0 chunk üretildiyse hata fırlat
        if not chunks:
            raise ValueError(
                "Dosyadan hiç veri çıkarılamadı. "
                "Dosya hazırlama kurallarına göre dokümanları güncelleyip aktarımı tekrar deneyiniz."
            )
        
        # Topic çıkarma için chunk'ları sakla
        parsed_chunks = chunks
        
        # 3. Chunk'ları embedding ile kaydet
        chunk_count = rag_service.add_chunks_with_embeddings(
            file_info["file_id"],
            chunks,
            cursor=cur
        )
        
        # 4. Görsel çıkarma (DOCX/PDF/PPTX)
        try:
            from app.services.document_processors.image_extractor import ImageExtractor
            img_extractor = ImageExtractor()
            extracted_images = img_extractor.extract(
                file_info["file_content"], file_info["file_type"]
            )
            if extracted_images:
                image_ids = img_extractor.save_to_db(
                    extracted_images, file_info["file_id"], cursor=cur
                )
                if image_ids:
                    _update_chunk_image_refs(
                        cur, file_info["file_id"],
                        extracted_images, image_ids
                    )
        except Exception as img_err:
            log_system_event(
                "WARNING",
                f"Görsel çıkarma atlandı ({file_name}): {img_err}",
                "rag_upload"
            )
        
        # 5. Maturity score + Status güncelle → completed
        file_id = file_info["file_id"]
        m_score = maturity_score_map.get(file_id)
        
        if m_score is not None:
            cur.execute(
                "UPDATE uploaded_files SET status = 'completed', chunk_count = %s, maturity_score = %s WHERE id = %s",
                (chunk_count, m_score, file_id)
            )
            log_system_event(
                "INFO",
                f"Maturity score kaydedildi: {file_name} → {m_score}",
                "rag",
                user_id=user_id
            )
        else:
            cur.execute(
                "UPDATE uploaded_files SET status = 'completed', chunk_count = %s WHERE id = %s",
                (chunk_count, file_id)
            )
        
        conn.commit()
        
        # 6. Topic çıkarma (commit sonrası, hata upload'ı bozmaz)
        try:
            if parsed_chunks:
                topic_count = extract_and_save_topics(
                    parsed_chunks, file_name, file_info["file_id"]
                )
                if topic_count > 0:
                    log_system_event(
                        "INFO",
                        f"{file_name}: {topic_count} topic otomatik çıkarıldı",
                        "rag",
                        user_id=user_id
                    )
        except Exception as e:
            log_error(f"Topic çıkarma hatası ({file_name}): {e}", "rag")
        
        # 7. 🧹 v2.42.0: Memory cleanup — büyük dosyalarda bellek tasarrufu
        file_info["file_content"] = None
        gc.collect()
        
        return (chunk_count, file_name, True)
    
    except Exception as e:
        # Status güncelle → failed
        log_error(
            f"Background processing hatası ({file_name}): {str(e)}",
            "rag", error_detail=str(e)
        )
        try:
            if conn:
                conn.rollback()
                cur2 = conn.cursor()
                cur2.execute(
                    "UPDATE uploaded_files SET status = 'failed' WHERE id = %s",
                    (file_info["file_id"],)
                )
                conn.commit()
        except Exception:
            pass
        return (0, file_name, False)
    finally:
        if conn:
            conn.close()


async def _process_files_background(
    files_to_process: list,
    user_id: int,
    maturity_score_map: dict = None
):
    """
    Ağır dosya işleme işlemlerini arkaplanda çalıştırır.
    İşlem bitince WebSocket ile kullanıcıya bildirim gönderir.
    
    v2.39.0: Asenkron upload support
    v2.40.0: Maturity score kaydı her dosya için ayrı, üst-seviye exception guard
    v2.43.0: CPU-bound işlemler run_in_executor ile thread pool'da çalışır
    
    Args:
        files_to_process: İşlenecek dosya bilgileri listesi
        user_id: Kullanıcı ID
        maturity_score_map: {file_id: score} dict (opsiyonel)
    """
    from app.core.websocket_manager import ws_manager
    
    log_system_event(
        "INFO",
        f"Background processing başladı: {len(files_to_process)} dosya, user_id={user_id}",
        "rag",
        user_id=user_id
    )
    
    total_chunks = 0
    processed_count = 0
    failed_files = []
    
    if maturity_score_map is None:
        maturity_score_map = {}
    
    loop = asyncio.get_event_loop()
    
    try:
        total_files = len(files_to_process)
        for idx, file_info in enumerate(files_to_process):
            # v2.43.0: CPU-bound işlemi thread pool'da çalıştır
            chunk_count, file_name, success = await loop.run_in_executor(
                _file_processing_executor,
                functools.partial(
                    _process_single_file_sync,
                    file_info,
                    user_id,
                    maturity_score_map,
                )
            )
            
            if success:
                total_chunks += chunk_count
                processed_count += 1
            else:
                failed_files.append(file_name)
            
            # 🔔 Dosya bazlı progress bildirimi
            try:
                await ws_manager.send_to_user(user_id, {
                    "type": "rag_upload_progress",
                    "current": idx + 1,
                    "total": total_files,
                    "file_name": file_name,
                    "success": success,
                    "chunk_count": chunk_count if success else 0,
                    "percentage": round(((idx + 1) / total_files) * 100),
                    "message": f"{idx + 1}/{total_files} dosya işlendi: {file_name}"
                })
            except Exception:
                pass  # Progress bildirimi kritik değil
                    
    except Exception as outer_err:
        log_error(
            f"Background processing üst-seviye hata (user_id={user_id}): {outer_err}",
            "rag", error_detail=str(outer_err)
        )
    
    # ═══════════════════════════════════════════════
    # 🔔 WebSocket ile kullanıcıya bildirim gönder
    # ═══════════════════════════════════════════════
    file_names = [f["file_name"] for f in files_to_process]
    
    try:
        if failed_files:
            # Kısmi başarı veya tamamen başarısız
            notification_type = "rag_upload_failed" if processed_count == 0 else "rag_upload_complete"
            await ws_manager.send_to_user(user_id, {
                "type": notification_type,
                "file_names": file_names,
                "processed_count": processed_count,
                "failed_files": failed_files,
                "total_chunks": total_chunks,
                "message": f"{processed_count}/{len(files_to_process)} dosya işlendi, {len(failed_files)} hata"
            })
            log_system_event(
                "WARNING",
                f"Asenkron upload kısmen başarılı: {processed_count}/{len(files_to_process)} dosya, {total_chunks} chunk",
                "rag",
                user_id=user_id
            )
        else:
            # Tamamen başarılı
            await ws_manager.send_to_user(user_id, {
                "type": "rag_upload_complete",
                "file_names": file_names,
                "processed_count": processed_count,
                "total_chunks": total_chunks,
                "message": f"{processed_count} dosya ve {total_chunks} chunk başarıyla işlendi"
            })
            log_system_event(
                "INFO",
                f"Asenkron upload tamamlandı: {processed_count} dosya, {total_chunks} chunk",
                "rag",
                user_id=user_id
            )
    except Exception as ws_err:
        log_error(f"WebSocket bildirim gönderilemedi (user_id={user_id}): {ws_err}", "rag")


def _update_chunk_image_refs(cursor, file_id: int, images, image_ids: list):
    """
    Chunk metadata'larını image_ids ile günceller.
    v2.38.0: Heading bazlı eşleştirme — görselin context_heading'i ile
    chunk'ın metadata.heading'ini eşleştirir (chunk_index yerine).
    
    v2.40.1: ExtractedImage dataclass attribute erişimi düzeltmesi.
    Görseller hem heading eşleştirmesi hem de chunk_index ile eşleştirilir.
    """
    from app.services.logging_service import log_system_event as _log
    
    if not image_ids:
        return

    matched_ids = set()
    
    for img, img_id in zip(images, image_ids):
        # ExtractedImage dataclass → attribute access (dict .get() değil!)
        heading = getattr(img, "context_heading", "") or ""
        chunk_idx = getattr(img, "context_chunk_index", None)
        
        if not heading:
            continue

        # 1. Heading eşleştirmesi (tam match)
        cursor.execute(
            """
            UPDATE rag_chunks
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{image_ids}',
                (COALESCE(metadata->'image_ids', '[]'::jsonb) || %s::jsonb)
            )
            WHERE file_id = %s
              AND metadata->>'heading' = %s
            RETURNING id
            """,
            (f'[{img_id}]', file_id, heading)
        )
        if cursor.fetchone():
            matched_ids.add(img_id)
            continue
        
        # 2. Partial heading eşleştirmesi (heading içerme)
        cursor.execute(
            """
            UPDATE rag_chunks
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{image_ids}',
                (COALESCE(metadata->'image_ids', '[]'::jsonb) || %s::jsonb)
            )
            WHERE file_id = %s
              AND metadata->>'heading' ILIKE %s
              AND (metadata->'image_ids' IS NULL OR NOT metadata->'image_ids' @> %s::jsonb)
            RETURNING id
            """,
            (f'[{img_id}]', file_id, f'%{heading[:60]}%', f'[{img_id}]')
        )
        if cursor.fetchone():
            matched_ids.add(img_id)
            continue
        
        # 3. Chunk index eşleştirmesi (sayfa bazlı fallback)
        if chunk_idx is not None:
            cursor.execute(
                """
                UPDATE rag_chunks
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{image_ids}',
                    (COALESCE(metadata->'image_ids', '[]'::jsonb) || %s::jsonb)
                )
                WHERE file_id = %s
                  AND chunk_index = %s
                  AND (metadata->'image_ids' IS NULL OR NOT metadata->'image_ids' @> %s::jsonb)
                RETURNING id
                """,
                (f'[{img_id}]', file_id, chunk_idx, f'[{img_id}]')
            )
            if cursor.fetchone():
                matched_ids.add(img_id)

    # Eşleşmeyen görselleri ilk chunk'a ata (son çare fallback)
    unmatched = [iid for iid in image_ids if iid not in matched_ids]
    for img_id in unmatched:
        cursor.execute(
            """
            UPDATE rag_chunks
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{image_ids}',
                (COALESCE(metadata->'image_ids', '[]'::jsonb) || %s::jsonb)
            )
            WHERE file_id = %s
              AND chunk_index = 0
              AND (metadata->'image_ids' IS NULL OR NOT metadata->'image_ids' @> %s::jsonb)
            """,
            (f'[{img_id}]', file_id, f'[{img_id}]')
        )
    
    _log("INFO", f"Dosya {file_id}: {len(matched_ids)}/{len(image_ids)} görsel chunk'a eşleştirildi", "rag_upload")


@router.post("/retry-file/{file_id}")
async def retry_file_processing(
    file_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Başarısız (status='failed') dosyayı tekrar işleme alır.
    Mevcut chunk'ları temizler ve yeniden background processing başlatır.
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Dosyanın varlığını ve durumunu kontrol et
        cur.execute(
            "SELECT id, file_name, file_type, status, company_id, maturity_score FROM rag_files WHERE id = %s",
            (file_id,)
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Dosya bulunamadı")
        
        db_id, file_name, file_type, status, company_id, maturity_score = row
        
        if status not in ('failed', 'error'):
            raise HTTPException(
                status_code=400,
                detail="Sadece başarısız dosyalar yeniden işlenebilir"
            )
        
        # Dosya içeriğini al
        cur.execute("SELECT file_data FROM rag_files WHERE id = %s", (file_id,))
        file_data_row = cur.fetchone()
        if not file_data_row or not file_data_row[0]:
            raise HTTPException(status_code=400, detail="Dosya verisi bulunamadı")
        
        file_data = bytes(file_data_row[0])
        
        # Mevcut chunk'ları temizle
        cur.execute("DELETE FROM rag_chunks WHERE file_id = %s", (file_id,))
        
        # Status'ü 'processing' yap
        cur.execute(
            "UPDATE rag_files SET status = 'processing', error_message = NULL WHERE id = %s",
            (file_id,)
        )
        conn.commit()
        
        _log("INFO", f"Retry başlatıldı: {file_name} (id={file_id})", "rag_upload")
        
        # Mevcut maturity_score'u koru
        maturity_map = None
        if maturity_score is not None:
            maturity_map = {file_name: maturity_score}
        
        # Background task olarak yeniden işle
        file_info = {
            "file_id": db_id,
            "file_name": file_name,
            "file_type": file_type,
            "file_data": file_data,
            "company_id": company_id
        }
        
        asyncio.ensure_future(
            _process_files_background(
                [file_info],
                current_user["user_id"],
                maturity_score_map=maturity_map
            )
        )
        
        return {
            "status": "processing",
            "message": f"{file_name} yeniden işleniyor...",
            "file_id": file_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Retry hatası (file_id={file_id})", "rag", error_detail=str(e))
        raise HTTPException(status_code=500, detail="Yeniden işleme başlatılamadı")
    finally:
        conn.close()
