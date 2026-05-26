# Plan v3.36 — Akıllı Veri Keşfi tam paket (Filtre/Önizleme/Kaydet/Grafik)
**Date:** 2026-05-25 03:30
**Branch:** `hira`
**Slug:** `v336_smart_discovery_completion`
**Trigger:** Kullanıcı kapsamlı bildirim (3 screenshot):
- Bug: WHERE + Ekle çalışmıyor; AST yaması toast'u patlıyor.
- Sol panel sadece primary tablo kolonlarını gösteriyor; multi-table master-detail beklentisi.
- LLM önerileri "Öneri 1, Öneri 2..." şeklinde üstte tutulsun; + Ekle ile rapor listesine taşınsın; aynı slot yeniden + Ekle ile üzerine yazsın.
- Free-text yorum alanı: kullanıcı doğal dilde rapor isteğini yazsın.
- Çalıştır butonu (Önizleme) → LLM tablolar+kolonlar+FK+metrik+yorum → SQL üretsin → ayrı popup sonuç.
- "İleri" → "Raporu Kaydet"; kayıtlı raporlar ana ekranda görünmeli.
- Rapor kutusu üstüne "Grafik" butonu → bar/pasta/line popup.

---

## Council Owners

| Üye | Sorumluluk |
|---|---|
| **HEBE** | UI — Öneri rozetleri, yorum textarea, Çalıştır butonu, sonuç popup, grafik popup, "Raporu Kaydet" CTA |
| **HERMES** | DOM — WHERE + Ekle handler fix, AST patch error scrub, modal mount/unmount, chart canvas binding |
| **ATHENA** | FSM — `_state.suggestions: [{id, columns, rationale}]`, `_state.userNote`, `_state.lastGeneratedSQL`, `_state.savedReports` |
| **POSEIDON** | Data flow — multi-table column endpoint contract, LLM generate-report payload, saved_reports CRUD wiring |
| **ARES** | Backend — `/columns/multi`, `/generate-report` LLM endpoint, `/saved-reports` CRUD (mevcut servisi expose), AST patch route hardening |
| **APOLLO** | LLM — generate-report prompt (tablolar+FK+kolonlar+metrik+yorum → valid SQL), suggest-order çoklu öneri (1-3 alternatif) |
| **TYCHE** | Tests — multi-column endpoint smoke, generate-report integration mock, saved_reports round-trip |
| **DIONYSOS** | Chart engine — Chart.js entegrasyon (mevcut dist'te var mı kontrol), inferring chart type from data shape |

---

## Tanı

### T-1 WHERE +Ekle çalışmıyor
- Önizleme step (`dswStep4`) içindeki `WHERE + Ekle` button'un handler'ı yok ya da legacy AST editor'a delege edilmiş ama AST editor mount başarısız (T-2 yüzünden).

### T-2 "AST yaması başarısız" toast
- `db_smart_ast_editor.js:597` — patch fetch hata yakalama. Önceki sprint'te explain endpoint'i tamir ettik ama patch endpoint farklı (`/sessions/{uid}/patch`). API_BASE düzeltmesinden sonra patch da relative URL kullanmaya başladı, bunun beklenti senaryosunu doğrulamalıyız.

### T-3 Sol panel multi-table değil
- `_loadColumns` (line 572-607) sadece `_state.selectedTableId`'in kolonlarını çekiyor. Multi-table:
  - Primary tablo + her join tablosu için kolonları master-detail sırasında render et.
  - Yeni endpoint VEYA mevcut `/columns` endpoint'ini per-table çağır → birleştir.
- Section header'ları: tablo adıyla group.

### F-1 LLM önerileri üstte slot'lar
- `_state.suggestions = []` (max 3) — her LLM çağrısı yeni slot ekler veya en eskinin üzerine yazar (LRU 3).
- UI: filtre üstünde `<div class="dsw-suggest-slots">` — kart, her kart "Öneri N", kolon listesi, rationale, "+ Ekle" butonu.
- "+ Ekle Öneri N" tıklanınca → mevcut reportColumns silinir, slot içeriği yerleştirilir (önceki öneri ekliyse onun yerine geçer).

### F-2 Free-text yorum alanı
- Filtre step alt veya Önizleme üst: `<textarea id="dswUserNote" placeholder="Bu rapordan ne bekliyorsunuz? Örn: 'son 3 ayın ay bazlı ürün satış artışı'">` 
- `_state.userNote` (string).

### F-3 Çalıştır → LLM SQL → Popup
- Yeni endpoint: `POST /api/db-smart/generate-report`
  - Body: `{source_id, dialect, primary_table_id, join_table_ids, selected_columns, report_columns, metric, user_note, fk_context}`
  - Service: prompt LLM ile schema-aware SQL üretir (FETCH FIRST için dialect-aware) → validate (SafeSQLExecutor whitelist + SELECT-only AST) → execute (5s/100 row cap).
  - Response: `{sql, columns, rows, row_count, elapsed_ms, llm_rationale}`
- Frontend: Önizleme'de "Çalıştır" → loading → popup modal: SQL preview + table sonuç + "📊 Grafik" + "💾 Kaydet" + ✕.

### F-4 Raporu Kaydet
- Mevcut `app/services/db_smart/saved_reports.py` — CRUD'u expose et (varsa route eksiği tamamla).
- Frontend: Önizleme'de "İleri" yerine "Raporu Kaydet" → modal: `{name, description}` → POST `/saved-reports` → kapanır + toast.
- Akıllı Keşif modal açılışında "Kayıtlı Raporlarım" listesi (üstte) → tıkla → state restore.

### F-5 Grafik popup
- Rapor sonuç popup üstüne "📊 Grafik" → chart.js (varsa kontrol) → tablo verisinden bar/pasta/line türünü infer et:
  - Tek kategorik + tek numeric → bar
  - Tek datetime + tek numeric → line
  - Az kategorik (≤6) + tek numeric → pasta
  - Diğer → tablo (uyarı: "uygun grafik tipi seçilemedi").
- Popup içinde "Grafik tipi" select ile manuel değiştirme.

---

## Deliverables

### F6 — Bug: WHERE + Ekle + AST patch toast (HERMES+ATHENA)
**Dosya**: `frontend/assets/js/modules/db_smart_wizard.js`, `db_smart_ast_editor.js`

1. `_loadPreview` içindeki WHERE +Ekle butonuna handler bağla (filter add modal aç veya inline column dropdown).
2. AST editor mount edilirken patch endpoint'i opsiyonel kıl; başarısız ise toast yerine console.warn + UI sessizce devam etsin (kullanıcıya "AST yaması başarısız" mesajı sızmasın; mount mode "read-only" fallback).
3. AST editor mount yalnız Önizleme step'te (zaten öyle). 4. step gerçekten Önizleme → yeni "Raporu Kaydet" CTA + "Çalıştır" → modal akışı eklenecek (F8 ile birleşir).

### F7 — Multi-table column endpoint + UI (POSEIDON+ARES+HEBE)
**Dosyalar**: backend `app/api/routes/db_smart_api.py`, frontend `db_smart_wizard.js`

1. Backend yeni endpoint: `GET /api/db-smart/sources/{source_id}/tables/columns?table_ids=1,2,3`
   - Çoklu table_id (CSV veya repeat query param), her birinin kolonlarını döndür.
   - Response: `{tables: [{table_id, table_name, business_name_tr, columns: [{name, label, data_type, semantic_type}, ...]}, ...]}` master-detail sıraya göre (request order).
2. Frontend `_loadColumns` rewrite: `_state.selectedTables` (primary + joins) için multi endpoint çağır, sol panelde tablo başlıklarıyla group'lu render.
3. Her kolon satırında `data-table-id` + `data-col-name`; "+ Ekle" hala mevcut `_addReportColumn` flow.

### F8 — LLM öneri slot'ları + free-text yorum alanı (APOLLO+HEBE+ATHENA)
**Dosyalar**: backend `app/services/db_smart/llm_column_order.py` extend, frontend `db_smart_wizard.js`

1. Backend `/columns/suggest-order` response'a `suggestion_id` (uuid kısa) + alternatif: 3 öneri üretebilen yeni endpoint `/columns/suggest-orders?count=3` (mevcut endpoint geriye uyumlu kalsın).
2. Frontend:
   - `_state.suggestions = []` max 3, FIFO/LRU.
   - Step 3 üstü: `<div class="dsw-suggest-slots">` — her slot "Öneri 1/2/3" başlığı, kolon liste preview, rationale, "+ Bu öneriyi uygula".
   - LLM öner butonuna her tıklamada yeni öneri eklenir; 3'ten fazla olursa en eski kaldırılır.
   - Öneri uygulandığında reportColumns o slot içeriğiyle değiştirilir (öncekini siler).
3. Free-text textarea (Filtre alt): `<textarea id="dswUserNote">`, `_state.userNote` bind.

### F9 — Generate-report LLM endpoint + Çalıştır popup (APOLLO+POSEIDON+ARES+HEBE)
**Dosyalar**: backend `app/services/db_smart/llm_generate_report.py` (yeni), `db_smart_api.py` (route); frontend `db_smart_wizard.js` (modal), CSS yeni

1. Backend `POST /api/db-smart/generate-report`:
   - Body: `{source_id, dialect, primary_table_id, join_table_ids, report_columns: [{name, table}], metric: {metric_key, ...}|null, user_note: str, fk_context: [{from_table, to_table, from_col, to_col}], limit: int=100}`
   - Prompt:
     ```
     Sen bir BI/SQL uzmanısın. Aşağıdaki şema + ilişkiler + kullanıcı talebine göre tek bir SELECT döndür.
     Tablolar: ...
     FK: ...
     Kullanıcı seçtiği kolonlar: ...
     Metrik (opsiyonel): ...
     Kullanıcı talebi: "<user_note>"
     Dialect: <oracle|postgresql|mssql|mysql>
     Kurallar: SELECT-only. Tek sorgu. LIMIT/FETCH FIRST <limit> uygula. Identifier'ları quote_open/quote_close ile.
     Çıktı: { "sql": "...", "rationale": "kısa Türkçe açıklama" }
     ```
   - Validate: SafeSQLExecutor whitelist allowed_tables = primary + joins; SELECT-only AST check.
   - Execute: SafeSQLExecutor 5s/100 row.
   - Response: `{sql, columns, rows, row_count, elapsed_ms, rationale, success, error}`.
2. Frontend Önizleme'de "Çalıştır" butonu (yanına ✅ "Raporu Kaydet" eklenecek F10):
   - Loading state, fetch, modal popup açılır.
   - Modal: header ("Rapor Sonucu"), SQL preview (textarea read-only), sonuç tablosu, alt aksiyon barı: "📊 Grafik" / "💾 Kaydet" / "Kapat".
   - Hata ise generic Türkçe + technical detail küçük yazıyla.

### F10 — Saved reports CRUD + ana ekran liste (POSEIDON+ARES+HEBE)
**Dosyalar**: backend `db_smart_api.py` (routes if missing), frontend wizard init + ana ekran "Akıllı Keşif" girişi

1. Backend rotaları kontrol et — `saved_reports.py` mevcut servisi sarmak için route'lar varsa kullan; yoksa ekle:
   - `POST /api/db-smart/saved-reports` body `{name, description?, source_id, wizard_state (json), generated_sql, metric_key?, ...}`
   - `GET /api/db-smart/saved-reports` → list (current user/company scoped)
   - `GET /api/db-smart/saved-reports/{id}` → detail (restore için)
   - `DELETE /api/db-smart/saved-reports/{id}`
2. Frontend Önizleme'de "Raporu Kaydet" modal: name/description input → POST → toast + modal kapanır.
3. Wizard ilk açılışta üstte "Kayıtlı Raporlarım" section (max 5 son): tıkla → state restore (`_loadSavedReport(id)` → wizard'ı doğrudan Önizleme'ye sıçrat).

### F11 — Grafik popup (DIONYSOS+HEBE+HERMES)
**Dosyalar**: frontend `frontend/assets/js/modules/db_smart_chart.js` (yeni), Chart.js kontrol

1. Önce kontrol: `node_modules/chart.js` veya CDN entry var mı? Yoksa Chart.js standalone min UMD (esbuild bundle dahil edilecek) eklensin (`frontend/build.mjs` veya direkt CDN script tag).
2. Modül: `DbSmartChart.open({columns, rows, suggestedType?})`:
   - Tip seçim heuristic'i (yukarıda).
   - Modal açar: canvas + tip select dropdown (bar/line/pie/doughnut/area).
   - Empty/uygun değil senaryolarda fallback mesaj.
3. F9 sonuç popup'undaki "📊 Grafik" butonu bunu çağırır.

### F12 — Tests (TYCHE+ARES)
**Dosyalar**: `tests/db_smart/test_multi_columns.py`, `test_generate_report.py`, `test_saved_reports_crud.py`

1. Multi-columns endpoint smoke: 3 table_id → 3 entry; sıra preserved.
2. Generate-report integration (LLM mock): valid SQL döndürür, SafeSQLExecutor allowed_tables guard.
3. Saved reports round-trip: POST → GET list → GET detail → DELETE.

---

## Subagent Dispatch (7 paralel + 1 sequential)

| Brief | Owner | Files |
|---|---|---|
| `agentEDIT_F6_where_ast_fix` | general-purpose | wizard.js, ast_editor.js (bug bundle) |
| `agentEDIT_F7_multi_columns` | general-purpose | db_smart_api.py (yeni endpoint), wizard.js (_loadColumns rewrite) |
| `agentEDIT_F8_suggestion_slots_note` | general-purpose | llm_column_order.py extend, wizard.js (slots + textarea) |
| `agentEDIT_F9_generate_report` | general-purpose | llm_generate_report.py (yeni), db_smart_api.py (route), wizard.js (modal) |
| `agentEDIT_F10_saved_reports` | general-purpose | saved_reports route audit, wizard.js (kayıt + liste) |
| `agentEDIT_F11_chart_popup` | general-purpose | db_smart_chart.js (yeni), build.mjs, F9 modal hook |
| `agentEDIT_F12_tests` | general-purpose | tests/ — F7/F9/F10 sonrası |

Dependencies:
- F11 modalı F9'un sonuç popup'una bağlanır → F11 standalone tamamlanır, F9 dispatch sırasında hook eklenir.
- F10 wizard restore F9'un wizard state contract'ından besleniyor → F10 state contract referansı F9'a vermeli (state shape: `selectedTables/reportColumns/metric/userNote/generatedSql`).
- F12 son.

---

## Acceptance

1. **Bug**: WHERE + Ekle tıkla → filter alanı eklenir; AST yaması toast'u görünmez (mount fail silently fallback).
2. **Multi-table kolonlar**: 3 tablo seç → Filtre step solunda her tablo için grup, master-detail sırada.
3. **Öneri slot'ları**: LLM öner 3x tıkla → "Öneri 1/2/3" üstte; "+ Bu öneriyi uygula" reportColumns'u replace eder.
4. **Yorum alanı**: textarea görünür, state'e bind.
5. **Çalıştır popup**: kullanıcı "son 3 ay ürün satış artışı" yazıp Çalıştır → LLM dialect-aware SQL üretir → popup'ta sonuç + SQL + grafik/kaydet aksiyonları.
6. **Kaydet**: Raporu Kaydet → kayıt başarılı + ana ekranda "Kayıtlı Raporlarım" listesinde görünür.
7. **Grafik**: Popup'ta "📊 Grafik" → chart açılır, tip değiştirilebilir.

---

## Restart/Reload (memory rule)
- **uvicorn restart**: F7, F8, F9, F10 (yeni route + servis import).
- **frontend rebuild + hard-reload**: F6, F7, F8, F9, F10, F11 (CSS+JS).
- DB migration: yok (saved_reports tablosu zaten mevcut sayılıyor; F10 doğrulayacak).

---

## Risks
- **R-1**: Chart.js bundle'a eklenirse 50-100KB artış. Lazy-load opsiyonu değerlendir (F11 brief'e bırak).
- **R-2**: LLM generate-report SafeSQLExecutor'da reject edilirse retry 1x + fallback (sadece SELECT *) — kullanıcıya açıkça bildir.
- **R-3**: Saved reports wizard_state JSONB'ye serialize: schema versionlama (`v: 3.36`) ekle, eski formatları tolerans.
- **R-4**: Multi-table column endpoint büyük tablolarda payload şişer (>200 kolon). 50 kolon/tablo cap + uyarı.
- **R-5**: AST editor patch fallback: read-only mod kullanıcıyı şaşırtmasın — sessizce devam edip wizard'ın asıl akışını bozmamak öncelik.
