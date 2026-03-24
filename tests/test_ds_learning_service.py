"""
VYRA L1 Support API - DS Learning Service Tests
=================================================
ds_learning_service modülünün unit testleri.
Fonksiyonlar: get_learning_results, get_learning_history, generate_synthetic_qa
"""

import pytest
import json
from unittest.mock import MagicMock
from datetime import datetime


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_learning_db():
    """DS Learning servis testleri için mock DB bağlantısı."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def sample_learning_results():
    """Örnek öğrenme sonuçları (DB row formatında)."""
    return [
        {
            "id": 1,
            "content_type": "schema_description",
            "content_text": "users tablosu: id (PK), username, email, created_at alanlarını içerir.",
            "metadata": {"question": "users tablosunda hangi alanlar var?", "table_name": "users"},
            "job_id": 1,
            "created_at": datetime(2026, 3, 24, 18, 0, 0)
        },
        {
            "id": 2,
            "content_type": "aggregate_query",
            "content_text": "users tablosundaki kayıt sayısı: SELECT COUNT(*) FROM users;",
            "metadata": {"question": "users tablosunda kaç kayıt var?", "table_name": "users"},
            "job_id": 1,
            "created_at": datetime(2026, 3, 24, 18, 0, 1)
        },
        {
            "id": 3,
            "content_type": "sample_insight",
            "content_text": "users tablosundan örnek: admin, testuser, devuser kullanıcıları mevcut.",
            "metadata": {"question": "users tablosunda hangi kullanıcılar var?", "table_name": "users"},
            "job_id": 1,
            "created_at": datetime(2026, 3, 24, 18, 0, 2)
        },
        {
            "id": 4,
            "content_type": "relationship_map",
            "content_text": "users.id → tickets.user_id (1:N ilişki)",
            "metadata": {"question": "users ile tickets arasında nasıl bir ilişki var?", "table_name": "users"},
            "job_id": 1,
            "created_at": datetime(2026, 3, 24, 18, 0, 3)
        }
    ]


@pytest.fixture
def sample_type_counts():
    """Tip bazlı sayım sonuçları."""
    return [
        {"content_type": "schema_description", "cnt": 113},
        {"content_type": "aggregate_query", "cnt": 43},
        {"content_type": "relationship_map", "cnt": 39},
        {"content_type": "sample_insight", "cnt": 30}
    ]


@pytest.fixture
def sample_history_rows():
    """Örnek iş geçmişi satırları."""
    return [
        {
            "id": 1,
            "source_id": 2,
            "job_type": "qa_generation",
            "status": "completed",
            "result_summary": json.dumps({"qa_pairs": 225, "types": {"schema_description": 113}}),
            "error_message": None,
            "duration_ms": 19000,
            "started_at": datetime(2026, 3, 24, 18, 49, 0),
            "completed_at": datetime(2026, 3, 24, 18, 49, 19)
        },
        {
            "id": 2,
            "source_id": 2,
            "job_type": "qa_generation",
            "status": "running",
            "result_summary": None,
            "error_message": None,
            "duration_ms": None,
            "started_at": datetime(2026, 3, 24, 18, 57, 0),
            "completed_at": None
        }
    ]


# =============================================================================
# TEST: get_learning_results
# =============================================================================

class TestGetLearningResults:
    """get_learning_results fonksiyonu testleri."""

    def test_returns_all_results_without_filter(self, mock_learning_db, sample_learning_results, sample_type_counts):
        """Filtre olmadan tüm sonuçlar dönmeli."""
        mock_conn, mock_cursor = mock_learning_db
        # İlk fetchall: sonuçlar, ikinci fetchall: tip sayıları
        mock_cursor.fetchall.side_effect = [sample_learning_results, sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=2)

        assert "results" in data
        assert "type_counts" in data
        assert "total" in data
        assert len(data["results"]) == 4
        assert data["total"] == 225  # 113 + 43 + 39 + 30

    def test_filters_by_content_type(self, mock_learning_db, sample_type_counts):
        """content_type filtresi çalışmalı."""
        mock_conn, mock_cursor = mock_learning_db
        filtered = [r for r in [
            {"id": 1, "content_type": "aggregate_query",
             "content_text": "SELECT COUNT(*) FROM users;",
             "metadata": {"question": "Kaç kayıt var?", "table_name": "users"},
             "job_id": 1,
             "created_at": datetime(2026, 3, 24, 18, 0)}
        ]]
        mock_cursor.fetchall.side_effect = [filtered, sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=2, content_type="aggregate_query")

        # SQL sorgusunda content_type parametresi olmalı
        call_args = mock_cursor.execute.call_args_list[0]
        sql = call_args[0][0]
        assert "content_type" in sql
        assert len(data["results"]) == 1
        assert data["results"][0]["content_type"] == "aggregate_query"

    def test_respects_limit_parameter(self, mock_learning_db, sample_type_counts):
        """limit parametresi SQL'e uygulanmalı."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.side_effect = [[], sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        get_learning_results(mock_conn, source_id=2, limit=10)

        call_args = mock_cursor.execute.call_args_list[0]
        params = call_args[0][1]
        assert 10 in params  # limit değeri SQL parametrelerinde olmalı

    def test_handles_string_metadata(self, mock_learning_db, sample_type_counts):
        """metadata string olarak gelirse JSON parse yapmalı."""
        mock_conn, mock_cursor = mock_learning_db
        row_with_str_meta = [{
            "id": 1,
            "content_type": "schema_description",
            "content_text": "test",
            "metadata": '{"question": "Test soru?", "table_name": "test_table"}',
            "job_id": 1,
            "created_at": datetime(2026, 3, 24, 18, 0)
        }]
        mock_cursor.fetchall.side_effect = [row_with_str_meta, sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=2)

        assert data["results"][0]["question"] == "Test soru?"
        assert data["results"][0]["table_name"] == "test_table"

    def test_handles_invalid_json_metadata(self, mock_learning_db, sample_type_counts):
        """Bozuk JSON metadata parse hatasında boş dict dönmeli."""
        mock_conn, mock_cursor = mock_learning_db
        row_with_bad_meta = [{
            "id": 1,
            "content_type": "schema_description",
            "content_text": "test",
            "metadata": "INVALID_JSON{{{",
            "job_id": None,
            "created_at": datetime(2026, 3, 24, 18, 0)
        }]
        mock_cursor.fetchall.side_effect = [row_with_bad_meta, sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=2)

        # Hata fırlatmamalı, boş dönmeli
        assert data["results"][0]["question"] == ""
        assert data["results"][0]["table_name"] == ""

    def test_handles_none_metadata(self, mock_learning_db, sample_type_counts):
        """metadata=None durumunda hata fırlatmamalı."""
        mock_conn, mock_cursor = mock_learning_db
        row_with_none_meta = [{
            "id": 1,
            "content_type": "schema_description",
            "content_text": "test",
            "metadata": None,
            "job_id": None,
            "created_at": None
        }]
        mock_cursor.fetchall.side_effect = [row_with_none_meta, sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=2)

        assert data["results"][0]["question"] == ""
        assert data["results"][0]["created_at"] is None

    def test_empty_results_returns_zero_total(self, mock_learning_db):
        """Sonuç yoksa total=0 dönmeli."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.side_effect = [[], []]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=999)

        assert data["results"] == []
        assert data["type_counts"] == {}
        assert data["total"] == 0

    def test_type_counts_aggregation(self, mock_learning_db, sample_learning_results, sample_type_counts):
        """type_counts doğru aggregate edilmeli."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.side_effect = [sample_learning_results, sample_type_counts]

        from app.services.ds_learning_service import get_learning_results
        data = get_learning_results(mock_conn, source_id=2)

        assert data["type_counts"]["schema_description"] == 113
        assert data["type_counts"]["aggregate_query"] == 43
        assert data["type_counts"]["relationship_map"] == 39
        assert data["type_counts"]["sample_insight"] == 30


# =============================================================================
# TEST: get_learning_history
# =============================================================================

class TestGetLearningHistory:
    """get_learning_history fonksiyonu testleri."""

    def test_returns_history_list(self, mock_learning_db, sample_history_rows):
        """İş geçmişi liste olarak dönmeli."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.return_value = sample_history_rows

        from app.services.ds_learning_service import get_learning_history
        history = get_learning_history(mock_conn, source_id=2)

        assert isinstance(history, list)
        assert len(history) == 2

    def test_completed_job_has_all_fields(self, mock_learning_db, sample_history_rows):
        """Tamamlanmış iş tüm alanları içermeli."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.return_value = [sample_history_rows[0]]

        from app.services.ds_learning_service import get_learning_history
        history = get_learning_history(mock_conn, source_id=2)

        job = history[0]
        assert job["job_type"] == "qa_generation"
        assert job["status"] == "completed"
        assert job["duration_ms"] == 19000
        assert "started_at" in job
        assert "completed_at" in job

    def test_running_job_has_null_completed(self, mock_learning_db, sample_history_rows):
        """Çalışan iş için completed_at None olmalı."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.return_value = [sample_history_rows[1]]

        from app.services.ds_learning_service import get_learning_history
        history = get_learning_history(mock_conn, source_id=2)

        job = history[0]
        assert job["status"] == "running"
        assert job["completed_at"] is None

    def test_empty_history(self, mock_learning_db):
        """İş geçmişi boşsa boş liste dönmeli."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.return_value = []

        from app.services.ds_learning_service import get_learning_history
        history = get_learning_history(mock_conn, source_id=999)

        assert history == []

    def test_result_summary_preserved(self, mock_learning_db, sample_history_rows):
        """result_summary JSON olarak dönmeli."""
        mock_conn, mock_cursor = mock_learning_db
        mock_cursor.fetchall.return_value = [sample_history_rows[0]]

        from app.services.ds_learning_service import get_learning_history
        history = get_learning_history(mock_conn, source_id=2)

        summary = history[0].get("result_summary")
        assert summary is not None
