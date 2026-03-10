"""
VYRA L1 Support API - RAG Upload Integration Tests
=====================================================
RAG dosya yükleme integration testleri.

⚠️ Bu testler ÇALIŞAN bir veritabanı ve uygulama gerektirir.
Sadece `pytest -m integration` ile çalıştırılmalıdır.
"""

import os
import io
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# Test için geçici dosya içeriği
TEST_FILE_CONTENT = b"Bu bir RAG upload test dosyasidir. Organizasyon yetkilendirmesi testi."
TEST_FILENAME = "test_rag_upload_doc.txt"


@pytest.fixture
def app_client():
    """TestClient oluştur — sadece integration testlerde."""
    from app.api.main import app
    from app.core.config import settings
    return TestClient(app), settings


@pytest.fixture
def admin_token(app_client):
    """Admin kullanıcısı için token al."""
    client, settings = app_client
    login_data = {
        "username": "admin",
        "password": "admin1234"
    }
    response = client.post(f"{settings.api_prefix}/auth/login", json=login_data)
    assert response.status_code == 200
    return response.json()["access_token"]


def test_rag_upload_with_orgs(app_client, admin_token):
    """
    RAG Dosya Yükleme Testi - Org Parametresi ile
    Frontend'deki 'selectedOrgIds' mantığının backend karşılığını test eder.
    """
    client, settings = app_client
    
    file_obj = io.BytesIO(TEST_FILE_CONTENT)
    files = {"files": (TEST_FILENAME, file_obj, "text/plain")}
    
    org_ids_param = "1"
    
    response = client.post(
        f"{settings.api_prefix}/rag/upload-files?org_ids={org_ids_param}",
        files=files,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    if response.status_code != 200:
        print(f"Hata Detayı: {response.text}")
        
    assert response.status_code == 200
    data = response.json()
    assert data["uploaded_count"] == 1
    assert data["success"] is True


def test_rag_upload_without_orgs_fallback(app_client, admin_token):
    """
    RAG Dosya Yükleme Testi - Org Parametresi Olmadan
    Eski davranışın bozulmadığını (fallback) test eder.
    """
    client, settings = app_client
    
    file_obj = io.BytesIO(TEST_FILE_CONTENT)
    files = {"files": ("test_no_org.txt", file_obj, "text/plain")}
    
    response = client.post(
        f"{settings.api_prefix}/rag/upload-files",
        files=files,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["uploaded_count"] == 1


def test_rag_cleanup(app_client, admin_token):
    """Test sırasında yüklenen dosyaları temizle."""
    client, settings = app_client
    
    response = client.get(
        f"{settings.api_prefix}/rag/files",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"search": "test_"}
    )
    assert response.status_code == 200
    files = response.json().get("files", [])
    
    for file in files:
        if file["file_name"] in [TEST_FILENAME, "test_no_org.txt"]:
            del_resp = client.delete(
                f"{settings.api_prefix}/rag/files/{file['id']}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert del_resp.status_code == 200
            print(f"Silindi: {file['file_name']}")
