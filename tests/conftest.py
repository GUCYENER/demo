"""
VYRA L1 Support API - Test Fixtures
====================================
Tüm testlerde paylaşılan fixture'lar.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from typing import Dict, Any


def run_async(coro):
    """Event loop izolasyonlu async runner.
    
    asyncio.run() mevcut event loop'u kapatarak sonraki testlerde
    RuntimeError oluşturur. Bu helper her çağrıda yeni loop oluşturur.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest.fixture
def mock_db_conn():
    """Mock PostgreSQL connection fixture."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    
    # Context manager desteği
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    
    return mock_conn, mock_cursor


@pytest.fixture
def mock_db_context(mock_db_conn):
    """get_db_conn için context manager mock."""
    mock_conn, mock_cursor = mock_db_conn
    
    with patch('app.core.db.get_db_conn') as mock_get_db:
        mock_get_db.return_value = mock_conn
        yield mock_conn, mock_cursor


# =============================================================================
# USER FIXTURES
# =============================================================================

@pytest.fixture
def sample_user() -> Dict[str, Any]:
    """Örnek kullanıcı verisi."""
    return {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "full_name": "Test User",
        "phone": "05551234567",
        "role": "user",
        "role_id": 2,
        "is_admin": False,
        "is_approved": True,
        "password": "$2b$12$hashedpassword"
    }


@pytest.fixture
def admin_user() -> Dict[str, Any]:
    """Örnek admin kullanıcı verisi."""
    return {
        "id": 99,
        "username": "admin",
        "email": "admin@example.com",
        "full_name": "Admin User",
        "phone": "05559999999",
        "role": "admin",
        "role_id": 1,
        "is_admin": True,
        "is_approved": True,
        "password": "$2b$12$hashedpassword"
    }


# =============================================================================
# DIALOG FIXTURES
# =============================================================================

@pytest.fixture
def sample_dialog() -> Dict[str, Any]:
    """Örnek dialog verisi."""
    return {
        "id": 1,
        "user_id": 1,
        "title": "VPN Bağlantı Sorunu",
        "status": "active",
        "source_type": "vyra_chat",
        "created_at": "2026-02-06T10:00:00",
        "updated_at": "2026-02-06T10:00:00"
    }


@pytest.fixture
def sample_message() -> Dict[str, Any]:
    """Örnek mesaj verisi."""
    return {
        "id": 1,
        "dialog_id": 1,
        "role": "user",
        "content": "VPN bağlantısı kuramıyorum",
        "created_at": "2026-02-06T10:00:00"
    }


# =============================================================================
# RAG FIXTURES
# =============================================================================

@pytest.fixture
def sample_rag_chunk() -> Dict[str, Any]:
    """Örnek RAG chunk verisi."""
    return {
        "id": 1,
        "file_id": 1,
        "chunk_index": 0,
        "chunk_text": "VPN bağlantısı için önce Cisco AnyConnect uygulamasını açın.",
        "embedding": [0.1] * 384,  # Örnek embedding
        "metadata": {"page": 1}
    }


@pytest.fixture
def sample_rag_results():
    """Örnek RAG arama sonuçları."""
    return [
        {
            "id": 1,
            "file_name": "vpn_guide.pdf",
            "chunk_text": "VPN bağlantısı için adımlar...",
            "score": 0.85,
            "file_id": 1
        },
        {
            "id": 2,
            "file_name": "network_faq.docx",
            "chunk_text": "Ağ sorunları için çözümler...",
            "score": 0.72,
            "file_id": 2
        }
    ]


# =============================================================================
# API TEST CLIENT
# =============================================================================

@pytest.fixture
def test_client():
    """FastAPI test client fixture."""
    from fastapi.testclient import TestClient

    with patch('app.api.main.init_db'):
        from app.api.main import create_app
        app = create_app()
        client = TestClient(app)
        yield client


@pytest.fixture
def auth_headers(sample_user) -> Dict[str, str]:
    """Authorization header fixture."""
    from app.api.routes.auth import create_access_token
    
    token = create_access_token(sample_user)
    return {"Authorization": f"Bearer {token}"}
