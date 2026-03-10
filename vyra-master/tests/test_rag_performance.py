"""
VYRA L1 Support API - RAG Performance Optimization Tests
=========================================================
v2.32.0 performans iyileştirmeleri için testler.

Test Kapsamı:
- Batch Cosine Similarity
- Deep Think Response Cache
- Sentetik Veri Üretimi
- Continuous Learning Service
- Paralel Execution

Author: VYRA AI Team
Version: 1.0.0 (2026-02-09)
"""

import pytest
import numpy as np
import time
from unittest.mock import patch, MagicMock, PropertyMock


# ============================================
# 1. Batch Cosine Similarity Tests
# ============================================

class TestBatchCosineSimilarity:
    """cosine_similarity_batch fonksiyon testleri"""
    
    def test_batch_empty_docs(self):
        """Boş doküman listesi boş sonuç döner"""
        from app.services.rag.scoring import cosine_similarity_batch
        
        result = cosine_similarity_batch([0.1, 0.2, 0.3], [])
        assert result == []
    
    def test_batch_identical_vectors(self):
        """Aynı vektörler batch'te 1.0 benzerlik verir"""
        from app.services.rag.scoring import cosine_similarity_batch
        
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = cosine_similarity_batch(vec, [vec, vec, vec])
        
        assert len(result) == 3
        for score in result:
            assert abs(score - 1.0) < 0.0001
    
    def test_batch_orthogonal_vectors(self):
        """Dik vektörler batch'te 0 benzerlik verir"""
        from app.services.rag.scoring import cosine_similarity_batch
        
        query = [1.0, 0.0, 0.0]
        docs = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        
        result = cosine_similarity_batch(query, docs)
        
        assert len(result) == 2
        for score in result:
            assert abs(score) < 0.0001
    
    def test_batch_known_similarity(self):
        """Bilinen benzerlik değerleri doğru hesaplanır"""
        from app.services.rag.scoring import cosine_similarity_batch
        
        query = [1.0, 0.0]
        docs = [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]
        
        result = cosine_similarity_batch(query, docs)
        
        assert abs(result[0] - 1.0) < 0.0001   # Aynı yön
        assert abs(result[1] - 0.0) < 0.0001   # Dik
        assert abs(result[2] - (-1.0)) < 0.0001 # Ters yön
    
    def test_batch_zero_query_vector(self):
        """Sıfır query vektörü tüm sonuçları 0 döner"""
        from app.services.rag.scoring import cosine_similarity_batch
        
        query = [0.0, 0.0, 0.0]
        docs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        
        result = cosine_similarity_batch(query, docs)
        
        assert all(score == 0.0 for score in result)
    
    def test_batch_performance_vs_single(self):
        """Batch hesaplama tekil hesaplamadan hızlıdır"""
        from app.services.rag.scoring import cosine_similarity_batch, cosine_similarity
        
        # 200 doküman vektörü (gerçek senaryo)
        np.random.seed(42)
        query = np.random.randn(384).tolist()
        doc_vecs = [np.random.randn(384).tolist() for _ in range(200)]
        
        # Batch timing
        t0 = time.time()
        batch_results = cosine_similarity_batch(query, doc_vecs)
        batch_time = time.time() - t0
        
        # Single timing
        t0 = time.time()
        single_results = [cosine_similarity(query, dv) for dv in doc_vecs]
        single_time = time.time() - t0
        
        # Sonuçlar tutarlı olmalı
        assert len(batch_results) == len(single_results)
        for b, s in zip(batch_results, single_results):
            assert abs(b - s) < 0.001
        
        # Batch daha hızlı olmalı (en az 1.0x — test ortamı CPU yükü değişkenliği toleransı)
        if single_time > 0.001:  # Çok hızlı test ortamlarında atla
            speedup = single_time / max(batch_time, 0.0001)
            assert speedup > 1.0, f"Batch sadece {speedup:.1f}x hızlı - beklenen: >1.0x"
    
    def test_batch_large_input(self):
        """Büyük girdilerde hata oluşmaz"""
        from app.services.rag.scoring import cosine_similarity_batch
        
        np.random.seed(42)
        query = np.random.randn(384).tolist()
        docs = [np.random.randn(384).tolist() for _ in range(500)]
        
        result = cosine_similarity_batch(query, docs)
        
        assert len(result) == 500
        assert all(-1.1 <= score <= 1.1 for score in result)  # Float tolerance


# ============================================
# 2. Deep Think Cache Tests
# ============================================

class TestDeepThinkCache:
    """Deep Think response cache testleri"""
    
    def test_cache_service_has_deep_think(self):
        """CacheService'te deep_think cache'i mevcut"""
        from app.core.cache import CacheService
        
        cs = CacheService()
        assert hasattr(cs, 'deep_think')
    
    def test_deep_think_cache_set_get(self):
        """Cache set/get çalışır"""
        from app.core.cache import CacheService
        
        cs = CacheService()
        cs.deep_think.set("test_key", {"response": "test"})
        result = cs.deep_think.get("test_key")
        
        assert result is not None
        assert result["response"] == "test"
    
    def test_deep_think_cache_miss(self):
        """Olmayan key None döner"""
        from app.core.cache import CacheService
        
        cs = CacheService()
        result = cs.deep_think.get("nonexistent_key_xyz")
        
        assert result is None
    
    def test_deep_think_cache_clear(self):
        """clear_all deep_think cache'ini de temizler"""
        from app.core.cache import CacheService
        
        cs = CacheService()
        cs.deep_think.set("test_clear", {"data": True})
        cs.clear_all()
        
        result = cs.deep_think.get("test_clear")
        assert result is None
    
    def test_deep_think_cache_stats(self):
        """İstatistikler deep_think bilgisini içerir"""
        from app.core.cache import CacheService
        
        cs = CacheService()
        stats = cs.get_all_stats()
        
        assert "deep_think" in stats


# ============================================
# 3. Synthetic Data Generator Tests
# ============================================

class TestSyntheticDataGenerator:
    """SyntheticDataGenerator testleri"""
    
    def test_generator_import(self):
        """SyntheticDataGenerator import edilebilir"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        assert SyntheticDataGenerator is not None
    
    def test_generator_instantiation(self):
        """Generator örneği oluşturulabilir"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        
        gen = SyntheticDataGenerator(max_chunks=10, questions_per_chunk=2)
        assert gen.max_chunks == 10
        assert gen.questions_per_chunk == 2
    
    def test_keyword_extraction(self):
        """Anahtar kelime çıkarma çalışır"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        
        gen = SyntheticDataGenerator()
        text = "VPN bağlantısı için Cisco AnyConnect uygulamasını açın"
        
        keywords = gen._extract_keywords_from_chunk(text)
        
        assert len(keywords) > 0
        # VPN, Cisco, AnyConnect gibi terimler olmalı
        keywords_lower = [k.lower() for k in keywords]
        assert any("vpn" in k or "cisco" in k or "anyconnect" in k for k in keywords_lower)
    
    def test_keyword_extraction_empty(self):
        """Boş text boş liste döner"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        
        gen = SyntheticDataGenerator()
        assert gen._extract_keywords_from_chunk("") == []
        assert gen._extract_keywords_from_chunk(None) == []
    
    def test_question_generation(self):
        """Soru üretimi çalışır"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        
        gen = SyntheticDataGenerator()
        keywords = ["VPN", "bağlantı", "Cisco"]
        
        # v2.44.0: _generate_questions → _generate_template_questions
        questions = gen._generate_template_questions(keywords)
        
        assert len(questions) > 0
        for q in questions:
            assert "query" in q
            assert "intent" in q
    
    def test_question_templates_coverage(self):
        """Tüm intent tipleri şablon içerir"""
        from app.services.ml_training.synthetic_data import QUESTION_TEMPLATES
        
        expected_intents = {"LIST_REQUEST", "HOW_TO", "TROUBLESHOOT", "SINGLE_ANSWER"}
        
        assert set(QUESTION_TEMPLATES.keys()) == expected_intents
        
        for intent, templates in QUESTION_TEMPLATES.items():
            assert len(templates) >= 3, f"{intent} en az 3 şablon içermeli"
    
    # === v2.44.0: Yeni fonksiyon testleri ===
    
    def test_validate_question_relevance_positive(self):
        """İlişkili soru geçerli olarak kabul edilir"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        assert gen._validate_question_relevance(
            "VPN nasıl bağlanılır",
            "vpn bağlantı kurulumu adımları şu şekildedir"
        ) is True
    
    def test_validate_question_relevance_hallucination(self):
        """İlişkisiz soru (halüsinasyon) reddedilir"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        assert gen._validate_question_relevance(
            "Exchange mail hesabı nasıl açılır",
            "vpn bağlantı kurulumu adımları"
        ) is False
    
    def test_validate_question_relevance_edge_cases(self):
        """Edge case'ler doğru ele alınır"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        # Çok kısa soru
        assert gen._validate_question_relevance("ne", "uzun chunk metni") is False
        # Boş chunk
        assert gen._validate_question_relevance("VPN nedir", "") is False
        # Çok uzun soru (>150 karakter)
        assert gen._validate_question_relevance("a " * 100, "test chunk") is False
    
    def test_estimate_relevance_score(self):
        """Skor çeşitlendirmesi çalışır"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        high = gen._estimate_relevance_score("VPN bağlantı kurulum", "VPN bağlantı kurulumu şu adımlarla yapılır")
        low = gen._estimate_relevance_score("Exchange posta kuralları", "VPN bağlantı kurulumu şu adımlarla yapılır")
        
        assert 0.5 <= high <= 0.95
        assert 0.5 <= low <= 0.95
        assert high > low  # Yüksek overlap → yüksek skor
    
    def test_pick_hard_negative(self):
        """Hard negative aynı topic farklı dosyadan seçilir"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        source = {"id": 1, "file_name": "a.xlsx", "content": "test"}
        candidates = [
            source,
            {"id": 2, "file_name": "b.xlsx", "content": "başka"},
            {"id": 3, "file_name": "a.xlsx", "content": "aynı dosya"},
        ]
        
        result = gen._pick_hard_negative(source, candidates)
        assert result is not None
        assert result["id"] != 1
    
    def test_pick_easy_negative(self):
        """Easy negative farklı topic'ten seçilir"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        source = {"id": 1}
        topic_groups = {
            "vpn": [source],
            "mail": [{"id": 2, "content": "mail chunk"}],
        }
        
        result = gen._pick_easy_negative(source, "vpn", topic_groups)
        assert result is not None
        assert result["id"] == 2
    
    def test_pick_easy_negative_single_topic(self):
        """Tek topic varsa None döner"""
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        gen = SyntheticDataGenerator()
        
        source = {"id": 1}
        topic_groups = {"vpn": [source]}
        
        result = gen._pick_easy_negative(source, "vpn", topic_groups)
        assert result is None


# ============================================
# 4. Continuous Learning Service Tests
# ============================================

class TestContinuousLearningService:
    """ContinuousLearningService testleri"""
    
    def test_service_import(self):
        """Servis import edilebilir"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        assert ContinuousLearningService is not None
    
    def test_service_instantiation(self):
        """Servis örneği oluşturulabilir"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        
        svc = ContinuousLearningService(interval_minutes=5, min_feedback_threshold=3)
        assert svc._interval_minutes == 5
        assert svc._min_feedback_threshold == 3
        assert not svc.is_running
    
    def test_service_start_stop(self):
        """Start/stop lifecycle çalışır"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        
        svc = ContinuousLearningService()
        
        assert svc.start() == True
        assert svc.is_running == True
        
        # Duplicate start
        assert svc.start() == False
        
        assert svc.stop() == True
        assert svc.is_running == False
        
        # Duplicate stop
        assert svc.stop() == False
    
    def test_service_status(self):
        """Status raporu tüm alanları içerir"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        
        svc = ContinuousLearningService()
        status = svc.get_status()
        
        assert "is_running" in status
        assert "interval_minutes" in status
        assert "min_feedback_threshold" in status
        assert "total_trainings" in status
    
    def test_singleton_pattern(self):
        """get_continuous_learning_service singleton döner"""
        from app.services.ml_training.continuous_learning import get_continuous_learning_service
        
        svc1 = get_continuous_learning_service()
        svc2 = get_continuous_learning_service()
        
        assert svc1 is svc2
    
    # === v2.44.0: Adversarial feedback koruması testleri ===
    
    def test_compute_query_chunk_overlap_high(self):
        """İlişkili sorgu-chunk → yüksek overlap"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        
        overlap = ContinuousLearningService._compute_query_chunk_overlap(
            "VPN nasıl bağlanılır",
            "VPN bağlantısı kurmak için önce istemciyi indirin."
        )
        assert overlap >= 0.4
    
    def test_compute_query_chunk_overlap_low(self):
        """İlişkisiz sorgu-chunk → düşük overlap"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        
        overlap = ContinuousLearningService._compute_query_chunk_overlap(
            "Exchange mail hesabı açılır",
            "VPN bağlantısı kurmak için önce istemciyi indirin."
        )
        assert overlap < 0.2
    
    def test_compute_query_chunk_overlap_empty(self):
        """Boş girişlerde 0 döner"""
        from app.services.ml_training.continuous_learning import ContinuousLearningService
        
        assert ContinuousLearningService._compute_query_chunk_overlap("", "chunk") == 0.0
        assert ContinuousLearningService._compute_query_chunk_overlap("query", "") == 0.0
        assert ContinuousLearningService._compute_query_chunk_overlap("", "") == 0.0


# ============================================
# 5. ML Training Package Tests
# ============================================

class TestMLTrainingPackage:
    """ml_training package export testleri"""
    
    def test_package_exports(self):
        """Tüm yeni modüller export edilir"""
        from app.services.ml_training import (
            MLSchedulingMixin,
            MLJobRunnerMixin,
            SyntheticDataGenerator,
            ContinuousLearningService,
            get_continuous_learning_service
        )
        
        assert MLSchedulingMixin is not None
        assert MLJobRunnerMixin is not None
        assert SyntheticDataGenerator is not None
        assert ContinuousLearningService is not None
        assert get_continuous_learning_service is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
