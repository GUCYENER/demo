"""
VYRA L1 Support API - User Profile Tests
==========================================
Kullanıcı profil yönetimi testleri.

Test Kapsamı:
- Profil bilgisi görüntüleme
- Profil güncelleme
- Şifre değiştirme
- Avatar güncelleme
- Organizasyon listeleme
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException


def _mock_db_conn():
    """get_db_conn mock helper."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# =============================================================================
# TEST: Get My Profile
# =============================================================================

class TestGetMyProfile:
    """Profil bilgisi testleri."""

    def test_get_profile_returns_data(self, sample_user):
        """Kullanıcı kendi profilini görebilmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = {
            "id": 1, "username": "testuser", "email": "test@example.com",
            "full_name": "Test User", "phone": "05551234567",
            "avatar": None, "role_name": "user",
            "role_id": 2, "is_admin": False, "is_approved": True,
            "created_at": "2026-01-01", "password": "hash"
        }

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import get_my_profile
            result = get_my_profile(current_user=sample_user)

        assert result.username == "testuser"
        assert result.email == "test@example.com"

    def test_get_profile_not_found(self, sample_user):
        """Kullanıcı bulunamazsa 404 dönmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = None

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import get_my_profile

            with pytest.raises(HTTPException) as exc:
                get_my_profile(current_user=sample_user)

            assert exc.value.status_code == 404


# =============================================================================
# TEST: Update Profile
# =============================================================================

class TestUpdateMyProfile:
    """Profil güncelleme testleri."""

    def test_update_profile_success(self, sample_user):
        """Profil güncellenebilmeli."""
        mock_conn, mock_cursor = _mock_db_conn()

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import update_my_profile
            from app.api.schemas.user_schemas import UpdateProfileRequest
            payload = UpdateProfileRequest(full_name="Updated Name")
            result = update_my_profile(payload=payload, current_user=sample_user)

        assert result["message"] == "Profil güncellendi"

    def test_update_profile_no_fields(self, sample_user):
        """Güncelleme verisi olmadan 400 dönmeli."""
        mock_conn, mock_cursor = _mock_db_conn()

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import update_my_profile
            from app.api.schemas.user_schemas import UpdateProfileRequest
            payload = UpdateProfileRequest()

            with pytest.raises(HTTPException) as exc:
                update_my_profile(payload=payload, current_user=sample_user)

            assert exc.value.status_code == 400


# =============================================================================
# TEST: Change Password
# =============================================================================

class TestChangePassword:
    """Şifre değiştirme testleri."""

    def test_change_password_wrong_current(self, sample_user):
        """Yanlış mevcut şifre ile değiştiremez."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = {"password": "$2b$12$somehash"}

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            with patch('app.api.routes.user_profile.verify_password', return_value=False):
                from app.api.routes.user_profile import change_password
                from app.api.schemas.user_schemas import ChangePasswordRequest
                payload = ChangePasswordRequest(
                    current_password="wrongpass",
                    new_password="newpass123"
                )

                with pytest.raises(HTTPException) as exc:
                    change_password(payload=payload, current_user=sample_user)

                assert exc.value.status_code == 400

    def test_change_password_user_not_found(self, sample_user):
        """Kullanıcı bulunamazsa 404 dönmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchone.return_value = None

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import change_password
            from app.api.schemas.user_schemas import ChangePasswordRequest
            payload = ChangePasswordRequest(
                current_password="anypass",
                new_password="newpass123"
            )

            with pytest.raises(HTTPException) as exc:
                change_password(payload=payload, current_user=sample_user)

            assert exc.value.status_code == 404


# =============================================================================
# TEST: Get My Organizations
# =============================================================================

class TestGetMyOrganizations:
    """Kullanıcı organizasyonları testleri."""

    def test_get_orgs_returns_list(self, sample_user):
        """Kullanıcı organizasyonlarını görebilmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "org_code": "ORG-IT", "org_name": "IT", "is_active": True}
        ]

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import get_my_organizations
            result = get_my_organizations(current_user=sample_user)

        assert len(result) == 1
        assert result[0]["org_code"] == "ORG-IT"

    def test_get_orgs_empty(self, sample_user):
        """Organizasyon yoksa boş liste dönmeli."""
        mock_conn, mock_cursor = _mock_db_conn()
        mock_cursor.fetchall.return_value = []

        with patch('app.api.routes.user_profile.get_db_conn', return_value=mock_conn):
            from app.api.routes.user_profile import get_my_organizations
            result = get_my_organizations(current_user=sample_user)

        assert result == []
