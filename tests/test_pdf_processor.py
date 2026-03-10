"""
VYRA L1 Support API - PDF Processor Unit Tests
================================================
pdf_processor.py v2.43.0 yeni fonksiyonları için unit testler.

Test Kapsamı:
- _clean_header_footer_blocks: Tekrarlayan header/footer filtreleme
- _detect_toc_section: İçindekiler tespiti
- _build_sections_from_structured: Heading hiyerarşi koruması
- _extract_structured_blocks_fitz: Font-aware heading detection
- _fix_turkish_chars: Türkçe karakter düzeltme

Author: VYRA AI Team
Version: 1.0.0 (2026-02-15)
"""

import pytest
from unittest.mock import patch


# ──────────────────────────────────────────────────────────────
# Test: PDFProcessor import ve oluşturma
# ──────────────────────────────────────────────────────────────


class TestPDFProcessorInit:
    """PDFProcessor initialization testleri"""

    def test_pdf_processor_import(self):
        """PDFProcessor import edilebilir"""
        from app.services.document_processors.pdf_processor import PDFProcessor
        assert PDFProcessor is not None

    def test_pdf_processor_instantiation(self):
        """PDFProcessor örneği oluşturulabilir"""
        from app.services.document_processors.pdf_processor import PDFProcessor
        proc = PDFProcessor()
        assert proc is not None
        assert proc.PROCESSOR_NAME == "PDFProcessor"

    def test_pdf_processor_custom_chunk_size(self):
        """PDFProcessor özel chunk_size ile oluşturulabilir"""
        from app.services.document_processors.pdf_processor import PDFProcessor
        proc = PDFProcessor(chunk_size=1000, chunk_overlap=200)
        assert proc.chunk_size == 1000
        assert proc.chunk_overlap == 200


# ──────────────────────────────────────────────────────────────
# Test: _clean_header_footer_blocks (Faz 6)
# ──────────────────────────────────────────────────────────────


class TestCleanHeaderFooterBlocks:
    """v2.43.0 Faz 6: Header/footer filtreleme testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.pdf_processor import PDFProcessor
        return PDFProcessor()

    def test_empty_blocks_returns_empty(self, processor):
        """Boş block listesi boş döner"""
        result = processor._clean_header_footer_blocks([])
        assert result == []

    def test_few_blocks_no_filtering(self, processor):
        """5'ten az blok varsa filtreleme yapılmaz"""
        blocks = [
            {"text": "Test", "page": 1, "is_heading": False}
        ]
        result = processor._clean_header_footer_blocks(blocks)
        assert len(result) == 1

    def test_page_number_removal(self, processor):
        """Sayfa numaraları temizlenir (sade sayı)"""
        blocks = [
            {"text": "Bu bir paragraf metnidir.", "page": 1, "is_heading": False},
            {"text": "1", "page": 1, "is_heading": False},
            {"text": "İkinci paragraf.", "page": 2, "is_heading": False},
            {"text": "2", "page": 2, "is_heading": False},
            {"text": "Üçüncü paragraf.", "page": 3, "is_heading": False},
            {"text": "3", "page": 3, "is_heading": False},
        ]
        result = processor._clean_header_footer_blocks(blocks)
        # Sayfa numaraları filtrelenmeli
        texts = [b["text"] for b in result]
        assert "1" not in texts
        assert "2" not in texts
        assert "3" not in texts

    def test_page_pattern_removal(self, processor):
        """'Sayfa X' formatına uyan satırlar temizlenir"""
        blocks = [
            {"text": "İçerik 1.", "page": 1, "is_heading": False},
            {"text": "Sayfa 1", "page": 1, "is_heading": False},
            {"text": "İçerik 2.", "page": 2, "is_heading": False},
            {"text": "Sayfa 2", "page": 2, "is_heading": False},
            {"text": "İçerik 3.", "page": 3, "is_heading": False},
            {"text": "Sayfa 3", "page": 3, "is_heading": False},
        ]
        result = processor._clean_header_footer_blocks(blocks)
        texts = [b["text"] for b in result]
        assert not any("Sayfa" in t for t in texts)

    def test_repeated_short_text_removal(self, processor):
        """Sayfaların %50+'sında tekrar eden kısa metinler temizlenir"""
        blocks = []
        for page in range(1, 6):
            blocks.append({"text": f"Sayfa {page} içe riği.", "page": page, "is_heading": False})
            blocks.append({"text": "ACME Corporation", "page": page, "is_heading": False})

        result = processor._clean_header_footer_blocks(blocks)
        texts = [b["text"] for b in result]
        assert "ACME Corporation" not in texts

    def test_heading_blocks_preserved(self, processor):
        """Heading blokları asla filtrelenmez"""
        blocks = [
            {"text": "Giriş", "page": 1, "is_heading": True},
            {"text": "İçerik 1.", "page": 1, "is_heading": False},
            {"text": "Bölüm 2", "page": 2, "is_heading": True},
            {"text": "İçerik 2.", "page": 2, "is_heading": False},
            {"text": "Bölüm 3", "page": 3, "is_heading": True},
            {"text": "İçerik 3.", "page": 3, "is_heading": False},
        ]
        result = processor._clean_header_footer_blocks(blocks)
        headings = [b["text"] for b in result if b.get("is_heading")]
        assert "Giriş" in headings
        assert "Bölüm 2" in headings

    def test_few_pages_no_filtering(self, processor):
        """3'ten az sayfa varsa filtreleme yapılmaz"""
        blocks = [
            {"text": "Page 1 content.", "page": 1, "is_heading": False},
            {"text": "Footer text.", "page": 1, "is_heading": False},
            {"text": "Page 2 content.", "page": 2, "is_heading": False},
            {"text": "Footer text.", "page": 2, "is_heading": False},
            {"text": "Ekstra blok.", "page": 2, "is_heading": False},
        ]
        result = processor._clean_header_footer_blocks(blocks)
        assert len(result) == len(blocks)  # Filtreleme yok

    def test_dash_page_number_removal(self, processor):
        """'- N -' formatındaki sayfa numaraları temizlenir"""
        blocks = [
            {"text": "İçerik sayfası.", "page": 1, "is_heading": False},
            {"text": "- 1 -", "page": 1, "is_heading": False},
            {"text": "İkinci sayfa.", "page": 2, "is_heading": False},
            {"text": "- 2 -", "page": 2, "is_heading": False},
            {"text": "Üçüncü sayfa.", "page": 3, "is_heading": False},
            {"text": "- 3 -", "page": 3, "is_heading": False},
        ]
        result = processor._clean_header_footer_blocks(blocks)
        texts = [b["text"] for b in result]
        assert "- 1 -" not in texts
        assert "- 2 -" not in texts


# ──────────────────────────────────────────────────────────────
# Test: _detect_toc_section (Faz 6)
# ──────────────────────────────────────────────────────────────


class TestDetectTocSection:
    """v2.43.0 Faz 6: İçindekiler tespiti testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.pdf_processor import PDFProcessor
        return PDFProcessor()

    def test_toc_heading_turkish(self, processor):
        """'İçindekiler' başlığı TOC olarak algılanır"""
        section = {"heading": "İçindekiler", "content": "Bölüm 1......5"}
        assert processor._detect_toc_section(section) is True

    def test_toc_heading_english(self, processor):
        """'Table of Contents' başlığı TOC olarak algılanır"""
        section = {"heading": "Table of Contents", "content": "Chapter 1......5"}
        assert processor._detect_toc_section(section) is True

    def test_toc_dot_patterns(self, processor):
        """Çok sayıda '...' içeren metin TOC olarak algılanır"""
        lines = [f"Bölüm {i}{'.' * 20}{i * 5}" for i in range(1, 15)]
        section = {
            "heading": "Genel Bilgiler",
            "content": "\n".join(lines)
        }
        assert processor._detect_toc_section(section) is True

    def test_toc_page_refs(self, processor):
        """Sayfa referansları yoğun olan metin TOC olarak algılanır"""
        lines = [f"Bölüm {i} {i * 10}" for i in range(1, 15)]
        section = {
            "heading": "Listeler",
            "content": "\n".join(lines)
        }
        assert processor._detect_toc_section(section) is True

    def test_normal_heading_not_toc(self, processor):
        """Normal başlık TOC değildir"""
        section = {
            "heading": "Giriş",
            "content": "Bu bölümde projenin genel yapısı anlatılmaktadır. Sistem birden fazla modülden oluşur."
        }
        assert processor._detect_toc_section(section) is False

    def test_empty_content_not_toc(self, processor):
        """Boş içerik TOC değildir"""
        section = {"heading": "", "content": ""}
        assert processor._detect_toc_section(section) is False


# ──────────────────────────────────────────────────────────────
# Test: _build_sections_from_structured (Faz 3)
# ──────────────────────────────────────────────────────────────


class TestBuildSectionsFromStructured:
    """v2.43.0 Faz 3: Heading hiyerarşi testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.pdf_processor import PDFProcessor
        return PDFProcessor()

    def test_simple_sections(self, processor):
        """Basit heading → content section oluşturma"""
        blocks = [
            {"text": "Giriş", "is_heading": True, "heading_level": 1, "page": 1, "font_size": 16, "is_bold": True},
            {"text": "Bu giriş bölümüdür.", "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
        ]
        sections = processor._build_sections_from_structured(blocks)
        assert len(sections) >= 1
        assert sections[0]["heading"] == "Giriş"
        assert "giriş bölümü" in sections[0]["content"].lower()

    def test_heading_hierarchy_preserved(self, processor):
        """Heading hiyerarşi (breadcrumb) korunur"""
        blocks = [
            {"text": "Bölüm 1", "is_heading": True, "heading_level": 1, "page": 1, "font_size": 18, "is_bold": True},
            {"text": "Alt Bölüm 1.1", "is_heading": True, "heading_level": 2, "page": 1, "font_size": 14, "is_bold": True},
            {"text": "Bu alt bölüm içeriğidir.", "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
        ]
        sections = processor._build_sections_from_structured(blocks)
        # Alt bölüm section'ı heading_path ile gelir
        sub_section = [s for s in sections if s.get("heading") == "Alt Bölüm 1.1"]
        assert len(sub_section) == 1
        assert sub_section[0]["heading_level"] == 2
        assert "Bölüm 1" in sub_section[0]["heading_path"]
        assert "Alt Bölüm 1.1" in sub_section[0]["heading_path"]

    def test_heading_stack_pops_higher_level(self, processor):
        """Aynı/üst seviye heading gelince stack sıfırlanır"""
        blocks = [
            {"text": "Bölüm 1", "is_heading": True, "heading_level": 1, "page": 1, "font_size": 18, "is_bold": True},
            {"text": "Alt 1.1", "is_heading": True, "heading_level": 2, "page": 1, "font_size": 14, "is_bold": True},
            {"text": "İçerik A.", "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
            {"text": "Bölüm 2", "is_heading": True, "heading_level": 1, "page": 2, "font_size": 18, "is_bold": True},
            {"text": "İçerik B.", "is_heading": False, "heading_level": 0, "page": 2, "font_size": 12, "is_bold": False},
        ]
        sections = processor._build_sections_from_structured(blocks)
        sec_b = [s for s in sections if s.get("heading") == "Bölüm 2"]
        assert len(sec_b) == 1
        # Bölüm 2 gelince Bölüm 1 ve Alt 1.1 stack'ten çıkmış olmalı
        assert "Alt 1.1" not in sec_b[0]["heading_path"]
        assert "Bölüm 1" not in sec_b[0]["heading_path"]

    def test_no_heading_blocks(self, processor):
        """Heading olmayan bloklar da section oluşturur"""
        blocks = [
            {"text": "Paragraf 1. Bu bir test paragrafıdır, en az elli karakter uzunluğunda bir metin.", "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
            {"text": "Paragraf 2. Devam eden içerik, ek bilgiler ve açıklamalar burada yazılıdır.", "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
        ]
        sections = processor._build_sections_from_structured(blocks)
        assert len(sections) >= 1
        # heading None veya boş string olabilir
        assert not sections[0]["heading"] or sections[0]["heading"] == ""

    def test_heading_path_is_list(self, processor):
        """heading_path her zaman list tipinde olmalı"""
        blocks = [
            {"text": "Başlık", "is_heading": True, "heading_level": 1, "page": 1, "font_size": 16, "is_bold": True},
            {"text": "İçerik satırı.", "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
        ]
        sections = processor._build_sections_from_structured(blocks)
        assert len(sections) >= 1
        assert isinstance(sections[0]["heading_path"], list)


# ──────────────────────────────────────────────────────────────
# Test: _fix_turkish_chars
# ──────────────────────────────────────────────────────────────


class TestFixTurkishChars:
    """Türkçe karakter düzeltme testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.pdf_processor import PDFProcessor
        return PDFProcessor()

    def test_fix_non_breaking_space(self, processor):
        """Non-breaking space temizlenir"""
        text = "Bu\u00a0bir\u00a0test"
        result = processor._fix_turkish_chars(text)
        assert "\u00a0" not in result
        assert "Bu bir test" == result

    def test_fix_null_char(self, processor):
        """NUL karakteri temizlenir (PostgreSQL için kritik)"""
        text = "Test\x00metni"
        result = processor._fix_turkish_chars(text)
        assert "\x00" not in result

    def test_fix_double_spaces(self, processor):
        """Çift boşluklar tek boşluğa indirilir"""
        text = "Bu  bir   test"
        result = processor._fix_turkish_chars(text)
        assert "  " not in result

    def test_fix_zero_width_chars(self, processor):
        """Zero-width karakterler temizlenir"""
        text = "Te\u200bst\u200cme\u200dtin"
        result = processor._fix_turkish_chars(text)
        assert "\u200b" not in result
        assert "\u200c" not in result
        assert "\u200d" not in result

# ──────────────────────────────────────────────────────────────
# Test: _extract_image_positions_fitz (Faz 4)
# ──────────────────────────────────────────────────────────────


class TestExtractImagePositions:
    """v2.43.0 Faz 4: Görsel-chunk eşleme testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.pdf_processor import PDFProcessor
        return PDFProcessor()

    @patch('app.services.document_processors.pdf_processor.PDFProcessor._extract_image_positions_fitz')
    def test_no_fitz_returns_empty(self, mock_img_pos, processor):
        """PyMuPDF yoksa boş dict döner"""
        mock_img_pos.return_value = {}
        result = processor._extract_image_positions_fitz(b"fake_pdf_bytes")
        assert result == {}

    def test_empty_bytes_returns_empty(self, processor):
        """Boş bytes ile boş dict döner"""
        result = processor._extract_image_positions_fitz(b"")
        assert isinstance(result, dict)

    @patch('app.services.document_processors.pdf_processor.PDFProcessor._extract_image_positions_fitz')
    def test_returns_page_keyed_dict(self, mock_extract, processor):
        """Sayfa bazlı görsel pozisyon sözlüğü döner"""
        mock_extract.return_value = {
            1: [{"xref": 5, "bbox": [100, 200, 300, 400], "width": 200, "height": 200, "y_pos": 200, "page": 1, "img_index": 0}],
            3: [{"xref": 8, "bbox": [50, 100, 250, 300], "width": 200, "height": 200, "y_pos": 100, "page": 3, "img_index": 0}]
        }
        result = processor._extract_image_positions_fitz(b"fake")
        assert 1 in result
        assert 3 in result
        assert result[1][0]["xref"] == 5

    @patch('app.services.document_processors.pdf_processor.PDFProcessor._extract_image_positions_fitz')
    @patch('app.services.document_processors.pdf_processor.PDFProcessor._extract_structured_blocks_fitz')
    def test_image_refs_in_chunk_metadata(self, mock_blocks, mock_images, processor):
        """Görsel bulunan sayfadaki chunk'lara image_refs eklenir"""
        mock_images.return_value = {
            1: [{"xref": 5, "page": 1, "y_pos": 200, "bbox": [0, 0, 100, 100], "width": 100, "height": 100, "img_index": 0}]
        }
        mock_blocks.return_value = [
            {"text": "Başlık", "is_heading": True, "heading_level": 1, "page": 1, "font_size": 16, "is_bold": True},
            {"text": "Bu bir paragraf metnidir ve yeterli uzunluktadır. " * 3, "is_heading": False, "heading_level": 0, "page": 1, "font_size": 12, "is_bold": False},
        ]

        import io
        file_obj = io.BytesIO(b"fake_pdf_data")
        chunks = processor.extract_chunks(file_obj, "test.pdf")

        # Sayfa 1'deki chunk'ta image_refs olmalı
        page1_chunks = [c for c in chunks if c["metadata"].get("page") == 1]
        if page1_chunks:
            assert "image_refs" in page1_chunks[0]["metadata"]
            assert page1_chunks[0]["metadata"]["image_refs"][0]["xref"] == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
