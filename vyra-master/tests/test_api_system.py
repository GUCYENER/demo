"""
VYRA L1 Support API - System Management Tests
================================================
Sistem yönetimi endpoint testleri.

Test Kapsamı:
- Sistem bilgisi (admin kontrol)
- Sistem sıfırlama (admin kontrol)
- Maturity threshold
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from tests.conftest import run_async


# =============================================================================
# TEST: Get System Info
# =============================================================================

class TestGetSystemInfo:
    """Sistem bilgisi testleri."""

    def test_get_system_info_requires_admin(self):
        """Normal kullanıcı sistem bilgisini göremez (403)."""
        non_admin = {"id": 1, "username": "user1", "is_admin": False}

        from app.api.routes.system import get_system_info

        with pytest.raises(HTTPException) as exc:
            run_async(get_system_info(current_user=non_admin))

        assert exc.value.status_code == 403

    def test_get_system_info_admin_success(self):
        """Admin sistem bilgisini görebilmeli."""
        admin_user = {"id": 1, "username": "admin", "is_admin": True}
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Her SELECT COUNT query için ayrı fetchone döndür
        mock_cursor.fetchone.return_value = {"cnt": 5}

        with patch('app.api.routes.system.get_db_conn', return_value=mock_conn):
            from app.api.routes.system import get_system_info
            result = run_async(get_system_info(current_user=admin_user))

        assert "protected" in result
        assert "to_delete" in result


# =============================================================================
# TEST: Reset System
# =============================================================================

class TestResetSystem:
    """Sistem sıfırlama testleri."""

    def test_reset_requires_admin(self):
        """Normal kullanıcı sistemi sıfırlayamaz (403)."""
        non_admin = {"id": 1, "username": "user1", "is_admin": False}

        from app.api.routes.system import reset_system

        with pytest.raises(HTTPException) as exc:
            run_async(reset_system(current_user=non_admin))

        assert exc.value.status_code == 403


# =============================================================================
# TEST: Maturity Threshold
# =============================================================================

class TestMaturityThreshold:
    """Maturity threshold testleri."""

    def test_get_maturity_threshold_default(self):
        """DB'de ayar yoksa default 80 dönmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = lambda s, *a: None

        with patch('app.api.routes.system.get_db_conn', return_value=mock_conn):
            from app.api.routes.system import get_maturity_threshold
            result = run_async(get_maturity_threshold())

        assert result["threshold"] == 80

    def test_get_maturity_threshold_from_db(self):
        """DB'de ayar varsa o değer dönmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"setting_value": "90"}
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = lambda s, *a: None

        with patch('app.api.routes.system.get_db_conn', return_value=mock_conn):
            from app.api.routes.system import get_maturity_threshold
            result = run_async(get_maturity_threshold())

        assert result["threshold"] == 90

    def test_get_maturity_threshold_db_error(self):
        """DB hatası durumunda default 80 dönmeli."""
        with patch('app.api.routes.system.get_db_conn', side_effect=Exception("DB error")):
            with patch('app.api.routes.system.log_error'):
                from app.api.routes.system import get_maturity_threshold
                result = run_async(get_maturity_threshold())

        assert result["threshold"] == 80
