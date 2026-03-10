"""
VYRA L1 Support API - Feature Extractor Module
================================================
CatBoost reranking için feature extraction modülü.
RAG sonuçları, kullanıcı context'i ve sorgu özelliklerini çıkarır.

Author: VYRA AI Team
Version: 1.0.0 (v2.13.0)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np

from app.core.db import get_db_conn
from app.services.logging_service import log_error, log_warning


# ============================================
# Feature Tanımları
# ============================================

FEATURE_NAMES = [
    'cosine_similarity',     # RAG skoru
    'exact_match_bonus',     # 🔧 v2.20.7: Teknik terim exact match bonusu (APE, VPN vb.)
    'chunk_length',          # Chunk karakter sayısı
    'keyword_overlap',       # Sorgu-chunk kelime örtüşmesi
    'quality_score',         # Pre-computed chunk kalitesi
    'topic_match',           # Topic eşleşmesi (0/1)
    'user_topic_affinity',   # Kullanıcının topic ilgisi
    'chunk_recency_days',    # Chunk yaşı (gün)
    'historical_ctr',        # Geçmiş tıklama oranı
    'word_count',            # Chunk kelime sayısı
    'has_steps',             # Adım/liste içeriyor mu
    'has_code',              # Kod bloğu içeriyor mu
    'query_length',          # Sorgu uzunluğu
    'source_file_type',      # 🆕 v2.34.0: Dosya tipi (0=xlsx, 1=pdf, 2=docx, 3=pptx, 4=txt)
    'heading_match',         # 🆕 v2.34.0: Heading-sorgu keyword eşleşmesi
]

# Topic sınıflandırması için anahtar kelimeler
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

# 🆕 v2.34.0: Dosya tipi numeric encoding
FILE_TYPE_ENCODING = {
    '.xlsx': 0, '.xls': 0,
    '.pdf': 1,
    '.docx': 2, '.doc': 2,
    '.pptx': 3, '.ppt': 3,
    '.txt': 4, '.csv': 4, '.md': 4,
}


@dataclass
class FeatureVector:
    """Tek bir chunk için feature vektörü"""
    chunk_id: int
    features: Dict[str, float] = field(default_factory=dict)
    
    def to_array(self) -> np.ndarray:
        """Feature dictionary'yi numpy array'e çevir"""
        return np.array([self.features.get(name, 0.0) for name in FEATURE_NAMES])


class FeatureExtractor:
    """
    CatBoost Reranking için Feature Extraction Servisi.
    
    RAG arama sonuçlarından, kullanıcı context'inden ve sorgudan
    feature'lar çıkarır.
    """
    
    def __init__(self):
        self._user_affinity_cache: Dict[int, Dict[str, float]] = {}
        self._chunk_ctr_cache: Dict[int, float] = {}
        # 🆕 v2.34.0: Dinamik topic cache (DB'den yüklenir)
        self._dynamic_topics: Optional[Dict[str, List[str]]] = None
        self._dynamic_topics_loaded_at: float = 0
    
    # ============================================
    # Ana Metotlar
    # ============================================
    
    def build_feature_matrix(
        self,
        results: List[Dict[str, Any]],
        user_id: Optional[int],
        query: str
    ) -> tuple[np.ndarray, List[int]]:
        """
        RAG sonuçları için feature matrix oluştur.
        
        Args:
            results: RAG arama sonuçları
            user_id: Kullanıcı ID (kişiselleştirme için)
            query: Arama sorgusu
            
        Returns:
            (feature_matrix, chunk_ids) tuple'ı
        """
        if not results:
            return np.array([]), []
        
        # Kullanıcı affinitesini yükle
        user_affinity = {}
        if user_id:
            user_affinity = self._get_user_affinity(user_id)
        
        # Query features
        query_features = self._extract_query_features(query)
        query_topic = self._detect_topic(query)
        
        feature_vectors = []
        chunk_ids = []
        
        for result in results:
            chunk_id = result.get('chunk_id', 0)
            chunk_ids.append(chunk_id)
            
            # Her sonuç için feature vektörü oluştur
            fv = FeatureVector(chunk_id=chunk_id)
            
            # Chunk features
            chunk_features = self._extract_chunk_features(result)
            fv.features.update(chunk_features)
            
            # Query-chunk etkileşim features
            interaction_features = self._extract_interaction_features(
                result, query, query_features
            )
            fv.features.update(interaction_features)
            
            # Topic match
            chunk_topic = result.get('topic_label', '') or self._detect_topic(
                result.get('content', '') or result.get('chunk_text', '')
            )
            fv.features['topic_match'] = 1.0 if chunk_topic == query_topic else 0.0
            
            # User affinity
            if user_affinity and chunk_topic:
                fv.features['user_topic_affinity'] = user_affinity.get(chunk_topic, 0.5)
            else:
                fv.features['user_topic_affinity'] = 0.5
            
            # Historical CTR
            fv.features['historical_ctr'] = self._get_chunk_ctr(chunk_id)
            
            # Query length
            fv.features['query_length'] = query_features.get('length', 0)
            
            feature_vectors.append(fv)
        
        # Numpy matrix'e çevir
        matrix = np.array([fv.to_array() for fv in feature_vectors])
        
        return matrix, chunk_ids
    
    # ============================================
    # Chunk Feature Extraction
    # ============================================
    
    def _extract_chunk_features(self, result: Dict[str, Any]) -> Dict[str, float]:
        """Chunk'tan feature çıkar"""
        content = result.get('content', '') or result.get('chunk_text', '')
        metadata = result.get('metadata') or {}
        
        # 🆕 v2.34.0: file_type encoding
        file_type = metadata.get('file_type', '') or result.get('file_type', '')
        file_type_num = FILE_TYPE_ENCODING.get(file_type.lower(), 5)  # 5 = bilinmeyen
        
        # 🆕 v2.34.0: Heading match (metadata'daki heading varsa)
        heading = metadata.get('heading', '')
        
        features = {
            'cosine_similarity': float(result.get('score', 0.0)),
            # 🔧 v2.20.7: exact_bonus RAG'dan gelen değeri kullan
            'exact_match_bonus': float(result.get('exact_bonus', 0.0)),
            'chunk_length': len(content),
            'quality_score': float(result.get('quality_score', 0.5)),
            'word_count': len(content.split()),
            'has_steps': self._has_steps(content),
            'has_code': self._has_code(content),
            'has_heading_match': 1 if heading else 0,
            'chunk_recency_days': self._calculate_recency(result),
            'source_file_type': float(file_type_num),  # 🆕 v2.34.0
            'heading_match': 0.0,  # Sonra interaction_features'da güncellenir
        }
        
        return features
    
    def _extract_query_features(self, query: str) -> Dict[str, Any]:
        """Sorgudan feature çıkar"""
        words = query.lower().split()
        return {
            'length': len(query),
            'word_count': len(words),
            'words': set(words),
            'keywords': self._extract_keywords(query),
        }
    
    def _extract_interaction_features(
        self,
        result: Dict[str, Any],
        query: str,
        query_features: Dict[str, Any]
    ) -> Dict[str, float]:
        """Sorgu-chunk etkileşim features"""
        content = result.get('content', '') or result.get('chunk_text', '')
        content_words = set(content.lower().split())
        query_words = query_features.get('words', set())
        
        # Keyword overlap hesapla
        if query_words:
            overlap = len(query_words & content_words) / len(query_words)
        else:
            overlap = 0.0
        
        # 🆕 v2.34.0: Heading match — heading'deki keyword eşleşmesi
        metadata = result.get('metadata') or {}
        heading = (metadata.get('heading', '') or '').lower()
        heading_match = 0.0
        if heading and query_words:
            heading_words = set(heading.split())
            heading_overlap = len(query_words & heading_words)
            heading_match = min(heading_overlap / max(len(query_words), 1), 1.0)
        
        return {
            'keyword_overlap': overlap,
            'heading_match': heading_match,  # 🆕 v2.34.0
        }
    
    # ============================================
    # Yardımcı Metotlar
    # ============================================
    
    def _detect_topic(self, text: str) -> str:
        """Metinden topic algıla (önce dinamik DB topic'leri, sonra statik)"""
        text_lower = text.lower()
        
        # 🆕 v2.34.0: Önce dinamik topic'lere bak (DB'den)
        dynamic_topics = self._load_dynamic_topics()
        if dynamic_topics:
            for topic, keywords in dynamic_topics.items():
                for keyword in keywords:
                    if keyword in text_lower:
                        return topic
        
        # Statik topic listesi (fallback)
        for topic, keywords in TOPIC_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return topic
        
        return 'general'
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Metinden anahtar kelimeleri çıkar"""
        # Stop words (Türkçe)
        stop_words = {'bir', 'bu', 've', 'ile', 'için', 'de', 'da', 'ne', 'nasıl', 'neden'}
        
        words = re.findall(r'\b\w+\b', text.lower())
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]
        
        return keywords
    
    def _has_steps(self, content: str) -> float:
        """İçerikte adım/liste var mı?"""
        # Numaralı liste veya bullet point kontrolü
        patterns = [
            r'\d+[\.\)]\s',  # 1. veya 1) 
            r'[-•]\s',       # - veya •
            r'adım\s*\d+',   # adım 1, adım 2
        ]
        
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return 1.0
        
        return 0.0
    
    def _has_code(self, content: str) -> float:
        """İçerikte kod bloğu var mı?"""
        code_indicators = ['```', '`', 'import ', 'def ', 'function', 'class ', '=>', '->']
        
        for indicator in code_indicators:
            if indicator in content:
                return 1.0
        
        return 0.0
    
    def _calculate_recency(self, result: Dict[str, Any]) -> float:
        """Chunk yaşını gün olarak hesapla"""
        from datetime import datetime, timezone
        
        created_at = result.get('created_at')
        if not created_at:
            return 365.0  # Varsayılan: 1 yıl
        
        try:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            
            now = datetime.now(timezone.utc)
            delta = now - created_at.replace(tzinfo=timezone.utc)
            return min(delta.days, 365.0)
        except Exception as e:
            log_warning(f"Chunk recency hesaplama hatası: {e}", "feature_extractor")
            return 365.0
    
    # ============================================
    # Veritabanı Etkileşimleri
    # ============================================
    
    def _get_user_affinity(self, user_id: int) -> Dict[str, float]:
        """Kullanıcının topic affinitesini getir"""
        if user_id in self._user_affinity_cache:
            return self._user_affinity_cache[user_id]
        
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT topic, affinity_score
                        FROM user_topic_affinity
                        WHERE user_id = %s
                    """, (user_id,))
                    
                    rows = cur.fetchall()
                    affinity = {row['topic']: row['affinity_score'] for row in rows}
                    
                    self._user_affinity_cache[user_id] = affinity
                    return affinity
        except Exception as e:
            log_error(f"User affinity getirilemedi: {e}", "feature_extractor")
            return {}
    
    def _get_chunk_ctr(self, chunk_id: int) -> float:
        """Chunk'ın geçmiş CTR'ını getir"""
        if chunk_id in self._chunk_ctr_cache:
            return self._chunk_ctr_cache[chunk_id]
        
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            COUNT(CASE WHEN feedback_type = 'helpful' THEN 1 END) as helpful,
                            COUNT(*) as total
                        FROM user_feedback
                        WHERE chunk_id = %s
                    """, (chunk_id,))
                    
                    row = cur.fetchone()
                    if row and row['total'] > 0:
                        ctr = row['helpful'] / row['total']
                    else:
                        ctr = 0.5  # Varsayılan (nötr)
                    
                    self._chunk_ctr_cache[chunk_id] = ctr
                    return ctr
        except Exception as e:
            log_error(f"Chunk CTR getirilemedi: {e}", "feature_extractor")
            return 0.5
    
    def clear_cache(self):
        """Cache'leri temizle"""
        self._user_affinity_cache.clear()
        self._chunk_ctr_cache.clear()
        self._dynamic_topics = None  # 🆕 v2.34.0
    
    # ============================================
    # 🆕 v2.34.0: Dinamik Topic Sistemi
    # ============================================
    
    def _load_dynamic_topics(self) -> Dict[str, List[str]]:
        """
        DB'den dinamik topic keyword'lerini yükler.
        5 dakika TTL ile cache'lenir.
        """
        import time as _time
        
        # Cache kontrolü (5 dk TTL)
        if self._dynamic_topics is not None:
            if (_time.time() - self._dynamic_topics_loaded_at) < 300:
                return self._dynamic_topics
        
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT topic_name, keywords 
                        FROM document_topics
                        WHERE keywords IS NOT NULL AND array_length(keywords, 1) > 0
                        ORDER BY topic_name
                    """)
                    rows = cur.fetchall()
                    
                    topics = {}
                    for row in rows:
                        topics[row['topic_name']] = row['keywords']
                    
                    self._dynamic_topics = topics
                    self._dynamic_topics_loaded_at = _time.time()
                    return topics
        except Exception as e:
            # Tablo yoksa veya hata olursa boş dön (statik fallback kullanılır)
            log_error(f"Dinamik topic yükleme hatası: {e}", "feature_extractor")
            self._dynamic_topics = {}
            self._dynamic_topics_loaded_at = _time.time()
            return {}


# Singleton instance
_feature_extractor: Optional[FeatureExtractor] = None


def get_feature_extractor() -> FeatureExtractor:
    """Feature Extractor singleton instance döndürür"""
    global _feature_extractor
    if _feature_extractor is None:
        _feature_extractor = FeatureExtractor()
    return _feature_extractor
