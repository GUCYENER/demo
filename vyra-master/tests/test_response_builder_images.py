"""
VYRA L1 Support API - Response Builder Image Integration Tests
===============================================================
RAG yanıtlarındaki görsel referans entegrasyonu testleri.

Test Kapsamı:
- Chunk metadata'dan image_ids çıkarma
- Image HTML tag oluşturma
- Metadata string/dict/None durumları
- Max 4 görsel limiti
"""

import pytest
from unittest.mock import patch, MagicMock


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def match_with_images():
    """Görsel referansı olan RAG match verisi."""
    return {
        "chunk_text": "VPN bağlantısı için adımlar...",
        "file_name": "vpn_guide.pdf",
        "similarity_score": 0.85,
        "metadata": {"image_ids": [1, 2, 3]}
    }


@pytest.fixture
def match_without_images():
    """Görsel referansı olmayan RAG match verisi."""
    return {
        "chunk_text": "Ağ ayarları bilgisi",
        "file_name": "network_faq.docx",
        "similarity_score": 0.72,
        "metadata": {}
    }


@pytest.fixture
def match_with_string_metadata():
    """metadata alanı JSON string olarak gelen RAG match verisi."""
    return {
        "chunk_text": "Test metin",
        "file_name": "test.pdf",
        "similarity_score": 0.90,
        "metadata": '{"image_ids": [5, 6]}'
    }


# =============================================================================
# GÖRSEL REFERANS TESTLERİ
# =============================================================================

class TestImageReferences:
    """Response builder'da görsel referans entegrasyonu testleri."""

    def test_image_tags_in_response(self, match_with_images):
        """image_ids varsa, yanıtta img tag'leri olmalı."""
        from app.services.dialog.response_builder import format_single_result
        
        result = format_single_result(match_with_images)
        
        assert 'rag-inline-image' in result
        assert 'data-image-id="1"' in result
        assert 'data-image-id="2"' in result
        assert 'data-image-id="3"' in result
        assert '/api/rag/images/1' in result

    def test_no_images_section_when_empty(self, match_without_images):
        """image_ids yoksa İlgili Görseller bölümü olmamalı."""
        from app.services.dialog.response_builder import format_single_result
        
        result = format_single_result(match_without_images)
        
        assert 'rag-inline-image' not in result
        assert 'İlgili Görseller' not in result

    def test_string_metadata_parsed(self, match_with_string_metadata):
        """JSON string metadata doğru parse edilmeli."""
        from app.services.dialog.response_builder import format_single_result
        
        result = format_single_result(match_with_string_metadata)
        
        assert 'data-image-id="5"' in result
        assert 'data-image-id="6"' in result

    def test_max_4_images(self):
        """En fazla 4 görsel gösterilmeli."""
        from app.services.dialog.response_builder import format_single_result
        
        match = {
            "chunk_text": "Test",
            "file_name": "test.pdf",
            "similarity_score": 0.80,
            "metadata": {"image_ids": [1, 2, 3, 4, 5, 6]}
        }
        
        result = format_single_result(match)
        
        assert 'data-image-id="1"' in result
        assert 'data-image-id="4"' in result
        assert 'data-image-id="5"' not in result  # 5. ve 6. gösterilmemeli
        assert 'data-image-id="6"' not in result

    def test_none_metadata(self):
        """metadata None ise hata vermemeli."""
        from app.services.dialog.response_builder import format_single_result
        
        match = {
            "chunk_text": "Test",
            "file_name": "test.pdf",
            "similarity_score": 0.80,
            "metadata": None
        }
        
        result = format_single_result(match)
        
        assert 'rag-inline-image' not in result

    def test_invalid_json_metadata(self):
        """Geçersiz JSON string metadata hata vermemeli."""
        from app.services.dialog.response_builder import format_single_result
        
        match = {
            "chunk_text": "Test",
            "file_name": "test.pdf",
            "similarity_score": 0.80,
            "metadata": "{broken json}"
        }
        
        result = format_single_result(match)
        
        # Hata fırlatmamalı, görselsiz devam etmeli
        assert isinstance(result, str)
        assert 'rag-inline-image' not in result

    def test_missing_metadata_key(self):
        """metadata dizini yoksa hata vermemeli."""
        from app.services.dialog.response_builder import format_single_result
        
        match = {
            "chunk_text": "Test",
            "file_name": "test.pdf",
            "similarity_score": 0.80
            # metadata anahtarı yok
        }
        
        result = format_single_result(match)
        
        assert isinstance(result, str)
        assert 'rag-inline-image' not in result

    def test_image_tag_has_correct_attributes(self, match_with_images):
        """img tag'inde class, src, alt ve data-image-id olmalı."""
        from app.services.dialog.response_builder import format_single_result
        
        result = format_single_result(match_with_images)
        
        # İlk görselin tüm attributelarını kontrol et
        assert 'class="rag-inline-image"' in result
        assert 'src="/api/rag/images/1"' in result
        assert 'alt="Doküman görseli"' in result
        assert 'data-image-id="1"' in result
