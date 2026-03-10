"""
VYRA L1 Support API - Dialog Messages Tests
=============================================
Mesaj ekleme, listeleme ve feedback testleri.

Test Kapsamı:
- Mesaj ekleme (user/assistant)
- Mesaj listeleme
- Metadata güncelleme (key-value)
- Feedback ekleme (user_id zorunlu)
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


# =============================================================================
# TEST: Add Message
# =============================================================================

class TestAddMessage:
    """Mesaj ekleme testleri."""

    def test_add_user_message(self):
        """Kullanıcı mesajı eklenebilmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {
                "id": 1, "dialog_id": 1, "role": "user",
                "content": "VPN bağlanamıyorum", "created_at": datetime.now()
            }
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import add_message
            result = add_message(
                dialog_id=1,
                role="user",
                content="VPN bağlanamıyorum"
            )

        assert result is not None
        assert isinstance(result, int)

    def test_add_assistant_message(self):
        """Asistan mesajı eklenebilmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {
                "id": 2, "dialog_id": 1, "role": "assistant",
                "content": "Çözüm bilgisi...", "created_at": datetime.now()
            }
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import add_message
            result = add_message(
                dialog_id=1,
                role="assistant",
                content="Çözüm bilgisi..."
            )

        assert result is not None
        assert isinstance(result, int)

    def test_add_message_with_metadata(self):
        """Metadata ile mesaj eklenebilmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {
                "id": 3, "dialog_id": 1, "role": "assistant",
                "content": "Çözüm...", "created_at": datetime.now()
            }
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import add_message
            result = add_message(
                dialog_id=1,
                role="assistant",
                content="Çözüm...",
                metadata={"rag_score": 0.85}
            )

        assert result is not None


# =============================================================================
# TEST: Get Dialog Messages
# =============================================================================

class TestGetDialogMessages:
    """Mesaj listeleme testleri."""

    def test_get_messages_returns_list(self):
        """Mesajlar liste olarak dönmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                {"id": 1, "role": "user", "content": "Merhaba",
                 "created_at": datetime.now(), "feedback_type": None},
                {"id": 2, "role": "assistant", "content": "Yardım",
                 "created_at": datetime.now(), "feedback_type": None}
            ]
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import get_dialog_messages
            result = get_dialog_messages(dialog_id=1)

        assert isinstance(result, list)
        assert len(result) == 2

    def test_get_messages_empty_dialog(self):
        """Boş dialog için boş liste dönmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import get_dialog_messages
            result = get_dialog_messages(dialog_id=999)

        assert result == []


# =============================================================================
# TEST: Update Message Metadata (key-value pattern)
# =============================================================================

class TestUpdateMessageMetadata:
    """Mesaj metadata güncelleme testleri."""

    def test_update_metadata_key_value(self):
        """key-value ile metadata güncellenmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"metadata": {}}
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import update_message_metadata
            result = update_message_metadata(
                message_id=1,
                key="rag_score",
                value=0.92
            )

        assert result is True
        assert mock_cursor.execute.called
        mock_conn.commit.assert_called()

    def test_update_metadata_not_found(self):
        """Mesaj bulunamazsa False dönmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.messages import update_message_metadata
            result = update_message_metadata(
                message_id=999,
                key="rag_score",
                value=0.92
            )

        assert result is False


# =============================================================================
# TEST: Add Message Feedback (user_id zorunlu)
# =============================================================================

class TestAddMessageFeedback:
    """Mesaj feedback testleri."""

    def test_add_positive_feedback(self):
        """Olumlu feedback eklenebilmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            # İlk fetchone: mesaj bilgisi, ikinci: user_feedback insert
            mock_cursor.fetchone.side_effect = [
                {
                    "id": 1, "dialog_id": 1, "content": "Çözüm...",
                    "metadata": None, "role": "assistant"
                },
                {"id": 10}  # feedback insert RETURNING
            ]
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.messages.log_warning'):
                from app.services.dialog.messages import add_message_feedback
                add_message_feedback(
                    message_id=1,
                    feedback_type="positive",
                    user_id=1
                )

        assert mock_cursor.execute.called

    def test_add_negative_feedback(self):
        """Olumsuz feedback eklenebilmeli."""
        with patch('app.services.dialog.messages.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.side_effect = [
                {
                    "id": 2, "dialog_id": 1, "content": "Çözüm...",
                    "metadata": None, "role": "assistant"
                },
                {"id": 11}
            ]
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.messages.log_warning'):
                from app.services.dialog.messages import add_message_feedback
                add_message_feedback(
                    message_id=2,
                    feedback_type="negative",
                    user_id=1
                )

        assert mock_cursor.execute.called
