"""
VYRA L1 Support API - Permission Management Tests
====================================================
RBAC izin yönetimi testleri.

Test Kapsamı:
- Rol listeleme (statik)
- Kaynak listeleme (statik hiyerarşi)
- Kullanıcı izinleri (DB'den)
- Rol izinleri (DB'den)
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from tests.conftest import run_async


def _mock_db_context(mock_conn):
    """get_db_context mock helper."""
    ctx = MagicMock()
    ctx.__enter__ = lambda s: mock_conn
    ctx.__exit__ = lambda s, *a: None
    return ctx


def _make_cursor_cm(mock_cursor):
    """cursor context manager desteği: with conn.cursor() as cur:"""
    cm = MagicMock()
    cm.__enter__ = lambda s: mock_cursor
    cm.__exit__ = lambda s, *a: None
    return cm


# =============================================================================
# TEST: Get Roles (Static)
# =============================================================================

class TestGetRoles:
    """Rol listeleme testleri."""

    def test_get_roles_returns_static_list(self):
        """Roller statik olarak döndürülmeli."""
        with patch('app.api.routes.permissions.log_system_event'):
            from app.api.routes.permissions import get_roles
            result = run_async(get_roles())

        assert result["success"] is True
        assert len(result["roles"]) == 2
        role_names = [r["name"] for r in result["roles"]]
        assert "admin" in role_names
        assert "user" in role_names


# =============================================================================
# TEST: Get Resources (Static hierarchy)
# =============================================================================

class TestGetResources:
    """Kaynak listeleme testleri."""

    def test_get_resources_returns_hierarchy(self):
        """Kaynaklar hiyerarşik döndürülmeli."""
        with patch('app.api.routes.permissions.log_system_event'):
            from app.api.routes.permissions import get_resources
            result = run_async(get_resources())

        assert result["success"] is True
        assert len(result["resources"]) > 0
        # İlk kaynak bir menü olmalı
        assert result["resources"][0]["type"] == "menu"


# =============================================================================
# TEST: Get Role Permissions (DB)
# =============================================================================

class TestGetRolePermissions:
    """Rol izin detayları."""

    def test_get_role_permissions_success(self):
        """Admin rol izinleri alınabilmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"resource_type": "menu", "resource_id": "menuNewTicket",
             "resource_label": "Ana Sayfa", "parent_resource_id": None,
             "can_view": True, "can_create": True,
             "can_update": True, "can_delete": False}
        ]
        mock_conn.cursor.return_value = _make_cursor_cm(mock_cursor)

        with patch('app.api.routes.permissions.get_db_context', return_value=_mock_db_context(mock_conn)):
            with patch('app.api.routes.permissions.log_system_event'):
                from app.api.routes.permissions import get_role_permissions
                result = run_async(get_role_permissions(role_name="admin"))

        assert result["success"] is True
        assert result["role_name"] == "admin"

    def test_get_role_permissions_invalid_role(self):
        """Geçersiz rol adı 400 dönmeli."""
        with pytest.raises(HTTPException) as exc:
            from app.api.routes.permissions import get_role_permissions
            run_async(get_role_permissions(role_name="superadmin"))

        assert exc.value.status_code == 400


# =============================================================================
# TEST: Get My Permissions (DB + auth)
# =============================================================================

class TestMyPermissions:
    """Kullanıcı kendi izinleri testleri."""

    def test_my_permissions_returns_data(self, sample_user):
        """Kullanıcı kendi izinlerini görebilmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"resource_id": "menuNewTicket", "can_view": True,
             "can_create": False, "can_update": False, "can_delete": False}
        ]
        # permissions.py uses: with conn.cursor() as cur:
        mock_conn.cursor.return_value = _make_cursor_cm(mock_cursor)

        with patch('app.api.routes.permissions.get_db_context', return_value=_mock_db_context(mock_conn)):
            with patch('app.api.routes.permissions.log_system_event'):
                from app.api.routes.permissions import get_my_permissions
                result = run_async(get_my_permissions(request_user=sample_user))

        assert result["success"] is True
        assert result["role"] == "user"
        assert "menuNewTicket" in result["permissions"]
