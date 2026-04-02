"""
VYRA ML Training - Scheduling Module
======================================
Schedule yönetimi, trigger kontrolleri, feedback kalite hesaplama.
v2.30.1: ml_training_service.py'den ayrıştırıldı
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any

from app.core.db import get_db_context
from app.services.logging_service import log_system_event, log_error, log_warning


class MLSchedulingMixin:
    """Schedule-related methods for MLTrainingService (Mixin pattern)."""

    def get_schedule(self) -> Optional[Dict[str, Any]]:
        """Aktif schedule bilgisini al"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, schedule_name, trigger_type, trigger_value,
                               is_active, last_triggered_at, next_trigger_at
                        FROM ml_training_schedules
                        WHERE is_active = TRUE
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                    
                    row = cur.fetchone()
                    if row:
                        return {
                            "id": row["id"],
                            "name": row["schedule_name"],
                            "trigger_type": row["trigger_type"],
                            "trigger_value": row["trigger_value"],
                            "is_active": row["is_active"],
                            "last_triggered": row["last_triggered_at"].isoformat() if row["last_triggered_at"] else None,
                            "next_trigger": row["next_trigger_at"].isoformat() if row["next_trigger_at"] else None
                        }
        except Exception as e:
            log_error(f"Schedule get hatası: {e}", "ml_training")
        
        return None
    
    def get_all_schedules(self) -> List[Dict[str, Any]]:
        """Tüm schedule kayıtlarını getir (hibrit)"""
        schedules = []
        
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT trigger_type, trigger_value, is_active
                        FROM ml_training_schedules
                        ORDER BY trigger_type
                    """)
                    
                    for row in cur.fetchall():
                        schedules.append({
                            "trigger_type": row["trigger_type"],
                            "trigger_value": row["trigger_value"],
                            "is_active": row["is_active"]
                        })
        except Exception as e:
            log_error(f"Schedule get all hatası: {e}", "ml_training")
        
        return schedules
    
    def save_hybrid_schedules(
        self, 
        user_id: int,
        schedules: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Hibrit schedule ayarlarını kaydet"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # Mevcut schedule'ları temizle
                    cur.execute("DELETE FROM ml_training_schedules")
                    
                    # Her schedule'ı ekle
                    for s in schedules:
                        schedule_name = f"schedule_{s['trigger_type']}_{s['trigger_value']}"
                        
                        cur.execute("""
                            INSERT INTO ml_training_schedules
                            (schedule_name, trigger_type, trigger_value, is_active, created_by)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            schedule_name,
                            s["trigger_type"],
                            s["trigger_value"],
                            s["is_active"],
                            user_id
                        ))
                    
                    conn.commit()
                    
                    # Aktif koşulları logla
                    active_conditions = [s["trigger_type"] for s in schedules if s["is_active"]]
                    if active_conditions:
                        log_system_event(
                            "INFO", 
                            f"Hibrit schedule kaydedildi: {', '.join(active_conditions)}", 
                            "ml_training"
                        )
                    
                    return {"success": True, "saved_count": len(schedules)}
                    
        except Exception as e:
            log_error(f"Hybrid schedule save hatası: {e}", "ml_training")
            return {"success": False, "error": str(e)}
    
    def save_schedule(
        self, 
        user_id: int,
        trigger_type: str,
        trigger_value: str,
        is_active: bool
    ) -> Dict[str, Any]:
        """Schedule ayarını kaydet (legacy)"""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # Mevcut aktif schedule'ları deaktive et
                    cur.execute("UPDATE ml_training_schedules SET is_active = FALSE")
                    
                    if is_active:
                        # Yeni schedule oluştur
                        schedule_name = f"schedule_{trigger_type}_{trigger_value}"
                        
                        cur.execute("""
                            INSERT INTO ml_training_schedules
                            (schedule_name, trigger_type, trigger_value, is_active, created_by)
                            VALUES (%s, %s, %s, TRUE, %s)
                            RETURNING id
                        """, (schedule_name, trigger_type, trigger_value, user_id))
                        
                        schedule_id = cur.fetchone()[0]
                        conn.commit()
                        
                        log_system_event(
                            "INFO", 
                            f"Eğitim schedule kaydedildi: {trigger_type}={trigger_value}", 
                            "ml_training"
                        )
                        
                        return {"success": True, "schedule_id": schedule_id}
                    else:
                        conn.commit()
                        return {"success": True, "message": "Schedule deaktive edildi"}
                        
        except Exception as e:
            log_error(f"Schedule save hatası: {e}", "ml_training")
            return {"success": False, "error": str(e)}
    
    def check_scheduled_trigger(self) -> str | None:
        """
        Hibrit schedule tetikleme koşulunu kontrol et.
        Aktif olan HERHANGİ BİR koşul sağlanırsa tetikleyen koşulu string olarak döner.
        Hiçbir koşul sağlanmazsa None döner.
        
        Desteklenen trigger_type'lar:
        - feedback_count: Belirli sayıda feedback sonrası tetikle
        - interval_days: Belirli gün sayısı sonra tetikle
        - quality_drop: Feedback kalitesi düşerse tetikle
        
        Returns:
            str | None: Tetikleme nedeni (ör: "feedback_count:500") veya None
        """
        schedules = self.get_all_schedules()
        active_schedules = [s for s in schedules if s.get("is_active")]
        
        if not active_schedules:
            return None
        
        # cl_interval ve job_timeout tiplerine bakmayız — bunlar farklı amaçlı
        training_schedules = [
            s for s in active_schedules 
            if s.get("trigger_type") in ("feedback_count", "interval_days", "quality_drop")
        ]
        
        if not training_schedules:
            return None
        
        stats = self.get_training_stats()
        
        for schedule in training_schedules:
            trigger_type = schedule.get("trigger_type")
            trigger_value = schedule.get("trigger_value")
            
            try:
                if trigger_type == "feedback_count":
                    # Feedback sayısını kontrol et
                    feedback_since_last = stats.get("feedback_since_last_training", 0)
                    threshold = int(trigger_value)
                    
                    if feedback_since_last >= threshold:
                        log_system_event(
                            "INFO",
                            f"Scheduled training tetiklendi (feedback_count): {feedback_since_last} >= {threshold}",
                            "ml_training"
                        )
                        return f"feedback_count:{trigger_value}"
                        
                elif trigger_type == "interval_days":
                    # Son eğitimden bu yana geçen gün sayısını kontrol et
                    last_training = stats.get("last_training")
                    
                    if last_training and last_training.get("start_time"):
                        from datetime import datetime
                        _ = datetime  # suppress pyflakes
                        last_date = datetime.fromisoformat(last_training["start_time"])
                        days_passed = (datetime.now() - last_date).days
                        threshold_days = int(trigger_value)
                        
                        if days_passed >= threshold_days:
                            log_system_event(
                                "INFO",
                                f"Scheduled training tetiklendi (interval_days): {days_passed} gün >= {threshold_days} gün",
                                "ml_training"
                            )
                            return f"interval_days:{trigger_value}"
                    # NOT: Hiç eğitim yoksa sürekli öğrenme zaten hallediyor,
                    # burada gereksiz tetikleme yapılmamalı.
                        
                elif trigger_type == "quality_drop":
                    # Son N feedback'in kalitesini kontrol et
                    quality_threshold = float(trigger_value)
                    recent_quality = self._calculate_recent_quality()
                    
                    if recent_quality is not None and recent_quality < quality_threshold:
                        # Cooldown: Son eğitimden beri yeni feedback gelmemişse tekrar tetikleme
                        # (Aynı feedbacklerle sonsuz eğitim döngüsünü önler)
                        feedback_since_last = stats.get("feedback_since_last_training", 0)
                        if feedback_since_last == 0 and stats.get("last_training"):
                            log_system_event(
                                "DEBUG",
                                f"quality_drop koşulu sağlandı ({recent_quality:.2f} < {quality_threshold}) "
                                f"ama son eğitimden beri yeni feedback yok, atlanıyor",
                                "ml_training"
                            )
                        else:
                            log_system_event(
                                "INFO",
                                f"Scheduled training tetiklendi (quality_drop): {recent_quality:.2f} < {quality_threshold}",
                                "ml_training"
                            )
                            return f"quality_drop:{trigger_value}"
                        
            except Exception as e:
                log_error(f"Schedule trigger kontrol hatası ({trigger_type}): {e}", "ml_training")
        
        return None
    
    def _calculate_recent_quality(self, sample_size: int = 100) -> Optional[float]:
        """
        Son N ticket'taki feedback oranını hesapla.
        Kalite = pozitif feedback / toplam feedback
        """
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            COUNT(CASE WHEN feedback_type = 'positive' THEN 1 END) as positive,
                            COUNT(*) as total
                        FROM (
                            SELECT feedback_type
                            FROM user_feedback
                            ORDER BY created_at DESC
                            LIMIT %s
                        ) AS recent
                    """, (sample_size,))
                    
                    row = cur.fetchone()
                    if row and row["total"] > 0:
                        return row["positive"] / row["total"]
        except Exception as e:
            log_warning(f"Feedback kalite hesaplama hatası: {e}", "ml_training")
        
        return None

