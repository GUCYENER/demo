---
plan_id: yetkilendirme_keshif_picker
created: 2026-06-02
branch: hira
status: completed
version_target: v3.49.0
closed: 2026-06-02
closure_note: "G1 (B1 sampled-schema filter) + G2 (B2 büyüteç/clear hizalama, bundle rebuild) + G3 (B3 /tables no-store) + G4 (py_compile+JS+build OK) + G5 code-review TEMİZ + G6 v3.49.0. NOT: test_api_db_smart.py'de 8 PRE-EXISTING failure (HEAD'de de fail, değişikliklerle ilgisiz). B3 canlı teyit bekliyor."
council_mod: 3
hebe_gate_required: true
---

# Yetkilendirme keşfedilen-filtre + Picker arama ikonu/hizalama + İlk-açılış staleness

## Context (Neden?)
Kullanıcı 3 sorun (ekran görüntüleri):
- **B1:** Yetkilendirme ekranı tüm ds_db_objects (269 ham katalog) listeliyor; YALNIZ keşfedilen
  (=örneklenmiş) schema/tablolar listelensin. **Karar: Etiketleme ile aynı (ds_db_samples).**
- **B2:** Akıllı Keşif "Tablo Seç" picker arama kutusunda büyüteç ikonu YOK + clear (×) hizalaması
  kaymış. İkon ekle + hizala.
- **B3:** Yetki verildikten sonra picker ilk açılışta yeni tabloları göstermiyor, reopen düzeltiyor
  (staleness "kaçak").

## Mevcut Durum (Explore — kanıtlı)
- **B1:** `get_source_schema_tree` (data_sources_api.py:567) ZATEN ds_db_objects (table/view) döndürüyor;
  ama `detect_objects` tüm katalogu koşulsuz ds_db_objects'e döküyor. `get_all_tables_status`
  (ds_enrichment_service.py:773-853) **ds_db_samples JOIN** ile yalnız örneklenmiş schema'ları gösterir
  (+ fallback: sample yoksa tümü). Yetkilendirme bunu uygulamıyor → tutarsızlık.
- **B2:** Picker arama kutusu `home.html:902-905` büyüteç `<i>`'den yoksun; clear × `_db_smart_wizard.css`'te
  flex item (position:absolute değil) + input padding yok → dışarı kayıyor. Referans doğru pattern:
  `.ds-scope-search` (data_sources.css: absolute icon + padding-left/right + absolute clear).
- **B3:** Picker FE her açılışta `_state.tables=[]` + taze fetch (FE cache yok). resolve_scope /
  user_accessible_tables / eligibility cache YOK (grep boş). PUT /permissions commit ediyor. → En olası
  kök: tarayıcı GET cache'i (`/tables` Cache-Control'süz, `_fetchJson`→vyraFetch no-store yok).

## Faz/Gate Haritası
- **G1 — B1 backend (HEPHAESTUS + APOLLO):** get_source_schema_tree'ye get_all_tables_status'taki
  sampled-schema filtresini (ds_db_samples DISTINCT + IN + fallback) uygula. Return shape değişmez.
- **G2 — B2 frontend (ATHENA + HEBE):** home.html picker arama kutusuna büyüteç `<i fa-search aria-hidden>`
  ekle; `_db_smart_wizard.css` `.dsw-picker-search` position:relative + input padding-left/right +
  büyüteç absolute + clear absolute right. aria-label korunur. → bundle rebuild.
- **G3 — B3 frontend (ATHENA + NIKE + ARES):** picker `_fetchJson` GET'lerine `cache: 'no-store'` (taze
  veri garantisi). GÜVENLİ savunma fix'i — en olası tarayıcı-cache nedenini kapatır, hata üretemez.
  **Canlı teyit gerekir** (statik repro yok). → bundle rebuild.
- **G4 — Test + Build (TYCHE):** py_compile, ilgili pytest, `node frontend/build.mjs` bundle rebuild.
- **G5 — Code review (ZORUNLU):** `/code-review medium`.
- **G6 — Versiyon (HERA):** config.py APP_VERSION → v3.49.0.

## Critical Files
- `app/api/routes/data_sources_api.py` (get_source_schema_tree — B1)
- `frontend/home.html` (picker arama kutusu büyüteç — B2)
- `frontend/assets/css/modules/_db_smart_wizard.css` (arama kutusu hizalama — B2)
- `frontend/assets/js/modules/db_smart_picker.js` (_fetchJson no-store — B3)
- `frontend/dist/bundle.min.js` (rebuild) + `app/core/config.py` (versiyon)

## Yeniden Kullanılacak Mevcut Fonksiyonlar
- get_all_tables_status sampled-schema deseni (ds_enrichment_service.py:783-823) — B1'de aynı mantık.
- `.ds-scope-search` CSS pattern (data_sources.css) — B2 referansı.

## Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| B1: hiç sample yoksa boş liste | Orta | admin tablo göremez | fallback (sample yok→tümü), get_all_tables_status ile aynı |
| B1: NULL-schema obj sampled'da elenir | Düşük | bazı obj gizli | get_all_tables_status ile birebir parity (kasıtlı) |
| B2: bundle rebuild atlanır | Orta | değişiklik görünmez | KAP 4 build zorunlu |
| B3: gerçek kök tarayıcı-cache değilse | Orta | staleness sürer | no-store zararsız; canlı teyit istenir, alternatif kazı |

## Verification
- B1: sample'lı kaynakta schema-tree örneklenmiş schema'ları döner (Etiketleme ile aynı sayım);
  sample yoksa tümü (fallback).
- B2: picker arama kutusunda büyüteç solda + clear × sağda hizalı (CSS), bundle rebuild.
- B3: no-store header GET'lerde; canlıda yetki ver→picker ilk açılış taze (kullanıcı teyidi).
- py_compile + pytest (data_sources/db_smart ilgili) + node build.mjs exit 0.

## Out-of-scope
- B3 alternatif kök (init race / wizard-level) — no-store canlıda çözmezse ayrı kazı.
- "Yalnız zenginleştirilmiş (enrichment)" semantiği — kullanıcı "örneklenmiş" seçti.
</content>
