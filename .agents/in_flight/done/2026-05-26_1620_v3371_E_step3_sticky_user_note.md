---
slug: v3371_E_step3_sticky_user_note
title: v3.37.1 E — "Bu rapordan ne bekliyorsunuz?" sticky footer (step3)
created: 2026-05-26T20:20+03:00
owner: ZEUS
council: [HEBE (primary UI), DEMETER (UX ergonomi), TYCHE (regression)]
related_audit: .agents/audits/v3371_bulgular_audit.md (Madde 6)
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
gate_1_status: pending
gate_2_status: pending
dispatch_target: HERMES subagent (frontend-only, no malware risk)
---

# v3.37.1 E — Step3 Sticky "Bu rapordan ne bekliyorsunuz?"

## Verbatim Spec (Madde 6)

> "Bu rapordan ne bekliyorsunuz?" sticky footer (üst scroll)

## Sorun

Step3 (filtre/kolon seçim) altında `.dsw-user-note` textarea var
([db_smart_wizard.js:1032-1037](frontend/assets/js/modules/db_smart_wizard.js#L1032-L1037)),
ama CSS sadece `margin-top:16px` veriyor ([_db_smart_wizard.css:1829](frontend/assets/css/modules/_db_smart_wizard.css#L1829)).
Kolon catalog uzunsa textarea scroll altında kayboluyor.

Ek: Step4'te ayrı bir `wizard-sticky-footer` zaten user_intent textarea
içeriyor (db_smart_wizard.js:2961+). State `_state.user_intent` ve
`_state.userNote` iki yere yazılıyor — duplicate.

## Scope

**Tek dosya:** `frontend/assets/css/modules/_db_smart_wizard.css`
**Olası ek:** `frontend/assets/js/modules/db_smart_wizard.js` (sadece duplicate state'i birleştirmek için, opsiyonel)

### CSS değişiklik

```css
.dsw-user-note {
    position: sticky;
    bottom: 0;
    z-index: 5;
    background: var(--vyra-bg-primary, #1a1d23);
    border-top: 1px solid var(--vyra-border, rgba(255,255,255,0.08));
    padding: 12px 16px;
    margin-top: 16px;
    backdrop-filter: blur(6px);
}
```

### Opsiyonel state birleştirme

`_state.userNote` ve `_state.user_intent` aynı değeri taşıyor.
`_renderStep3` textarea input handler'ı `_state.userNote = e.target.value` set ediyor,
`_ensureRunFooter` textarea handler'ı `_state.user_intent = ta.value` + `_state.userNote = ta.value` set ediyor.
Step3'teki handler'ı `_state.user_intent = e.target.value; _state.userNote = e.target.value;` yap.

## Acceptance

1. Step3'te kolon catalog uzun → textarea scroll'da görünmeye devam eder
2. Textarea üzerindeki içerik step4'teki sticky footer textarea'sına aynen yansır
3. Diğer step'lerde (1,2,4) sticky davranışı tetiklenmez (`.dsw-user-note` sadece step3'te render ediliyor)
4. Mobile/dar viewport'ta layout bozulmaz

## Gate-1 Self-Review (yazımda)

| Kontrol | Durum |
|---------|-------|
| Spec verbatim ile eşleşme | ✅ Madde 6 sticky scope tam |
| Tek dosya / izole | ✅ CSS-only + opsiyonel JS one-liner |
| Council üyesi atandı | ✅ HEBE (primary), DEMETER, TYCHE |
| Restart gereksinimi | Frontend rebuild (esbuild bundle) — kullanıcıya bildirilecek |
| Test stratejisi | TYCHE: visual regression yok (CSS); manual smoke checklist |

## Gate-2 Verification Plan (dispatch sonrası)

- HEBE çıktısı: CSS değişikliği + (varsa) JS state birleştirme
- ZEUS verifies: dosya:satır diff, build success, manual scroll test screenshot
- Spec-vs-output tablo: Madde 6 verbatim ↔ shipped behavior

## Restart Notes

- Frontend: `cd frontend && node build.mjs` ile bundle rebuild **şart**
- Browser: Ctrl+Shift+R (hard reload) kullanıcı yapacak
- Backend/DB: değişiklik yok

## Dispatch

`HERMES` subagent ile dispatch — sadece CSS ve JS, malware-trigger riski yok.
