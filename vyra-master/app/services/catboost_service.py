"""
VYRA L1 Support API - CatBoost Reranking Service
=================================================
CatBoost tabanlı RAG sonuç reranking servisi.
Model yükleme, inference ve fallback mekanizması.

Author: VYRA AI Team
Version: 1.0.0 (v2.13.0)
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np

from app.core.config import settings, BASE_DIR
from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error, log_warning
from app.services.feature_extractor import get_feature_extractor, FEATURE_NAMES


# Model dosyaları için dizin
MODELS_DIR = BASE_DIR / "models"


@dataclass
class RerankResult:
    """Reranking sonucu"""
    chunk_id: int
    original_score: float
    rerank_score: float
    combined_score: float
    rank: int


class CatBoostRerankingService:
    """
    CatBoost tabanlı RAG Reranking Servisi.
    
    Özellikler:
    - Lazy model loading
    - Graceful fallback (model yoksa mevcut davranış)
    - Batch inference
    - Model versioning
    """
    
    def __init__(self):
        self._model = None
        self._model_loaded = False
        self._model_version: Optional[str] = None
        self._feature_extractor = get_feature_extractor()
        
        # Model ağırlıkları (combined score için)
        # v2.44.0: 0.7/0.3 → 0.5/0.5 dengelendi (model olgunlaştıkça CatBoost ağırlığı artırılabilir)
        self.original_weight = 0.5  # RAG skoru ağırlığı
        self.rerank_weight = 0.5    # CatBoost skoru ağırlığı
    
    # ============================================
    # Model Yönetimi
    # ============================================
    
    def is_ready(self) -> bool:
        """Model yüklü ve kullanıma hazır mı?"""
        if self._model_loaded:
            return self._model is not None
        
        # İlk kez kontrol - model yüklemeyi dene
        return self._try_load_model()
    
    def _try_load_model(self) -> bool:
        """Aktif modeli yüklemeyi dene"""
        try:
            # Veritabanından aktif modeli bul
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT model_path, model_version, model_name
                        FROM ml_models
                        WHERE is_active = TRUE AND model_type = 'catboost'
                        ORDER BY trained_at DESC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    
                    if not row:
                        log_system_event(
                            "INFO", 
                            "CatBoost: Aktif model bulunamadı, fallback modda çalışılacak",
                            "catboost_service"
                        )
                        self._model_loaded = True
                        return False
                    
                    model_path = row['model_path']
                    
                    # Model dosyası var mı?
                    if not os.path.exists(model_path):
                        log_warning(
                            f"CatBoost: Model dosyası bulunamadı: {model_path}",
                            "catboost_service"
                        )
                        self._model_loaded = True
                        return False
                    
                    # CatBoost'u import et ve modeli yükle
                    from catboost import CatBoostRanker
                    
                    self._model = CatBoostRanker()
                    self._model.load_model(model_path)
                    self._model_version = row['model_version']
                    self._model_loaded = True
                    
                    log_system_event(
                        "INFO",
                        f"CatBoost: Model yüklendi (v{self._model_version})",
                        "catboost_service"
                    )
                    return True
                    
        except ImportError:
            log_warning(
                "CatBoost kütüphanesi yüklü değil, fallback modda çalışılacak",
                "catboost_service"
            )
            self._model_loaded = True
            return False
            
        except Exception as e:
            log_error(f"CatBoost model yükleme hatası: {e}", "catboost_service")
            self._model_loaded = True
            return False
    
    def load_model(self, model_path: str) -> bool:
        """Belirli bir model dosyasını yükle"""
        try:
            from catboost import CatBoostRanker
            
            if not os.path.exists(model_path):
                log_error(f"Model dosyası bulunamadı: {model_path}", "catboost_service")
                return False
            
            self._model = CatBoostRanker()
            self._model.load_model(model_path)
            self._model_loaded = True
            
            log_system_event("INFO", f"CatBoost: Model yüklendi: {model_path}", "catboost_service")
            return True
            
        except Exception as e:
            log_error(f"Model yükleme hatası: {e}", "catboost_service")
            return False
    
    def get_model_info(self) -> Dict[str, Any]:
        """Model bilgilerini döndür"""
        return {
            "is_ready": self.is_ready(),
            "model_loaded": self._model_loaded,
            "model_version": self._model_version,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": FEATURE_NAMES,
        }
    
    # ============================================
    # Inference
    # ============================================
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        Feature matrix için skor tahmin et.
        
        Args:
            features: (n_samples, n_features) numpy array
            
        Returns:
            (n_samples,) numpy array - rerank skorları
        """
        if self._model is None:
            # Model yok, dummy score döndür (cosine similarity'yi kullan)
            return features[:, 0] if features.shape[1] > 0 else np.zeros(features.shape[0])
        
        try:
            # 🆕 v2.34.0: Feature sayısı uyumsuzluğu koruması
            # Eski model 13 feature beklerken yeni extractor 15 üretebilir
            expected_features = self._model.feature_count_ if hasattr(self._model, 'feature_count_') else features.shape[1]
            if features.shape[1] != expected_features:
                if features.shape[1] > expected_features:
                    # Fazla feature'ları kırp (eski model yeni feature'ları görmez)
                    features = features[:, :expected_features]
                else:
                    # Eksik feature için 0 pad (olmaması gereken durum)
                    pad = np.zeros((features.shape[0], expected_features - features.shape[1]))
                    features = np.hstack([features, pad])
            
            return self._model.predict(features)
        except Exception as e:
            log_error(f"CatBoost predict hatası: {e}", "catboost_service")
            return features[:, 0] if features.shape[1] > 0 else np.zeros(features.shape[0])
    
    # ============================================
    # Reranking
    # ============================================
    
    def rerank_results(
        self,
        results: List[Dict[str, Any]],
        user_id: Optional[int],
        query: str
    ) -> List[Dict[str, Any]]:
        """
        RAG sonuçlarını CatBoost ile yeniden sırala.
        
        Args:
            results: RAG arama sonuçları (dict listesi)
            user_id: Kullanıcı ID (kişiselleştirme için)
            query: Arama sorgusu
            
        Returns:
            Yeniden sıralanmış sonuçlar
        """
        if not results:
            return results
        
        # Model hazır değilse orijinal sıralamayı koru
        if not self.is_ready():
            return results
        
        try:
            # Feature matrix oluştur
            feature_matrix, chunk_ids = self._feature_extractor.build_feature_matrix(
                results, user_id, query
            )
            
            if feature_matrix.size == 0:
                return results
            
            # CatBoost skorları al
            rerank_scores = self.predict(feature_matrix)
            
            # Combined score hesapla
            original_scores = feature_matrix[:, 0]  # cosine_similarity
            combined_scores = (
                self.original_weight * original_scores + 
                self.rerank_weight * self._normalize_scores(rerank_scores)
            )
            
            # Sonuçları rerank skoruna göre sırala
            sorted_indices = np.argsort(combined_scores)[::-1]  # Descending
            
            reranked_results = []
            for rank, idx in enumerate(sorted_indices):
                result = results[idx].copy()
                result['original_score'] = float(original_scores[idx])
                result['rerank_score'] = float(rerank_scores[idx])
                result['combined_score'] = float(combined_scores[idx])
                result['rerank_position'] = rank + 1
                reranked_results.append(result)
            
            log_system_event(
                "DEBUG",
                f"CatBoost reranking: {len(results)} sonuç yeniden sıralandı",
                "catboost_service"
            )
            
            return reranked_results
            
        except Exception as e:
            log_error(f"Reranking hatası: {e}", "catboost_service")
            # Hata durumunda orijinal sıralamayı koru
            return results
    
    def _normalize_scores(self, scores: np.ndarray) -> np.ndarray:
        """Skorları 0-1 arasına normalize et"""
        if len(scores) == 0:
            return scores
        
        min_score = scores.min()
        max_score = scores.max()
        
        if max_score - min_score < 1e-6:
            return np.ones_like(scores) * 0.5
        
        return (scores - min_score) / (max_score - min_score)
    
    # ============================================
    # Cache Yönetimi
    # ============================================
    
    def clear_cache(self):
        """Feature extractor cache'ini temizle"""
        self._feature_extractor.clear_cache()
    
    def reload_model(self) -> bool:
        """Modeli yeniden yükle"""
        self._model = None
        self._model_loaded = False
        self._model_version = None
        return self._try_load_model()


# Singleton instance
_catboost_service: Optional[CatBoostRerankingService] = None


def get_catboost_service() -> CatBoostRerankingService:
    """CatBoost Service singleton instance döndürür"""
    global _catboost_service
    if _catboost_service is None:
        _catboost_service = CatBoostRerankingService()
    return _catboost_service
