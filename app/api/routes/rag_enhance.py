"""
VYRA L1 Support API - RAG Enhancement Routes
=============================================
Doküman iyileştirme (CatBoost + LLM) endpoint'leri.

Author: VYRA AI Team
Version: 1.1.0 (v3.2.1)
"""

import os
import time
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from app.api.routes.auth import get_current_user

from app.services.document_enhancer import (
    DocumentEnhancer, get_enhanced_file_path, cleanup_enhanced_file
)
from app.services.logging_service import log_system_event, log_error


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


@router.post("/enhance-document")
async def enhance_document(file: UploadFile = File(...)):
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
        
        def _run_pipeline():
            maturity_result = _run_maturity_analysis(file_content, file_name)
            return enhancer.analyze_and_enhance(
                file_content=file_content,
                file_name=file_name,
                maturity_result=maturity_result
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
                # Dosya formatını belirle (PDF mi DOCX mi?)
                is_pdf = selective_path.lower().endswith('.pdf')
                if is_pdf:
                    download_name = f"iyilestirilmis_{session_id}.pdf"
                    media = "application/pdf"
                else:
                    download_name = f"iyilestirilmis_{session_id}.docx"
                    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                
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
        is_pdf = file_path.lower().endswith('.pdf')
        if is_pdf:
            download_name = f"iyilestirilmis_{session_id}.pdf"
            media = "application/pdf"
        else:
            download_name = f"iyilestirilmis_{session_id}.docx"
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        
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
                    WHERE f.file_name = %s
                    """,
                    (del_name,)
                )
                for org_row in cur.fetchall():
                    if org_row["org_id"] not in saved_org_ids:
                        saved_org_ids.append(org_row["org_id"])
                
                cur.execute(
                    "DELETE FROM rag_chunks WHERE file_id IN (SELECT id FROM uploaded_files WHERE file_name = %s)",
                    (del_name,)
                )
                cur.execute("DELETE FROM uploaded_files WHERE file_name = %s", (del_name,))
            
            # Dosyayı PostgreSQL'e kaydet (maturity_score ve status dahil)
            # v3.2.1: İyileştirilmiş dosyanın olgunluğunu yeniden hesapla
            # (Orijinal dosyanın skorunu DEĞİL, iyileştirilmişi kullan)
            try:
                from app.services.maturity_analyzer import analyze_file
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
                m_score = data.get("maturity_score")  # Fallback: orijinal skor
            
            cur.execute(
                """
                INSERT INTO uploaded_files (file_name, file_type, file_size_bytes, file_content, mime_type, uploaded_by, maturity_score, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed')
                RETURNING id
                """,
                (
                    upload_name, upload_ext, file_size, file_content_bytes,
                    upload_mime,
                    current_user["id"],
                    m_score
                ),
            )
            file_id = cur.fetchone()["id"]
            
            # Embedding oluştur — XLSX/PPTX ise enhanced text'lerden
            if orig_file_type in ("XLSX", "XLS", "PPTX", "PPT"):
                # Enhanced section text'lerinden chunk oluştur
                chunks = []
                for s in data["sections"]:
                    s_idx = s.section_index
                    s_heading = s.heading
                    
                    # Onaylı section ise enhanced text, değilse orijinal
                    if s_idx in approved_indexes:
                        text_to_chunk = s.enhanced_text
                    else:
                        text_to_chunk = s.original_text
                    
                    if not text_to_chunk or not text_to_chunk.strip():
                        continue
                    
                    # Text'i chunk'lara böl (inline splitter)
                    # Her chunk'ın başına section heading prefix eklenir
                    # → Embedding search sırasında heading context de vektöre dahil olur
                    heading_prefix = f"[Bölüm: {s_heading}]\n" if s_heading else ""
                    _chunk_size = 1000 - len(heading_prefix)  # Heading prefix'i düşerek hesapla
                    _overlap = 100
                    _start = 0
                    ci = 0
                    while _start < len(text_to_chunk):
                        _end = min(_start + _chunk_size, len(text_to_chunk))
                        # Kelime ortasında bölme
                        if _end < len(text_to_chunk):
                            _last_space = text_to_chunk.rfind(' ', _start, _end)
                            if _last_space > _start:
                                _end = _last_space
                        
                        chunk_text = text_to_chunk[_start:_end].strip()
                        if chunk_text:
                            # Heading prefix + chunk text
                            full_chunk = heading_prefix + chunk_text
                            chunks.append({
                                "text": full_chunk,
                                "metadata": {
                                    "source_file": upload_name,
                                    "section": s_heading,
                                    "section_index": s_idx,
                                    "chunk_index": ci,
                                    "enhanced": s_idx in approved_indexes
                                }
                            })
                            ci += 1
                        
                        _start = _end - _overlap if _end < len(text_to_chunk) else len(text_to_chunk)
                
                log_system_event(
                    "INFO",
                    f"Enhanced text'lerden {len(chunks)} chunk oluşturuldu ({orig_file_type})",
                    "rag_enhance"
                )
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
            
            # Görsel çıkarma — ORİJİNAL dosyadan (enhanced PDF sadece metin içerir)
            try:
                from app.services.document_processors.image_extractor import ImageExtractor
                img_extractor = ImageExtractor()
                original_content = data.get("original_content")
                original_ext = data.get("file_type", upload_ext)
                if not original_ext.startswith('.'):
                    original_ext = f".{original_ext}"
                
                if original_content:
                    extracted_images = img_extractor.extract(original_content, original_ext)
                    if extracted_images:
                        image_ids = img_extractor.save_to_db(
                            extracted_images, file_id, cursor=cur
                        )
                        if image_ids:
                            from app.api.routes.rag_upload import _update_chunk_image_refs
                            _update_chunk_image_refs(cur, file_id, extracted_images, image_ids)
                        log_system_event("INFO", f"Orijinal dosyadan {len(extracted_images)} görsel çıkarıldı", "rag_enhance")
            except Exception as img_err:
                log_system_event("WARNING", f"Görsel çıkarma atlandı: {img_err}", "rag_enhance")
            
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
            
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            log_error(f"Enhanced RAG yükleme hatası (rollback): {e}", "rag_enhance")
            raise HTTPException(status_code=500, detail="Bilgi tabanına yükleme sırasında bir hata oluştu.")
        finally:
            conn.close()
        
        # 4. Session temizle — v3.2.1: Hemen silmek yerine flag ile işaretle
        # Race condition: kullanıcı upload sonrası hâlâ "İndir" butonuna basabilir
        # Session TTL mekanizması (_cleanup_expired_sessions) otomatik temizleyecek
        cleanup_enhanced_file(session_id)
        if session_id in _session_data:
            _session_data[session_id]["_uploaded"] = True
            # original_content bellek tüketimini azalt
            _session_data[session_id].pop("original_content", None)
        
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
        '.txt': 'TXT', '.csv': 'TXT'
    }
    return type_map.get(ext, 'TXT')
