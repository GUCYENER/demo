"""
VYRA L1 Support API - Güvenlik Testleri
========================================
Bu modül, uygulamadaki güvenlik açıklarını test eder:
1. Token olmadan API erişimi (401 kontrolü)
2. Admin endpoint'lerine normal kullanıcı erişimi (403 kontrolü)  
3. Ticket IDOR zafiyeti (başka kullanıcının ticket'ına erişim)
4. Token expire kontrolü
"""

import sys
import os
import time
from datetime import datetime, timedelta
from typing import Optional

# Proje root'unu path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from jose import jwt

# Test konfigürasyonu
API_BASE = "http://localhost:8002/api"
JWT_SECRET = "your-secret-key-change-in-production"  # config.py'den alınmalı
JWT_ALGORITHM = "HS256"

# Test sonuçları
test_results = []


def log_test(test_name: str, passed: bool, details: str = ""):
    """Test sonucunu loglar"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{status} | {test_name}")
    if details:
        print(f"         └─ {details}")
    test_results.append({"name": test_name, "passed": passed, "details": details})


def create_test_token(user_id: int, role: str = "user", expired: bool = False) -> str:
    """Test için JWT token oluşturur"""
    if expired:
        exp = datetime.utcnow() - timedelta(hours=1)  # Geçmişte
    else:
        exp = datetime.utcnow() + timedelta(hours=1)  # Gelecekte
    
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": exp,
        "type": "access"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_auth_header(token: str) -> dict:
    """Authorization header döndürür"""
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# TEST 1: Token olmadan API erişimi (401 beklenir)
# ==============================================================================
def test_unauthorized_access():
    """Token olmadan korumalı endpoint'lere erişim denemesi"""
    print("\n" + "="*60)
    print("TEST 1: Token Olmadan API Erişimi (401 Beklenir)")
    print("="*60)
    
    protected_endpoints = [
        ("GET", "/auth/me", "Kullanıcı bilgisi"),
        ("GET", "/llm-config/", "LLM listesi"),
        ("GET", "/prompts/", "Prompt listesi"),
        ("GET", "/rag/files", "RAG dosya listesi"),
        ("GET", "/tickets/history", "Ticket geçmişi"),
        ("GET", "/users/list", "Kullanıcı listesi"),
    ]
    
    for method, endpoint, description in protected_endpoints:
        try:
            if method == "GET":
                response = requests.get(f"{API_BASE}{endpoint}", timeout=5)
            elif method == "POST":
                response = requests.post(f"{API_BASE}{endpoint}", timeout=5)
            
            passed = response.status_code == 401
            log_test(
                f"Unauthorized: {description}",
                passed,
                f"Status: {response.status_code} (Beklenen: 401)"
            )
        except requests.exceptions.ConnectionError:
            log_test(f"Unauthorized: {description}", False, "Backend'e bağlanılamadı!")
        except Exception as e:
            log_test(f"Unauthorized: {description}", False, str(e))


# ==============================================================================
# TEST 2: Admin endpoint'lerine normal kullanıcı erişimi (403 beklenir)
# ==============================================================================
def test_admin_only_endpoints():
    """Normal kullanıcı token'ı ile admin endpoint'lerine erişim"""
    print("\n" + "="*60)
    print("TEST 2: Admin Endpoint'lerine Normal Kullanıcı Erişimi (403 Beklenir)")
    print("="*60)
    
    # Normal kullanıcı token'ı (role=user)
    user_token = create_test_token(user_id=999, role="user")
    headers = get_auth_header(user_token)
    
    admin_endpoints = [
        ("GET", "/llm-config/", "LLM listesi (admin only)"),
        ("GET", "/prompts/", "Prompt listesi (admin only)"),
        ("GET", "/users/list", "Kullanıcı listesi (admin only)"),
        ("POST", "/rag/rebuild", "RAG rebuild (admin only)"),
    ]
    
    for method, endpoint, description in admin_endpoints:
        try:
            if method == "GET":
                response = requests.get(f"{API_BASE}{endpoint}", headers=headers, timeout=5)
            elif method == "POST":
                response = requests.post(f"{API_BASE}{endpoint}", headers=headers, timeout=5)
            
            # 401 (token'daki user DB'de yok) veya 403 (yetki yok) kabul edilebilir
            passed = response.status_code in [401, 403]
            log_test(
                f"Admin Only: {description}",
                passed,
                f"Status: {response.status_code} (Beklenen: 401 veya 403)"
            )
        except requests.exceptions.ConnectionError:
            log_test(f"Admin Only: {description}", False, "Backend'e bağlanılamadı!")
        except Exception as e:
            log_test(f"Admin Only: {description}", False, str(e))


# ==============================================================================
# TEST 3: Ticket IDOR Zafiyeti (403 beklenir)
# ==============================================================================
def test_ticket_idor():
    """Kullanıcının başka birinin ticket'ına erişim denemesi"""
    print("\n" + "="*60)
    print("TEST 3: Ticket IDOR Zafiyeti (403 Beklenir)")
    print("="*60)
    
    # Kullanıcı ID=999 için token
    user_token = create_test_token(user_id=999, role="user")
    headers = get_auth_header(user_token)
    
    # Başka kullanıcının ticket'ına erişim denemesi
    test_ticket_ids = [1, 2, 3, 100]
    
    for ticket_id in test_ticket_ids:
        try:
            response = requests.get(
                f"{API_BASE}/tickets/{ticket_id}",
                headers=headers,
                timeout=5
            )
            
            # Olası durumlar:
            # 401: Token'daki user DB'de yok
            # 403: Yetki yok (IDOR koruması çalışıyor)
            # 404: Ticket bulunamadı (bu da kabul edilebilir)
            passed = response.status_code in [401, 403, 404]
            
            status_meaning = {
                401: "Kullanıcı doğrulanamadı",
                403: "IDOR koruması aktif",
                404: "Ticket bulunamadı",
                200: "⚠️ ERİŞİM VERİLDİ - AÇIK!"
            }
            
            log_test(
                f"IDOR: Ticket #{ticket_id} erişimi",
                passed,
                f"Status: {response.status_code} ({status_meaning.get(response.status_code, 'Bilinmiyor')})"
            )
        except requests.exceptions.ConnectionError:
            log_test(f"IDOR: Ticket #{ticket_id}", False, "Backend'e bağlanılamadı!")
        except Exception as e:
            log_test(f"IDOR: Ticket #{ticket_id}", False, str(e))


# ==============================================================================
# TEST 4: Süresi dolmuş token kontrolü (401 beklenir)
# ==============================================================================
def test_expired_token():
    """Süresi dolmuş token ile erişim denemesi"""
    print("\n" + "="*60)
    print("TEST 4: Süresi Dolmuş Token (401 Beklenir)")
    print("="*60)
    
    # Süresi dolmuş token
    expired_token = create_test_token(user_id=1, role="admin", expired=True)
    headers = get_auth_header(expired_token)
    
    try:
        response = requests.get(f"{API_BASE}/auth/me", headers=headers, timeout=5)
        passed = response.status_code == 401
        log_test(
            "Expired Token: /auth/me erişimi",
            passed,
            f"Status: {response.status_code} (Beklenen: 401)"
        )
    except requests.exceptions.ConnectionError:
        log_test("Expired Token", False, "Backend'e bağlanılamadı!")
    except Exception as e:
        log_test("Expired Token", False, str(e))


# ==============================================================================
# TEST 5: Geçersiz token formatı (401 beklenir)
# ==============================================================================
def test_invalid_token_format():
    """Geçersiz formatta token ile erişim"""
    print("\n" + "="*60)
    print("TEST 5: Geçersiz Token Formatı (401 Beklenir)")
    print("="*60)
    
    invalid_tokens = [
        ("Boş string", ""),
        ("Rastgele string", "invalid-token-123"),
        ("Sadece Bearer", "Bearer"),
        ("Kötü formatlanmış JWT", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid"),
    ]
    
    for description, token in invalid_tokens:
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = requests.get(f"{API_BASE}/auth/me", headers=headers, timeout=5)
            passed = response.status_code == 401
            log_test(
                f"Invalid Token: {description}",
                passed,
                f"Status: {response.status_code} (Beklenen: 401)"
            )
        except Exception as e:
            log_test(f"Invalid Token: {description}", False, str(e))


# ==============================================================================
# TEST 6: SQL Injection denemesi
# ==============================================================================
def test_sql_injection():
    """SQL injection girişimlerini test eder"""
    print("\n" + "="*60)
    print("TEST 6: SQL Injection Koruması")
    print("="*60)
    
    # Login endpoint'inde SQL injection denemesi
    sql_payloads = [
        {"username": "admin' OR '1'='1", "password": "test"},
        {"username": "admin'--", "password": "test"},
        {"username": "'; DROP TABLE users;--", "password": "test"},
        {"username": "admin", "password": "' OR '1'='1"},
    ]
    
    for payload in sql_payloads:
        try:
            response = requests.post(
                f"{API_BASE}/auth/login",
                json=payload,
                timeout=5
            )
            # SQL injection çalışmamalı - 401 veya 422 bekleniyor
            passed = response.status_code in [401, 422]
            log_test(
                f"SQL Injection: {payload['username'][:30]}...",
                passed,
                f"Status: {response.status_code} (Beklenen: 401 veya 422)"
            )
        except Exception as e:
            log_test(f"SQL Injection", False, str(e))


# ==============================================================================
# SONUÇ RAPORU
# ==============================================================================
def print_summary():
    """Test sonuçlarının özetini yazdırır"""
    print("\n" + "="*60)
    print("📊 TEST SONUÇLARI ÖZET")
    print("="*60)
    
    total = len(test_results)
    passed = sum(1 for r in test_results if r["passed"])
    failed = total - passed
    
    print(f"\n  Toplam Test  : {total}")
    print(f"  ✅ Başarılı  : {passed}")
    print(f"  ❌ Başarısız : {failed}")
    print(f"  Başarı Oranı : {(passed/total*100):.1f}%" if total > 0 else "N/A")
    
    if failed > 0:
        print("\n  ⚠️ BAŞARISIZ TESTLER:")
        for r in test_results:
            if not r["passed"]:
                print(f"     - {r['name']}: {r['details']}")
    
    print("\n" + "="*60)
    
    # Exit code
    return 0 if failed == 0 else 1


# ==============================================================================
# ANA PROGRAM
# ==============================================================================
if __name__ == "__main__":
    print("\n")
    print("╔" + "═"*58 + "╗")
    print("║     VYRA L1 Support API - GÜVENLİK TEST SÜİTİ          ║")
    print("╚" + "═"*58 + "╝")
    print(f"\n📅 Test Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 API Base URL: {API_BASE}")
    
    # Backend bağlantı kontrolü
    print("\n🔍 Backend bağlantısı kontrol ediliyor...")
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Backend aktif - Versiyon: {data.get('version', 'N/A')}")
        else:
            print(f"   ⚠️ Backend yanıt verdi ama status: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("   ❌ Backend'e bağlanılamadı! Lütfen önce backend'i başlatın.")
        print("      Komut: .\\start_simple.ps1")
        sys.exit(1)
    
    # Testleri çalıştır
    test_unauthorized_access()
    test_admin_only_endpoints()
    test_ticket_idor()
    test_expired_token()
    test_invalid_token_format()
    test_sql_injection()
    
    # Özet
    exit_code = print_summary()
    sys.exit(exit_code)
