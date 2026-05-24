---
plan_id: smart_discovery_picker_redesign
created: 2026-05-24
branch: hira
status: in_progress
version_target: v3.34.2
council_mod: 2
hebe_gate_required: true
parent_request: yeni_konu.docx
---

# Plan — Akıllı Veri Keşfi Tablo Seçici UX Yeniden Tasarımı

## 1. Context

Kullanıcı `Gecici_Dosyalar_Sil/yeni konu.docx` ile **Akıllı Veri Keşfi** sekmesinin "1 · Tablo Seç" adımı + alt-modal'ı + saved-reports search clear için UX yeniden tasarımı istedi.

3 görsel:
- **image1** — Wizard Adım 1: üstte beyaz arama input'u VAR; talep: KALDIR, sade "Ara" butonu + açıklayıcı mesaj olsun.
- **image2** — "Tablo Seç" alt-modal: sol panel mevcut; talep: schema-bazlı akordeon, persist selection, "Tümünü Temizle", "Sadece Seçilenler" filtresi, FK öneri sıkılaştırma, ilişkisiz tablo uyarısı, arama temizle ikonu.
- **image3** — Anasayfa "Rapor ara..." input'una temizleme ikonu ekle.

## 2. Mevcut Durum (Explore)

- `frontend/assets/js/modules/db_smart_wizard.js` (990 satır) — wizard ana akış, step 1 search input + Tablo Seç butonu (line 726).
- `frontend/assets/js/modules/db_smart_picker.js` (441 satır) — alt-modal; flat list, Türkçe normalize, FK panel, "Seç ve Kapat" mevcut.
- `frontend/assets/css/modules/_db_smart_wizard.css` — picker CSS de bu dosyada (dsw-picker-* class'ları).
- `frontend/assets/js/modules/saved_reports_grid.js` (451 satır) — anasayfa rapor arama.
- Backend (mevcut, yeterli):
  - `GET /api/db-smart/sources/{source_id}/tables?q&limit=200` — schema, name, label, table_id döner; schema-bazlı gruplama frontend'de.
  - `GET /api/db-smart/sources/{source_id}/tables/{table_id}/related?depth=1` — FK ilişkili tablolar.

## 3. Faz/Gate Haritası

| Gate | Madde | Strateji | Review |
|------|-------|----------|--------|
| G1 | Wizard step 1 sadeleştirme | db_smart_wizard.js: input + dropdown'ı kaldır → tek "Ara" butonu + açıklayıcı paragraph; picker direkt açılır (initialQuery boş) | HEBE + ATHENA |
| G2 | Picker modal enhancements | db_smart_picker.js: (a) Schema-akordeon render (group by schema, ilk schema açık), (b) "Tümünü Temizle" buton, (c) "Sadece Seçilenler" toggle filter, (d) arama temizle ikonu, (e) seçim persist across search filter, (f) FK önerisi yoksa ilişkisiz seçim için warning toast | HEBE + ATHENA + NIKE |
| G3 | Picker CSS | _db_smart_wizard.css: dsw-picker-accordion, dsw-picker-clear-btn, dsw-picker-filter-only-selected, dsw-picker-warning style'ları | HEBE |
| G4 | Saved reports clear icon | saved_reports_grid.js + _saved_reports_grid.css: input'a clear icon (×) ekle, value boş değilse görünür | HEBE + ATHENA |
| G5 | Bundle rebuild + verification | node frontend/build.mjs + manuel test | HEPHAESTUS + TYCHE |
| G6 | Code review | Diff özet, syntax check, regression | HERMES + ARES + TYCHE + HEBE |

## 4. Critical Files

**Modify:**
- `frontend/assets/js/modules/db_smart_wizard.js` (G1)
- `frontend/assets/js/modules/db_smart_picker.js` (G2)
- `frontend/assets/css/modules/_db_smart_wizard.css` (G3 — picker CSS aynı dosyada)
- `frontend/assets/js/modules/saved_reports_grid.js` (G4)
- `frontend/assets/css/modules/_saved_reports_grid.css` (G4)

**Bundle (auto):**
- `frontend/dist/bundle.min.js`, `frontend/dist/bundle.min.css` (G5)

**Out of scope:**
- Backend endpoint'leri (mevcut yeterli). FK relationship strength sıralaması zaten backend'de.
- Türkçe semantic search backend — şu an mevcut Türkçe normalize frontend'de yeterli. İleri RAG entegrasyonu R02x'e bırakılır.

## 5. Parallel Dispatch Topolojisi

Disjoint dosya kontratı:

| Ajan | Dosya kapsamı | Kapsam dışı |
|------|---------------|-------------|
| **AGENT-A** (Wizard step 1) | db_smart_wizard.js (sadece step 1 render + arama input kaldırma bölgesi) | picker.js, saved_reports_grid.js, CSS |
| **AGENT-B** (Picker modal) | db_smart_picker.js + _db_smart_wizard.css'in dsw-picker-* bölümü | wizard.js, saved_reports_grid.js, _saved_reports_grid.css |
| **AGENT-C** (Saved reports clear) | saved_reports_grid.js + _saved_reports_grid.css | wizard.js, picker.js, _db_smart_wizard.css |

CSS file overlap riski: _db_smart_wizard.css hem wizard'ın step 1 CSS'ini hem picker CSS'ini içeriyor. AGENT-A wizard step 1 için minor CSS değişikliği yapabilir (ARA butonu styling), AGENT-B sadece dsw-picker-* bloğuna dokunur. → AGENT-A briefinde "yalnız .dsw-step-1-* ve yeni .dsw-ara-* class'lar; .dsw-picker-* ASLA dokunma" denecek.

## 6. Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|------|----------|------|------------|
| AGENT-A/B CSS dosya çakışması | med | low | Class prefix izolasyonu (.dsw-ara-* vs .dsw-picker-*) |
| Persist selection bug — kullanıcı arama yapınca tick'ler düşer | med | med | _state.primaryId + _state.joins jam Map ile zaten persist; arama sadece _state.filtered etkiler — render'da source-of-truth Map'ten okunur |
| FK öneri boş → kullanıcı ilişkisiz seçince UX karışır | med | low | Toast warning + sağ panel placeholder "İlişkili tablo bulunamadı, sol panelden başka tablo seçmeniz önerilir" |
| Schema-akordeon perf — 500 tablo varsa render yavaşlar | low | low | Group by önceden, ilk açık, lazy expand (toggle) |
| Türkçe semantic mismatch ("müşteri" → CUSTOMER bulamaz) | med | med | Mevcut backend zaten Türkçe semantic match yapıyor (semantic.label); label boşsa name; arama _nl/_nn/_nf çoklu alanlarda Türkçe normalize ile match |

## 7. Verification

- **G1**: Wizard aç → step 1'de input görünmemeli; "Ara" butonu tıklanınca picker açılır.
- **G2**: Picker aç → schema akordeon görünür; "Tümünü Temizle" seçimleri sıfırlar; "Sadece Seçilenler" toggle aktifken yalnız tick'liler listelenir; arama yap → tick'ler kaybolmaz; arama temizle ikonu görünür değer varken.
- **G2 FK guard**: Ana tablo seç → sağ FK paneli gelir; FK bulunamayan ana tabloda placeholder + 2. tablo seçilemez (veya seçilince toast warning).
- **G4**: Anasayfa "Rapor ara..." → text yaz → × ikonu görünür; tıkla → input temizlenir + grid refresh.
- **G5**: Bundle rebuild; CSS size <+5KB, JS size <+10KB beklenir.

## 8. Out-of-scope

- Backend semantic search RAG (ileri sprint R021).
- Mobil responsive picker (mevcut min-width yeterli).
- Picker'da tablo preview (Aday Tablo paneli — wizard ileri adımları).
- saved_reports_grid'in pagination + sorting iyileştirmeleri.

## 9. Versiyon

v3.34.1 → **v3.34.2** (UX enhancement bundle). Bump commit sonrası.
