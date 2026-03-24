"""
VYRA L1 Support API - DS Learning API Endpoint Tests
======================================================
Data Sources Learning API endpoint'lerinin integration testleri.
Endpoint'ler: learning-history, learning-results, generate-qa, schedule
"""

import pytest
from unittest.mock import patch, MagicMock


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def ds_learning_client():
    """DS Learning API testi için özel client."""
    with patch('app.api.main.init_db'):
        from fastapi.testclient import TestClient
        from app.api.main import create_app
        app = create_app()
        client = TestClient(app)
        yield client


@pytest.fixture
def ds_auth_headers():
    """DS Learning testleri için auth header."""
    from app.api.routes.auth import create_access_token
    user = {
        "id": 1,
        "username": "testadmin",
        "role": "admin",
        "role_id": 1,
        "is_admin": True,
        "is_approved": True,
        "company_id": 1
    }
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_learning_results_data():
    """Mock learning results verisi."""
    return {
        "results": [
            {
                "id": 1,
                "content_type": "schema_description",
                "content_text": "users tablosu açıklaması",
                "question": "users tablosu nedir?",
                "table_name": "users",
                "metadata": {"question": "users tablosu nedir?", "table_name": "users"},
                "created_at": "2026-03-24T18:00:00"
            },
            {
                "id": 2,
                "content_type": "aggregate_query",
                "content_text": "SELECT COUNT(*) FROM users;",
                "question": "Kaç kullanıcı var?",
                "table_name": "users",
                "metadata": {"question": "Kaç kullanıcı var?", "table_name": "users"},
                "created_at": "2026-03-24T18:00:01"
            }
        ],
        "type_counts": {
            "schema_description": 113,
            "aggregate_query": 43,
            "sample_insight": 30,
            "relationship_map": 39
        },
        "total": 225
    }


@pytest.fixture
def mock_history_data():
    """Mock history verisi."""
    return [
        {
            "id": 1,
            "source_id": 2,
            "job_type": "qa_generation",
            "status": "completed",
            "result_summary": {"qa_pairs": 225},
            "error_message": None,
            "duration_ms": 19000,
            "started_at": "2026-03-24T18:49:00",
            "completed_at": "2026-03-24T18:49:19"
        }
    ]


# =============================================================================
# TEST: GET /learning-results
# =============================================================================

class TestLearningResultsEndpoint:
    """GET /{source_id}/learning-results endpoint testleri."""

    def test_returns_200_with_valid_source(self, ds_learning_client, ds_auth_headers, mock_learning_results_data):
        """Geçerli source_id ile 200 dönmeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_results',
                       return_value=mock_learning_results_data):
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-results?limit=5",
                    headers=ds_auth_headers
                )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "type_counts" in data
        assert "total" in data

    def test_returns_correct_total(self, ds_learning_client, ds_auth_headers, mock_learning_results_data):
        """total alanı doğru dönmeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_results',
                       return_value=mock_learning_results_data):
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-results",
                    headers=ds_auth_headers
                )

        assert response.json()["total"] == 225

    def test_content_type_filter_passed(self, ds_learning_client, ds_auth_headers, mock_learning_results_data):
        """content_type query param servise iletilmeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_results',
                       return_value=mock_learning_results_data) as mock_fn:
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-results?content_type=aggregate_query&limit=10",
                    headers=ds_auth_headers
                )

        mock_fn.assert_called_once_with(mock_conn, 2, "aggregate_query", 10)
        assert response.status_code == 200

    def test_default_limit_is_50(self, ds_learning_client, ds_auth_headers, mock_learning_results_data):
        """limit parametresi verilmezse 50 olmalı."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_results',
                       return_value=mock_learning_results_data) as mock_fn:
                ds_learning_client.get(
                    "/api/data-sources/2/learning-results",
                    headers=ds_auth_headers
                )

        mock_fn.assert_called_once_with(mock_conn, 2, None, 50)

    def test_unauthorized_returns_401(self, ds_learning_client):
        """Auth olmadan 401 dönmeli."""
        response = ds_learning_client.get("/api/data-sources/2/learning-results")
        assert response.status_code in [401, 403]

    def test_results_contain_question_field(self, ds_learning_client, ds_auth_headers, mock_learning_results_data):
        """Her sonuç question alanı içermeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_results',
                       return_value=mock_learning_results_data):
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-results",
                    headers=ds_auth_headers
                )

        results = response.json()["results"]
        for r in results:
            assert "question" in r
            assert "content_type" in r
            assert "content_text" in r


# =============================================================================
# TEST: GET /learning-history
# =============================================================================

class TestLearningHistoryEndpoint:
    """GET /{source_id}/learning-history endpoint testleri."""

    def test_returns_200(self, ds_learning_client, ds_auth_headers, mock_history_data):
        """200 dönmeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_history',
                       return_value=mock_history_data):
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-history",
                    headers=ds_auth_headers
                )

        assert response.status_code == 200
        assert "history" in response.json()

    def test_history_contains_job_fields(self, ds_learning_client, ds_auth_headers, mock_history_data):
        """Her iş kaydı gerekli alanları içermeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_history',
                       return_value=mock_history_data):
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-history",
                    headers=ds_auth_headers
                )

        job = response.json()["history"][0]
        required_fields = ["job_type", "status", "duration_ms", "started_at"]
        for field in required_fields:
            assert field in job, f"Alan eksik: {field}"

    def test_empty_history(self, ds_learning_client, ds_auth_headers):
        """Boş history liste dönmeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_learning_history',
                       return_value=[]):
                response = ds_learning_client.get(
                    "/api/data-sources/2/learning-history",
                    headers=ds_auth_headers
                )

        assert response.json()["history"] == []


# =============================================================================
# TEST: POST /generate-qa
# =============================================================================

class TestGenerateQaEndpoint:
    """POST /{source_id}/generate-qa endpoint testleri."""

    def test_returns_success_response(self, ds_learning_client, ds_auth_headers):
        """QA üretimi başarıyla başlatılmalı."""
        mock_source_row = MagicMock()
        mock_source_row.__getitem__ = lambda self, key: {"id": 2, "company_id": 1, "name": "Test DB"}[key]
        mock_source_row.keys = lambda: ["id", "company_id", "name"]

        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = mock_source_row
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.create_job', return_value=1):
                with patch('app.api.routes.data_sources_api.threading'):
                    response = ds_learning_client.post(
                        "/api/data-sources/2/generate-qa",
                        headers=ds_auth_headers
                    )

        assert response.status_code == 200

    def test_unauthorized_returns_401(self, ds_learning_client):
        """Auth olmadan 401 dönmeli."""
        response = ds_learning_client.post("/api/data-sources/2/generate-qa")
        assert response.status_code in [401, 403]


# =============================================================================
# TEST: GET /schedule
# =============================================================================

class TestScheduleEndpoint:
    """GET /{source_id}/schedule endpoint testleri."""

    def test_returns_200(self, ds_learning_client, ds_auth_headers):
        """Schedule bilgisi dönmeli."""
        mock_schedule = {
            "exists": True,
            "schedule_type": "daily",
            "interval_value": 24,
            "is_active": True,
            "last_run": None,
            "next_run": None
        }
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_schedule',
                       return_value=mock_schedule):
                response = ds_learning_client.get(
                    "/api/data-sources/2/schedule",
                    headers=ds_auth_headers
                )

        assert response.status_code == 200

    def test_schedule_not_found(self, ds_learning_client, ds_auth_headers):
        """Schedule yoksa exists=False dönmeli."""
        with patch('app.api.routes.data_sources_api.get_db_context') as mock_ctx:
            mock_conn = MagicMock()
            mock_ctx.return_value.__enter__ = lambda s: mock_conn
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch('app.services.ds_learning_service.get_schedule',
                       return_value={"exists": False}):
                response = ds_learning_client.get(
                    "/api/data-sources/2/schedule",
                    headers=ds_auth_headers
                )

        assert response.json()["exists"] is False


# =============================================================================
# TEST: OpenAPI Route Registration
# =============================================================================

class TestRouteRegistration:
    """API route'larının doğru kayıt edildiğini doğrular."""

    def test_learning_results_route_exists(self, ds_learning_client):
        """learning-results route OpenAPI'de kayıtlı olmalı."""
        response = ds_learning_client.get("/openapi.json")
        paths = response.json().get("paths", {})
        assert "/api/data-sources/{source_id}/learning-results" in paths, \
            "learning-results route OpenAPI'de bulunamadı!"

    def test_learning_history_route_exists(self, ds_learning_client):
        """learning-history route OpenAPI'de kayıtlı olmalı."""
        response = ds_learning_client.get("/openapi.json")
        paths = response.json().get("paths", {})
        assert "/api/data-sources/{source_id}/learning-history" in paths

    def test_generate_qa_route_exists(self, ds_learning_client):
        """generate-qa route OpenAPI'de kayıtlı olmalı."""
        response = ds_learning_client.get("/openapi.json")
        paths = response.json().get("paths", {})
        assert "/api/data-sources/{source_id}/generate-qa" in paths

    def test_schedule_route_exists(self, ds_learning_client):
        """schedule route OpenAPI'de kayıtlı olmalı."""
        response = ds_learning_client.get("/openapi.json")
        paths = response.json().get("paths", {})
        assert "/api/data-sources/{source_id}/schedule" in paths

    def test_learning_results_is_get(self, ds_learning_client):
        """learning-results GET methodu ile kayıtlı olmalı."""
        response = ds_learning_client.get("/openapi.json")
        paths = response.json().get("paths", {})
        route = paths.get("/api/data-sources/{source_id}/learning-results", {})
        assert "get" in route, "learning-results POST değil GET olmalı!"
