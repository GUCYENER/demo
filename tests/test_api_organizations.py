"""
VYRA L1 Support API - Organization Management Tests
=====================================================
Organizasyon CRUD ve yetki kontrol testleri.

Test Kapsamı:
- Organizasyon listeleme
- Organizasyon oluşturma (duplicate check)
- Organizasyon silme (not found, protected)
- Organizasyon güncelleme
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from tests.conftest import run_async


def _mock_db_context(mock_conn):
    """get_db_context mock helper - context manager pattern."""
    ctx = MagicMock()
    ctx.__enter__ = lambda s: mock_conn
    ctx.__exit__ = lambda s, *a: None
    return ctx


# =============================================================================
# TEST: List Organizations
# =============================================================================

class TestListOrganizations:
    """Organizasyon listeleme testleri."""

    def test_list_orgs_returns_data(self, admin_user):
        """Admin organizasyonları listeleyebilmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # fetchone for count, fetchall for list
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_cursor.fetchall.return_value = [{
            "id": 1, "org_code": "ORG-IT", "org_name": "Bilgi Teknolojileri",
            "description": "IT birimi", "is_active": True,
            "user_count": 5, "document_count": 10,
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
            "created_by": None,
            "updated_at": None
        }]

        with patch('app.api.routes.organizations.get_db_context', return_value=_mock_db_context(mock_conn)):
            from app.api.routes.organizations import list_organizations
            result = run_async(list_organizations(page=1, per_page=10, admin=admin_user))

        assert result["total"] == 1
        assert len(result["organizations"]) == 1

    def test_list_orgs_empty(self, admin_user):
        """Boş organizasyon listesi döndürülebilmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_cursor.fetchall.return_value = []

        with patch('app.api.routes.organizations.get_db_context', return_value=_mock_db_context(mock_conn)):
            from app.api.routes.organizations import list_organizations
            result = run_async(list_organizations(page=1, per_page=10, admin=admin_user))

        assert result["total"] == 0
        assert result["organizations"] == []


# =============================================================================
# TEST: Create Organization
# =============================================================================

class TestCreateOrganization:
    """Organizasyon oluşturma testleri."""

    def test_create_org_duplicate_code(self, admin_user):
        """Aynı code ile oluşturma 400 dönmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"id": 1}  # duplicate found

        with patch('app.api.routes.organizations.get_db_context', return_value=_mock_db_context(mock_conn)):
            from app.api.routes.organizations import create_organization, OrganizationCreate
            payload = OrganizationCreate(org_code="ORG-IT", org_name="IT Birimi")

            with pytest.raises(HTTPException) as exc:
                run_async(create_organization(payload=payload, admin=admin_user))

            assert exc.value.status_code == 400


# =============================================================================
# TEST: Delete Organization
# =============================================================================

class TestDeleteOrganization:
    """Organizasyon silme testleri."""

    def test_delete_org_not_found(self, admin_user):
        """Olmayan organizasyon 404 dönmeli."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with patch('app.api.routes.organizations.get_db_context', return_value=_mock_db_context(mock_conn)):
            from app.api.routes.organizations import delete_organization

            with pytest.raises(HTTPException) as exc:
                run_async(delete_organization(org_id=999, admin=admin_user))

            assert exc.value.status_code == 404

    def test_delete_org_protected(self, admin_user):
        """Korunan organizasyon silinemez (403)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"org_code": "ORG-DEFAULT"}

        with patch('app.api.routes.organizations.get_db_context', return_value=_mock_db_context(mock_conn)):
            from app.api.routes.organizations import delete_organization

            with pytest.raises(HTTPException) as exc:
                run_async(delete_organization(org_id=1, admin=admin_user))

            assert exc.value.status_code == 403
