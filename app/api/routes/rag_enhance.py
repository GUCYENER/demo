"""
VYRA L1 Support API - RAG Enhancement Routes
=============================================
Doküman iyileştirme (CatBoost + LLM) endpoint'leri.

Author: VYRA AI Team
Version: 1.3.0 (v3.4.5)
"""

import os
import time
import asyncio
import hashlib
import tempfile
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
# v3.4.4: original_content disk'te saklanır, bellekte sadece path tutulur
_session_data: dict = {}  # session_id → {"original_content_path": str, ..., "_created_at": float}

# v3.2.1: Session TTL — 30 dakika sonra otomatik temizleme
_SESSION_TTL_SECONDS = 1800  # 30 dakika


def _get_original_content(data: dict) -> bytes:
    """Session verisinden orijinal dosya içeriğini okur (disk'ten)."""
    path = data.get("original_content_path")
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return b""


def _cleanup_expired_sessions() -> None:
    """TTL'i dolmuş session'ları temizler — memory leak önleme."""
    now = time.time()
    expired = [sid for sid, data in _session_data.items()
               if now - data.get("_created_at", 0) > _SESSION_TTL_SECONDS]
    for sid in expired:
        # v3.4.4: Disk'teki orijinal dosyayı da temizle
        _data = _session_data.get(sid, {})
        _orig_path = _data.get("original_content_path")
        if _orig_path and os.path.exists(_orig_path):
            try:
                os.remove(_orig_path)
            except Exception:
                pass
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
        
        # v3.4.4: original_content'i disk'e yaz (bellek sızıntısı önleme)
        _orig_path = tempfile.mktemp(suffix=f"_{result.session_id}_orig", prefix="enhance_")
        with open(_orig_path, "wb") as _of:
            _of.write(file_content)
        
        _session_data[result.session_id] = {
            "original_content_path": _orig_path,  # v3.4.4: bellek yerine disk
            "file_type": ext,
            "file_name": file_name,
            "sections": result.sections,
            "maturity_score": maturity_result.get("total_score"),
            "_created_at": time.time()
        }
        
        # v3.3.0 [C2]: Enhancement geçmişini DB'ye kaydet
        try:
            from app.core.db import get_db_conn
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
                original_content=_get_original_content(data),
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
    company_id: int = Query(default=None),
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
    from app.core.db import get_db_conn
    
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
            file_content_bytes = _get_original_content(data)
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
                original_content=_get_original_content(data),
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
        
        # ═══════════════════════════════════════════════
        # SENKRON KISIM: Dosya kaydı (hızlı, ~1sn)
        # ═══════════════════════════════════════════════
        conn = get_db_conn()
        file_id = None
        
        try:
            cur = conn.cursor()
            
            # Aynı isimli dosya varsa org grup atamalarını koru, sonra sil (sil-yaz)
            names_to_delete = list(set([file_name, upload_name]))
            saved_org_ids = []
            
            for del_name in names_to_delete:
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
                
                cur.execute(
                    "DELETE FROM rag_chunks WHERE file_id IN (SELECT id FROM uploaded_files WHERE file_name = %s AND is_active = TRUE)",
                    (del_name,)
                )
                # v3.4.8: Eski görselleri de temizle
                cur.execute(
                    "DELETE FROM document_images WHERE file_id IN (SELECT id FROM uploaded_files WHERE file_name = %s AND is_active = TRUE)",
                    (del_name,)
                )
                cur.execute(
                    "UPDATE uploaded_files SET is_active = FALSE WHERE file_name = %s AND is_active = TRUE",
                    (del_name,)
                )
            
            # Versiyon numarası
            cur.execute(
                "SELECT MAX(file_version) as max_ver FROM uploaded_files WHERE file_name = %s",
                (upload_name,)
            )
            ver_row = cur.fetchone()
            next_version = (ver_row["max_ver"] or 0) + 1 if ver_row and ver_row["max_ver"] else 1
            
            # Dosya hash
            file_hash = hashlib.md5(file_content_bytes[:1024*1024]).hexdigest()
            
            # Maturity skoru (ön hesaplama, background'da güncellenecek)
            m_score = data.get("maturity_score")
            
            # Dosyayı DB'ye kaydet — status='processing'
            cur.execute(
                """
                INSERT INTO uploaded_files (file_name, file_type, file_size_bytes, file_content, mime_type, uploaded_by, maturity_score, status, file_version, is_active, file_hash, company_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'processing', %s, TRUE, %s, %s)
                RETURNING id
                """,
                (
                    upload_name, upload_ext, file_size, file_content_bytes,
                    upload_mime,
                    current_user["id"],
                    m_score,
                    next_version,
                    file_hash,
                    company_id
                ),
            )
            file_id = cur.fetchone()["id"]
            
            # Org grup atamaları
            all_org_ids = list(saved_org_ids)
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
            
            # COMMIT — dosya kaydı tamamlandı
            conn.commit()
            
            log_system_event(
                "INFO",
                f"Enhanced dosya kaydedildi: {upload_name} (file_id={file_id}), processing başlıyor...",
                "rag_enhance",
                user_id=current_user["id"]
            )
            
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            log_error(f"Enhanced dosya kayıt hatası (rollback): {e}", "rag_enhance")
            raise HTTPException(status_code=500, detail="Dosya kaydı sırasında bir hata oluştu.")
        finally:
            conn.close()
        
        # ═══════════════════════════════════════════════
        # ASENKRON KISIM: Ağır işlemler background'da
        # ═══════════════════════════════════════════════
        # v3.4.5: file_content_bytes ve original_content artık bg_params'ta tutulmuyor
        # Background thread DB'den okur — bellek optimizasyonu + normal upload ile tutarlı
        _bg_params = {
            "file_id": file_id,
            "upload_name": upload_name,
            "upload_ext": upload_ext,
            "orig_file_type": orig_file_type,
            "approved_indexes": approved_indexes,
            "sections": data["sections"],
            "original_file_type": data.get("file_type", upload_ext),
            "original_content_path": data.get("original_content_path"),  # disk path (image extraction için)
            "m_score_initial": m_score,
            "session_id": session_id,
            "user_id": current_user["id"],
        }
        
        def _bg_enhanced_processing():
            """Background thread: Chunk oluşturma, embedding, image, topic, maturity"""
            import io as _bio
            bg_conn = None
            try:
                from app.services.rag_service import get_rag_service as _get_rag_svc
                from app.services.rag.topic_extraction import extract_and_save_topics as _extract_topics
                from app.core.db import get_db_conn as _get_db
                
                bg_conn = _get_db()
                bg_cur = bg_conn.cursor()
                _rag = _get_rag_svc()
                
                _fid = _bg_params["file_id"]
                _uname = _bg_params["upload_name"]
                _uext = _bg_params["upload_ext"]
                _approvals = _bg_params["approved_indexes"]
                _sections = _bg_params["sections"]
                _m = _bg_params["m_score_initial"]
                
                # v3.4.5: Dosya içeriğini DB'den oku (bellek optimizasyonu)
                bg_cur.execute("SELECT file_content FROM uploaded_files WHERE id = %s", (_fid,))
                _content_row = bg_cur.fetchone()
                if not _content_row or not _content_row["file_content"]:
                    raise ValueError(f"Dosya içeriği DB'de bulunamadı (id={_fid})")
                _fcontent = bytes(_content_row["file_content"])
                
                log_system_event("INFO", f"[BG] Enhanced processing başladı: {_uname} (file_id={_fid})", "rag_enhance")
                
                # 1. Chunk oluştur — iyileştirilmiş bölümlerden combined_text
                # v3.4.7 Issue 5: Heading'leri Markdown heading formatında yaz
                # TXT processor heading'leri parse edip chunk metadata'ya aktarır
                # Bu sayede orijinal dosyanın heading'leri ile enhanced chunk heading'leri
                # tutarlı olur → görsel-chunk eşleştirmesi iyileşir
                chunks = []
                combined_text = ""
                for s in _sections:
                    s_idx = s.section_index
                    s_heading = s.heading or f"Bölüm {s_idx + 1}"
                    section_text = s.enhanced_text if s_idx in _approvals else s.original_text
                    if section_text and section_text.strip():
                        # v3.4.7: Heading'i ## format ile yaz (TXT processor heading tespit eder)
                        combined_text += f"\n\n## {s_heading}\n\n{section_text}"
                
                if combined_text.strip():
                    from app.services.document_processors.txt_processor import TXTProcessor
                    txt_proc = TXTProcessor()
                    temp_file = _bio.BytesIO(combined_text.strip().encode("utf-8"))
                    processed = txt_proc.process_bytes(temp_file, _uname)
                    chunks = [
                        {"text": c.text, "metadata": {"source_file": _uname, "enhanced": True, **c.metadata}}
                        for c in processed.chunks
                    ]
                
                # Maturity: iyileştirilmiş metin üzerinden hesapla
                try:
                    from app.services.maturity_analyzer import analyze_file as _analyze
                    mat_obj = _bio.BytesIO(combined_text.strip().encode("utf-8"))
                    mat_result = _analyze(mat_obj, _uname.rsplit('.', 1)[0] + '.txt')
                    new_score = mat_result.get("total_score")
                    if new_score is not None:
                        _m = new_score
                        log_system_event("INFO", f"[BG] {_uname}: maturity yeniden hesaplandı: {new_score}", "rag_enhance")
                except Exception as mat_err:
                    log_system_event("WARNING", f"[BG] {_uname}: maturity hesaplama hatası: {mat_err}", "rag_enhance")
                
                
                if not chunks:
                    raise ValueError("Dosyadan hiç veri çıkarılamadı.")
                
                # 2. Embedding + DB kayıt
                chunk_count = _rag.add_chunks_with_embeddings(_fid, chunks, cursor=bg_cur)
                log_system_event("INFO", f"[BG] {_uname}: {chunk_count} chunk eklendi", "rag_enhance")
                
                # 3. Görsel çıkarma — 2 aşamalı:
                # Aşama 1: skip_ocr=True ile hızlı çıkarma + DB kayıt + chunk eşleştirme
                # Aşama 2: OCR ayrı bağlantıda çalışır (uzun sürer, timeout riski yok)
                # v3.4.8: Önceki yaklaşımda skip_ocr=False tüm görsellerde OCR çalıştırıyordu
                # 411 görsel için 30+ dakika → connection timeout → SAVEPOINT rollback → 0 görsel
                _orig_path = _bg_params.get("original_content_path")
                _orig_content = None
                if _orig_path and os.path.exists(_orig_path):
                    try:
                        with open(_orig_path, "rb") as _of:
                            _orig_content = _of.read()
                    except Exception:
                        pass
                if not _orig_content:
                    _orig_content = _fcontent
                
                _saved_image_ids = []  # OCR aşaması için
                if _orig_content:
                    try:
                        from app.services.document_processors.image_extractor import ImageExtractor
                        from app.api.routes.rag_upload import _update_chunk_image_refs
                        
                        bg_cur.execute("SAVEPOINT sp_images")
                        
                        img_ext = ImageExtractor()
                        _oext = _bg_params.get("original_file_type", _uext)
                        if not _oext.startswith('.'):
                            _oext = f".{_oext}"
                        
                        # Aşama 1: Hızlı çıkarma (OCR yok, ~30sn)
                        extracted_images = img_ext.extract(_orig_content, _oext, skip_ocr=True)
                        if extracted_images:
                            image_ids, saved_images = img_ext.save_to_db(extracted_images, _fid, cursor=bg_cur)
                            if image_ids:
                                _update_chunk_image_refs(bg_cur, _fid, saved_images, image_ids)
                                _saved_image_ids = list(image_ids)
                            log_system_event("INFO", f"[BG] {len(extracted_images)} görsel çıkarıldı (file_id={_fid})", "rag_enhance")
                        
                        bg_cur.execute("RELEASE SAVEPOINT sp_images")
                    except Exception as img_err:
                        try:
                            bg_cur.execute("ROLLBACK TO SAVEPOINT sp_images")
                        except Exception:
                            pass
                        log_system_event("WARNING", f"[BG] Görsel çıkarma hatası: {img_err}", "rag_enhance")
                
                # 4. Status → processing (Tüm işlemler bitene kadar completed yapmıyoruz) + maturity + chunk_count güncelle
                bg_cur.execute(
                    "UPDATE uploaded_files SET status = 'processing', chunk_count = %s, maturity_score = %s WHERE id = %s",
                    (chunk_count, _m, _fid)
                )
                bg_conn.commit()
                
                # 5. Topic çıkarma (commit sonrası)
                try:
                    topic_count = _extract_topics(chunks, _uname, _fid)
                    if topic_count > 0:
                        log_system_event("INFO", f"[BG] {_uname}: {topic_count} topic çıkarıldı", "rag_enhance")
                except Exception:
                    pass
                
                # 5b. OCR Aşama 2: Görseller kaydedildikten sonra OCR çalıştır
                # Ayrı bağlantı kullanır — uzun sürse bile ana transaction etkilenmez
                if _saved_image_ids:
                    ocr_conn = None
                    try:
                        from app.services.document_processors.image_extractor import ImageExtractor
                        ocr_conn = _get_db()
                        ocr_cur = ocr_conn.cursor()
                        
                        # Kaydedilmiş görselleri oku
                        _ph = ','.join(['%s'] * len(_saved_image_ids))
                        ocr_cur.execute(
                            f"SELECT id, image_data, image_format FROM document_images WHERE id IN ({_ph})",
                            _saved_image_ids
                        )
                        ocr_rows = ocr_cur.fetchall()
                        
                        if ocr_rows:
                            _ocr_ext = ImageExtractor()
                            # v3.4.8: OCR reader'ı önce yükle — yüklenemezse atla
                            if _ocr_ext._get_ocr_reader() is None:
                                log_system_event("WARNING", f"[BG] OCR reader yüklenemedi, OCR aşaması atlanıyor (file_id={_fid})", "rag_enhance")
                            else:
                                ocr_count = 0
                                ocr_skipped = 0
                                ocr_errors = 0
                                for orow in ocr_rows:
                                    fmt = orow["image_format"]
                                    # v3.4.8: OCR desteklenmeyen formatları atla (emf, wmf)
                                    if fmt not in ImageExtractor.OCR_FORMATS:
                                        ocr_skipped += 1
                                        continue
                                    try:
                                        ocr_text = _ocr_ext._run_ocr_single(
                                            bytes(orow["image_data"]),
                                            fmt
                                        )
                                        if ocr_text and ocr_text.strip():
                                            ocr_cur.execute(
                                                "UPDATE document_images SET ocr_text = %s WHERE id = %s",
                                                (ocr_text.strip(), orow["id"])
                                            )
                                            ocr_count += 1
                                            
                                        # Hızlandırılmış UX: 5 başarılı OCR'da bir ara kayıt yap
                                        if ocr_count > 0 and (ocr_count % 5) == 0:
                                            ocr_conn.commit()
                                            
                                    except Exception as single_ocr_err:
                                        ocr_errors += 1
                                        log_system_event("WARNING", f"[BG] OCR tekil hata (img_id={orow['id']}, fmt={fmt}): {single_ocr_err}", "rag_enhance")
                                
                                # Kalanları kaydet
                                ocr_conn.commit()
                                log_system_event(
                                    "INFO" if ocr_count > 0 else "WARNING",
                                    f"[BG] OCR Aşama 2: {ocr_count}/{len(ocr_rows)} başarılı, "
                                    f"{ocr_skipped} format dışı, {ocr_errors} hata (file_id={_fid})",
                                    "rag_enhance"
                                )
                        
                        ocr_cur.close()
                    except Exception as ocr_err:
                        log_system_event("WARNING", f"[BG] OCR aşaması hatası: {ocr_err}", "rag_enhance")
                    finally:
                        if ocr_conn:
                            try:
                                ocr_conn.close()
                            except Exception:
                                pass
                
                # 6. Enhancement history güncelle
                try:
                    _sid = _bg_params.get("session_id")
                    if _sid:
                        h_conn = _get_db()
                        h_cur = h_conn.cursor()
                        h_cur.execute(
                            "UPDATE enhancement_history SET maturity_score_after = %s, uploaded_to_rag = TRUE WHERE session_id = %s",
                            (_m, _sid)
                        )
                        h_conn.commit()
                        h_cur.close()
                        h_conn.close()
                except Exception:
                    pass
                
                log_system_event(
                    "INFO",
                    f"[BG] Enhanced processing tamamlandı: {_uname} ({chunk_count} chunk, maturity={_m})",
                    "rag_enhance",
                    user_id=_bg_params["user_id"]
                )
                
                # 6.5 Her şey (OCR dahil) bittiğinde UI için status'u tamamlandı olarak işaretle
                try:
                    f_cur = bg_conn.cursor()
                    f_cur.execute("UPDATE uploaded_files SET status = 'completed' WHERE id = %s", (_fid,))
                    bg_conn.commit()
                    f_cur.close()
                except Exception as status_err:
                    log_system_event("WARNING", f"[BG] Status güncellenemedi: {status_err}", "rag_enhance")
                
                # 7. WebSocket bildirimi — "Yükleme tamamlandı"
                # v3.4.4: run_coroutine_threadsafe ile ana event loop'a gönder
                try:
                    from app.core.websocket_manager import ws_manager
                    _ws_msg = {
                        "type": "rag_upload_complete",
                        "file_names": [_uname],
                        "processed_count": 1,
                        "total_chunks": chunk_count,
                        "message": f"'{_uname}' bilgi tabanına başarıyla yüklendi ({chunk_count} chunk)"
                    }
                    asyncio.run_coroutine_threadsafe(
                        ws_manager.send_to_user(_bg_params["user_id"], _ws_msg),
                        _bg_params["_loop"]
                    )
                except Exception as ws_err:
                    log_system_event("WARNING", f"[BG] WS bildirim gönderilemedi: {ws_err}", "rag_enhance")
                
            except Exception as bg_err:
                log_error(f"[BG] Enhanced processing hatası: {bg_err}", "rag_enhance")
                # Status → failed
                if bg_conn:
                    try:
                        bg_conn.rollback()
                        f_cur = bg_conn.cursor()
                        f_cur.execute(
                            "UPDATE uploaded_files SET status = 'failed' WHERE id = %s",
                            (_bg_params["file_id"],)
                        )
                        bg_conn.commit()
                        f_cur.close()
                    except Exception:
                        pass
                # WS hata bildirimi
                try:
                    from app.core.websocket_manager import ws_manager
                    asyncio.run_coroutine_threadsafe(
                        ws_manager.send_to_user(_bg_params["user_id"], {
                            "type": "rag_upload_failed",
                            "file_names": [_bg_params["upload_name"]],
                            "message": f"'{_bg_params['upload_name']}' yüklenirken hata oluştu"
                        }),
                        _bg_params["_loop"]
                    )
                except Exception:
                    pass
            finally:
                if bg_conn:
                    try:
                        bg_conn.close()
                    except Exception:
                        pass
        
        # v3.4.4: asyncio.ensure_future + run_in_executor ile çalıştır
        # Normal upload pipeline ile tutarlı yaklaşım
        _bg_params["_loop"] = asyncio.get_event_loop()
        loop = asyncio.get_event_loop()
        asyncio.ensure_future(loop.run_in_executor(None, _bg_enhanced_processing))
        log_system_event("INFO", f"Enhanced background task başlatıldı (file_id={file_id})", "rag_enhance")
        
        # v3.4.5: Session temizleme background task tamamlandığında yapılır
        # (original_content_path hâlâ background thread tarafından okunabilir)
        cleanup_enhanced_file(session_id)
        if session_id in _session_data:
            _session_data[session_id]["_uploaded"] = True
        
        # HEMEN YANIT DÖN — modal kapanır, dosya listesinde "İşleniyor" görünür
        return JSONResponse(content={
            "status": "ok",
            "message": f"'{upload_name}' kaydedildi, işleniyor...",
            "file_name": upload_name,
            "file_id": file_id,
            "chunk_count": 0,
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
    # v3.4.4: Disk'teki orijinal dosyayı da temizle
    data = _session_data.get(session_id, {})
    _orig_path = data.get("original_content_path")
    if _orig_path and os.path.exists(_orig_path):
        try:
            os.remove(_orig_path)
        except Exception:
            pass
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
