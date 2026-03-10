"""
VYRA L1 Support API - Feedback Service
========================================
Kullanıcı geri bildirim toplama ve işleme servisi.
Feedback loop ile model iyileştirme için veri toplama.

Author: VYRA AI Team
Version: 1.0.0 (v2.13.0)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error


# Feedback tipleri
FEEDBACK_TYPES = {
    'helpful': 'Cevap işe yaradı',
    'not_helpful': 'Cevap işe yaramadı',
    'copied': 'Cevap kopyalandı',
    'partial': 'Kısmen faydalı',
}


@dataclass
class FeedbackStats:
    """Kullanıcı feedback istatistikleri"""
    total_feedback: int
    helpful_count: int
    not_helpful_count: int
    helpfulness_rate: float
    recent_feedback: List[Dict[str, Any]]


class FeedbackService:
    """
    Kullanıcı Feedback Servisi.
    
    Özellikler:
    - Feedback kaydetme
    - İstatistik hesaplama
    - CTR hesaplama (chunk bazında)
    - Topic affinity güncelleme trigger
    """
    
    def __init__(self):
        pass
    
    # ============================================
    # Feedback Kaydetme
    # ============================================
    
    def record_feedback(
        self,
        user_id: int,
        feedback_type: str,
        ticket_id: Optional[int] = None,
        chunk_ids: Optional[List[int]] = None,
        query_text: Optional[str] = None,
        response_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Kullanıcı geri bildirimini kaydet.
        
        Args:
            user_id: Kullanıcı ID
            feedback_type: 'helpful', 'not_helpful', 'copied', 'partial'
            ticket_id: İlgili ticket ID
            chunk_ids: Kullanılan chunk ID'leri
            query_text: Kullanıcının sorgusu
            response_text: Verilen cevap
            
        Returns:
            Kayıt sonucu
        """
        if feedback_type not in FEEDBACK_TYPES:
            return {"success": False, "error": f"Geçersiz feedback tipi: {feedback_type}"}
        
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    # Her chunk için ayrı feedback kaydı
                    if chunk_ids:
                        for chunk_id in chunk_ids:
                            cur.execute("""
                                INSERT INTO user_feedback 
                                (user_id, ticket_id, chunk_id, feedback_type, query_text, response_text)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (user_id, ticket_id, chunk_id, feedback_type, query_text, response_text))
                    else:
                        # Chunk ID olmadan genel feedback
                        cur.execute("""
                            INSERT INTO user_feedback 
                            (user_id, ticket_id, chunk_id, feedback_type, query_text, response_text)
                            VALUES (%s, %s, NULL, %s, %s, %s)
                        """, (user_id, ticket_id, feedback_type, query_text, response_text))
                    
                    conn.commit()
                    
                    log_system_event(
                        "INFO",
                        f"Feedback kaydedildi: user={user_id}, type={feedback_type}, chunks={chunk_ids}",
                        "feedback_service"
                    )
                    
                    # Pozitif feedback ise topic affinity'yi güncelle
                    if feedback_type == 'helpful' and query_text:
                        self._update_topic_affinity(user_id, query_text, success=True)
                    elif feedback_type == 'not_helpful' and query_text:
                        self._update_topic_affinity(user_id, query_text, success=False)
                    
                    return {"success": True, "message": "Geri bildiriminiz kaydedildi"}
                    
        except Exception as e:
            log_error(f"Feedback kayıt hatası: {e}", "feedback_service")
            return {"success": False, "error": str(e)}
    
    # ============================================
    # İstatistikler
    # ============================================
    
    def get_user_stats(self, user_id: int, days: int = 30) -> FeedbackStats:
        """Kullanıcının feedback istatistiklerini getir"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    since_date = datetime.now() - timedelta(days=days)
                    
                    # Toplam ve tip bazında sayılar
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total,
                            COUNT(CASE WHEN feedback_type = 'helpful' THEN 1 END) as helpful,
                            COUNT(CASE WHEN feedback_type = 'not_helpful' THEN 1 END) as not_helpful
                        FROM user_feedback
                        WHERE user_id = %s AND created_at >= %s
                    """, (user_id, since_date))
                    
                    row = cur.fetchone()
                    total = row['total'] or 0
                    helpful = row['helpful'] or 0
                    not_helpful = row['not_helpful'] or 0
                    
                    # Helpfulness rate
                    rate = helpful / total if total > 0 else 0.0
                    
                    # Son 10 feedback
                    cur.execute("""
                        SELECT feedback_type, query_text, created_at
                        FROM user_feedback
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT 10
                    """, (user_id,))
                    
                    recent = [dict(row) for row in cur.fetchall()]
                    
                    return FeedbackStats(
                        total_feedback=total,
                        helpful_count=helpful,
                        not_helpful_count=not_helpful,
                        helpfulness_rate=rate,
                        recent_feedback=recent
                    )
                    
        except Exception as e:
            log_error(f"User stats hatası: {e}", "feedback_service")
            return FeedbackStats(
                total_feedback=0,
                helpful_count=0,
                not_helpful_count=0,
                helpfulness_rate=0.0,
                recent_feedback=[]
            )
    
    def get_chunk_ctr(self, chunk_id: int) -> Dict[str, Any]:
        """Chunk'ın CTR (Click-Through Rate) istatistiklerini getir"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total,
                            COUNT(CASE WHEN feedback_type = 'helpful' THEN 1 END) as helpful,
                            COUNT(CASE WHEN feedback_type = 'copied' THEN 1 END) as copied
                        FROM user_feedback
                        WHERE chunk_id = %s
                    """, (chunk_id,))
                    
                    row = cur.fetchone()
                    total = row['total'] or 0
                    helpful = row['helpful'] or 0
                    copied = row['copied'] or 0
                    
                    ctr = (helpful + copied) / total if total > 0 else 0.5
                    
                    return {
                        "chunk_id": chunk_id,
                        "total_feedback": total,
                        "helpful_count": helpful,
                        "copied_count": copied,
                        "ctr": ctr
                    }
                    
        except Exception as e:
            log_error(f"Chunk CTR hatası: {e}", "feedback_service")
            return {"chunk_id": chunk_id, "ctr": 0.5, "error": str(e)}
    
    def get_global_stats(self, days: int = 30) -> Dict[str, Any]:
        """Sistem geneli feedback istatistikleri"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    since_date = datetime.now() - timedelta(days=days)
                    
                    cur.execute("""
                        SELECT 
                            COUNT(*) as total,
                            COUNT(CASE WHEN feedback_type = 'helpful' THEN 1 END) as helpful,
                            COUNT(CASE WHEN feedback_type = 'not_helpful' THEN 1 END) as not_helpful,
                            COUNT(CASE WHEN feedback_type = 'copied' THEN 1 END) as copied,
                            COUNT(DISTINCT user_id) as unique_users
                        FROM user_feedback
                        WHERE created_at >= %s
                    """, (since_date,))
                    
                    row = cur.fetchone()
                    total = row['total'] or 0
                    helpful = row['helpful'] or 0
                    
                    return {
                        "period_days": days,
                        "total_feedback": total,
                        "helpful_count": helpful,
                        "not_helpful_count": row['not_helpful'] or 0,
                        "copied_count": row['copied'] or 0,
                        "unique_users": row['unique_users'] or 0,
                        "helpfulness_rate": helpful / total if total > 0 else 0.0
                    }
                    
        except Exception as e:
            log_error(f"Global stats hatası: {e}", "feedback_service")
            return {"error": str(e)}
    
    # ============================================
    # Topic Affinity Güncelleme
    # ============================================
    
    def _update_topic_affinity(self, user_id: int, query_text: str, success: bool):
        """Feedback'e göre topic affinity güncelle"""
        from app.services.user_affinity_service import get_user_affinity_service
        
        try:
            affinity_service = get_user_affinity_service()
            affinity_service.update_from_query(user_id, query_text, success)
        except Exception as e:
            log_error(f"Topic affinity güncelleme hatası: {e}", "feedback_service")
    
    # ============================================
    # Training Data Export
    # ============================================
    
    def export_training_data(self, min_samples: int = 100) -> List[Dict[str, Any]]:
        """Model eğitimi için feedback verilerini dışa aktar"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            uf.user_id,
                            uf.chunk_id,
                            uf.feedback_type,
                            uf.query_text,
                            rc.chunk_text,
                            rc.quality_score,
                            rc.topic_label
                        FROM user_feedback uf
                        LEFT JOIN rag_chunks rc ON uf.chunk_id = rc.id
                        WHERE uf.chunk_id IS NOT NULL
                        ORDER BY uf.created_at DESC
                        LIMIT %s
                    """, (min_samples * 10,))  # Daha fazla al, filtrele
                    
                    return [dict(row) for row in cur.fetchall()]
                    
        except Exception as e:
            log_error(f"Training data export hatası: {e}", "feedback_service")
            return []


# Singleton instance
_feedback_service: Optional[FeedbackService] = None


def get_feedback_service() -> FeedbackService:
    """Feedback Service singleton instance döndürür"""
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = FeedbackService()
    return _feedback_service
