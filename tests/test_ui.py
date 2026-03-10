"""
VYRA L1 Support - UI/UX Test Senaryoları
=========================================
Bu modül, frontend UI/UX testlerini içerir:
1. Ticket History Accordion testleri
2. Sayfa erişim kontrolü testleri
3. UI bileşen kontrolleri

Manuel test için kullanılabilir veya Selenium ile otomatize edilebilir.
"""

import sys
import os
from datetime import datetime

# Proje root'unu path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

# Test konfigürasyonu
API_BASE = "http://localhost:8002/api"
FRONTEND_BASE = "http://localhost:5500"

# Test sonuçları
test_results = []


def log_test(test_name: str, passed: bool, details: str = ""):
    """Test sonucunu loglar"""
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{status} | {test_name}")
    if details:
        print(f"         └─ {details}")
    test_results.append({"name": test_name, "passed": passed, "details": details})


# ==============================================================================
# TEST SENARYOLARI - TİCKET HISTORY ACCORDION
# ==============================================================================

def test_ticket_history_api():
    """Ticket history API endpoint testleri"""
    print("\n" + "="*60)
    print("TEST: Ticket History API")
    print("="*60)
    
    # 1. Authenticated request için gerçek token gerekli
    # Bu test sadece API'nin çalışıp çalışmadığını kontrol eder
    
    try:
        # Token olmadan - 401 beklenir
        response = requests.get(f"{API_BASE}/tickets/history", timeout=5)
        passed = response.status_code == 401
        log_test(
            "Ticket History: Token olmadan erişim",
            passed,
            f"Status: {response.status_code} (Beklenen: 401)"
        )
    except Exception as e:
        log_test("Ticket History: Token olmadan erişim", False, str(e))
    
    try:
        # Endpoint yapısı kontrolü
        response = requests.get(f"{API_BASE}/tickets/history?page=1&page_size=10", timeout=5)
        # 401 beklenir (token yok) ama endpoint doğru çalışmalı
        endpoint_works = response.status_code in [401, 200]
        log_test(
            "Ticket History: Pagination parametreleri",
            endpoint_works,
            f"Status: {response.status_code}"
        )
    except Exception as e:
        log_test("Ticket History: Pagination parametreleri", False, str(e))


def test_frontend_pages():
    """Frontend sayfalarının erişilebilirlik testleri"""
    print("\n" + "="*60)
    print("TEST: Frontend Sayfa Erişimi")
    print("="*60)
    
    pages = [
        ("/login.html", "Login Sayfası"),
        ("/home.html", "Ana Sayfa"),
    ]
    
    for path, description in pages:
        try:
            response = requests.get(f"{FRONTEND_BASE}{path}", timeout=5)
            passed = response.status_code == 200
            log_test(
                f"Frontend: {description}",
                passed,
                f"Status: {response.status_code}"
            )
        except Exception as e:
            log_test(f"Frontend: {description}", False, str(e))


def test_static_assets():
    """Statik dosyaların yüklenme testleri"""
    print("\n" + "="*60)
    print("TEST: Statik Dosyalar")
    print("="*60)
    
    assets = [
        ("/assets/js/ticket_history.js", "Ticket History JS"),
        ("/assets/css/ticket-history.css", "Ticket History CSS"),
        ("/assets/js/home_page.js", "Home Page JS"),
        ("/assets/css/home.css", "Home CSS"),
    ]
    
    for path, description in assets:
        try:
            response = requests.get(f"{FRONTEND_BASE}{path}", timeout=5)
            passed = response.status_code == 200
            log_test(
                f"Asset: {description}",
                passed,
                f"Status: {response.status_code}"
            )
        except Exception as e:
            log_test(f"Asset: {description}", False, str(e))


# ==============================================================================
# MANUEL TEST SENARYOLARI (CHECKLIST)
# ==============================================================================

def print_manual_test_checklist():
    """Manuel test senaryolarını yazdırır"""
    print("\n" + "="*60)
    print("📋 MANUEL TEST SENARYOLARI (CHECKLIST)")
    print("="*60)
    
    checklist = """
┌─────────────────────────────────────────────────────────────────┐
│  TICKET HISTORY ACCORDION TESTLERİ                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  HAZIRLIK:                                                      │
│  [ ] Backend başlatıldı (.\start_simple.ps1)                    │
│  [ ] Frontend http://localhost:5500/login.html açık             │
│  [ ] Geçerli kullanıcı bilgileri ile giriş yapıldı             │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 1: ACCORDION GÖRÜNÜMLERİ                                  │
│  [ ] "Geçmiş Çözümler" sekmesine tıkla                          │
│  [ ] Accordion kartları başlangıçta KAPALI olmalı              │
│  [ ] Her kartta BAŞLIK ve TARİH görünmeli                       │
│  [ ] "Çözüldü" badge'i yeşil renkte görünmeli                   │
│  [ ] Chevron ikonu (ok) aşağı yönlü olmalı                      │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 2: ACCORDION AÇILMA/KAPANMA                               │
│  [ ] İlk accordion header'a tıkla                               │
│  [ ] Kart AÇILMALI (içerik görünmeli)                          │
│  [ ] Chevron ikonu 180° dönerek YUKARI yönelmeli               │
│  [ ] Border rengi SARI tonuna dönüşmeli                        │
│  [ ] Animasyon pürüzsüz olmalı (0.4s)                          │
│  [ ] Aynı header'a tekrar tıkla - KAPANMALI                    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 3: ACCORDION İÇERİĞİ                                      │
│  [ ] "Kullanıcı Talebi" bölümü görünmeli (sarı sol border)     │
│  [ ] "AI Çözüm Önerisi" bölümü görünmeli                       │
│  [ ] Çözüm adımları numaralı liste şeklinde olmalı             │
│  [ ] ÇYM notu varsa mor kutucukta görünmeli                    │
│  [ ] "Kopyala" butonu çalışmalı                                │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 4: YENİLE BUTONU                                          │
│  [ ] Sağ üstteki yenile butonuna tıkla                         │
│  [ ] Buton dönerek animasyonlı olmalı                          │
│  [ ] Liste yeniden yüklenmeli                                  │
│  [ ] Toast/bildirim çıkmamalı (sessiz yenileme)                │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 5: BOŞ DURUM                                              │
│  [ ] Hiç ticket yoksa boş durum mesajı görünmeli               │
│  [ ] "Henüz çözüm kaydı yok" metni görünmeli                   │
│  [ ] Büyük inbox ikonu görünmeli                               │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 6: RESPONSIVE TASARIM                                     │
│  [ ] Tarayıcıyı küçült (mobil görünüm)                         │
│  [ ] Accordion'lar düzgün görünmeli                            │
│  [ ] Metinler kesilmemeli veya taşmamalı                       │
│  [ ] Badge'ler düzgün konumlanmalı                             │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 7: GÜVENLİK (URL MANİPÜLASYONU)                           │
│  [ ] localStorage'dan access_token'ı sil                       │
│  [ ] http://localhost:5500/home.html adresine git              │
│  [ ] Otomatik olarak login.html'e yönlendirilmeli              │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TEST 8: TOKEN SÜRE KONTROLÜ                                    │
│  [ ] Console'da "[VYRA] Token süresi dolmuş" mesajı kontrol et │
│  [ ] Süresi dolmuş token ile login'e yönlendirme               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

📝 NOTLAR:
- Tüm testler tarayıcı DevTools açıkken yapılmalı
- Console'da hata mesajı olmamalı
- Network sekmesinde 4xx/5xx hata olmamalı

🎨 GÖRSEL STANDARTLAR:
- Accordion arka plan: Gradient (#1e2128 → #181b20)
- Hover border: Sarı (#ffc107) %20 opacity
- Açık durum border: Sarı (#ffc107) %40 opacity
- Badge rengi: Yeşil (#22c55e)
- Font: System UI (Inter benzeri)
"""
    
    print(checklist)


# ==============================================================================
# SONUÇ RAPORU
# ==============================================================================
def print_summary():
    """Test sonuçlarının özetini yazdırır"""
    print("\n" + "="*60)
    print("📊 OTOMATİK TEST SONUÇLARI ÖZET")
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
    
    return 0 if failed == 0 else 1


# ==============================================================================
# ANA PROGRAM
# ==============================================================================
if __name__ == "__main__":
    print("\n")
    print("╔" + "═"*58 + "╗")
    print("║   VYRA L1 Support - UI/UX TEST SÜİTİ                    ║")
    print("╚" + "═"*58 + "╝")
    print(f"\n📅 Test Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 API Base URL: {API_BASE}")
    print(f"🖥️ Frontend URL: {FRONTEND_BASE}")
    
    # Bağlantı kontrolü
    print("\n🔍 Bağlantı kontrol ediliyor...")
    
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Backend aktif - Versiyon: {data.get('version', 'N/A')}")
        else:
            print(f"   ⚠️ Backend yanıt verdi ama status: {response.status_code}")
    except:
        print("   ❌ Backend'e bağlanılamadı!")
    
    try:
        response = requests.get(f"{FRONTEND_BASE}/login.html", timeout=5)
        if response.status_code == 200:
            print("   ✅ Frontend aktif")
        else:
            print(f"   ⚠️ Frontend yanıt verdi ama status: {response.status_code}")
    except:
        print("   ❌ Frontend'e bağlanılamadı!")
    
    # Otomatik testler
    test_ticket_history_api()
    test_frontend_pages()
    test_static_assets()
    
    # Özet
    exit_code = print_summary()
    
    # Manuel test checklist
    print_manual_test_checklist()
    
    sys.exit(exit_code)
