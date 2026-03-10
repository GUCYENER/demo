"""
VYRA L1 Support API - Ticket Service Tests
============================================
ticket_service.py birim testleri.

Test Kapsamı:
- get_ticket_detail (ticket detayları)
- list_ticket_history_for_user (ticket geçmişi)
- update_ticket_llm_evaluation (LLM değerlendirme)
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
    """DB connection mock — get_db_conn() doğrudan çağrılıyor (context manager değil)."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def patched_db(mock_db):
    """Tüm DB bağlantılarını mock'la."""
    mock_conn, mock_cursor = mock_db
    
    with patch('app.services.ticket_service.get_db_conn', return_value=mock_conn):
        yield mock_conn, mock_cursor


# =============================================================================
# TEST: get_ticket_detail
# =============================================================================

class TestGetTicketDetail:
    """Ticket detayı getirme testleri."""
    
    def test_existing_ticket(self, patched_db):
        """Mevcut ticket detayları doğru formatta dönmeli."""
        mock_conn, mock_cursor = patched_db
        now = datetime.now()
        
        # İlk fetchone = ticket row, fetchall = steps
        mock_cursor.fetchone.return_value = {
            'id': 1,
            'user_id': 1,
            'title': 'VPN Bağlantı Sorunu',
            'description': 'VPN bağlantısı kuramıyorum',
            'source_type': 'vyra_chat',
            'source_name': None,
            'final_solution': 'Çözüm metni',
            'cym_text': 'CYM açıklama',
            'cym_portal_url': None,
            'llm_evaluation': None,
            'rag_results': None,
            'interaction_type': 'rag_only',
            'created_at': now
        }
        mock_cursor.fetchall.return_value = [
            {
                'step_order': 1,
                'step_title': 'Adım 1',
                'step_body': 'Yapılacak işlem'
            }
        ]
        
        from app.services.ticket_service import get_ticket_detail
        result = get_ticket_detail(1)
        
        assert result is not None
        assert result.id == 1
        assert result.title == 'VPN Bağlantı Sorunu'
        assert len(result.steps) == 1
        mock_conn.close.assert_called_once()
    
    def test_nonexistent_ticket(self, patched_db):
        """Mevcut olmayan ticket None dönmeli."""
        mock_conn, mock_cursor = patched_db
        mock_cursor.fetchone.return_value = None
        
        from app.services.ticket_service import get_ticket_detail
        result = get_ticket_detail(999)
        
        assert result is None
        mock_conn.close.assert_called_once()


# =============================================================================
# TEST: list_ticket_history_for_user
# =============================================================================

class TestListTicketHistory:
    """Ticket geçmişi listeleme testleri."""
    
    def test_admin_query(self, patched_db):
        """Admin tüm ticket'ları görmeli."""
        mock_conn, mock_cursor = patched_db
        now = datetime.now()
        
        # İlk fetchall = org ids, ikinci fetchall = ticket listesi
        mock_cursor.fetchall.side_effect = [
            [],  # user_org_rows (admin olduğu için önemli değil)
            [    # ticket rows
                {
                    'id': 1, 'user_id': 1, 'title': 'Test',
                    'description': 'Desc', 'source_type': 'vyra_chat',
                    'source_name': None,
                    'final_solution': 'Sol', 'cym_text': 'CYM',
                    'cym_portal_url': None, 'llm_evaluation': None,
                    'rag_results': None, 'interaction_type': 'rag_only',
                    'created_at': now, 'total_count': 1
                }
            ]
        ]
        
        from app.services.ticket_service import list_ticket_history_for_user
        result = list_ticket_history_for_user(
            user_id=99, is_admin=True,
            page=1, page_size=10,
            start_date=None, end_date=None
        )
        
        assert result is not None
        assert result.total == 1
        assert len(result.items) == 1
        mock_conn.close.assert_called_once()
    
    def test_empty_result(self, patched_db):
        """Sonuç yoksa boş liste dönmeli."""
        mock_conn, mock_cursor = patched_db
        
        mock_cursor.fetchall.side_effect = [
            [],  # user_org_rows
            []   # ticket rows (boş)
        ]
        
        from app.services.ticket_service import list_ticket_history_for_user
        result = list_ticket_history_for_user(
            user_id=1, is_admin=False,
            page=1, page_size=10,
            start_date=None, end_date=None
        )
        
        assert result.total == 0
        assert len(result.items) == 0


# =============================================================================
# TEST: update_ticket_llm_evaluation
# =============================================================================

class TestUpdateTicketLlmEvaluation:
    """LLM değerlendirme güncelleme testleri."""
    
    def test_update_success(self, patched_db):
        """Başarılı güncelleme True dönmeli."""
        mock_conn, mock_cursor = patched_db
        mock_cursor.fetchone.return_value = {'user_id': 1}
        
        from app.services.ticket_service import update_ticket_llm_evaluation
        result = update_ticket_llm_evaluation(
            ticket_id=1,
            llm_evaluation="AI değerlendirme metni",
            user_id=1
        )
        
        assert result is True
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
    
    def test_nonexistent_ticket(self, patched_db):
        """Mevcut olmayan ticket False dönmeli."""
        mock_conn, mock_cursor = patched_db
        mock_cursor.fetchone.return_value = None
        
        from app.services.ticket_service import update_ticket_llm_evaluation
        result = update_ticket_llm_evaluation(
            ticket_id=999,
            llm_evaluation="test",
            user_id=1
        )
        
        assert result is False
    
    def test_wrong_user_rejected(self, patched_db):
        """Başkasının ticket'ını güncelleyemez."""
        mock_conn, mock_cursor = patched_db
        mock_cursor.fetchone.return_value = {'user_id': 1}
        
        from app.services.ticket_service import update_ticket_llm_evaluation
        result = update_ticket_llm_evaluation(
            ticket_id=1,
            llm_evaluation="test",
            user_id=999  # farklı kullanıcı
        )
        
        assert result is False
