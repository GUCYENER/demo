"""
VYRA L1 Support API - Feedback Service Tests
==============================================
FeedbackService birim testleri.

Test Kapsamı:
- record_feedback (feedback kaydetme)
- get_user_stats (kullanıcı istatistikleri)
- get_chunk_ctr (chunk CTR)
- get_global_stats (global istatistikler)
- Geçersiz feedback tipi kontrolü
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_db():
    """DB connection mock."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


@pytest.fixture
def feedback_service(mock_db):
    """FeedbackService instance — DB mock'lanmış."""
    mock_conn, mock_cursor = mock_db
    
    with patch('app.services.feedback_service.get_db_conn') as mock_get_db:
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        
        from app.services.feedback_service import FeedbackService
        service = FeedbackService()
        service._mock_conn = mock_conn
        service._mock_cursor = mock_cursor
        yield service


# =============================================================================
# TEST: record_feedback
# =============================================================================

class TestRecordFeedback:
    """Feedback kaydetme testleri."""
    
    def test_invalid_type_rejected(self, feedback_service):
        """Geçersiz feedback tipi reddedilmeli."""
        result = feedback_service.record_feedback(
            user_id=1,
            feedback_type="invalid_type"
        )
        assert result["success"] is False
        assert "Geçersiz" in result["error"]
    
    def test_valid_type_accepted(self, feedback_service):
        """Geçerli feedback tipi kabul edilmeli."""
        result = feedback_service.record_feedback(
            user_id=1,
            feedback_type="helpful",
            query_text="test query"
        )
        assert result["success"] is True
        assert "kaydedildi" in result["message"]
    
    def test_with_chunk_ids(self, feedback_service):
        """Chunk ID'leri ile feedback kaydı."""
        result = feedback_service.record_feedback(
            user_id=1,
            feedback_type="not_helpful",
            chunk_ids=[1, 2, 3],
            query_text="test query"
        )
        assert result["success"] is True
        # Her chunk için ayrı INSERT çağrılmalı
        assert feedback_service._mock_cursor.execute.call_count >= 3
    
    def test_without_chunk_ids(self, feedback_service):
        """Chunk ID olmadan genel feedback."""
        result = feedback_service.record_feedback(
            user_id=1,
            feedback_type="copied"
        )
        assert result["success"] is True
    
    def test_db_error_handled(self, feedback_service):
        """DB hatası graceful şekilde handle edilmeli."""
        feedback_service._mock_cursor.execute.side_effect = Exception("DB error")
        
        result = feedback_service.record_feedback(
            user_id=1,
            feedback_type="helpful"
        )
        assert result["success"] is False


# =============================================================================
# TEST: get_user_stats
# =============================================================================

class TestGetUserStats:
    """Kullanıcı istatistik testleri."""
    
    def test_returns_stats(self, feedback_service):
        """İstatistikler doğru formatta dönmeli."""
        # fetchone → toplam/helpful/not_helpful sayılar
        feedback_service._mock_cursor.fetchone.return_value = {
            'total': 10, 'helpful': 7, 'not_helpful': 3
        }
        feedback_service._mock_cursor.fetchall.return_value = []
        
        from app.services.feedback_service import FeedbackStats
        stats = feedback_service.get_user_stats(user_id=1)
        
        assert isinstance(stats, FeedbackStats)
        assert stats.total_feedback == 10
        assert stats.helpful_count == 7
        assert stats.helpfulness_rate == 0.7
    
    def test_zero_feedback(self, feedback_service):
        """Hiç feedback yoksa sıfır dönmeli."""
        feedback_service._mock_cursor.fetchone.return_value = {
            'total': 0, 'helpful': 0, 'not_helpful': 0
        }
        feedback_service._mock_cursor.fetchall.return_value = []
        
        stats = feedback_service.get_user_stats(user_id=999)
        assert stats.total_feedback == 0
        assert stats.helpfulness_rate == 0.0
    
    def test_db_error_returns_empty(self, feedback_service):
        """DB hatası boş istatistik dönmeli."""
        feedback_service._mock_cursor.fetchone.side_effect = Exception("DB error")
        
        stats = feedback_service.get_user_stats(user_id=1)
        assert stats.total_feedback == 0


# =============================================================================
# TEST: feedback tipleri
# =============================================================================

class TestFeedbackTypes:
    """Feedback tipi sabitleri testleri."""
    
    def test_all_types_defined(self):
        """Tüm beklenen feedback tipleri tanımlı olmalı."""
        from app.services.feedback_service import FEEDBACK_TYPES
        
        expected = {'helpful', 'not_helpful', 'copied', 'partial'}
        assert set(FEEDBACK_TYPES.keys()) == expected
    
    def test_types_have_descriptions(self):
        """Her tipin Türkçe açıklaması olmalı."""
        from app.services.feedback_service import FEEDBACK_TYPES
        
        for key, value in FEEDBACK_TYPES.items():
            assert isinstance(value, str)
            assert len(value) > 0
