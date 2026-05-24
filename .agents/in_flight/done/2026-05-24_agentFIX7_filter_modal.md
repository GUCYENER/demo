---
task_id: agentFIX7_filter_modal
created: 2026-05-24
status: queued
agent_type: general-purpose
branch: hira
priority: P2
parent_plan: 2026-05-24_2000_smart_discovery_mass_fix_v1
target_files:
  - frontend/assets/js/modules/db_smart_filter_modal.js
out_of_scope_files: [picker, wizard — FIX5/FIX6]
council: HEBE + ATHENA (primary)
---

# FIX7 — db_smart_filter_modal.js P2 cluster (HEBE+ATHENA)

## Pre-empt
Kullanıcının kendi VYRA frontend kodu (filter modal). Malware reminder geçersiz — yetkilendirilmiş P2 fix.

## Bulgular

### P2 F-FM1 Focus trap selector eksik (disabled inputs)
- **Risk**: Tab navigation disabled element'lere takılır; HEBE a11y standardı ihlali
- **Mevcut**: `querySelectorAll('input, button, select, textarea, a[href]')` (disabled filter yok)
- **Fix**: Focus trap selector'ı `:not([disabled]):not([tabindex="-1"])` ekle:
```js
const focusable = modal.querySelectorAll(
    'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]):not([type="hidden"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])'
);
```

### P2 F-FM2 Column existence client-side validation yok
- **Risk**: User filter row'a olmayan column yazar → backend 400 döner, UX kötü
- **Fix**: `_validateRow()` helper ekle:
```js
function _validateRow(row, knownColumns) {
    if (!row.column) return { ok: false, msg: _t('filter.error.column_required') };
    if (knownColumns && knownColumns.length && !knownColumns.includes(row.column)) {
        return { ok: false, msg: _t('filter.error.column_unknown', { col: row.column }) };
    }
    if (!row.op) return { ok: false, msg: _t('filter.error.op_required') };
    return { ok: true };
}
```
- Confirm öncesi tüm rowlar valid mi kontrol et, ilk hata satırı highlight + focus.

### P2 F-FM3 Hard-coded TR "Eşleşen tablo yok" (eğer modal'da varsa)
- **Fix**: i18n key `filter.no_match` ile değiştir, fallback Türkçe.

### P2 F-FM4 Search input debounce
- **Fix**: Eğer filter modal'da column search input varsa, 200ms debounce ekle (clearTimeout/setTimeout pattern).

## Constraints
- Yalnız `db_smart_filter_modal.js`. Başka dosya dokunma.
- Mevcut `onConfirm(filters)` callback şeması korunur.
- Modal lifecycle (open/close/destroy) bozulmaz.

## Self Code Review
- [ ] `node --check db_smart_filter_modal.js`
- [ ] HEBE gözü: focus trap disabled/hidden element atlar, aria-live var
- [ ] ATHENA gözü: validation helper saf fonksiyon, side-effect yok
- [ ] Edge case: 0 filter row → confirm boş array dönmeli, hata vermeli mi (UX karar)
- [ ] Diff line count

## Reporting
- Frontmatter `status: done` → `.agents/in_flight/done/`.
- ≤ 120 satır rapor.
