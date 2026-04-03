"""
VYRA ML Training - Job Runner Module
======================================
Eğitim job execution, status yönetimi, script çalıştırma.
v2.30.1: ml_training_service.py'den ayrıştırıldı
"""

from __future__ import annotations
import subprocess
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from app.core.db import get_db_context
from app.services.logging_service import log_system_event, log_error, log_warning


# Proje kök dizini (D:\VYRA)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class MLJobRunnerMixin:
    """Job execution methods for MLTrainingService (Mixin pattern)."""

    def start_training(self, user_id: int, trigger: str = "manual") -> Dict[str, Any]:
        """
        Eğitimi başlat (async thread'de)
        
        Args:
            user_id: Eğitimi başlatan kullanıcı
            trigger: 'manual' veya 'feedback_count:500'
        """
        if self.is_training():
            return {
                "success": False,
                "error": "Eğitim zaten devam ediyor",
                "job_id": self._current_job_id
            }
        
        # Job kaydı oluştur
        job_id = self._create_job(user_id, trigger)
        if not job_id:
            return {"success": False, "error": "Job oluşturulamadı"}
        
        self._current_job_id = job_id
        
        # Thread'de eğitimi başlat
        self._training_thread = threading.Thread(
            target=self._run_training,
            args=(job_id,),
            daemon=True
        )
        self._training_thread.start()
        
        log_system_event("INFO", f"Model eğitimi başlatıldı. Job ID: {job_id}", "ml_training")
        
        return {
            "success": True,
            "job_id": job_id,
            "message": "Eğitim arka planda başlatıldı"
        }
    
    def _create_job(self, user_id: int, trigger: str) -> Optional[int]:
        """Eğitim job kaydı oluştur"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    job_name = f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    job_type = "manual" if trigger == "manual" else "scheduled"
                    
                    cur.execute("""
                        INSERT INTO ml_training_jobs 
                        (job_name, job_type, status, trigger_condition, created_by)
                        VALUES (%s, %s, 'pending', %s, %s)
                        RETURNING id
                    """, (job_name, job_type, trigger, user_id))
                    
                    job_id = cur.fetchone()["id"]
                    conn.commit()
                    return job_id
        except Exception as e:
            log_error(f"Job oluşturma hatası: {e}", "ml_training")
            return None
    
    def _run_training(self, job_id: int):
        """Eğitim scriptini çalıştır (thread içinde)"""
        start_time = datetime.now()
        timeout_min = self.get_job_timeout_setting() or 60  # Varsayılan 60 dk
        
        try:
            # Job durumunu güncelle
            self._update_job_status(job_id, "running", start_time=start_time)
            
            # train_model.py scriptini çalıştır
            script_path = PROJECT_ROOT / "scripts" / "train_model.py"
            
            # Timeout: dakika → saniye (0 = sınırsız)
            timeout_sec = timeout_min * 60 if timeout_min > 0 else None
            
            result = subprocess.run(
                [sys.executable, str(script_path), "--min-samples", "30", "--job-id", str(job_id)],
                capture_output=True,
                text=True,
                timeout=timeout_sec
            )
            
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            
            if result.returncode == 0:
                # Başarılı
                # Model ID'yi bul
                model_id = self._get_latest_model_id()
                samples = self._extract_samples_from_output(result.stdout, job_id=job_id)
                
                self._update_job_status(
                    job_id, "completed",
                    end_time=end_time,
                    duration=duration,
                    model_id=model_id,
                    samples=samples
                )
                
                log_system_event("INFO", f"Model eğitimi tamamlandı. Job ID: {job_id}, Süre: {duration}s", "ml_training")
            else:
                # Hata - stderr veya stdout'tan hata mesajını al
                error_msg = result.stderr[:500] if result.stderr else ""
                if not error_msg and result.stdout:
                    # Script stdout'a yazdıysa (print ile) oradan al
                    error_msg = result.stdout[-500:] if len(result.stdout) > 500 else result.stdout
                if not error_msg:
                    error_msg = "Bilinmeyen hata (exit code: " + str(result.returncode) + ")"
                
                self._update_job_status(
                    job_id, "failed",
                    end_time=end_time,
                    duration=duration,
                    error=error_msg
                )
                
                log_error(f"Model eğitimi başarısız. Job ID: {job_id}, Hata: {error_msg}", "ml_training")
                
        except subprocess.TimeoutExpired:
            timeout_msg = f"Eğitim zaman aşımına uğradı ({timeout_min} dk)"
            self._update_job_status(job_id, "failed", error=timeout_msg)
            log_error(f"Model eğitimi timeout. Job ID: {job_id}, Limit: {timeout_min}dk", "ml_training")
            
        except Exception as e:
            self._update_job_status(job_id, "failed", error=str(e))
            log_error(f"Model eğitimi hatası: {e}", "ml_training")
        
        finally:
            self._current_job_id = None
    
    def _update_job_status(
        self, 
        job_id: int, 
        status: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        duration: Optional[int] = None,
        model_id: Optional[int] = None,
        samples: Optional[int] = None,
        error: Optional[str] = None
    ):
        """Job durumunu güncelle"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    updates = ["status = %s"]
                    params = [status]
                    
                    if start_time:
                        updates.append("start_time = %s")
                        params.append(start_time)
                    if end_time:
                        updates.append("end_time = %s")
                        params.append(end_time)
                    if duration is not None:
                        updates.append("duration_seconds = %s")
                        params.append(duration)
                    if model_id:
                        updates.append("model_id = %s")
                        params.append(model_id)
                    if samples is not None:
                        updates.append("training_samples = %s")
                        params.append(samples)
                    if error:
                        updates.append("error_message = %s")
                        params.append(error)
                    
                    params.append(job_id)
                    
                    cur.execute(f"""
                        UPDATE ml_training_jobs
                        SET {', '.join(updates)}
                        WHERE id = %s
                    """, params)
                    conn.commit()
        except Exception as e:
            log_error(f"Job status güncelleme hatası: {e}", "ml_training")
    
    def _get_latest_model_id(self) -> Optional[int]:
        """En son eğitilen modelin ID'sini al"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM ml_models
                        WHERE is_active = TRUE
                        ORDER BY trained_at DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    return row["id"] if row else None
        except Exception as e:
            log_error(f"Son model ID alma hatası: {e}", "ml_training")
            return None
    
    def _extract_samples_from_output(self, output: str, job_id: int = None) -> int:
        """
        Script çıktısından veya DB'den sample sayısını çıkar.
        v3.3.1: Önce DB'den gerçek sayıyı oku (güvenilir), sonra stdout parse (fallback).
        """
        # 1. DB'den gerçek sayıyı kontrol et (en güvenilir)
        if job_id:
            try:
                with get_db_context() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT COUNT(*) as cnt FROM ml_training_samples WHERE job_id = %s",
                            (job_id,)
                        )
                        row = cur.fetchone()
                        if row and row['cnt'] > 0:
                            return row['cnt']
            except Exception as e:
                log_system_event("DEBUG", f"DB sample count hatası: {e}", "ml_training")
        
        # 2. Stdout parse fallback
        try:
            # "Veri boyutu: (1234, 12)" formatından çıkar
            import re
            match = re.search(r"Veri boyutu:\s*\((\d+),", output)
            if match:
                return int(match.group(1))
        except Exception as e:
            log_error(f"Sample sayısı çıkarma hatası: {e}", "ml_training")
        return 0
    
    def _get_required_feedback_count(self) -> int:
        """
        DB'deki feedback_count schedule ayarından gerekli feedback sayısını al.
        Ayar yoksa default 50 döner.
        """
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # is_active kontrolü kaldırıldı - schedule ayarı ne olursa olsun değeri al
                    cur.execute("""
                        SELECT trigger_value 
                        FROM ml_training_schedules 
                        WHERE trigger_type = 'feedback_count'
                        ORDER BY id DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    if row:
                        value = int(row["trigger_value"])
                        log_system_event("DEBUG", f"DB'den feedback_count değeri: {value}", "ml_training")
                        return value
                    else:
                        log_system_event("DEBUG", "DB'de feedback_count schedule bulunamadı", "ml_training")
        except Exception as e:
            log_error(f"Required feedback count okuma hatası: {e}", "ml_training")
        
        return 50  # Default değer
    
    def get_job_timeout_setting(self) -> int:
        """
        DB'deki job_timeout schedule ayarından timeout süresini al.
        Ayar kapalıysa veya yoksa 0 döner (timeout devre dışı).
        Ayar aktifse dakika cinsinden değer döner, varsayılan 60.
        """
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT trigger_value, is_active
                        FROM ml_training_schedules 
                        WHERE trigger_type = 'job_timeout'
                        ORDER BY id DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    if row:
                        if row["is_active"]:
                            value = int(row["trigger_value"])
                            return value
                        else:
                            # Timeout devre dışı
                            return 0
        except Exception as e:
            log_error(f"Job timeout setting okuma hatası: {e}", "ml_training")
        
        return 60  # Default: 60 dakika
    
    # ============================================
    # Training History
    # ============================================
    
    def get_training_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Eğitim geçmişini getir"""
        history = []
        
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            j.id, j.job_name, j.job_type, j.status,
                            j.trigger_condition, j.start_time, j.end_time,
                            j.duration_seconds, j.training_samples,
                            j.error_message, j.created_at,
                            m.model_version
                        FROM ml_training_jobs j
                        LEFT JOIN ml_models m ON j.model_id = m.id
                        ORDER BY j.created_at DESC
                        LIMIT %s
                    """, (limit,))
                    
                    for row in cur.fetchall():
                        history.append({
                            "id": row["id"],
                            "name": row["job_name"],
                            "type": row["job_type"],
                            "status": row["status"],
                            "trigger": row["trigger_condition"],
                            "start_time": row["start_time"].isoformat() if row["start_time"] else None,
                            "end_time": row["end_time"].isoformat() if row["end_time"] else None,
                            "duration": row["duration_seconds"],
                            "samples": row["training_samples"],
                            "error": row["error_message"],
                            "model_version": row["model_version"],
                            "created_at": row["created_at"].isoformat() if row["created_at"] else None
                        })
                        
        except Exception as e:
            log_error(f"Training history hatası: {e}", "ml_training")
        
        return history
    
    def get_current_job_status(self) -> Optional[Dict[str, Any]]:
        """Çalışan job durumunu al — v3.3.2: type bilgisi + DB fallback"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # Önce kendi job_id varsa onu kontrol et
                    target_id = self._current_job_id
                    
                    if target_id:
                        cur.execute("""
                            SELECT id, job_name, job_type, status, start_time
                            FROM ml_training_jobs
                            WHERE id = %s
                        """, (target_id,))
                    else:
                        # Kendi job_id yoksa DB'den running job bul (CL veya scheduled)
                        cur.execute("""
                            SELECT id, job_name, job_type, status, start_time
                            FROM ml_training_jobs
                            WHERE status = 'running'
                            ORDER BY id DESC
                            LIMIT 1
                        """)
                    
                    row = cur.fetchone()
                    if row:
                        elapsed = None
                        if row["start_time"]:
                            elapsed = int((datetime.now() - row["start_time"]).total_seconds())
                        
                        return {
                            "job_id": row["id"],
                            "name": row["job_name"],
                            "type": row["job_type"],
                            "status": row["status"],
                            "elapsed_seconds": elapsed
                        }
        except Exception as e:
            log_warning(f"Mevcut job durumu alma hatası: {e}", "ml_training")
        
        return None

