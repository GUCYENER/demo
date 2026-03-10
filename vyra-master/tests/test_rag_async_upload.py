"""
VYRA L1 Support API - RAG Async Upload Unit Tests
===================================================
v2.39.0: Asenkron RAG upload fonksiyonları için unit testleri.

Kapsam:
- _process_files_background: Edge case, hata yakalama, WS bildirim
- scheduling._calculate_recent_quality: SQL subquery fix
- upload_files endpoint: 202 Accepted response, status='processing'
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


# ═══════════════════════════════════════════════
# 1. FileUploadResponse Schema Testleri
# ═══════════════════════════════════════════════

class TestFileUploadResponseSchema:
    """FileUploadResponse ve FileListItem schema testleri."""

    def test_file_upload_info_schema(self):
        """FileUploadInfo schema doğru alanları içermeli."""
        from app.api.schemas.rag_schemas import FileUploadInfo
        info = FileUploadInfo(
            file_name="test.pdf",
            file_type=".pdf",
            file_size_bytes=1024
        )
        assert info.file_name == "test.pdf"
        assert info.file_type == ".pdf"
        assert info.file_size_bytes == 1024

    def test_file_upload_response_schema(self):
        """FileUploadResponse schema embeddings_created alanı olmalı."""
        from app.api.schemas.rag_schemas import FileUploadResponse, FileUploadInfo
        response = FileUploadResponse(
            message="Test mesajı",
            uploaded_count=1,
            files=[FileUploadInfo(file_name="a.txt", file_type=".txt", file_size_bytes=100)],
            embeddings_created=False
        )
        assert response.uploaded_count == 1
        assert response.embeddings_created is False

    def test_file_list_item_status_field(self):
        """FileListItem status alanını desteklemeli (v2.39.0)."""
        from app.api.schemas.rag_schemas import FileListItem
        item = FileListItem(
            id=1,
            file_name="doc.pdf",
            file_type=".pdf",
            file_size_bytes=2048,
            chunk_count=5,
            uploaded_at="2026-01-01T00:00:00",
            uploaded_by=1,
            status="processing"
        )
        assert item.status == "processing"

    def test_file_list_item_status_default(self):
        """FileListItem status varsayılan değeri 'completed' olmalı."""
        from app.api.schemas.rag_schemas import FileListItem
        item = FileListItem(
            id=2,
            file_name="doc2.pdf",
            file_type=".pdf",
            file_size_bytes=1024,
            chunk_count=3,
            uploaded_at="2026-01-01",
            uploaded_by=1
        )
        assert item.status == "completed"

    def test_file_list_item_status_failed(self):
        """FileListItem failed status kabul edilmeli."""
        from app.api.schemas.rag_schemas import FileListItem
        item = FileListItem(
            id=3,
            file_name="fail.txt",
            file_type=".txt",
            file_size_bytes=512,
            chunk_count=0,
            uploaded_at="2026-01-01",
            uploaded_by=2,
            status="failed"
        )
        assert item.status == "failed"


# ═══════════════════════════════════════════════
# 2. Background Processing Edge Case Testleri
# ═══════════════════════════════════════════════

class TestBackgroundProcessingEdgeCases:
    """_process_files_background edge case testleri."""

    def test_empty_files_list(self):
        """Boş dosya listesiyle background processing çağrılmalı."""
        from app.api.routes.rag_upload import _process_files_background

        loop = asyncio.new_event_loop()
        try:
            with patch('app.core.websocket_manager.ws_manager') as mock_ws:
                mock_ws.send_to_user = AsyncMock()
                loop.run_until_complete(
                    _process_files_background([], user_id=1, maturity_score_map=None)
                )
                # Boş listede bile WS bildirim gönderilmeli
                mock_ws.send_to_user.assert_called_once()
                call_args = mock_ws.send_to_user.call_args
                assert call_args[0][1]["type"] == "rag_upload_complete"
                assert call_args[0][1]["processed_count"] == 0
        finally:
            loop.close()

    def test_ws_notification_error_does_not_crash(self):
        """WebSocket bildirim hatası background task'ı çökertmemeli."""
        from app.api.routes.rag_upload import _process_files_background

        loop = asyncio.new_event_loop()
        try:
            with patch('app.core.websocket_manager.ws_manager') as mock_ws:
                mock_ws.send_to_user = AsyncMock(side_effect=Exception("WS Error"))
                with patch('app.api.routes.rag_upload.log_error') as mock_log:
                    # Exception fırlatmamalı
                    loop.run_until_complete(
                        _process_files_background([], user_id=999, maturity_score_map=None)
                    )
                    # Hata loglanmalı
                    mock_log.assert_called()
                    log_msg = mock_log.call_args[0][0]
                    assert "WebSocket bildirim gönderilemedi" in log_msg
        finally:
            loop.close()


# ═══════════════════════════════════════════════
# 3. Scheduling SQL Fix Testi
# ═══════════════════════════════════════════════

class TestSchedulingQualityCalculation:
    """_calculate_recent_quality SQL subquery fix testi."""

    def test_calculate_recent_quality_uses_subquery(self):
        """SQL sorgusu subquery ile ORDER BY + LIMIT kullanmalı (GROUP BY hatası olmadan)."""
        import inspect
        from app.services.ml_training.scheduling import MLSchedulingMixin

        scheduler = MLSchedulingMixin.__new__(MLSchedulingMixin)
        source = inspect.getsource(scheduler._calculate_recent_quality)

        # Subquery pattern: "FROM (" ve ") AS recent" bulunmalı
        assert "FROM (" in source or "FROM(" in source, \
            "SQL sorgusu subquery kullanmalı (FROM ( ... ) AS recent)"
        assert "AS recent" in source, \
            "Subquery 'AS recent' alias'ına sahip olmalı"
        # ORDER BY ve LIMIT subquery içinde olmalı
        assert "ORDER BY created_at DESC" in source
        assert "LIMIT" in source

    def test_calculate_recent_quality_no_direct_aggregate_order(self):
        """Aggregate + ORDER BY aynı seviyede kullanılmamalı (PostgreSQL hatası)."""
        import inspect
        from app.services.ml_training.scheduling import MLSchedulingMixin

        scheduler = MLSchedulingMixin.__new__(MLSchedulingMixin)
        source = inspect.getsource(scheduler._calculate_recent_quality)

        # "FROM user_feedback\n...ORDER BY" pattern'ı olmamalı (subquery dışında)
        lines = source.split('\n')
        from_line_idx = None
        subquery_depth = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if '(' in stripped:
                subquery_depth += stripped.count('(')
            if ')' in stripped:
                subquery_depth -= stripped.count(')')

            if 'FROM user_feedback' in stripped and subquery_depth > 0:
                from_line_idx = i

        # FROM user_feedback subquery içinde olmalı
        assert from_line_idx is not None, \
            "FROM user_feedback subquery içinde olmalı"

    @patch('app.services.ml_training.scheduling.get_db_context')
    def test_calculate_recent_quality_returns_float(self, mock_db_ctx):
        """_calculate_recent_quality float değer döndürmeli."""
        from app.services.ml_training.scheduling import MLSchedulingMixin

        # Mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"positive": 7, "total": 10}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        scheduler = MLSchedulingMixin.__new__(MLSchedulingMixin)
        result = scheduler._calculate_recent_quality(sample_size=100)

        assert result == 0.7

    @patch('app.services.ml_training.scheduling.get_db_context')
    def test_calculate_recent_quality_zero_total(self, mock_db_ctx):
        """Toplam 0 ise None döndürmeli."""
        from app.services.ml_training.scheduling import MLSchedulingMixin

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"positive": 0, "total": 0}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        scheduler = MLSchedulingMixin.__new__(MLSchedulingMixin)
        result = scheduler._calculate_recent_quality(sample_size=100)

        assert result is None

    @patch('app.services.ml_training.scheduling.get_db_context')
    def test_calculate_recent_quality_db_error_returns_none(self, mock_db_ctx):
        """Veritabanı hatası None döndürmeli, exception fırlatmamalı."""
        from app.services.ml_training.scheduling import MLSchedulingMixin

        mock_db_ctx.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB connection error")
        )

        scheduler = MLSchedulingMixin.__new__(MLSchedulingMixin)
        result = scheduler._calculate_recent_quality(sample_size=100)

        assert result is None


# ═══════════════════════════════════════════════
# 4. Maturity Score Edge Case
# ═══════════════════════════════════════════════

class TestMaturityScoreEdgeCases:
    """Maturity score parsing edge case testleri."""

    def test_maturity_scores_parsing_valid(self):
        """Geçerli maturity_scores string'i doğru parse edilmeli."""
        scores_str = "85.3,72.1,90.0"
        score_list = [float(s.strip()) for s in scores_str.split(',') if s.strip()]
        assert score_list == [85.3, 72.1, 90.0]

    def test_maturity_scores_parsing_empty(self):
        """Boş string boş liste döndürmeli."""
        scores_str = ""
        score_list = [float(s.strip()) for s in scores_str.split(',') if s.strip()]
        assert score_list == []

    def test_maturity_scores_parsing_extra_commas(self):
        """Fazla virgülle parse doğru çalışmalı."""
        scores_str = "85.3,,72.1,"
        score_list = [float(s.strip()) for s in scores_str.split(',') if s.strip()]
        assert score_list == [85.3, 72.1]

    def test_maturity_scores_parsing_invalid_raises(self):
        """Geçersiz değer float conversion hatası vermeli."""
        scores_str = "85.3,abc,72.1"
        with pytest.raises(ValueError):
            [float(s.strip()) for s in scores_str.split(',') if s.strip()]
