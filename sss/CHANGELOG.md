# 📝 VYRA L1 Support — Değişiklik Günlüğü (Changelog)

Tüm önemli değişiklikler bu dosyada tarihsel sırayla kaydedilir.
Format: [Semantic Versioning](https://semver.org/)

---

## [v3.3.0] — 2026-04-03

### 🆕 Eklenen
- **C5: Enhancement Progress WebSocket:** LLM iyileştirme sırasında bölüm bazlı gerçek zamanlı ilerleme (WebSocket)
- **A4: Dosya Versiyonlama:** `uploaded_files` tablosuna `file_version`, `is_active`, `file_hash` sütunları — soft-delete ile versiyon takibi
- **A8: pgvector Migration:** `FLOAT[]` → `vector(384)` güvenli migration (extension yoksa atlanır) + IVFFlat index
- **D1: Enhancement Impact API:** `GET /enhancement-impact` — maturity skor karşılaştırma raporu
- **C6: PDF Font Koruması:** PyMuPDF ile orijinal PDF font boyutu tespit edilerek enhanced çıktıda korunuyor

### ⚡ İyileştirilen
- **A2: NumPy Dedup:** `_deduplicate_chunks()` O(n²) pure-Python → NumPy vectorized matris çarpımı (~100x hız)
- **A7: Paralel Processing:** `_process_files_background()` sıralı → `asyncio.gather` ile concurrent dosya işleme

### 📁 Yeni API
- `GET /api/rag/enhancement-impact` — Enhancement etki ölçüm raporu (before/after skor, iyileşme yüzdesi)

### 📁 Değişen Dosyalar (10 dosya)
- `app/core/config.py`, `app/core/schema.py`, `app/api/routes/rag_enhance.py`, `app/api/routes/rag_upload.py`
- `app/services/document_enhancer.py`, `app/services/rag/service.py`
- `frontend/assets/js/websocket_client.js`, `frontend/assets/js/modules/document_enhancer_modal.js`
- `frontend/assets/css/modules/document_enhancer_modal.css`

### 🐛 Düzeltilen (Code Review)
- **Import Hatası (rag_enhance.py):** `log_warning` import eksikti → NameError crash düzeltildi
- **Import Hatası (rag_enhance.py):** `get_db_conn` scope dışı kullanım → inline import eklendi
- **Tanımsız Fonksiyon (rag_upload.py):** `_log()` → `log_system_event()` ile değiştirildi (2 yer)
- **KeyError (rag_upload.py):** Retry flow'da `file_data` → `file_content` düzeltildi
- **KeyError (rag_upload.py):** `current_user["user_id"]` → `current_user["id"]` düzeltildi
- **Dict Key Hatası (rag_upload.py):** `maturity_map` key'i `file_name` → `file_id` düzeltildi
- **SQL Eksik Sütun (rag_enhance.py):** `enhancement_history` INSERT'te `user_id` sütunu eksikti
- **Schema Senkron (schema.py):** `enhancement_history` tablosu ve `uploaded_files` migration sütunları eklendi

---

## [v2.52.1] — 2026-03-05

### 🔧 Düzeltme
- **Enhance API Fix:** `window.API_BASE` → `window.API_BASE_URL` + auth token key düzeltmesi
- **Enhance Validation Bypass:** Kısa kaynak metin (< 500 char) için halüsinasyon kontrolü atlanıyor
- **CatBoost Bypass Fix:** Minimum içerik uzunluğu 80 → 300 char (kısa chunk'lar LLM'e yönlendirilir)
- **log_system_event İmza Hatası:** Eksik `level` parametresi eklendi (dialog.py)

### 🆕 Yeni Özellik
- **`[NO_MATCH]` Token Filtreleme:** LLM prompt'una "bilgi yoksa `[NO_MATCH]` yaz" direktifi eklendi — %100 güvenilir ilgisizlik algılama
- **Streaming Buffer:** İlk 15 token buffer'lanıyor — `[NO_MATCH]` tespit edilirse kullanıcıya gönderilmeden durdurulur
- **"Vyra ile Sohbet Et" Butonu:** İlgisiz sonuçlarda Corpix sohbet moduna geçiş butonu (mor gradient)
- **Marker Yedek Filtre:** `[NO_MATCH]` gelmezse 12 Türkçe ilgisizlik ifadesiyle fallback kontrol

### 🧠 İyileştirme
- **Dinamik Grounding Eşiği:** Chunk uzunluğuna göre (< 200 → 0.05, < 500 → 0.10, ≥ 500 → 0.15)

---

## [v2.52.0] — 2026-03-05

### 🧠 İyileştirme
- **ML Pipeline Quality:** Intent-bazlı prompt, per-question mimari, streaming LLM, 2000 char context, post-processing, refinement
- **UPSERT + Kalite Koruma:** `add()` → UPSERT, `_compute_answer_quality_score()` (0-100), eski iyi cevap korunur
- **GENERAL Intent Fix:** Stem matching ile Türkçe çekim eki toleransı, eşikler düşürüldü
- **Training Samples UX:** `has_learned_answer` EXISTS subquery (duplicate yok), cevap ikonu

### 🔧 Düzeltilen
- **Connection Leak:** `add()` finally bloğu eklendi
- **Dead Code:** `_get_existing_questions()` kaldırıldı

### 🧪 Test
- 507/507 test başarılı — 5 yeni UPSERT testi

---

## [v2.51.1] — 2026-03-04

### 🎯 İyileştirme
- **CL Soru Kalitesi:** LLM promptuna dosya bağlamı eklendi, halüsinasyon eşiği %20→%40, post-generation grounding filtresi
- **Cevap Önizleme:** Eğitim örneklerinde "Cevap" butonu — VyraModal ile öğrenilmiş cevap görüntüleme
- **XSS Koruması:** Learned answer preview'da `escapeHtml()` uygulandı
- **Login:** Turkcell Active Directory otomatik seçili hale getirildi
- **Reset:** `document_images` + `learned_answers` tabloları sıfırlamaya eklendi

### 🧪 Test
- 475/475 test başarılı — 0 regresyon

---

## [v2.51.0] — 2026-03-04

### 🧠 Eklenen
- **Learned Q&A Cache (Tier 1):** `learned_answers` tablosu + `LearnedQAService` — CL eğitimi sırasında LLM cevap üretimi + semantik sorgu eşleştirme (~100ms)
- **Vyra Önerisi:** CatBoost bypass sonrası "Vyra önerisi al" butonu → LLM ile cevap iyileştirme endpoint'i
- **4 katmanlı yanıt:** Cache → Learned QA → CatBoost Bypass → LLM

### 🧪 Test
- 62/62 test başarılı — 0 regresyon

---

## [v2.50.0] — 2026-03-04

### ⚡ Eklenen
- **LLM Streaming (SSE):** `call_llm_api_stream()` + `process_stream()` + `POST .../messages/stream` endpoint — token-by-token yanıt
- **Redis Persistent Cache:** `RedisCache` sınıfı — `deep_think` cache restart'ta korunur (fallback: in-memory)
- **CatBoost Direct Answer:** `combined_score ≥ 0.75` → LLM bypass, RAG chunk direkt dönüş (~3s)

### 📁 Yeni Dosyalar
- `app/core/redis_cache.py`, `tests/test_llm_streaming.py`

### 🧪 Test
- 62/62 test başarılı (7 streaming + 33 deep_think + 22 dialog)

---

## [v2.46.0] — 2026-03-03

### 🔐 Eklenen
- **LDAP/Active Directory Entegrasyonu:** 3 adımlı auth (Service Bind → User Search → User Bind) + Direct Bind Fallback
- **Dual-Auth:** Domain seçimi ile LDAP veya lokal (sadece admin) kimlik doğrulama
- **AES-256 Fernet şifreleme:** LDAP bind password’ları veritabanında şifreli
- **Admin Panel LDAP Yönetimi:** CRUD API + 3 aşamalı bağlantı testi + Modern SaaS UI
- **Organizasyon senkronizasyonu:** LDAP’tan gelen yeni org’lar otomatik oluşturuluyor
- **Otomatik kullanıcı oluşturma:** LDAP doğrulanan kullanıcılar auto-create + auto-approve

### 🛡️ Güvenlik
- XSS koruması: innerHTML sanitize (`_esc()` helper)
- Password None crash guard, verify_password güvenliği
- `_assign_user_org` ayrı DB context (stale cursor önleme)

### 🧪 Test
- 15 yeni LDAP unit test, 468/468 toplam test başarılı

### 📁 Yeni Dosyalar
- `app/core/encryption.py`, `app/services/ldap_auth.py`, `app/api/routes/ldap_settings.py`
- `frontend/assets/js/modules/ldap_settings.js`, `frontend/assets/css/modules/ldap_settings.css`
- `tests/test_ldap_auth.py`

---

## [v2.45.1] — 2026-02-16

### 🔧 Düzeltilen
- **Alakasız görsel filtreleme:** Görseller sadece primary source dosyasından alınıyor — DB ilişkisi (`file_id`) ile kesin eşleştirme

---

## [v2.45.0] — 2026-02-16

### ⏱️ Düzeltilen
- **CL Interval Fix:** `get_continuous_learning_service()` singleton artık `system_settings`'ten `cl_interval_minutes` okuyor — restart sonrası korunuyor
- **Countdown Timer:** `_thread_start_time` ile ilk çalışma için de gerçek ISO tarih — "Yakında..." yerine MM:SS geri sayım

### 🤖 Eklenen
- **Manuel Eğitim LLM Desteği (`train_model.py` v2.0):** SyntheticDataGenerator + FeatureExtractor + adversarial koruma + halüsinasyon filtresi + CatBoostClassifier
- **Countdown Timer UI:** `startNextRunCountdown()` fonksiyonu, `.cl-countdown` CSS animasyonu
- **Training samples kaydı:** Manuel eğitim sonuçları `ml_training_samples` tablosuna

### 🔧 Değişen
- **CatBoostRegressor → CatBoostClassifier:** Manuel eğitim artık CL ile aynı model tipini kullanıyor
- **6 placeholder feature kaldırıldı:** FeatureExtractor ile gerçek 15 feature

### 🎨 UI Fix
- **Özet wrap fix:** `📋 Özet:` artık `dt-section` olarak render ediliyor — `white-space: nowrap` kesme sorunu çözüldü
- **OCR hover tooltip fix:** Tooltip `document.body`'ye taşındı — `overflow-x: hidden` parent kesme sorunu çözüldü, `position: fixed` ile konumlandırma

---

## [v2.44.0] — 2026-02-16

### 🤖 Eklenen
- **LLM Destekli Sentetik Veri:** Chunk içeriğine özel gerçekçi Türkçe sorular (template fallback)
- **Halüsinasyon Filtresi:** LLM soruları %20+ keyword overlap kontrolünden geçiriliyor
- **Adversarial Feedback Koruması:** Negatif oy + yüksek benzerlik = şüpheli → eğitimden çıkar
- **Zengin Metadata:** heading, quality_score, topic_label eğitim verisinde gerçek değerler
- **Hard/Easy Negatives:** Aynı topic farklı dosya + farklı topic'ten negatif örnekler
- **Gerçek Feedback Entegrasyonu:** user_feedback tablosundan eğitim verisi

### 🔧 Değişen
- **CatBoost Ağırlıkları:** 0.7/0.3 → 0.5/0.5 (model olgunlaştıkça ayarlanabilir)
- **Skor Çeşitlendirmesi:** Sabit 0.85 → keyword overlap'a göre 0.55-0.95

### 🧪 Test
- 10 yeni test: halüsinasyon, adversarial, negatif örnek seçimi, skor çeşitlendirme

## [v2.43.0] — 2026-02-16

### 📄 Eklenen
- **PyMuPDF Font-Aware Heading Detection:** Font size, bold, italic ile heading tespiti (Faz 2)
- **Heading Hiyerarşi (Breadcrumb Path):** `heading_path` ve `heading_level` metadata — PDF + DOCX (Faz 3)
- **Tablo Yapısal Metadata:** `table_id`, `column_headers`, `row_count` + heading context (Faz 5)
- **Header/Footer Temizleme:** %50+ sayfa tekrarı filtreleme, sayfa numarası temizleme (Faz 6)
- **TOC Tespiti:** İçindekiler bölümü `type: toc` olarak işaretleme (Faz 6)
- **Chunk Deduplication:** Cosine similarity 0.95+ ile dosya-içi duplicate chunk kaldırma (Faz 7)
- **Cross-File Deduplication:** Farklı dosyalardaki duplicate chunk tespiti (DB son 1000 chunk) (Faz 7)
- **Görsel-Chunk Eşleme:** PyMuPDF ile sayfa bazlı görsel pozisyonu + `image_refs` metadata (Faz 4)
- **DOCX Görsel Tespiti:** XML namespace tabanlı heading-image eşlemesi (Faz 4)

### 🔧 İyileştirilen
- **Quality Score:** Bilgi yoğunluğu (keyword diversity +0.1, entity density +0.05), bağlam bütünlüğü (heading overlap +0.1), TOC cezası (-0.3), dil karışıklığı (-0.1)
- **Async Upload:** `run_in_executor` ile CPU-bound işlemler thread pool'a taşındı (Faz 1)

### 🧪 Test
- 91 unit test — `test_pdf_processor.py` (30), `test_docx_processor.py` (11), `test_rag_service.py` (50)

---

## [v2.40.0] — 2026-02-13

### 🖼️ Eklenen
- **Paragraf-Pozisyon Bazlı Görsel Yerleştirme:** PDF/DOCX'ten çıkarılan görsellere `paragraph_index` ve `page_y_position` kaydediliyor, paragraflar arası doğru konuma yerleştiriliyor
- **Inline Görsel Koruma:** `_update_paragraph_text` orijinal DOCX görselleri koruma (WML+WP namespace kontrolü)

### 🏗️ İyileştirilen
- **DRY Refactoring:** `_map_images_to_sections()`, `_organize_images_at_positions()`, `_get_section_text()` yardımcıları ile ~110 satır tekrarlanan kod kaldırıldı
- **`para_start`/`para_end` Tutarlılığı:** Tüm extract fonksiyonları (`_extract_docx_sections`, `_split_text_by_headings`, `_extract_xlsx_sections`, `_extract_pptx_sections`) artık paragraf aralığı döndürüyor

### 🧪 Test
- 10 yeni test (TestHelperFunctions) → toplam 83 birim testi, 0 failure ✅

---

## [v2.39.0] — 2026-02-12

### 🆕 Eklenen
- **Asenkron RAG Upload:** Dosya yükleme artık UI'ı bloke etmeden arkaplanda işleniyor
- **WebSocket Bildirimleri:** `rag_upload_complete` / `rag_upload_failed` mesajları ile gerçek zamanlı geri bildirim
- **Status Takibi:** `uploaded_files` tablosuna `status` sütunu (`processing`, `completed`, `failed`) eklendi
- **Processing Spinner:** Dosya listesinde işlenen dosyalar için animasyonlu spinner gösterimi
- **Bildirim Navigasyonu:** `VyraNotification` ile bildirme tıklandığında Bilgi Tabanı sekmesine yönlendirme (`navigateToRag`)
- **Browser Notification:** Sayfa arka plandayken tarayıcı bildirimi gösterimi

### 🔧 Değiştirilen
- `rag_upload.py`: Senkron upload → iki aşamalı asenkron (senkron kayıt + `asyncio.ensure_future` background task)
- `rag_upload.js`: `uploadFiles()` → 202 Accepted ile anında dönüş
- `notification.js`: `add()` → `targetSection` parametresi, `navigateToRag()` fonksiyonu
- `websocket_client.js`: `handleRagUploadComplete()`, `handleRagUploadFailed()` handler'ları
- `rag_file_list.js`: `renderFileRow()` → status badge desteği (processing/failed)
- `rag_upload.css`: Status badge, pulse animasyon ve satır stilleri

---

## [v2.38.4] — 2026-02-12

### 🔍 İyileştirilen
- **Feedback Veri Zenginleştirme:** `user_feedback` tablosuna `query_text` (kullanıcı sorusu) ve `dialog_id` kaydediliyor — ML öğrenme verisi tamamlandı
- **DB Şema:** `user_feedback` tablosuna `dialog_id INTEGER` sütunu eklendi

### 🧹 Temizlik
- **Pyflakes Temizlik (15 dosya, 34+ fix → 0 uyarı):** Unused imports, f-string placeholder, unused variables giderildi
- **DB system_logs Sütun Fix:** HTTP middleware artık `log_request()` kullanıyor — `request_path`, `request_method`, `response_status` sütunları doluyor
- **Feature Improvement:** `feature_extractor.py` — `heading` değişkeni `has_heading_match` feature olarak CatBoost'a besleniyor

---

## [v2.38.3] — 2026-02-12

### 🔍 İyileştirilen
- **RAG TOC Domination Fix:** İçindekiler tablosu chunk'ları BM25'te baskın → `_is_toc_chunk()` algılama + 3 katmanlı ceza sistemi
- **Query Preprocessing:** Türkçe soru ekleri (`nelerdir`, `nedir`) temizlenerek embedding kalitesi artırıldı
- **Score Gap Threshold:** 10→25 — daha fazla ilgili sonuç döndürülüyor

### 📈 Etki
- "Atama Türleri nelerdir?" → 1 sonuç (TOC) → 3 sonuç (gerçek içerik)

---

## [v2.38.2] — 2026-02-11

### 🐛 Düzeltilen
- **Image Serve 404:** Split-port (5500/8002) mimarisinde relative img src → absolute backend URL rewriting
- **OCR Popup API_BASE:** `window.location.origin` → backend port detection

---

## [v2.38.1] — 2026-02-11

### 🐛 Düzeltilen
- **Fallback rag_results:** `_single_synthesis` / `_chunked_synthesis` → `_fallback_response` artık `rag_results` alıyor
- **Test mock fix:** `test_pdf_conversion_fallback_on_error` — `patch.object` kullanımına geçildi
- **Pyflakes cleanup:** f-string placeholder uyarıları, unused import

### 🧪 Test
- 262 passed, 0 failed ✅

---

## [v2.38.0] — 2026-02-11

### ✨ Eklenen
- **Deep Think heading context:** `_prepare_context` artık heading bilgisini LLM'e aktarıyor
- **Parçalı LLM synthesis:** 12000+ karakter context otomatik parçalanıp birleştiriliyor
- **Heading bazlı image-chunk eşleştirme:** chunk_index yerine metadata heading ile eşleştirme

### 🔧 Düzeltilen
- **CSS overflow:** `.message-bubble` ve `.dt-response` responsive overflow kuralları
- **OCR batch logging:** Sessiz hata yakalama yerine detaylı loglama
- **PDF cümle bölme:** Türkçe-uyumlu regex ile cümle sınırlarında bölme
- **Fallback prompt:** Daha detaylı ve organize yanıtlar için güncelleme

### 🧪 Test
- 7 yeni test (heading context, chunked synthesis, PDF bölme) → toplam 85 test, 0 failure

---

## [v2.36.2] — 2026-02-11

### 🔧 Düzeltilen
- **PDF motoru:** `docx2pdf` (Word bağımlı) → `fpdf2` (saf Python) geçişi
- **Türkçe unicode:** Arial TTF ile tam karakter desteği, Helvetica fallback
- **Bold font edge case:** `arialbd.ttf` yoksa büyük boyut fallback
- **import os:** `document_enhancer.py`'de eksik import düzeltildi

### 🧪 Test
- `test_document_enhancer.py` — 23 unit test (tümü geçti)

---

## [v2.36.1] — 2026-02-10

### ✨ Eklenen
- **OCR Görsel Metin Çıkarma:** EasyOCR entegrasyonu ile DOCX/PDF/PPTX görsellerinden metin çıkarma
- **OCR Popup UI:** Inline görsellere hover ile "📝 Metin" butonu, modern popup
- **ThreadPoolExecutor:** OCR batch işlemi paralel (max 4 thread)
- **SSS Dokümantasyon Sistemi:** Kapsamlı teknik dokümantasyon altyapısı

### 🔧 Düzeltilen
- FastAPI route sıralama çakışması (`by-file` literal path önce)
- DOCX görsel çıkarmada minimum boyut filtresi eklendi (50x50)
- Kullanılmayan import temizliği (`json`, `field`, `BinaryIO`)

### 🧪 Test
- `test_image_extractor.py` — 35 unit test
- `test_rag_images.py` — 21 API endpoint test
- `test_response_builder_images.py` — 8 görsel referans test
- `test_catboost_service.py` — feature_names_count düzeltmesi (13→15)

---

## [v2.36.0] — 2026-02-08

### ✨ Eklenen
- RAG doküman görsel çıkarma pipeline
- `document_images` tablosu (DB schema)
- Image lightbox (büyütülmüş görsel görüntüleme)
- ML Training Samples Viewer

---

## [v2.35.x] — 2026-02-06

### ✨ Eklenen
- Dialog modül refactoring (monolithic → modüler)
- Bridge Delegation ve Accessor Delegation pattern'leri

### 🔧 Düzeltilen
- Duplicate source bilgisi sorunu
- WebSocket çift mesaj gönderimi

---

## [v2.34.0] — 2026-02-05

### ✨ Eklenen
- CatBoost feature'ları: `source_file_type`, `heading_match`
- RAG performans iyileştirme (lazy model loading)

---

## [v2.33.x] — 2026-02-03

### ✨ Eklenen
- Regions UI iyileştirmeleri (status filter, tooltip)
- Register form validasyonları (telefon, şifre, email)

---

> 📌 Daha eski versiyonlar için `README.md` dosyasındaki changelog bölümüne bakınız.
