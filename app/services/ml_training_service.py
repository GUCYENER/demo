"""
VYRA L1 Support API - ML Training Service
==========================================
CatBoost model eğitim yönetimi, scheduled jobs ve eğitim geçmişi.

Author: VYRA AI Team
Version: 1.0.0 (v2.13.1)
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from app.core.db import get_db_context
from app.services.logging_service import log_system_event, log_error, log_warning
from app.services.ml_training import MLJobRunnerMixin, MLSchedulingMixin


# Proje kök dizini
PROJECT_ROOT = Path(__file__).parent.parent.parent


class MLTrainingService(MLJobRunnerMixin, MLSchedulingMixin):
    """
    ML Model Eğitim Yönetimi
    
    - Manuel eğitim tetikleme
    - Scheduled job yönetimi
    - Eğitim geçmişi
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._current_job_id: Optional[int] = None
        self._training_thread: Optional[threading.Thread] = None
        self._initialized = True
    
    # ============================================
    # Training Stats
    # ============================================
    
    def get_training_stats(self) -> Dict[str, Any]:
        """Eğitim istatistiklerini döndür"""
        # required_feedback'i önce al - hata olsa bile default değer dönsün
        required_feedback = self._get_required_feedback_count()
        
        stats = {
            "total_feedback": 0,
            "feedback_since_last_training": 0,
            "active_model": None,
            "last_training": None,
            "is_training": self.is_training(),
            "training_ready": False,
            "required_feedback": required_feedback  # Default olarak ekle
        }
        
        try:
            print("[MLTraining] get_training_stats try bloğuna girdi")
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # Toplam feedback
                    cur.execute("SELECT COUNT(*) as count FROM user_feedback")
                    stats["total_feedback"] = cur.fetchone()["count"]
                    print(f"[MLTraining] total_feedback: {stats['total_feedback']}")
                    
                    # Aktif model
                    cur.execute("""
                        SELECT model_version, trained_at, training_samples
                        FROM ml_models 
                        WHERE is_active = TRUE
                        ORDER BY trained_at DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    if row:
                        stats["active_model"] = {
                            "version": row["model_version"],
                            "trained_at": row["trained_at"].isoformat() if row["trained_at"] else None,
                            "samples": row["training_samples"]
                        }
                        
                        # Son eğitimden sonraki feedback sayısı
                        cur.execute("""
                            SELECT COUNT(*) as count FROM user_feedback
                            WHERE created_at > %s
                        """, (row["trained_at"],))
                        stats["feedback_since_last_training"] = cur.fetchone()["count"]
                    else:
                        stats["feedback_since_last_training"] = stats["total_feedback"]
                    
                    # Son eğitim bilgisi
                    cur.execute("""
                        SELECT id, job_name, status, start_time, end_time, duration_seconds
                        FROM ml_training_jobs
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                    last_job = cur.fetchone()
                    if last_job:
                        stats["last_training"] = {
                            "id": last_job["id"],
                            "name": last_job["job_name"],
                            "status": last_job["status"],
                            "start_time": last_job["start_time"].isoformat() if last_job["start_time"] else None,
                            "duration": last_job["duration_seconds"]
                        }
                    
                    # Anlık eğitim kriterden bağımsız — her zaman çalışabilir
                    stats["training_ready"] = True
                    
        except Exception as e:
            import traceback
            print(f"[MLTraining] HATA: {e}")
            print(traceback.format_exc())
            log_error(f"Training stats hatası: {e}\n{traceback.format_exc()}", "ml_training")
        
        return stats
    
    # ============================================
    # Training Execution
    # ============================================
    
    def is_training(self) -> bool:
        """Eğitim devam ediyor mu?"""
        if self._training_thread and self._training_thread.is_alive():
            return True
        
        # Veritabanından kontrol
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM ml_training_jobs
                        WHERE status = 'running'
                        LIMIT 1
                    """)
                    return cur.fetchone() is not None
        except Exception as e:
            log_warning(f"is_training DB kontrolü hatası: {e}", "ml_training")
            return False
    
    def kill_stale_jobs(self, timeout_minutes: int = 60) -> int:
        """
        Belirtilen süreden uzun çalışan job'ları kill et.
        
        Args:
            timeout_minutes: Zaman aşımı süresi (dakika), varsayılan 60 dakika (1 saat)
            
        Returns:
            Kill edilen job sayısı
        """
        killed_count = 0
        
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # Belirtilen süreden uzun süren running job'ları bul
                    cur.execute("""
                        SELECT id, job_name, start_time
                        FROM ml_training_jobs
                        WHERE status = 'running'
                          AND start_time IS NOT NULL
                          AND start_time < NOW() - MAKE_INTERVAL(mins => %s)
                    """, (timeout_minutes,))
                    
                    stale_jobs = cur.fetchall()
                    
                    for job in stale_jobs:
                        job_id = job["id"]
                        job_name = job["job_name"]
                        start_time = job["start_time"]
                        
                        # Süreyi hesapla (timezone-aware ise naive'a çevir)
                        if start_time.tzinfo is not None:
                            start_time = start_time.replace(tzinfo=None)
                        elapsed = datetime.now() - start_time
                        elapsed_minutes = int(elapsed.total_seconds() / 60)
                        
                        # Job'ı failed olarak işaretle
                        cur.execute("""
                            UPDATE ml_training_jobs
                            SET status = 'failed',
                                end_time = NOW(),
                                duration_seconds = EXTRACT(EPOCH FROM (NOW() - start_time))::INTEGER,
                                error_message = %s
                            WHERE id = %s
                        """, (
                            f"Otomatik sonlandırıldı: {elapsed_minutes} dakikayı geçti (limit: {timeout_minutes} dk)",
                            job_id
                        ))
                        
                        killed_count += 1
                        
                        log_system_event(
                            "WARNING",
                            f"Stale job kill edildi: {job_name} (ID: {job_id}, Süre: {elapsed_minutes} dk)",
                            "ml_training"
                        )
                    
                    if killed_count > 0:
                        conn.commit()
                        
                        # Memory'deki thread referanslarını temizle
                        self._current_job_id = None
                        self._training_thread = None
                        
        except Exception as e:
            log_error(f"Stale jobs kill hatası: {e}", "ml_training")
        
        return killed_count
    
    # ========================================
    # Job Execution → ml_training/job_runner.py (v2.30.1)
    # ========================================
    # Mixin'den gelir: start_training, _create_job, _run_training, etc.

    
    # ============================================
    # Scheduled Jobs
    # ============================================
    
    # ========================================
    # Scheduling → ml_training/scheduling.py (v2.30.1)
    # ========================================
    # Mixin'den gelir: get_schedule, save_hybrid_schedules, check_scheduled_trigger, etc.



# Singleton instance
_ml_training_service = None

def get_ml_training_service() -> MLTrainingService:
    """MLTrainingService singleton instance döndür"""
    global _ml_training_service
    if _ml_training_service is None:
        _ml_training_service = MLTrainingService()
    return _ml_training_service
