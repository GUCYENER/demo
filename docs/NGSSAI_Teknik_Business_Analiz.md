# NGSSAI AIOps Platform — Teknik & Business Analiz Dokümanı

**Versiyon:** 2.40.0  
**Tarih:** Mart 2026  
**Hazırlayan:** Platform Ekibi

---

## İÇİNDEKİLER

1. [Yönetici Özeti](#1-yönetici-özeti)
2. [Business Analizi](#2-business-analizi)
3. [Teknik Mimari](#3-teknik-mimari)
4. [Veri Modeli](#4-veri-modeli)
5. [API Katmanı](#5-api-katmanı)
6. [Güvenlik & Yetkilendirme](#6-güvenlik--yetkilendirme)
7. [AI / ML Bileşenleri](#7-ai--ml-bileşenleri)
8. [Mevcut Sınırlamalar & Riskler](#8-mevcut-sınırlamalar--riskler)
9. [Platform Entegrasyon Analizi](#9-platform-entegrasyon-analizi)
10. [Yol Haritası Önerileri](#10-yol-haritası-önerileri)

---

## 1. Yönetici Özeti

NGSSAI, kurumsal ortamlarda L1 teknik destek süreçlerini otomatize etmek amacıyla geliştirilmiş bir **yapay zeka destekli bilgi yönetim ve diyalog platformudur**. Platform; doküman tabanlı bir RAG (Retrieval-Augmented Generation) çekirdeği, çok katmanlı LLM yanıt mimarisi ve kurumsal LDAP/SSO desteğiyle kurumlara ölçeklenebilir, denetlenebilir bir yapay zeka asistanı sunmaktadır.

### Temel Değer Önerileri

| Değer | Açıklama |
|---|---|
| **Hız** | L1 taleplerine ortalama <2 saniyede yanıt üretme |
| **Doğruluk** | 4 katmanlı yanıt pipeline ile bağlama uygun çözüm |
| **Güvenlik** | LDAP + JWT + org-bazlı veri izolasyonu |
| **Öğrenen Sistem** | Geri bildirimlerle sürekli iyileşen CatBoost modeli |
| **Kurumsal Hazırlık** | Çok organizasyonlu mimari, rol tabanlı erişim kontrolü |

---

## 2. Business Analizi

### 2.1 Hedef Kullanıcı Kitlesi

| Segment | Kullanıcı Profili | Temel İhtiyaç |
|---|---|---|
| **L1 Destek Teknisyenleri** | İlk hat çözüm ekibi | Hızlı, doğru çözüm önerileri |
| **Son Kullanıcılar** | Problem bildiren çalışanlar | Self-servis sohbet arabirimi |
| **Sistem Yöneticileri** | Platform & içerik yönetimi | Doküman yükleme, kullanıcı yönetimi |
| **IT Yöneticisi / CIO** | Karar vericiler | Raporlama, verimlilik metrikleri |

### 2.2 İş Süreçleri & Platform Akışı

```
Kullanıcı Sorusu
      │
      ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Cache Hit? │─YES─▶  Anında Yanıt│     │  Feedback   │
└──────┬──────┘     └──────────────┘     │  Döngüsü    │
       │NO                               └──────▲──────┘
       ▼                                        │
┌─────────────┐                                 │
│ Learned Q&A │─HIT─▶ Semantik Eşleşme ─────────┘
└──────┬──────┘
       │MISS
       ▼
┌─────────────┐
│  CatBoost   │─HIGH─▶ Direkt RAG Sonucu
│  Ranking    │  CONF
└──────┬──────┘
       │LOW
       ▼
┌─────────────┐
│  Deep Think │──▶ RAG + LLM Sentez ──▶ Yanıt + Görsel
│ Orchestrator│
└─────────────┘
```

### 2.3 Temel İş Metrikleri

| Metrik | Hedef | Açıklama |
|---|---|---|
| L1 Çözüm Oranı | %70+ | Bot tarafından çözüme kavuşturulan talepler |
| Ortalama Yanıt Süresi | <2 saniye | Cache/Learned seviyelerinde <500ms |
| Doküman İşleme Kapasitesi | PDF/DOCX/XLSX/PPTX/TXT | Görsel ve tablo dahil |
| Eğitim Döngüsü | Otomatik | Kullanıcı feedbackine dayalı CatBoost re-training |
| Kullanıcı Onay Süreci | Yönetici onaylı | Güvenlik & yetki denetimi |

### 2.4 Rekabet Analizi & Farkılaşma

| Özellik | NGSSAI | Genel RAG Sistemleri | Kurumsal Chatbot'lar |
|---|---|---|---|
| 4 katmanlı cevap pipeline | ✅ | ❌ | ❌ |
| CatBoost hibrit sıralama | ✅ | ❌ | ❌ |
| OCR ile görsel bağlam | ✅ | Nadiren | ❌ |
| LDAP/AD entegrasyonu | ✅ | ❌ | ✅ |
| Org-bazlı içerik izolasyonu | ✅ | ❌ | Kısmi |
| Sürekli öğrenme döngüsü | ✅ | ❌ | Nadiren |
| On-premise kurulum | ✅ | Kısmi | ❌ |

---

## 3. Teknik Mimari

### 3.1 Genel Sistem Mimarisi

```
┌────────────────────────────────────────────────────────┐
│                    FRONTEND KATMANI                    │
│  login.html + home.html + partials + JS modules        │
│  Vanilla JS · CSS3 · esbuild bundle                    │
└───────────────────────┬────────────────────────────────┘
                        │ HTTP / WebSocket
┌───────────────────────▼────────────────────────────────┐
│                    API KATMANI                         │
│              FastAPI (Python 3.13)                     │
│         uvicorn · CORS · JWT Middleware                │
│                                                        │
│  /auth  /dialogs  /rag  /tickets  /users  /system      │
└───┬────────────┬──────────────┬────────────────────────┘
    │            │              │
┌───▼──┐   ┌────▼──────┐  ┌───▼────────────────────────┐
│Redis │   │PostgreSQL │  │     AI/ML Servisleri        │
│Cache │   │  Vector   │  │  sentence-transformers      │
│Store │   │  Store    │  │  CatBoost · Google Gemini   │
└──────┘   └───────────┘  │  EasyOCR                   │
                          └────────────────────────────┘
```

### 3.2 Teknoloji Yığını

| Katman | Teknoloji | Versiyon / Not |
|---|---|---|
| **Backend Framework** | FastAPI | Python 3.13 |
| **ASGI Sunucu** | Uvicorn | Async HTTP + WebSocket |
| **Veritabanı** | PostgreSQL | FLOAT[] vektör depolama |
| **Cache** | Redis | In-memory fallback destekli |
| **Embedding Modeli** | sentence-transformers | paraphrase-multilingual-MiniLM-L12-v2 |
| **LLM** | Google Gemini 2.0 Flash | Streaming (SSE) destekli |
| **ML Ranking** | CatBoost | Hibrit semantik + keyword sıralama |
| **OCR** | EasyOCR | PDF/DOCX içi görsel metin çıkarma |
| **Frontend Build** | esbuild | JS + CSS bundle, 58 istek → 3 istek |
| **Auth** | JWT + BCrypt + LDAP | Dual-auth (Local + Active Directory) |
| **Şifreleme** | AES-256 Fernet | LDAP bind şifresi koruması |
| **Migrasyon** | Alembic | Otomatik schema yönetimi |

### 3.3 Frontend Modül Yapısı

```
frontend/
├── home.html               ← Ana uygulama sayfası (inline CSS + JS init)
├── login.html              ← Giriş sayfası (self-contained)
├── partials/               ← Dinamik yüklenen HTML bölümleri
│   ├── section_parameters.html   ← LLM, Prompt, ML, LDAP, Org İzinleri
│   ├── section_knowledge.html    ← RAG bilgi tabanı, dosya yönetimi
│   ├── section_auth.html         ← Kullanıcı & rol yönetimi
│   ├── section_org.html          ← Organizasyon yönetimi
│   ├── section_profile.html      ← Kullanıcı profili
│   └── modals.html               ← Global modal'lar
├── assets/js/
│   ├── authorization.js    ← Kullanıcı, rol, profil modülü
│   ├── org_module.js       ← Organizasyon CRUD
│   ├── rag_upload.js       ← Dosya yükleme ve bilgi tabanı
│   ├── home_page.js        ← Sayfa geçişleri, sidebar
│   └── modules/            ← LLM, Prompt, RAG FileList, ML Training
└── dist/                   ← bundle.min.js + bundle.min.css
```

### 3.4 Yanıt Pipeline Detayı

```
Gelen Mesaj
    │
    ├─► [T0] Cache Kontrolü (Redis)          → <100ms
    │        ─ Tam eşleşme: Direkt dön
    │
    ├─► [T1] Learned Q&A Semantic Search     → ~200ms
    │        ─ Threshold > 0.85: Dön
    │        ─ PostgreSQL pg_vector benzeri FLOAT[] + NumPy
    │
    ├─► [T2] CatBoost Hybrid Ranking         → ~300ms
    │        ─ Semantik + Keyword + Metadata feature'ları
    │        ─ Confidence > 0.75: RAG chunk direkt dön
    │
    └─► [T3] Deep Think + LLM Sentez         → ~1-3s
             ─ Intent tespiti (List/How-to/Troubleshoot)
             ─ RAG chunk'ları topla + görsel bağla
             ─ Gemini 2.0 Flash SSE streaming
             ─ Sonucu Learned Q&A'ya kaydet
```

---

## 4. Veri Modeli

### 4.1 Temel Tablolar

```sql
-- Kullanıcı & Yetki
users               (id, full_name, username, email, phone, password, avatar,
                     role_id, is_admin, is_approved, created_at)
roles               (id, name, description)
organization_groups (id, org_code, org_name, description, is_active)
user_organizations  (user_id, org_id)            ← M:N bağlantı

-- Diyalog & Chat
dialogs             (id, user_id, title, source_type, status, created_at)
dialog_messages     (id, dialog_id, role, content, content_type, metadata JSONB)

-- RAG Bilgi Tabanı
uploaded_files      (id, file_name, file_type, file_size_bytes, file_content BYTEA,
                     chunk_count, maturity_score, status, uploaded_by)
rag_chunks          (id, file_id, chunk_index, chunk_text, embedding FLOAT[],
                     metadata JSONB, quality_score, topic_label)
document_images     (id, file_id, image_data BYTEA, ocr_text, context_heading)
document_organizations (file_id, org_id)         ← İçerik izolasyonu

-- ML & Öğrenme
user_feedback       (id, user_id, dialog_id, chunk_id, feedback_type)
ml_models           (id, model_version, model_path, is_active, metrics JSONB)
ml_training_jobs    (id, status, started_at, completed_at, samples_count)
learned_answers     (id, question_text, answer_text, embedding FLOAT[], hit_count)

-- Sistem
system_settings     (setting_key, setting_value)
system_logs         (level, message, module, request_path, response_status)
```

### 4.2 Veri Akışı: Doküman Yüklemeden Yanıta

```
Doküman (PDF/DOCX/...) → Metin + Görsel Çıkarma (EasyOCR)
       │
       ▼
Chunk'lara Bölme (semantik başlık tespiti)
       │
       ▼
Embedding Üretimi (sentence-transformers) → FLOAT[] PostgreSQL
       │
       ▼
Maturity Analizi (kural & skor) → uploaded_files.maturity_score
       │
       ▼
Org Ataması → document_organizations
       │
       ▼
[SORGU GELDİĞİNDE]
       │
       ▼
Query Embedding → NumPy Cosine Similarity → Top-K Chunks
       │
       ▼
CatBoost Reranking → Deep Think → Gemini Flash → Yanıt
```

---

## 5. API Katmanı

### 5.1 Endpoint Envanteri

| Grup | Method | Path | İşlev |
|---|---|---|---|
| **Auth** | POST | `/api/auth/login` | JWT token üretimi |
| | POST | `/api/auth/register` | Kullanıcı kaydı |
| | POST | `/api/auth/refresh` | Token yenileme |
| | GET | `/api/auth/me` | Mevcut kullanıcı bilgisi |
| | GET | `/api/auth/ldap-domains` | LDAP domain listesi |
| **Diyalog** | GET | `/api/dialogs` | Dialog listesi |
| | POST | `/api/dialogs` | Yeni dialog başlat |
| | GET | `/api/dialogs/active` | Aktif dialog |
| | POST | `/api/dialogs/{id}/close` | Dialog kapat |
| | GET | `/api/dialogs/{id}/messages` | Mesaj geçmişi |
| | POST | `/api/dialogs/{id}/messages` | Senkron yanıt |
| | POST | `/api/dialogs/{id}/messages/stream` | SSE streaming yanıt |
| | POST | `/api/dialogs/{id}/feedback` | Geri bildirim gönder |
| **RAG** | POST | `/api/rag/upload-files` | Doküman yükle & işle |
| | GET | `/api/rag/files` | Yüklü dosya listesi |
| | DELETE | `/api/rag/files/{id}` | Dosya sil |
| | POST | `/api/rag/search` | Direkt RAG arama |
| | POST | `/api/rag/rebuild` | Vektör index yeniden oluştur |
| | POST | `/api/rag/analyze-maturity` | Doküman olgunluk analizi |
| | GET | `/api/rag/images/{id}` | Doküman görseli getir |
| **Tickets** | POST | `/api/tickets/search` | Çözüm arama |
| | POST | `/api/tickets/from-chat-async` | Async ticket oluştur |
| | GET | `/api/tickets/history` | Ticket geçmişi |
| | POST | `/api/tickets/{id}/ai-evaluate` | AI değerlendirme ekle |
| **Kullanıcı** | GET | `/api/users/list` | Kullanıcı listesi (admin) |
| | PUT | `/api/users/{id}/approve` | Kullanıcı onayla |
| | PUT | `/api/users/{id}/toggle-active` | Aktif/Pasif geçiş |
| | GET | `/api/users/roles` | Rol listesi |
| | GET | `/api/users/me` | Kendi profili |
| | PUT | `/api/users/me` | Profil güncelle |
| **Organizasyon** | GET | `/api/organizations` | Org listesi |
| | POST | `/api/organizations` | Yeni org oluştur |
| | PUT | `/api/organizations/{id}` | Org güncelle |
| | DELETE | `/api/organizations/{id}` | Org sil |
| **Sistem** | GET | `/api/health/health` | Sistem sağlık kontrolü |
| | GET | `/api/system/info` | Sistem istatistikleri |
| | GET/PUT | `/api/system/maturity-threshold` | Olgunluk eşiği yönetimi |
| | POST | `/api/system/ml/training/start` | ML eğitimi başlat |
| **WebSocket** | WS | `/api/ws` | Gerçek zamanlı bildirimler |

### 5.2 Mevcut API Olgunluğu

| Kriter | Durum |
|---|---|
| REST Uyumluluğu | ✅ Yüksek |
| JWT Kimlik Doğrulama | ✅ Tüm endpoint'lerde |
| Streaming (SSE) | ✅ Mesaj endpoint'inde |
| WebSocket | ✅ Bildirim & task takibi |
| Hata Kodları | ✅ FastAPI standart |
| API Versiyonlama | ⚠️ Eksik (`/v1/` prefix yok) |
| OpenAPI Dokümantasyon | ✅ `/docs` otomatik |
| Rate Limiting | ❌ Henüz yok |
| API Key Desteği | ❌ Sadece JWT |

---

## 6. Güvenlik & Yetkilendirme

### 6.1 Kimlik Doğrulama Akışı

```
Kullanıcı Girişi
      │
      ├── Local? → BCrypt şifre doğrulama → JWT Access + Refresh Token
      │
      └── LDAP?  → 3 adımlı bağlama süreci:
                   1. Servis Hesabı Bind
                   2. Kullanıcı DN Arama
                   3. Kullanıcı Bind Doğrulama
                   → JWT üretimi + otomatik kullanıcı oluşturma
```

### 6.2 Yetki Katmanları

| Seviye | Mekanizma | Kapsam |
|---|---|---|
| **Kimlik** | JWT Bearer Token | Tüm API endpoint'leri |
| **Rol** | RBAC (admin / user) | Yönetim işlemleri |
| **Organizasyon** | Org filtresi | Doküman ve içerik erişimi |
| **Onay** | Admin onayı zorunlu | Yeni kullanıcı aktivasyonu |
| **Şifre** | AES-256 Fernet | LDAP bind şifresi şifrelemesi |

---

## 7. AI / ML Bileşenleri

### 7.1 Embedding & Arama

- **Model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- **Dil Desteği:** Türkçe dahil çok dilli
- **Depolama:** PostgreSQL `FLOAT[]` kolonu
- **Benzerlik:** NumPy cosine similarity (in-memory hesaplama)
- **Not:** pgvector gibi native uzantı kullanılmıyor; büyük veri setlerinde performans kaybı olabilir

### 7.2 CatBoost Hibrit Sıralama

- **Feature'lar:** Semantik skor, keyword overlap, metadata sinyalleri, pozisyon bilgisi
- **Eğitim:** `ml_training.py` — kullanıcı geri bildirimleri + sentetik veri
- **Otomatik Yeniden Eğitim:** Scheduler ile periyodik tetikleme
- **Fallback:** CatBoost yoksa saf cosine similarity ile çalışır

### 7.3 LLM Konfigürasyonu

- **Varsayılan:** Google Gemini 2.0 Flash
- **Streaming:** SSE (Server-Sent Events)
- **Çoklu LLM:** Platform birden fazla LLM config kaydını destekliyor (llm-config tablosu)
- **Sıcaklık / Top-P:** Kullanıcı arayüzünden ayarlanabilir

### 7.4 OCR & Görsel İşleme

- **Motor:** EasyOCR
- **Desteklenen Format:** PDF ve DOCX içi gömülü görseller
- **Chunk Bağlama:** Görsel, ait olduğu metin chunk'ı ile ilişkilendiriliyor
- **Yanıt Entegrasyonu:** LLM yanıtında ilgili görsel inline gösteriliyor

### 7.5 Olgunluk Analizi

- **Amaç:** Yüklenen dokümanın bilgi tabanına katkı kalitesini ölçmek
- **Çıktı:** 0-100 arası maturity score
- **Eşik:** Kullanıcı arayüzünden ayarlanabilir (varsayılan 80)
- **Eylem:** Eşiğin altındaki dokümanlar için "İyileştir" butonu

---

## 8. Mevcut Sınırlamalar & Riskler

| Alan | Sınırlama | Risk Seviyesi | Çözüm Önerisi |
|---|---|---|---|
| **Vektör Arama** | pgvector yok, NumPy ile hesaplanıyor | Orta | pgvector uzantısı veya Qdrant/Chroma entegrasyonu |
| **LLM Bağımlılığı** | Sadece Google Gemini | Yüksek | Çoklu LLM sağlayıcı desteği (OpenAI, Azure, Ollama) |
| **Offline Model** | HuggingFace'e erişim gerekiyor | Yüksek | Model dosyasını `models/` dizinine önceden indirme |
| **Redis Opsiyonel** | In-memory fallback var ama cache kalıcı değil | Düşük | Redis zorunlu hale getirme |
| **API Versiyonlama** | `/v1/` prefix yok | Düşük | Versiyonlu API yapısına geçiş |
| **Rate Limiting** | Yok | Orta | FastAPI middleware ile eklenebilir |
| **Dosya Boyutu** | BYTEA ile DB'de depolama | Orta | Object storage (MinIO, S3) |
| **Ölçeklenebilirlik** | Single-instance | Yüksek | Kubernetes + stateless dönüşüm |
| **Test Kapsamı** | Eksik | Orta | Unit + Integration testler |

---

## 9. Platform Entegrasyon Analizi

Bu bölüm, talep edilen 3 yeni kanal entegrasyonunun mevcut platform üzerindeki geliştirme gereksinimlerini, teknik uyumluluğunu ve iş etkisini analiz etmektedir.

---

### 9.1 Web Entegrasyonu — Chat Add-on (JavaScript Widget)

#### 9.1.1 Tanım

Herhangi bir kurumsal web sitesine tek bir `<script>` etiketi eklenerek chatbot'un açılır pencere (floating widget) biçiminde devreye alınması.

```html
<!-- Hedef: Bu kadar basit entegrasyon -->
<script src="https://ngssai.domain.com/widget.js"
        data-org="ORG-IT"
        data-token="PUBLIC_API_KEY">
</script>
```

#### 9.1.2 Mevcut Platform Uyumluluğu

| Bileşen | Durum | Not |
|---|---|---|
| `/api/dialogs/{id}/messages/stream` SSE | ✅ Hazır | Widget doğrudan kullanabilir |
| CORS Politikası | ⚠️ Kısıtlı | Şu an Replit domain'ine kilitli |
| JWT Auth | ⚠️ Uyarlanmalı | Widget için API Key / anon-token akışı gerekli |
| Org bazlı içerik filtresi | ✅ Hazır | `data-org` parametresi mevcut yapıya oturur |
| WebSocket | ✅ Hazır | Real-time bildirimlerde kullanılabilir |

#### 9.1.3 Geliştirme Gereksinimleri

**Backend:**
- `POST /api/auth/widget-token` — public API key'den kısa ömürlü JWT üretimi
- CORS ayarlarında `allowed_origins` listesini genişletme
- Widget API Key yönetim tablosu: `widget_api_keys (id, org_id, key_hash, allowed_domains, is_active)`
- İsteğe bağlı: IP/domain beyaz liste denetimi

**Frontend (Yeni Widget Paketi):**
- Bağımsız `ngssai-widget.js` (~30KB hedef) — shadow DOM ile host site CSS'inden izole
- Floating button + chat panel bileşeni
- Mesaj balonu, yazıyor göstergesi, dosya gönderim UI
- Session yönetimi (localStorage ile oturum sürekliliği)
- Tema özelleştirme: renk, logo, placeholder metin parametreleri

**Güvenlik:**
- Widget API Key → Domain kısıtlaması (Referer header denetimi)
- Rate limiting (IP bazlı, dk başına mesaj limiti)
- XSS koruması (shadow DOM izolasyonu)

#### 9.1.4 Tahmini İş Yükü

| Görev | Süre (Adam/Gün) |
|---|---|
| Widget JS bileşeni tasarımı ve geliştirmesi | 10 |
| Backend API Key auth akışı | 4 |
| CORS + güvenlik konfigürasyonu | 2 |
| Dokümantasyon + entegrasyon kılavuzu | 2 |
| Test & QA | 3 |
| **Toplam** | **~21 Adam/Gün** |

#### 9.1.5 İş Etkisi

- **Kapsam genişlemesi:** Mevcut uygulama sınırları dışında her web kanalına ulaşım
- **Self-servis aktivasyon:** Teknik olmayan ekipler kodu kopyala-yapıştır ile chatbot ekleyebilir
- **Analitik fırsatı:** Hangi sayfadan ne sorulduğu → içerik boşluğu tespiti

---

### 9.2 Mobil Uygulama Desteği — SDK

#### 9.2.1 Tanım

NGSSAI'nin diyalog ve RAG yeteneklerini mobil uygulamalara (iOS / Android / React Native / Flutter) gömebilecek bir SDK / kütüphane paketi.

#### 9.2.2 Mevcut Platform Uyumluluğu

| Bileşen | Durum | Not |
|---|---|---|
| REST API katmanı | ✅ Hazır | SDK'nın tüm ihtiyaçları karşılanıyor |
| SSE Streaming | ✅ Hazır | Mobil HTTP istemcileri SSE destekliyor |
| JWT Auth | ✅ Hazır | SDK refresh token akışını yönetebilir |
| WebSocket | ✅ Hazır | Push bildirim altyapısı mevcut |
| Binary veri (görsel) | ✅ Hazır | `/api/rag/images/{id}` endpoint'i var |

#### 9.2.3 SDK Mimarisi (Önerilen)

```
ngssai-sdk/
├── core/
│   ├── NGSSAIClient.ts        ← Ana istemci sınıfı
│   ├── AuthManager.ts         ← JWT + refresh token yönetimi
│   ├── DialogManager.ts       ← Dialog CRUD + mesaj gönderimi
│   └── StreamHandler.ts       ← SSE / WebSocket bağlantı yönetimi
├── ui/  (opsiyonel UI bileşenleri)
│   ├── ChatView               ← Hazır kullanımlık chat arayüzü
│   └── MessageBubble          ← Özelleştirilebilir mesaj balonu
└── platform/
    ├── ReactNativeAdapter.ts  ← RN fetch + AsyncStorage
    ├── FlutterAdapter.dart    ← Flutter http + SharedPreferences
    └── iOSAdapter.swift       ← URLSession + Keychain
```

#### 9.2.4 Geliştirme Gereksinimleri

**Backend:**
- Mevcut API'da büyük değişiklik gerekmez
- Mobil için `POST /api/auth/mobile-token` (biometric auth payload desteği) — isteğe bağlı
- Push bildirim desteği: FCM (Firebase) ve APNs entegrasyonu için `POST /api/notifications/register-device`
- Cihaz token yönetim tablosu: `device_tokens (user_id, device_token, platform, created_at)`

**SDK:**
- TypeScript core (React Native uyumlu)
- Dart paketi (Flutter uyumlu)
- Swift/Objective-C wrapper (native iOS)
- Kotlin wrapper (native Android)
- npm, pub.dev, CocoaPods, Maven üzerinden dağıtım

**Ek Özellikler:**
- Offline mesaj kuyruğu (bağlantı kesilince mesajları sakla, yeniden bağlandığında gönder)
- Dosya yükleme desteği (kamera, galeri)
- Bildirim altyapısı (yeni mesaj/yanıt bildirimleri)

#### 9.2.5 Tahmini İş Yükü

| Görev | Süre (Adam/Gün) |
|---|---|
| TypeScript core SDK | 12 |
| React Native UI bileşenleri | 8 |
| Flutter Dart paketi | 10 |
| Native iOS Swift wrapper | 8 |
| Native Android Kotlin wrapper | 8 |
| Backend mobil-spesifik eklemeler | 5 |
| Dokümantasyon + örnek app | 5 |
| Test & QA | 7 |
| **Toplam** | **~63 Adam/Gün** |

#### 9.2.6 İş Etkisi

- **Kullanım yeri genişlemesi:** Masaüstü bağımlılığından kurtulma, saha teknisyenlerine ulaşım
- **Entegrasyon kolaylığı:** Mevcut kurumsal mobil uygulamalara eklenti olarak entegre edilebilir
- **Retention:** Mobil push bildirimleri ile kullanıcı geri dönüşü

---

### 9.3 Sesli Asistan — Voice Agent

#### 9.3.1 Tanım

Telefon kanalı (PSTN/VoIP) veya web ses kanalı üzerinden gelen konuşmaları anlayan, NGSSAI bilgi tabanına danışarak sesli yanıt üretenbir modül.

#### 9.3.2 Teknik Bileşenler (Gerekli)

```
Telefon Araması
      │
      ▼
[1] Telefoni Katmanı       Twilio / Vonage / Genesys / Avaya
      │ SIP / WebRTC
      ▼
[2] STT - Konuşma → Metin  Azure Speech / Google STT / Whisper
      │ text
      ▼
[3] NGSSAI Dialog API      Mevcut /api/dialogs/{id}/messages
      │ yanıt metni
      ▼
[4] TTS - Metin → Ses      Azure TTS / Google TTS / ElevenLabs
      │ audio stream
      ▼
[5] Telefoni Katmanı       Arayana geri oynat
```

#### 9.3.3 Mevcut Platform Uyumluluğu

| Bileşen | Durum | Not |
|---|---|---|
| Diyalog API | ✅ Hazır | Ses Agent metin bazlı API'yi kullanır |
| SSE Streaming | ✅ Hazır | TTS için chunk bazlı streaming avantajlıdır |
| Çok turlu dialog yönetimi | ✅ Hazır | Konuşma bağlamı dialog_messages'da tutuluyor |
| STT/TTS | ❌ Yok | Harici servis entegrasyonu gerekli |
| Telefoni katmanı | ❌ Yok | Twilio/Vonage gibi servis gerekli |
| Ses optimizasyonu | ❌ Yok | Yanıtlar şu an uzun ve metin formatında |

#### 9.3.4 Geliştirme Gereksinimleri

**Backend Yeni Servisler:**
- `VoiceSessionManager` — çağrı başına dialog oluşturma/sonlandırma
- STT entegrasyonu (Azure Cognitive Services veya Whisper API)
- TTS entegrasyonu (Azure Neural TTS, Google TTS veya ElevenLabs)
- `POST /api/voice/inbound` — telefoni webhook alıcısı
- `POST /api/voice/stream-audio` — ses stream endpoint'i

**Prompt Mühendisliği (Kritik):**
- Yanıtlar ses için yeniden tasarlanmalı: kısa, madde işaretsiz, doğal konuşma dili
- "3 numaralı adımı tekrar eder misiniz?" gibi sesli navigasyon komutları
- Belirsiz sorularda netleştirici soru sorma akışı

**Telefoni Entegrasyonu:**
- Twilio Programmable Voice (önerilen: kurulum hızı)
- Vonage (PSTN kalitesi yüksek)
- Genesys / Avaya (mevcut kurumsal altyapı varsa)

**Yeni Veritabanı Nesneleri:**
```sql
voice_sessions (
    id, dialog_id, caller_number, call_sid,
    provider, duration_seconds, status, created_at
)
```

#### 9.3.5 Tahmini İş Yükü

| Görev | Süre (Adam/Gün) |
|---|---|
| STT/TTS servis entegrasyonu | 8 |
| Telefoni webhook (Twilio) | 6 |
| VoiceSessionManager servisi | 8 |
| Sesli yanıt prompt mühendisliği | 5 |
| Sesli komut parsing (tekrar / dur / yardım) | 5 |
| Backend endpoint'leri | 5 |
| Test & QA (gerçek çağrı testleri) | 7 |
| **Toplam** | **~44 Adam/Gün** |

#### 9.3.6 İş Etkisi

- **7/24 telefon desteği:** İnsan müdahalesi olmadan çağrı yanıtlama
- **Mevcut call center entegrasyonu:** IVR sonrası L1 chatbot olarak konumlanma
- **Erişilebilirlik:** Bilgisayar kullanamayan teknik personele ulaşım

---

## 10. Yol Haritası Önerileri

### Kısa Vade (0–3 Ay) — Temel İyileştirmeler

| Öncelik | İş | Etki |
|---|---|---|
| 🔴 Yüksek | Offline embedding model (models/ dizinine önceden indir) | RAG stabilitesi |
| 🔴 Yüksek | Web Widget (JS Add-on) — MVP | Kanal genişlemesi |
| 🟡 Orta | pgvector uzantısı veya Qdrant entegrasyonu | Arama performansı |
| 🟡 Orta | API versiyonlama (`/api/v1/`) | Geriye uyumluluk |
| 🟡 Orta | Rate limiting middleware | Güvenlik |

### Orta Vade (3–6 Ay) — Platform Genişlemesi

| Öncelik | İş | Etki |
|---|---|---|
| 🔴 Yüksek | SDK — React Native MVP | Mobil kanal |
| 🟡 Orta | Çoklu LLM sağlayıcı (OpenAI / Azure / Ollama) | LLM bağımlılığı azaltma |
| 🟡 Orta | Object storage (MinIO/S3 — BYTEA yerine) | Ölçeklenebilirlik |
| 🟢 Düşük | Flutter SDK | Kanal genişlemesi |

### Uzun Vade (6–12 Ay) — Olgunlaşma

| Öncelik | İş | Etki |
|---|---|---|
| 🔴 Yüksek | Voice Agent (Twilio + Azure STT/TTS) | Telefon kanalı |
| 🟡 Orta | Kubernetes deployment | Yüksek erişilebilirlik |
| 🟡 Orta | Analytics dashboard | Yönetici raporlama |
| 🟢 Düşük | Native iOS / Android SDK | Tam platform kapsamı |

---

## Ekler

### Ek A — Entegrasyon Karşılaştırma Tablosu

| Özellik | Web Widget | Mobil SDK | Voice Agent |
|---|---|---|---|
| Backend değişikliği | Az | Az-Orta | Yüksek |
| Yeni servis entegrasyonu | Hayır | Opsiyonel (FCM/APNs) | Evet (STT/TTS/Telefoni) |
| Mevcut API kullanımı | %95 | %95 | %70 |
| Tahmini iş yükü | ~21 A/G | ~63 A/G | ~44 A/G |
| Teknik risk | Düşük | Orta | Yüksek |
| İş etkisi | Yüksek | Yüksek | Çok Yüksek |
| Öneri sırası | 1. | 2. | 3. |

### Ek B — Mevcut API Endpoint Sayıları

| Grup | Endpoint Sayısı |
|---|---|
| Auth | 5 |
| Dialog/Chat | 8 |
| RAG/Knowledge | 7 |
| Tickets | 7 |
| Kullanıcı Yönetimi | 8 |
| Organizasyon | 5 |
| Sistem/Admin | 6 |
| WebSocket | 1 |
| **Toplam** | **47** |

---

*Bu doküman NGSSAI platform ekibi tarafından hazırlanmıştır. İçerik, kaynak kod analizi ve çalışma ortamı incelemesine dayanmaktadır.*
