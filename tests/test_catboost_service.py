"""
VYRA L1 Support API - CatBoost Service Tests
=============================================
catboost_service.py ve feature_extractor.py için unit testler.

Author: VYRA AI Team
"""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock


# Test edilecek modüller import
from app.services.feature_extractor import (
    FeatureExtractor, 
    get_feature_extractor,
    FEATURE_NAMES,
    TOPIC_KEYWORDS
)


class TestFeatureExtractor:
    """FeatureExtractor sınıfı testleri"""
    
    def setup_method(self):
        """Her test öncesi çalışır"""
        self.extractor = FeatureExtractor()
    
    def test_topic_detection_vpn(self):
        """VPN topic algılama testi (statik keywords)"""
        text = "Cisco AnyConnect VPN bağlantı sorunu yaşıyorum"
        # Dinamik topic'leri devre dışı bırak, statik TOPIC_KEYWORDS test et
        with patch.object(self.extractor, '_load_dynamic_topics', return_value={}):
            topic = self.extractor._detect_topic(text)
        assert topic == 'vpn'
    
    def test_topic_detection_outlook(self):
        """Outlook topic algılama testi (statik keywords)"""
        text = "Outlook mail gönderemiyorum hata veriyor"
        with patch.object(self.extractor, '_load_dynamic_topics', return_value={}):
            topic = self.extractor._detect_topic(text)
        assert topic == 'outlook'
    
    def test_topic_detection_general(self):
        """Genel topic algılama testi"""
        text = "Merhaba nasılsınız"
        with patch.object(self.extractor, '_load_dynamic_topics', return_value={}):
            topic = self.extractor._detect_topic(text)
        assert topic == 'general'
    
    def test_extract_keywords(self):
        """Anahtar kelime çıkarma testi"""
        text = "VPN bağlantısı için nasıl yapılır"
        keywords = self.extractor._extract_keywords(text)
        assert 'vpn' in keywords
        assert 'bağlantısı' in keywords
        # Stop words olmamalı
        assert 'için' not in keywords
        assert 'nasıl' not in keywords
    
    def test_has_steps_numbered(self):
        """Numaralı adım tespit testi"""
        content = "1. İlk adım 2. İkinci adım 3. Üçüncü adım"
        result = self.extractor._has_steps(content)
        assert result == 1.0
    
    def test_has_steps_bullet(self):
        """Bullet point adım tespit testi"""
        content = "- Birinci madde\n- İkinci madde"
        result = self.extractor._has_steps(content)
        assert result == 1.0
    
    def test_has_steps_no_steps(self):
        """Adım olmayan içerik testi"""
        content = "Bu düz bir paragraf metnidir."
        result = self.extractor._has_steps(content)
        assert result == 0.0
    
    def test_has_code_backticks(self):
        """Kod bloğu tespit testi - backticks"""
        content = "Kodu çalıştırın: ```python print('merhaba')```"
        result = self.extractor._has_code(content)
        assert result == 1.0
    
    def test_has_code_import(self):
        """Kod bloğu tespit testi - import"""
        content = "import numpy as np kullanmalısınız"
        result = self.extractor._has_code(content)
        assert result == 1.0
    
    def test_has_code_no_code(self):
        """Kod olmayan içerik testi"""
        content = "Bu düz bir metin parçasıdır."
        result = self.extractor._has_code(content)
        assert result == 0.0
    
    @patch('app.services.feature_extractor.get_db_conn')
    def test_build_feature_matrix_shape(self, mock_db):
        """Feature matrix boyut testi"""
        # Mock veritabanı
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        
        # Test verisi
        results = [
            {
                'chunk_id': 1,
                'content': 'VPN bağlantısı için şu adımları izleyin',
                'score': 0.85,
                'quality_score': 0.7,
                'topic_label': 'vpn'
            },
            {
                'chunk_id': 2,
                'content': 'Outlook ayarlarını kontrol edin',
                'score': 0.72,
                'quality_score': 0.6,
                'topic_label': 'outlook'
            }
        ]
        
        matrix, chunk_ids = self.extractor.build_feature_matrix(
            results, user_id=None, query="VPN nasıl bağlanırım"
        )
        
        # Feature sayısı doğru olmalı
        assert matrix.shape[1] == len(FEATURE_NAMES)
        # Sonuç sayısı doğru olmalı
        assert matrix.shape[0] == 2
        assert len(chunk_ids) == 2
    
    def test_feature_names_count(self):
        """Feature isim sayısı testi"""
        assert len(FEATURE_NAMES) == 15  # v2.34.0: source_file_type + heading_match eklendi
    
    def test_topic_keywords_defined(self):
        """Topic keywords tanımlı mı testi"""
        assert 'vpn' in TOPIC_KEYWORDS
        assert 'outlook' in TOPIC_KEYWORDS
        assert 'network' in TOPIC_KEYWORDS


class TestCatBoostService:
    """CatBoostRerankingService testleri"""
    
    @patch('app.services.catboost_service.get_db_conn')
    def test_is_ready_no_model(self, mock_db):
        """Model yokken is_ready False döner"""
        from app.services.catboost_service import CatBoostRerankingService
        
        # Mock - boş sonuç dön
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        
        service = CatBoostRerankingService()
        result = service.is_ready()
        
        # Model yoksa False dönmeli
        assert result == False
    
    def test_normalize_scores(self):
        """Skor normalizasyon testi"""
        from app.services.catboost_service import CatBoostRerankingService
        
        service = CatBoostRerankingService()
        
        scores = np.array([0.2, 0.5, 0.8, 1.0])
        normalized = service._normalize_scores(scores)
        
        # Min 0, max 1 olmalı
        assert normalized.min() == 0.0
        assert normalized.max() == 1.0
    
    def test_normalize_scores_same_values(self):
        """Aynı değerlerle normalizasyon testi"""
        from app.services.catboost_service import CatBoostRerankingService
        
        service = CatBoostRerankingService()
        
        scores = np.array([0.5, 0.5, 0.5])
        normalized = service._normalize_scores(scores)
        
        # Tümü 0.5 olmalı
        assert np.allclose(normalized, 0.5)
    
    def test_get_model_info(self):
        """Model bilgisi testi"""
        from app.services.catboost_service import CatBoostRerankingService
        
        service = CatBoostRerankingService()
        info = service.get_model_info()
        
        assert 'is_ready' in info
        assert 'feature_count' in info
        assert 'feature_names' in info
        assert info['feature_count'] == len(FEATURE_NAMES)


class TestFeedbackService:
    """FeedbackService testleri"""
    
    @patch('app.services.feedback_service.get_db_conn')
    def test_record_feedback_invalid_type(self, mock_db):
        """Geçersiz feedback tipi testi"""
        from app.services.feedback_service import FeedbackService
        
        service = FeedbackService()
        result = service.record_feedback(
            user_id=1,
            feedback_type='invalid_type'
        )
        
        assert result['success'] == False
        assert 'error' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
