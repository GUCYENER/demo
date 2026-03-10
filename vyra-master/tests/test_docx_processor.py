"""
VYRA L1 Support API - DOCX Processor Unit Tests
=================================================
docx_processor.py v2.43.0 heading hiyerarşi testleri.

Test Kapsamı:
- _chunks_from_document: Heading hiyerarşi + tablo metadata (Faz 3 + Faz 5)

Author: VYRA AI Team
Version: 1.0.0 (2026-02-15)
"""

import pytest
from unittest.mock import MagicMock, PropertyMock


class TestDOCXProcessorInit:
    """DOCXProcessor initialization testleri"""

    def test_docx_processor_import(self):
        """DOCXProcessor import edilebilir"""
        from app.services.document_processors.docx_processor import DOCXProcessor
        assert DOCXProcessor is not None

    def test_docx_processor_instantiation(self):
        """DOCXProcessor örneği oluşturulabilir"""
        from app.services.document_processors.docx_processor import DOCXProcessor
        proc = DOCXProcessor()
        assert proc is not None
        assert proc.PROCESSOR_NAME == "DOCXProcessor"


class TestDOCXHeadingHierarchy:
    """v2.43.0 Faz 3: DOCX heading hiyerarşi testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.docx_processor import DOCXProcessor
        return DOCXProcessor()

    def _make_mock_para(self, text, style_name=None):
        """Mock paragraph oluşturur"""
        para = MagicMock()
        para.text = text
        if style_name:
            para.style = MagicMock()
            para.style.name = style_name
        else:
            para.style = MagicMock()
            para.style.name = "Normal"
            # style.name.startswith('Heading') → False
        return para

    def _make_mock_doc(self, paragraphs, tables=None):
        """Mock document oluşturur"""
        doc = MagicMock()
        doc.paragraphs = paragraphs
        doc.tables = tables or []
        return doc

    def test_heading_level_extracted(self, processor):
        """Heading level doğru çıkarılır"""
        paragraphs = [
            self._make_mock_para("Bölüm 1", "Heading 1"),
            self._make_mock_para("Bu bölümün detaylı içeriğidir. Bu paragraf en az yüz karakter uzunluğunda olmalıdır, bu yüzden yeterli miktarda metin yazıyoruz."),
        ]
        doc = self._make_mock_doc(paragraphs)
        chunks = processor._chunks_from_document(doc)
        assert len(chunks) >= 1
        assert chunks[0]["metadata"]["heading_level"] == 1

    def test_heading_path_breadcrumb(self, processor):
        """Heading path (breadcrumb) doğru oluşturulur"""
        paragraphs = [
            self._make_mock_para("Bölüm 1", "Heading 1"),
            self._make_mock_para("Alt Bölüm 1.1", "Heading 2"),
            self._make_mock_para("Alt bölüm içeriği metnidir. Detaylar burada bulunur. Bu paragraf en az yüz karakter uzunluğunda olmalıdır, çeşitli açıklamalar ve bilgiler buraya yazılmıştır."),
        ]
        doc = self._make_mock_doc(paragraphs)
        chunks = processor._chunks_from_document(doc)
        # Alt bölüm chunk'ı heading_path'te her iki heading'i içermeli
        sub_chunks = [c for c in chunks if c["metadata"].get("heading") == "Alt Bölüm 1.1"]
        assert len(sub_chunks) >= 1
        path = sub_chunks[0]["metadata"]["heading_path"]
        assert "Bölüm 1" in path
        assert "Alt Bölüm 1.1" in path

    def test_heading_stack_reset_on_same_level(self, processor):
        """Aynı seviye heading gelince stack sıfırlanır"""
        paragraphs = [
            self._make_mock_para("Bölüm 1", "Heading 1"),
            self._make_mock_para("Bölüm 1 içeriği ve detaylı açıklama metni. Bu paragraf en az yüz karakter uzunluğunda olmalıdır, bu nedenle yeterli metin ekliyoruz."),
            self._make_mock_para("Bölüm 2", "Heading 1"),
            self._make_mock_para("Bölüm 2 içeriği ve detaylı açıklama metni. Bu paragraf da en az yüz karakter uzunluğunda olmalıdır, bu nedenle yeterli metin ekliyoruz."),
        ]
        doc = self._make_mock_doc(paragraphs)
        chunks = processor._chunks_from_document(doc)
        sec2_chunks = [c for c in chunks if c["metadata"].get("heading") == "Bölüm 2"]
        assert len(sec2_chunks) >= 1
        path = sec2_chunks[0]["metadata"]["heading_path"]
        assert "Bölüm 1" not in path
        assert "Bölüm 2" in path

    def test_no_heading_chunks(self, processor):
        """Heading olmayan paragraflar heading_level=0 alır"""
        paragraphs = [
            self._make_mock_para("Serbest paragraf metni. En az yüz karakter uzunluğunda olmak zorundadır, bu yüzden biraz daha uzun bir metin yazıyoruz burada."),
        ]
        doc = self._make_mock_doc(paragraphs)
        chunks = processor._chunks_from_document(doc)
        assert len(chunks) >= 1
        assert chunks[0]["metadata"]["heading_level"] == 0
        assert chunks[0]["metadata"]["heading_path"] == []

    def test_heading_level_h3(self, processor):
        """Heading 3 doğru level alır"""
        paragraphs = [
            self._make_mock_para("Ana Bölüm", "Heading 1"),
            self._make_mock_para("Alt Bölüm", "Heading 2"),
            self._make_mock_para("Alt Alt Bölüm", "Heading 3"),
            self._make_mock_para("Bu en derin alt bölümün içerik metnidir. En az yüz karakter uzunluğunda olması gerekmektedir, bu nedenle yeterli miktarda metin ekliyoruz."),
        ]
        doc = self._make_mock_doc(paragraphs)
        chunks = processor._chunks_from_document(doc)
        h3_chunks = [c for c in chunks if c["metadata"].get("heading") == "Alt Alt Bölüm"]
        assert len(h3_chunks) >= 1
        assert h3_chunks[0]["metadata"]["heading_level"] == 3
        path = h3_chunks[0]["metadata"]["heading_path"]
        assert len(path) == 3
        assert path[0] == "Ana Bölüm"
        assert path[1] == "Alt Bölüm"
        assert path[2] == "Alt Alt Bölüm"


class TestDOCXTableMetadata:
    """v2.43.0 Faz 5: DOCX tablo metadata testleri"""

    @pytest.fixture
    def processor(self):
        from app.services.document_processors.docx_processor import DOCXProcessor
        return DOCXProcessor()

    def _make_mock_table(self, headers, rows):
        """Mock table oluşturur"""
        table = MagicMock()
        all_rows = []

        # Header row
        header_row = MagicMock()
        header_cells = []
        for h in headers:
            cell = MagicMock()
            cell.text = h
            header_cells.append(cell)
        header_row.cells = header_cells
        all_rows.append(header_row)

        # Data rows
        for row_data in rows:
            row = MagicMock()
            cells = []
            for val in row_data:
                cell = MagicMock()
                cell.text = val
                cells.append(cell)
            row.cells = cells
            all_rows.append(row)

        table.rows = all_rows
        return table

    def _make_mock_doc(self, paragraphs=None, tables=None):
        doc = MagicMock()
        doc.paragraphs = paragraphs or []
        doc.tables = tables or []
        return doc

    def test_table_has_column_headers(self, processor):
        """Tablo chunk'larında column_headers bilgisi var"""
        table = self._make_mock_table(
            ["Ad", "Soyad", "Departman"],
            [["Ali", "Yılmaz", "IT"]]
        )
        doc = self._make_mock_doc(tables=[table])
        chunks = processor._chunks_from_document(doc)
        table_chunks = [c for c in chunks if c["metadata"].get("type") == "table_row"]
        assert len(table_chunks) >= 1
        assert "column_headers" in table_chunks[0]["metadata"]
        assert table_chunks[0]["metadata"]["column_headers"] == ["Ad", "Soyad", "Departman"]

    def test_table_has_row_count(self, processor):
        """Tablo chunk'larında row_count bilgisi var"""
        table = self._make_mock_table(
            ["Alan", "Değer"],
            [["Test1", "Val1"], ["Test2", "Val2"]]
        )
        doc = self._make_mock_doc(tables=[table])
        chunks = processor._chunks_from_document(doc)
        table_chunks = [c for c in chunks if c["metadata"].get("type") == "table_row"]
        assert len(table_chunks) >= 1
        assert table_chunks[0]["metadata"]["row_count"] == 2

    def test_table_has_table_id(self, processor):
        """Tablo chunk'larında table_id bilgisi var"""
        table = self._make_mock_table(
            ["Alan", "Değer"],
            [["Test", "Val"]]
        )
        doc = self._make_mock_doc(tables=[table])
        chunks = processor._chunks_from_document(doc)
        table_chunks = [c for c in chunks if c["metadata"].get("type") == "table_row"]
        assert len(table_chunks) >= 1
        assert table_chunks[0]["metadata"]["table_id"] == 1
        # Geriye uyumluluk
        assert table_chunks[0]["metadata"]["table"] == 1

    def test_table_inherits_last_heading(self, processor):
        """Tablolar son heading context'ini alır"""
        def _make_para(text, style_name=None):
            para = MagicMock()
            para.text = text
            para.style = MagicMock()
            para.style.name = style_name or "Normal"
            return para

        paragraphs = [
            _make_para("Personel Listesi", "Heading 1"),
            _make_para("Aşağıda personel bilgileri yer almaktadır. Detaylı bilgiler tabloda sunulmuştur. Bu paragraf en az yüz karakter uzunluğunda olmalıdır."),
        ]
        table = self._make_mock_table(
            ["Ad", "Departman"],
            [["Ali", "IT"]]
        )
        doc = self._make_mock_doc(paragraphs=paragraphs, tables=[table])
        chunks = processor._chunks_from_document(doc)
        table_chunks = [c for c in chunks if c["metadata"].get("type") == "table_row"]
        assert len(table_chunks) >= 1
        assert table_chunks[0]["metadata"]["heading"] == "Personel Listesi"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
