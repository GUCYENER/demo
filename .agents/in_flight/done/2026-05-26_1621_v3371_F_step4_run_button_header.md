---
slug: v3371_F_step4_run_button_header
title: v3.37.1 F — Önizleme Çalıştır butonu sağ-üst header'a taşı
created: 2026-05-26T20:21+03:00
owner: ZEUS
council: [HEBE (primary UI), ARES (state preservation), TYCHE (regression)]
related_audit: .agents/audits/v3371_bulgular_audit.md (Madde 7)
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
gate_1_status: pending
gate_2_status: pending
dispatch_target: HERMES subagent
---

# v3.37.1 F — Önizleme Çalıştır → Sağ-Üst Header

## Verbatim Spec (Madde 7)

> **YENİ:** Önizleme Çalıştır butonu sağ üst header + ORDER BY ayarlanabilir

**ORDER BY parçası:** Audit'te ✅ PRESENT (db_smart_wizard.js:2832+ `_renderOrderByChips`). Bu brief sadece Çalıştır button move'unu kapsar.

## Sorun

`▶️ Çalıştır` butonu `wizard-sticky-footer-actions` içinde alt-sağda
([db_smart_wizard.js:2966-2971](frontend/assets/js/modules/db_smart_wizard.js#L2966-L2971)).
Kullanıcı önizleme step (step4) header'ında sağ-üst köşede istiyor — sticky footer'ı
"intent yazma alanı" olarak bırakıp asıl aksiyonu yukarı taşımak.

## Scope

**Tek dosya:** `frontend/assets/js/modules/db_smart_wizard.js`

### Değişiklik özeti

1. Step4 panel header'ında (varsa) yeni button mount — `_ensureRunHeaderButton(panel)` helper
2. Mevcut sticky footer içindeki `#run-btn` ya kaldırılır ya da gizlenir
3. Handler aynı: `_runGeneratedReport`

### Algoritma

```javascript
function _ensureRunHeaderButton(panel) {
    if (!panel) return;
    // Header zaten varsa hedef bul; yoksa step-title yanına yerleştir
    let header = panel.querySelector('.dsw-step-header');
    if (!header) {
        header = panel.querySelector('.wizard-step-title')?.parentElement;
    }
    if (!header) return;
    if (header.querySelector('#run-btn-header')) return; // idempotent
    const btn = document.createElement('button');
    btn.id = 'run-btn-header';
    btn.type = 'button';
    btn.className = 'wizard-run-btn dsw-run-btn-header';
    btn.setAttribute('aria-label', 'Raporu çalıştır');
    btn.textContent = '▶️ Çalıştır';
    btn.addEventListener('click', _runGeneratedReport);
    header.appendChild(btn);
}
```

CSS ek:
```css
.dsw-run-btn-header {
    margin-left: auto;       /* push to right */
    align-self: flex-start;  /* top */
}
```

Sticky footer'daki `#run-btn`:
- **Seçenek A** (tercih): kaldır (innerHTML'den çıkar, line 2970-2971 sil)
- **Seçenek B**: `style="display:none"` — A seçeneği daha temiz

`_v337StepHook(4)` içinde mevcut `_ensureRunFooter(panel)` çağrısının yanına `_ensureRunHeaderButton(panel)` eklenir.

## Acceptance

1. Step4'e geçince sağ-üst header'da `▶️ Çalıştır` görünür
2. Footer'da `▶️ Çalıştır` artık yok; sadece `user_intent` textarea + `✨ Hazır Format Öner` kalır
3. Header button click → mevcut `_runGeneratedReport` flow, sonuç modal aynı
4. Disabled state (loading) için header button da `disabled + aria-busy + ⏳` döngüsü göstermeli
5. Re-render (step4'e geri dönüş) idempotent — duplicate button yok

## Gate-1 Self-Review

| Kontrol | Durum |
|---------|-------|
| Spec verbatim ile eşleşme | ✅ Madde 7 button move scope |
| ORDER BY ayrı tutuldu | ✅ Bu brief sadece button taşıma |
| Tek dosya / izole | ✅ JS + küçük CSS ek |
| Council üyesi atandı | ✅ HEBE, ARES, TYCHE |
| Restart | Frontend bundle rebuild |
| Acceptance #4 (loading state) | Footer kaldırıldığı için header button'a `_loading` patern aktarılmalı — `_runGeneratedReport` içinde id="run-btn" referansı varsa **dikkat** |

### Risk

`_runGeneratedReport` içinde `document.getElementById('run-btn')` ile butona ref alıyor olabilir — yeni id `run-btn-header` olduğu için bu kod patlatabilir. Brief'in ilk adımı: `_runGeneratedReport` içinde id referansını tara, gerekirse her iki id'yi destekle.

## Gate-2 Verification Plan

- HEBE çıktısı: JS + CSS değişiklikleri
- ZEUS verifies: build success, button visibility test, loading state test
- ARES: state korunumu (textarea değer aktarımı)

## Restart Notes

- Frontend bundle rebuild gerekli
- Hard reload kullanıcı
- Backend/DB yok

## Dispatch

HERMES — frontend-only, malware risk yok.
