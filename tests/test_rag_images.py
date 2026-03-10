"""
VYRA L1 Support API - RAG Images API Unit Tests
=================================================
RAG görsel endpoint'leri unit testleri.

Test Kapsamı:
- GET /images/by-file/{file_id} — metadata listesi
- GET /images/{image_id} — binary görsel döndürme
- GET /images/{image_id}/ocr — OCR metin endpoint
- Route sıralama doğrulaması (literal path → parametreli path)
- X-Has-OCR header kontrolü
- Hata durumları (404, 500)
"""

import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_db_row_with_image():
    """OCR metni olan görsel DB row mockı."""
    return {
        "image_data": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        "image_format": "png",
        "ocr_text": "Test OCR metin",
    }


@pytest.fixture
def mock_db_row_without_ocr():
    """OCR metni olmayan görsel DB row mockı."""
    return {
        "image_data": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        "image_format": "jpeg",
        "ocr_text": "",
    }


@pytest.fixture
def mock_file_images_rows():
    """by-file endpoint için çoklu görsel row mockı."""
    return [
        {
            "id": 1, "image_index": 0, "image_format": "png",
            "width_px": 800, "height_px": 600, "file_size_bytes": 5000,
            "context_heading": "Giriş", "context_chunk_index": 0,
            "alt_text": "Görsel 1", "ocr_preview": "OCR preview text",
            "has_ocr": True
        },
        {
            "id": 2, "image_index": 1, "image_format": "jpeg",
            "width_px": 1024, "height_px": 768, "file_size_bytes": 12000,
            "context_heading": "Bölüm 2", "context_chunk_index": 1,
            "alt_text": "Görsel 2", "ocr_preview": "",
            "has_ocr": False
        },
    ]


@pytest.fixture
def mock_ocr_row():
    """OCR endpoint için DB row mockı."""
    return {
        "ocr_text": "Bu bir OCR metin sonucudur.\nİkinci satır.",
        "alt_text": "Test görseli",
        "context_heading": "Bölüm 1"
    }


# =============================================================================
# get_file_images ENDPOINT TESTLERİ
# =============================================================================

class TestGetFileImages:
    """GET /images/by-file/{file_id} endpoint testleri."""

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_returns_image_list(self, mock_get_db, mock_file_images_rows):
        """Dosyaya ait görsellerin metadata listesini döndürmeli."""
        from app.api.routes.rag_images import get_file_images
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_file_images_rows
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_file_images(file_id=1))
        
        assert result["file_id"] == 1
        assert result["total_images"] == 2
        assert len(result["images"]) == 2
        assert result["images"][0]["has_ocr"] is True
        assert result["images"][1]["has_ocr"] is False
        assert result["images"][0]["ocr_preview"] == "OCR preview text"
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_empty_file(self, mock_get_db):
        """Görsel olmayan dosya için boş liste dönmeli."""
        from app.api.routes.rag_images import get_file_images
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_file_images(file_id=999))
        
        assert result["total_images"] == 0
        assert result["images"] == []
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_db_error_returns_500(self, mock_get_db):
        """DB hatası 500 dönmeli."""
        from app.api.routes.rag_images import get_file_images
        from fastapi import HTTPException
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("DB connection failed")
        mock_get_db.return_value = mock_conn
        
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(get_file_images(file_id=1))
        
        assert exc_info.value.status_code == 500
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_url_field_format(self, mock_get_db, mock_file_images_rows):
        """url alanı /api/rag/images/{id} formatında olmalı."""
        from app.api.routes.rag_images import get_file_images
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_file_images_rows
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_file_images(file_id=1))
        
        assert result["images"][0]["url"] == "/api/rag/images/1"
        assert result["images"][1]["url"] == "/api/rag/images/2"


# =============================================================================
# get_document_image ENDPOINT TESTLERİ
# =============================================================================

class TestGetDocumentImage:
    """GET /images/{image_id} endpoint testleri."""

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_returns_binary_image(self, mock_get_db, mock_db_row_with_image):
        """Görsel binary olarak dönmeli."""
        from app.api.routes.rag_images import get_document_image
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_db_row_with_image
        mock_get_db.return_value = mock_conn
        
        response = asyncio.get_event_loop().run_until_complete(get_document_image(image_id=1))
        
        assert response.media_type == "image/png"
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_has_ocr_header_true(self, mock_get_db, mock_db_row_with_image):
        """OCR metni varken X-Has-OCR: true olmalı."""
        from app.api.routes.rag_images import get_document_image
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_db_row_with_image
        mock_get_db.return_value = mock_conn
        
        response = asyncio.get_event_loop().run_until_complete(get_document_image(image_id=1))
        
        assert response.headers["X-Has-OCR"] == "true"

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_has_ocr_header_false(self, mock_get_db, mock_db_row_without_ocr):
        """OCR metni yokken X-Has-OCR: false olmalı."""
        from app.api.routes.rag_images import get_document_image
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_db_row_without_ocr
        mock_get_db.return_value = mock_conn
        
        response = asyncio.get_event_loop().run_until_complete(get_document_image(image_id=1))
        
        assert response.headers["X-Has-OCR"] == "false"

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_not_found_returns_404(self, mock_get_db):
        """Bulunamayan görsel 404 dönmeli."""
        from app.api.routes.rag_images import get_document_image
        from fastapi import HTTPException
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_get_db.return_value = mock_conn
        
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(get_document_image(image_id=999))
        
        assert exc_info.value.status_code == 404
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_memoryview_conversion(self, mock_get_db):
        """memoryview otomatik bytes'a çevrilmeli."""
        from app.api.routes.rag_images import get_document_image
        import asyncio
        
        row = {
            "image_data": memoryview(b"\x89PNG" + b"\x00" * 100),
            "image_format": "png",
            "ocr_text": ""
        }
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = row
        mock_get_db.return_value = mock_conn
        
        response = asyncio.get_event_loop().run_until_complete(get_document_image(image_id=1))
        
        # Hata fırlatmadan tamamlanmalı
        assert response.media_type == "image/png"

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_cache_control_header(self, mock_get_db, mock_db_row_with_image):
        """Cache-Control header'ı olmalı."""
        from app.api.routes.rag_images import get_document_image
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_db_row_with_image
        mock_get_db.return_value = mock_conn
        
        response = asyncio.get_event_loop().run_until_complete(get_document_image(image_id=1))
        
        assert "Cache-Control" in response.headers
        assert "86400" in response.headers["Cache-Control"]


# =============================================================================
# get_image_ocr_text ENDPOINT TESTLERİ
# =============================================================================

class TestGetImageOcrText:
    """GET /images/{image_id}/ocr endpoint testleri."""

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_returns_ocr_text(self, mock_get_db, mock_ocr_row):
        """OCR metnini JSON olarak döndürmeli."""
        from app.api.routes.rag_images import get_image_ocr_text
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_ocr_row
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=1))
        
        assert result["image_id"] == 1
        assert result["has_text"] is True
        assert "OCR metin" in result["ocr_text"]
        assert result["context_heading"] == "Bölüm 1"
        assert result["alt_text"] == "Test görseli"
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_empty_ocr_text(self, mock_get_db):
        """OCR metin yoksa has_text: false olmalı."""
        from app.api.routes.rag_images import get_image_ocr_text
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "ocr_text": "",
            "alt_text": "",
            "context_heading": ""
        }
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=1))
        
        assert result["has_text"] is False
        assert result["ocr_text"] == ""

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_null_ocr_text(self, mock_get_db):
        """ocr_text NULL ise has_text: false olmalı, crash olmamalı."""
        from app.api.routes.rag_images import get_image_ocr_text
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "ocr_text": None,
            "alt_text": None,
            "context_heading": None
        }
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=1))
        
        assert result["has_text"] is False
        assert result["ocr_text"] == ""

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_not_found_returns_404(self, mock_get_db):
        """Bulunamayan görsel 404 dönmeli."""
        from app.api.routes.rag_images import get_image_ocr_text
        from fastapi import HTTPException
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_get_db.return_value = mock_conn
        
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=999))
        
        assert exc_info.value.status_code == 404

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_strips_whitespace(self, mock_get_db):
        """OCR metin başında/sonundaki whitespace temizlenmeli."""
        from app.api.routes.rag_images import get_image_ocr_text
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "ocr_text": "  \n  temiz metin  \n  ",
            "alt_text": "",
            "context_heading": ""
        }
        mock_get_db.return_value = mock_conn
        
        result = asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=1))
        
        assert result["ocr_text"] == "temiz metin"
        assert result["has_text"] is True


# =============================================================================
# ROUTE SIRALAMA TESTİ
# =============================================================================

class TestRouteOrdering:
    """FastAPI route sıralaması doğrulaması."""

    def test_by_file_route_before_image_id(self):
        """by-file literal path, {image_id} parametreli path'ten ÖNCE tanımlı olmalı."""
        from app.api.routes.rag_images import router
        
        routes = [route.path for route in router.routes]
        
        by_file_idx = None
        image_id_idx = None
        
        for i, path in enumerate(routes):
            if "by-file" in path:
                by_file_idx = i
            elif path == "/images/{image_id}" and image_id_idx is None:
                image_id_idx = i
        
        assert by_file_idx is not None, "by-file route bulunamadı"
        assert image_id_idx is not None, "{image_id} route bulunamadı"
        assert by_file_idx < image_id_idx, (
            f"by-file route ({by_file_idx}) image_id route'tan ({image_id_idx}) ÖNCE olmalı!"
        )

    def test_ocr_route_exists(self):
        """OCR endpoint'i route listesinde olmalı."""
        from app.api.routes.rag_images import router
        
        routes = [route.path for route in router.routes]
        
        assert any("/ocr" in path for path in routes), "OCR route bulunamadı"


# =============================================================================
# CONNECTION CLEANUP TESTİ
# =============================================================================

class TestConnectionCleanup:
    """Tüm endpoint'lerde connection kapatılıyor mu kontrolü."""

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_conn_closed_on_success(self, mock_get_db, mock_ocr_row):
        """Başarılı istekte connection kapatılmalı."""
        from app.api.routes.rag_images import get_image_ocr_text
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_ocr_row
        mock_get_db.return_value = mock_conn
        
        asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=1))
        
        mock_conn.close.assert_called_once()

    @patch('app.api.routes.rag_images.get_db_conn')
    def test_conn_closed_on_error(self, mock_get_db):
        """Hata durumunda da connection kapatılmalı (finally)."""
        from app.api.routes.rag_images import get_image_ocr_text
        from fastapi import HTTPException
        import asyncio
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("DB Error")
        mock_get_db.return_value = mock_conn
        
        with pytest.raises(HTTPException):
            asyncio.get_event_loop().run_until_complete(get_image_ocr_text(image_id=1))
        
        mock_conn.close.assert_called_once()
