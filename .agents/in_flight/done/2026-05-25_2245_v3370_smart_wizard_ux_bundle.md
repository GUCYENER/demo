---
slug: v3370_smart_wizard_ux_bundle
title: B2/B3/B5a/B6/B7 + LLM UX entegrasyon — Smart Discovery Wizard FE bundle
created: 2026-05-25T22:45+03:00
owner: hira
target_version: v3.37.0
priority: P1 (B2/B7a=P2, diğer=P1)
status: pending
council_brief: [HEBE, NIKE, TYCHE, POSEIDON, HERMES, ZEUS]
related_plans:
  - .agents/plans/2026-05-25_2230_smart_discovery_bulgular_v3370_v1.md
---

# Smart Discovery Wizard FE Bundle

## 1. Tetikleyici (Why)
6 UX bulgu aynı dosya scope'unda (`db_smart_wizard.js`/`db_smart_wizard.html`/`db_smart.css`). Disjoint kuralı gereği **tek agent** ile yapılır (merge çakışması önleme).

## 2. Hedef (What)

### B2 (P2) — SQL pretty-print
- Önizleme paneli `<pre>` blok manuel formatter ile: keyword newlines (SELECT/FROM/WHERE/GROUP BY/ORDER BY/JOIN).
- 3rd-party lib YOK (bundle size R6).

### B3 (P1) — Delete confirmation → grid refresh
- `saved_reports` delete confirmation onayı sonrası: `await loadSavedReports()` çağrısı + toast "Rapor silindi".

### B5a (P1) — Empty columns → Next disable + toast
- Step 3 → Next butonu: seçili column count 0 ise `disabled` + tıklanırsa toast "En az bir kolon seçin".

### B6 (P2) — "Bu rapordan ne bekliyorsunuz?" sticky footer
- Step 4 (Önizleme) sayfasının altında sticky textarea (`<textarea placeholder="Bu rapordan ne bekliyorsunuz?">`).
- Çalıştır butonu ile aynı div'de, mobile responsive.
- Değer: `state.user_intent` (LLM endpoint'lerine geçirilecek).

### B7a (P2) — Çalıştır button position
- Sağ alt sticky (kullanıcı kararı).

### B7b (P1) — ORDER BY editable chip
- Önizleme paneli: order_by satırı chip olarak render et, kullanıcı sıralama yönünü (ASC/DESC) toggle edebilsin + sıralama kolonunu drag-reorder.

### LLM UX Entegrasyon

**B4 metric suggest** (Step 2):
- "Metrik öner" butonu → `POST /api/db/smart/llm/metric-suggest`
- Spinner + chip listesi; chip click → metric'i state'e ekle.

**B5b column suggest** (Step 3):
- "Kolon öner" butonu → `POST /api/db/smart/llm/column-suggest`
- 2 kategori (metric-bound + related dimensions) ayrı bölümlerde render.

**B8 format suggest** (Step 4):
- "Hazır rapor formatı öner" butonu → `POST /api/db/smart/llm/format-suggest`
- Format kartları: title + chart_type ikonu + "Uygula" butonu (state.format = card.id).

## 3. Kapsam (Disjoint File Scope)

| Subagent | Files | Op |
|----------|-------|-----|
| HEBE-FE | `frontend/db_smart_wizard.js` | edit (TEK AGENT) |
| HEBE-FE | `frontend/db_smart_wizard.html` | edit |
| HEBE-FE | `frontend/css/db_smart.css` | edit |
| TYCHE+POSEIDON | `tests/frontend/test_smart_wizard_ux.py` | create (jsdom veya Playwright — POSEIDON kararı) |

**Yasak**: backend (`app/`), `serve.py`, başka frontend dosyaları.

## 4. Implementation Notes
- LLM butonları default disabled (state validation gerek): metric için table seçili, column için metric seçili, format için columns seçili.
- LLM fetch error → toast + buton re-enable.
- Cache hint: response `cache_hit: true` ise küçük "(önbellek)" notu.

## 5. Test (TYCHE+POSEIDON brief)

Backend smoke + jsdom unit:
- `test_b3_delete_then_grid_reloads`
- `test_b5a_next_disabled_when_no_columns`
- `test_b5a_toast_on_empty_next_click`
- `test_b6_sticky_footer_textarea_state_binding`
- `test_b7b_order_by_chip_toggle_asc_desc`
- `test_llm_metric_button_calls_endpoint_with_chips`
- `test_llm_column_two_category_render`
- `test_llm_format_card_apply_sets_state`
- `test_llm_error_toast_and_button_reenabled`

(Test runner: POSEIDON jsdom önerirse — backend mocking ile; Playwright önerirse — full e2e.)

## 6. Acceptance
- [ ] 6 UX bulgu (B2/B3/B5a/B6/B7a/B7b) UI'da görünür ve çalışır
- [ ] 3 LLM endpoint çağrısı + chip/card UX
- [ ] Cache hint görünüyor
- [ ] 9 pytest PASS
- [ ] Manuel smoke: 4-step wizard end-to-end + saved report rerun (B1'le birlikte)

## 7. Risk
- R-B7b: chip drag-reorder lib gerekmeden vanilla JS ile — basit array re-order yeterli.
- R-LLM-FE: 3 endpoint'i de paralel hazırlamak — Stack 2 bitmeden Stack 3 bitmez. Bağımlılık: Stack 2 → Stack 3 sequential.

## 8. Bağımlılık
- **Stack 2** (3 LLM endpoint) bitmeden bu stack başlayamaz (endpoint'ler olmadan FE button mock olur). Ama HEBE buton UX'i mock response ile başlayabilir; endpoint hazır olunca gerçek fetch'e geçer.
- **Karar**: HEBE mock response ile başlasın (Stack 2 paralel). Stack 2 bitince HEBE son commit'te mock'u real fetch'e çevirir.

## 9. Gate
- KAPI 1: HEBE+NIKE+TYCHE+POSEIDON+HERMES masa.
- KAPI 2: spec-vs-output + 9 pytest PASS + manuel wizard smoke.
