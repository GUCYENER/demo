# 📚 VYRA L1 Support — Teknik Dokümantasyon

| Bilgi | Değer |
|-------|-------|
| **Platform Versiyonu** | v3.3.0 |
| **Son Güncelleme** | 2026-04-03 |
| **Durum** | ✅ Güncel |

---

## 📋 Doküman Dizini

### 👤 01 — Kullanıcı Kılavuzu
Son kullanıcılar ve yöneticiler için adım adım kullanım talimatları.

| Doküman | Açıklama | Durum |
|---------|----------|-------|
| [Giriş ve Kurulum](01_user_manual/giris_ve_kurulum.md) | Login, kayıt, ilk kullanım | ✅ |
| [Soru Sorma ve Dialog](01_user_manual/soru_sorma_ve_dialog.md) | Ask Vyra chatbot, dialog yönetimi | ✅ |
| [RAG Bilgi Bankası](01_user_manual/rag_bilgi_bankasi.md) | Dosya yükleme, arama, görseller | ✅ |
| [Destek Talepleri](01_user_manual/destek_talepleri.md) | Ticket oluşturma, takip, geçmiş | ✅ |
| [Admin Paneli](01_user_manual/admin_paneli.md) | Org, kullanıcı, LLM, prompt yönetimi | ✅ |

---

### 🏗️ 02 — Mimari Tasarım
Sistem mimarisi, veritabanı şeması ve API referansı.

| Doküman | Açıklama | Durum |
|---------|----------|-------|
| [Sistem Mimarisi](02_architecture/system_overview.md) | Katmanlar, veri akışı, teknoloji yığını | ✅ |
| [Veritabanı Şeması](02_architecture/database_schema.md) | Tablolar, ilişkiler, indeksler | ✅ |
| [API Referansı](02_architecture/api_reference.md) | Tüm endpoint'ler, input/output | ✅ |
| [Güvenlik Modeli](02_architecture/security_model.md) | Auth, JWT, RBAC, rate limiting | ✅ |

---

### 🧩 03 — Bileşen Dokümantasyonu
Fonksiyon bazlı, input/output örnekli teknik detaylar.

#### Backend Bileşenleri
| Doküman | Açıklama | Durum |
|---------|----------|-------|
| [Dialog Pipeline](03_components/backend/dialog_pipeline.md) | Mesaj → İşleme → Yanıt akışı | ✅ |
| [RAG Pipeline](03_components/backend/rag_pipeline.md) | Upload → Chunk → Embed → Search | ✅ |
| [Doküman İşleyiciler](03_components/backend/document_processors.md) | DOCX/PDF/PPTX/Excel/TXT parser'lar | ✅ |
| [OCR Sistemi](03_components/backend/ocr_system.md) | EasyOCR, batch paralel OCR | ✅ |
| [ML Eğitim](03_components/backend/ml_training.md) | CatBoost, feature extraction | ✅ |
| [Doküman İyileştirici](03_components/backend/document_enhancer.md) | LLM tabanlı iyileştirme | ✅ |
| [Olgunluk Analizi](03_components/backend/maturity_analyzer.md) | Doküman kalite skorlama | ✅ |

#### Frontend Bileşenleri
| Doküman | Açıklama | Durum |
|---------|----------|-------|
| [Dialog Modülleri](03_components/frontend/dialog_modules.md) | Chat UI, mesaj render | ✅ |
| [RAG Modülleri](03_components/frontend/rag_modules.md) | Dosya listesi, kartlar, org modal | ✅ |
| [Ticket Modülleri](03_components/frontend/ticket_modules.md) | Ticket listesi, chat, LLM eval | ✅ |
| [Admin Modülleri](03_components/frontend/admin_modules.md) | LLM config, prompt, parametre | ✅ |
| [Yardımcı Modüller](03_components/frontend/utility_modules.md) | Lightbox, OCR popup, sidebar | ✅ |

---

### 🔧 04 — Geliştirici Rehberi
Yeni geliştiriciler için kurulum ve standartlar.

| Doküman | Açıklama | Durum |
|---------|----------|-------|
| [Ortam Kurulumu](04_developer_guide/environment_setup.md) | Python, PostgreSQL, .env | ✅ |
| [Kod Standartları](04_developer_guide/coding_standards.md) | CSS, modüler yapı, loglama | ✅ |
| [Test Rehberi](04_developer_guide/testing_guide.md) | pytest, coverage, TDD | ✅ |

---

## 🔄 Güncelleme Protokolü

Her yeni özellik veya versiyon güncellemesinde:

1. İlgili bileşen dokümanını güncelle
2. `CHANGELOG.md` dosyasına not ekle
3. Bu `INDEX.md`'deki versiyon numarasını güncelle
4. Doküman durum sütununu kontrol et

> 📌 Detaylı değişiklik geçmişi: [CHANGELOG.md](CHANGELOG.md)
