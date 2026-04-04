"""
VYRA L1 Support API - RAG Enhancement Routes
=============================================
Doküman iyileştirme (CatBoost + LLM) endpoint'leri.

Author: VYRA AI Team
Version: 1.2.0 (v3.3.0)
"""

import os
import time
import asyncio
import threading
from typing import Dict, Any
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from app.api.routes.auth import get_current_user

from app.services.document_enhancer import (
    DocumentEnhancer, get_enhanced_file_path, cleanup_enhanced_file
)
from app.services.logging_service import log_system_event, log_error, log_warning


router = APIRouter()

# Selective download için session verilerini sakla
_session_data: dict = {}  # session_id → {"original_content": bytes, ..., "_created_at": float}

# v3.2.1: Session TTL — 30 dakika sonra otomatik temizleme
_SESSION_TTL_SECONDS = 1800  # 30 dakika


def _cleanup_expired_sessions() -> None:
    """TTL'i dolmuş session'ları temizler — memory leak önleme."""
    now = time.time()
    expired = [sid for sid, data in _session_data.items()
               if now - data.get("_created_at", 0) > _SESSION_TTL_SECONDS]
    for sid in expired:
        cleanup_enhanced_file(sid)
        _session_data.pop(sid, None)
    if expired:
        log_system_event("INFO", f"{len(expired)} expired session temizlendi", "rag_enhance")

# Desteklenen dosya tipleri
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.csv'}


def _detect_download_format(file_path: str, session_id: str) -> tuple:
    """Dosya uzantısına göre indirme adı ve MIME type döndürür."""
    ext = os.path.splitext(file_path)[1].lower()
    _mime_map = {
        ".pdf": ("application/pdf", "pdf"),
        ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        ".xls": ("application/vnd.ms-excel", "xls"),
        ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
    }
    if ext in _mime_map:
        media, fmt = _mime_map[ext]
        return f"iyilestirilmis_{session_id}.{fmt}", media
    # Varsayılan: DOCX
    return (
        f"iyilestirilmis_{session_id}.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@router.post("/enhance-document")
async def enhance_document(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Dokümanı analiz edip CatBoost + LLM ile iyileştirme önerileri oluşturur.
    
    Akış:
    1. Dosyayı oku
    2. Maturity analizi çalıştır
    3. CatBoost ile chunk priority belirle
    4. LLM ile düşük kaliteli bölümleri iyileştir
    5. İyileştirilmiş DOCX oluştur
    
    Returns:
        {sections, catboost_summary, session_id, ...}
    """
    
    log_system_event("INFO", f"Enhancement isteği: {file.filename}", "rag_enhance")
    
    # Dosya tipi kontrolü
    file_name = file.filename or "unknown"
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya formatı: {ext}. Desteklenen: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    
    try:
        # Dosya içeriğini oku
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(status_code=400, detail="Dosya boş.")
        
        # Enhancement pipeline (senkron LLM call → thread pool'da çalıştır)
        loop = asyncio.get_event_loop()
        enhancer = DocumentEnhancer()
        
        # v3.3.0 [C5]: WebSocket progress callback — thread-safe
        # run_in_executor içinde senkron çalışır, async WS'e bridge yapar
        from app.core.websocket_manager import ws_manager
        _loop = loop
        _user_id = None
        try:
            _user_id = current_user.get("id") if hasattr(current_user, "get") else None
        except Exception:
            pass
        
        def _progress_callback(current, total, heading, status):
            """Thread pool'dan WebSocket'e progress gönderir."""
            if not _user_id:
                return
            status_labels = {
                "processing": f"Bölüm {current}/{total} iyileştiriliyor: {heading[:40]}...",
                "skipped": f"Bölüm {current}/{total} atlandı (yeterli kalite)",
                "error": f"Bölüm {current}/{total} LLM hatası",
            }
            msg = {
                "type": "enhancement_progress",
                "current": current,
                "total": total,
                "heading": (heading or "")[:60],
                "status": status,
                "percentage": round((current / total) * 100),
                "message": status_labels.get(status, f"Bölüm {current}/{total}")
            }
            try:
                asyncio.run_coroutine_threadsafe(ws_manager.send_to_user(_user_id, msg), _loop)
            except Exception:
                pass
        
        def _run_pipeline():
            maturity_result = _run_maturity_analysis(file_content, file_name)
            return enhancer.analyze_and_enhance(
                file_content=file_content,
                file_name=file_name,
                maturity_result=maturity_result,
                progress_callback=_progress_callback
            ), maturity_result
        
        result, maturity_result = await loop.run_in_executor(None, _run_pipeline)
        
        if result.error:
            raise HTTPException(status_code=500, detail=result.error)
        
        # Session verilerini sakla (selective download için)
        _cleanup_expired_sessions()  # v3.2.1: Önce eski session'ları temizle
        _session_data[result.session_id] = {
            "original_content": file_content,
            "file_type": ext,
            "file_name": file_name,
            "sections": result.sections,
            "maturity_score": maturity_result.get("total_score"),
            "_created_at": time.time()
        }
        
        # v3.3.0 [C2]: Enhancement geçmişini DB'ye kaydet
        try:
            from app.core.db import get_db_conn
            import hashlib
            import json as _json
            file_hash = hashlib.md5(file_content[:1024*1024]).hexdigest()
            sections_summary = []
            for s in result.sections:
                sections_summary.append({
                    "heading": s.heading,
                    "change_type": s.change_type,
                    "integrity_score": getattr(s, "integrity_score", None),
                    "priority": s.priority
                })
            
            conn = get_db_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO enhancement_history 
                    (file_name, file_hash, original_file_type, session_id,
                     user_id, total_sections, enhanced_sections, maturity_score_before, sections_summary)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        file_name, file_hash, ext, result.session_id,
                        current_user.get("id"),
                        result.total_sections, result.enhanced_count,
                        maturity_result.get("total_score"),
                        _json.dumps(sections_summary, ensure_ascii=False)
                    )
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as hist_err:
            log_system_event("WARNING", f"Enhancement history kayıt hatası: {hist_err}", "rag_enhance")
        
        return JSONResponse(content=enhancer.to_dict(result))
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Enhancement endpoint hatası: {e}", "rag_enhance")
        raise HTTPException(status_code=500, detail="İyileştirme sırasında bir hata oluştu.")


@router.get("/download-enhanced/{session_id}")
async def download_enhanced(
    session_id: str,
    sections: str = Query(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    İyileştirilmiş DOCX dosyasını indirir.
    
    Args:
        session_id: enhance-document yanıtındaki session_id
        sections: Opsiyonel — virgülle ayrılmış onaylanan section index'leri (örn: "0,2,3")
                  Verilmezse tüm iyileştirmeler uygulanır.
    """
    
    # Selective download: Kullanıcı belirli bölümler seçmişse yeniden oluştur
    if sections is not None and session_id in _session_data:
        try:
            approved_indexes = [int(x.strip()) for x in sections.split(",") if x.strip()]
            data = _session_data[session_id]
            
            enhancer = DocumentEnhancer()
            selective_path = enhancer.generate_selective_docx(
                original_content=data["original_content"],
                sections=data["sections"],
                approved_indexes=approved_indexes,
                session_id=session_id,
                file_type=data["file_type"]
            )
            
            if selective_path and os.path.exists(selective_path):
                # Dosya formatını belirle
                download_name, media = _detect_download_format(selective_path, session_id)
                
                return FileResponse(
                    path=selective_path,
                    filename=download_name,
                    media_type=media
                )
        except Exception as e:
            log_error(f"Selective download hatası: {e}", "rag_enhance")
            # Fallback: normal download
    
    # Normal download (tüm iyileştirmeler veya fallback)
    file_path = get_enhanced_file_path(session_id)
    
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="İyileştirilmiş dosya bulunamadı. Lütfen önce dokümanı analiz edin."
        )
    
    try:
        download_name, media = _detect_download_format(file_path, session_id)
        
        return FileResponse(
            path=file_path,
            filename=download_name,
            media_type=media
        )
    except Exception as e:
        log_error(f"Download hatası: {e}", "rag_enhance")
        raise HTTPException(status_code=500, detail="Dosya indirme sırasında bir hata oluştu.")


@router.post("/upload-enhanced/{session_id}")
async def upload_enhanced_to_rag(
    session_id: str,
    sections: str = Query(default=None),
    org_ids: str = Query(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    İyileştirilmiş DOCX'i bilgi tabanına (RAG) yükler.
    
    Akış:
    1. Session'dan onaylanan section'ları al
    2. Selective DOCX oluştur
    3. Mevcut RAG upload pipeline ile DB'ye yükle (aynı isim → sil-yaz)
    4. Embedding'leri oluştur
    5. Session temizle
    """
    import io as _io
    from app.core.db import get_db_conn
    from app.services.rag_service import get_rag_service
    from app.services.document_processors import get_processor_for_extension
    from app.services.rag.topic_extraction import extract_and_save_topics
    
    if session_id not in _session_data:
        raise HTTPException(status_code=404, detail="Session bulunamadı. Lütfen önce dokümanı analiz edin.")
    
    data = _session_data[session_id]
    file_name = data.get("file_name", f"enhanced_{session_id}.docx")
    
    log_system_event("INFO", f"RAG yükleme isteği (enhanced): {file_name}", "rag_enhance")
    
    try:
        enhancer = DocumentEnhancer()
        
        if sections is not None:
            approved_indexes = [int(x.strip()) for x in sections.split(",") if x.strip()]
        else:
            # Tüm section'lar onaylı
            approved_indexes = [s.section_index for s in data["sections"]]
        
        # Orijinal dosya tipini belirle
        orig_file_type = data.get("file_type", "DOCX").upper().replace(".", "")
        
        # XLSX/PPTX gibi non-DOCX formatlar: orijinal dosyayı koru
        # RAG chunk'ları enhanced text'ten oluşturulacak
        if orig_file_type in ("XLSX", "XLS", "PPTX", "PPT"):
            # Orijinal dosya binary'si korunur
            file_content_bytes = data["original_content"]
            file_size = len(file_content_bytes)
            
            ext_map = {
                "XLSX": (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "XLS": (".xls", "application/vnd.ms-excel"),
                "PPTX": (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
                "PPT": (".ppt", "application/vnd.ms-powerpoint"),
            }
            upload_ext, upload_mime = ext_map.get(orig_file_type, (".xlsx", "application/octet-stream"))
            upload_name = file_name
            
            # Uzantıyı düzelt (orijinal adı koru)
            if not upload_name.lower().endswith(upload_ext):
                upload_name = os.path.splitext(upload_name)[0] + upload_ext
            
            log_system_event(
                "INFO",
                f"Orijinal format korunuyor: {orig_file_type} → {upload_name} "
                f"(chunk'lar enhanced text'ten oluşturulacak)",
                "rag_enhance"
            )
        else:
            # DOCX, PDF, TXT: enhanced DOCX/PDF oluştur
            docx_path = enhancer.generate_selective_docx(
                original_content=data["original_content"],
                sections=data["sections"],
                approved_indexes=approved_indexes,
                session_id=session_id,
                file_type=data["file_type"]
            )
            
            if not docx_path or not os.path.exists(docx_path):
                raise HTTPException(status_code=500, detail="İyileştirilmiş dosya oluşturulamadı.")
            
            # Oluşturulan dosyayı oku (PDF veya DOCX olabilir)
            with open(docx_path, "rb") as f:
                file_content_bytes = f.read()
            
            file_size = len(file_content_bytes)
            
            # Dosya formatını belirle
            is_pdf = docx_path.lower().endswith('.pdf')
            if is_pdf:
                upload_ext = '.pdf'
                upload_mime = 'application/pdf'
                upload_name = file_name
                if not upload_name.lower().endswith('.pdf'):
                    upload_name = os.path.splitext(upload_name)[0] + '.pdf'
            else:
                upload_ext = '.docx'
                upload_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                upload_name = file_name
                if not upload_name.lower().endswith('.docx'):
                    upload_name = os.path.splitext(upload_name)[0] + '.docx'
        
        # 3. RAG pipeline: DB'ye yükle
        conn = get_db_conn()
        rag_service = get_rag_service()
        total_chunks = 0
        file_id = None
        
        try:
            cur = conn.cursor()
            
            # Aynı isimli dosya varsa org grup atamalarını koru, sonra sil (sil-yaz)
            # Hem orijinal isim hem de çıkış formatındaki isim silinmeli
            names_to_delete = list(set([file_name, upload_name]))
            saved_org_ids = []
            
            for del_name in names_to_delete:
                # Org grup atamalarını koru (silinmeden önce)
                cur.execute(
                    """
                    SELECT doc_org.org_id
                    FROM document_organizations doc_org
                    JOIN uploaded_files f ON doc_org.file_id = f.id
                    WHERE f.file_name = %s AND f.is_active = TRUE
                    """,
                    (del_name,)
                )
                for org_row in cur.fetchall():
                    if org_row["org_id"] not in saved_org_ids:
                        saved_org_ids.append(org_row["org_id"])
                
                # Eski versiyonların chunk'larını ve soft-delete
                cur.execute(
                    "DELETE FROM rag_chunks WHERE file_id IN (SELECT id FROM uploaded_files WHERE file_name = %s AND is_active = TRUE)",
                    (del_name,)
                )
                cur.execute(
                    "UPDATE uploaded_files SET is_active = FALSE WHERE file_name = %s AND is_active = TRUE",
                    (del_name,)
                )
            
            # Versiyon numarasını hesapla
            cur.execute(
                "SELECT MAX(file_version) as max_ver FROM uploaded_files WHERE file_name = %s",
                (upload_name,)
            )
            ver_row = cur.fetchone()
            next_version = (ver_row["max_ver"] or 0) + 1 if ver_row and ver_row["max_ver"] else 1
            
            # Dosya hash'i (bütünlük kontrolü)
            import hashlib as _hashlib
            file_hash = _hashlib.md5(file_content_bytes[:1024*1024]).hexdigest()
            
            # Dosyayı PostgreSQL'e kaydet (maturity_score ve status dahil)
            # v3.3.0 [B1]: Maturity skoru — iyileştirilmiş metin üzerinden hesapla
            m_score = data.get("maturity_score")  # Fallback: orijinal skor
            
            try:
                from app.services.maturity_analyzer import analyze_file
                
                if orig_file_type in ("XLSX", "XLS", "PPTX", "PPT"):
                    # XLSX/PPTX: Orijinal binary değişmedi, maturity'yi
                    # iyileştirilmiş section text'leri üzerinden ölçmek gerekiyor.
                    # combined_text henüz oluşturulmadı, burada erken hesaplama yapamayız.
                    # Chunk'lar oluşturulduktan sonra hesaplanacak (aşağıda).
                    m_score = data.get("maturity_score")  # Geçici olarak orijinal
                    log_system_event(
                        "INFO",
                        f"Orijinal format korunuyor ({orig_file_type}), "
                        f"maturity skoru chunk'lar sonrası güncellenecek",
                        "rag_enhance"
                    )
                else:
                    # DOCX/PDF/TXT: Enhanced dosyanın kendisi üzerinden maturity hesapla
                    enhanced_file_obj = _io.BytesIO(file_content_bytes)
                    enhanced_maturity = analyze_file(enhanced_file_obj, upload_name)
                    m_score = enhanced_maturity.get("total_score")
                    log_system_event(
                        "INFO",
                        f"İyileştirilmiş dosya olgunluk skoru: {m_score} "
                        f"(orijinal: {data.get('maturity_score')})",
                        "rag_enhance"
                    )
            except Exception as mat_err:
                log_warning(f"İyileştirilmiş olgunluk hesaplanamadı: {mat_err}", "rag_enhance")
                m_score = data.get("maturity_score")
            
            cur.execute(
                """
                INSERT INTO uploaded_files (file_name, file_type, file_size_bytes, file_content, mime_type, uploaded_by, maturity_score, status, file_version, is_active, file_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed', %s, TRUE, %s)
                RETURNING id
                """,
                (
                    upload_name, upload_ext, file_size, file_content_bytes,
                    upload_mime,
                    current_user["id"],
                    m_score,
                    next_version,
                    file_hash
                ),
            )
            file_id = cur.fetchone()["id"]
            
            # v3.3.0 [D2]: Tüm formatları processor pipeline üzerinden işle
            # XLSX/PPTX dahil — inline chunking kaldırıldı
            # Bu sayede dedup, quality score, heading prefix otomatik uygulanır
            if orig_file_type in ("XLSX", "XLS", "PPTX", "PPT"):
                # Enhanced section text'lerini birleştirip geçici TXT dosyası olarak processor'a ver
                combined_text = ""
                for s in data["sections"]:
                    s_idx = s.section_index
                    s_heading = s.heading or f"Bölüm {s_idx + 1}"
                    
                    if s_idx in approved_indexes:
                        section_text = s.enhanced_text
                    else:
                        section_text = s.original_text
                    
                    if section_text and section_text.strip():
                        combined_text += f"\n\n{s_heading}\n{'=' * len(s_heading)}\n{section_text}"
                
                if combined_text.strip():
                    # TXT processor ile chunk oluştur (heading detection + overlap + quality score)
                    from app.services.document_processors.txt_processor import TXTProcessor
                    txt_proc = TXTProcessor()
                    temp_file_obj = _io.BytesIO(combined_text.strip().encode("utf-8"))
                    processed = txt_proc.process_bytes(temp_file_obj, upload_name)
                    
                    chunks = [
                        {
                            "text": chunk.text,
                            "metadata": {"source_file": upload_name, "enhanced": True, **chunk.metadata}
                        }
                        for chunk in processed.chunks
                    ]
                else:
                    chunks = []
                
                log_system_event(
                    "INFO",
                    f"Enhanced text'lerden processor pipeline ile {len(chunks)} chunk oluşturuldu ({orig_file_type})",
                    "rag_enhance"
                )
                
                # XLSX/PPTX: Maturity'yi iyileştirilmiş metin üzerinden yeniden hesapla
                try:
                    from app.services.maturity_analyzer import analyze_file as _analyze
                    enhanced_text_obj = _io.BytesIO(combined_text.strip().encode("utf-8"))
                    enhanced_mat = _analyze(enhanced_text_obj, upload_name.replace(upload_ext, '.txt'))
                    new_m_score = enhanced_mat.get("total_score")
                    if new_m_score is not None:
                        m_score = new_m_score
                        # uploaded_files'ta maturity_score'u güncelle
                        cur.execute(
                            "UPDATE uploaded_files SET maturity_score = %s WHERE id = %s",
                            (m_score, file_id)
                        )
                        log_system_event(
                            "INFO",
                            f"XLSX/PPTX maturity yeniden hesaplandı: {m_score} "
                            f"(orijinal: {data.get('maturity_score')})",
                            "rag_enhance"
                        )
                except Exception as mat_err2:
                    log_warning(f"XLSX/PPTX maturity yeniden hesaplanamadı: {mat_err2}", "rag_enhance")
            else:
                # DOCX/PDF/TXT: processor ile parse et
                processor = get_processor_for_extension(upload_ext)
                if not processor:
                    raise ValueError(f"{upload_ext} işlemcisi bulunamadı.")
                
                file_obj = _io.BytesIO(file_content_bytes)
                processed = processor.process_bytes(file_obj, upload_name)
                
                chunks = [
                    {
                        "text": chunk.text,
                        "metadata": {"source_file": upload_name, **chunk.metadata}
                    }
                    for chunk in processed.chunks
                ]
            
            if not chunks:
                raise ValueError("Dosyadan hiç veri çıkarılamadı.")
            
            chunk_count = rag_service.add_chunks_with_embeddings(
                file_id, chunks, cursor=cur
            )
            total_chunks = chunk_count
            
            # v3.4.2: Görsel çıkarma — background thread'de çalışır
            # Kullanıcıya hemen yanıt dönmesi için senkron pipeline'dan çıkarıldı
            _original_content_for_bg = data.get("original_content")
            _original_ext_for_bg = data.get("file_type", upload_ext)
            if not _original_ext_for_bg.startswith('.'):
                _original_ext_for_bg = f".{_original_ext_for_bg}"
            _file_id_for_bg = file_id
            
            # Org grup atamalarını yaz: frontend'den gelen + eski dosyadan kopyalanan
            all_org_ids = list(saved_org_ids)  # Eski dosyadan kopyalananlar
            if org_ids:
                frontend_org_ids = [int(x.strip()) for x in org_ids.split(",") if x.strip()]
                for oid in frontend_org_ids:
                    if oid not in all_org_ids:
                        all_org_ids.append(oid)
            
            if all_org_ids:
                for oid in all_org_ids:
                    cur.execute(
                        """
                        INSERT INTO document_organizations (file_id, org_id, assigned_by)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (file_id, org_id) DO NOTHING
                        """,
                        (file_id, oid, current_user["id"])
                    )
                log_system_event("INFO", f"Org grupları atandı: {len(all_org_ids)} org", "rag_enhance")
            
            # COMMIT
            conn.commit()
            
            # Topic çıkarma (commit sonrası)
            try:
                topic_count = extract_and_save_topics(chunks, upload_name, file_id)
                if topic_count > 0:
                    log_system_event("INFO", f"{upload_name}: {topic_count} topic çıkarıldı", "rag_enhance")
            except Exception as te:
                log_error(f"Topic çıkarma hatası: {te}", "rag_enhance")
            
            log_system_event(
                "INFO",
                f"Enhanced dosya RAG'a yüklendi: {upload_name} ({total_chunks} chunk)",
                "rag_enhance",
                user_id=current_user["id"]
            )
            
            # v3.3.0: enhancement_history tablosunu güncelle (maturity_score_after + uploaded_to_rag)
            try:
                conn2 = get_db_conn()
                cur2 = conn2.cursor()
                cur2.execute(
                    """
                    UPDATE enhancement_history 
                    SET maturity_score_after = %s, uploaded_to_rag = TRUE
                    WHERE session_id = %s
                    """,
                    (m_score, session_id)
                )
                conn2.commit()
                cur2.close()
                conn2.close()
                log_system_event(
                    "INFO",
                    f"Enhancement history güncellendi: session={session_id}, "
                    f"score_after={m_score}, uploaded=true",
                    "rag_enhance"
                )
            except Exception as hist_err:
                log_warning(f"Enhancement history güncellenemedi: {hist_err}", "rag_enhance")
            
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            log_error(f"Enhanced RAG yükleme hatası (rollback): {e}", "rag_enhance")
            raise HTTPException(status_code=500, detail="Bilgi tabanına yükleme sırasında bir hata oluştu.")
        finally:
            conn.close()
        
        # v3.4.2: Görsel çıkarma — background thread'de çalışır (tüm görseller eksiksiz)
        # Kullanıcıya hemen yanıt dönülür, görseller arka planda eklenir
        if _original_content_for_bg:
            def _bg_image_extraction():
                try:
                    from app.services.document_processors.image_extractor import ImageExtractor
                    from app.api.routes.rag_upload import _update_chunk_image_refs
                    from app.core.db import get_db_conn as _get_db_conn
                    
                    bg_conn = _get_db_conn()
                    bg_cur = bg_conn.cursor()
                    
                    img_extractor = ImageExtractor()
                    extracted_images = img_extractor.extract(
                        _original_content_for_bg, _original_ext_for_bg
                    )
                    if extracted_images:
                        image_ids = img_extractor.save_to_db(
                            extracted_images, _file_id_for_bg, cursor=bg_cur
                        )
                        if image_ids:
                            _update_chunk_image_refs(
                                bg_cur, _file_id_for_bg, extracted_images, image_ids
                            )
                        bg_conn.commit()
                        log_system_event(
                            "INFO",
                            f"[BG] Orijinal dosyadan {len(extracted_images)} görsel çıkarıldı ve kaydedildi (file_id={_file_id_for_bg})",
                            "rag_enhance"
                        )
                    else:
                        bg_conn.commit()
                    bg_cur.close()
                    bg_conn.close()
                except Exception as bg_err:
                    log_system_event("WARNING", f"[BG] Görsel çıkarma hatası: {bg_err}", "rag_enhance")
            
            bg_thread = threading.Thread(target=_bg_image_extraction, daemon=True)
            bg_thread.start()
            log_system_event("INFO", f"Görsel çıkarma background thread başlatıldı (file_id={_file_id_for_bg})", "rag_enhance")
        
        # 4. Session temizle — v3.2.1: Hemen silmek yerine flag ile işaretle
        cleanup_enhanced_file(session_id)
        if session_id in _session_data:
            _session_data[session_id]["_uploaded"] = True
            # NOT: original_content background thread kullanıyor, hemen silme
            # _session_data[session_id].pop("original_content", None)
        
        return JSONResponse(content={
            "status": "ok",
            "message": f"'{upload_name}' bilgi tabanına başarıyla yüklendi.",
            "file_name": upload_name,
            "file_id": file_id,
            "chunk_count": total_chunks,
            "enhanced_sections": len(approved_indexes)
        })
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Upload enhanced hatası: {e}", "rag_enhance")
        raise HTTPException(status_code=500, detail="Dosya yükleme sırasında bir hata oluştu.")


@router.delete("/cleanup-enhanced/{session_id}")
async def cleanup_enhanced(session_id: str):
    """Geçici iyileştirilmiş dosyayı ve session verisini temizle"""
    cleanup_enhanced_file(session_id)
    _session_data.pop(session_id, None)
    return {"status": "ok", "message": "Geçici dosya temizlendi."}


# ─────────────────────────────────────────
# Helper: Maturity Analizi
# ─────────────────────────────────────────

def _run_maturity_analysis(file_content: bytes, file_name: str) -> dict:
    """Maturity analyzer'ı çalıştır ve sonucu döndür"""
    import io
    
    try:
        from app.services.maturity_analyzer import analyze_file
        
        file_obj = io.BytesIO(file_content)
        result = analyze_file(file_obj, file_name)
        
        return result
    except Exception as e:
        log_error(f"Maturity analizi hatası: {e}", "rag_enhance")
        # Maturity analizi başarısız olsa bile enhancement devam edebilir
        return {
            "file_type": _detect_file_type(file_name),
            "violations": [],
            "total_score": 0,
            "categories": {}
        }


def _detect_file_type(file_name: str) -> str:
    """Dosya uzantısından tip belirle"""
    ext = os.path.splitext(file_name)[1].lower()
    type_map = {
        '.pdf': 'PDF', '.docx': 'DOCX', '.doc': 'DOCX',
        '.xlsx': 'XLSX', '.xls': 'XLSX',
        '.pptx': 'PPTX', '.ppt': 'PPTX',
        '.txt': 'TXT', '.csv': 'CSV'
    }
    return type_map.get(ext, 'TXT')


# ─────────────────────────────────────────
#  v3.3.0 [D1]: Enhancement Etki Ölçüm API
# ─────────────────────────────────────────

@router.get("/enhancement-impact")
async def get_enhancement_impact(
    file_name: str = Query(None, description="Belirli dosya adı filtresi"),
    limit: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Enhancement etki ölçüm raporu.
    maturity_score_before vs maturity_score_after karşılaştırması.
    
    Returns:
        summary: Genel istatistikler (ortalama iyileşme, dosya sayısı)
        items: Dosya bazlı etki listesi
    """
    from app.core.db import get_db_conn
    
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        
        query = """
            SELECT 
                file_name, original_file_type, session_id,
                total_sections, enhanced_sections,
                maturity_score_before, maturity_score_after,
                uploaded_to_rag, created_at
            FROM enhancement_history
            WHERE user_id = %s
        """
        params = [current_user["id"]]
        
        if file_name:
            query += " AND file_name ILIKE %s"
            params.append(f"%{file_name}%")
        
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        items = []
        total_before = 0
        total_after = 0
        measured_count = 0
        
        for row in rows:
            score_before = row["maturity_score_before"]
            score_after = row["maturity_score_after"]
            improvement = None
            
            if score_before is not None and score_after is not None:
                improvement = round(score_after - score_before, 1)
                total_before += score_before
                total_after += score_after
                measured_count += 1
            
            items.append({
                "file_name": row["file_name"],
                "file_type": row["original_file_type"],
                "session_id": row["session_id"],
                "total_sections": row["total_sections"],
                "enhanced_sections": row["enhanced_sections"],
                "score_before": round(score_before, 1) if score_before else None,
                "score_after": round(score_after, 1) if score_after else None,
                "improvement": improvement,
                "improvement_pct": round((improvement / score_before) * 100, 1) if improvement and score_before else None,
                "uploaded_to_rag": row["uploaded_to_rag"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            })
        
        avg_before = round(total_before / measured_count, 1) if measured_count > 0 else None
        avg_after = round(total_after / measured_count, 1) if measured_count > 0 else None
        avg_improvement = round(avg_after - avg_before, 1) if avg_before and avg_after else None
        
        cur.close()
        conn.close()
        
        return JSONResponse(content={
            "summary": {
                "total_enhancements": len(items),
                "measured_count": measured_count,
                "avg_score_before": avg_before,
                "avg_score_after": avg_after,
                "avg_improvement": avg_improvement,
                "avg_improvement_pct": round((avg_improvement / avg_before) * 100, 1) if avg_improvement and avg_before else None,
            },
            "items": items
        })
        
    except Exception as e:
        from app.core.logging_config import log_error
        log_error(f"Enhancement impact sorgusu hatası: {e}", "rag_enhance")
        raise HTTPException(status_code=500, detail="Etki ölçüm verileri alınamadı")
