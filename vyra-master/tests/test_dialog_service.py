"""
VYRA L1 Support API - Dialog Service Tests
============================================
dialog service modüler yapı için unit testler.

Author: VYRA AI Team
Version: 2.0.0 (2026-02-07) - Modular structure mock paths
"""

import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, Any


class TestCreateDialog:
    """create_dialog() fonksiyon testleri"""
    
    @patch('app.services.dialog.crud.get_db_context')
    @patch('app.services.dialog.crud.log_system_event')
    def test_create_dialog_success(self, mock_log, mock_db_context):
        """Yeni dialog başarıyla oluşturulur"""
        from app.services.dialog_service import create_dialog
        
        # Mock setup
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 1}
        
        # Context manager mock
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        # Test - create_dialog returns int (dialog_id)
        result = create_dialog(user_id=1, title="Test Dialog")
        
        # Assertions
        assert result == 1  # Returns dialog_id as int
        mock_conn.commit.assert_called_once()
    
    @patch('app.services.dialog.crud.get_db_context')
    @patch('app.services.dialog.crud.log_system_event')
    def test_create_dialog_with_source_type(self, mock_log, mock_db_context):
        """source_type parametresi doğru kaydedilir"""
        from app.services.dialog_service import create_dialog
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 2}
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = create_dialog(user_id=1, source_type="vyra_chat")
        
        assert result == 2
        # SQL'de source_type geçtiğini doğrula
        call_args = mock_cursor.execute.call_args
        assert "source_type" in call_args[0][0]


class TestCloseDialog:
    """close_dialog() fonksiyon testleri"""
    
    @patch('app.services.dialog.crud.get_db_context')
    @patch('app.services.dialog.crud.log_system_event')
    def test_close_dialog_success(self, mock_log, mock_db_context):
        """Dialog başarıyla kapatılır"""
        from app.services.dialog_service import close_dialog
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 1}  # RETURNING id
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = close_dialog(dialog_id=1, user_id=1)
        
        assert result == True
        mock_conn.commit.assert_called_once()
    
    @patch('app.services.dialog.crud.get_db_context')
    @patch('app.services.dialog.crud.log_system_event')
    def test_close_dialog_not_found(self, mock_log, mock_db_context):
        """Olmayan dialog kapatılmaya çalışılınca False döner"""
        from app.services.dialog_service import close_dialog
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # No RETURNING result
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = close_dialog(dialog_id=999, user_id=1)
        
        assert result == False


class TestGetDialogHistory:
    """get_dialog_history() fonksiyon testleri"""
    
    @patch('app.services.dialog.crud.get_db_context')
    def test_get_history_empty(self, mock_db_context):
        """Boş geçmiş listesi döner"""
        from app.services.dialog_service import get_dialog_history
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = get_dialog_history(user_id=1)
        
        # Returns dict with items, total, limit, offset
        assert isinstance(result, dict)
        assert result["total"] == 0
        assert len(result["items"]) == 0
    
    @patch('app.services.dialog.crud.get_db_context')
    def test_get_history_with_results(self, mock_db_context):
        """Geçmiş dialoglar döner"""
        from app.services.dialog_service import get_dialog_history
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 2}
        mock_cursor.fetchall.return_value = [
            {"id": 1, "title": "Dialog 1", "status": "closed"},
            {"id": 2, "title": "Dialog 2", "status": "closed"}
        ]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = get_dialog_history(user_id=1)
        
        assert result["total"] == 2
        assert len(result["items"]) == 2


class TestAddMessage:
    """add_message() fonksiyon testleri"""
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_add_user_message(self, mock_db_context):
        """Kullanıcı mesajı eklenir"""
        from app.services.dialog_service import add_message
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 1}
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message(
            dialog_id=1,
            role="user",
            content="Test mesaj"
        )
        
        # Returns message_id as int
        assert result == 1
        mock_conn.commit.assert_called_once()
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_add_assistant_message(self, mock_db_context):
        """Assistant mesajı eklenir"""
        from app.services.dialog_service import add_message
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 2}
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message(
            dialog_id=1,
            role="assistant",
            content="AI yanıtı",
            metadata={"source": "rag"}
        )
        
        assert result == 2
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_add_message_with_metadata(self, mock_db_context):
        """Metadata ile mesaj eklenir"""
        from app.services.dialog_service import add_message
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 3}
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        metadata = {"quick_reply": {"type": "yes_no"}}
        result = add_message(
            dialog_id=1,
            role="assistant",
            content="Çözüm bulundu",
            metadata=metadata
        )
        
        assert result == 3


class TestGetDialogMessages:
    """get_dialog_messages() fonksiyon testleri"""
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_get_messages_empty(self, mock_db_context):
        """Boş mesaj listesi döner"""
        from app.services.dialog_service import get_dialog_messages
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = get_dialog_messages(dialog_id=1)
        
        assert isinstance(result, list)
        assert len(result) == 0
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_get_messages_with_results(self, mock_db_context):
        """Mesajlar döner"""
        from app.services.dialog_service import get_dialog_messages
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "role": "user", "content": "Soru", "metadata": None},
            {"id": 2, "role": "assistant", "content": "Cevap", "metadata": None}
        ]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = get_dialog_messages(dialog_id=1)
        
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"


class TestCloseInactiveDialogs:
    """close_inactive_dialogs() fonksiyon testleri"""
    
    @patch('app.services.dialog.crud.get_db_context')
    @patch('app.services.dialog.crud.log_system_event')
    def test_close_inactive_dialogs(self, mock_log, mock_db_context):
        """İnaktif dialoglar kapatılır"""
        from app.services.dialog_service import close_inactive_dialogs
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = close_inactive_dialogs(inactivity_minutes=30)
        
        assert result == 3  # Returns count of closed dialogs
        mock_conn.commit.assert_called_once()


class TestParseChunkDetails:
    """parse_chunk_details() fonksiyon testleri (response_builder)"""
    
    def test_parse_empty_text(self):
        """Boş metin parse edilir"""
        from app.services.dialog_service import _parse_chunk_details
        
        result = _parse_chunk_details("")
        assert result == {}
    
    def test_parse_markdown_format(self):
        """Markdown formatlı chunk text parse edilir"""
        from app.services.dialog_service import _parse_chunk_details
        
        chunk = "**Uygulama Adı:** SAP\n**Talep Tipi:** Yetki"
        result = _parse_chunk_details(chunk)
        
        assert "uygulama_adi" in result
        assert result["uygulama_adi"] == "SAP"
        assert "talep_tipi" in result
        assert result["talep_tipi"] == "Yetki"
    
    def test_parse_fallback_preview(self):
        """Parse edilemezse önizleme döner"""
        from app.services.dialog_service import _parse_chunk_details
        
        chunk = "Bu bir düz metin"
        result = _parse_chunk_details(chunk)
        
        assert "onizleme" in result


class TestAddMessageFeedback:
    """add_message_feedback() fonksiyon testleri (v2.38.4 enrichment)"""
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_feedback_success_with_enrichment(self, mock_db_context):
        """Feedback başarıyla eklenir, query_text ve dialog_id zenginleştirilir."""
        from app.services.dialog_service import add_message_feedback
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        
        # İlk fetchone: mesaj metadata + content + dialog_id
        # İkinci fetchone: kullanıcının sorusu
        mock_cursor.fetchone.side_effect = [
            {"metadata": {"intent": "SINGLE_ANSWER"}, "content": "Bot yanıtı", "dialog_id": 10},
            {"content": "Kullanıcının sorusu"}
        ]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message_feedback(message_id=1, feedback_type="helpful", user_id=1)
        
        assert result is True
        # Commit tam 1 kere çağrılmalı (atomik transaction)
        mock_conn.commit.assert_called_once()
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_feedback_message_not_found(self, mock_db_context):
        """Mesaj bulunamadığında False döner."""
        from app.services.dialog_service import add_message_feedback
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message_feedback(message_id=999, feedback_type="helpful", user_id=1)
        
        assert result is False
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_feedback_metadata_as_string(self, mock_db_context):
        """String metadata doğru parse edilir."""
        from app.services.dialog_service import add_message_feedback
        import json
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        
        # metadata string olarak döner
        mock_cursor.fetchone.side_effect = [
            {"metadata": json.dumps({"intent": "HOW_TO"}), "content": "Yanıt", "dialog_id": 5},
            {"content": "Soru metni"}
        ]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message_feedback(message_id=2, feedback_type="not_helpful", user_id=1)
        
        assert result is True
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_feedback_no_user_query_graceful(self, mock_db_context):
        """Kullanıcı sorusu bulunamadığında query_text=None olur, hata fırlatmaz."""
        from app.services.dialog_service import add_message_feedback
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        
        # İlk fetchone: mesaj bulunur
        # İkinci fetchone: kullanıcı sorusu YOK
        mock_cursor.fetchone.side_effect = [
            {"metadata": {}, "content": "Bot yanıtı", "dialog_id": 1},
            None  # query bulunamadı
        ]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message_feedback(message_id=3, feedback_type="helpful", user_id=1)
        
        assert result is True
    
    @patch('app.services.dialog.messages.get_db_context')
    def test_feedback_extracts_chunk_id(self, mock_db_context):
        """rag_results metadata'sından chunk_id çıkarılır."""
        from app.services.dialog_service import add_message_feedback
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        
        metadata_with_rag = {
            "intent": "SINGLE_ANSWER",
            "rag_results": [{"chunk_id": 42, "score": 85}]
        }
        
        mock_cursor.fetchone.side_effect = [
            {"metadata": metadata_with_rag, "content": "Yanıt", "dialog_id": 7},
            {"content": "Soru"}
        ]
        
        mock_db_context.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_context.return_value.__exit__ = MagicMock(return_value=False)
        
        result = add_message_feedback(message_id=4, feedback_type="helpful", user_id=1)
        
        assert result is True
        # INSERT çağrısını kontrol et — chunk_id=42 geçirilmeli
        insert_calls = [
            c for c in mock_cursor.execute.call_args_list
            if 'INSERT INTO user_feedback' in str(c)
        ]
        assert len(insert_calls) == 1
        insert_params = insert_calls[0][0][1]
        assert insert_params[4] == 42  # chunk_id pozisyonu


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

