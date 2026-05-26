---
slug: v3371_bulgular_audit
title: v3.37.1 — Bulgular 8 Madde Audit (Verbatim Listeye Göre Revize)
created: 2026-05-26T18:45+03:00
revised: 2026-05-26T17:15+00:00
owner: ZEUS
council: [ZEUS, HERMES, HEBE, ATHENA, METIS, TYCHE, ARES]
audit_source: Kullanıcı verbatim 8-madde listesi (2026-05-26)
audit_method: Graphify-first lookup (mcp__graphify__search) + targeted Read
graphify_status: online (last_graphify_ts 1779803474, status/search OK)
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
spec_authority: Kullanıcı verbatim liste (memory feedback_user_bulgu_list_authoritative)
---

# v3.37.1 Bulgular — Verbatim 8 Madde Audit

> **Spec drift düzeltmesi:** Bu audit dosyası 2026-05-26 17:15 UTC itibarıyla,
> kullanıcının verbatim sunduğu 8 madde listesine göre revize edildi. Eski
> sürüm (kendi docx-extract'ım) reddedildi (bkz: memory
> `feedback_user_bulgu_list_authoritative.md`).
>
> **Graphify durumu:** v1 audit'i offline bypass ile yapılmıştı; v2 audit (bu
> dosya) Graphify ONLINE iken yapıldı. Search hit'leri ve dosya:satır referansları
> mevcut.

## 1) Verbatim Madde Tablosu

| # | Madde (verbatim) | v3.37.1 öncesi durum | Şu anki kod | Verdict |
|---|------------------|----------------------|-------------|---------|
| 1 | Saved-report açıp Çalıştır → hata + console | source_id NULL → port=None | Brief A direct-apply: rerun_port_resolve + migration 047 | ✅ KAPALI |
| 2 | SQL göster pretty print | tek satır SQL | Brief C direct-apply: `_prettyPrintSql` (report_detail_modal.js:60, JOIN marker fix) | ✅ KAPALI |
| 3 | **YENİ:** Silme → Evet → grid refresh, silinen rapor görünmemeli | onDeleted callback wiring vardı | modal.js:786-787 onDeleted fire OK · home.html:1034 → `SavedReportsGrid.refresh()` OK · saved_reports_grid.js:459-477 `refresh()` _fetchList OK | 🟡 WIRING TAM — runtime gap araştırılacak |
| 4 | Metrik dinamik LLM + önizlemede ayrı başlık + SQL uygulanıyor mu | metrik manuel | Brief B direct-apply: `_loadMetrics()` LLM-first, `_autoSuggestMetrics()`, `✨ LLM Önerisi` category open by default (db_smart_wizard.js:733, 786) | ✅ KAPALI |
| 5 | Filtre kolon validation + toast + metric-aware kolon LLM ayrı kategori | filtre adımı (step3) flat catalog | `_renderStep3` (db_smart_wizard.js:977): tablo-grup catalog yok metrik-aware filter yok; `_addReportColumn`'da validation yok | ❌ AÇIK — YENİ İŞ |
| 6 | "Bu rapordan ne bekliyorsunuz?" sticky footer (üst scroll) | step3 alt bloğunda `dsw-user-note` | `.dsw-user-note` CSS: `margin-top:16px` (1829-1834) — **position:sticky YOK**. Step4'te ayrıca `wizard-sticky-footer` (3 ayrı yerde duplicate user_intent textarea) var | ❌ AÇIK — YENİ İŞ |
| 7 | **YENİ:** Önizleme Çalıştır butonu sağ üst header + ORDER BY ayarlanabilir | Çalıştır sticky footer'da | `wizard-sticky-footer` içinde `▶️ Çalıştır` (db_smart_wizard.js:2970-2971). Header'a taşınmamış. ORDER BY UI mevcut (`_renderOrderByChips`, line 2832+, `_state.order_by`) | 🟡 ORDER BY ✅ · Çalıştır position ❌ — YENİ İŞ |
| 8 | Önizleme'de Hazır Rapor Formatı Öner butonu + liste + LLM + seçim → çalıştır | yoktu | `✨ Hazır Format Öner` butonu (db_smart_wizard.js:2967) · `/llm/format-suggest` endpoint (3248) · liste kart render (3262) · "Uygula" set `_state.format` (3291-3310). **Seçim → otomatik çalıştır yok**; kullanıcı ayrıca `▶️ Çalıştır`'a tıklamalı | 🟡 KISMEN AÇIK — auto-run gap |

## 2) Açık Maddeler — Detaylı Bulgular

### Madde 3 — Silme refresh (runtime gap)

**Kod tarafı doğru görünüyor:**
- `report_detail_modal.js:782-788`: DELETE then close() then onDeleted(deletedId)
- `home.html:1034`: `onDeleted: function () { if (window.SavedReportsGrid.refresh) window.SavedReportsGrid.refresh(); }`
- `saved_reports_grid.js:459-477`: refresh = skeleton + _fetchList + render

**Olası runtime sebepleri (test gerekli):**
- DELETE API gerçekten silmiyor olabilir (soft-delete?)
- `_lastItems` veya chip-filter client-side cache stale dönebilir
- `_fetchList()` cache-busting header eksik olabilir (304 ile aynı liste)
- `close()` overlay'i kaldırırken `_opts.onDeleted` aynı `_opts`'i bulamayabilir (ama deletedId değişkeni ile zaten yakalanmış)

**Aksiyon:** Backend DELETE route'una hit doğrulaması ve `_fetchList()`'in network response'unu denetlemek için (a) backend log, (b) browser network tab kontrolü. Eğer her şey OK ise — sorun değil, ama kullanıcı bulgu listesinde belirttiği için Brief açılıp doğrulanmalı.

### Madde 5 — Filtre validation + metric-aware kolon LLM

**Gap 1:** `_renderStep3` (db_smart_wizard.js:977-1068) sadece flat tablo-grup catalog gösteriyor. Metrik-aware ayrı kategori (`✨ Metrik için uygun kolonlar` benzeri) yok.

**Gap 2:** `_addReportColumn` (1104-1128) sadece duplicate check yapıyor. Kolon'un seçili metric ile semantic uyumu (örn. metric `revenue` ise amount/numeric kolon mu?) kontrol edilmiyor. Hatalı/uyumsuz seçimlerde toast yok.

**Aksiyon:** Yeni brief — `2026-05-26_v3371_D_step3_validation_metric_filter.md`
- ATHENA + METIS: metric-aware backend endpoint `/llm/column-filter-suggest` veya mevcut `column-suggest`'in metric-aware genişletilmesi
- HEBE + APOLLO: Step3 UI — ✨ Metrik için uygun kolonlar category (open by default) + invalid select toast
- TYCHE: validation rule tests

### Madde 6 — Sticky footer (üst scroll)

**Gap:** `.dsw-user-note` (step3 sonrası) `margin-top:16px` ile bloğun altında. `position:sticky` veya `position:fixed` yok. Scroll'da görünmüyor.

**Not:** Step4'te `wizard-sticky-footer` zaten var (line 2961+); kullanıcı muhtemelen step3'te de aynı sticky davranışını istiyor.

**Aksiyon:** Yeni brief — `2026-05-26_v3371_E_step3_sticky_user_note.md`
- HEBE: `.dsw-user-note` için sticky CSS (bottom:0, z-index, backdrop) + duplicate textarea'ı tek state'e bağla
- DEMETER: scroll ergonomi review

### Madde 7 — Çalıştır button move + ORDER BY

**Gap 1:** `▶️ Çalıştır` butonu `wizard-sticky-footer-actions` içinde (line 2970). Kullanıcı önizleme step'inin sağ-üst header bölgesine taşımak istiyor.

**Mevcut (PRESENT):** ORDER BY UI — `dsw-orderby-bar` + add-select + chips (line 2832+). `_state.order_by` array, ASC/DESC toggle, drag/reorder yok ama add/remove + direction OK.

**Aksiyon:** Yeni brief — `2026-05-26_v3371_F_step4_run_button_header.md`
- HEBE: Step4 panel header'a `▶️ Çalıştır` mount (varolan id="run-btn"'ı footer'dan header'a taşı, event handler aynı)
- ARES: state preservation check (footer kaldırılırsa user_intent textarea'sını koru)

### Madde 8 — Format öner + seçim → çalıştır

**Gap:** `Uygula` butonu sadece `_state.format = card` set ediyor (db_smart_wizard.js:3302-3309). Otomatik `_runGeneratedReport` çağrılmıyor.

**Aksiyon:** Yeni brief — `2026-05-26_v3371_G_format_select_autorun.md`
- HEBE: Uygula handler'ına `_runGeneratedReport()` çağrısı ekle (config flag ile opsiyonel "Uygula ve Çalıştır" CTA olarak ayrı buton)
- APOLLO: UX flow review — auto-run vs explicit?

## 3) Verbatim ↔ Kod Eşleme (Gate-2 Hazırlık)

| Madde | Verbatim spec | Kod kanıt | Eşleşme |
|-------|---------------|-----------|---------|
| 1 | hata + console reproduces | migrations/versions/047_v3371_*.py + db_smart_api rerun_port_resolve | ✅ |
| 2 | pretty print | `_prettyPrintSql` + report_detail_modal.js:395 | ✅ |
| 3 | grid refresh on delete | wiring tam; runtime test gerek | 🟡 |
| 4 | dinamik LLM + ayrı başlık + SQL applied | `_autoSuggestMetrics` + `✨ LLM Önerisi` open | ✅ |
| 5 | validation + metric-aware kategori | yok | ❌ |
| 6 | sticky footer | static margin only | ❌ |
| 7 | Çalıştır header + ORDER BY | ORDER BY ✅ · Çalıştır ❌ | 🟡 |
| 8 | öner + liste + LLM + seçim→çalıştır | öner+liste+LLM ✅ · seçim→çalıştır 🟡 | 🟡 |

## 4) Sonuç

**Kapalı (ship'lenmiş):** 1, 2, 4
**Yarı-açık (runtime/UX gap):** 3, 7, 8
**Tamamen yeni iş:** 5, 6

**Yeni brief sayısı:** 4 (D: step3 validation, E: sticky footer, F: run button move, G: format auto-run)

**Migration 047:** kullanıcı onayı ile `alembic upgrade head` çalıştırılacak (Brief A bağlamında shipped, henüz prod-apply değil).
