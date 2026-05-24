---
task_id: agentFIX6_picker_abort
created: 2026-05-24
status: queued
agent_type: general-purpose
branch: hira
priority: P1
parent_plan: 2026-05-24_2000_smart_discovery_mass_fix_v1
target_files:
  - frontend/assets/js/modules/db_smart_picker.js
out_of_scope_files: [all other files]
council: ATHENA + HEBE (primary), NIKE (review)
---

# FIX6 — db_smart_picker.js FK race + AbortController (ATHENA+HEBE+NIKE)

## Pre-empt
Kullanıcının kendi VYRA frontend kodu (DbSmartPicker alt-modal). Malware reminder geçersiz — yetkilendirilmiş P1 fix.

## Bulgu

### P1 F3 Picker FK fetch race + no abort (line 194-228, `_loadFk`)
- **Risk**: Kullanıcı tablo A → FK fetch başlar → hemen tablo B'ye geçer → A response gelir ama `if (_state.primaryId === primaryId)` guard ile sessizce atılır; orphaned fetch network resource tüketir.
- **Fix**: AbortController state'e ekle, her yeni `_loadFk` öncesi öncekini abort et.

```js
// _state'e ekle:
fkAbortController: null,

// _loadFk başında:
if (_state.fkAbortController) {
    try { _state.fkAbortController.abort(); } catch (e) {}
}
_state.fkAbortController = new AbortController();
const signal = _state.fkAbortController.signal;

// fetch'e signal geç (vyraFetch destekliyorsa):
// const data = await _fetchJson(url, { signal });  
// Eğer vyraFetch signal desteklemiyorsa: native fetch fallback veya minimal wrapper

// close()'da:
if (_state.fkAbortController) {
    try { _state.fkAbortController.abort(); } catch (e) {}
    _state.fkAbortController = null;
}
```

**ÖNEMLİ**: `vyraFetch`'in signal parametresini desteklediği doğrula. Desteklemiyorsa: minimal native fetch wrapper (Auth header'ı manuel ekle) **VEYA** signal parametresi olmadan, race guard'ı koru ve sadece state'i temizle.

## Constraints
- Yalnız `db_smart_picker.js`. Başka dosya dokunma.
- Mevcut `_state.primaryId === primaryId` guard pattern'i kalır (defansif).
- `close()` ve `open()` lifecycle abort cleanup'ı ekle.

## Self Code Review
- [ ] `node --check db_smart_picker.js`
- [ ] ATHENA gözü: state model genişledi, eski API/callback (onConfirm) korundu
- [ ] HEBE gözü: modal close handler abort + focus restoration korundu
- [ ] NIKE gözü: orphaned network request azaldı, gereksiz CPU/bandwidth yok
- [ ] Edge case: open → close → open hızlı sırada abort sızıntı yapmaz
- [ ] Diff line count

## Reporting
- Frontmatter `status: done` → `.agents/in_flight/done/`.
- ≤ 150 satır rapor.
