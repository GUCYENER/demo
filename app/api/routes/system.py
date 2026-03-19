"""
VYRA L1 Support API - System Management Routes
===============================================
Sistem yönetimi endpoint'leri (reset, maintenance vb.)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error
from app.api.routes.auth import get_current_user


router = APIRouter()


class ResetResponse(BaseModel):
    success: bool
    message: str
    deleted_counts: dict


@router.post("/reset", response_model=ResetResponse)
async def reset_system(
    company_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Sistemi sıfırlar.
    
    KORUNAN VERİLER:
    - Admin kullanıcılar (users WHERE is_admin = TRUE)
    - Roller (roles)
    - LLM Konfigürasyonları (llm_config)
    - Prompt Şablonları (prompt_templates)
    - Sistem görselleri (system_assets)
    - Organizasyonlar (organization_groups)
    
    SİLİNEN VERİLER:
    - Ticket'lar ve mesajları (tickets, ticket_steps, ticket_messages)
    - Dialog'lar ve mesajları (dialogs, dialog_messages)
    - Çözüm logları (solution_logs)
    - RAG dosyaları ve chunk'ları (uploaded_files, rag_chunks)
    - Doküman görselleri (document_images)
    - RAG feedback'leri (user_feedback)
    - Dinamik topic'ler (document_topics)
    - ML modelleri ve eğitim (ml_models, ml_training_jobs, ml_training_samples, ml_training_schedules)
    - Öğrenilmiş cevaplar (learned_answers)
    - Sistem logları (system_logs)
    - Admin olmayan kullanıcılar
    """
    # Sadece admin sıfırlayabilir
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    deleted_counts = {}
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Firma bazlı filtre (varsa)
        co_filter = ""
        co_params = []
        if company_id is not None:
            co_filter = "WHERE company_id = %s"
            co_params = [company_id]
        
        # 1️⃣ Ticket mesajları sil
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM ticket_messages WHERE ticket_id IN (SELECT id FROM tickets WHERE company_id = %s)", co_params)
            deleted_counts["ticket_messages"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM ticket_messages WHERE ticket_id IN (SELECT id FROM tickets WHERE company_id = %s)", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM ticket_messages")
            deleted_counts["ticket_messages"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM ticket_messages")
        
        # 2️⃣ Ticket adımları sil
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM ticket_steps WHERE ticket_id IN (SELECT id FROM tickets WHERE company_id = %s)", co_params)
            deleted_counts["ticket_steps"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM ticket_steps WHERE ticket_id IN (SELECT id FROM tickets WHERE company_id = %s)", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM ticket_steps")
            deleted_counts["ticket_steps"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM ticket_steps")
        
        # 3️⃣ Çözüm logları sil
        cur.execute("SELECT COUNT(*) as cnt FROM solution_logs")
        deleted_counts["solution_logs"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM solution_logs")
        
        # 4️⃣ Ticket'ları sil
        if company_id is not None:
            cur.execute(f"SELECT COUNT(*) as cnt FROM tickets {co_filter}", co_params)
            deleted_counts["tickets"] = cur.fetchone()["cnt"]
            cur.execute(f"DELETE FROM tickets {co_filter}", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM tickets")
            deleted_counts["tickets"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM tickets")
        
        # 5️⃣ Dialog mesajlarını sil (FK: dialogs -> dialog_messages)
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM dialog_messages WHERE dialog_id IN (SELECT id FROM dialogs WHERE user_id IN (SELECT id FROM users WHERE company_id = %s))", co_params)
            deleted_counts["dialog_messages"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM dialog_messages WHERE dialog_id IN (SELECT id FROM dialogs WHERE user_id IN (SELECT id FROM users WHERE company_id = %s))", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM dialog_messages")
            deleted_counts["dialog_messages"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM dialog_messages")
        
        # 6️⃣ Dialog'ları sil
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM dialogs WHERE user_id IN (SELECT id FROM users WHERE company_id = %s)", co_params)
            deleted_counts["dialogs"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM dialogs WHERE user_id IN (SELECT id FROM users WHERE company_id = %s)", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM dialogs")
            deleted_counts["dialogs"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM dialogs")
        
        # 7️⃣ RAG feedback'lerini sil
        cur.execute("SELECT COUNT(*) as cnt FROM user_feedback")
        deleted_counts["user_feedback"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM user_feedback")
        
        # 8️⃣ RAG chunk'larını sil
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM rag_chunks WHERE file_id IN (SELECT id FROM uploaded_files WHERE company_id = %s)", co_params)
            deleted_counts["rag_chunks"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM rag_chunks WHERE file_id IN (SELECT id FROM uploaded_files WHERE company_id = %s)", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM rag_chunks")
            deleted_counts["rag_chunks"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM rag_chunks")
        
        # 8️⃣.5 Doküman görsellerini sil (FK: uploaded_files -> document_images)
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM document_images WHERE file_id IN (SELECT id FROM uploaded_files WHERE company_id = %s)", co_params)
            deleted_counts["document_images"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM document_images WHERE file_id IN (SELECT id FROM uploaded_files WHERE company_id = %s)", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM document_images")
            deleted_counts["document_images"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM document_images")
        
        # 9️⃣ Yüklenen dosyaları sil
        if company_id is not None:
            cur.execute(f"SELECT COUNT(*) as cnt FROM uploaded_files {co_filter}", co_params)
            deleted_counts["uploaded_files"] = cur.fetchone()["cnt"]
            cur.execute(f"DELETE FROM uploaded_files {co_filter}", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM uploaded_files")
            deleted_counts["uploaded_files"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM uploaded_files")
        
        # 9️⃣.5 Dinamik topic'leri sil (v2.34.0)
        cur.execute("SELECT COUNT(*) as cnt FROM document_topics")
        deleted_counts["document_topics"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM document_topics")
        
        # 🔟 ML eğitim örneklerini sil (FK: ml_training_jobs -> ml_training_samples)
        cur.execute("SELECT COUNT(*) as cnt FROM ml_training_samples")
        deleted_counts["ml_training_samples"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM ml_training_samples")
        
        # 🆕 v2.51.1: Öğrenilmiş cevapları sil (CL tarafından üretilen Q&A)
        cur.execute("SELECT COUNT(*) as cnt FROM learned_answers")
        deleted_counts["learned_answers"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM learned_answers")
        
        # 1️⃣0️⃣.5 ML eğitim job'larını sil
        cur.execute("SELECT COUNT(*) as cnt FROM ml_training_jobs")
        deleted_counts["ml_training_jobs"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM ml_training_jobs")
        
        # 1️⃣0️⃣.7 ML eğitim schedule'larını sil
        cur.execute("SELECT COUNT(*) as cnt FROM ml_training_schedules")
        deleted_counts["ml_training_schedules"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM ml_training_schedules")
        
        # 1️⃣1️⃣ ML modellerini sil
        cur.execute("SELECT COUNT(*) as cnt FROM ml_models")
        deleted_counts["ml_models"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM ml_models")
        
        # 1️⃣2️⃣ Sistem loglarını sil
        cur.execute("SELECT COUNT(*) as cnt FROM system_logs")
        deleted_counts["system_logs"] = cur.fetchone()["cnt"]
        cur.execute("DELETE FROM system_logs")
        
        # 1️⃣3️⃣ Admin olmayan kullanıcıları sil
        if company_id is not None:
            cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = FALSE AND company_id = %s", co_params)
            deleted_counts["non_admin_users"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM users WHERE is_admin = FALSE AND company_id = %s", co_params)
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = FALSE")
            deleted_counts["non_admin_users"] = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM users WHERE is_admin = FALSE")
        
        conn.commit()
        
        # Reset işlemini logla
        log_system_event(
            "WARNING",
            f"🔄 Sistem sıfırlandı. Kullanıcı: {current_user.get('username')}. "
            f"Silinen: {sum(deleted_counts.values())} kayıt",
            "system_reset"
        )
        
        return ResetResponse(
            success=True,
            message="Sistem başarıyla sıfırlandı. Tüm ticket, dosya ve loglar silindi.",
            deleted_counts=deleted_counts
        )
        
    except Exception as e:
        conn.rollback()
        log_error(f"Sistem sıfırlama hatası: {str(e)}", "system_reset")
        raise HTTPException(status_code=500, detail="Sıfırlama işlemi sırasında bir hata oluştu.")
    finally:
        conn.close()


@router.get("/info")
async def get_system_info(
    company_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Sistem bilgilerini döndürür (sıfırlama öncesi özet)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        info = {}
        
        # Korunan veriler
        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = TRUE")
        info["admin_users"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM llm_config")
        info["llm_configs"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM prompt_templates")
        info["prompt_templates"] = cur.fetchone()["cnt"]
        
        # Silinecek veriler
        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin = FALSE")
        info["non_admin_users"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM tickets")
        info["tickets"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM dialogs")
        info["dialogs"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM uploaded_files")
        info["uploaded_files"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM rag_chunks")
        info["rag_chunks"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM document_images")
        info["document_images"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM user_feedback")
        info["user_feedback"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM ml_models")
        info["ml_models"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM ml_training_jobs")
        info["ml_training_jobs"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM ml_training_samples")
        info["ml_training_samples"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM document_topics")
        info["document_topics"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM learned_answers")
        info["learned_answers"] = cur.fetchone()["cnt"]
        
        cur.execute("SELECT COUNT(*) as cnt FROM system_logs")
        info["system_logs"] = cur.fetchone()["cnt"]
        
        return {
            "protected": {
                "admin_users": info["admin_users"],
                "llm_configs": info["llm_configs"],
                "prompt_templates": info["prompt_templates"]
            },
            "to_delete": {
                "non_admin_users": info["non_admin_users"],
                "tickets": info["tickets"],
                "dialogs": info["dialogs"],
                "uploaded_files": info["uploaded_files"],
                "rag_chunks": info["rag_chunks"],
                "document_images": info.get("document_images", 0),
                "user_feedback": info["user_feedback"],
                "document_topics": info["document_topics"],
                "ml_models": info["ml_models"],
                "ml_training_jobs": info["ml_training_jobs"],
                "ml_training_samples": info["ml_training_samples"],
                "learned_answers": info["learned_answers"],
                "system_logs": info["system_logs"]
            }
        }
        
    finally:
        conn.close()


# ============================================
# ML Model Management Endpoints (v2.13.0)
# ============================================

@router.get("/ml/status")
async def get_ml_status(current_user: dict = Depends(get_current_user)):
    """
    CatBoost model durumunu döndürür.
    
    Bilgiler:
    - Model yüklü mü?
    - Aktif model versiyonu
    - Feature bilgileri
    - Global feedback istatistikleri
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.services.catboost_service import get_catboost_service
        from app.services.feedback_service import get_feedback_service
        
        catboost_service = get_catboost_service()
        feedback_service = get_feedback_service()
        
        model_info = catboost_service.get_model_info()
        global_stats = feedback_service.get_global_stats(days=30)
        
        # Veritabanından model listesi
        conn = get_db_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, model_name, model_version, is_active, trained_at, training_samples
                FROM ml_models
                ORDER BY trained_at DESC
                LIMIT 5
            """)
            models = [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
        
        return {
            "catboost": model_info,
            "feedback_stats": global_stats,
            "available_models": models,
            "training_ready": global_stats.get("total_feedback", 0) >= 50
        }
        
    except Exception as e:
        log_error(f"ML status hatası: {e}", "ml_status")
        return {
            "catboost": {"is_ready": False, "error": "ML servis bilgisi alınamadı."},
            "feedback_stats": {},
            "available_models": [],
            "training_ready": False
        }


@router.post("/ml/reload")
async def reload_ml_model(current_user: dict = Depends(get_current_user)):
    """
    CatBoost modelini yeniden yükler.
    
    Yeni bir model eğitildikten sonra aktif hale getirmek için kullanılır.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.services.catboost_service import get_catboost_service
        
        catboost_service = get_catboost_service()
        success = catboost_service.reload_model()
        
        log_system_event(
            "INFO",
            f"ML model reload: {'başarılı' if success else 'model bulunamadı'}. Kullanıcı: {current_user.get('username')}",
            "ml_reload"
        )
        
        return {
            "success": success,
            "message": "Model yeniden yüklendi" if success else "Aktif model bulunamadı, fallback modda"
        }
        
    except Exception as e:
        log_error(f"ML reload hatası: {e}", "ml_reload")
        raise HTTPException(status_code=500, detail="İşlem sırasında bir hata oluştu.")


@router.post("/ml/clear-cache")
async def clear_ml_cache(current_user: dict = Depends(get_current_user)):
    """
    ML servislerinin cache'ini temizler.
    
    User affinity ve feature extractor cache'leri temizlenir.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.services.catboost_service import get_catboost_service
        from app.services.user_affinity_service import get_user_affinity_service
        from app.services.feature_extractor import get_feature_extractor
        
        get_catboost_service().clear_cache()
        get_user_affinity_service().clear_cache()
        get_feature_extractor().clear_cache()
        
        log_system_event(
            "INFO",
            f"ML cache temizlendi. Kullanıcı: {current_user.get('username')}",
            "ml_cache"
        )
        
        return {"success": True, "message": "Cache temizlendi"}
        
    except Exception as e:
        log_error(f"Cache temizleme hatası: {e}", "ml_cache")
        raise HTTPException(status_code=500, detail="İşlem sırasında bir hata oluştu.")


# ============================================
# ML Training Management Endpoints (v2.13.1)
# ============================================

@router.get("/ml/training/stats")
async def get_training_stats(
    company_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Eğitim istatistiklerini döndürür.
    
    - Toplam feedback sayısı
    - Son eğitimden sonraki feedback
    - Aktif model bilgisi
    - Son eğitim durumu
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    from app.services.ml_training_service import get_ml_training_service
    
    service = get_ml_training_service()
    stats = service.get_training_stats()
    
    return stats


@router.post("/ml/training/start")
async def start_training(current_user: dict = Depends(get_current_user)):
    """
    Model eğitimini başlatır (arka planda).
    
    Eğitim ~5-10 dakika sürebilir.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.services.ml_training_service import get_ml_training_service
        
        service = get_ml_training_service()
        print(f"[MLTraining] start_training çağrılıyor, user_id: {current_user.get('id')}")
        result = service.start_training(
            user_id=current_user.get("id"),
            trigger="manual"
        )
        print(f"[MLTraining] start_training sonucu: {result}")
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[MLTraining] start_training HATA: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="İşlem sırasında bir hata oluştu.")


@router.get("/ml/training/status")
async def get_training_status(current_user: dict = Depends(get_current_user)):
    """
    Çalışan eğitim job'ının durumunu döndürür.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    from app.services.ml_training_service import get_ml_training_service
    
    service = get_ml_training_service()
    status = service.get_current_job_status()
    
    return {
        "is_training": service.is_training(),
        "current_job": status
    }


@router.get("/ml/training/history")
async def get_training_history(
    limit: int = 20,
    company_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Eğitim geçmişini döndürür.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    from app.services.ml_training_service import get_ml_training_service
    
    service = get_ml_training_service()
    history = service.get_training_history(limit=limit)
    
    return {"history": history}


@router.get("/ml/training/samples/{job_id}")
async def get_training_samples(
    job_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """
    Belirli bir eğitim job'ının örneklerini döndürür.
    Pagination: offset + limit ile sayfalama destekler.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.core.db import get_db_context

        with get_db_context() as conn:
            with conn.cursor() as cur:
                # Toplam sayı
                cur.execute(
                    "SELECT COUNT(*) as total FROM ml_training_samples WHERE job_id = %s",
                    (job_id,)
                )
                total = cur.fetchone()["total"]
                
                # Sayfalı veri — EXISTS subquery ile learned_answers varlık kontrolü
                # NOT: LEFT JOIN yerine EXISTS kullanıyoruz, aynı soruya birden 
                # fazla cevap kaydedilmişse duplicate row döndürme riskini önler.
                cur.execute("""
                    SELECT mts.id, mts.query, mts.chunk_text, mts.source_file, 
                           mts.intent, mts.relevance_label, mts.score,
                           EXISTS(
                               SELECT 1 FROM learned_answers la 
                               WHERE LOWER(TRIM(la.question)) = LOWER(TRIM(mts.query))
                           ) AS has_learned_answer
                    FROM ml_training_samples mts
                    WHERE mts.job_id = %s
                    ORDER BY mts.id
                    LIMIT %s OFFSET %s
                """, (job_id, limit, offset))
                
                samples = []
                for row in cur.fetchall():
                    samples.append({
                        "id": row["id"],
                        "query": row["query"],
                        "chunk_text": row["chunk_text"],
                        "source_file": row["source_file"],
                        "intent": row["intent"],
                        "relevance": row["relevance_label"],
                        "score": float(row["score"]) if row["score"] else 0,
                        "has_learned_answer": row["has_learned_answer"]
                    })
        
        return {
            "samples": samples, 
            "total": total, 
            "job_id": job_id,
            "offset": offset,
            "limit": limit,
            "has_next": (offset + limit) < total
        }
    
    except Exception as e:
        log_error(f"Training samples getirme hatası: {e}", "ml_training")
        raise HTTPException(status_code=500, detail="İşlem sırasında bir hata oluştu.")


@router.get("/ml/learned-answer")
async def get_learned_answer(
    question: str = Query(..., min_length=2, max_length=2000),
    current_user: dict = Depends(get_current_user)
):
    """
    Belirli bir soru için learned_answers tablosundaki öğrenilmiş cevabı döndürür.
    🆕 v2.51.0: Eğitim örnekleri modalında 'Cevap' butonu için.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.core.db import get_db_context
        
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, question, answer, intent, source_file, 
                           quality_score, hit_count, created_at
                    FROM learned_answers
                    WHERE question = %s
                    LIMIT 1
                """, (question,))
                row = cur.fetchone()
                
                if not row:
                    return {"found": False, "answer": None}
                
                return {
                    "found": True,
                    "answer": row["answer"],
                    "quality_score": float(row["quality_score"]) if row["quality_score"] else 0,
                    "hit_count": row["hit_count"] or 0,
                    "created_at": str(row["created_at"]) if row["created_at"] else None
                }
    
    except Exception as e:
        log_error(f"Learned answer getirme hatası: {e}", "ml_training")
        return {"found": False, "answer": None, "error": str(e)}

class ScheduleItem(BaseModel):
    trigger_type: str = Field(..., pattern=r'^(feedback_count|interval_days|quality_drop|job_timeout|cl_interval)$')
    trigger_value: str = Field(..., max_length=20)
    is_active: bool


class HybridScheduleRequest(BaseModel):
    schedules: List[ScheduleItem]


@router.get("/ml/training/schedule")
async def get_schedule(
    company_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Tüm zamanlanmış eğitim ayarlarını döndürür (hibrit).
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    from app.services.ml_training_service import get_ml_training_service
    
    service = get_ml_training_service()
    schedules = service.get_all_schedules()
    
    return {"schedules": schedules}


@router.post("/ml/training/schedule")
async def save_schedule(
    request: HybridScheduleRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Hibrit zamanlanmış eğitim ayarlarını kaydeder.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    from app.services.ml_training_service import get_ml_training_service
    
    service = get_ml_training_service()
    result = service.save_hybrid_schedules(
        user_id=current_user.get("id"),
        schedules=[s.model_dump() for s in request.schedules]
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result


@router.get("/ml/training/continuous-status")
async def get_continuous_learning_status(current_user: dict = Depends(get_current_user)):
    """
    Continuous Learning servis durumunu döndürür.
    
    - Çalışıyor mu?
    - Toplam eğitim sayısı
    - Son eğitim zamanı
    - Sonraki planlanan çalışma zamanı
    - Son eğitim sonuçları
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.services.ml_training.continuous_learning import get_continuous_learning_service
        
        service = get_continuous_learning_service()
        return service.get_status()
        
    except Exception as e:
        log_error(f"CL status hatası: {e}", "ml_training")
        return {
            "is_running": False,
            "error": "Continuous Learning durumu alınamadı.",
            "total_trainings": 0,
            "interval_minutes": 30,
            "min_feedback_threshold": 10,
        }


class CLConfigRequest(BaseModel):
    interval_minutes: int = Field(30, ge=1, le=1440)
    is_active: bool = True


@router.post("/ml/training/continuous-config")
async def update_continuous_config(
    request: CLConfigRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Continuous Learning servis konfigürasyonunu günceller.
    - interval_minutes: Eğitim aralığı (dakika)
    - is_active: Servisi başlat/durdur
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    try:
        from app.services.ml_training.continuous_learning import get_continuous_learning_service
        
        service = get_continuous_learning_service()
        result = service.update_config(
            interval_minutes=request.interval_minutes,
            is_active=request.is_active
        )
        
        # DB'ye persist et (restart'ta korunsun)
        conn = None
        try:
            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO system_settings (setting_key, setting_value, description, updated_at)
                    VALUES ('cl_interval_minutes', %s, 'Sürekli öğrenme aralığı (dakika)', CURRENT_TIMESTAMP)
                    ON CONFLICT (setting_key) DO UPDATE SET setting_value = %s, updated_at = CURRENT_TIMESTAMP
                """, (str(request.interval_minutes), str(request.interval_minutes)))
                cur.execute("""
                    INSERT INTO system_settings (setting_key, setting_value, description, updated_at)
                    VALUES ('cl_is_active', %s, 'Sürekli öğrenme aktiflik durumu', CURRENT_TIMESTAMP)
                    ON CONFLICT (setting_key) DO UPDATE SET setting_value = %s, updated_at = CURRENT_TIMESTAMP
                """, (str(request.is_active).lower(), str(request.is_active).lower()))
            conn.commit()
        except Exception as db_err:
            log_error(f"CL config DB kayıt hatası: {db_err}", "ml_training")
        finally:
            if conn:
                conn.close()
        
        log_system_event(
            "INFO",
            f"CL config güncellendi: interval={request.interval_minutes}dk, active={request.is_active}",
            "ml_training"
        )
        
        return result
        
    except Exception as e:
        log_error(f"CL config güncelleme hatası: {e}", "ml_training")
        raise HTTPException(status_code=500, detail="İşlem sırasında bir hata oluştu.")


# ════════════════════════════════════════════════
#  Maturity Enhancement Threshold
# ════════════════════════════════════════════════

@router.get("/maturity-threshold")
async def get_maturity_threshold():
    """Maturity iyileştirme eşik değerini getir"""
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT setting_value FROM system_settings WHERE setting_key = 'maturity_enhance_threshold'"
            )
            row = cur.fetchone()
            threshold = int(row['setting_value']) if row else 80
        return {"threshold": threshold}
    except Exception as e:
        log_error(f"Maturity threshold okuma hatası: {e}", "system")
        return {"threshold": 80}
    finally:
        if conn:
            conn.close()


@router.put("/maturity-threshold")
async def set_maturity_threshold(threshold: int = Query(..., ge=0, le=100)):
    """Maturity iyileştirme eşik değerini güncelle"""
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_settings (setting_key, setting_value, description, updated_at)
                VALUES ('maturity_enhance_threshold', %s, 'Maturity iyileştirme eşik değeri (0-100)', CURRENT_TIMESTAMP)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = %s, updated_at = CURRENT_TIMESTAMP
            """, (str(threshold), str(threshold)))
        conn.commit()
        log_system_event("INFO", f"Maturity threshold güncellendi: {threshold}", "system")
        return {"status": "ok", "threshold": threshold}
    except Exception as e:
        log_error(f"Maturity threshold güncelleme hatası: {e}", "system")
        raise HTTPException(status_code=500, detail="İşlem sırasında bir hata oluştu.")
    finally:
        if conn:
            conn.close()

