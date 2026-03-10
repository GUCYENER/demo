"""
VYRA L1 Support API - Dialog CRUD Tests
=========================================
Dialog oluşturma, listeleme ve kapatma testleri.

Test Kapsamı:
- Dialog oluşturma
- Aktif dialog bulma
- Dialog kapatma
- Dialog geçmişi
- Dialog listeleme
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


# =============================================================================
# TEST: Create Dialog
# =============================================================================

class TestCreateDialog:
    """Dialog oluşturma testleri."""

    def test_create_dialog_returns_id(self):
        """Yeni dialog oluşturulmalı ve int ID dönmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"id": 1}
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.crud.log_system_event'):
                from app.services.dialog.crud import create_dialog
                result = create_dialog(user_id=1, title="Yeni Dialog")

        assert isinstance(result, int)
        assert result == 1

    def test_create_dialog_default_title(self):
        """Başlık verilmezse varsayılan başlık kullanılmalı."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"id": 2}
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.crud.log_system_event'):
                from app.services.dialog.crud import create_dialog
                result = create_dialog(user_id=1)

        assert result == 2

    def test_create_dialog_with_source_type(self):
        """Kaynak tipi belirtilmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"id": 3}
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.crud.log_system_event'):
                from app.services.dialog.crud import create_dialog
                result = create_dialog(user_id=1, source_type="vyra_chat")

        assert result == 3
        mock_conn.commit.assert_called()


# =============================================================================
# TEST: Get Active Dialog
# =============================================================================

class TestGetActiveDialog:
    """Aktif dialog bulma testleri."""

    def test_get_active_dialog_exists(self):
        """Aktif dialog varsa dict dönmeli."""
        row_data = {
            "id": 1, "user_id": 1, "title": "Test",
            "status": "active", "created_at": datetime.now(), "updated_at": datetime.now()
        }

        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = row_data
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.crud import get_active_dialog
            result = get_active_dialog(user_id=1)

        assert result is not None
        assert result["status"] == "active"

    def test_get_active_dialog_none(self):
        """Aktif dialog yoksa None dönmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.crud import get_active_dialog
            result = get_active_dialog(user_id=1)

        assert result is None


# =============================================================================
# TEST: Close Dialog
# =============================================================================

class TestCloseDialog:
    """Dialog kapatma testleri."""

    def test_close_dialog_success(self):
        """Dialog başarıyla kapatılmalı."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {"id": 1}
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.crud.log_system_event'):
                from app.services.dialog.crud import close_dialog
                result = close_dialog(dialog_id=1, user_id=1)

        assert result is True
        mock_conn.commit.assert_called()

    def test_close_dialog_not_found(self):
        """Bulunmayan dialog False dönmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.crud import close_dialog
            result = close_dialog(dialog_id=999, user_id=1)

        assert result is False


# =============================================================================
# TEST: List User Dialogs
# =============================================================================

class TestListUserDialogs:
    """Kullanıcı dialog listesi testleri."""

    def test_list_dialogs_returns_list(self):
        """Dialog listesi dönmeli."""
        rows = [
            {"id": 1, "title": "Dialog 1", "source_type": "vyra_chat",
             "status": "active", "created_at": datetime.now(),
             "updated_at": datetime.now(), "closed_at": None, "message_count": 5},
        ]

        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = rows
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.crud import list_user_dialogs
            result = list_user_dialogs(user_id=1)

        assert isinstance(result, list)
        assert len(result) == 1

    def test_list_dialogs_empty(self):
        """Dialog yoksa boş liste dönmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.crud import list_user_dialogs
            result = list_user_dialogs(user_id=1)

        assert result == []


# =============================================================================
# TEST: Close Inactive Dialogs
# =============================================================================

class TestCloseInactiveDialogs:
    """İnaktif dialog kapatma testleri."""

    def test_close_inactive_returns_count(self):
        """Kapatılan dialog sayısı dönmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [{"id": 1}, {"id": 2}]
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            with patch('app.services.dialog.crud.log_system_event'):
                from app.services.dialog.crud import close_inactive_dialogs
                result = close_inactive_dialogs(inactivity_minutes=30)

        assert result == 2

    def test_close_inactive_no_dialogs(self):
        """İnaktif dialog yoksa 0 dönmeli."""
        with patch('app.services.dialog.crud.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = lambda s, *a: None

            from app.services.dialog.crud import close_inactive_dialogs
            result = close_inactive_dialogs()

        assert result == 0
