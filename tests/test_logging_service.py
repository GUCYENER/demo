"""
VYRA L1 Support API - Logging Service Tests
=============================================
Loglama servisi fonksiyon testleri.

Test Kapsamı:
- Sistem olayı loglama
- Hata loglama
- Request loglama
- Log seviyeleri
"""

import pytest
from unittest.mock import patch, MagicMock


# =============================================================================
# TEST: Log System Event
# =============================================================================

class TestLogSystemEvent:
    """Sistem olayı loglama testleri."""

    def test_log_info_event(self):
        """INFO seviyesinde log kaydı olmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_system_event
            log_system_event("INFO", "Test log mesajı", "test")

            assert mock_cursor.execute.called
            mock_conn.commit.assert_called()

    def test_log_warning_event(self):
        """WARNING seviyesinde log kaydı olmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_system_event
            log_system_event("WARNING", "Dikkat çeken bir durum", "test")

            assert mock_cursor.execute.called

    def test_log_error_event(self):
        """ERROR seviyesinde log kaydı olmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_system_event
            log_system_event("ERROR", "Kritik hata oluştu", "test")

            assert mock_cursor.execute.called


# =============================================================================
# TEST: Log Error
# =============================================================================

class TestLogError:
    """Hata loglama testleri."""

    def test_log_error_with_module(self):
        """Modül bilgisi ile hata loglanmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_error
            log_error("Test hatası", "rag_service")

            assert mock_cursor.execute.called

    def test_log_error_handles_db_failure(self):
        """DB hatası olsa bile crash olmamalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_get_db.side_effect = Exception("DB connection failed")

            from app.services.logging_service import log_error
            # Should not raise
            log_error("Test hatası", "test")


# =============================================================================
# TEST: Log Request
# =============================================================================

class TestLogRequest:
    """Request loglama testleri."""

    def test_log_request_success(self):
        """HTTP request loglanmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_request
            log_request(
                request_path="/api/rag/search",
                request_method="POST",
                response_status=200
            )

            assert mock_cursor.execute.called
            mock_conn.commit.assert_called()

    def test_log_request_with_error_status(self):
        """Hata status'lu request loglanmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_request
            log_request(
                request_path="/api/auth/login",
                request_method="POST",
                response_status=401
            )

            assert mock_cursor.execute.called


# =============================================================================
# TEST: Log Warning (convenience function)
# =============================================================================

class TestLogWarning:
    """Uyarı loglama testleri."""

    def test_log_warning_convenience(self):
        """log_warning convenience fonksiyonu çalışmalı."""
        with patch('app.services.logging_service.get_db_conn') as mock_get_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_db.return_value = mock_conn

            from app.services.logging_service import log_warning
            log_warning("Yavaş sorgu tespit edildi", "db")

            assert mock_cursor.execute.called
