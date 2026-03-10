"""
VYRA L1 Support API - Health Check Tests
==========================================
Health check endpoint'i ve bileşen kontrol testleri.
"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def health_client():
    """Health test için özel client - DB init atlanır."""
    with patch('app.api.main.init_db'):
        from fastapi.testclient import TestClient
        from app.api.main import create_app
        app = create_app()
        client = TestClient(app)
        yield client


# =============================================================================
# TEST: Health Endpoint
# =============================================================================

class TestHealthEndpoint:
    """Health check endpoint testleri."""

    def test_health_returns_200(self, health_client):
        """Health endpoint 200 dönmeli."""
        with patch('app.core.db.check_db_connection', return_value=True):
            with patch('app.core.db.get_pool_stats', return_value={"active": 1}):
                with patch('app.core.cache.cache_service') as mock_cache:
                    mock_cache.get_all_stats.return_value = {"memory": {}, "query": {}}
                    with patch('app.api.routes.health._get_db_version', return_value="2.40.0"):
                        response = health_client.get("/api/health")

        assert response.status_code == 200

    def test_health_response_structure(self, health_client):
        """Health response doğru yapıda olmalı."""
        with patch('app.core.db.check_db_connection', return_value=True):
            with patch('app.core.db.get_pool_stats', return_value={}):
                with patch('app.core.cache.cache_service') as mock_cache:
                    mock_cache.get_all_stats.return_value = {}
                    with patch('app.api.routes.health._get_db_version', return_value="2.40.0"):
                        response = health_client.get("/api/health")

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "components" in data

    def test_health_status_ok_when_all_healthy(self, health_client):
        """Tüm bileşenler sağlıklıysa status 'ok' olmalı."""
        with patch('app.core.db.check_db_connection', return_value=True):
            with patch('app.core.db.get_pool_stats', return_value={}):
                with patch('app.core.cache.cache_service') as mock_cache:
                    mock_cache.get_all_stats.return_value = {"memory": {}, "query": {}}
                    with patch('app.api.routes.health._get_db_version', return_value="2.40.0"):
                        response = health_client.get("/api/health")

        assert response.json()["status"] == "ok"

    def test_health_status_error_when_db_down(self, health_client):
        """DB bağlantısı yoksa status 'error' olmalı."""
        with patch('app.core.db.check_db_connection', return_value=False):
            with patch('app.core.db.get_pool_stats', return_value={}):
                with patch('app.core.cache.cache_service') as mock_cache:
                    mock_cache.get_all_stats.return_value = {}
                    with patch('app.api.routes.health._get_db_version', return_value="2.40.0"):
                        response = health_client.get("/api/health")

        data = response.json()
        assert data["status"] == "error"

    def test_health_includes_version(self, health_client):
        """Health response versiyon bilgisi içermeli."""
        with patch('app.core.db.check_db_connection', return_value=True):
            with patch('app.core.db.get_pool_stats', return_value={}):
                with patch('app.core.cache.cache_service') as mock_cache:
                    mock_cache.get_all_stats.return_value = {}
                    with patch('app.api.routes.health._get_db_version', return_value="2.40.0"):
                        response = health_client.get("/api/health")

        assert response.json()["version"] == "2.40.0"
