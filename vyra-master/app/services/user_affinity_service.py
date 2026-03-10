"""
VYRA L1 Support API - User Affinity Service
=============================================
Kullanıcı konu affinitesi yönetimi.
Kişiselleştirme için kullanıcının hangi konularda soru sorduğunu takip eder.

Author: VYRA AI Team
Version: 1.0.0 (v2.13.0)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error


# Topic anahtar kelimeleri (feature_extractor ile senkronize)
TOPIC_KEYWORDS = {
    'vpn': ['vpn', 'cisco', 'anyconnect', 'tunnel', 'bağlantı', 'remote'],
    'outlook': ['outlook', 'mail', 'email', 'e-posta', 'eposta', 'takvim'],
    'ldap': ['ldap', 'active directory', 'ad', 'kullanıcı', 'şifre', 'parola'],
    'network': ['ağ', 'network', 'internet', 'wifi', 'ethernet', 'ip'],
    'printer': ['yazıcı', 'printer', 'yazdırma', 'baskı', 'toner'],
    'software': ['yazılım', 'program', 'uygulama', 'kurulum', 'install'],
    'hardware': ['donanım', 'hardware', 'ekran', 'klavye', 'mouse', 'disk'],
    'security': ['güvenlik', 'virüs', 'antivirus', 'firewall', 'şifreleme'],
}

# Affinity güncelleme parametreleri
AFFINITY_INCREASE_ON_SUCCESS = 0.05  # Başarılı feedback
AFFINITY_DECREASE_ON_FAILURE = 0.03  # Başarısız feedback
AFFINITY_MIN = 0.1
AFFINITY_MAX = 0.95
AFFINITY_DEFAULT = 0.5


@dataclass
class UserAffinity:
    """Kullanıcı topic affinitesi"""
    user_id: int
    topic: str
    affinity_score: float
    query_count: int
    success_count: int
    updated_at: datetime


class UserAffinityService:
    """
    Kullanıcı Affinity Servisi.
    
    Özellikler:
    - Topic bazlı affinity takibi
    - Sorgu ve feedback bazlı affinity güncelleme
    - Kişiselleştirme için top topic'ler
    """
    
    def __init__(self):
        self._cache: Dict[int, Dict[str, float]] = {}
    
    # ============================================
    # Affinity Sorgulama
    # ============================================
    
    def get_user_affinity(self, user_id: int) -> Dict[str, float]:
        """
        Kullanıcının tüm topic affinitelerini getir.
        
        Returns:
            {topic: affinity_score, ...}
        """
        if user_id in self._cache:
            return self._cache[user_id]
        
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT topic, affinity_score
                        FROM user_topic_affinity
                        WHERE user_id = %s
                    """, (user_id,))
                    
                    affinity = {row['topic']: row['affinity_score'] for row in cur.fetchall()}
                    self._cache[user_id] = affinity
                    return affinity
                    
        except Exception as e:
            log_error(f"User affinity getirme hatası: {e}", "user_affinity_service")
            return {}
    
    def get_top_topics(self, user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Kullanıcının en ilgili olduğu topic'leri getir"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT topic, affinity_score, query_count, success_count
                        FROM user_topic_affinity
                        WHERE user_id = %s
                        ORDER BY affinity_score DESC
                        LIMIT %s
                    """, (user_id, limit))
                    
                    return [dict(row) for row in cur.fetchall()]
                    
        except Exception as e:
            log_error(f"Top topics hatası: {e}", "user_affinity_service")
            return []
    
    def get_user_profile(self, user_id: int) -> Dict[str, Any]:
        """Kullanıcının tam affinity profilini getir"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    # Affinity verileri
                    cur.execute("""
                        SELECT topic, affinity_score, query_count, success_count, updated_at
                        FROM user_topic_affinity
                        WHERE user_id = %s
                        ORDER BY affinity_score DESC
                    """, (user_id,))
                    
                    affinities = [dict(row) for row in cur.fetchall()]
                    
                    # Özet istatistikler
                    total_queries = sum(a['query_count'] for a in affinities)
                    total_success = sum(a['success_count'] for a in affinities)
                    
                    return {
                        "user_id": user_id,
                        "total_queries": total_queries,
                        "total_success": total_success,
                        "success_rate": total_success / total_queries if total_queries > 0 else 0.0,
                        "topic_count": len(affinities),
                        "affinities": affinities,
                        "top_topics": affinities[:3] if affinities else []
                    }
                    
        except Exception as e:
            log_error(f"User profile hatası: {e}", "user_affinity_service")
            return {"user_id": user_id, "error": str(e)}
    
    # ============================================
    # Affinity Güncelleme
    # ============================================
    
    def update_from_query(self, user_id: int, query_text: str, success: bool = True):
        """
        Sorgu metninden topic algıla ve affinity güncelle.
        
        Args:
            user_id: Kullanıcı ID
            query_text: Sorgu metni
            success: Feedback başarılı mı?
        """
        topic = self._detect_topic(query_text)
        if not topic or topic == 'general':
            return
        
        self.update_affinity(user_id, topic, success)
    
    def update_affinity(self, user_id: int, topic: str, success: bool):
        """
        Belirli bir topic için affinity güncelle.
        
        Args:
            user_id: Kullanıcı ID
            topic: Konu
            success: Pozitif güncelleme mi?
        """
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    # Mevcut kaydı kontrol et
                    cur.execute("""
                        SELECT id, affinity_score, query_count, success_count
                        FROM user_topic_affinity
                        WHERE user_id = %s AND topic = %s
                    """, (user_id, topic))
                    
                    row = cur.fetchone()
                    
                    if row:
                        # Mevcut kaydı güncelle
                        current_score = row['affinity_score']
                        query_count = row['query_count'] + 1
                        success_count = row['success_count'] + (1 if success else 0)
                        
                        # Affinity skorunu güncelle
                        if success:
                            new_score = min(current_score + AFFINITY_INCREASE_ON_SUCCESS, AFFINITY_MAX)
                        else:
                            new_score = max(current_score - AFFINITY_DECREASE_ON_FAILURE, AFFINITY_MIN)
                        
                        cur.execute("""
                            UPDATE user_topic_affinity
                            SET affinity_score = %s, query_count = %s, success_count = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (new_score, query_count, success_count, row['id']))
                    else:
                        # Yeni kayıt oluştur
                        initial_score = AFFINITY_DEFAULT + (AFFINITY_INCREASE_ON_SUCCESS if success else -AFFINITY_DECREASE_ON_FAILURE)
                        initial_score = max(AFFINITY_MIN, min(initial_score, AFFINITY_MAX))
                        
                        cur.execute("""
                            INSERT INTO user_topic_affinity 
                            (user_id, topic, affinity_score, query_count, success_count)
                            VALUES (%s, %s, %s, 1, %s)
                        """, (user_id, topic, initial_score, 1 if success else 0))
                    
                    conn.commit()
                    
                    # Cache'i temizle
                    if user_id in self._cache:
                        del self._cache[user_id]
                    
                    log_system_event(
                        "DEBUG",
                        f"Affinity güncellendi: user={user_id}, topic={topic}, success={success}",
                        "user_affinity_service"
                    )
                    
        except Exception as e:
            log_error(f"Affinity güncelleme hatası: {e}", "user_affinity_service")
    
    # ============================================
    # Topic Algılama
    # ============================================
    
    def _detect_topic(self, text: str) -> str:
        """Metinden topic algıla"""
        text_lower = text.lower()
        
        for topic, keywords in TOPIC_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return topic
        
        return 'general'
    
    # ============================================
    # Cache Yönetimi
    # ============================================
    
    def clear_cache(self, user_id: Optional[int] = None):
        """Cache'i temizle"""
        if user_id:
            self._cache.pop(user_id, None)
        else:
            self._cache.clear()
    
    # ============================================
    # Toplu İşlemler
    # ============================================
    
    def recalculate_all_affinities(self):
        """Tüm kullanıcıların affinitelerini feedback verilerinden yeniden hesapla"""
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    # Feedback verilerinden topic istatistiklerini hesapla
                    cur.execute("""
                        SELECT 
                            uf.user_id,
                            rc.topic_label as topic,
                            COUNT(*) as total,
                            COUNT(CASE WHEN uf.feedback_type = 'helpful' THEN 1 END) as helpful
                        FROM user_feedback uf
                        JOIN rag_chunks rc ON uf.chunk_id = rc.id
                        WHERE rc.topic_label IS NOT NULL
                        GROUP BY uf.user_id, rc.topic_label
                    """)
                    
                    rows = cur.fetchall()
                    
                    for row in rows:
                        user_id = row['user_id']
                        topic = row['topic']
                        total = row['total']
                        helpful = row['helpful']
                        
                        # Affinity skoru hesapla
                        if total > 0:
                            success_rate = helpful / total
                            affinity_score = AFFINITY_MIN + (AFFINITY_MAX - AFFINITY_MIN) * success_rate
                        else:
                            affinity_score = AFFINITY_DEFAULT
                        
                        # Upsert
                        cur.execute("""
                            INSERT INTO user_topic_affinity 
                            (user_id, topic, affinity_score, query_count, success_count)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (user_id, topic) 
                            DO UPDATE SET 
                                affinity_score = EXCLUDED.affinity_score,
                                query_count = EXCLUDED.query_count,
                                success_count = EXCLUDED.success_count,
                                updated_at = NOW()
                        """, (user_id, topic, affinity_score, total, helpful))
                    
                    conn.commit()
                    
                    log_system_event(
                        "INFO",
                        f"Affinity recalculation tamamlandı: {len(rows)} kayıt",
                        "user_affinity_service"
                    )
                    
                    # Cache'i temizle
                    self._cache.clear()
                    
        except Exception as e:
            log_error(f"Affinity recalculation hatası: {e}", "user_affinity_service")


# Singleton instance
_user_affinity_service: Optional[UserAffinityService] = None


def get_user_affinity_service() -> UserAffinityService:
    """User Affinity Service singleton instance döndürür"""
    global _user_affinity_service
    if _user_affinity_service is None:
        _user_affinity_service = UserAffinityService()
    return _user_affinity_service
