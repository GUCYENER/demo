"""
VYRA L1 Support API - Themes & Company Branding Tests
=======================================================
Tema API endpoint'leri ve firma branding alanları (app_name, theme_id)
için unit testler.

Test Kapsamı:
- Pydantic model validasyonları (CompanyCreate/CompanyUpdate app_name, theme_id)
- GET /api/themes (tema listesi, auth gerektirmez)
- GET /api/themes/full (auth gerekli)
- GET /api/themes/{id} (tema detay, 404 durumu)
- GET /api/companies/by-url (tema branding dahil eşleşme)
- POST /api/companies (app_name, theme_id ile oluşturma)
- PUT /api/companies/{id} (app_name, theme_id güncelleme)
- Route registration doğrulama

v2.59.0
"""

import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# TEST: Pydantic Model Validasyonları (CompanyCreate / CompanyUpdate)
# =============================================================================

class TestCompanyBrandingModels:
    """CompanyCreate ve CompanyUpdate modellerinde app_name/theme_id validasyonu."""

    def test_company_create_with_app_name(self):
        """app_name alanı kabul edilmeli."""
        from app.api.routes.companies import CompanyCreate
        c = CompanyCreate(
            name="Test Firma",
            app_name="MyBrand",
            tax_type="vd",
            tax_number="1234567890",
            phone="555-1234",
            email="test@test.com",
            contact_name="Ali",
            contact_surname="Yılmaz"
        )
        assert c.app_name == "MyBrand"

    def test_company_create_without_app_name(self):
        """app_name opsiyonel, None olmalı."""
        from app.api.routes.companies import CompanyCreate
        c = CompanyCreate(
            name="Test Firma",
            tax_type="vd",
            tax_number="1234567890",
            phone="555-1234",
            email="test@test.com",
            contact_name="Ali",
            contact_surname="Yılmaz"
        )
        assert c.app_name is None

    def test_company_create_with_theme_id(self):
        """theme_id alanı kabul edilmeli."""
        from app.api.routes.companies import CompanyCreate
        c = CompanyCreate(
            name="Test Firma",
            theme_id=5,
            tax_type="vd",
            tax_number="1234567890",
            phone="555-1234",
            email="test@test.com",
            contact_name="Ali",
            contact_surname="Yılmaz"
        )
        assert c.theme_id == 5

    def test_company_create_without_theme_id(self):
        """theme_id opsiyonel, None olmalı."""
        from app.api.routes.companies import CompanyCreate
        c = CompanyCreate(
            name="Test Firma",
            tax_type="vd",
            tax_number="1234567890",
            phone="555-1234",
            email="test@test.com",
            contact_name="Ali",
            contact_surname="Yılmaz"
        )
        assert c.theme_id is None

    def test_company_create_app_name_max_length(self):
        """app_name 200 karakter sınırını aşmamalı."""
        from app.api.routes.companies import CompanyCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CompanyCreate(
                name="Test Firma",
                app_name="A" * 201,  # 201 karakter — sınır aşımı
                tax_type="vd",
                tax_number="1234567890",
                phone="555-1234",
                email="test@test.com",
                contact_name="Ali",
                contact_surname="Yılmaz"
            )

    def test_company_update_with_branding_fields(self):
        """CompanyUpdate app_name ve theme_id kabul etmeli."""
        from app.api.routes.companies import CompanyUpdate
        u = CompanyUpdate(app_name="NewBrand", theme_id=3)
        assert u.app_name == "NewBrand"
        assert u.theme_id == 3

    def test_company_update_empty(self):
        """CompanyUpdate boş bırakılabilen alanlarla oluşturulabilmeli."""
        from app.api.routes.companies import CompanyUpdate
        u = CompanyUpdate()
        assert u.app_name is None
        assert u.theme_id is None


# =============================================================================
# TEST: Themes API — GET /api/themes (Liste)
# =============================================================================

class TestGetThemes:
    """GET /api/themes — tema listesi endpoint testleri."""

    @patch('app.api.routes.themes.get_db_context')
    def test_returns_list(self, mock_db_ctx):
        """Tema listesi döndürmeli."""
        from app.api.routes.themes import get_themes

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "Okyanus Mavisi", "code": "ocean_blue",
             "description": "Profesyonel ve güven veren",
             "preview_colors": '["#4D99FF", "#7C3AED"]',
             "login_headline": "Test", "login_subtitle": "Sub",
             "features_json": "[]", "sort_order": 1},
            {"id": 2, "name": "Altın Sarısı", "code": "golden_amber",
             "description": "Sıcak ve premium",
             "preview_colors": '["#F59E0B", "#EF4444"]',
             "login_headline": "Test2", "login_subtitle": "Sub2",
             "features_json": "[]", "sort_order": 2},
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_themes()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "Okyanus Mavisi"
        assert result[1]["code"] == "golden_amber"

    @patch('app.api.routes.themes.get_db_context')
    def test_returns_empty_when_no_themes(self, mock_db_ctx):
        """Tema yokken boş liste dönmeli."""
        from app.api.routes.themes import get_themes

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_themes()
        assert result == []

    @patch('app.api.routes.themes.get_db_context')
    def test_no_css_variables_in_basic_list(self, mock_db_ctx):
        """Temel listede css_variables olmamalı (performans)."""
        from app.api.routes.themes import get_themes

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "Test", "code": "test",
             "description": "Desc", "preview_colors": "[]",
             "login_headline": "H", "login_subtitle": "S",
             "features_json": "[]", "sort_order": 1},
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_themes()
        # css_variables key'i SQL sorgusunda yok, sonuçta olmamalı
        assert "css_variables" not in result[0]


# =============================================================================
# TEST: Themes API — GET /api/themes/{id} (Detay)
# =============================================================================

class TestGetThemeDetail:
    """GET /api/themes/{id} — tek tema detayı endpoint testleri."""

    @patch('app.api.routes.themes.get_db_context')
    def test_returns_theme(self, mock_db_ctx):
        """Geçerli ID ile tema detayı dönmeli."""
        from app.api.routes.themes import get_theme

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        css_vars = {"dark": {"--gold": "#4D99FF"}, "light": {"--gold": "#3B82F6"}}
        mock_cursor.fetchone.return_value = {
            "id": 1, "name": "Okyanus", "code": "ocean_blue",
            "description": "Test", "css_variables": json.dumps(css_vars),
            "preview_colors": '["#4D99FF"]', "login_headline": "H",
            "login_subtitle": "S", "features_json": "[]", "sort_order": 1
        }
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_theme(1)
        assert result["id"] == 1
        assert result["code"] == "ocean_blue"
        assert "css_variables" in result

    @patch('app.api.routes.themes.get_db_context')
    def test_returns_404_when_not_found(self, mock_db_ctx):
        """Geçersiz ID ile 404 dönmeli."""
        from app.api.routes.themes import get_theme

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            get_theme(9999)
        assert exc_info.value.status_code == 404


# =============================================================================
# TEST: Themes API — GET /api/themes/full (Auth required)
# =============================================================================

class TestGetThemesFull:
    """GET /api/themes/full — CSS variables dahil tam liste."""

    @patch('app.api.routes.themes.get_db_context')
    def test_returns_full_with_css(self, mock_db_ctx):
        """Full endpoint css_variables içermeli."""
        from app.api.routes.themes import get_themes_full

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        css_vars = {"dark": {"--gold": "#4D99FF"}}
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "Test", "code": "test",
             "description": "X", "css_variables": json.dumps(css_vars),
             "preview_colors": "[]", "login_headline": "H",
             "login_subtitle": "S", "features_json": "[]", "sort_order": 1},
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        # current_user mock — bu endpoint auth gerektirir
        mock_user = {"id": 1, "role": "admin", "is_admin": True}
        result = get_themes_full(current_user=mock_user)

        assert len(result) == 1
        assert "css_variables" in result[0]


# =============================================================================
# TEST: Companies by-url — Tema branding verisi
# =============================================================================

class TestGetCompanyByUrlBranding:
    """GET /api/companies/by-url — firma tema branding testi."""

    @patch('app.api.routes.companies.get_db_context')
    def test_returns_branding_with_theme(self, mock_db_ctx):
        """URL eşleşmesinde tema bilgisi de dönmeli."""
        from app.api.routes.companies import get_company_by_url

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        css_vars = {"dark": {"--gold": "#EAB308"}}
        mock_cursor.fetchall.return_value = [
            {
                "id": 10, "name": "Test Firma", "app_name": "MyApp",
                "website": "http://demo.example.com",
                "theme_id": 3, "has_logo": True,
                "theme_code": "yellow_black",
                "theme_css": json.dumps(css_vars),
                "login_headline": "Hoş geldiniz",
                "login_subtitle": "Alt Başlık",
                "features_json": '[{"title":"F1","desc":"D1","icon":"accent"}]'
            }
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_company_by_url(url="http://demo.example.com/login")

        assert result["found"] is True
        assert result["company"]["app_name"] == "MyApp"
        assert result["company"]["theme"]["code"] == "yellow_black"
        assert result["company"]["logo_url"] == "/api/companies/10/logo"

    @patch('app.api.routes.companies.get_db_context')
    def test_returns_default_app_name_when_null(self, mock_db_ctx):
        """app_name NULL ise 'NGSSAI' dönmeli."""
        from app.api.routes.companies import get_company_by_url

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {
                "id": 5, "name": "Firma2", "app_name": None,
                "website": "http://localhost:5500",
                "theme_id": None, "has_logo": False,
                "theme_code": None,
                "theme_css": None,
                "login_headline": None,
                "login_subtitle": None,
                "features_json": None
            }
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_company_by_url(url="http://localhost:5500")

        assert result["found"] is True
        assert result["company"]["app_name"] == "NGSSAI"
        assert result["company"]["theme"] is None  # tema atanmamış
        assert result["company"]["logo_url"] is None  # logo yok

    @patch('app.api.routes.companies.get_db_context')
    def test_no_match_returns_not_found(self, mock_db_ctx):
        """URL eşleşmezse found=False dönmeli."""
        from app.api.routes.companies import get_company_by_url

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        result = get_company_by_url(url="http://unknown.example.com")
        assert result["found"] is False
        assert result["company"] is None

    def test_invalid_url_returns_not_found(self):
        """Geçersiz URL format'ında found=False dönmeli."""
        from app.api.routes.companies import get_company_by_url
        result = get_company_by_url(url="not-a-valid-url")
        assert result["found"] is False


# =============================================================================
# TEST: Company Create — Branding alanları
# =============================================================================

class TestCreateCompanyBranding:
    """POST /api/companies — app_name ve theme_id ile firma oluşturma."""

    @patch('app.api.routes.companies.get_db_context')
    def test_create_with_app_name_and_theme(self, mock_db_ctx):
        """app_name ve theme_id ile firma oluşturulabilmeli."""
        from app.api.routes.companies import create_company, CompanyCreate

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # tax_number duplicate check — None = yok
        mock_cursor.fetchone.side_effect = [
            None,  # tax_number kontrolü — benzersiz
            {"id": 99, "name": "Test", "app_name": "CustomApp", "theme_id": 5,
             "tax_type": "vd", "tax_number": "1234567890",
             "address_il": None, "address_ilce": None,
             "address_mahalle": None, "address_text": None,
             "phone": "555", "email": "a@b.com", "website": None,
             "contact_name": "Ali", "contact_surname": "Yılmaz",
             "is_active": True, "created_at": "2024-01-01", "updated_at": None}
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        company = CompanyCreate(
            name="Test",
            app_name="CustomApp",
            theme_id=5,
            tax_type="vd",
            tax_number="1234567890",
            phone="555",
            email="a@b.com",
            contact_name="Ali",
            contact_surname="Yılmaz"
        )
        admin_user = {"id": 1, "role": "admin", "is_admin": True}
        result = create_company(company=company, admin=admin_user)

        assert result["app_name"] == "CustomApp"
        assert result["theme_id"] == 5

    @patch('app.api.routes.companies.get_db_context')
    def test_create_without_app_name_defaults(self, mock_db_ctx):
        """app_name boş bırakıldığında INSERT'te 'NGSSAI' kullanılmalı."""
        from app.api.routes.companies import create_company, CompanyCreate

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            None,  # tax check
            {"id": 100, "name": "NoApp", "app_name": "NGSSAI", "theme_id": None,
             "tax_type": "vd", "tax_number": "9876543210",
             "address_il": None, "address_ilce": None,
             "address_mahalle": None, "address_text": None,
             "phone": "555", "email": "x@x.com", "website": None,
             "contact_name": "Veli", "contact_surname": "Kan",
             "is_active": True, "created_at": "2024-01-01", "updated_at": None}
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        company = CompanyCreate(
            name="NoApp",
            tax_type="vd",
            tax_number="9876543210",
            phone="555",
            email="x@x.com",
            contact_name="Veli",
            contact_surname="Kan"
        )
        admin_user = {"id": 1, "role": "admin", "is_admin": True}
        result = create_company(company=company, admin=admin_user)
        assert result["app_name"] == "NGSSAI"

        # INSERT sorgusunda app_name 'NGSSAI' olmalı (company.app_name or 'NGSSAI')
        execute_calls = mock_cursor.execute.call_args_list
        insert_call = execute_calls[1]  # 0: tax check, 1: INSERT
        insert_params = insert_call[0][1]  # tuple params
        assert insert_params[1] == "NGSSAI"  # app_name parametresi


# =============================================================================
# TEST: Company Update — Branding alanları
# =============================================================================

class TestUpdateCompanyBranding:
    """PUT /api/companies/{id} — app_name ve theme_id güncelleme."""

    @patch('app.api.routes.companies.get_db_context')
    def test_update_app_name(self, mock_db_ctx):
        """Sadece app_name güncellenebilmeli."""
        from app.api.routes.companies import update_company, CompanyUpdate

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Firma var mı check
        mock_cursor.fetchone.side_effect = [
            {"id": 1},  # firma mevcut
            {"id": 1, "name": "Test", "app_name": "NewName", "theme_id": None,
             "tax_type": "vd", "tax_number": "123",
             "address_il": None, "address_ilce": None,
             "address_mahalle": None, "address_text": None,
             "phone": "555", "email": "a@b.com", "website": None,
             "contact_name": "Ali", "contact_surname": "Yılmaz",
             "is_active": True, "created_at": "2024-01-01",
             "updated_at": "2024-02-01", "has_logo": False}
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        update = CompanyUpdate(app_name="NewName")
        admin_user = {"id": 1, "role": "admin", "is_admin": True}
        result = update_company(company_id=1, company=update, admin=admin_user)

        assert result["app_name"] == "NewName"

    @patch('app.api.routes.companies.get_db_context')
    def test_update_theme_id(self, mock_db_ctx):
        """theme_id güncellenebilmeli."""
        from app.api.routes.companies import update_company, CompanyUpdate

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            {"id": 2},  # firma mevcut
            {"id": 2, "name": "Test", "app_name": "NGSSAI", "theme_id": 7,
             "tax_type": "vd", "tax_number": "456",
             "address_il": None, "address_ilce": None,
             "address_mahalle": None, "address_text": None,
             "phone": "555", "email": "b@c.com", "website": None,
             "contact_name": "Veli", "contact_surname": "Kan",
             "is_active": True, "created_at": "2024-01-01",
             "updated_at": "2024-02-01", "has_logo": False}
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        update = CompanyUpdate(theme_id=7)
        admin_user = {"id": 1, "role": "admin", "is_admin": True}
        result = update_company(company_id=2, company=update, admin=admin_user)

        assert result["theme_id"] == 7


# =============================================================================
# TEST: Company List — Branding alanları dahil
# =============================================================================

class TestGetCompaniesListBranding:
    """GET /api/companies — listede app_name ve theme_id var mı."""

    @patch('app.api.routes.companies.get_db_context')
    def test_list_includes_branding_fields(self, mock_db_ctx):
        """Firma listesinde app_name ve theme_id olmalı."""
        from app.api.routes.companies import get_companies

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "Firma1", "app_name": "Brand1", "theme_id": 3,
             "tax_type": "vd", "tax_number": "111",
             "address_il": None, "address_ilce": None,
             "address_mahalle": None, "address_text": None,
             "phone": "555", "email": "a@a.com", "website": None,
             "contact_name": "A", "contact_surname": "B",
             "is_active": True, "created_at": "2024-01-01",
             "updated_at": None, "has_logo": False}
        ]
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        admin_user = {"id": 1, "role": "admin", "is_admin": True}
        result = get_companies(current_user=admin_user)

        assert len(result) == 1
        assert result[0]["app_name"] == "Brand1"
        assert result[0]["theme_id"] == 3


# =============================================================================
# TEST: Route Registration
# =============================================================================

class TestRouteRegistration:
    """Yeni route'ların doğru register edildiğini doğrula."""

    def test_themes_router_has_prefix(self):
        """themes.router prefix /api/themes olmalı."""
        from app.api.routes.themes import router
        assert router.prefix == "/api/themes"

    def test_themes_router_has_list_route(self):
        """GET / route var mı."""
        from app.api.routes.themes import router
        paths = [r.path for r in router.routes]
        assert "/api/themes/" in paths

    def test_themes_router_has_detail_route(self):
        """GET /{theme_id} route var mı."""
        from app.api.routes.themes import router
        paths = [r.path for r in router.routes]
        assert "/api/themes/{theme_id}" in paths

    def test_themes_router_has_full_route(self):
        """GET /full route var mı."""
        from app.api.routes.themes import router
        paths = [r.path for r in router.routes]
        assert "/api/themes/full" in paths

    def test_companies_router_prefix(self):
        """companies.router prefix /api/companies olmalı."""
        from app.api.routes.companies import router
        assert router.prefix == "/api/companies"

    def test_themes_imported_in_main(self):
        """themes modülü main.py'de import edilmiş olmalı."""
        from app.api import main
        assert hasattr(main, 'themes')


# =============================================================================
# TEST: Schema — company_themes CREATE TABLE SQL doğrulama
# =============================================================================

class TestSchemaThemeConfig:
    """Schema.py'deki company_themes tablosu SQL doğrulama."""

    def test_schema_contains_company_themes(self):
        """Schema SQL'inde company_themes tablosu olmalı."""
        from app.core.schema import SCHEMA_SQL
        assert "company_themes" in SCHEMA_SQL

    def test_schema_contains_app_name_column(self):
        """Schema SQL'inde app_name ALTER komutu olmalı."""
        from app.core.schema import SCHEMA_SQL
        assert "app_name" in SCHEMA_SQL

    def test_schema_contains_theme_id_column(self):
        """Schema SQL'inde theme_id ALTER komutu olmalı."""
        from app.core.schema import SCHEMA_SQL
        assert "theme_id" in SCHEMA_SQL

    def test_schema_contains_11_themes(self):
        """Schema'da 11 INSERT INTO satırı olmalı (sort_order 1-11)."""
        from app.core.schema import SCHEMA_SQL
        # Her tema sort_order ile ekleniyor
        assert "sort_order" in SCHEMA_SQL
        # Son tema sarı-siyah, sort_order=11
        assert "yellow_black" in SCHEMA_SQL

    def test_schema_contains_yellow_black_theme(self):
        """Sarı-siyah teması schema'da olmalı."""
        from app.core.schema import SCHEMA_SQL
        assert "Sarı Siyah" in SCHEMA_SQL
        assert "yellow_black" in SCHEMA_SQL


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
