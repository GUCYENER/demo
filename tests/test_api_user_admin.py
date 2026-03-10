"""
VYRA L1 Support API - User Admin Tests
========================================
Admin kullanıcı yönetimi testleri.

Test Kapsamı:
- Kullanıcı listeleme
- Kullanıcı onaylama
- Kullanıcı reddetme
- Rol listeleme
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException


def _mock_db_conn():
    """get_db_conn mock helper — returns mock conn directly."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# =============================================================================
# TEST: List Users
# =============================================================================

class TestListUsers:
    """Kullanıcı listeleme testleri."""

    def test_list_users_returns_data(self, admin_user):
        """Admin kullanıcıları listeleyebilmeli."""
        mock_conn, mock_cursor = _mock_db_conn()

        # fetchone calls: total count, pending count
        mock_cursor.fetchone.side_effect = [
            {"cnt": 1},  # total count
            {"cnt": 0},  # pending count
        ]
        # fetchall calls: user list, org map
        mock_cursor.fetchall.side_effect = [
            [{"id": 1, "full_name": "Test User", "username": "testuser",
              "email": "test@x.com", "phone": "555", "role_id": 2,
              "role_name": "user", "role_desc": "User",
              "is_admin": False, "is_approved": True,
              "approved_at": None, "created_at": "2026-01-01"}],
            []  # user_organizations
        ]

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import list_users
            result = list_users(page=1, per_page=10, admin=admin_user)

        assert result["total"] == 1
        assert len(result["users"]) == 1

    def test_list_users_empty(self, admin_user):
        """Boş kullanıcı listesi döndürülebilmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.side_effect = [{"cnt": 0}, {"cnt": 0}]
        mock_cursor.fetchall.side_effect = [[], []]

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import list_users
            result = list_users(page=1, per_page=10, admin=admin_user)

        assert result["total"] == 0


# =============================================================================
# TEST: Approve User
# =============================================================================

class TestApproveUser:
    """Kullanıcı onaylama testleri."""

    def test_approve_user_not_found(self, admin_user):
        """Olmayan kullanıcı 404 dönmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = None

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import approve_user
            from app.api.schemas.user_schemas import ApproveUserRequest
            payload = ApproveUserRequest(user_id=999, role_id=2, org_ids=[1])

            with pytest.raises(HTTPException) as exc:
                approve_user(payload=payload, admin=admin_user)

            assert exc.value.status_code == 404

    def test_approve_user_success(self, admin_user):
        """Kullanıcı başarıyla onaylanmalı."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = {"id": 5}

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import approve_user
            from app.api.schemas.user_schemas import ApproveUserRequest
            payload = ApproveUserRequest(user_id=5, role_id=2, org_ids=[1, 2])
            result = approve_user(payload=payload, admin=admin_user)

        assert result["message"] is not None
        assert result["user_id"] == 5


# =============================================================================
# TEST: Reject User
# =============================================================================

class TestRejectUser:
    """Kullanıcı reddetme testleri."""

    def test_reject_user_not_found(self, admin_user):
        """Olmayan kullanıcı 404 dönmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = None

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import reject_user
            from app.api.schemas.user_schemas import RejectUserRequest
            payload = RejectUserRequest(user_id=999)

            with pytest.raises(HTTPException) as exc:
                reject_user(payload=payload, admin=admin_user)

            assert exc.value.status_code == 404

    def test_reject_approved_user_fails(self, admin_user):
        """Onaylanmış kullanıcı reddedilemez (400)."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = {"id": 5, "is_approved": True}

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import reject_user
            from app.api.schemas.user_schemas import RejectUserRequest
            payload = RejectUserRequest(user_id=5)

            with pytest.raises(HTTPException) as exc:
                reject_user(payload=payload, admin=admin_user)

            assert exc.value.status_code == 400


# =============================================================================
# TEST: List Roles
# =============================================================================

class TestListRoles:
    """Rol listeleme testleri."""

    def test_list_roles_returns_list(self, admin_user):
        """Roller listelenebilmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "admin", "description": "Yönetici"},
            {"id": 2, "name": "user", "description": "Kullanıcı"}
        ]

        with patch('app.api.routes.user_admin.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_admin import get_roles
            result = get_roles(admin=admin_user)

        assert len(result["roles"]) == 2
