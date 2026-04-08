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
import hashlib
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
    - CSV → csv_processor
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
            
            # v3.3.0: Boş dosya kontrolü
            if file_size == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Boş dosya yüklenemez: {f.filename}"
                )
            
            if file_size > max_size_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dosya cok buyuk: {f.filename} ({file_size // (1024*1024)}MB). "
                           f"Maksimum: {settings.MAX_FILE_SIZE_MB}MB"
                )

            # MIME type
            mime_type = f.content_type or "application/octet-stream"
            
            # v3.3.0: MIME type - uzantı uyumluluk kontrolü
            MIME_EXT_MAP = {
                '.pdf': ['application/pdf'],
                '.docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 
                          'application/octet-stream', 'application/zip'],
                '.doc': ['application/msword', 'application/octet-stream'],
                '.xlsx': ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
                          'application/octet-stream', 'application/zip'],
                '.xls': ['application/vnd.ms-excel', 'application/octet-stream'],
                '.pptx': ['application/vnd.openxmlformats-officedocument.presentationml.presentation', 
                          'application/octet-stream', 'application/zip'],
                '.csv': ['text/csv', 'text/plain', 'application/octet-stream'],
                '.txt': ['text/plain', 'application/octet-stream'],
            }
            expected_mimes = MIME_EXT_MAP.get(ext, [])
            if expected_mimes and mime_type not in expected_mimes:
                log_system_event("WARNING", 
                     f"MIME uyumsuzluğu: {f.filename} uzantısı={ext}, mime={mime_type}", 
                     "rag_upload")
            
            # v3.3.0: Dosya bütünlüğü quick-check (magic bytes)
            MAGIC_BYTES = {
                '.pdf': b'%PDF',
                '.docx': b'PK',   # ZIP tabanlı
                '.xlsx': b'PK',   # ZIP tabanlı
                '.pptx': b'PK',   # ZIP tabanlı
                '.xls': b'\xd0\xcf\x11\xe0',  # OLE2
            }
            expected_magic = MAGIC_BYTES.get(ext)
            if expected_magic and not content[:len(expected_magic)].startswith(expected_magic):
                raise HTTPException(
                    status_code=400,
                    detail=f"Bozuk veya geçersiz dosya: {f.filename}. "
                           f"Dosya içeriği {ext} formatıyla uyuşmuyor."
                )

            # v3.3.0 [A4]: Dosya versiyonlama — silmek yerine soft-delete
            file_hash = hashlib.md5(content[:1024*1024]).hexdigest()
            
            # Mevcut aktif versiyonu bul (varsa)
            cur.execute(
                "SELECT MAX(file_version) as max_ver FROM uploaded_files WHERE file_name = %s AND is_active = TRUE",
                (f.filename,)
            )
            ver_row = cur.fetchone()
            next_version = (ver_row["max_ver"] or 0) + 1 if ver_row and ver_row["max_ver"] else 1
            
            # Eski versiyonları deaktive et ve chunk'larını temizle
            cur.execute(
                """
                UPDATE uploaded_files SET is_active = FALSE 
                WHERE file_name = %s AND is_active = TRUE
                RETURNING id
                """,
                (f.filename,)
            )
            old_ids = [r["id"] for r in cur.fetchall()]
            if old_ids:
                placeholders = ','.join(['%s'] * len(old_ids))
                cur.execute(f"DELETE FROM rag_chunks WHERE file_id IN ({placeholders})", old_ids)

            # Dosyayı PostgreSQL'e kaydet — status='processing'
            cur.execute(
                """
                INSERT INTO uploaded_files (file_name, file_type, file_size_bytes, file_content, mime_type, uploaded_by, status, company_id, file_version, is_active, file_hash)
                VALUES (%s, %s, %s, %s, %s, %s, 'processing', %s, %s, TRUE, %s)
                RETURNING id
                """,
                (f.filename, ext, file_size, content, mime_type, current_user["id"], company_id, next_version, file_hash),
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
            # v3.4.4: file_content bellek optimizasyonu — icerik DB'den okunacak
            files_to_process.append({
                "file_id": file_id,
                "file_name": f.filename,
                "file_type": ext,
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
        
        # v3.4.4: Dosya içeriğini DB'den oku (bellek optimizasyonu)
        cur.execute("SELECT file_content FROM uploaded_files WHERE id = %s", (file_info["file_id"],))
        content_row = cur.fetchone()
        if not content_row or not content_row["file_content"]:
            raise ValueError(f"Dosya içeriği DB'de bulunamadı (id={file_info['file_id']})")
        file_content = bytes(content_row["file_content"])
        
        # 1. Processor ile dosyayı parse et
        processor = get_processor_for_extension(file_info["file_type"])
        if not processor:
            raise ValueError(f"İşlemci bulunamadı: {file_info['file_type']}")
        
        file_obj = io.BytesIO(file_content)
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
            
            # v3.4.7 Issue 15: Eski görselleri temizle (re-upload durumunda)
            cur.execute(
                "DELETE FROM document_images WHERE file_id = %s",
                (file_info["file_id"],)
            )
            
            extracted_images = img_extractor.extract(
                file_content, file_info["file_type"]
            )
            if extracted_images:
                image_ids, saved_images = img_extractor.save_to_db(
                    extracted_images, file_info["file_id"], cursor=cur
                )
                if image_ids:
                    _update_chunk_image_refs(
                        cur, file_info["file_id"],
                        saved_images, image_ids
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
        
        # 7. 🧹 v2.42.0 + v3.4.4: Memory cleanup — büyük dosyalarda bellek tasarrufu
        del file_content
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
        
        # v3.3.0 [A7]: Paralel dosya processing — asyncio.gather ile concurrent çalıştır
        # ThreadPoolExecutor max_workers=2 kısıtı paralelliği doğal olarak sınırlar
        
        async def _process_one(idx, file_info):
            """Tek dosya işle ve progress bildir."""
            chunk_count, file_name, success = await loop.run_in_executor(
                _file_processing_executor,
                functools.partial(
                    _process_single_file_sync,
                    file_info,
                    user_id,
                    maturity_score_map,
                )
            )
            
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
            
            return chunk_count, file_name, success
        
        # Tüm dosyaları eşzamanlı başlat (thread pool otomatik sıraya alır)
        results = await asyncio.gather(
            *[_process_one(idx, fi) for idx, fi in enumerate(files_to_process)],
            return_exceptions=True
        )
        
        for r in results:
            if isinstance(r, Exception):
                log_error(f"Paralel processing exception: {r}", "rag")
                failed_files.append(str(r)[:80])
                continue
            chunk_count, file_name, success = r
            if success:
                total_chunks += chunk_count
                processed_count += 1
            else:
                failed_files.append(file_name)
                    
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
    v3.4.7: Chunk metadata'larını image_ids ile günceller.
    
    Üç katmanlı eşleştirme (tüm dosya türlerini destekler):
    
    Strateji A — Sayfa Bazlı (PDF):
      1. Görselin page_number = Chunk metadata.page → aynı sayfadaki chunk'a ata
      2. Aynı sayfada birden fazla chunk varsa heading eşleşmesi + Y pozisyonu ile seçim (v3.4.7)
    
    Strateji B — Heading Bazlı (DOCX/PPTX — sayfa bilgisi yoksa):
      1. Görselin context_heading = Chunk metadata.heading → heading eşleşmesi
      2. Tam eşleşme > substring eşleşme öncelikli
    
    Strateji C — Nearby Text Keyword Overlap (v3.4.7, Sorun 6):
      A ve B başarısız olursa nearby_text ile chunk metin benzerliği hesaplanır
    
    Eşleşme yoksa → atanmaz (yanlış eşleşme yerine eksik tercih edilir)
    
    Ek: OCR metni eşleşen chunk'ların metadata'sına injection edilir (Sorun 10)
    """
    from app.services.logging_service import log_system_event as _log
    import re
    
    if not image_ids:
        return

    # --- Yardımcı: Heading normalizasyonu ---
    def _normalize(text: str) -> str:
        t = (text or "").strip().lower()
        t = re.sub(r'^(sayfa\s*\d+\s*[-–:]*\s*)', '', t)
        t = re.sub(r'^(\d+[.)]\s*)', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t
    
    # --- Yardımcı: Keyword overlap hesapla ---
    def _keyword_overlap(text_a: str, text_b: str) -> float:
        """v3.4.7: İki metin arasında keyword overlap oranı hesapla (0.0-1.0)"""
        if not text_a or not text_b:
            return 0.0
        words_a = set(w.lower() for w in text_a.split() if len(w) >= 3)
        words_b = set(w.lower() for w in text_b.split() if len(w) >= 3)
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / max(len(words_a), 1)

    # --- Tüm chunk'ları ön-yükle ---
    # v3.4.7: chunk_text de alınıyor (Strateji C için)
    cursor.execute(
        """
        SELECT id, chunk_index, 
               metadata->>'heading' as heading, 
               COALESCE(metadata->>'page', metadata->>'slide') as page,
               LEFT(chunk_text, 500) as chunk_text_preview
        FROM rag_chunks 
        WHERE file_id = %s 
        ORDER BY chunk_index
        """,
        (file_id,)
    )
    chunk_rows = cursor.fetchall()
    
    if not chunk_rows:
        _log("WARNING", f"Dosya {file_id}: Chunk bulunamadı, görsel eşleştirme atlandı", "rag_upload")
        return
    
    # Sayfa → chunk listesi mapping (PDF)
    page_to_chunks = {}
    # Heading → chunk listesi mapping (DOCX/PPTX fallback)
    heading_to_chunks = {}
    has_page_data = False
    
    for cr in chunk_rows:
        heading_norm = _normalize(cr["heading"] or "")
        entry = {
            "id": cr["id"],
            "chunk_index": cr["chunk_index"],
            "heading_norm": heading_norm,
            "chunk_text_preview": cr.get("chunk_text_preview", "") or "",
        }
        
        # Sayfa bilgisi varsa page mapping'e ekle
        page = cr["page"]
        if page is not None:
            try:
                page_num = int(page)
                page_to_chunks.setdefault(page_num, []).append(entry)
                has_page_data = True
            except (ValueError, TypeError):
                pass
        
        # Heading mapping'e her zaman ekle (DOCX/PPTX fallback)
        if heading_norm:
            heading_to_chunks.setdefault(heading_norm, []).append(entry)
    
    matched_count = 0
    # v3.4.7 Issue 10: OCR text injection için image_id → chunk_id mapping'i tut
    chunk_image_ocr_map = {}  # chunk_id → [ocr_text_1, ocr_text_2, ...]
    
    for img, img_id in zip(images, image_ids):
        best_chunk_id = None
        
        # ═══════════════════════════════════════════════
        # Strateji A: Sayfa Bazlı Eşleştirme (PDF)
        # ═══════════════════════════════════════════════
        if has_page_data:
            img_page = getattr(img, "page_number", -1)
            if img_page < 0:
                alt = getattr(img, "alt_text", "") or ""
                m = re.search(r'Sayfa\s+(\d+)', alt)
                if m:
                    img_page = int(m.group(1))
            
            if img_page >= 0:
                candidates = page_to_chunks.get(img_page, [])
                if candidates:
                    if len(candidates) == 1:
                        best_chunk_id = candidates[0]["id"]
                    else:
                        # Birden fazla chunk aynı sayfada → heading eşleşmesi ile seç
                        img_heading_norm = _normalize(getattr(img, "context_heading", "") or "")
                        
                        if img_heading_norm:
                            best_match_score = 0
                            for c in candidates:
                                if c["heading_norm"]:
                                    if img_heading_norm == c["heading_norm"]:
                                        best_chunk_id = c["id"]
                                        break
                                    elif (img_heading_norm in c["heading_norm"] or 
                                          c["heading_norm"] in img_heading_norm):
                                        if 0.8 > best_match_score:
                                            best_match_score = 0.8
                                            best_chunk_id = c["id"]
                        
                        # v3.4.7 Issue 7: Heading eşleşmesi başarısız → chunk_index ile
                        # en yakın chunk'a ata (Y pozisyonu proxy olarak chunk_index kullan)
                        if best_chunk_id is None and candidates:
                            # nearby_text overlap ile en iyi eşleşmeyi bul
                            img_nearby = getattr(img, "nearby_text", "") or ""
                            if img_nearby:
                                best_overlap = 0.0
                                for c in candidates:
                                    ov = _keyword_overlap(img_nearby, c["chunk_text_preview"])
                                    if ov > best_overlap:
                                        best_overlap = ov
                                        best_chunk_id = c["id"]
                            # Hala None ise → chunk_index bazlı (ortadaki chunk)
                            if best_chunk_id is None:
                                mid_idx = len(candidates) // 2
                                best_chunk_id = candidates[mid_idx]["id"]
        
        # ═══════════════════════════════════════════════
        # Strateji B: Heading Bazlı Eşleştirme (DOCX/PPTX)
        # Sayfa eşleşmesi bulunamadıysa heading ile dene
        # ═══════════════════════════════════════════════
        if best_chunk_id is None:
            img_heading = getattr(img, "context_heading", "") or ""
            img_heading_norm = _normalize(img_heading)
            
            if img_heading_norm:
                # 1. Tam eşleşme
                if img_heading_norm in heading_to_chunks:
                    best_chunk_id = heading_to_chunks[img_heading_norm][0]["id"]
                else:
                    # 2. Substring eşleşme (en kısa heading — en spesifik)
                    best_match_len = float('inf')
                    for h_norm, chunks_list in heading_to_chunks.items():
                        if (img_heading_norm in h_norm or h_norm in img_heading_norm):
                            if len(h_norm) < best_match_len:
                                best_match_len = len(h_norm)
                                best_chunk_id = chunks_list[0]["id"]
        
        # ═══════════════════════════════════════════════
        # v3.4.7 Strateji C: Nearby Text Keyword Overlap (Sorun 6)
        # A ve B başarısız olursa, nearby_text ile chunk metni karşılaştır
        # ═══════════════════════════════════════════════
        if best_chunk_id is None:
            img_nearby = getattr(img, "nearby_text", "") or ""
            if img_nearby and len(img_nearby) >= 10:
                best_overlap = 0.0
                best_overlap_id = None
                for cr in chunk_rows:
                    ov = _keyword_overlap(img_nearby, cr.get("chunk_text_preview", ""))
                    if ov >= 0.3 and ov > best_overlap:  # Min %30 overlap
                        best_overlap = ov
                        best_overlap_id = cr["id"]
                if best_overlap_id is not None:
                    best_chunk_id = best_overlap_id
                    _log("DEBUG", f"Dosya {file_id}: Görsel {img_id} Strateji C ile eşleşti (overlap={best_overlap:.2f})", "rag_upload")
        
        # Eşleşme bulunamadıysa → atanmaz
        if best_chunk_id is None:
            continue
        
        # Chunk'a image_id ekle
        cursor.execute(
            """
            UPDATE rag_chunks
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{image_ids}',
                (COALESCE(metadata->'image_ids', '[]'::jsonb) || %s::jsonb)
            )
            WHERE id = %s
              AND (metadata->'image_ids' IS NULL OR NOT metadata->'image_ids' @> %s::jsonb)
            """,
            (f'[{img_id}]', best_chunk_id, f'[{img_id}]')
        )
        matched_count += 1
        
        # v3.4.7 Issue 10: OCR text'i topla (sonra chunk metadata'ya injection)
        ocr_text = getattr(img, "ocr_text", "") or ""
        if not ocr_text:
            # DB'den OCR text'i çek (save_to_db sonrası doldurulmuş olabilir)
            try:
                cursor.execute("SELECT ocr_text FROM document_images WHERE id = %s", (img_id,))
                ocr_row = cursor.fetchone()
                if ocr_row and ocr_row.get("ocr_text"):
                    ocr_text = ocr_row["ocr_text"].strip()
            except Exception:
                pass
        if ocr_text and len(ocr_text.strip()) > 5:
            chunk_image_ocr_map.setdefault(best_chunk_id, []).append(ocr_text.strip())
    
    # v3.4.7 Issue 10: OCR text injection — eşleşen chunk'ların metadata'sına ocr_texts ekle
    # BM25 aramalarda görsel içindeki metin de aranabilir olur
    ocr_injected = 0
    for chunk_id, ocr_texts in chunk_image_ocr_map.items():
        combined_ocr = " | ".join(ocr_texts)[:1000]  # Max 1000 char
        try:
            cursor.execute(
                """
                UPDATE rag_chunks
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{ocr_texts}',
                    %s::jsonb
                )
                WHERE id = %s
                """,
                (f'"{combined_ocr}"', chunk_id)
            )
            ocr_injected += 1
        except Exception:
            pass
    
    _log(
        "INFO", 
        f"Dosya {file_id}: {matched_count}/{len(image_ids)} görsel chunk'a eşleştirildi "
        f"({'sayfa' if has_page_data else 'heading'} bazlı)"
        f"{f', {ocr_injected} chunk OCR zenginleştirildi' if ocr_injected else ''}", 
        "rag_upload"
    )


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
            "SELECT id, file_name, file_type, status, company_id, maturity_score FROM uploaded_files WHERE id = %s",
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
        cur.execute("SELECT file_content FROM uploaded_files WHERE id = %s", (file_id,))
        file_data_row = cur.fetchone()
        if not file_data_row or not file_data_row[0]:
            raise HTTPException(status_code=400, detail="Dosya verisi bulunamadı")
        
        # v3.4.5: file_data artık background'da DB'den okunuyor, retry'da gerekmez
        
        # Mevcut chunk'ları temizle
        cur.execute("DELETE FROM rag_chunks WHERE file_id = %s", (file_id,))
        
        # Status'ü 'processing' yap
        cur.execute(
            "UPDATE uploaded_files SET status = 'processing' WHERE id = %s",
            (file_id,)
        )
        conn.commit()
        
        log_system_event("INFO", f"Retry başlatıldı: {file_name} (id={file_id})", "rag_upload")
        
        # Mevcut maturity_score'u koru
        maturity_map = None
        if maturity_score is not None:
            maturity_map = {db_id: maturity_score}
        
        # Background task olarak yeniden işle
        # v3.4.4: file_content gönderilmiyor — background'da DB'den okunuyor
        file_info = {
            "file_id": db_id,
            "file_name": file_name,
            "file_type": file_type,
            "company_id": company_id
        }
        
        asyncio.ensure_future(
            _process_files_background(
                [file_info],
                current_user["id"],
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
