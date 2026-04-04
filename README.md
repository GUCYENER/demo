# VYRA L1 Support API - README

## 📋 Proje Hakkında

VYRA L1 Support API, AI destekli teknik destek sistemidir. RAG (Retrieval-Augmented Generation) teknolojisi ile bilgi tabanından semantik arama yaparak kullanıcılara otomatik çözüm önerileri sunar.

## 🏗️ Portable Altyapı (Standalone Dağıtım)

> **ÖNEMLİ:** Bu proje tamamen **portable/standalone** olarak çalışır. Sunucuya ayrıca yazılım kurulumu gerekmez. Tüm bileşenler proje klasörünün içindedir.

### Bileşenler

| Bileşen | Konum | Açıklama |
|---|---|---|
| **Python 3.13** | `python/` | Portable Python (venv yapısı). `python/Scripts/python.exe` ana çalıştırıcı. `python/Lib/site-packages/` paketler. |
| **PostgreSQL** | `pgsql/` | Standalone PostgreSQL kurulumu (port 5005). `pgsql/bin/` binary, `pgsql/data/` veritabanı. |
| **Redis** | `redis/` | Portable Redis server (port 6380, auth, 128MB LRU). Deep Think cache persistence. |
| **Nginx** | `nginx/` | Portable Nginx reverse proxy (port 8000). `nginx/conf/conf.d/vyra.conf` config. |
| **Offline Paketler** | `offline_packages/` | pip bağımlılıkları offline kurulum için. İnternete kapalı sunucularda kullanılır. |

### Başlatma / Durdurma

| Komut | Açıklama |
|---|---|
| `canlida_calistir.bat` | Tek tıkla production başlatma (PostgreSQL → Redis → Backend → Nginx) |
| `canlida_durdur.bat` | Tek tıkla güvenli durdurma |
| `start.ps1` | PowerShell ile başlatma (geliştirme ortamı, port 5500) |
| `stop.ps1` | PowerShell ile durdurma |

### Taşınabilirlik (Portability)

- Proje klasörü herhangi bir disk/dizine kopyalanabilir (`D:\VYRA`, `E:\VYRA`, `C:\projeler\vyra` vb.)
- `canlida_calistir.bat` ilk çalışmada **otomatik yol düzeltme** yapar:
  - `pyvenv.cfg` → Python home yolunu mevcut konuma günceller
  - `vyra.conf` → Nginx frontend root yolunu günceller
- Tüm script'ler `%~dp0` (bat) veya `$PSScriptRoot` (ps1) ile dinamik proje kökü kullanır

### Canlıya Taşıma (Yeni Sunucu Kurulumu)

1. Proje klasörünü hedef sunucuya kopyalayın
2. `python/Lib/` altında stdlib dosyaları yoksa (sadece `site-packages` varsa):
   ```powershell
   # Kaynak makinede çalıştırın (Python 3.13 kurulu olan makine):
   robocopy "C:\...\Python313\Lib" "PROJE\python\Lib" /E /XD site-packages __pycache__ test tests tkinter turtledemo idlelib ensurepip lib2to3
   robocopy "C:\...\Python313" "PROJE\python\Scripts" python3.dll python313.dll /NFL /NDL
   ```
3. `.env` dosyasını düzenleyin (JWT_SECRET, DB bilgileri vb.)
4. `canlida_calistir.bat` çift tıklayın — tüm servisler otomatik başlar

## 🚀 Versiyon Geçmişi

### 🆕 v3.4.0 (2026-04-04) - Modular Refactoring: document_enhancer.py → 8 Modül

**🏗️ Modüler Mimari (2350 satır → 8 modül, her biri ≤300 satır):**
- ✅ **Facade Pattern:** `document_enhancer.py` artık sadece orchestrator — iş mantığı alt modüllere delege edildi
- ✅ **Backward Compatibility:** Mevcut import path'leri (`from app.services.document_enhancer import ...`) aynen çalışmaya devam ediyor
- ✅ **Dosya türüne göre output bölme:** PDF, DOCX, XLSX oluşturma ayrı modüllerde

**📁 Yeni Modüller (`app/services/enhancer/`):**

| Modül | Satır | Sorumluluk |
|-------|-------|------------|
| `__init__.py` | 26 | Paket yönetimi ve re-export |
| `section_extractors.py` | 373 | PDF, DOCX, XLSX, CSV, PPTX, TXT bölüm çıkarma |
| `catboost_prioritizer.py` | 242 | CatBoost kalite tahmini, heuristic priority, weakness tespiti |
| `llm_enhancement.py` | 563 | LLM iyileştirme akışı + anchor + corrective retry |
| `output_pdf.py` | 220 | fpdf2 ile PDF oluşturma (Türkçe + Markdown + görseller) |
| `output_docx.py` | 188 | DOCX oluşturma/güncelleme (format koruma + görsel koruma) |
| `output_xlsx.py` | 99 | XLSX enhanced sheet ekleme (orijinal korunur) |
| `image_helpers.py` | 110 | Görsel-bölüm eşleştirme ve pozisyon hesaplama |

**🧪 Test Sonuçları:**
- ✅ **80 passed**, 3 skipped (eksik kütüphane), 0 failed
- ✅ **37 yeni modüler test** (`test_enhancer_modules.py`): SectionExtractor, CatBoostPrioritizer, LLMEnhancer, OutputXlsx, Facade, ImageHelpers
- ✅ **45 mevcut test** (`test_document_enhancer.py`): Regresyon — tümü geçti

**📁 Değişen Dosyalar:**
- `app/services/document_enhancer.py` — Monolitik → Facade (2350 → 304 satır)
- `app/core/config.py` — `APP_VERSION: 3.4.0`
- `app/core/schema.py` — `app_version: 3.4.0`
- `tests/test_document_enhancer.py` — Modüler import'lara uyum
- `tests/test_enhancer_modules.py` — 37 yeni modüler unit test

---

### 🆕 v3.3.3 (2026-04-04) - Zero-Loss Enhancement Architecture

**🛡️ Faz 1: Content Anchor Service (Extract-Protect-Reinject):**
- ✅ **`content_anchor_service.py` (YENİ):** 8 regex pattern (para birimi, yüzde, tarih, saat, URL/email, telefon, kod, sayı) ile kritik verileri ‹‹ANC_XXX›› placeholder'larına çevirir
- ✅ **Sıralı extraction:** Spesifik → genel (URL → tarih → saat → para → yüzde → telefon → kod → sayı) — çakışma yok
- ✅ **Re-injection:** LLM çıktısındaki placeholder'lar orijinal değerlerle geri doldurulur
- ✅ **Recovery:** LLM'in sildiği placeholder'lar bağlam bazlı otomatik kurtarılır (before_context eşleşmesi)

**🔄 Faz 2: Corrective Retry Mechanism (max 2 retry):**
- ✅ **`_call_llm_corrective()`:** Integrity validator başarısız olduğunda düzeltici prompt ile LLM tekrar çağrılır
- ✅ **Hata özeti:** Issues, kayıp varlıklar ve halüsinasyon şüphesi olan veriler LLM'e iletilir
- ✅ **Anchor koruması:** Retry'larda da anchor extract + reinject + recovery uygulanır
- ✅ **Metin kırpma:** Retry'da da 6000 char sınırı uygulanır (token limit koruması)

**📦 Faz 3: Structured Prompt — Fenced Critical Blocks:**
- ✅ **FROZEN_START / FROZEN_END:** Anchor ID'leri LLM'e yapılandırılmış şekilde sunulur
- ✅ **Tip özeti:** `url: 1, number: 3, date: 1` formatında anchor tip dağılımı

**📊 Faz 4: Semantik Tutarlılık + Diff Analizi:**
- ✅ **Cosine Similarity:** RAG embedding modeli ile orijinal/enhanced metin benzerliği (eşik: ≥0.80)
- ✅ **Diff Analizi:** `difflib.SequenceMatcher` ile satır bazlı silme/ekleme oranı tespiti (eşik: silme ≤%40)
- ✅ **Dinamik eşik:** `redundant_content` weakness'i varsa silme eşiği %60'a yükseltilir
- ✅ **Graceful fallback:** Embedding modeli yüklenemezse kontrol atlanır (penalty yok)

**📁 Yeni Dosyalar:**
- `app/services/content_anchor_service.py` — Extract-Protect-Reinject pattern (337 satır)

**📁 Değişen Dosyalar:**
- `app/core/config.py` — `APP_VERSION: 3.3.3`
- `app/core/schema.py` — `app_version: 3.3.3`
- `app/services/document_enhancer.py` — Retry loop, corrective prompt, fenced blocks, anchor entegrasyonu
- `app/services/content_integrity_validator.py` — Semantik tutarlılık + diff analizi (2 yeni kontrol)

---

### 🆕 v3.3.1 (2026-04-03) - Anlık Eğitim Revizyonu + Dosya Yükleme Bildirim İyileştirmesi

**⚡ Anlık Eğitim (Model Sekmesi):**
- ✅ **Kriterden bağımsız:** "Yeterli Veri Yok" butonu kaldırıldı — feedback sayısı ne olursa olsun eğitim başlatılabilir
- ✅ **Çift katman çakışma kontrolü:** Local state + sunucu `/status` sorgusu — otomatik eğitim çalışıyorsa uyarı verir
- ✅ **Notification:** Eğitim tamamlandığında `NgssNotification.success()` ile bildirime yazılır
- ✅ **Dinamik hint:** "En az 50 feedback gerekli" → "Sistemdeki feedback: N" (bilgi amaçlı)
- ✅ **CSS class migration:** Inline style → `.ml-train-desc`, `.ml-train-actions`, `.ml-train-hint` class'ları

**📄 Dosya Yükleme Bildirim İyileştirmesi:**
- ✅ **Processing polling:** Upload sonrası 5sn aralıkla dosya durumu kontrol eden REST fallback polling eklendi
- ✅ **WS-bağımsız bildirim:** WebSocket çalışmasa bile dosya işleme tamamlandığında `NgssNotification.add('success', ...)` bildirime yazılır
- ✅ **Duplicate koruması:** WS `rag_upload_complete` gelince polling otomatik durur — çift bildirim önlenir
- ✅ **Auto-scroll:** Upload sonrası dosya listesine (`#rag-files-list`) smooth scroll eklendi
- ✅ **İlk bildirim:** "📄 Dosya İşleniyor" → "📄 Dosya Yüklendi" olarak düzeltildi

**📁 Değişen Dosyalar:**
- `app/core/config.py` — `APP_VERSION: 3.3.1`
- `app/core/schema.py` — `app_version: 3.3.1`
- `app/services/ml_training_service.py` — `training_ready = True` (kriterden bağımsız)
- `frontend/assets/js/modules/ml_training.js` — Buton/hint/polling/notification revizyonu
- `frontend/assets/js/rag_upload.js` — `_startProcessingPoll()`, auto-scroll, bildirim iyileştirmesi
- `frontend/assets/js/websocket_client.js` — WS handler'da polling durdurucu
- `frontend/assets/css/home.css` — `.ml-train-desc`, `.ml-train-actions`, `.ml-train-hint`
- `frontend/partials/section_parameters.html` — İnline style → CSS class'lar

---

### 🆕 v3.3.0 (2026-04-03) - RAG Pipeline Optimization: WebSocket Progress, Paralel Processing, Dosya Versiyonlama

**🔴 P0 — Enhancement Pipeline İyileştirmeleri:**
- ✅ **C5: Enhancement Progress WebSocket:** `rag_enhance.py` + `document_enhancer.py` — LLM iyileştirme sırasında bölüm bazlı gerçek zamanlı ilerleme: "Bölüm 3/10 iyileştiriliyor..." mesajı WebSocket üzerinden frontend'e gönderilir
- ✅ **C5 Frontend:** `websocket_client.js` — `enhancement_progress` mesaj handler'ı, `vyra:enhancement_progress` event dispatch
- ✅ **C5 Modal:** `document_enhancer_modal.js` — Animasyonlu progress bar, bölüm detay gösterimi, listener lifecycle yönetimi
- ✅ **C5 CSS:** `document_enhancer_modal.css` — Progress bar gradient shimmer animasyonu, detay metin stili

**🟡 P1 — Performans Optimizasyonları:**
- ✅ **A2: NumPy Dedup:** `rag/service.py` — `_deduplicate_chunks()` O(n²) pure-Python cosine similarity → NumPy vectorized matris çarpımı (~100x hız artışı). Import hatası fallback korunuyor
- ✅ **A7: Paralel Dosya Processing:** `rag_upload.py` — Sıralı `for` loop → `asyncio.gather` ile concurrent dosya işleme. ThreadPoolExecutor(max_workers=2) paralelliği doğal sınırlar
- ✅ **A4: Dosya Versiyonlama:** `rag_upload.py` + `schema.py` — Hard-delete yerine soft-delete (is_active=false) + version artırma. `file_version`, `is_active`, `file_hash` sütunları eklendi

**🔵 P1 — Altyapı Modernizasyonu:**
- ✅ **A8: pgvector Migration:** `schema.py` — `FLOAT[]` → `vector(384)` güvenli migration (pgvector yoksa atlanır) + IVFFlat index. 3 tablo: `rag_chunks`, `learned_answers`, `ds_learning_results`
- ✅ **C6: PDF Font Koruması:** `document_enhancer.py` — PyMuPDF ile orijinal PDF font boyutu tespit edilerek enhanced çıktıda korunuyor. Heading boyutları body'ye oranla dinamik
- ✅ **D1: Enhancement Etki Ölçümü:** `rag_enhance.py` — `GET /enhancement-impact` endpoint. maturity_score_before/after karşılaştırma + iyileşme yüzdesi raporu

**🟢 P2 — Altyapı:**
- ✅ **Versiyon:** `config.py` → `APP_VERSION: 3.3.0`, `schema.py` → `system_settings app_version: 3.3.0`
- ✅ **SSS:** INDEX, CHANGELOG, api_reference, database_schema güncellendi

**📁 Değişen Dosyalar (10+ dosya):**
- `app/core/config.py` — `APP_VERSION: 3.3.0`
- `app/core/schema.py` — `app_version: 3.3.0`, dosya versiyonlama sütunları + pgvector migration + index'ler
- `app/api/routes/rag_enhance.py` — WebSocket progress callback, current_user dependency, enhancement-impact endpoint
- `app/api/routes/rag_upload.py` — Paralel processing (asyncio.gather), dosya versiyonlama (soft-delete)
- `app/services/document_enhancer.py` — `progress_callback`, C6 PDF font koruması (PyMuPDF)
- `app/services/rag/service.py` — NumPy vectorized dedup
- `frontend/assets/js/websocket_client.js` — `enhancement_progress` handler
- `frontend/assets/js/modules/document_enhancer_modal.js` — Progress bar + WS listener
- `frontend/assets/css/modules/document_enhancer_modal.css` — Progress bar CSS
- `sss/INDEX.md`, `sss/CHANGELOG.md`, `sss/02_architecture/api_reference.md`, `sss/02_architecture/database_schema.md`

---

### 🆕 v3.2.1 (2026-04-03) - RAG Best Practice: Context Injection, Chunk Overlap & Native Format Enhance

**🔴 P0 — RAG Retrieval Doğruluğu:**
- ✅ **Context Injection:** `rag/service.py` — Her chunk text'ine `[Kaynak: dosya_adı | Bölüm: heading]` prefix eklenir → embedding modeli bağlamı görür, retrieval doğruluğu %15-30 artar
- ✅ **Heading prefix (tüm processor'lar):** `excel_processor.py`, `txt_processor.py`, `docx_processor.py` — Chunk text'e `[Bölüm: sheet/heading]` prefix eklenerek embedding arama bağlamı güçlendirildi
- ✅ **Chunk overlap:** `docx_processor.py`, `txt_processor.py` — `OVERLAP_SIZE=100` karakter — bölüm geçişlerinde bağlam kaybı önlendi
- ✅ **Speaker notes bonus:** `rag/service.py` — `speaker_notes` tipi chunk'lara +0.10 quality bonus (açıklayıcı içerik)

**🟡 P1 — Document Enhancement Pipeline:**
- ✅ **Native XLSX/PPTX enhance:** `rag_enhance.py` — Enhanced dosyalar artık orijinal formatında (XLSX/PPTX) kalır, zorla DOCX dönüştürme kaldırıldı
- ✅ **Section-based chunking (enhance):** `rag_enhance.py` — XLSX/PPTX enhance sonrası approved section text'lerinden heading prefix'li chunk oluşturulur
- ✅ **İyileştirilmiş maturity re-score:** `rag_enhance.py` — Upload öncesi enhance edilmiş dosyanın olgunluk skoru yeniden hesaplanır (orijinal skor değil)
- ✅ **Content Integrity Validator:** `content_integrity_validator.py` (**YENİ**) — LLM çıktısının orijinal içerikle tutarlılığını doğrular (`integrity_score`, `integrity_issues`)
- ✅ **LLM hata yönetimi:** `document_enhancer.py` — `llm_error` ve `integrity_failed` change type'ları eklendi, başarısız bölümler kullanıcıya gösterilir
- ✅ **Session temizleme güvenliği:** `rag_enhance.py` — Upload sonrası session hemen silinmez, `_uploaded` flag ile işaretlenir (race condition koruması)

**🟢 P2 — Processor İyileştirmeleri:**
- ✅ **Excel sheet summary chunk:** `excel_processor.py` — Dosya seviyesinde sheet özeti chunk'ı (satır/sütun sayısı) → RAG'da dosya bağlamı
- ✅ **charset-normalizer encoding:** `txt_processor.py` — `charset_normalizer.from_bytes()` ile akıllı encoding tespiti (Türkçe dosyalarda iyileştirme)
- ✅ **file_type metadata:** `docx_processor.py`, `txt_processor.py`, `pptx_processor.py` — Tüm chunk metadata'ya `file_type` alanı eklendi
- ✅ **Fortify uyumluluk:** `docx_processor.py`, `pptx_processor.py` — `print(sys.stderr)` → `logging` modülüne taşındı
- ✅ **Enhancer priority genişletme:** `document_enhancer.py` — Excel (merge, boş satır, formül), DOCX (metin kutusu, liste), PPTX (slayt başlık) ihlal boost'ları eklendi
- ✅ **Enhancer weakness genişletme:** `document_enhancer.py` — Tüm dosya türleri için yapısal zayıflık tespiti

**🎨 Frontend İyileştirmeleri:**
- ✅ **Enhancer modal LLM hata gösterimi:** `document_enhancer_modal.js` — `llm_error` ve `integrity_failed` badge'leri, sıralama iyileştirmesi
- ✅ **Maturity modal PPTX/TXT desteği:** `maturity_score_modal.js` — Tüm dosya türleri için maturity analiz başlatma
- ✅ **Inline CSS temizliği:** `document_enhancer_modal.js` — `style.display` → CSS class (`hidden`) geçişi
- ✅ **Retry butonu:** `rag_file_list.js` — Başarısız dosyalarda `fa-rotate-right` butonu + `retryFile()` fonksiyonu
- ✅ **Upload progress bar:** `rag_file_list.js` — WebSocket `rag_upload_progress` event ile gerçek zamanlı ilerleme çubuğu
- ✅ **WS progress handler:** `websocket_client.js` — `rag_upload_progress` ve `rag_upload_complete` event dispatch
- ✅ **CSS iyileştirmeleri:** `document_enhancer_modal.css` + `rag_upload.css` — Progress bar, retry buton, integrity badge stilleri

**📁 Yeni Dosyalar:**
- `app/services/content_integrity_validator.py` — LLM çıktısı bütünlük doğrulama servisi

**📁 Değişen Dosyalar (23 dosya):**
- `app/core/config.py` — `APP_VERSION: 3.2.1`
- `app/core/schema.py` — `app_version: 3.2.1` (system_settings)
- `app/api/routes/rag_enhance.py` — Native format + section chunking + maturity re-score + session guard
- `app/api/routes/rag_upload.py` — WS progress + retry endpoint
- `app/api/routes/rag_maturity.py` — API güvenlik (exception maskeleme)
- `app/services/document_enhancer.py` — Integrity validator + LLM hata yönetimi + priority/weakness genişletme
- `app/services/maturity_analyzer.py` — Logging + merge penalty yumuşatma + gizli sheet + büyük dosya kuralları
- `app/services/rag/service.py` — `_inject_context_prefix()` + speaker notes bonus
- `app/services/document_processors/excel_processor.py` — Sheet summary + gruplu chunking + heading prefix
- `app/services/document_processors/docx_processor.py` — Chunk overlap + file_type metadata + logging
- `app/services/document_processors/txt_processor.py` — charset-normalizer + chunk overlap + heading prefix
- `app/services/document_processors/pptx_processor.py` — file_type metadata + logging
- `app/services/document_processors/pdf_processor.py` — file_type metadata
- `app/services/document_processors/image_extractor.py` — Minor fix
- `frontend/assets/js/modules/document_enhancer_modal.js` — LLM hata UI + inline CSS kaldırma
- `frontend/assets/js/modules/maturity_score_modal.js` — Tüm dosya türleri desteği
- `frontend/assets/js/modules/rag_file_list.js` — Retry + progress listener
- `frontend/assets/js/websocket_client.js` — Progress event dispatch
- `frontend/assets/js/modules/company_module.js` — Logo 404 fallback
- `frontend/assets/css/modules/document_enhancer_modal.css` — Integrity badge + hata stilleri
- `frontend/assets/css/rag_upload.css` — Progress bar + retry buton stilleri
- `frontend/home.html` — Cache busting v3.2.1

---

### 🆕 v3.2.0 (2026-04-02) - XLSX Upload Pipeline Optimizasyonu

**🔴 P0 — Kritik Düzeltmeler:**
- ✅ **Veri kaybı fix:** `excel_processor.py` — `'0'` ve `'0.0'` değerleri artık filtrelenmiyor (finansal tablolarda veri kaybı önlendi)
- ✅ **Fortify uyumluluk:** `excel_processor.py` + `maturity_analyzer.py` — Tüm `print(sys.stderr)` → `logging` modülüne taşındı (10+ satır)
- ✅ **API güvenlik:** `rag_maturity.py` + `maturity_analyzer.py` — Exception detayları API response'dan kaldırıldı, genel hata mesajı döndürülür

**🟡 P1 — İşlevsel İyileştirmeler:**
- ✅ **`.xls` maturity analiz:** `analyze_xls()` fonksiyonu — `xlrd` tabanlı bağımsız analiz (3 kural: başlık, boşluk, veri tipi)
- ✅ **Logo 404 fallback:** `company_module.js` — Logo `<img>` tag'ına `onerror` handler eklendi
- ✅ **Merge penalty yumuşatma:** Eşik 10→20, skor 30→50 — processor merge'leri otomatik çözümlediği için ağır penalty gereksiz
- ✅ **Gruplu chunking:** `MIN_CHUNK_LENGTH=20` — Kısa satırlar birleştirilerek daha anlamlı chunk'lar oluşturuluyor

**🟢 P2 — Altyapı Geliştirmeleri:**
- ✅ **`.xls` merge hücre desteği:** `_chunks_from_xlrd()` — xlrd merge haritası ile boş hücreler doldurulur
- ✅ **Gizli sheet kontrolü:** Maturity KURAL 7 — hidden sheet uyarısı
- ✅ **Büyük dosya uyarısı:** Maturity KURAL 8 — 10K+ satır performans uyarısı
- ✅ **WebSocket progress:** `rag_upload_progress` mesaj tipi — dosya bazlı gerçek zamanlı ilerleme
- ✅ **Retry endpoint:** `POST /retry-file/{file_id}` — başarısız dosyaları tekrar işleme

**📁 Değişen Dosyalar:**
- `app/services/document_processors/excel_processor.py` — 4 düzeltme (veri kaybı, logging, gruplu chunking, XLS merge)
- `app/services/maturity_analyzer.py` — 6 düzeltme (logging, XLS desteği, merge penalty, gizli sheet, boyut uyarısı)
- `app/api/routes/rag_maturity.py` — API güvenlik (exception maskeleme)
- `app/api/routes/rag_upload.py` — WS progress bildirimi + retry endpoint
- `frontend/assets/js/websocket_client.js` — Progress handler
- `frontend/assets/js/modules/company_module.js` — Logo fallback

**🧪 Test:** 46 passed, 0 failed ✅

---

### 🆕 v3.1.2 (2026-04-02) - ML Training Stabilization & Learned Q&A All-Training

**🧠 Learned Q&A — Tüm Eğitim Tiplerine Entegrasyon:**
- ✅ **`train_model.py` Adım 11:** Scheduled/Manual eğitimlerden sonra da `bulk_generate()` çağrılıyor
- ✅ **Limit kaldırıldı:** `max_answers=50` limiti kaldırıldı — barajı aşan (relevance=1, score≥0.70) TÜM sorular işleniyor
- ✅ **Overflow protection:** Soru max 500 char, cevap max 3000 char, chunk max 2000 char sınırı
- ✅ **Temiz kesim:** Cevap uzunsa son cümle noktasında kırpılıyor (cümle ortasında kalmaz)
- ✅ **Refinement koruması:** `_refine_answer()` giriş verileri de sınırlandırıldı

**🔧 Çift Job Kaydı Sorunu:**
- ✅ **`--job-id` parametresi:** `job_runner` → `train_model.py` mevcut job ID iletimi
- ✅ **Standalone/External mod:** Dışarıdan job ID gelince yeni kayıt oluşturmaz

**⏱️ Timeout Dinamik Okuma:**
- ✅ **Hardcoded 600s kaldırıldı:** `get_job_timeout_setting()` ile DB'den dakika cinsinden okuma
- ✅ **Scope güvenliği:** `timeout_min` try bloğu dışında tanımlı (UnboundLocalError riski yok)
- ✅ **Dinamik hata mesajı:** Timeout mesajında gerçek limit değeri gösteriliyor

**🛡️ quality_drop Cooldown:**
- ✅ **Sonsuz döngü engeli:** Son eğitimden beri yeni feedback yoksa quality_drop tetiklenmiyor

**📐 Dinamik Halüsinasyon Eşikleri:**
- ✅ **Length Ratio:** Kaynak <200 char → 30x, 200-500 → 15x, >500 → 8x (kısa komut referansları için)
- ✅ **Grounding:** Kaynak <200 char → %5, 200-500 → %15, >500 → %30 (kısa chunk'larda az kelime örtüşmesi doğal)

**📁 Değişen Dosyalar:**
- `scripts/train_model.py` — `--job-id` param + Learned Q&A (Adım 11)
- `app/services/ml_training/job_runner.py` — `--job-id` iletimi + DB timeout
- `app/services/ml_training/scheduling.py` — quality_drop cooldown
- `app/services/learned_qa_service.py` — max_answers limitsiz + overflow protection + dinamik eşikler
- `app/services/ml_training/continuous_learning.py` — max_answers kaldırıldı

---

### 🆕 v2.60.2 (2026-03-27) - Production Deployment Optimizasyonu

**⚡ ONNX Embedding Optimizasyonu:**
- ✅ **ONNX Runtime:** sentence-transformers PyTorch yerine ONNX model kullanımı (~200s → ~4s yükleme)
- ✅ **HuggingFace resmi ONNX:** `model.onnx` + `tokenizer.json` — offline kullanım
- ✅ **token_type_ids:** BERT modeli zorunlu kılıyor, dinamik ekleme

**🔐 Redis Güvenlik & Port:**
- ✅ **Port 6380:** Mevcut Redis çakışmasını önlemek için özel port
- ✅ **requirepass:** Redis şifreli erişim (`redis.windows.conf` + `.env`)
- ✅ **Bat entegrasyonu:** `canlida_calistir.bat` ve `canlida_durdur.bat` şifreli Redis CLI

**🖥️ Multi-Instance Uvicorn (Windows):**
- ✅ **4 ayrı instance:** Windows multiprocessing socket hatası (`WinError 10022`) çözümü
- ✅ **Port aralığı:** 8002-8005, Nginx upstream load-balance
- ✅ **Port müsaitlik kontrolü:** Başlatma öncesi `netstat` ile çakışma tespiti

**🌐 Nginx İyileştirmeleri:**
- ✅ **Dinamik frontend root:** `vyra.conf`'taki path her çalıştırmada `%PROJECT_ROOT%` ile otomatik güncellenir
- ✅ **BOM koruması:** PowerShell UTF8NoBOM ile dosya yazma
- ✅ **$http_host:** Proxy redirect port kaybı düzeltildi (CORS hatası çözümü)
- ✅ **Config testi:** `nginx -t` ile başlatma öncesi syntax doğrulama

**🛑 Durdurma Scripti (canlida_durdur.bat):**
- ✅ **Tam yeniden yazım:** Redis port 6380 + auth, Python PID bazlı kill (sadece VYRA), PostgreSQL fast→immediate fallback
- ✅ **Process temizliği:** Tüm servislerde orphan process tespiti ve zorla durdurma

**📁 Değişen Dosyalar:**
- `app/services/rag/embedding.py` — ONNX yükleme ve token_type_ids
- `app/core/config.py` — REDIS_URL port 6380, v2.60.2
- `.env` — Redis şifreli URL
- `redis/redis.windows.conf` — requirepass + port 6380
- `canlida_calistir.bat` — Multi-instance Uvicorn, dinamik Nginx root, port kontrolü
- `canlida_durdur.bat` — Tam yeniden yazım
- `nginx/conf/conf.d/vyra.conf` — 4 upstream, $http_host, dinamik root

---

### 🆕 v2.60.1 (2026-03-26) - Hardcoded Renk Temizliği (Full Branding Compliance)

**🎨 CSS Değişken Migrasyonu:**
- ✅ **14 CSS + 1 HTML dosyasında ~90 satır** hardcoded sarı/amber renk (`#fbbf24`, `#f59e0b`, `rgba(251,191,36,...)`) `var()` wrapper'larına dönüştürüldü
- ✅ **Etkilenen modüller:** home, dialog-chat, authorization, modal, toast, notification, ticket-history, ldap_settings, org_permissions, rag_upload, ds_learning, maturity_score_modal, document_enhancer_modal, vyra_auth, section_parameters
- ✅ **BrandingEngine uyumu:** Tüm UI bileşenleri artık dinamik tema renklerine %100 uyumlu

**📁 Değişen Dosyalar:**
- `frontend/assets/css/home.css` — 25 satır var() migrasyonu
- `frontend/assets/css/dialog-chat.css` — 6 satır var() migrasyonu
- `frontend/assets/css/authorization.css` — 3 satır var() migrasyonu
- `frontend/assets/css/modules/ldap_settings.css` — 14 satır var() migrasyonu
- `frontend/assets/css/modules/org_permissions.css` — 13 satır var() migrasyonu
- `frontend/assets/css/rag_upload.css` — 7 satır var() migrasyonu
- `frontend/assets/css/modules/ds_learning.css` — 6 satır var() migrasyonu
- `frontend/assets/css/modules/maturity_score_modal.css` — 5 satır var() migrasyonu
- `frontend/assets/css/modules/document_enhancer_modal.css` — 3 satır var() migrasyonu
- `frontend/assets/css/modal.css` — 3 satır var() migrasyonu
- `frontend/assets/css/toast.css` — 2 satır var() migrasyonu
- `frontend/assets/css/ticket-history.css` — 2 satır var() migrasyonu
- `frontend/assets/css/notification.css` — 1 satır var() migrasyonu
- `frontend/assets/css/vyra_auth.css` — 1 satır var() migrasyonu
- `frontend/partials/section_parameters.html` — 1 inline style var() migrasyonu

---

### 🆕 v2.60.0 (2026-03-25) - Özel Tema Oluşturucu & Kullanıcı Tema Seçici

**🎨 Özel Tema Oluşturucu (Admin):**
- ✅ **Firma Tasarım Sekmesi:** Tema kart grid, color picker, canlı önizleme
- ✅ **Renk Önerme:** Complementary, Analogous, Triadic, Split Complementary renk algoritması
- ✅ **CSS Variable Engine:** İki ana renkten otomatik dark+light mod CSS değişken hesaplama
- ✅ **Firma-Tema Atama:** `company_theme_assignments` tablosu ile çoklu tema atama
- ✅ **Anlık Yansıtma:** Firma kaydedildiğinde tema anında uygulanıyor (BrandingEngine.applyAll)

**🌙 Kullanıcı Tema Seçici:**
- ✅ **Ay butonu popup:** Firma bazlı tema listesi, dark/light toggle
- ✅ **Anlık uygulama:** Tema seçildiğinde sayfa yenilemesiz CSS güncelleme
- ✅ **ESC desteği + Overlay koruması:** Modal standartlarına uygun

**📁 Yeni Dosyalar:**
- `frontend/assets/js/modules/theme_picker_popup.js` — Kullanıcı tema seçici popup
- `frontend/assets/css/theme_picker.css` — Popup ve tasarım sekmesi stilleri

**📁 Değişen Dosyalar:**
- `app/api/routes/themes.py` — CRUD, suggest, assign, company-themes endpoint'leri (8 route)
- `app/core/schema.py` — `company_theme_assignments` tablosu, `is_custom`/`company_id` sütunları
- `frontend/assets/js/modules/company_module.js` — Tasarım sekmesi UI, tema atama, anlık yansıtma
- `frontend/partials/modals.html` — Tasarım sekmesi HTML (color picker, öner butonu, kart grid)
- `frontend/home.html` — Ay butonu → ThemePickerPopup.toggle()
- `frontend/build.mjs` — Yeni dosyalar bundle'a dahil

### 🆕 v2.59.0 (2026-03-25) - Multi-Tenant Branding System

**🎨 Firma Bazlı Dinamik Branding:**
- ✅ **`company_themes` tablosu:** 11 hazır SaaS tasarım (Okyanus Mavisi, Altın Sarısı, Zümrüt Orman, Sarı Siyah vb.)
- ✅ **`companies` branding alanları:** `app_name` (varsayılan: NGSSAI) + `theme_id` FK
- ✅ **Tasarım sekmesi:** Parametreler ekranında tema kartlı grid kataloğu
- ✅ **Firma CSS Tasarımı dropdown:** Firma tanımında tema seçimi + önizleme butonu
- ✅ **Branding Engine:** Login ve ana ekranda CSS değişkenleri, logo, app_name otomatik uygulama
- ✅ **URL bazlı eşleşme:** `GET /api/companies/by-url` — subdomain'e göre branding

**🔧 Düzeltmeler:**
- ✅ **Favicon:** Eski "V" API favicon → inline SVG "N" ikonu
- ✅ **Sidebar/Topbar ikon:** "H" → "N" (NGSSAI) güncellendi
- ✅ **CSS lint uyarıları:** `background-clip: text` ve `appearance: none` standart property eklendi
- ✅ **Console hataları:** `config.js` çift yükleme kaldırıldı
- ✅ **CORS trailing slash:** 6 API çağrısında trailing slash düzeltmesi

**📁 Yeni Dosyalar:**
- `app/api/routes/themes.py` — Tema API (3 endpoint)
- `frontend/assets/js/branding_engine.js` — Dinamik branding motoru
- `frontend/assets/js/modules/theme_catalog_module.js` — Tema kataloğu modülü
- `frontend/assets/css/modules/theme_catalog.css` — Tema kartları stilleri
- `tests/test_themes_branding.py` — 33 unit test

**📁 Değişen Dosyalar:**
- `app/api/main.py` — themes router kaydı
- `app/api/routes/companies.py` — app_name, theme_id CRUD
- `app/core/schema.py` — company_themes tablo + ALTER companies + 11 tema data
- `frontend/home.html` — Branding engine entegrasyon, favicon, N ikonu
- `frontend/login.html` — CSS lint düzeltmeleri
- `frontend/partials/modals.html` — Uygulama Adı + Tema seçimi alanları
- `frontend/partials/section_parameters.html` — Tasarım sekmesi
- `frontend/assets/js/modules/company_module.js` — Tema yükleme/kaydetme/önizleme
- `frontend/assets/js/modules/param_tabs.js` — Tasarım tab kaydı

**🧪 Test:** 33 yeni + 658 regresyon = **658/658 PASSED** ✅

---

### 🆕 v2.58.0 (2026-03-24) - Hybrid Router Pipeline Faz 2

**🤖 LLM Text-to-SQL:**
- ✅ **Template fallback:** Template SQL eşleşmediğinde LLM ile schema-aware SQL üretimi
- ✅ **3 aşamalı parser:** ```sql bloğu, genel code block, SELECT fallback parse
- ✅ **6 katmanlı güvenlik:** `validate_sql()` + `check_table_whitelist()` — DDL/DML/injection koruması

**🔀 Answer Merger (HYBRID intent):**
- ✅ **DB + RAG birleştirme:** `_merge_hybrid_answer()` — veritabanı verileri ve doküman bilgilerini LLM ile sentezleme
- ✅ **`process()` + `process_stream()`:** HYBRID intent desteği — paralel DB + RAG çağrı ve merge

**📊 Streaming Pipeline DB Desteği:**
- ✅ **`process_stream()` DB routing:** Intent detection sonrası DB routing
- ✅ **`db_complete` event:** DB sonuçları geldi sinyali (row_count, source_db, SQL, elapsed_ms)
- ✅ **Merge streaming:** DB + RAG sonuçları birleşik `done` event'i ile

**🛡️ SQL Audit Log Dashboard:**
- ✅ **`sql_audit_log` tablosu:** `company_id` FK, execution log (user, source, SQL, status, elapsed_ms)
- ✅ **Admin API:** `GET /api/admin/sql-audit` (sayfalı, filtreli), `GET .../stats` (istatistik özeti)
- ✅ **Audit entegrasyonu:** process() + process_stream() sonrasında otomatik log kaydı

**📁 Yeni Dosyalar:**
- `app/services/text_to_sql.py` — LLM Text-to-SQL servisi (284 satır)
- `app/services/sql_audit_log.py` — SQL audit log servisi (240 satır)
- `app/api/routes/sql_audit_api.py` — Admin SQL audit API (54 satır)
- `tests/test_text_to_sql.py` — 14 unit test
- `tests/test_answer_merger.py` — 5 unit test
- `tests/test_sql_audit.py` — 6 unit test

**📁 Değişen Dosyalar:**
- `app/services/hybrid_router.py` — `_generate_and_execute_llm_sql()` LLM fallback
- `app/services/deep_think_service.py` — `_merge_hybrid_answer()`, HYBRID intent, audit log
- `app/core/schema.py` — `sql_audit_log` tablosu + index'ler
- `app/api/main.py` — `sql_audit_api.router` include

**🧪 Test:** 25 yeni + tüm regresyon = 100% PASSED ✅

---

### 🆕 v2.55.0 (2026-03-23) - Veri Kaynakları Yönetimi + Bilgi Tabanı Entegrasyonu

**🔌 Veri Kaynakları (Parametreler → Kaynaklar Sekmesi):**
- ✅ **5 kaynak tipi:** Veri Tabanı (PostgreSQL/MSSQL/MySQL/Oracle), File Server, FTP/SFTP, SharePoint, Manuel Dosya
- ✅ **CRUD API:** `data_sources_api.py` — JWT auth, Fernet şifreleme, firma bazlı yetki
- ✅ **Dinamik modal:** Kaynak tipine göre form alanları değişiyor (DB bağlantı, FTP protokol, SharePoint Azure AD)
- ✅ **Modern SaaS UI:** Kart grid, tip badge, durum göstergesi, glassmorphism modal
- ✅ **Firma bazlı:** Admin tüm firmaları görür, kullanıcı sadece kendi firması

**📋 Bilgi Tabanı Entegrasyonu:**
- ✅ **Kaynak seçimi:** Dosya yükleme alanı üstünde tanımlı veri kaynağı dropdown'ı
- ✅ **Dosya listesi kolonu:** "Veri Kaynağı" kolonu badge'li gösterim (5 tip × renk kodu)

**🗄️ Veritabanı:**
- ✅ **`data_sources` tablosu:** `schema.py` + Alembic migration `002_data_sources.py`
- ✅ **İndeksler:** `company_id`, `source_type`, `is_active`

**📁 Yeni Dosyalar:**
- `app/api/routes/data_sources_api.py` — CRUD API (270 satır)
- `frontend/assets/js/modules/data_sources_module.js` — Frontend modülü (598 satır)
- `frontend/assets/css/modules/data_sources.css` — CSS stilleri (356 satır)
- `migrations/versions/002_data_sources.py` — Alembic migration

**📁 Değişen Dosyalar:**
- `app/api/main.py` — data_sources router kaydı
- `app/core/schema.py` — data_sources tablo, app_version
- `frontend/partials/section_parameters.html` — Kaynaklar sekmesi
- `frontend/assets/js/modules/param_tabs.js` — Tab switch desteği
- `frontend/assets/js/rag_upload.js` — Kaynak seçimi dropdown
- `frontend/assets/js/modules/rag_file_list.js` — Veri Kaynağı kolonu
- `frontend/build.mjs` — Yeni JS/CSS bundle
- `frontend/home.html` — Cache busting v2.55.0

---

### 🆕 v2.53.1 (2026-03-22) - RAG Kısa Sorgu Koruması + Deep Think Pipeline Guard

**🔍 RAG Normalizasyon Düzeltmesi:**
- ✅ **Akıllı normalizasyon (`scoring.py`):** Tek sonuçta ham skor korunur, 2 sonuçta oransal, 3+ sonuçta Min-Max — `original_raw_score` saklanır
- ✅ **Mutlak minimum ham skor filtresi (`service.py`):** `ABSOLUTE_MIN_RAW_SCORE = 0.42` — düşük kaliteli eşleşmeler elenir
- ✅ **Kısa sorgu eşik yükseltme (`rag.py`):** 5 karakterden az anlamlı içerik → `min_score = 0.55`

**🛡️ Deep Think Kısa Sorgu Guard (3 katman):**
- ✅ **`_is_short_meaningless_query()`:** Kesik kelime tespiti ("bilg.", "yet."), tek kelime ve toplam <10 char kontrolü
- ✅ **`process()` + `process_stream()` guard:** Cache kontrolünden ÖNCE çalışır → eski yanlış cache sonuçları da engellenir
- ✅ **`processor.py` guard:** Dialog seviyesinde Deep Think'e gitmeden ÖNCE anlamsız sorgu filtresi

**⚡ Expanded Retrieval İyileştirme:**
- ✅ **Kısa sorgu min_score:** 8 karakterden az anlamlı içerik → `min_score = 0.45` (Deep Think pipeline)

**📁 Değişen Dosyalar:**
- `app/services/rag/scoring.py` — Akıllı normalizasyon stratejisi
- `app/services/rag/service.py` — ABSOLUTE_MIN_RAW_SCORE filtresi
- `app/core/rag.py` — Kısa sorgu eşik yükseltme
- `app/services/deep_think_service.py` — Kısa sorgu guard + expanded_retrieval iyileştirme
- `app/services/dialog/processor.py` — Dialog seviyesi kısa sorgu koruması

---

### 🆕 v2.53.0 (2026-03-19) - Login Firma Branding + Company ID Gap Fix

**🏢 Login Ekranı Firma Branding:**
- ✅ **URL'den firma eşleşmesi:** `GET /api/companies/by-url` (auth gerektirmez) — companies.website ile ILIKE eşleşme
- ✅ **Login formu üstünde:** Firma logosu (56x56) + firma adı + "Firma Tanımlı" read-only badge
- ✅ **Glassmorphism kart:** Gradient üst çizgi, smooth animasyon, modern SaaS tasarım
- ✅ **Modüler yapı:** `login_branding.js` — IIFE pattern, null-check kontrolleri, try/catch

**🔧 Company ID Gap Düzeltmeleri (8 dosya, 12+ değişiklik):**
- ✅ **`companies.py` GET list SELECT:** `website` sütunu eksikti → eklendi (kayıt sonrası görünüm düzeltildi)
- ✅ **`system.py` reset:** Firma bazlı filtre tutarsızlığı — 8 tablo artık company_id ile filtreleniyor
- ✅ **`rag_upload.py`/`rag_files.py`:** company_id param + INSERT/WHERE eklendi
- ✅ **`auth.py`:** Register + LDAP register'a company_id eklendi
- ✅ **`ticket_service.py`:** 3 INSERT'e user→company_id çekimi
- ✅ **`rag_search.py`:** stats endpoint'ine company_id param eklendi

**📁 Yeni Dosyalar:**
- `frontend/assets/js/login_branding.js` — Login firma branding modülü (102 satır)

**📁 Değişen Dosyalar:**
- `app/api/routes/companies.py` — `by-url` endpoint + GET list SELECT düzeltmesi
- `app/api/routes/system.py` — Firma bazlı reset tutarlılığı
- `app/api/routes/rag_upload.py` — company_id INSERT
- `app/api/routes/rag_files.py` — company_id WHERE
- `app/api/routes/auth.py` — register/LDAP company_id
- `app/api/routes/rag_search.py` — stats company_id
- `app/services/ticket_service.py` — 3 ticket INSERT company_id
- `frontend/login.html` — Firma branding bloğu + CSS

---

### 🆕 v2.52.1 (2026-03-05) - İlgisiz İçerik Filtreleme + CatBoost Bypass Fix + Enhance API Fix

**🔧 Enhance API Düzeltmeleri:**
- ✅ **API URL düzeltme:** `window.API_BASE` → `window.API_BASE_URL` (501 hatası kök nedeni)
- ✅ **Auth token düzeltme:** `localStorage.getItem('token')` → `'access_token'`
- ✅ **Kısa kaynak validation bypass:** source_len < 500 char durumunda halüsinasyon kontrolü atlanıyor

**🤔 İlgisiz İçerik Filtreleme — `[NO_MATCH]` Token Yaklaşımı:**
- ✅ **LLM Prompt direktifi:** Kural 11 — bilgi yoksa cevabın başına `[NO_MATCH]` tokeni yazılıyor
- ✅ **Backend `[NO_MATCH]` kontrolü:** Token tabanlı %100 güvenilir ilgisizlik algılama
- ✅ **Marker yedek filtre:** Token gelmezse 12 Türkçe ilgisizlik ifadesi ile fallback kontrol
- ✅ **Streaming buffer:** İlk 15 token buffer'lanıyor — `[NO_MATCH]` tespit edilirse kullanıcıya token gönderilmeden durdurulur
- ✅ **"Vyra ile Sohbet Et" butonu:** İlgisiz sonuçlarda Corpix sohbet moduna geçiş (mor gradient buton)
- ✅ **`no_relevant_result` metadata:** Frontend'te ilgisizlik durumu algılanıp uygun buton gösteriliyor

**⚡ CatBoost Bypass İyileştirme:**
- ✅ **Minimum içerik uzunluğu:** 80 → 300 karakter (kısa chunk'lar LLM sentezlemeye yönlendirilir)

**🧠 ML Training Grounding Düzeltme:**
- ✅ **Dinamik grounding eşiği:** Chunk uzunluğuna göre (< 200 char → 0.05, < 500 → 0.10, ≥ 500 → 0.15)

---

### 🆕 v2.52.0 (2026-03-05) - ML Pipeline Quality + UPSERT + Stem Matching

**🧠 ML Training Kalite İyileştirme:**
- ✅ **Intent-bazlı zengin prompt:** Deep Think `_get_format_instruction()` mantığı Learned QA üretimine entegre
- ✅ **Asenkron per-question mimari:** Her soru bağımsız task olarak işlenir (hata izolasyonu)
- ✅ **Streaming LLM:** `call_llm_api_stream()` ile timeout riski azaltıldı
- ✅ **Tam chunk context:** 600 char limiti kaldırıldı, 2000 char'a çıkarıldı
- ✅ **Post-processing:** Prompt leak temizleme + format düzeltme
- ✅ **Refinement:** 2. LLM çağrısıyla cevap iyileştirme (kısaltma yasak, sadece zenginleştir)

**🔄 UPSERT + Kalite Koruma:**
- ✅ **`add()` → UPSERT:** Eski cevap varsa kalite skoru karşılaştır, daha iyiyse güncelle
- ✅ **`_compute_answer_quality_score()`:** LLM gerektirmeyen statik kalite ölçümü (0-100)
- ✅ **Kalite kriterleri:** Uzunluk (30p), adım yapısı (25p), format zenginliği (25p), kelime çeşitliliği (20p)
- ✅ **Connection leak fix:** `add()` fonksiyonuna `finally` bloğu eklendi
- ✅ **Dead code temizliği:** `_get_existing_questions()` kaldırıldı

**🎯 GENERAL Intent Scoring Düzeltme:**
- ✅ **Kök eşleştirme (stem matching):** Türkçe çekim eki toleransı (`_stem_match()`)
- ✅ **Grounding eşiği:** 0.30 → 0.15 (stem matching ile)
- ✅ **Relevance eşiği:** 0.40 → 0.25 (stem matching ile)
- ✅ **Intent korunması:** Düşük grounding'li sorular GENERAL'e zorlanmıyor

**📊 Training Samples UX İyileştirme:**
- ✅ **`has_learned_answer`:** EXISTS subquery (duplicate row riski yok)
- ✅ **Cevap ikonu:** ✅ cevap var, ⏳ henüz üretilmedi, — cevap yok

**📁 Değişen Dosyalar:**
- `app/services/learned_qa_service.py` — UPSERT, kalite koruma, per-question mimari
- `app/services/ml_training/synthetic_data.py` — Stem matching, grounding iyileştirme
- `app/api/routes/system.py` — EXISTS subquery, has_learned_answer
- `frontend/assets/js/modules/ml_training.js` — Cevap ikonu mantığı
- `frontend/assets/css/home.css` — pending/ready CSS

**🧪 Test:** 507/507 PASSED — 5 yeni UPSERT testi

---

### 🆕 v2.51.1 (2026-03-04) - CL Soru Kalitesi + Cevap Önizleme

**🎯 CL Sentetik Soru Kalitesi İyileştirme:**
- ✅ **Dosya bağlam bilgisi:** LLM promptuna `Dosya: Komutlar.xlsx` eklendi — sorular dosya konusuyla sınırlı
- ✅ **Halüsinasyon eşiği %20 → %40:** `_validate_question_relevance()` daha sıkı filtreleme
- ✅ **Post-generation grounding:** `_estimate_grounding()` — %30 altı uyumluluk → negatife düşürülür

**👁️ Eğitim Örnekleri Cevap Önizleme:**
- ✅ **Cevap sütunu:** Skor sağında yeni "Cevap" kolonu (score ≥ 0.70 + pozitif eşleşme)
- ✅ **`GET /ml/learned-answer`:** Soru bazlı öğrenilmiş cevap lookup endpoint
- ✅ **VyraModal:** Cevap preview (soru + cevap + kalite skoru + kullanım sayısı)
- ✅ **XSS koruması:** `escapeHtml(data.answer)` — LLM çıktısı sanitize

**🔑 Login & Sistem Sıfırlama:**
- ✅ **Turkcell AD otomatik seçim:** Login dropdown'da Turkcell Active Directory varsayılan olarak seçili
- ✅ **Reset genişletme:** `document_images` (411) + `learned_answers` (204) tabloları sıfırlamaya eklendi

**📁 Değişen Dosyalar:**
- `app/services/ml_training/synthetic_data.py` — 3 katmanlı kalite filtresi
- `app/api/routes/system.py` — `/ml/learned-answer` endpoint + reset genişletme
- `frontend/assets/js/modules/ml_training.js` — Cevap kolonu + `showSampleAnswer()`
- `frontend/assets/js/login.js` — LDAP domain auto-select
- `frontend/assets/css/home.css` — `.sample-answer-btn` + `.learned-answer-preview` stiller

**🧪 Test:** 475/475 PASSED — 0 regresyon

---

### 🆕 v2.51.0 (2026-03-04) - Learned Q&A Cache + Vyra Önerisi

**🧠 Learned Q&A Cache (Tier 1):**
- ✅ **`learned_answers` tablosu:** Öğrenilmiş soru-cevap çiftleri (embedding ile semantik arama)
- ✅ **`LearnedQAService`:** `search()` → cosine similarity ~100ms, `bulk_generate()` → LLM batch cevap üretimi
- ✅ **CL entegrasyonu:** Step 8 — eğitim sonrası otomatik Q&A üretimi (max 50/cycle)
- ✅ **Deep Think Tier 1:** Cache → **Learned QA** → CatBoost Bypass → LLM (4 katmanlı yanıt mimarisi)

**✨ Vyra Önerisi (Can Enhance):**
- ✅ **CatBoost bypass metadata:** `can_enhance: true` + `original_query` — frontend bilgilendirilir
- ✅ **`POST /{dialog_id}/messages/enhance`:** LLM ile cevabı iyileştirme endpoint'i
- ✅ **Frontend butonu:** "🪄 Vyra önerisi al" — gradient buton + spinner + success animasyonu
- ✅ **DB güncelleme:** Orijinal mesaj enhanced content ile güncellenir, cache invalidate

**📁 Yeni Dosyalar:**
- `app/services/learned_qa_service.py` — LearnedQAService (search, add, bulk_generate)

**📁 Değişen Dosyalar:**
- `app/core/schema.py` — `learned_answers` tablosu
- `app/services/ml_training/continuous_learning.py` — Step 8 Q&A üretimi
- `app/services/deep_think_service.py` — Tier 1 lookup (process + process_stream)
- `app/api/routes/dialog.py` — `/enhance` endpoint
- `frontend/assets/js/modules/dialog_chat.js` — `handleEnhance()` + buton render
- `frontend/assets/css/dialog-chat.css` — Vyra enhance buton stilleri

**🧪 Test:** 62/62 PASSED — 0 regresyon

---

### 🆕 v2.50.0 (2026-03-04) - Performance Optimization (3 Faz)

**⚡ Faz 1: LLM Streaming (SSE):**
- ✅ **Token-by-token yanıt:** `call_llm_api_stream()` ile LLM yanıtları SSE üzerinden streaming
- ✅ **Deep Think streaming pipeline:** `process_stream()` — RAG + CatBoost + LLM synthesis akışı
- ✅ **SSE endpoint:** `POST /{dialog_id}/messages/stream` — `StreamingResponse` ile
- ✅ **Frontend streaming UI:** `handleSendMessage()` fetch ile SSE okuma + cursor animasyonu
- ✅ **Event türleri:** `rag_complete`, `token`, `cached`, `done`, `saved`, `error`

**🗄️ Faz 2: Redis Persistent Cache:**
- ✅ **RedisCache sınıfı:** `redis_cache.py` — MemoryCache ile aynı interface, pickle serialization
- ✅ **Deep Think cache → Redis:** Sunucu restart'ta cache korunur (1 saat TTL)
- ✅ **Otomatik fallback:** Redis yoksa in-memory fallback — sıfır risk
- ✅ **Config:** `REDIS_URL` ayarı `.env`'den okunabilir

**🤖 Faz 3: CatBoost Direct Answer:**
- ✅ **LLM bypass:** `combined_score ≥ 0.75` ve içerik ≥ 80 char → LLM atlanır
- ✅ **Batch + streaming:** Hem `process()` hem `process_stream()`'e bypass eklendi
- ✅ **Cache entegrasyonu:** Bypass sonuçları da cache'e kaydedilir
- ✅ **Log:** `"CatBoost BYPASS"` mesajıyla log'da görünür

**🧪 Test:** 62/62 PASSED (7 streaming + 33 deep_think + 22 dialog) — 0 regresyon

**📁 Yeni Dosyalar:**
- `app/core/redis_cache.py` — Redis-backed cache (fallback: in-memory)
- `tests/test_llm_streaming.py` — 7 streaming unit test

**📁 Değişen Dosyalar:**
- `app/core/llm.py` — `call_llm_api_stream()`
- `app/services/deep_think_service.py` — `process_stream()` + CatBoost bypass
- `app/api/routes/dialog.py` — SSE streaming endpoint
- `app/services/dialog/processor.py` — `process_user_message_stream()`
- `app/core/cache.py` — deep_think cache → RedisCache
- `app/core/config.py` — `REDIS_URL`, v2.50.0
- `frontend/assets/js/modules/dialog_chat.js` — Streaming fetch + 4 helper
- `frontend/assets/css/dialog-chat.css` — Streaming cursor animasyonu

---

### 🆕 v2.49.1 (2026-03-04) - Past Solutions Image Rendering & RAG Score Badge

**🖼️ Geçmiş Çözümler Görselleri (P0):**
- ✅ **Metadata-based image render:** Görseller artık `metadata.image_ids`'den direkt render ediliyor
- ✅ **Img link temizliği:** Content'teki raw `<img>` tag metinleri kaldırıldı — gereksiz linkler yok
- ✅ **API URL rewrite:** Görseller için `apiBase` ile absolute URL otomatik oluşturuluyor

**🎯 RAG Score Badge (P1):**
- ✅ **best_score metadata:** Deep Think ve legacy RAG akışlarında `best_score` metadata'ya eklendi
- ✅ **Frontend badge:** Skor > 0 ise bullseye ikonu ile mesaj-meta alanında gösterim

**🔧 Deep Think Formatter (P2):**
- ✅ **Img tag koruması:** `_inlineFormat()` fonksiyonunda img tag'leri `escapeHtml`'den korunuyor
- ✅ **Genişletilmiş img tespiti:** `startsWith` → `includes('<img ')` — satır içi img'ler de yakalanıyor
- ✅ **Default paragraf dalı:** Img kontrolü eklendi

**🧹 Test Düzeltmeleri:**
- ✅ `test_api_auth.py` — `full_name` min_length=2 uyumu
- ✅ `test_api_organizations.py` — `page`/`per_page` default int değerleri
- ✅ `test_api_user_admin.py` — `result['roles']` dict key erişimi
- ✅ Unused import temizliği (timedelta, asyncio)
- ✅ **468/468 test PASSED**

### 🆕 v2.48.0 (2026-03-04) - Production Hardening & Bare-Metal Deployment

**🌐 Frontend URL Dinamikleştirme (P0):**
- ✅ **Merkezi config.js:** Tüm API/WebSocket URL'leri `window.API_BASE_URL` üzerinden dinamik
- ✅ **Port-bazlı ortam tespiti:** Port 5500 → dev, Port 80/443 → production (Nginx)
- ✅ **20+ JS dosyası refactor:** Hardcoded `localhost:8002` → dinamik URL

**🔒 Güvenlik Sıkılaştırmaları (P0):**
- ✅ **CORS config-driven:** `.env` dosyasından `CORS_ORIGINS` okunuyor, `null` origin kaldırıldı
- ✅ **Swagger/ReDoc kapalı:** Production'da (`debug=False`) API belgeleri devre dışı
- ✅ **Admin şifre log kaldırıldı:** Default admin şifresi artık log'a yazılmıyor
- ✅ **Pydantic model_validator:** CORS origin birleştirme `__init__` → `model_validator(mode='after')`

**🚀 Bare-Metal Deployment (P1):**
- ✅ **Nginx reverse proxy:** `deploy/nginx/vyra.conf` — API proxy, WebSocket, statik dosya, güvenlik header'ları
- ✅ **`canlida_calistir.bat`:** Tek tıkla production başlatma (venv + pip + Nginx + PostgreSQL + Uvicorn)
- ✅ **`canlida_durdur.bat`:** Tek tıkla güvenli durdurma
- ✅ **`deploy/setup_nginx.ps1`:** Otomatik Nginx indirme ve kurulum
- ✅ **`deploy/start_production.ps1`:** 4 aşamalı orchestration (DB → Migration → Backend → Nginx)
- ✅ **`deploy/stop_production.ps1`:** Sıralı güvenli kapatma
- ✅ **`deploy/DEPLOYMENT_GUIDE.md`:** Step-by-step Windows Server rehberi

**🎨 Kod Kalitesi:**
- ✅ **Inline CSS temizlendi:** `organization_management.html` → CSS class'a taşındı
- ✅ **Favicon relative path:** `home.html`, `login.html` — absolute → relative

---

### 🆕 v2.47.0 (2026-03-03) - Güvenlik Denetimi & Input Validation

**🛡️ SQL Injection Güvenlik Denetimi:**
- ✅ **LIMIT/OFFSET parametrize:** `rag_files.py`, `user_admin.py` — f-string yerine `%s` placeholder
- ✅ **Hata bilgi sızıntısı maskeleme:** 11 dosyada 30 yerde `detail=str(e)` → genel mesaj
- ✅ **Least Privilege DB:** `vyra_app` kullanıcısı — sadece DML (SELECT/INSERT/UPDATE/DELETE), DDL yetkisi yok

**✅ Input Validation (Pydantic Field + Query Params):**
- ✅ **Auth modelleri:** username regex, password min/max, email max 254
- ✅ **Profil/Şifre:** full_name 2-150, şifre min 6 karakter
- ✅ **LLM Config:** temperature 0-2, top_p 0-1, timeout 1-300
- ✅ **Prompts:** title max 200, content max 50K
- ✅ **Query params:** page/per_page/search sınırları (3 dosya)
- ✅ **System:** ScheduleItem whitelist regex, CLConfig interval 1-1440

**🎨 Yetkilendirme Paneli İyileştirmeler:**
- ✅ **Pasife alma modern modal:** native `confirm()` → glassmorphism SaaS modal + ESC desteği
- ✅ **Route düzeltmeleri:** `toggle-active` ve `roles` endpoint çift prefix sorunu çözüldü
- ✅ **XSS koruması:** Modal içi username HTML entity escape

---

### 🆕 v2.46.0 (2026-03-03) - LDAP/Active Directory Entegrasyonu

**🔐 Dual-Auth (LDAP + Lokal):**
- ✅ **LDAP kimlik doğrulama:** 3 adımlı auth (Service Bind → User Search → User Bind) + Direct Bind Fallback
- ✅ **Lokal auth:** Sadece admin kullanıcılar için lokal login
- ✅ **Domain dropdown:** Login ekranında aktif LDAP domain seçimi
- ✅ **Otomatik kullanıcı oluşturma:** LDAP'tan doğrulanan kullanıcılar otomatik oluşturulup onaylanıyor (role=user)
- ✅ **Organizasyon erişim kontrolü:** `allowed_orgs` listesiyle yetkisiz org'lar engelleniyor

**🛡️ Güvenlik:**
- ✅ **AES-256 Fernet şifreleme:** LDAP bind password'ları veritabanında şifreli saklanıyor (`encryption.py`)
- ✅ **XSS koruması:** Admin paneli LDAP tablo render'ında HTML escape
- ✅ **Safe password handling:** LDAP kullanıcısı lokal login denerse crash engellenmiş

**⚙️ Admin Panel — LDAP Yönetimi:**
- ✅ **CRUD API:** LDAP sunucu ayarları oluşturma, güncelleme, silme (soft delete)
- ✅ **3 aşamalı bağlantı testi:** TCP → LDAP Server Init → Service Bind
- ✅ **Modern SaaS UI:** LDAP Ayarları sekmesi, sunucu listesi tablosu, ayar modal

**🔄 Organizasyon Senkronizasyonu:**
- ✅ **Otomatik org oluşturma:** LDAP'tan gelen yeni organizasyonlar `organization_groups` tablosuna ekleniyor
- ✅ **Kullanıcı-org ataması:** LDAP kullanıcıları ilgili org grubuna atanıyor

**🧪 Test:** 468 test (31 auth + LDAP) → 0 failure ✅

**📁 Yeni Dosyalar:**
- `app/core/encryption.py` — AES-256 Fernet şifreleme servisi
- `app/services/ldap_auth.py` — LDAP authentication servisi (491 satır)
- `app/api/routes/ldap_settings.py` — LDAP Settings CRUD API (300 satır)
- `frontend/assets/js/modules/ldap_settings.js` — Admin panel LDAP modülü
- `frontend/assets/css/modules/ldap_settings.css` — LDAP stilleri
- `tests/test_ldap_auth.py` — 15 unit test

**📁 Değişen Dosyalar:**
- `app/api/routes/auth.py` — Dual-auth branching, LDAP helpers, `/ldap-domains` endpoint
- `app/api/main.py` — LDAP settings router kaydı
- `app/core/schema.py` — `ldap_settings` tablosu, `users` LDAP alanları (auth_type, domain, department, title, organization, last_login)
- `frontend/login.html` — Domain dropdown
- `frontend/assets/js/login.js` — Domain yükleme/gönderme
- `frontend/assets/css/login.css` — Domain select stili
- `frontend/partials/section_parameters.html` — LDAP Ayarları sekmesi
- `frontend/assets/js/modules/param_tabs.js` — Tab switch desteği
- `frontend/build.mjs` — LDAP CSS/JS bundle
- `requirements.txt` — `ldap3`, `cryptography`

---

### 🔧 v2.45.1 (2026-02-16) - Alakasız Görsel Filtreleme Fix

- ✅ **Primary Source Image Filtering:** Görseller artık sadece en yüksek skorlu kaynak dosyadan (primary source) alınıyor
- ✅ **DB İlişkisi Kullanımı:** `rag_chunks.file_id → uploaded_files ← document_images.file_id` ilişkisi ile kesin eşleştirme
- ❌ **Kaldırılan:** Heuristik skor filtresi (≥0.50) — yerine kaynak dosya bazlı kesin filtreleme
- **Dosya:** `app/services/deep_think_service.py` satır 561-618

---

### 🆕 v2.45.0 (2026-02-16) - CL Interval Fix + Countdown Timer + Manuel Eğitim LLM

**⏱️ Sürekli Öğrenme (CL) Interval Fix:**
- ✅ **DB'den interval okuma:** `get_continuous_learning_service()` singleton'ı artık `system_settings` tablosundan `cl_interval_minutes` okuyor — restart sonrası korunuyor
- ✅ **`_thread_start_time` tracking:** Servis `start()` edildiğinde timestamp kaydediliyor — ilk çalışma için de ISO tarih hesaplanıyor

**⏲️ Countdown Timer (Sonraki Çalışma):**
- ✅ **MM:SS geri sayım:** `startNextRunCountdown()` fonksiyonu ile sonraki çalışma zamanına geri sayım
- ✅ **CSS animasyonu:** Monospace font, mavi arka plan, "Çalışıyor..." animasyonlu state
- ✅ **Edge case:** `isNaN(targetTime)` koruması, servis durma durumu, "Yakında..." fallback

**🤖 Manuel Eğitim LLM Desteği (`train_model.py` v2.0):**
- ✅ **SyntheticDataGenerator:** LLM destekli sentetik veri üretimi (halüsinasyon koruması dahil)
- ✅ **FeatureExtractor:** Gerçek 15 feature (6 placeholder kaldırıldı)
- ✅ **Adversarial koruma:** Şüpheli negatif feedback filtreleme
- ✅ **CatBoostClassifier:** Regressor → Classifier geçişi (CL ile aynı)
- ✅ **Training samples kaydı:** `ml_training_samples` tablosuna yazım
- ✅ **Topic refinement:** Eğitimden keyword güncelleme
- ✅ **Hot-swap:** Model eğitimi sonrası servis anında güncelleme
- ✅ **CLI:** `--no-llm`, `--max-chunks`, `--dry-run` parametreleri

**🎨 Dialog Chat UI Fix:**
- ✅ **Özet wrap fix:** `📋 Özet:` artık `dt-section` olarak render ediliyor — `white-space: nowrap` kesilme sorunu çözüldü
- ✅ **OCR tooltip fix:** Tooltip `document.body`'ye taşındı — `overflow-x: hidden` parent kesme sorunu çözüldü
- ✅ **Tooltip iyileştirmesi:** `position: fixed`, ekran taşma kontrolü, amber border, z-index 9999, min-width 280px

**📁 Değişen Dosyalar:**
- `app/services/ml_training/continuous_learning.py` — `_thread_start_time`, DB interval, get_status ISO tarih
- `frontend/assets/js/modules/ml_training.js` — `startNextRunCountdown()`, countdown state
- `frontend/assets/css/home.css` — `.cl-countdown`, `.cl-countdown.running` stilleri
- `scripts/train_model.py` — v2.0 LLM destekli tam yeniden yazım
- `frontend/assets/js/modules/dialog_chat_utils.js` — Özet catHeader→section render
- `frontend/assets/js/modules/rag_ocr_popup.js` — Tooltip body'ye taşıma, fixed positioning
- `frontend/assets/css/modules/rag_image_lightbox.css` — Tooltip z-index, min-width, amber border
- `frontend/assets/css/dialog-chat.css` — dt-section-value word wrap kuralları

---

### 🆕 v2.44.0 (2026-02-16) - CatBoost Öğrenme Kalitesi İyileştirmesi

**🤖 LLM Destekli Sentetik Veri:**
- ✅ **LLM soru üretimi:** Chunk içeriğine özel gerçekçi Türkçe sorular (template fallback korunuyor)
- ✅ **Zengin metadata:** heading, quality_score, topic_label DB'den gerçek değerlerle eğitim
- ✅ **Hard/Easy negatives:** Aynı topic farklı dosya + farklı topic'ten negatif örnekler
- ✅ **Skor çeşitlendirmesi:** Keyword overlap'a göre 0.55-0.95 arası dinamik skor

**🛡️ Halüsinasyon & Adversarial Feedback Koruması:**
- ✅ **LLM halüsinasyon filtresi:** Üretilen soruların %20+ keyword overlap kontrolü
- ✅ **Adversarial feedback koruması:** Negatif oy + yüksek benzerlik = şüpheli → eğitimden çıkar
- ✅ **Prompt güçlendirme:** "SADECE parçadaki bilgilere dayalı sorular üret" kuralı

**⚖️ Score Dengeleme & Feedback Entegrasyonu:**
- ✅ **Ağırlık dengeleme:** CatBoost/cosine 0.7/0.3 → 0.5/0.5
- ✅ **Gerçek feedback:** user_feedback tablosundan pozitif/negatif örnekler eğitime dahil
- ✅ **10 yeni test:** Halüsinasyon, adversarial, negatif örnek seçimi, skor çeşitlendirme

### 🆕 v2.43.0 (2026-02-16) - RAG Document Processing Enhancement

**📄 Faz 2: PyMuPDF Font-Aware Heading Detection:**
- ✅ **Font-level heading:** PyMuPDF ile font size, bold, italic bilgileri kullanılarak heading tespiti
- ✅ **Otomatik heading level:** Font boyutuna göre H1-H3 level belirleme
- ✅ **Regex fallback:** Mevcut regex tabanlı heading tespiti korunuyor

**🗂️ Faz 3: Heading Hiyerarşi (Breadcrumb Path):**
- ✅ **`heading_path`:** PDF ve DOCX'te heading hiyerarşi breadcrumb (`["Bölüm 1", "Alt Bölüm 1.1"]`)
- ✅ **`heading_level`:** Her chunk'ta heading seviye bilgisi (1-3)
- ✅ **Heading stack:** Aynı/üst seviye heading gelince stack sıfırlanarak doğru path korunuyor

**📊 Faz 5: Tablo Yapısal Metadata (DOCX + PDF):**
- ✅ **`table_id`, `column_headers`, `row_count`:** Tablo chunk'larında yapısal bilgiler
- ✅ **Heading context:** Tablolar son heading bağlamını miras alıyor

**🧹 Faz 6: Header/Footer Temizleme + TOC Tespiti (PDF):**
- ✅ **`_clean_header_footer_blocks`:** %50+ sayfa tekrarı olan kısa metinler otomatik filtreleniyor
- ✅ **Sayfa numarası temizleme:** `"1"`, `"Sayfa 1"`, `"- 1 -"` formatları otomatik kaldırılıyor
- ✅ **`_detect_toc_section`:** İçindekiler bölümü `type: toc` olarak işaretleniyor

**🔁 Faz 7: Chunk Deduplication + Quality Score:**
- ✅ **`_deduplicate_chunks`:** Cosine similarity 0.95+ ile dosya-içi duplicate chunk tespiti
- ✅ **`_cross_file_deduplicate`:** Farklı dosyalardaki duplicate chunk tespiti (DB son 1000 chunk)
- ✅ **Hızlı ön-filtre:** Uzunluk %30+ farklıysa similarity hesaplanmıyor (performans)
- ✅ **Bilgi yoğunluğu:** Keyword diversity (+0.1), entity density (+0.05)
- ✅ **Bağlam bütünlüğü:** Heading-içerik keyword overlap bonusu (+0.1)
- ✅ **Quality score ceza:** TOC -0.3, dil karışıklığı -0.1, düşük diversity -0.05

**🖼️ Faz 4: Görsel-Chunk Eşleme (PDF + DOCX):**
- ✅ **`_extract_image_positions_fitz`:** PyMuPDF ile sayfa bazlı görsel pozisyonu çıkarma
- ✅ **`image_refs` metadata:** Görsel bulunan sayfadaki chunk'lara otomatik görsel referansları
- ✅ **DOCX görsel tespiti:** XML namespace tabanlı heading-image eşlemesi

**🧪 Unit Testler:**
- ✅ **91 test** — `test_pdf_processor.py` (30), `test_docx_processor.py` (11), `test_rag_service.py` (50)
- ✅ Tüm testler başarılı

**📁 Yeni Dosyalar:**
- `tests/test_pdf_processor.py` — PDF processor unit testleri
- `tests/test_docx_processor.py` — DOCX processor unit testleri

**📁 Değişen Dosyalar:**
- `app/services/document_processors/pdf_processor.py` — Faz 2,3,5,6 iyileştirmeleri
- `app/services/document_processors/docx_processor.py` — Faz 3,5 heading + tablo metadata
- `app/services/rag/service.py` — Faz 7 dedup + quality score
- `app/api/routes/rag_upload.py` — Faz 1 async run_in_executor
- `app/core/config.py` — v2.43.0 versiyon güncelleme
- `tests/test_rag_service.py` — Dedup + quality score testleri eklendi

---

### 🆕 v2.42.0 (2026-02-15) - Crash Recovery + Org Modal Fix + Memory Management

**🛡️ Crash Recovery Guard:**
- ✅ **Startup recovery:** Uygulama başladığında `processing` durumundaki orphan dosyalar otomatik `failed` olarak güncelleniyor
- ✅ **`_recover_stuck_files()`** fonksiyonu `main.py` lifespan'a eklendi

**🔧 Org Edit Modal Fix:**
- ✅ **Fallback API fetch:** `this.orgs` boş/undefined olduğunda org listesi otomatik API'den yeniden yükleniyor
- ✅ **Async delegation:** `openFileOrgEditModal` async olarak güncellendi

**🧹 Memory Management (Büyük Dosyalar):**
- ✅ **Processing sonrası cleanup:** `file_content` byte dizisi None olarak ayarlanıp `gc.collect()` tetikleniyor
- ✅ **Batch embedding:** 50'şerli batch'ler ile embedding üretimi — 100+ chunk dosyalarda bellek taşması önleniyor
- ✅ **`EMBEDDING_BATCH_SIZE = 50`** class constant olarak `RAGService`'e eklendi

**📁 Değişen Dosyalar:**
- `app/api/main.py` — `_recover_stuck_files()` startup guard
- `app/api/routes/rag_upload.py` — Memory cleanup + GC
- `app/services/rag/service.py` — Batch embedding desteği
- `frontend/assets/js/modules/rag_file_org_edit.js` — Async fallback fetch
- `frontend/assets/js/rag_upload.js` — Async delegation güncelleme

---

### 🆕 v2.41.0 (2026-02-15) - Alembic Migration & Frontend Build Pipeline

**🗄️ Faz 1: Alembic Migration Sistemi:**
- ✅ **Alembic kurulumu:** `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako` oluşturuldu
- ✅ **Baseline migration:** `001_baseline.py` — 22 tablo, 80+ index, varsayılan veriler
- ✅ **`init_db()` refactor:** Önce Alembic migration, başarısızlıkta SCHEMA_SQL fallback
- ✅ **Circular FK fix:** `organization_groups.created_by → users(id)` — tablo sırası düzeltildi (`roles → users → organization_groups`)

**⚡ Faz 2: Frontend Build Pipeline (esbuild):**
- ✅ **Bundle:** 15 CSS → `bundle.min.css`, 43 JS → `bundle.min.js`
- ✅ **Boyut azaltma:** CSS: 314KB → 192KB (%39↓), JS: 644KB → 335KB (%48↓)
- ✅ **HTTP istekleri:** 58 → 3 (dramatik azalma)
- ✅ **Bundle sıralama fix:** `ticket_history.js` alt modüllerden önce yükleniyor (`dateRangeBtn` ReferenceError çözüldü)
- ✅ **Watch mode desteği:** `npm run watch` ile geliştirme sırasında otomatik rebuild

**🔄 Sistem Sıfırlama İyileştirmesi:**
- ✅ **`ml_training_schedules`** reset kapsamına eklendi (26/26 tablo kapsanıyor)

**🧹 Kod Kalitesi:**
- ✅ **`env.py`:** Unused `text` import kaldırıldı (pyflakes)
- ✅ **Dependency:** `alembic` paketi `.venv`'e kuruldu

**📁 Yeni Dosyalar:**
- `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/001_baseline.py`
- `frontend/package.json`, `frontend/build.mjs`

**📁 Değişen Dosyalar:**
- `app/core/db.py` — `_run_alembic_migration()` + `init_db()` dual strategy
- `app/api/routes/system.py` — `ml_training_schedules` reset eklendi
- `frontend/home.html` — Bundle dosyaları referansı
- `requirements.txt` — `alembic` eklendi
- `.gitignore` — `node_modules/`, `frontend/dist/`

---

### 🆕 v2.40.0 (2026-02-13) - Görsel Pozisyonlama & DRY Refactoring

**🖼️ Paragraf-Pozisyon Bazlı Görsel Yerleştirme:**
- ✅ **`paragraph_index` & `page_y_position`:** PDF/DOCX'ten çıkarılan görsellere orijinal konumları kaydediliyor
- ✅ **Paragraflar arası yerleştirme:** Görseller artık bölüm sonuna topluca değil, orijinal sırasına göre paragraflar arasına yerleştiriliyor (DOCX + PDF rendering)
- ✅ **Inline görsel koruma:** `_update_paragraph_text` orijinal DOCX'teki görselleri asla silmiyor (WML+WP namespace kontrolü)

**🏗️ DRY Refactoring (Ortak Yardımcı Fonksiyonlar):**
- ✅ **`_get_section_text(section)`:** Section metin alma — None-safe, `@staticmethod`
- ✅ **`_map_images_to_sections(sections, images)`:** Heading + chunk_index eşleştirmesi, bölüm içi relative pozisyon hesaplama — tek kaynak
- ✅ **`_organize_images_at_positions(sec_imgs, total)`:** Paragraf dict oluşturma, bounds-safe — tek kaynak
- ✅ **~110 satır tekrarlanan kod kaldırıldı** (`_create_fresh_docx` + `_create_fresh_pdf` birleştirildi)

**📐 `para_start`/`para_end` Tutarlılığı (Tüm Extract Fonksiyonları):**
- ✅ **`_extract_docx_sections`** — paragraf aralığı zaten vardı
- ✅ **`_split_text_by_headings`** — PDF/TXT akışı, satır bazlı aralık eklendi
- ✅ **`_extract_xlsx_sections`** — sheet başına satır aralığı eklendi
- ✅ **`_extract_pptx_sections`** — slayt başına paragraf aralığı eklendi

**🧪 Test:** 83 birim testi (10 yeni) → 0 failure ✅

**📁 Değişen Dosyalar:**
- `app/services/document_enhancer.py` — 3 yeni yardımcı fonksiyon, 4 extract fonksiyonu güncellendi
- `app/services/document_processors/image_extractor.py` — `paragraph_index`, `page_y_position` eklendi
- `tests/test_document_enhancer.py` — `TestHelperFunctions` (10 yeni test)

---

### 🔧 v2.39.0 (2026-02-12) - Asenkron RAG Upload

**🔄 Asenkron Dosya İşleme:**
- ✅ **Background Processing:** Dosya yükleme artık UI'ı bloke etmeden arkaplanda işleniyor (`asyncio.ensure_future`)
- ✅ **WebSocket Bildirimleri:** `rag_upload_complete` / `rag_upload_failed` mesajları ile gerçek zamanlı geri bildirim
- ✅ **Status Takibi:** `uploaded_files` tablosuna `status` sütunu (`processing`/`completed`/`failed`)
- ✅ **Processing Spinner:** Dosya listesinde işlenen dosyalar animasyonlu spinner + pulse efekti
- ✅ **Bildirim Navigasyonu:** Bildirim tıklandığında Bilgi Tabanı sekmesine yönlendirme (`navigateToRag`)
- ✅ **Browser Notification:** Sayfa arka plandayken tarayıcı bildirimi

---

### 🔧 v2.38.4 (2026-02-12) - Pyflakes Temizlik & DB Log Sütun Fix

**🧹 Statik Analiz Temizliği (15 dosya, 34+ bulgu → 0 uyarı):**
- ✅ **Unused Imports (~18):** `json`, `sys`, `subprocess`, `WebSocketDisconnect`, `UploadFile`, `File`, `BinaryIO`, `Path`, `BytesIO`, `re`, `io`, `Optional`, `Any`, `List`, `timedelta` vb. kaldırıldı
- ✅ **f-string Placeholder (4):** `db.py`, `maturity_analyzer.py`, `response_builder.py` — interpolation olmayan f-string'ler normal string'e dönüştürüldü
- ✅ **Unused Variables (4):** `maturity_analyzer.py` — `shape_count`, `nsmap`, `etree`, `first_row_text` temizlendi
- ✅ **feature_extractor.py:** `heading` değişkeni `has_heading_match` feature olarak CatBoost'a besleniyor

**🛢️ DB system_logs Sütun Fix:**
- ✅ **Root Cause:** HTTP middleware `log_system_event()` kullanıyordu → `request_path`, `request_method`, `response_status` sütunları NULL
- ✅ **Fix:** Middleware artık `log_request()` fonksiyonunu kullanıyor → sütunlar doğru dolduruluyor
- ✅ **Yavaş İstek Uyarısı:** >2s süreli istekler için ayrıca WARNING logu eklendi

---

### 🔧 v2.38.3 (2026-02-12) - RAG Search Kalite İyileştirmesi

**🔍 RAG Arama Kalitesi — TOC Domination Fix:**
- ✅ **Root Cause:** İçindekiler tablosu (TOC) chunk'ları her anahtar kelimeyi içerdiği için BM25'te en yüksek skoru alıyor, asıl içerik chunk'larını sonuçlardan eliyordu
- ✅ **`_is_toc_chunk()`:** TOC chunk algılama fonksiyonu — yoğun nokta deseni (`\\.{5,}`) ve sayfa referansı kontrolü
- ✅ **`_preprocess_query()`:** Türkçe soru ekleri temizleme (`nelerdir`, `nedir`, `nasıl yapılır` vb.) — embedding benzerliğini artırır
- ✅ **TOC ceza sistemi (3 katman):** BM25 %70 ceza + Final skor %50 ceza + Exact match bonus engelleme
- ✅ **Skor farkı eşiği:** `SCORE_GAP_THRESHOLD` 10→25 — normalizasyon sonrası daha fazla ilgili sonuç geçsin
- 📈 **Sonuç:** "Atama Türleri nelerdir?" sorgusu 1 sonuç (TOC) → 3 sonuç (gerçek içerik)

---

### 🔧 v2.38.2 (2026-02-11) - Image Serve 404 Fix

**🐛 Kritik Bug Fix — Görsel Servis Hatası:**
- ✅ **Root Cause:** Split-port mimarisinde (Frontend:5500 / Backend:8002) `<img src="/api/rag/images/{id}">` relative URL'ler frontend static server'a yönleniyordu → 404
- ✅ **`dialog_chat_utils.js`:** `_rewriteApiUrls()` fonksiyonu eklendi — tüm `/api/` prefixed img src'leri absolute backend URL'e dönüştürür
- ✅ **`rag_ocr_popup.js`:** `API_BASE` düzeltmesi — `window.location.origin` (port 5500) yerine backend port detection (8002) kullanılıyor

---

### 🔧 v2.38.1 (2026-02-11) - /confirm Code Review & Bug Fixes

**🐛 Kritik Bug Fix:**
- ✅ **Fallback rag_results:** `_single_synthesis` ve `_chunked_synthesis` artık `rag_results`'ı `_fallback_response`'a aktarıyor (önceden `[]` gönderiliyordu → LLM hatası durumunda "sonuç bulunamadı" yerine RAG içeriği gösterilir)

**🔧 Test & Kalite:**
- ✅ **Mock fix:** `test_pdf_conversion_fallback_on_error` — `patch('fpdf.FPDF')` → `patch.object(DocumentEnhancer, '_create_fresh_pdf')` (ModuleNotFoundError düzeltmesi)
- ✅ **Pyflakes cleanup:** `rag_upload.py` f-string placeholder uyarıları, `test_document_enhancer.py` unused MagicMock import

**🧪 Test:** 262 passed, 0 failed ✅

---

### 🔧 v2.38.0 (2026-02-11) - Deep Think & OCR Pipeline İyileştirmeleri

**🆕 CSS Responsive Fix:**
- ✅ **Overflow koruması:** `.message-bubble` min-width, `.dt-response` word-break/overflow kuralları eklendi
- ✅ **Code/Table overflow:** `pre`, `code`, `table` elementleri için max-width ve wrap kuralları

**🆕 LLM Context Zenginleştirme:**
- ✅ **Heading bilgisi:** `_prepare_context` artık metadata heading'i `Bölüm: X` olarak LLM'e aktarıyor
- ✅ **Detaylı yanıt:** Fallback prompt güncellemesi — daha kapsamlı ve organize yanıtlar
- ✅ **Parçalı synthesis:** 12000+ karakter context otomatik olarak parçalanıp LLM ile birleştiriliyor

**🆕 Image-Chunk Eşleştirme Düzeltmesi:**
- ✅ **Heading bazlı:** `_update_chunk_image_refs` chunk_index yerine `metadata->>'heading'` eşleştirme
- ✅ **Fallback:** Heading'siz görseller ilk chunk'a atanır

**🆕 OCR & PDF İyileştirmeleri:**
- ✅ **OCR error logging:** Batch OCR hatalarında detaylı loglama + 0/N uyarısı
- ✅ **Türkçe cümle bölme:** PDF `_split_large_section` regex ile cümle sınırlarında bölme

**🧪 Test:** 85 test (78 mevcut + 7 yeni) → 0 failure

---

### 🔧 v2.37.0 (2026-02-11) - Chunklama Kalitesi & Görsel-Başlık İlişkilendirme

**🆕 Chunk Kalite İyileştirmeleri:**
- ✅ **Chunk boyutu artırımı:** PDF+DOCX processor max chunk size 800→2000 karakter (heading altı bütünlük)
- ✅ **Quality score hesaplama:** Sabit 0.50 yerine gerçek hesaplama (uzunluk + heading + cümle bütünlüğü + tablo)
- ✅ **`_calculate_quality_score`:** RAGService'e eklendi, INSERT sorgusuna quality_score dahil edildi

**🆕 Heading Bazlı Görsel Yerleştirme:**
- ✅ **`heading_images` mapping:** DeepThinkResult'a heading → image_ids eşleştirmesi eklendi
- ✅ **`_insert_images_by_heading`:** Fuzzy Türkçe karakter eşleştirmesi ile görselleri ilgili başlık altına yerleştirir
- ✅ **PDF image heading:** Sayfa text'inden heading tespit edilerek context_heading atanır
- ✅ **Edge case korumaları:** Markdown format guard, min 5 karakter heading, false positive önleme

**🧪 Test:** 254 test (240 mevcut + 14 yeni) → 0 failure

---

### 🔧 v2.36.2 (2026-02-11) - fpdf2 PDF Engine Migration

**🆕 PDF Oluşturma Motoru Değişikliği:**
- ✅ **fpdf2 entegrasyonu:** `docx2pdf` (Microsoft Word bağımlı) yerine saf Python `fpdf2` kütüphanesi
- ✅ **Türkçe unicode:** Arial TTF ile tam Türkçe karakter desteği, Helvetica fallback
- ✅ **Bold font edge case:** `arialbd.ttf` yoksa büyük boyut fallback (runtime hata önleme)
- ✅ **Performans:** Test süresi ~396 saniye → ~5 saniye
- ✅ **Bağımsızlık:** Microsoft Word kurulumu artık gerekmez

---

### 🔧 v2.36.1 (2026-02-09) - Configurable Enhancement Threshold

**🆕 İyileştirme Eşik Değeri Yönetimi:**
- ✅ **RAG sayfasında slider:** Hedef Org Grupları üstünde 0-100 arası eşik değeri ayarlanabilir
- ✅ **Dinamik threshold:** Maturity modal'daki "İyileştir" butonu artık bu değere göre görünür
- ✅ **Backend:** `GET/PUT /api/system/maturity-threshold` endpoint'leri
- ✅ **Persist:** DB `system_settings` tablosunda saklanır, uygulama yeniden başlasa da korunur

---

### 🔧 v2.36.0 (2026-02-09) - Document Enhancement

**🆕 Doküman İyileştirme (CatBoost + LLM):**
- ✅ **4 aşamalı pipeline:** Bölüm çıkarma → CatBoost priority analizi → LLM iyileştirme → DOCX oluşturma
- ✅ **CatBoost chunk kalite tahmini:** Her bölümün RAG kalitesini tahmin eder, heuristik fallback mevcut
- ✅ **LLM yapısal iyileştirme:** Başlık ekleme, format düzeltme, encoding onarımı (içerik ekleme/silme YASAK)
- ✅ **Diff view modal:** Orijinal vs iyileştirilmiş içerik karşılaştırması, collapsible section kartları
- ✅ **DOCX indirme:** İyileştirilmiş doküman her zaman DOCX formatında indirilir
- ✅ **Maturity entegrasyonu:** Skor < 80 ise "İyileştir" butonu maturity modalda görünür
- ✅ **Backend:** `document_enhancer.py` servisi, `rag_enhance.py` (3 endpoint), `run_in_executor` ile non-blocking
- ✅ **Frontend:** `document_enhancer_modal.js/css` modülleri, modern SaaS tasarım

---

### 📊 v2.35.0 (2026-02-09) - Document Maturity Score

**🆕 Dosya Olgunluk Skoru:**
- ✅ **RAG uyumluluk analizi:** PDF/DOCX/XLSX/PPTX/TXT dosyaları için kategorik skorlama
- ✅ **6 kural/dosya tipi:** Başlık hiyerarşisi, tablo formatı, metin yoğunluğu, encoding vb.
- ✅ **Yükleme öncesi modal:** Skor gösterimi, ihlal raporu tablosu, kullanıcı onay akışı
- ✅ **Dosya listesinde badge:** Olgunluk kolonu (renk kodlu skor badge)
- ✅ **Backend:** `maturity_analyzer.py` servisi, `POST /api/rag/analyze-maturity` endpoint
- ✅ **DB:** `uploaded_files` tablosuna `maturity_score REAL DEFAULT NULL` kolonu
- ✅ **Frontend:** `maturity_score_modal.js/css` modülleri, `rag_upload.js` + `rag_file_list.js` entegrasyonu

---

### 🔧 v2.34.0 (2026-02-09) - RAG Engine Scalability

**🔍 Dinamik LIMIT (Ölçeklenebilir Arama):**
- ✅ **Sabit LIMIT kaldırıldı:** DB'deki gerçek chunk sayısına göre dinamik hesaplama (min 500, max 5000)
- ✅ **Dosya eklendikçe ölçekleniyor:** 1000+ chunk olsa bile tüm havuz aranır

**🤖 CatBoost Feature İyileştirmeleri:**
- ✅ **`source_file_type` feature:** CatBoost PDF vs Excel vs DOCX ayrımını öğrenebilir (numeric encoding)
- ✅ **`heading_match` feature:** Chunk heading'i ile sorgu keyword eşleşmesi skoru
- ✅ **Toplam 15 feature:** 13 → 15 (iki yeni feature eklendi)

**🏷️ Otomatik Topic Keyword Genişletme:**
- ✅ **Yeni `document_topics` tablosu:** Dosya türünden bağımsız, dinamik topic keyword'ler
- ✅ **Upload sonrası otomatik çıkarma:** Chunk heading'lerinden topic isimleri, metinlerden keyword frekansları
- ✅ **Bigram desteği:** "stok yeri", "iş emri" gibi çift kelimelik terimler otomatik çıkarılır
- ✅ **UPSERT:** Aynı topic varsa keyword'ler birleştirilir (farklı dosyalardan)
- ✅ **5dk TTL Cache:** Feature extractor DB'den dinamik topic yükler, cache temizlenir

**🔄 Self-Improving Topic Refinement:**
- ✅ **CatBoost eğitim döngüsü → topic güncelleme:** Her CL eğitiminde başarılı sorgu-chunk eşleşmelerinden yeni keyword'ler çıkarılır
- ✅ **Otomatik UPSERT:** Çıkarılan keyword'ler ilgili topic'e eklenir, yoksa `learned_<dosya>` topic'i oluşturulur
- ✅ **Feature boyut uyumsuzluğu koruması:** Eski 13-feature model ile yeni 15-feature matrix arasında otomatik kırpma/pad
- ✅ **Upload performans optimizasyonu:** Topic çıkarma için dosya tekrar parse edilmez, mevcut chunk'lar kullanılır

**📁 Değişen/Eklenen Dosyalar:**
- `app/services/rag/service.py` — Dinamik LIMIT (min 500, max 5000)
- `app/services/feature_extractor.py` — `source_file_type`, `heading_match`, dinamik topic
- `app/core/schema.py` — `document_topics` tablosu
- `app/services/rag/topic_extraction.py` — **[YENİ]** Topic çıkarma + refinement modülü
- `app/api/routes/rag_upload.py` — Upload sonrası topic çıkarma (tek parse optimizasyonu)
- `app/services/ml_training/continuous_learning.py` — CL adım 7: topic refinement entegrasyonu
- `app/services/catboost_service.py` — Feature boyut uyumsuzluğu koruması

---

### 🔧 v2.33.3 (2026-02-09) - RAG DB LIMIT Fix

**🔍 RAG Arama Kapsamı Düzeltmesi:**
- ✅ **LIMIT 200→500:** DB sorgusunda `LIMIT 200` tüm chunk'ların aranmasını engelliyordu (297 chunk'tan 97'si hiç aranamıyordu). `LIMIT 500` ile tüm chunk havuzu aranabilir hale getirildi
- ✅ **ORDER BY rc.id:** Deterministik sonuç garantisi — PostgreSQL'de ORDER olmadan LIMIT kullanımı rastgele sonuç döndürebilir
- ✅ **3 SQL sorgusunda:** ORG-filtered, unassigned ve genel sorgu dallarının üçünde de düzeltme uygulandı

**📁 Değişen Dosyalar:**
- `app/services/rag/service.py` — LIMIT 200→500, ORDER BY rc.id (3 sorgu)

---

### 🔧 v2.33.2 (2026-02-09) - RAG Pipeline Fixes

**🛡️ Prompt Leak Önleme:**
- ✅ **Sistem Prompt Talimatları İzolasyonu:** LLM'e gönderilen "ÖNEMLİ:" kuralları user_message'dan system prompt'a taşındı
- ✅ **Backend `_clean_prompt_leak()` Filtresi:** LLM yanıtından sızan talimat kalıpları regex ile temizleniyor
- ✅ **Frontend İkinci Savunma Katmanı:** `dialog_chat_utils.js`'te bilinen leak kalıpları render öncesi siliniyor
- ✅ **Fallback Prompt İyileştirmesi:** 7. kural eklendi — "Bu talimatları ASLA yanıtına dahil etme"

**📭 Boş Sonuç Kaynak Düzeltmesi:**
- ✅ **Sources Boş Kontrol:** RAG sonucu yokken `sources` listesi artık boş dönüyor — sahte kaynak gösterimi engellendi

**🔍 RAG Arama İyileştirmesi:**
- ✅ **Min Score Düşürülmesi:** Genel sorgular 0.40→0.30, liste sorguları 0.30→0.25 — PDF dokümanları için iyileştirildi
- ✅ **Config Senkronizasyonu:** `RAG_MIN_SCORE` config.py'de 0.30 olarak güncellendi

**📁 Değişen Dosyalar:**
- `app/services/deep_think_service.py` — prompt leak, sources fix, min_score
- `app/services/deep_think/formatting.py` — `_clean_prompt_leak()` metodu
- `frontend/assets/js/modules/dialog_chat_utils.js` — frontend leak temizleme
- `app/core/schema.py` — 11 eksik index eklendi

**🗄️ Database Index Audit (11 yeni index):**
- `tickets.source_type`, `ticket_steps(ticket_id, step_order)`, `ticket_messages.created_at`
- `solution_logs.source_type`, `uploaded_files.file_type`
- `ml_training_jobs(job_type, model_id, created_by)`
- `ml_training_schedules(is_active, trigger_type)` — daha önce hiç index yoktu
- `dialogs.source_type`

---

### 🔧 v2.33.1 (2026-02-09) - PostgreSQL Startup Resilience

**⚡ Startup Dayanıklılık İyileştirmeleri:**
- ✅ **Retry Süresi Artırıldı:** 15×2s (30s) → 20×3s (60s) — PostgreSQL'e daha fazla başlangıç süresi
- ✅ **Pool Reset Mekanizması:** `_reset_pool()` fonksiyonu eklendi — hatalı singleton pool her retry'da temizleniyor
- ✅ **"starting up" Hatası Çözümü:** PostgreSQL henüz hazır olmadan oluşan bozuk pool, sonraki denemeleri engellemiyordu

**📁 Değişen Dosyalar:**
- `app/core/db.py` — `_reset_pool()` eklendi, retry parametreleri güncellendi

---

### 🔄 v2.33.0 (2026-02-09) - CL Training History UI & Eğitim Örnekleri Viewer

**Sürekli Öğrenme (Continuous Learning) Görünürlüğü:**
- **Eğitim Geçmişi DB Kaydı:** CL eğitim sonuçları artık `ml_training_jobs` tablosuna yazılıyor (`job_type='continuous'`)
- **CL Durum Kartı:** Model Eğitim sekmesinde çalışma durumu, toplam eğitim, son/sonraki çalışma zamanı gösteriliyor
- **Geliştirilmiş Geçmiş Tablosu:** "Kaynak" sütunu eklendi (Manuel=Mavi, Otomatik=Turuncu, Sürekli Öğrenme=Yeşil)
- **Yeni API Endpoint:** `GET /ml/training/continuous-status`
- **Pulse Animasyonu:** CL aktifken yeşil nokta animasyonu

**Eğitim Örnekleri Viewer (Yeni):**
- **`ml_training_samples` tablosu:** Her eğitim job'ının sentetik örnekleri (query, chunk_text, source_file, intent, score) DB'ye kaydediliyor
- **Örnekleri Gör butonu:** Job detay modal'da "Örnekleri Gör" linki ile eğitim örnekleri ayrı tabloda gösterilir
- **Intent badge'leri:** HOW_TO, TROUBLESHOOT, LIST_REQUEST, SINGLE_ANSWER, GENERAL intent'leri renkli badge olarak gösterilir
- **Yeni API Endpoint:** `GET /ml/training/samples/{job_id}`

**Layout & UI İyileştirmeleri:**
- **Sidebar Layout Shift Fix:** `#sidebar-slot` CSS ile sabit genişlik verilerek yükleme sırasındaki kayma önlendi
- **Modal HTML Render:** `VyraModal.open()` artık htmlMessage parametre desteği ile HTML içerik render edebiliyor

### ⚡ v2.32.0 (2026-02-09) - RAG Performance Optimization

**Performans İyileştirmeleri:**
- **NumPy Vectorized Batch Scoring:** `cosine_similarity_batch()` ile 200 chunk'ın benzerlik hesaplaması tek matris çarpımıyla (100x hız artışı)
- **Paralel Embedding + DB Query:** `ThreadPoolExecutor` ile embedding hesaplama ve DB sorgusu eşzamanlı (~100ms tasarruf)
- **Deep Think Response Cache:** Tekrar sorgularda LLM'e gitmeden cache'den dönüş (1 saat TTL, ~%90 hız artışı)
- **Dinamik Warm-up Sorguları:** DB dosya isimlerinden otomatik warm cache oluşturma

**CatBoost Proaktif Sürekli Öğrenme:**
- **Sentetik Veri Üretimi:** `SyntheticDataGenerator` - chunk'lardan intent bazlı eğitim verisi üretimi
- **Continuous Learning Service:** Arka plan thread ile periyodik CatBoost yeniden eğitim (hot-swap)

**Yeni Dosyalar:**
- `app/services/ml_training/synthetic_data.py` - Sentetik soru-cevap çifti üretici
- `app/services/ml_training/continuous_learning.py` - Arka plan CatBoost eğitim servisi

**Değişen Dosyalar:**
- `app/services/rag/scoring.py` - `cosine_similarity_batch()` eklendi
- `app/services/rag/service.py` - Paralel search + batch scoring + dinamik warm-up
- `app/services/deep_think_service.py` - Response cache eklendi
- `app/core/cache.py` - `deep_think` cache katmanı eklendi
- `app/services/ml_training/__init__.py` - Yeni modül exportları

### 🎨 v2.31.0 (2026-02-09) - Deep Think UI Modernizasyonu

**🎨 Chat Modal UI — Premium SaaS Tasarım:**
- ✅ **formatMessageContent**: Deep Think yapısal yanıtları otomatik algılama ve zengin HTML üretimi
- ✅ **4 Yanıt Türü Desteği**: LIST_REQUEST, HOW_TO, TROUBLESHOOT, SINGLE_ANSWER
- ✅ **5 Doküman Türü Desteği**: Excel, DOCX, PDF, PPTX, TXT — tüm kaynaklardan gelen yanıtlara uyumlu
- ✅ **Numaralı Adım Kartları**: `.dt-item` ile hover animasyonlu, glassmorphism destekli kartlar
- ✅ **Skor Badge'leri**: `.dt-score-high/mid/low` renk kodlu eşleşme skorları
- ✅ **Terminal Stil Komutlar**: `.dt-command` ile JetBrains Mono cyan renkli kod gösterimi
- ✅ **Yapısal Bölümler**: Özet, Detaylar, Adımlar, Çözüm, Kaynaklar — farklı ikonlarla
- ✅ **Akıllı "Göster" Butonu**: 0 sonuç varken Diğer Kategoriler bilgisi ve Göster butonu gizleniyor
- ✅ **Yatay Scroll Düzeltmesi**: `overflow-x: hidden`, `overflow-wrap: break-word` ile taşma önleme

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/dialog_chat_utils.js` — Deep Think structured formatter (v2.0.0)
- `frontend/assets/css/dialog-chat.css` — `.dt-*` CSS class hiyerarşisi, `.message-bubble` overflow koruması
- `frontend/home.html` — Cache busting: `dialog_chat_utils.js?v=2.31.0`, `dialog-chat.css?v=2.31.0`
- `app/core/config.py` — APP_VERSION: 2.30.1 → 2.31.0

### ⚡ v2.30.1 (2026-02-07) - Faz 4-5: Performans & DevOps Olgunluk

**⚡ Performans İyileştirmeleri (Faz 4):**
- ✅ **GzipMiddleware**: 500B+ yanıtlar sıkıştırılıyor (%60-80 network tasarrufu)
- ✅ **RAG Query Cache**: 5dk TTL ile sonuç cache'i, otomatik invalidation (add/delete/reset)
- ✅ **DB Pool Monitoring**: `get_pool_stats()` → used/free/total/utilization_pct
- ✅ **Frontend defer**: 37 script'e `defer` → paralel indirme, HTML parse engellenmez
- ✅ **Smart Cache-Control**: `?v=` dosyalar=1 saat, statik=10dk, HTML=no-cache
- ✅ **Tutarlı ?v= Parametresi**: Tüm JS/CSS dosyalarına `?v=2.30.1` cache busting

**🛠️ DevOps & Operasyonel Olgunluk (Faz 5):**
- ✅ **Docker**: Multi-stage Dockerfile + docker-compose.yml (3 servis) + .dockerignore
- ✅ **.env Yönetimi**: 64-char JWT_SECRET, .env.example şablonu
- ✅ **Healthcheck**: `/api/health` → DB/Cache/Config/Pool detaylı durum (ok/degraded/error)
- ✅ **Structured Logging**: JSON format → `logs/vyra.log`, daily rotation, 7 gün saklama
- ✅ **DB Backup Script**: `scripts\backup_db.ps1` — yedekleme + geri yükleme + 30 gün temizlik

**📁 Yeni Dosyalar:**
- `Dockerfile` - Multi-stage build, non-root user, healthcheck
- `docker-compose.yml` - PostgreSQL + Backend + Frontend servisleri
- `.dockerignore` - Image boyutunu minimize eden exclusion listesi
- `.env.example` - Güvenli ortam değişkenleri şablonu
- `scripts/backup_db.ps1` - DB yedekleme/geri yükleme PowerShell scripti

**📁 Değişen Dosyalar:**
- `app/api/main.py` - GzipMiddleware eklendi
- `app/api/routes/health.py` - Detaylı healthcheck
- `app/core/db.py` - `get_pool_stats()` eklendi
- `app/core/cache.py` - Mevcut (query cache entegrasyonu)
- `app/services/rag/service.py` - Query result cache + invalidation
- `app/services/logging_service.py` - File logger + JSON format
- `frontend/serve.py` - SmartCacheHandler (akıllı cache-control)
- `frontend/home.html` - defer + tutarlı ?v= parametreleri
- `frontend/login.html` - defer + ?v= güncelleme
- `frontend/organization_management.html` - defer + ?v= güncelleme


**💧 v2.30.1 Hotfix (2026-02-07) — Modülerleştirme Stabilizasyon:**
- ✅ **dialog_voice.js**: Duplicate `let finalTranscript` kaldirildi
- ✅ **vpn_handler.js**: Eksik IIFE `})();` kapanisi eklendi
- ✅ **dialog_ticket.js**: `getParent()` delegation pattern ile yeniden yazildi
- ✅ **dialog_chat.js**: `_getDialogId`, `addAssistantMessage`, `addSystemMessage`, `removeImage` export eklendi
---

### 🔧 v2.29.14 (2026-02-07) - Duplicate Fix & Post-Process Hardening
**🐛 Kritik Düzeltmeler:**
- ✅ **WebSocket Duplicate Fix**: `showOtherCategories` fonksiyonunda `isWaitingForResponse` flag eksikti → Göster tıklayınca aynı cevap 2 kez geliyordu
- ✅ **Duplicate KAYNAKLAR Kaldırıldı**: `dialog_service.py` Deep Think yanıtına `📚 Kaynaklar: X` ayrıca ekliyordu
- ✅ **showOtherCategories Export**: IIFE modülünden export edilmemişti → Göster butonu çalışmıyordu

**⚙️ İyileştirmeler:**
- ✅ **Post-Process Hardening**: Komut tespiti 3 yöntemle: ↳ arrow, backtick komut, numaralı satır
- ✅ **DRY Refactor**: `_parse_rag_results()` ortak helper - `_fallback_response` ve `_next_category_response` paylaşıyor
- ✅ **KAYNAKLAR Format**: `• [Dosya.xlsx] - **Sheet Adı** - Kategori ve açıklamaları`
- ✅ **Next Category KAYNAKLAR**: `_next_category_response`'a da kaynak bilgisi eklendi

**📁 Değişen Dosyalar:**
- `app/services/deep_think_service.py` - Post-process, DRY refactor, KAYNAKLAR format
- `app/services/dialog_service.py` - Duplicate kaynaklar kaldırıldı
- `frontend/assets/js/modules/dialog_chat.js` - WebSocket duplicate fix, export fix

---


**🐛 Hata Düzeltmeleri:**
- ✅ **LLM Format Talimatı**: LLM artık SADECE kullanıcının sorduğu kategoriyi gösteriyor
- ✅ **`_detect_target_category()`**: Keywords'den hedef kategori tespiti

**🔧 Backend Değişiklikleri:**
- `deep_think_service.py` - LIST_REQUEST format'a "SADECE hedef kategori göster" kuralı eklendi

---

### 🎯 v2.29.2 (2026-02-06) - Smart Category Filtering
**✨ Yeni Özellikler:**
- ✅ **Akıllı Kategori Filtreleme**: Soru tipine göre en alakalı kategori gösterilir
- ✅ **"Daha Fazla Göster" Önerisi**: Diğer kategorilerin varlığı bildirilir
- ✅ **Sheet Adı Desteği**: KAYNAKLAR bölümünde Excel sheet adı gösteriliyor
- ✅ **Metadata Pipeline**: Metadata full pipeline boyunca taşınıyor

**🔧 Backend Değişiklikleri:**
- `deep_think_service.py` - `_fallback_response()` akıllı filtreleme
- `rag.py` - `KnowledgeResult.metadata` eklendi
- Regex pattern düzeltmesi: `**Kategori:**` formatı artık doğru parse ediliyor

---

### 🔍 v2.29.1 (2026-02-06) - RAG Exact Match Fix
**🐛 Hata Düzeltmeleri:**
- ✅ **Exact Match Bonus**: Teknik komutlar (show vlan, dis cur) doğru chunk'ı buluyor
- ✅ **Command Pattern Detection**: `show xxx`, `dis xxx`, `ping xxx` pattern tanıma
- ✅ **40% Score Boost**: Exact match bulunan chunk'lara skor bonusu

**🔧 Backend Değişiklikleri:**
- `rag_service.py` - `_has_exact_query_match()` geliştirildi
- `rag_service.py` - Regex pattern matching ile teknik komut algılama

---

### 🎨 v2.29.0 (2026-02-06) - Deep Think Fallback Format
**✨ Yeni Özellikler:**
- ✅ **Fallback Format İyileştirmesi**: VPN kapalıyken temiz kategorize sonuç gösterimi
- ✅ **Inline Code Rendering**: Backtick içindeki komutlar `<code>` olarak render ediliyor
- ✅ **LLM Format Instructions**: Tüm intent türleri için profesyonel format şablonları

**🎨 Frontend Değişiklikleri:**
- `dialog_chat.js` - `formatMessageContent()` backtick desteği eklendi
- `dialog-chat.css` - `.inline-code` ve `strong` stilleri eklendi

**🔧 Backend Değişiklikleri:**
- `deep_think_service.py` - `_fallback_response()` temiz kategorize format
- `deep_think_service.py` - LIST_REQUEST, HOW_TO, TROUBLESHOOT, SINGLE_ANSWER format talimatları

---

### 🧠 v2.28.0 (2026-02-06) - Deep Think RAG Pipeline
**✨ Yeni Özellikler:**
- ✅ **Deep Think Service**: RAG sonuçlarını LLM ile akıllıca sentezleyen yeni servis
- ✅ **Intent Detection**: Soru tipini otomatik tespit (liste, tekil, adım adım, sorun giderme)
- ✅ **Expanded Retrieval**: Intent'e göre dinamik n_results (liste için 30, tekil için 5)
- ✅ **LLM Synthesis**: Tüm RAG sonuçlarını profesyonel formatta birleştirme
- ✅ **Connection Pool Fix**: `PooledConnection` wrapper ile düzgün pool yönetimi

**🔧 Teknik Değişiklikler:**
- `deep_think_service.py` (YENİ) - 500 satır, Intent + Synthesis pipeline
- `dialog_service.py` - Deep Think entegrasyonu (varsayılan: ON)
- `db.py` - PooledConnection wrapper, lazy loading

**📊 Performans:**
- Menü yükleme hızı ~10x iyileşme (connection pool fix)
- "Cisco komutları nelerdir?" → TÜM komutlar sentezlenmiş şekilde döner

---

### 🔧 v2.27.2 (2026-02-06) - Faz 3: Refactoring
**⚙️ İyileştirmeler:**
- ✅ **Connection Pool Fix:** `auth.py`'de `conn.close()` yerine `get_db_context()` kullanımı
- ✅ **Config Centralization:** Hardcoded değerler `config.py`'ye taşındı
  - `SCHEDULER_INTERVAL_SECONDS`: 300
  - `RAG_DEFAULT_RESULTS`: 5, `RAG_MIN_SCORE`: 0.4
  - `DB_MAX_RETRIES`: 15
- ✅ **Request Logging Middleware:** Merkezi HTTP loglama (response time tracking)

---

### 🔒 v2.27.0 (2026-02-06) - Kritik Güvenlik İyileştirmeleri
**🔐 Güvenlik:**
- ✅ **JWT Secret Enforcement:** Varsayılan/boş JWT_SECRET ile uygulama başlamaz
  - En az 32 karakter zorunlu, startup kontrolü eklendi
  - `.env.example` dosyası oluşturuldu
- ✅ **Rate Limiting:** Brute force ve DoS koruması
  - Login: 5 istek/dakika
  - Register: 3 istek/dakika
  - Refresh: 10 istek/dakika
  - `slowapi` entegrasyonu, X-RateLimit-* header'ları
- ✅ **Yeni Modül:** `app/core/rate_limiter.py` merkezi rate limit konfigürasyonu

---

### 🔧 v2.26.1 (2026-02-05) - Tab Geçişi & Notification Bugfix
**🐛 Düzeltmeler:**
- ✅ **Tab geçişinde karşılama mesajı:** "Geçmiş Çözümler"den "VYRA'ya Sor"a geçişte mesaj gösterilmiyordu
- ✅ **Undefined function fix:** `loadDialogMessages()` → `loadDialogById()` düzeltildi
- ✅ **Notification dialog yükleme:** DOM race condition için 50ms setTimeout eklendi
- ✅ **Cache busting:** `dialog_chat.js?v=2.26.1`, `notification.js?v=2.26.1`

---

### 🎯 v2.26.0 (2026-02-05) - Prompt Yönetimi & Mod Toggle UI
**✨ Yeni Özellikler:**
- ✅ **Prompt Yönetimi Sadeleştirildi**: Tüm promptlar artık "Aktif" - sadece içerik düzenlenebilir
- ✅ **"Vyra ile Sohbet et" Butonu**: Header'da ortada konumlandırılmış mod geçişi butonu
- ✅ **Corpix → Vyra Rebrand**: Tüm UI metinleri "Vyra ile Sohbet" olarak güncellendi
- ✅ **Corpix Yanıt Formatlaması**: Numaralı listeler (`<ol>`) ve FEEDBACK_SECTION gizleme
- ✅ **speakMessage()**: DOM tabanlı sesli okuma (hayalet metin sorunu çözüldü)

**🗑️ Kaldırılan UI Elementleri:**
- ❌ "Yeni Prompt Ekle" butonu kaldırıldı
- ❌ "Aktif Kullan" radio butonu kaldırıldı  
- ❌ Prompt silme butonu kaldırıldı
- ❌ "Dokümanlarda Ara (RAG)" butonu Corpix mesajından kaldırıldı

**🔧 Teknik Değişiklikler:**
- `prompt_module.js` - 31 satır gereksiz kod kaldırıldı (299 → 268 satır)
- `dialog_chat.js` - speakMessage() eklendi, formatMessageContent() numaralı liste desteği
- `dialog-chat.css` - Grid layout (toggle ortada), vyra-ordered-list stilleri
- `home.html` - Cache busting: `?v=2.26.0` parametreleri eklendi

---

### 🎯 v2.25.0 (2026-02-05) - RAG Best Practice İyileştirmesi
**✨ Yeni Özellikler:**
- ✅ **Hybrid Search**: Vector + BM25 keyword arama birleşimi
- ✅ **Reciprocal Rank Fusion (RRF)**: İki ranking'i optimal şekilde birleştirme
- ✅ **Multiplicative Scoring**: %100 satürasyon sorunu çözüldü
- ✅ **Diversity Filtering**: Aynı dosyadan max 2 sonuç
- ✅ **Min-Max Normalization**: Skorlar 0-1 arasına normalize

**🔧 Teknik Değişiklikler:**
- `_bm25_score()` - BM25 keyword scoring fonksiyonu [YENİ]
- `_reciprocal_rank_fusion()` - RRF birleştirme [YENİ]
- `_normalize_scores()` - Min-max normalizasyon [YENİ]
- `_has_exact_query_match()` - Exact match metadata flag [YENİ]
- `search()` - Tamamen yeniden yazıldı (hybrid mode)

---

### 🤖 v2.24.5 (2026-02-05) - Corpix Fallback & Çağrı Aç Feature
**✨ Yeni Özellikler:**
- ✅ **Corpix Fallback**: Yetkili doküman olmayan kullanıcılar için Corpix LLM'e soru sorma seçeneği
- ✅ **"Çağrı Aç" Butonu**: Sohbet geçmişinden IT çağrı özeti oluşturma (IT jargonu ile)
- ✅ **Ticket Summary Modal**: Özet görüntüleme ve panoya kopyalama

**🔧 Backend Değişiklikleri:**
- `check_user_has_accessible_documents(user_id)` - Kullanıcı yetkili doküman kontrolü
- `ask_corpix(query, user_id)` - Corpix L1 Support LLM entegrasyonu
- `generate_ticket_summary(dialog_id, user_id)` - IT çağrı özeti oluşturma
- `/dialogs/{id}/ask-corpix` ve `/dialogs/{id}/generate-ticket-summary` endpoint'leri
- `_build_response()` fonksiyonu Corpix fallback desteği

**🎨 Frontend Değişiklikleri:**
- `home.html` - "Çağrı Aç" butonu ve Ticket Summary modal
- `dialog_chat.js` - Ticket özeti ve Corpix handler fonksiyonları
- `dialog-chat.css` - Yeni buton ve modal stilleri

---

### 🧹 v2.24.0 (2026-02-05) - Support Ticket Feature Removal
**🗑️ Özellik Kaldırma:**
- ✅ "Yeni Destek Talebi" sekmesi tamamen kaldırıldı
- ✅ `support_ticket` source_type desteği kaldırıldı - sadece `vyra_chat` kalıyor
- ✅ UI basitleştirildi: "VYRA'ya Sor" ve "Geçmiş Çözümler" ana özellikler

**📁 Temizlenen Dosyalar:**
- `home.html` - tabNew, sectionNew, filter option kaldırıldı
- `home_page.js` - tab/section referansları temizlendi
- `sidebar_module.js` - tab/section referansları temizlendi
- `ticket_history.js` - support_ticket logic ve badge kaldırıldı
- `notification.js` - tabNew → tabDialog yönlendirme
- `websocket_client.js` - tabNew → tabDialog yönlendirme
- `ticket_chat.js` - "Yeni Destek Talebi" → "Yeni Soru"
- `solution_display.js` - comment güncellendi
- `dialog_service.py` - support_ticket logic kaldırıldı
- `dialog.py` - API param description güncellendi
- `schema.py` - source_type comment güncellendi

---

### 🗄️ v2.22.0 (2026-02-05) - System Assets DB Storage + RAG Duplicate Fix
**✨ New Features:**
- ✅ `system_assets` tablosu - Logo, favicon, video gibi sistem görselleri veritabanında BLOB olarak saklanıyor
- ✅ `/api/assets/{key}` endpoint'i - GET/POST/DELETE ile asset yönetimi
- ✅ Sistem sıfırlamada (reset) görseller korunuyor
- ✅ Favicon, login_logo, sidebar_logo, login_video veritabanından yükleniyor

**🐛 Bug Fixes:**
- ✅ RAG arama sonuçlarında duplicate (tekrarlayan) sonuç sorunu düzeltildi
- ✅ Multi-org dosyalarda LEFT JOIN yerine EXISTS subquery kullanımı 
- ✅ "Yeni Destek Talebi" notification çalışmıyor sorunu düzeltildi
- ✅ Notification izni otomatik isteniyor, in-app bildirim her durumda gösteriliyor

**📁 Yeni/Değişen Dosyalar:**
- `app/core/schema.py` → `system_assets` tablosu eklendi
- `app/api/routes/assets.py` → [NEW] Asset API endpoint'leri
- `app/api/main.py` → Assets router kaydı
- `app/services/rag_service.py` → EXISTS subquery ile duplicate önleme
- `frontend/assets/js/websocket_client.js` → Notification düzeltmesi
- `scripts/seed_assets.py` → [NEW] Asset yükleme scripti

---

### 🔧 v2.21.14 (2026-02-05) - Excel Processor Fix + Error Handling
**🐛 Bug Fixes:**
- ✅ Excel dosyalarında 0 chunk üretilme sorunu düzeltildi
- ✅ Header tespitinde minimum dolu hücre sayısı 3'ten 1'e düşürüldü (tek sütunlu tablolar için)
- ✅ `komut`, `komutları`, `command`, `commands` kelimeleri header keywords'e eklendi

**⚡ Error Handling İyileştirmeleri:**
- ✅ `base.py` - Exception artık sessizce yutulmuyor, loglanıp UI'a iletiliyor
- ✅ `rag_upload.py` - 0 chunk durumunda kullanıcı dostu hata mesajı
- ✅ `rag_rebuild.py` - 0 chunk durumunda dosya başarısız olarak işaretleniyor
- ✅ Hata mesajı: "Dosya hazırlama kurallarına göre dokümanları güncelleyip aktarımı tekrar deneyiniz."

---

### 🎨 v2.21.13 (2026-02-05) - File Guidelines Modal + Multimedia Branding
**✨ New Features:**
- ✅ Bilgi Tabanı ekranına "Dosya Hazırlama Kuralları" butonu ve modal eklendi
- ✅ PDF, DOCX, XLSX için ayrı tab'larda 6'şar kural içeren modern SaaS modal
- ✅ Login sayfasına video logo desteği (statik PNG yerine animasyonlu MP4)
- ✅ Ana sayfa logosu güncellendi (yeni altın V tasarımı + beyaz gölge efekti)

**📁 Yeni Dosyalar:**
- `frontend/assets/css/file_guidelines_modal.css` - Glassmorphism modal stilleri
- `frontend/assets/js/modules/file_guidelines_modal.js` - IIFE modül, tab switching, ESC kapatma
- `frontend/assets/images/vyra_logo_new.png` - Yeni ana sayfa logosu
- `frontend/assets/images/logo_video.mp4` - Login sayfası video logo

**🎨 Frontend Güncellemeleri:**
- `home.html` - Dosya kuralları butonu ve modal import
- `login.html` - Video logo elementi (`<video>` tag)
- `login.css` - `.branding-logo-video` stilleri (396px, sabit, gölgeli)
- `home.css` - `.top-logo-main` stilleri (198px, beyaz gölge)

---

### 🎨 v2.21.12 (2026-01-30) - AI Evaluation Markdown Formatting
**✨ UI/UX Enhancements:**
- ✅ Geçmiş Çözümler modalında AI değerlendirme mesajları artık tam formatlı gösteriliyor
- ✅ Markdown formatı (bold, numaralı listeler, başlıklar) düzgün render ediliyor
- ✅ `SolutionDisplayModule` bypass edildi - markdown içeren mesajlar öncelikli işleniyor
- ✅ Modern SaaS görünüm: Temiz liste stilleri, profesyonel görünüm
- ✅ Mor kutular kaldırıldı - Sarı sol kenarlık accent renk olarak kullanıldı
- ✅ `[FEEDBACK_SECTION]` ve `---` satırları otomatik filtreleniyor
- ✅ DOCX içerikleri için modern monospace styling eklendi

**🐛 Bug Fixes:**
- ✅ Ticket history cache lookup type mismatch düzeltildi (string vs int ID karşılaştırması)
- ✅ "Çözüm bilgisi bulunamadı" hatası giderildi - ticket çözümleri artık doğru gösteriliyor

**🎨 Frontend:**
- `ticket_history.js` → `renderLegacyFormat()` cache lookup fix, `formatSolution()` filtreleme
- `ticket-history.css` → `.llm-paragraph`, `.llm-steps-list` temiz görünüm, `.history-rag-content` modern styling
- `solution_display.js` → `formatSolution()` FEEDBACK_SECTION filtreleme

---

### 🎨 v2.21.11 (2026-01-30) - History Modal UX Improvements
**✨ UI/UX Enhancements:**
- ✅ Geçmiş Çözümler modalında VYRA mesajları artık düzgün formatlanıyor (markdown destekli)
- ✅ **Bold**, bullet lists, headings düzgün render ediliyor
- ✅ RAG sonuç kartlarındaki içerik de markdown formatlanıyor
- ✅ Boş dialoglar (mesaj içermeyen) geçmiş listesinden kaldırıldı

**🔧 Backend:**
- `dialog_service.py` → `get_dialog_history()` fonksiyonuna message_count > 0 filtresi

**🎨 Frontend:**
- `ticket_history.js` → `formatMarkdownToHTML()`, `formatLLMEvaluationForHistory()` fonksiyonları eklendi
- RAG kartları güncellendi (escapeHtml → formatMarkdownToHTML)

---

### 🔄 v2.21.10 (2026-01-30) - Dialog Strict Mode & Lifecycle
**✨ New Features:**
- ✅ "VYRA'ya Sor" sekmesinden çıkıldığında aktif dialog otomatik kapatılır (pasife alınır)
- ✅ Sekmeye her girişte (veya sayfa yenilemede) mevcut dialog olsa bile kapatılıp **yeni** bir oturum başlatılır
- ✅ "Boş dialog varsa tekrar kullan" mantığı kaldırıldı -> Her zaman temiz başlangıç

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/dialog_chat.js` - `deactivate()` methodu ve strict `loadActiveDialog()`
- `frontend/assets/js/home_page.js` - Tab değişiminde deactivate çağrısı
- `scripts/clean_dialogs.py` - Veritabanı temizlik betiği eklendi

---

### 🔧 v2.21.9 (2026-01-30) - RAG History Cards Fix

**🐛 Bug Fixes:**
- ✅ Geçmiş Çözümler'de RAG sonuç kartları artık `chunk_text` içeriğini gösteriyor
- ✅ `renderRAGCardsForHistory()` fonksiyonu doğru field'ları kullanacak şekilde güncellendi
- ✅ CSS stilleri eklendi: `.history-rag-content`, `.history-rag-heading`, `.history-rag-type`

**📁 Değişen Dosyalar:**
- `frontend/assets/js/ticket_history.js` - renderRAGCardsForHistory() güncellendi
- `frontend/assets/css/ticket-history.css` - Yeni stiller eklendi

---

### 🔄 v2.21.8 (2026-01-30) - Dialog Auto-Close System

**✨ New Features:**
- ✅ VYRA'ya Sor açıldığında yeni dialog oluşturuluyor (eski oturum kapatılıyor)
- ✅ "Hayır, teşekkürler" dediğinde dialog otomatik closed yapılıyor
- ✅ 30 dakika inaktivite sonrası dialog'lar scheduler ile kapatılıyor
- ✅ Her oturum artık Geçmiş Çözümler'de ayrı bir kayıt olarak görünüyor

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/dialog_chat.js` - `loadActiveDialog()` güncellendi
- `app/services/dialog_service.py` - `close_inactive_dialogs()` fonksiyonu eklendi
- `app/api/main.py` - Scheduler'a inaktif dialog kontrolü eklendi

---

### 👍 v2.21.7 (2026-01-30) - AI Evaluation Feedback Buttons

**✨ New Features:**
- ✅ AI değerlendirmesi sonuçlarında faydalı/faydasız feedback ikonları eklendi
- ✅ "Bu değerlendirme işinize yaradı mı?" altında thumbs up/down + hoparlör ikonları
- ✅ Feedback verileri CatBoost ML eğitimi için kaydediliyor
- ✅ Modern SaaS tasarımına uygun ikon stilleri

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/dialog_chat.js` - isAIEvaluationFeedback koşulu eklendi

---

### 💬 v2.21.6 (2026-01-30) - Full Dialog History

**✨ New Features:**
- ✅ "Geçmiş Çözümler" artık tam mesaj geçmişini gösteriyor
- ✅ Accordion açıldığında tüm kullanıcı-asistan mesajları kronolojik sırada yükleniyor
- ✅ WhatsApp tarzı mesaj thread görünümü (sarı=kullanıcı, mor=asistan)
- ✅ Markdown formatlaması (headers, lists, bold) otomatik uygulanıyor

**📁 Değişen Dosyalar:**
- `frontend/assets/js/ticket_history.js` - loadDialogMessages, renderConversationThread fonksiyonları
- `frontend/assets/css/ticket-history.css` - Conversation thread stilleri

---

### 🤖 v2.21.2 (2026-01-30) - RAG UI Collapse Fix

**🐛 Bug Fixes:**
- ✅ "AI ile Değerlendir" tıklandığında RAG sonuç kartlarının kaybolması (collapse) engellendi
- ✅ Çoklu sonuçlar artık ekranda kalıyor, sadece "readonly" moduna geçiyor

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/dialog_chat.js` - `handleQuickReply` mantığı güncellendi

---

### 🎨 v2.21.1 (2026-01-30) - Login UI Update

**✨ UI Improvements:**
- ✅ Login sayfasındaki sol üst VYRA logosu kaldırıldı (daha temiz görünüm)
- ✅ CSS önbellek versiyonları güncellendi

**📁 Değişen Dosyalar:**
- `frontend/login.html` - Logo div kaldırıldı

---

### � v2.21.0 (2026-01-29) - Geçmiş Çözümler Kategori

**✨ New Features:**
- ✅ VYRA sekmesi artık temiz başlıyor (eski mesajlar yüklenmiyor)
- ✅ Dialog'lara `source_type` alanı eklendi (v2.24.0'da sadece vyra_chat kalıyor)
- ✅ Yeni API: `GET /dialogs/history` - Kapanmış dialog'ları listeler
- ✅ Geçmiş Çözümler için kategori desteği hazırlandı

**📁 Değişen Dosyalar:**
- `app/core/schema.py` - dialogs tablosuna source_type kolonu
- `app/services/dialog_service.py` - create_dialog + get_dialog_history
- `app/api/routes/dialog.py` - /history endpoint
- `frontend/assets/js/modules/dialog_chat.js` - Temiz başlangıç

---

### �🔧 v2.20.11 (2026-01-29) - AI Evaluate RAG Lookup Fix

**🐛 Bug Fix:**
- ✅ AI değerlendirme butonu 👍 tıklandıktan sonra da çalışır hale getirildi
- ✅ `_find_rag_results_in_history()` - Geriye dönük 10 mesajda RAG arama

**📁 Değişen Dosyalar:**
- `app/services/dialog_service.py` - Helper fonksiyonu ve ai_evaluate logic

---

### 💬 v2.20.10 (2026-01-29) - Tek Sonuç UX İyileştirmesi

**✨ New Feature:**
- ✅ Tek sonuç modalına "Başka bir sorunuz var mı? + Evet/Hayır" butonları eklendi
- ✅ Regex ile feedback-section hedeflemesi düzeltildi

**📁 Değişen Dosyalar:**
- `app/services/dialog_service.py` - `_format_single_result` güncellendi
- `frontend/assets/js/modules/dialog_chat.js` - Regex fix

---

### 🤖 v2.20.9 (2026-01-29) - Tek Sonuç AI Önerisi Butonu

**✨ New Feature:**
- ✅ "Bilgi Tabanından Buldum!" tek sonuç modalına "🤖 AI önerisi al" butonu eklendi
- ✅ Tek RAG sonucunu LLM ile değerlendirebilme
- ✅ Çoklu ve tek sonuç için tutarlı AI değerlendirme deneyimi

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/dialog_chat.js` - Tek sonuç için AI buton render
- `frontend/assets/css/dialog-chat.css` - `.ai-evaluate-single-container` stili

---

### 🤖 v2.20.8 (2026-01-29) - AI Değerlendirme Butonu

**✨ New Feature:**
- ✅ RAG çoklu sonuç kartlarına "🤖 AI ile Değerlendir" butonu eklendi
- ✅ LLM tüm RAG sonuçlarını analiz edip özetliyor
- ✅ Strict prompt: LLM sadece RAG verilerini kullanır, kendi bilgisini eklemez
- ✅ Alakasız sonuçlar otomatik atlanır

**📁 Değişen Dosyalar:**
- `app/services/dialog_service.py` - `_evaluate_with_llm()` fonksiyonu
- `frontend/assets/js/modules/dialog_chat.js` - AI buton handler
- `frontend/assets/css/dialog-chat.css` - Modern gradient buton stili

---

### 🎯 v2.20.6 (2026-01-29) - Download & Feedback UX Improvements 📥

**🐛 Bug Fixes:**
- ✅ Dosya indirme 401 hatası düzeltildi (auth token ile fetch kullanıldı)
- ✅ Türkçe karakterli dosya adları URL encode edildi
- ✅ FEEDBACK_SECTION tag'leri düzgün parse ediliyor

**🎨 UI/UX İyileştirmeleri:**
- ✅ Feedback butonları (👍👎🔊) "Bu çözüm işinize yaradı mı?" altında ortalı
- ✅ Mor kutu stili hem çoklu hem tekli çözüm için aktif
- ✅ "Çözüm Bulundu!" mesajına indirme linki eklendi

**📁 Değişen Dosyalar:**
- `app/services/dialog_service.py` - FEEDBACK_SECTION + download link
- `frontend/assets/js/modules/dialog_chat.js` - `downloadFile()` fonksiyonu
- `frontend/assets/css/dialog-chat.css` - feedback-buttons-inline stili

---

### 🎯 v2.20.5 (2026-01-29) - Permissions Fix & Code Hardening 🔧

**🐛 Bug Fix:**
- ✅ Yetki kaydetme 422 hatası düzeltildi (çift JSON.stringify sorunu)

**🔧 Code Review (Confirm Ritual):**
- ✅ Syntax validation: Tüm Python dosyaları compile edildi
- ✅ Backend review: Error handling, parameterized queries, route ordering
- ✅ Frontend review: `isInitialized` flag eklendi (duplicate listener önleme)
- ✅ CSS review: No inline styles

**📁 Değişen Dosyalar:**
- `frontend/assets/js/modules/permissions_manager.js`

---

### 🎯 v2.20.4 (2026-01-29) - Çoklu Seçim UI/UX İyileştirmeleri ✨

**🎨 UI/UX İyileştirmeleri:**
- ✅ Eşleşme skoru dosya adının ÜSTÜNDE gösterilir (kullanıcı isteği)
- ✅ Dosya adları tıklanabilir indirme linki haline getirildi (📥 simgesi ile)
- ✅ "Bu çözümler işinize yaradı mı?" bölümü ayrı renk kategorisinde gösteriliyor
- ✅ Mor/Violet tema ile feedback section vurgusu

**🔧 Backend Değişiklikleri:**
- ✅ `GET /api/rag/download/{file_name}` - Dosya adı ile indirme endpoint'i
- ✅ `_format_multi_solution` - Yeni format düzeni

**📁 Değişen Dosyalar:**
- `app/services/dialog_service.py` - Format değişiklikleri
- `app/api/routes/rag_files.py` - Download by name endpoint
- `frontend/assets/js/modules/dialog_chat.js` - Markdown link desteği
- `frontend/assets/css/dialog-chat.css` - Download link ve feedback section stilleri

---

### 🎯 v2.20.3 (2026-01-29) - Çoklu Seçim Detay Gösterimi 📋

**🔧 Bug Fix:**
- ✅ "Tümünü Seç" ile çoklu seçimde detay içerik gösterilmiyor sorunu düzeltildi
- ✅ `_format_multi_solution` fonksiyonu artık her seçim için tam `chunk_text` içeriği gösteriyor
- ✅ `similarity_score` → `score` key uyumsuzluğu düzeltildi

**📁 Değişen Dosya:**
- `app/services/dialog_service.py` - _format_multi_solution fonksiyonu

---

### 🎯 v2.20.0 (2026-01-29) - Dynamic RBAC Sistemi 🛡️

**🔐 Rol Bazlı Yetkilendirme (RBAC):**
- ✅ `role_permissions` tablosu ile dinamik yetki yönetimi
- ✅ 4 seviyeli granüler yetkiler: `can_view`, `can_create`, `can_update`, `can_delete`
- ✅ Hiyerarşik kaynak yapısı: Menü → Sekme (parent-child ilişkisi)
- ✅ Admin Immunity: Admin yetkileri korunmalı, değiştirilemez

**🎨 Yetki Yönetim Paneli (Frontend):**
- ✅ `permissions_manager.js` modülü (IIFE pattern, 411 satır)
- ✅ Hiyerarşik kaynak ağacı görselleştirmesi
- ✅ CRUD matris checkbox'ları
- ✅ Dirty state tracking (Kaydet butonu durumu)
- ✅ `VYRA_API` null-check koruması

**🔧 Backend API Endpoints:**
- ✅ `GET /api/permissions/roles` - Mevcut rolleri listele
- ✅ `GET /api/permissions/resources` - Hiyerarşik kaynak ağacı
- ✅ `GET /api/permissions/my/permissions` - Kullanıcı yetkileri
- ✅ `GET /api/permissions/{role_name}` - Rol yetkileri
- ✅ `POST /api/permissions/{role_name}` - Yetki güncelleme (Admin-only)

**⚠️ Route Ordering Ritual:**
- ✅ `/my/permissions` route'u `/{role_name}`'den ÖNCE tanımlı
- ✅ Traceable logging: DEBUG seviyesinde yetki sorguları loglanıyor
- ✅ Atomic upserts: ON CONFLICT ile veri bütünlüğü

**🎨 Modern SaaS Tasarım:**
- ✅ `permissions.css` (371 satır) - Glassmorphism, gradient efektler
- ✅ Responsive tasarım (768px breakpoint)
- ✅ Role selector butonları, checkbox grid'i, loading animasyonları

**📁 Yeni/Değişen Dosyalar:**
- `app/api/routes/permissions.py` (276 satır)
- `frontend/assets/js/modules/permissions_manager.js` (411 satır)
- `frontend/assets/css/permissions.css` (371 satır)
- `app/core/default_data.py` - Default permission seeding

---

### 🎯 v2.19.6 (2026-01-28) - RAG UX İyileştirmeleri ✨

**🔍 RAG Arama Kalite İyileştirmeleri:**
- ✅ 3 karakterli teknik terim desteği (APE, VPN, DNS, SQL vb.)
- ✅ Büyük harfli teknik terimler için akıllı bonus sistemi
- ✅ Exact match algoritmasında iyileştirmeler

**🎨 UI/UX Düzeltmeleri:**
- ✅ RAG çözüm seçiminde faydalı/faydasız butonları gösteriliyor
- ✅ "Çözüm Seçildi!" mesajlarında feedback butonları aktif
- ✅ Çözüm süre gösterimi (responseTime) tüm akışlarda çalışıyor:
  - Tek RAG sonucu durumu
  - Çoklu sonuçtan kart seçimi durumu

**📁 Etkilenen Dosyalar:**
- `app/services/rag_service.py` - Exact match bonus değişiklikleri
- `frontend/assets/js/modules/dialog_chat.js` - Feedback butonları
- `frontend/assets/js/home_page.js` - ResponseTime hesaplama

---

### 🎯 v2.19.2 - v2.19.5 (2026-01-28) - RAG Best Practices Modernization 🚀

**Tüm Document Processor'lar 2024 RAG Best Practices'e uygun hale getirildi:**

| Processor | Versiyon | Yeni Özellikler |
|-----------|----------|-----------------|
| **PDF** | v2.19.2 | Heading detection, Table detection, Semantic chunking |
| **PPTX** | v2.19.3 | Slide title extraction, Speaker notes, Semantic chunking |
| **TXT** | v2.19.4 | Heading detection (Markdown), Section chunking |
| **Excel** | v2.19.5 | API tutarlılığı, Zengin metadata |
| **DOCX** | v2.19.1 | Heading/metadata enrichment (önceden tamamlandı) |

**Ortak İyileştirmeler:**
- ✅ `extract_chunks()` metodu tüm processor'larda tutarlı
- ✅ `heading`, `chunk_index`, `source` metadata standardı
- ✅ `_fix_turkish_chars()` entegrasyonu
- ✅ Semantic chunking (paragraf/cümle sınırlarında bölme)

---


### v3.1.1 (2026-04-01) - Branding Parameterization — Full Bundle Cleanup 🏷️

**🔄 Parametrik Branding:**
- ✅ `websocket_client.js`: Bildirim metinleri `BrandingEngine.getAppName()` ile dinamik hale getirildi
- ✅ `ticket_history.js`: Default dialog başlığı (`NGSSAI Analiz Süreci`) parametrik yapıya kavuşturuldu
- ✅ `bundle.min.js`: Tüm kaynak dosyalar güncellendikten sonra `node build.mjs` ile yeniden build edildi (93 → 78 NGSSAI; kalan referanslar console.log prefix'leri ve BrandingEngine replace mekanizması)
- ✅ Cache busting `v3.1.1 → v3.1.2` ile tarayıcı cache bypass garantisi sağlandı

### v2.19.5 (2026-01-28) - Excel Processor Best Practices 📊

**🔄 API Tutarlılığı:**
- ✅ `extract_chunks(file_obj, file_name)` imzası diğer processor'larla uyumlu hale getirildi
- ✅ Geriye uyumluluk korundu (`file_path` opsiyonel parametre)

**📋 Zengin Metadata:**
- ✅ `heading` eklendi (Sheet adı heading olarak kullanılıyor)
- ✅ `chunk_index` eklendi
- ✅ `source` eklendi (dosya adı)
- ✅ Mevcut: `sheet`, `row`, `header_row`, `type`

**📝 Dokümantasyon:**
- ✅ Docstring'ler güncellendi
- ✅ Versiyon v3.0 → v3.1

---

### v2.19.4 (2026-01-28) - TXT Processor Best Practices 📝

**🔍 Heading Detection:**
- ✅ Markdown heading desteği (`#`, `##`, `###`)
- ✅ BÜYÜK HARF başlık tespiti
- ✅ Numaralı başlıklar (1. Başlık, 1.1 Alt Başlık)
- ✅ Separator tespiti (`===`, `---`, `***`)

**🇹🇷 Türkçe Karakter Düzeltme:**
- ✅ `_fix_turkish_chars()` tüm fonksiyonlara entegre edildi

**🧠 Semantic Chunking:**
- ✅ Heading bazlı section bölümleme
- ✅ Paragraf ve cümle sınırlarında bölme
- ✅ `line_start` metadata'sı

**📋 Yeni Metodlar:**
- `_is_heading()` - Heading tespiti
- `_is_separator()` - Separator kontrolü
- `_extract_sections()` - Section bölümleme
- `_split_large_content()` - Semantic bölme
- `extract_chunks()` - PDF/DOCX/PPTX ile tutarlı format

---

### v2.19.3 (2026-01-28) - PPTX Processor Best Practices 📽️

**🎯 Slide Title Extraction:**
- ✅ Title placeholder ile başlık tespiti
- ✅ Fallback: En büyük kısa text shape

**📝 Speaker Notes Desteği:**
- ✅ Konuşmacı notları ayrı chunk olarak ekleniyor
- ✅ `type: "speaker_notes"` metadata

**🧠 Semantic Chunking:**
- ✅ Slayt bazlı zengin metadata
- ✅ Tablo içeriği ayrı tespit (`has_table` flag)
- ✅ Büyük içerik paragraf sınırlarında bölünüyor

**📋 Yeni Metodlar:**
- `_get_slide_title()` - Slayt başlığı çıkarma
- `_get_speaker_notes()` - Konuşmacı notları
- `_extract_slide_content()` - Zengin slayt içeriği
- `_split_content()` - Paragraf bazlı bölme
- `extract_chunks()` - PDF/DOCX ile tutarlı format

---

### v2.19.2 (2026-01-28) - PDF Processor Best Practices 📄

**🔍 Heading Detection:**
- ✅ Regex pattern ile heading tespiti (BÜYÜK HARF, 1. Numaralı, Madde X vb.)
- ✅ Türkçe heading desteği (GİRİŞ, SONUÇ, ÖZET, Bölüm, Kısım)
- ✅ Sayfa numarası tracking ve metadata'ya ekleme

**📊 Table Detection:**
- ✅ Pipe karakteri (|) ile tablo tespiti
- ✅ Tab karakteri ile ayrılmış sütunlar tespiti
- ✅ `is_table` metadata flag'i

**🧠 Semantic Chunking:**
- ✅ Heading'lere göre bölümleme (`_extract_sections_with_headings`)
- ✅ Semantic section split (`_split_large_section`)
- ✅ Paragraf ve cümle sınırlarında bölme
- ✅ Min 50 karakter chunk kontrolü

**📋 Yeni Metodlar:**
- `_detect_heading()` - Satırın heading olup olmadığını tespit eder
- `_detect_table_content()` - Tablo yapısı kontrolü
- `_extract_sections_with_headings()` - Metni heading bazlı bölümler
- `_split_large_section()` - Büyük section'ları semantic böler
- `extract_chunks()` - DOCX ile tutarlı zengin metadata çıktısı

---

### v2.19.1 (2026-01-28) - RAG DOCX Metadata Enrichment 📄

**🔍 RAG Sonuç Kartları Zenginleştirme:**
- ✅ **Dosya türü ikonları**: DOCX (mavi), PDF (kırmızı), XLSX (yeşil) vb. renkli ikonlar
- ✅ **Heading gösterimi**: DOCX bölüm başlıkları mor renkte kart üzerinde
- ✅ **Chunk önizleme**: İlk 200 karakter fallback olarak gösteriliyor
- ✅ **Metadata akışı**: Backend'den frontend'e zengin metadata taşınıyor

**🛠️ Backend Değişiklikleri:**
- ✅ `rag_service.py` - SQL sorgularına `file_type` eklendi
- ✅ `dialog_service.py` - `file_type` ve `heading` extraction

**🎨 Frontend Değişiklikleri:**
- ✅ `dialog_chat.js` - `getFileTypeIcon()` fonksiyonu (12 dosya türü destekli)
- ✅ `dialog-chat.css` - `.card-file-icon` ve `.card-heading` stilleri

**📋 2024 Best Practices Uyumluluğu:**
- ✅ Metadata transparency
- ✅ Visual differentiation
- ✅ Hierarchical context
- ✅ Fallback preview

---

### v2.19.0 (2026-01-28) - RAG Multi-Select & UI Enhancements 🎯

**✨ Çoklu Kart Seçimi:**
- ✅ RAG sonuç kartlarından **birden fazla seçim** yapılabilir
- ✅ **Tümünü Seç** checkbox'ı eklendi
- ✅ "X Seçimi Gönder" dinamik buton etiketi
- ✅ Seçilen kartlar görsel olarak vurgulanıyor (checkbox + border)

**🎨 Modern Çözüm Formatı:**
- ✅ Çoklu seçimlerde her çözüm ayrı **card formatında** gösteriliyor
- ✅ Detaylar (Uygulama Adı, Keyflow Search, vb.) düzenli listeleniyor
- ✅ Ham chunk yerine okunabilir, modern SaaS tasarımı

**🔧 Diğer İyileştirmeler:**
- ✅ "İlgimi Çekmiyor" butonu RAG seçim kartlarına eklendi
- ✅ "VYRA'ya sor +" butonu boş durumda pasif (animasyon durur)
- ✅ Textarea kartlarda seçim beklenirken devre dışı + placeholder güncelleniyor

**📋 Değişiklikler:**
- `frontend/assets/js/modules/dialog_chat.js` - toggleCardSelection, toggleSelectAll, handleMultiSelect
- `frontend/assets/css/dialog-chat.css` - Çoklu seçim stilleri
- `app/api/routes/dialog.py` - QuickReplyRequest.selection_ids
- `app/services/dialog_service.py` - multi_select action, _format_multi_solution

---

### v2.18.2 (2026-01-28) - ML Training Fixes & Scheduler 🤖

**🐛 CatBoost Eğitim Script Düzeltmeleri:**
- ✅ Windows encoding hatası düzeltildi (emoji karakterleri kaldırıldı)
- ✅ `LEFT JOIN` ile chunk olmayan feedback'ler dahil edildi
- ✅ `CatBoostRanker` → `CatBoostRegressor` (tek grup sorunu çözüldü)
- ✅ Veri çeşitliliği kontrolü eklendi (en az 2 farklı feedback tipi gerekli)
- ✅ Anlamlı hata mesajları: "Yeterli feedback çeşitliligi yok"

**⚙️ Otomatik Eğitim Scheduler:**
- ✅ 5 dakikada bir schedule koşulları kontrol ediliyor
- ✅ Koşul sağlanırsa otomatik eğitim tetikleniyor
- ✅ `_run_schedule_checker()` arka plan thread'i
- ✅ Uygulama kapanırken temiz shutdown

**🎨 Frontend İyileştirmeleri:**
- ✅ "Modeli Şimdi Eğit" butonu sayfa yüklenince pasif başlıyor
- ✅ Eğitim sırasında buton pasif kalıyor
- ✅ \"Başarısız\" üzerine gelince **tooltip ile hata mesajı** (ilk 500 karakter)

**🔧 Backend Düzeltmeleri:**
- ✅ `fetchone()[0]` → `fetchone()["id"]` (RealDictCursor uyumu)
- ✅ Debug log eklendi: `/ml/training/start` endpoint

**📋 Değişiklikler:**
- `scripts/train_model.py` - CatBoostRegressor, veri kontrolü, encoding fix
- `app/api/main.py` - Schedule checker thread
- `app/services/ml_training_service.py` - RealDictCursor fix
- `app/api/routes/system.py` - Debug logging
- `frontend/assets/js/modules/ml_training.js` - Buton state, tooltip

---

### v2.18.1 (2026-01-27) - Textarea Auto Resize 📝

- ✅ Shift+Enter ile satır eklendiğinde textarea **otomatik büyüyor**
- 📏 Max 6 satıra kadar genişler, sonra scroll aktif olur
- 🔄 Mesaj gönderilince textarea boyutu resetlenir

---

### v2.18.0 (2026-01-27) - Dialog Chat UI Enhancement ✨

**🎨 Yeni Özellik:**
- ✅ Sohbet tamamlandığında (İyi günler dilerim mesajı) + butonu **parlayan animasyonla** vurgulanıyor
- 🏷️ "VYRA'ya sor" yazısı buton yanında beliriyor
- 🔄 Yeni sohbet başlatıldığında animasyon otomatik resetleniyor

**📋 Değişiklikler:**
- `frontend/assets/css/dialog-chat.css` - Pulse-glow animasyonu ve label stilleri
- `frontend/home.html` - VYRA'ya sor label span'ı
- `frontend/assets/js/modules/dialog_chat.js` - highlightNewDialogButton / resetNewDialogButtonHighlight

---

### v2.17.9 (2026-01-27) - LLM Exception Handling 🛡️

**🐛 Critical Bug Fix:**
- ✅ VPN hatası olduğunda **artık ticket'a kaydedilmiyor**!
- 🔧 `call_llm_api()` fonksiyonu artık hata durumunda exception fırlatıyor (return yerine raise)
- 📢 Özel exception sınıfları eklendi: `LLMConnectionError`, `LLMConfigError`, `LLMResponseError`

**📋 Değişiklikler:**
- `app/core/llm.py` - Exception class'ları ve hata yönetimi güncellendi

**🔄 Etki:**
- Geçmiş Çözümler → Corpix AI Değerlendirmesi → VPN hatası = Popup gösterilir, kayıt yapılmaz

---

### v2.17.8 (2026-01-27) - Unified VPN Error Handling 🌐

**🔧 İyileştirmeler:**
- ✅ "Geçmiş Çözümler" sekmesindeki Corpix AI değerlendirmesinde VPN popup eklendi
- 🔗 Tüm modüller artık **aynı global fonksiyonları** kullanıyor (kod çoklaması yok):
  - `window.isVPNNetworkError()` → VPN hata tespiti
  - `window.showVPNErrorPopup()` → VPN popup gösterimi
- 📍 Kullanılan modüller: dialog_chat.js, ticket_chat.js, ticket_history.js, websocket_client.js

**📋 Değişiklikler:**
- `frontend/assets/js/ticket_history.js` - requestLLMEvaluationForHistory error handling
- `frontend/assets/js/modules/dialog_chat.js` - notification icon fix (vyra_logo.png)

---

### v2.17.7 (2026-01-27) - Dialog Chat VPN Error Popup 🌐

**🐛 Bug Fix:**
- ✅ "VYRA'ya Sor" sekmesinde VPN hatası oluştuğunda popup gösterilmiyor → Düzeltildi
- 🔍 HTTP response error ve network error durumlarında `isVPNNetworkError()` kontrolü eklendi
- 📢 VPN hatası tespit edildiğinde `showVPNErrorPopup()` çağrılıyor

**📋 Değişiklikler:**
- `frontend/assets/js/modules/dialog_chat.js` - handleSendMessage error handling güncellendi

---

### v2.17.6 (2026-01-27) - New Request Button Fix 🔧

**🐛 Bug Fix:**
- ✅ "Yeni Destek Talebi" butonuna tıklandığında textarea artık yazılabilir duruma geçiyor
- 📝 Çözüm sağlandıktan sonra `problemText.disabled = true` yapılıyordu, buton sıfırlamıyordu
- 🔗 `TicketChatModule.reset()` artık buton tarafından çağrılıyor

**📋 Değişiklikler:**
- `frontend/assets/js/home_page.js` - newRequestBtn handler güncellendi
- `frontend/assets/js/modules/solution_display.js` - disabled = false eklendi

---

### v2.17.5 (2026-01-27) - RAG Performance Improvements 🎯

**🔍 Arama İyileştirmeleri:**
- ✅ `_is_technical_term()`: Teknik rol isimlerini tespit eder (SC_380_KURUMSAL_MUSTERILER...)
- ✅ `_calculate_exact_match_bonus()`: Tam eşleşme için +0.5 bonus
- ✅ 3 bileşenli skor: Semantic + Exact Match + Fuzzy
- ✅ Teknik terimler için %50+ skor artışı

**📋 Değişiklikler:**
- `app/services/rag_service.py` - 2 yeni helper, skor hesaplama güncellendi

---

### v2.17.4 (2026-01-27) - Dialog Service Refactor 🔧

**🐛 Kritik Bug Fix:**
- ✅ RAG araması "bilgi bulunamadı" döndürüyordu - f-string syntax hatası düzeltildi
- ✅ Log mesajındaki format specifier hatası tüm aramaları bozuyordu
- ✅ Exception handler hatayı sessizce yutuyordu - detaylı traceback eklendi

**🧹 Clean Code Refactor:**
- `_perform_rag_search()`: Ayrı fonksiyon, güvenli hata yakalama, traceback loglama
- `_extract_ocr_texts()`: OCR işlemini izole eden helper
- `_build_response()`: Yanıt oluşturma mantığını ayıran helper
- `process_user_message()`: Sadece akış kontrolü yapan temiz ana fonksiyon

**📋 Değişiklikler:**
- `app/services/dialog_service.py` - Modüler refactor + kritik bug fix

---

### v2.17.3 (2026-01-27) - VPN Error Popup 🌐

**Modern SaaS VPN Hata Popup'ı:**
- ✅ LLM bağlantı hatalarında (443, DNS resolution) kullanıcı dostu popup
- ✅ "Corpix desteği için, şirket VPN ya da Wi-Fi açık olmalıdır" mesajı
- ✅ Teknik detayları (HTTPSConnectionPool, port=443, vb.) gizliyor
- ✅ Wi-Fi ikonu ile görsel uyarı

**VPN Hata Tespiti:**
- `isVPNNetworkError()` utility fonksiyonu eklendi
- HTTPSConnectionPool, port=443, NameResolutionError, getaddrinfo failed gibi hata kalıpları tespit ediliyor
- Tüm hata noktalarında (ticket, LLM evaluation, WebSocket) entegre

**Dosya Değişiklikleri:**
- `frontend/assets/js/modal.js` - `vpnError()` metodu ve `network` icon tipi
- `frontend/assets/css/modal.css` - `.vyra-modal-icon.network` stili
- `frontend/assets/js/home_page.js` - `isVPNNetworkError()`, `showVPNErrorPopup()` ve hata yakalama
- `frontend/assets/js/modules/ticket_chat.js` - VPN hata kontrolü
- `frontend/assets/js/websocket_client.js` - VPN hata kontrolü

---

### v2.17.1 (2026-01-27) - Single Result Feedback Icons 👍

**Feedback İkon Düzeltmesi:**
- ✅ "Bilgi Tabanından Buldum!" mesajlarında artık 👍/👎 ikonları görünüyor
- 📝 Tek sonuç bulunduğunda kullanıcı faydalı/faydasız geri bildirimi verebiliyor

**Dosya Değişiklikleri:**
- `frontend/assets/js/modules/dialog_chat.js` - isSolutionMessage koşulu genişletildi

---

### v2.17.0 (2026-01-27) - Excel Merge Cell Support & RAG Performance 📊

**Excel Merge Hücre Desteği:**
- ✅ `_build_merge_value_map()` fonksiyonu eklendi - merge range'leri için (row, col) → value haritası
- ✅ `_resolve_merged_values()` fonksiyonu eklendi - satırdaki None değerleri merge map'ten dolduruyor
- ✅ `_chunks_from_openpyxl()` güncellendi - merge hücreler alt satırlara taşınıyor
- 📝 **Sorun:** E sütununda merge edilmiş "Yetki Hakkında Bilgi" RAG chunk'larına eksik kaydediliyordu
- 🎯 **Çözüm:** openpyxl `merged_cells.ranges` API ile merge değerleri tüm ilgili satırlara yayılıyor

**RAG Performans İyileştirmesi:**
- ✅ Lazy Fuzzy Boost: `semantic_score >= 0.5` ise fuzzy hesaplama atlanıyor
- 📈 Daha hızlı yanıt süresi - gereksiz string matching işlemleri kaldırıldı

**Dosya Değişiklikleri:**
- `app/services/document_processors/excel_processor.py` - Merge hücre desteği
- `app/services/rag_service.py` - Lazy fuzzy boost optimizasyonu

---

### v2.16.0 (2026-01-27) - Modern SaaS Corpix AI UI & Chat Enhancements 🎨

**Modern SaaS Corpix AI Değerlendirmesi:**
- ✅ "Corpix ile Değerlendir" butonu premium tasarıma güncellendi:
  - Glassmorphism efekti (backdrop-filter blur)
  - Multi-layer gradient arka plan
  - Hover glow efekti (shine animation)
  - Box-shadow layers ile derinlik
- ✅ "Corpix AI Değerlendirmesi" sonuç kutusu yeniden tasarlandı:
  - Premium gradient header
  - Sol accent çizgi (4px mor gradient)
  - Icon glow efekti
  - Uppercase title with letter-spacing
- ✅ İçerik formatlaması geliştirildi:
  - `.llm-paragraph`: Border-left ile vurgulanmış paragraflar
  - `.llm-steps-list`: Numaralı adımlar (mor gradient badges)
  - `code`: Dosya yolları için monospace stil
  - Key-Value formatı: Bold labels

**Chat UI İyileştirmeleri:**
- ✅ "Başka bir sorunuz var mı?" butonları - yanıt verildiyse disabled görünüyor
- ✅ Feedback butonları (👍/👎) sadece "Çözüm Bulundu!" mesajında gösteriliyor
- ✅ Diğer mesajlarda (çoklu sonuç, harika mesajı) sadece 🔊 hoparlör kalıyor

**Metin Değişiklikleri:**
- ✅ "AI Çözüm Önerisi" → "VYRA ÇÖZÜMÜ"
- ✅ "Birden fazla ilgili kayıt buldum" → "Vyra birden fazla ilgili kayıt buldu"

**Backend LLM Formatlaması:**
- ✅ `_format_llm_response_html()` modern SaaS stiline güncellendi
- ✅ Numaralı listeleri `<ol class="llm-steps-list">` olarak çeviriyor
- ✅ Dosya yollarını `<code>` içinde gösteriyor
- ✅ Key: Value formatını bold etiketlerle vurguluyor
- ✅ Paragrafları `<div class="llm-paragraph">` ile stilize ediyor

**Dosya Değişiklikleri:**
- `frontend/assets/css/home.css` - LLM stilleri modernize
- `frontend/assets/css/ticket-history.css` - LLM stilleri modernize
- `frontend/assets/css/dialog-chat.css` - Disabled buton stilleri
- `frontend/assets/js/modules/dialog_chat.js` - Feedback filtreleme, buton disable
- `frontend/assets/js/ticket_history.js` - VYRA ÇÖZÜMÜ metni, format fonksiyonu
- `app/services/dialog_service.py` - Metin değişikliği, answered flag
- `app/api/routes/tickets.py` - Modern LLM HTML formatlaması

---

### v2.15.1 (2026-01-26) - OCR & Duplicate Message Fixes 🔧

**OCR Sistemi Düzeltmeleri:**
- ✅ EasyOCR bağımlılığı `D:\VYRA\.venv` ortamına yüklendi
- ✅ Görsel yapıştırma sonrası OCR metin çıkarma çalışıyor
- ✅ RAG aramasında temiz OCR metni kullanılıyor (`[Görsel]` etiketleri kaldırıldı)
- ✅ Yüksek RAG skorları (%76+) elde ediliyor

**Duplicate Mesaj Sorunu Çözümü:**
- ✅ `dialog_chat.js` → `isInitialized` flag eklendi
- ✅ `showSection("dialog")` her çağrıldığında event listener'lar tekrar eklenmiyordu
- ✅ Tek mesaj → Tek yanıt garantisi

**Diğer İyileştirmeler:**
- ✅ `image_handler.js` → Paste debounce (500ms) eklendi
- ✅ `websocket_client.js` → `isWaitingForResponse` kontrolü eklendi
- ✅ WebSocket/HTTP race condition önlendi

**Teknik Değişiklikler:**
- `dialog_chat.js` → `init()` fonksiyonunda duplicate event listener önleme
- `dialog_service.py` → `raw_ocr_texts` listesi ile temiz OCR araması
- `image_handler.js` → `lastPasteTime` ile debounce
- `websocket_client.js` → `isWaitingForResponse()` kontrolü

---

### v2.15.0 (2026-01-26) - WebSocket Dialog Notifications 🔔

**Gerçek Zamanlı Bildirim Sistemi:**
- ✅ WebSocket üzerinden VYRA yanıt bildirimi
- ✅ Browser notification desteği (sayfa arkaplandayken)
- ✅ Notification'a tıklayınca "VYRA'ya Sor" sekmesine yönlendirme
- ✅ Global notification ikonu - her sayfada sağ üst köşede görünür (fixed)

**WebSocket Bağlantı Durumu Göstergesi:**
- ✅ "VYRA Asistan" başlığı altında canlı durum göstergesi
- ✅ 🟢 Çevrimiçi (WebSocket bağlı) - yeşil animasyonlu dot
- ✅ 🔴 Çevrimdışı (WebSocket kopuk) - kırmızı statik dot
- ✅ Otomatik yeniden bağlanma (5 deneme, exponential backoff)

**Dialog UI İyileştirmeleri:**
- ✅ Çözüm mesajı yapısı yeniden düzenlendi:
  - Detaylı çözüm içeriği
  - "Bu çözüm işinize yaradı mı?" + feedback butonları (👍/👎/🔊)
  - Ayırıcı çizgi (altın sarısı gradient)
  - "Başka bir sorunuz var mı?" + Evet/Hayır butonları (en altta)

**Backend:**
- ✅ `dialog.py` → `send_message` endpoint async yapıldı
- ✅ `websocket_manager.py` → `send_dialog_message()`, `send_dialog_typing()` fonksiyonları
- ✅ Route seviyesinde WebSocket bildirimi (`await ws_manager.send_dialog_message()`)

**Frontend:**
- ✅ `websocket_client.js` → `handleDialogMessage()`, `updateConnectionStatus()`
- ✅ `dialog_chat.js` → `addMessageFromWS()`, `askMoreHtml` render mantığı
- ✅ `dialog-chat.css` → `.ask-more-section`, `.status-dot` stilleri
- ✅ `notification.js` → `globalNotificationArea` öncelikli kullanım
- ✅ `notification.css` → `.global-notification-container` stili

---

### v2.14.1 (2026-01-26) - Smart Excel Processor + Response Time ⏱️

**Excel Processor v3 - Akıllı Header Tespiti:**
- ✅ Genel amaçlı header satırı algılama (6 farklı Excel yapısı desteklenir)
- ✅ 5 kriterli skorlama algoritması:
  - Dolu hücre sayısı (3-10 arası ideal)
  - Ortalama hücre uzunluğu (kısa = header)
  - Sayısal olmama oranı
  - Benzersizlik oranı
  - Tipik header kelimeleri (ad, tip, tarih, bilgi, yetki, vb.)
- ✅ Açıklama satırlarını otomatik atlama
- ✅ Satır bazlı chunking (`**Header:** Değer` formatı)
- ✅ Aktif sütun tespiti (boş sütunlar hariç tutulur)

**DOCX Processor İyileştirmesi:**
- ✅ Paragraf ve tablo içerikleri anlamlı formatta chunk'lanıyor
- ✅ Heading bazlı section gruplandırma
- ✅ Tablo satırları ayrı chunk olarak işleniyor

**Response Time Gösterimi (Frontend):**
- ✅ AI yanıt süresini mesaj bubble'ında gösterme
- ✅ Yeşil badge formatı: `[🕐 2.34s]`
- ✅ `performance.now()` API ile hassas ölçüm

**Teknik:**
- `excel_processor.py` → `_detect_header_row()` fonksiyonu eklendi
- `docx_processor.py` → `extract_chunks()` metodu eklendi
- `base.py` → `process_bytes()` custom chunking desteği
- `dialog_chat.js` → Response time hesaplama ve gösterim
- `dialog-chat.css` → `.response-time` stilleri

---

### v2.14.0 (2026-01-25) - Dialog Chat System ("VYRA'ya Sor") 💬

**Yeni WhatsApp Tarzı Chat Arayüzü:**
- ✅ "VYRA'ya Sor" sekmesi (1. sırada, varsayılan aktif)
- ✅ Çoklu mesaj alışverişi - dialog oturumu DB'de saklanır
- ✅ Sol: VYRA yanıtları (koyu gri baloncuk), Sağ: Kullanıcı (mavi baloncuk)
- ✅ Mesaj altında saat gösterimi (HH:mm formatı)

**Sesli Etkileşim (Web Speech API):**
- ✅ 🎤 Mikrofon butonu - Türkçe ses tanıma (STT)
- ✅ 🔊 Hoparlör butonu - Türkçe sesli okuma (TTS)
- ✅ Konuşurken animasyonlu buton durumu

**Görsel & OCR Desteği:**
- ✅ 📎 Dosya ekleme butonu
- ✅ Ctrl+V ile görsel yapıştırma
- ✅ OCR sonucu AI yanıtına dahil edilir

**AI Akıllı Yanıt:**
- ✅ Çoklu doküman eşleşmesinde seçim butonları
- ✅ Hızlı yanıt butonları (Evet/Hayır)
- ✅ 👍/👎 ML feedback entegrasyonu

**Backend:**
- ✅ `dialogs` tablosu - dialog oturumları
- ✅ `dialog_messages` tablosu - mesaj geçmişi
- ✅ `dialog_service.py` - Dialog iş mantığı + RAG + OCR
- ✅ `dialog.py` routes - 8 API endpoint
- ✅ 6 yeni index (performans)

**Frontend:**
- ✅ `dialog-chat.css` - WhatsApp tarzı UI (~520 satır)
- ✅ `dialog_chat.js` - Chat modülü (~770 satır)
- ✅ `home.html` - Yeni sekme ve section
- ✅ `home_page.js` - Tab yönetimi güncellendi

---

### v2.13.1 (2026-01-25) - ML Training Admin Panel & Hibrit Schedule 🎓

**Model Eğitim Yönetimi:**
- ✅ Parametreler → "Model Eğitim" sekmesi (sadece admin)
- ✅ Stats kartları: Toplam feedback, aktif model, son eğitim, bekleyen feedback
- ✅ "Modeli Şimdi Eğit" butonu ile anlık eğitim başlatma
- ✅ Eğitim geçmişi tablosu (tarih, tür, süre, sonuç)

**Hibrit Otomatik Eğitim Koşulları:**
- ✅ Feedback Sayısı: 100/250/500/1000 feedback sonrası tetikle
- ✅ Zaman Aralığı: 3/7/14/30 gün sonra tetikle
- ✅ Kalite Düşüşü: %80/%70/%60/%50 altına düşerse tetikle
- ✅ Her koşul için ayrı toggle - herhangi biri sağlanırsa eğitim başlar

**Backend:**
- ✅ `ml_training_service.py` - Eğitim yönetim servisi
- ✅ `ml_training_jobs` tablosu - Eğitim geçmişi
- ✅ `ml_training_schedules` tablosu - Hibrit zamanlanmış görevler
- ✅ 6 yeni API endpoint (stats, start, status, history, schedule get/post)
- ✅ `get_all_schedules()` - Çoklu schedule desteği
- ✅ `save_hybrid_schedules()` - 3 koşulu birden kaydet
- ✅ `check_scheduled_trigger()` - OR mantığıyla tetikleme kontrolü

**Frontend:**
- ✅ `ml_training.js` - Admin panel modülü
- ✅ Modern SaaS tasarımda hibrit schedule UI
- ✅ Her koşul için ayrı toggle ve değer seçimi

---

### v2.13.0 (2026-01-25) - CatBoost Hybrid Reranking + Feedback UI 🤖

**Hibrit CatBoost + RAG Sistemi:**
- ✅ CatBoost tabanlı reranking modeli entegrasyonu
- ✅ 12 feature'lı feature extraction pipeline
- ✅ Geniş arama (top 20) → CatBoost reranking → Final sonuç (top 5)
- ✅ Model yoksa graceful fallback (mevcut RAG davranışı)
- ✅ Kişiselleştirme: Kullanıcı topic affinitesi

**Feedback Loop Sistemi:**
- ✅ `user_feedback` tablosu - kullanıcı geri bildirimleri
- ✅ `user_topic_affinity` tablosu - topic bazlı kullanıcı tercihleri
- ✅ `ml_models` tablosu - model versiyonlama
- ✅ `POST /api/feedback` - feedback kaydetme endpoint
- ✅ `GET /api/users/me/affinity` - kullanıcı profili endpoint

**Frontend Feedback UI:**
- ✅ Çözüm kutusunda 👍/👎 butonları (Modern SaaS tasarım)
- ✅ Glassmorphism efektli hover animasyonları
- ✅ Toast ile feedback onayı
- ✅ Kopyalama işleminde otomatik feedback

**Admin ML Yönetimi:**
- ✅ `GET /api/system/ml/status` - Model durumu
- ✅ `POST /api/system/ml/reload` - Model yeniden yükleme
- ✅ `POST /api/system/ml/clear-cache` - Cache temizleme

**Model Eğitim:**
- ✅ `scripts/train_model.py` - CatBoost model eğitim scripti
- ✅ Feedback verilerinden otomatik eğitim
- ✅ Model versiyonlama ve aktif model yönetimi

**Yeni Dosyalar:**
- `app/services/catboost_service.py` - CatBoost reranking servisi
- `app/services/feature_extractor.py` - Feature extraction
- `app/services/feedback_service.py` - Feedback yönetimi
- `app/services/user_affinity_service.py` - User affinity
- `app/api/routes/feedback.py` - Feedback API routes
- `scripts/train_model.py` - Model eğitim scripti
- `tests/test_catboost_service.py` - Unit testler

**Dependencies:**
- `catboost>=1.2.0`
- `rapidfuzz>=3.0.0`

---

### v2.12.0 (2026-01-25) - Modern SaaS Tab UI & Multi-Image 🎨

**Yeni Modern Tab Tasarımı:**
- ✅ Tab'lar modern SaaS tasarımına dönüştürüldü (rounded, gradient)
- ✅ Her tab'a favori yıldız (⭐) ikonu eklendi
- ✅ Favori tab localStorage ile kalıcı hale getirildi
- ✅ Sayfa yüklenince ve sidebar'dan dönünce favori tab otomatik açılıyor
- ✅ Favori tıklandığında otomatik sekme geçişi

**Yeni Gönder Butonu (Inline):**
- ✅ "Çözüm Öner" butonu kaldırıldı
- ✅ Textarea içinde sağ altta inline gönder butonu (paper-plane icon)
- ✅ Attach (📎) ikonu gönder butonunun solunda
- ✅ Boşken pasif (gri), yazı yazılınca aktif (sarı gradient)

**Çoklu Görsel Desteği:**
- ✅ Maksimum 5 görsel eklenebilir
- ✅ Grid önizleme alanı (thumbnail'lar)
- ✅ Tekil görsel kaldırma (X butonu)
- ✅ "Tümünü Kaldır" butonu  
- ✅ Duplicate dosya kontrolü
- ✅ Çoklu dosya seçimi desteği

**Yaramaz Çocuk Animasyonu:**
- ✅ "Hadi başlayalım vyra vyra 😊" yazısına modern animasyon
- ✅ 10 saniyede bir otomatik hareketlenme
- ✅ Emoji zıplama, brand büyüme, text titreme efektleri

**Bug Fixes:**
- ✅ Duplicate script yüklemeleri temizlendi (console hataları düzeltildi)
- ✅ Attach butonu 2 kere tıklama sorunu düzeltildi
- ✅ Sidebar Ana Sayfa favori tab sorunu düzeltildi

---

### v2.11.5 (2026-01-25) - UI Disable During Upload 🔒

**Kullanıcı Deneyimi İyileştirmeleri:**
- ✅ Dosya yüklenirken "Hedef Org Grupları" kalem butonu disable oluyor
- ✅ Dosya yüklenirken drop-zone (sürükle-bırak alanı) disable oluyor
- ✅ Dosya yüklenirken "Yeniden Oluştur" butonu disable oluyor
- ✅ Yükleme tamamlandığında tüm UI elementleri otomatik aktif oluyor

**Teknik:**
- `setUploadingState(bool)` fonksiyonu eklendi
- `uploadFiles()` başında ve finally bloğunda çağrılıyor

---

### v2.11.4 (2026-01-25) - RAG Upload Flow Fixes (Pending Files) 🚀

**Kullanıcı Deneyimi Düzeltmeleri:**
- ✅ Org seçimi olmadan dosya sürükle-bırak/seçim yapılırsa, dosyalar hafızaya alınıyor (`pendingFiles`)
- ✅ Org seçimi tamamlandığında bekleyen dosyalar **otomatik olarak** yükleniyor
- ✅ Org seçili değilken "Dosya Yükle" alanına tıklandığında önce Org seçimi yapılıyor, ardından otomatik olarak dosya seçim diyaloğu açılıyor
- ✅ Kullanıcının "dosya seçtim ama yüklenmedi" sorunu çözüldü

---

### v2.11.3 (2026-01-25) - RAG Upload Logic Fixes 🐛

**Düzeltmeler:**
- ✅ RAG dosya yükleme sonrası org seçiminin sıfırlanması iptal edildi (seri yükleme kolaylığı)
- ✅ Dosya yükleme başarılı/hata durumunda çift toast mesajı gösterilmesi sorunu düzeltildi
- ✅ Hedef Org Grubu seçili ise "Open Screen" (Org Modal) tekrar açılmıyor, doğrudan dosya yüklemeye devam edilebiliyor

---

### v2.11.2 (2026-01-25) - No-Org User Warning 🚫

**Yeni Özellikler:**
- ✅ Kullanıcının aktif org tanımı yoksa "Çözüm Öner" butonunda uyarı
- ✅ Mesaj: "Doküman organizasyon yetkiniz bulunamamıştır"
- ✅ Yeni endpoint: `GET /users/me/organizations` - kullanıcının org listesi

**Değişiklikler:**
- `ticket_chat.js` → `suggestSolution()` fonksiyonuna org kontrol eklendi
- `user_profile.py` → `/me/organizations` endpoint eklendi

---

### v2.11.1 (2026-01-25) - 🔒 RAG Org Active Security Fix

**Kritik Güvenlik Düzeltmesi:**
- ✅ RAG aramada pasif organizasyonların dokümanları artık filtreleniyor
- ✅ `organizations.is_active = false` olan org'ların dokümanları arama sonuçlarına dahil edilmiyor
- ✅ Kullanıcının org'u pasif yapıldığında o org'un dokümanlarına erişim kesiliyor

**Değişiklikler:**
- `rag_service.py` → `search()` fonksiyonunda org aktiflik kontrolü eklendi
- Hem kullanıcı org atamasında hem de doküman sorgusunda `is_active = true` filtresi uygulanıyor

---

### v2.11.0 (2026-01-25) - File Org Modal & Upload Pre-Check 📝

**Bilgi Tabanı Dosya Org Düzenleme Modalı:**
- ✅ Arama kutusu eklendi (org kodu veya adı ile arama)
- ✅ Arama temizleme butonu (X) eklendi
- ✅ Pagination eklendi (tek sayfa bile gösteriliyor)
- ✅ Toplam kayıt sayısı sol altta gösteriliyor
- ✅ Seçili sayısı badge olarak gösteriliyor
- ✅ İptal butonu sol, Kaydet butonu sağ alt footer layout

**Dosya Yükleme Org Ön Kontrolü:**
- ✅ Hedef org seçilmeden dosya yükleme engellendi
- ✅ Toast uyarısı: "Önce hedef org grubu seçiniz"
- ✅ Otomatik org seçim modalı açılıyor

**Diğer İyileştirmeler:**
- ✅ ORG badge'larına tooltip (hover ile uzun ad) eklendi
- ✅ File dialog duplicate açılma sorunu düzeltildi

---

### v2.10.0 (2026-01-25) - Complete Frontend Modularization 🎨

**7 Yeni Frontend Modülü:**
- ✅ `modules/llm_module.js` - LLM CRUD işlemleri
- ✅ `modules/prompt_module.js` - Prompt CRUD işlemleri
- ✅ `modules/image_handler.js` - Görsel yapıştırma, sürükle-bırak
- ✅ `modules/sidebar_module.js` - Sidebar navigasyon
- ✅ `modules/param_tabs.js` - Parametre sekmeleri
- ✅ `modules/solution_display.js` - Çözüm formatlama ve gösterimi
- ✅ `modules/ticket_chat.js` - Çözüm öner, WebSocket entegrasyonu

**Mimari:**
- IIFE pattern ile encapsulation
- Window scope'a modül namespace'leri eklendi
- home.html'de script yükleme sırası optimize edildi

---

### v2.9.1 (2026-01-25) - Frontend Modularization 🎨

**Frontend Modülerleştirme:**
- ✅ `modules/llm_module.js` - LLM CRUD işlemleri (IIFE pattern, ~300 satır)
- ✅ `modules/prompt_module.js` - Prompt CRUD işlemleri (IIFE pattern, ~280 satır)
- ✅ `modules/image_handler.js` - Görsel yapıştırma, sürükle-bırak (~150 satır)

**Değişiklikler:**
- home.html'de modüller script olarak eklendi
- Modüller paralel çalışabilir yapıda tasarlandı
- Window scope'a LLMModule, PromptModule, ImageHandler olarak eklendi

---

### v2.9.0 (2026-01-25) - Modular Backend Architecture 🏗️

**Backend Modülerleştirme:**
- ✅ `db.py` refactoring (539 → 150 satır):
  - `app/core/schema.py` - PostgreSQL tablo şemaları
  - `app/core/default_data.py` - Varsayılan veriler ve insert fonksiyonu
  
- ✅ `rag.py` refactoring (675 → 23 satır):
  - `app/api/schemas/rag_schemas.py` - 10 Pydantic model
  - `app/api/routes/rag_upload.py` - Dosya yükleme (dosya türüne göre processor)
  - `app/api/routes/rag_search.py` - Semantik arama ve istatistikler
  - `app/api/routes/rag_files.py` - Dosya listeleme, indirme, silme
  - `app/api/routes/rag_rebuild.py` - Embedding yeniden oluşturma
  
- ✅ `users.py` refactoring (485 → 18 satır):
  - `app/api/schemas/user_schemas.py` - 11 Pydantic model
  - `app/api/routes/user_admin.py` - Admin kullanıcı yönetimi
  - `app/api/routes/user_profile.py` - Self-service profil işlemleri

**Yeni Klasör Yapısı:**
```
app/
├── api/
│   ├── routes/
│   │   ├── rag.py (aggregator)
│   │   ├── rag_upload.py
│   │   ├── rag_search.py
│   │   ├── rag_files.py
│   │   ├── rag_rebuild.py
│   │   ├── users.py (aggregator)
│   │   ├── user_admin.py
│   │   └── user_profile.py
│   └── schemas/
│       ├── __init__.py
│       ├── rag_schemas.py
│       └── user_schemas.py
└── core/
    ├── db.py (refactored)
    ├── schema.py (NEW)
    └── default_data.py (NEW)
```

**Kazanımlar:**
- 📉 Toplam 1700+ satır kod → modülerleştirildi
- 🔧 Bakım kolaylığı - her modül tek sorumluluk
- 🧪 Test edilebilirlik artırıldı
- 📚 Kod okuma ve navigasyon kolaylaştırıldı

---

### v2.8.4 (2026-01-25) - Organization-Based RAG & Ticket Authorization 🔒

**RAG Arama Org Filtreleme:**
- ✅ `run_worker()` → `user_id` parametresi eklendi
- ✅ `search_knowledge_base()` → `user_id` parametresi eklendi
- ✅ `RAGService.search()` kullanıcının tüm org'larını alıp filtreliyor (birden fazla org destekli)
- ✅ Sadece yetkili org'lardaki + legacy dokümanlar aranıyor

**Geçmiş Çözümler Org Filtreleme:**
- ✅ `tickets` tablosuna `source_org_ids INTEGER[]` sütunu eklendi
- ✅ Ticket oluşturulurken kullanıcının mevcut org'ları kaydediliyor
- ✅ Geçmiş sorgulandığında `source_org_ids && user_orgs` kesişim kontrolü
- ✅ Kullanıcı org değiştirirse eski ticket'ları göremez

**Kullanıcı Onay Akışı İyileştirmesi:**
- ✅ `handleApprove` - Org seçilmeden onay engellleniyor
- ✅ Uyarı mesajı: "Önce organizasyon grubu seçin!"

---

### v2.8.3 (2026-01-25) - Modern SaaS Search UI & Bug Fixes 🎨🔧

**Modern SaaS Arama Kutuları:**
- ✅ Tüm arama kutuları modern tasarıma güncellendi:
  - 🔍 Sol tarafta arama ikonu
  - 🎨 Gradient arka plan (indigo → mor)
  - ✨ Focus'ta glow efekti
  - ❌ Yuvarlak kırmızı temizle butonu (hover efektli)
- ✅ RAG Dosyalar: Arama butonu kaldırıldı (yazarken arıyor)
- ✅ Yetkilendirme Paneli: Debounce arama eklendi
- ✅ Organizasyon Yönetimi: Modern tasarım uygulandı

**CORS Genişletme:**
- ✅ `localhost:8001`, `localhost:8002`, `localhost:3000` eklendi
- ✅ `null` origin (file:// protokolü) eklendi

**Bug Fixes:**
- 🐛 Organizations GET endpoint SQL hatası düzeltildi (`do` → `doc_org` alias)
- 🐛 `do` PostgreSQL reserved keyword sorunu çözüldü

---

### v2.8.2 (2026-01-25) - Pagination & Search Enhancements 📄🔍

**Pagination Sistemi:**
- ✅ Her ekranda tutarlı pagination: ⏮️ İlk | ◀️ Önceki | **N/M** | Sonraki ▶️ | Son ⏭️
- ✅ Tek kayıt olsa bile pagination gösteriliyor
- ✅ Sayfa başına max 10 kayıt

**Organizasyon Yönetimi:**
- ✅ Pagination İlk/Son sayfa butonları

**Yetkilendirme Paneli:**
- ✅ Backend pagination desteği (page, per_page params)
- ✅ Frontend pagination ve toplam sayı footer
- ✅ `PATCH /users/{id}/organizations` - Kullanıcı org güncelleme API (DB kayıt)
- 🐛 Kullanıcı org değişikliği artık veritabanına kaydediliyor

**Bilgi Tabanı (RAG):**
- ✅ Dosya arama kutusu (dosya adı ile ILIKE arama)
- ✅ Arama temizleme (X) butonu
- ✅ Backend pagination/search desteği
- ✅ Pagination footer

---

### v2.8.1 (2026-01-25) - UI/UX Enhancements & Bug Fixes 🎨

**Organizasyon Yönetimi UI:**
- ✅ Arama temizle (X) butonu eklendi
- ✅ Footer: Sol'da "Toplam: X kayıt" + Sağ'da pagination
- ✅ Debounce süresi 300ms → 150ms (daha hızlı arama)

**Bilgi Tabanı (RAG) Geliştirmeleri:**
- ✅ Hedef Org Grupları: Sayfa açılışında boş başlıyor
- ✅ Dosya yükleme sonrası org seçimi sıfırlanıyor
- ✅ Yüklü dosyalar tablosuna org düzenleme kalemi 📝 eklendi
- ✅ `PATCH /rag/files/{id}/organizations` - Dosya org güncelleme API

**Yetkilendirme Paneli:**
- ✅ Kullanıcı listesinde gerçek org grupları gösteriliyor
- ✅ `list_users` artık her kullanıcının org gruplarını döndürüyor

**Veritabanı Index Bakımı:**
- ✅ 9 yeni index eklendi (ticket_messages, solution_logs, system_logs, uploaded_files, rag_chunks)
- ✅ Toplam 33 index tanımlı (11 tablo için)

**Bug Fixes:**
- 🐛 Authorization panelinde ORG-DEFAULT fallback sorunu düzeltildi

---

### v2.8.0 (2026-01-24) - Organization-Based Authorization 🔒
**Yeni Özellikler:**
- ✅ Organizasyon bazlı dokümantasyon yetkilendirme sistemi
- ✅ Organizations CRUD API (Admin only)
- ✅ User-Organization binding (Many-to-Many)
- ✅ Document-Organization binding (Many-to-Many)
- ✅ RAG search org filtering (KRİTİK GÜVENLİK)
- ✅ Organization Management UI modülleri (JS + CSS)

**Database Changes:**
- **Yeni Tablolar:**
  - `organization_groups` - Organizasyon grup tanımları
  - `user_organizations` - Kullanıcı-org ilişkisi
  - `document_organizations` - Doküman-org ilişkisi
- **Indexes:** Performance için 6 yeni index
- **Varsayılan Veriler:** ORG-DEFAULT, ORG-ADMIN

**Güvenlik:**
- 🔒 RAG aramaları artık kullanıcının org yetkilerine göre filtrelenir
- 🔒 Backend enforcement (frontend filtresi YOK - güvenilmez)
- 🔒 Legacy dokümanlar (org atanmamış) tüm kullanıcılara açık kalır

**API Changes:**
- `POST /api/organizations` - Yeni org oluştur
- `GET /api/organizations` - Org listele (pagination, search)
- `PUT /api/organizations/{id}` - Org güncelle
- `DELETE /api/organizations/{id}` - Org sil
- `POST /api/users/approve` - `org_ids` parametresi eklendi
- RAG search artık `user_id` parametresi ile çağrılıyor

**Migration Guide:**
```bash
# 1. PostgreSQL ve Python çalıştır
.\start_simple.ps1

# 2. Migration otomatik çalışır (init_db())
# 3. Varsayılan org grupları ve admin binding oluşturulur
```

---

### v2.7.1 (2026-01-23) - Ticket History Enhancements
- ✅ Ticket history pagination (per_page: 10)
- ✅ Search (title, description filtering)
- ✅ Turkish date picker (tarih aralığı seçimi)
- ✅ Modern SaaS UI refresh

### v2.7.0 (2026-01-22) - RAG System Upgrade
- ✅ PostgreSQL-based RAG (embedding FLOAT[] array)
- ✅ Atomic transaction support (dosya + embedding tek işlem)
- ✅ Fuzzy matching (rapidfuzz integration)
- ✅ Embedding cache (LRU)
- ✅ Binary file storage (BYTEA)

### v2.6.0 (2026-01-20) - Authorization System
- ✅ User approval workflow
- ✅ Role-based access control (Admin/User)
- ✅ Toast notifications
- ✅ Modern authorization panel

### v2.5.0 (2026-01-18) - Parameters Module
- ✅ LLM configuration management
- ✅ Prompt template designer
- ✅ System reset functionality

### v2.0.0 (2026-01-15) - PostgreSQL Migration
- ✅ SQLite → PostgreSQL migration
- ✅ Connection pooling
- ✅ Transaction support
- ✅ RealDictCursor (dict-like rows)

---

## 🛠️ Teknoloji Stack

### Backend
- **Framework:** FastAPI 0.115.12
- **Database:** PostgreSQL 17.2
- **ORM:** Raw SQL (psycopg2-binary 2.9.10)
- **AI/ML:** 
  - sentence-transformers 3.3.1
  - rapidfuzz 3.11.0 (fuzzy matching)
- **Auth:** JWT (python-jose)
- **Utils:** 
  - PyPDF2, python-docx, openpyxl, python-pptx
  - Pillow (image processing)

### Frontend
- **Core:** Vanilla JavaScript (ES6+)
- **CSS:** Custom CSS + Utility Classes
- **Icons:** FontAwesome 6.x

---

## 📁 Proje Yapısı

```
vyra_l1_fastapi/
├── app/
│   ├── api/
│   │   ├── main.py                    # FastAPI app factory
│   │   ├── routes/
│   │   │   ├── rag.py                 # RAG aggregator (v2.9.0)
│   │   │   ├── rag_upload.py          # Dosya yükleme
│   │   │   ├── rag_search.py          # Semantik arama
│   │   │   ├── rag_files.py           # Dosya yönetimi
│   │   │   ├── rag_rebuild.py         # Embedding rebuild
│   │   │   ├── users.py               # User aggregator
│   │   │   ├── user_admin.py          # Admin işlemleri
│   │   │   ├── user_profile.py        # Profil self-service
│   │   │   ├── organizations.py       # Org CRUD
│   │   │   ├── tickets.py             # Ticket CRUD
│   │   │   └── ...
│   │   └── schemas/                   # Pydantic models
│   │       ├── rag_schemas.py         # RAG schemas (v2.9.0)
│   │       └── user_schemas.py        # User schemas
│   │
│   ├── core/
│   │   ├── config.py                  # Settings
│   │   ├── db.py                      # PostgreSQL (refactored v2.9.0)
│   │   ├── schema.py                  # SQL schemas (v2.9.0)
│   │   ├── default_data.py            # Default data (v2.9.0)
│   │   └── cache.py                   # LRU cache
│   │
│   └── services/
│       ├── ai_service.py              # LLM integration
│       ├── rag_service.py             # RAG search
│       └── logging_service.py         # Centralized logging
│
├── frontend/
│   ├── home.html                      # Main dashboard
│   └── assets/js/
│       ├── modules/                   # Modüler bileşenler (v2.10.0)
│       │   ├── llm_module.js          # LLM CRUD
│       │   ├── prompt_module.js       # Prompt CRUD
│       │   ├── image_handler.js       # Görsel işleme
│       │   ├── sidebar_module.js      # Navigasyon
│       │   ├── param_tabs.js          # Sekme yönetimi
│       │   ├── solution_display.js    # Çözüm formatlama
│       │   └── ticket_chat.js         # LLM chat
│       ├── home_page.js               # Koordinatör
│       ├── rag_upload.js              # RAG modülü
│       ├── authorization.js           # Auth modülü
│       └── org_module.js              # Org modülü
│
├── pgsql/                             # Embedded PostgreSQL
├── start_simple.ps1                   # Başlatma
├── stop_simple.ps1                    # Durdurma
└── README.md
```

---

## 🚦 Kurulum ve Çalıştırma

### Gereksinimler
- Python 3.11+
- PowerShell (Windows)
- Git

### 1. Projeyi Klonlayın
```bash
git clone <repo-url>
cd vyra_l1_fastapi
```

### 2. Virtual Environment Oluşturun
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Bağımlılıkları Yükleyin
```powershell
pip install -r requirements.txt
```

### 4. Uygulamayı Başlatın
```powershell
.\start_simple.ps1
```

**İlk başlatmada:**
- PostgreSQL başlar (port 5005)
- Database şeması oluşturulur
- Varsayılan admin user oluşturulur
- Backend başlar (port 8002)
- Frontend başlar (port 5500)
- Tarayıcı otomatik açılır

### Varsayılan Giriş Bilgileri
- **Kullanıcı Adı:** admin
- **Şifre:** admin1234

---

## 🔐 Organizasyon Yönetimi (v2.8.0)

### Konsept
- Her kullanıcı bir veya birden fazla **organizasyon grubuna** atanabilir
- Her doküman bir veya birden fazla **organizasyon grubuna** atanabilir
- RAG aramaları sırasında kullanıcılar **sadece yetkili oldukları org gruplarındaki** dokümanlara erişebilir

### Varsayılan Organizasyonlar
- **ORG-DEFAULT:** Genel kullanıcılar için
- **ORG-ADMIN:** Admin kullanıcılar için

### Kullanıcı Onaylama (User Approval)
Admin, yeni kullanıcıları onaylarken organizasyon gruplarını da atar:

```json
POST /api/users/approve
{
  "user_id": 123,
  "role_id": 2,
  "is_admin": false,
  "org_ids": [1, 3]  // ORG-DEFAULT ve ORG-IT
}
```

### RAG Güvenlik
```python
# Backend - rag_service.py
def search(query: str, user_id: int):
    # 1. Kullanıcının org_ids'ini al
    # 2. Sadece yetkili org gruplarındaki dosyaların chunk'larını getir
    # 3. Legacy dosyalar (org atanmamış) tüm kullanıcılara açık
    ...
```

**Önemli:** Frontend filtresi YOK. Güvenlik tamamen backend'de enforce ediliyor.

---

## 📊 Database Schema (v2.8.0)

### Yeni Tablolar

**organization_groups**
```sql
CREATE TABLE organization_groups (
    id SERIAL PRIMARY KEY,
    org_code VARCHAR(50) UNIQUE NOT NULL,
    org_name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**user_organizations (Many-to-Many)**
```sql
CREATE TABLE user_organizations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id INTEGER NOT NULL REFERENCES organization_groups(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER REFERENCES users(id),
    UNIQUE(user_id, org_id)
);
```

**document_organizations (Many-to-Many)**
```sql
CREATE TABLE document_organizations (
    id SERIAL PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    org_id INTEGER NOT NULL REFERENCES organization_groups(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER REFERENCES users(id),
    UNIQUE(file_id, org_id)
);
```

---

## 🧪 Test

### API Test
```powershell
# Health check
Invoke-RestMethod -Uri "http://localhost:8002/api/health"

# Login
$resp = Invoke-RestMethod -Uri "http://localhost:8002/api/auth/login" `
    -Method POST `
    -Body (@{username="admin"; password="admin1234"} | ConvertTo-Json) `
    -ContentType "application/json"

$token = $resp.access_token
$headers = @{Authorization = "Bearer $token"}

# List organizations
Invoke-RestMethod -Uri "http://localhost:8002/api/organizations" -Headers $headers
```

### RAG Search Test
```powershell
# RAG search (org filtered)
$body = @{query="şifre sıfırlama"; n_results=5} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8002/api/rag/search" `
    -Method POST `
    -Headers $headers `
    -Body $body `
    -ContentType "application/json"
```

---

## 📝 Geliştirme Kuralları

### 1. Database Migration
- Tüm schema değişiklikleri `app/core/db.py` içinde `SCHEMA_SQL` değişkeninde yapılır
- Migration otomatik (`init_db()` - IF NOT EXISTS)
- Versiyon numarası `config.py` içinde güncellenir

### 2. Backend
- **Router:** `app/api/routes/` altında modüler
- **Service:** İş mantığı `app/services/` altında
- **Auth:** `get_current_user`, `get_current_admin` dependency kullan
- **Log:** `log_system_event()` ile tüm işlemleri logla

### 3. Frontend
- **JavaScript:** Vanilla JS (ES6+), modüler yapı
- **CSS:** Inline CSS YASAK (global/module CSS kullan)
- **Modal:** ESC support + overlay click koruması

### 4. Git Workflow
```bash
# Versiyon güncelleme
# 1. config.py → APP_VERSION
# 2. README.md → Changelog
# 3. Git commit

git add .
git commit -m "v2.8.0: Organization-based authorization system"
git push
```

---

## 🐛 Troubleshooting

### PostgreSQL başlamıyor
```powershell
# Manuel start
cd pgsql
.\bin\pg_ctl.exe -D .\data start

# Port kontrolü
netstat -an | findstr "5005"
```

### Backend hatası
```powershell
# Log kontrolü
.\stop_simple.ps1
.\start_simple.ps1  # Terminalde hatayı gör
```

### Frontend yüklenmiyor
- Tarayıcı cache temizle (Ctrl+Shift+Delete)
- `http://localhost:5500` manuel açmayı dene

---

## 📞 Destek

**Geliştirici:** Yasın Fazlıoğlu  
**E-posta:** yasin.fazlioglu@consultant.turkcell.com.tr  
**Versiyon:** 3.1.0 (Enrichment-Aware Routing + Hallucination Guard)

---

## 📜 Lisans

Bu proje Turkcell Teknoloji için geliştirilmiştir.
