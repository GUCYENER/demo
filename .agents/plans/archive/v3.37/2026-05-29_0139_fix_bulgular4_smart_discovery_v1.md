---
plan_id: fix_bulgular4_smart_discovery
created: 2026-05-29
branch: hira
status: completed
version_target: v3.37.9
council_mod: 3
hebe_gate_required: true
---

# Bulgular4 — Akıllı Veri Keşfi sihirbazı 5 bulgu fix

## 1. Context (Neden bu değişiklik?)
Kullanıcı `Gecici_Dosyalar_Sil/bulgular4.docx` ile Akıllı Veri Keşfi (Smart Data
Discovery) sihirbazında 5 sorun raporladı (6 ekran görüntüsü ile). Ekran
görüntüleri muhtemelen son `dist/bundle.min.js` rebuild'inden (2026-05-29 01:20)
ÖNCE alınmış; bu yüzden her bulgu **güncel kaynak kodda doğrulandı** (varsayım
yok, kodu okuyarak). Servisler şu an DOWN → canlı repro yapılamadı.

## 2. Mevcut Durum (Explore — kodu okuyarak doğrulandı)

**B1 — Step 3 (Filtre) "İleri →" pasif kalıyor (LLM öneri uygulayınca):**
`frontend/assets/js/modules/db_smart_wizard.js`
- `_updateNextGuard()` (247) İleri butonunu `reportColumns.length` ile aç/kapat eder.
- Tek-kolon ekleme (`1341`) ve silme (`1545`) guard'ı çağırır.
- **`_applySuggestionSlot()` (1809)** reportColumns'u REPLACE eder (1822),
  `_renderReportColumns()` çağırır (1842) ama **`_updateNextGuard()` ÇAĞIRMAZ**
  → LLM önerisi uygulanınca buton pasif kalır. **Kök neden = eksik guard çağrısı.**

**B2 — Step 4 (Önizleme) "ORDER BY / Sıralama yok." çift gösterim:**
`frontend/assets/js/modules/db_smart_ast_editor.js`
- `_render()` (164-167) "ORDER BY" section'ı + `_renderOrderList()` (228) boşken
  "Sıralama yok." basar.
- Wizard ayrıca kendi editable "SIRALAMA" chip barını gösterir
  (`db_smart_wizard.js:_renderOrderByChips` 3714 — "+ Kolon seç" dropdown ile çalışan).
- **Kök neden = iki ORDER BY UI'ı redundant.** AST editor'ün statik ORDER BY
  section'ı kaldırılmalı/gizlenmeli (çalışan chip bar kalır).

**B3 — WHERE filtre ekleyince 400 "SELECT requires at least one column":**
AST key mismatch (sistemik):
- Wizard `_buildStarterAst()` (`db_smart_wizard.js:2402-2413`) AST'i **`select`**
  key ile kurar; explain endpoint (`db_smart_api.py:655`) de **`select`** okur.
- `ast_renderer.render` (`ast_renderer.py:409-411`) ve TÜM ops (`add_column`,
  `remove_column`, `add_filter`, `reorder_columns`) **`columns`** key okur/yazar.
- Akış: WHERE "+ Ekle" → `_applyPatch('add_filter')` → patch sonrası
  `_refreshExplain` → POST `/explain` (body.ast = `select`-keyed) →
  guard 655 geçer (`select` dolu) → `render()` 673 `columns` okur (boş) →
  ValueError → **`db_smart_api.py:674` HTTPException(400, "AST render hatası:
  SELECT requires at least one column")**. **Kök neden = select↔columns key
  tutarsızlığı.**

**B4 — "Çalıştır" üretilen SQL'de "W0SELECT/W0FROM" garbage + DB hatası:**
- `data.sql` pretty-print edilmeden execute ediliyor (`db_smart_wizard.js:2077`);
  display ayrıca clean `_prettyPrintSql` kullanır (kaynak test edildi — temiz).
- Sorgu DB'de patladığı için "W0" **gerçekten çalıştırılan SQL'in içinde** = backend.
- `app/services/db_smart/llm_generate_report.py:444-456` yorumu zaten diyor ki:
  **"W0SELECT/W0FROM garbage-prefix failure mode UPSTREAM"** — v3.37.4'te maskeleyen
  sanitizer bilinçli KALDIRILDI, yerine raw-LLM telemetri logu kondu.
- `_validate_select_sql` (133) "SELECT/WITH ile başlamalı" der → "W0SELECT" reddedilip
  fallback SELECT * tetiklemeli; ama görselde tam kolon listesi var → ya sanitizer
  döneminden bir görüntü, ya da "W0" validation'dan sonra giren bir artefakt.
- **Kök neden = LLM ham çıktısı / JSON parse artefaktı (upstream).** Telemetri logu
  bir prod örneği yakalamak için var. **KARAR GEREKLİ (aşağıda).**

**B5 — Kayıtlı rapor silinince ekrandan hemen kaybolmuyor:**
- `report_detail_modal.js:_onDelete` (809) DELETE → 204 → `close()` → `onDeleted(id)` ✅
- `home.html:1030-1037` `onDeleted: () => SavedReportsGrid.refresh()` ✅
- `saved_reports_grid.js:refresh()` (493) yeniden fetch + render ✅
- `vyraFetch` 204'ü null döner (parse hatası yok, `api_client.js:259-308`) ✅
- backend `delete_saved_report` (1540) hard-delete, `list_saved_reports` (1304)
  cache yok, RLS-bound ✅
- **Güncel kaynakta wiring DOĞRU.** Bug 5 ya son rebuild ÖNCESİ görüntü (zaten
  düzelmiş), ya da browser cache / subtle timing. **Canlı repro gerekli.**

**Çapraz bulgu:** `dist/bundle.min.js` (01:20) kaynaktan (20:53) daha yeni →
güncel. Tarayıcı `home.html`→`dist/bundle.min.js` yükler → **her frontend fix
sonrası `node build.mjs` rebuild ZORUNLU** (esbuild kurulu).

## İlerleme (2026-05-29 01:4x)
- ✅ G1 B1 — `_applySuggestionSlot`'a `_updateNextGuard()` eklendi (wizard.js)
- ✅ G2 B3 — `ast_renderer.render` dual-key (columns→select fallback, string/dict normalize); columns-keyed geri uyum + select-keyed+filtre render fonksiyonel test geçti, empty hâlâ raise
- ✅ G3 B2 — AST editor statik ORDER BY section kaldırıldı (ast_editor.js)
- ✅ G4 B4 — `_repair_glued_keyword_garbage` + validation öncesi çağrı; raw telemetri korundu; regex W0/WD temizliyor, clean SQL dokunulmuyor (test geçti)
- ✅ Versiyon — config.py 3.37.1→3.37.9 + README v3.37.9 girdisi
- ✅ Rebuild — `node build.mjs` exit 0 (bundle güncel)
- 🔍 G5 B5 — kaynak wiring doğru; **canlı repro bekliyor** (servisler DOWN)
- ⏳ Doğrulama açığı: pytest koşulamadı (WSL'de pip yok / win-python asılıyor), canlı e2e smoke yapılamadı (servisler DOWN). py_compile + node -c + fonksiyonel birim testleri geçti.

## 3. Faz/Gate Haritası
| Gate | İş | Konsey |
|---|---|---|
| G1 | B1 — `_applySuggestionSlot` sonuna `_updateNextGuard()` ekle (+ savunma: `_renderReportColumns` içinde guard) | ATHENA + HEBE |
| G2 | B3 — `ast_renderer` dual-key aware: `columns` yoksa `select` oku (render + ops + `_require_select`); geri uyumlu | HEPHAESTUS + HERMES + ARES |
| G3 | B2 — AST editor ORDER BY section'ını kaldır/gizle (çalışan SIRALAMA chip bar kalır) | ATHENA + HEBE |
| G4 | B4 — KARAR sonrası: ya targeted sanitizer (W0-prefix strip + telemetri korunur) ya telemetri-only | METIS + ARES + POSEIDON |
| G5 | B5 — canlı repro; defect doğrulanırsa fix, değilse "rebuild sonrası çözüldü" raporu | ATHENA + TYCHE |
| G6 | `node build.mjs` rebuild + post-impl review (TYCHE/ARES) + smoke | NIKE + TYCHE |

## 4. Critical Files to Modify
- `frontend/assets/js/modules/db_smart_wizard.js` (B1)
- `app/services/db_smart/ast_renderer.py` (B3)
- `frontend/assets/js/modules/db_smart_ast_editor.js` (B2)
- `app/services/db_smart/llm_generate_report.py` (B4 — karara bağlı)
- `frontend/dist/*` (rebuild çıktısı)

## 5. Yeniden Kullanılacak Mevcut Fonksiyonlar
- `_updateNextGuard()`, `_renderReportColumns()` (B1)
- `ast_renderer._require_select`, `render`, `add_column/remove_column` (B3)
- `_validate_select_sql`, telemetri logu (B4)

## 6. Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| B3 dual-key fix başka render path'i bozar | Orta | Yüksek | `columns or select` fallback (additive), pytest ast_renderer |
| B2 ORDER BY kaldırma AST editor'ün başka kullanımını bozar | Düşük | Orta | Sadece wizard Step4 context; chip bar parity |
| B4 sanitizer ekip kararına aykırı | Orta | Orta | KARAR kullanıcıdan alınır; telemetri korunur |
| Rebuild sonrası regresyon | Düşük | Yüksek | Rebuild + smoke + post-impl review |

## 7. Verification
- B1/B2/B3/B5: servis ayağa kalkınca canlı smoke (Step3 İleri, Step4 ORDER BY yok,
  WHERE filtre eklenir, rapor sil→kaybolur).
- B3: `pytest tests/db_smart/test_ast_renderer*` (select-keyed AST render yeşil).
- B4: telemetri logu + (sanitizer eklendiyse) W0-prefixed input unit test.
- G6: `node build.mjs` exit 0 + bundle güncel.

## 8. Out-of-scope
- AST editor select↔columns key'inin TAM birleştirilmesi (geniş refactor) — bu
  fazda sadece dual-key fallback. Tam unifikasyon REFACTOR_BACKLOG'a.
- LLM prompt revizyonu (B4 upstream kökü prompt ise) — telemetri sonucu beklenir.
