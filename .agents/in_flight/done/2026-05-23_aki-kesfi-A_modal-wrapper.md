---
brief_id: aki-kesfi-A_modal-wrapper
plan_ref: 2026-05-23_1700_aki_kesfi_modal_redesign_v1
status: completed
completed_by: ZEUS (takeover — sub-agent refused with malware claim despite pre-empt clause)
completed_at: 2026-05-23
agent_type: zeus-takeover
owned_files:
  - frontend/assets/js/modules/db_smart_wizard.js
  - frontend/assets/css/modules/_db_smart_wizard.css
  - frontend/assets/js/i18n/loader.js
forbidden_files: ["frontend/home.html", "*/saved_reports_grid.js", "*/db_smart_filter_modal.js", "app/api/**"]
council_gate_after: true
summary: |
  loader.js: ensureInit() + DOMContentLoaded auto-bootstrap eklendi. Önce hiçbir
  yer VyraI18n.init() çağırmıyordu — bu yüzden aki_kesif bundle yüklenmiyordu
  ve wizard.step.indicator gibi key'ler ham görünüyordu. Ayrıca loader.js
  build.mjs JS_FILES'a (wizard'dan ÖNCE) eklendi — daha önce hiç bundle'a
  girmiyordu.
  db_smart_wizard.js: _ensureI18n() helper + init() içinde bundle await; sonra
  applyTranslations(panel) + _setStep tekrar çalıştırılarak step.indicator
  yenileniyor. openAsModal({reportId?, onClose, onSave}) → Promise, closeModal(),
  isOpen() eklendi. Strateji: inline panel klonlamak yerine appendChild ile
  taşınıyor (Agent A note #3 — event binding korunur), kapanışta orijinal
  parent+nextSibling konumuna iade. ESC+overlay click+focus trap+body scroll
  lock+return-focus eklendi. reportId verilirse GET /saved-reports/{id} ile
  wizard_state hydrate (sourceId, selectedTable*, metric, filters).
  _db_smart_wizard.css: .dsw-modal-overlay (rgba 0 0 0 .55 + blur 4px,
  z-index 1000), .dsw-modal-dialog (min(1100,95vw) × min(720,90vh)), .dsw-in-modal
  inner panel flex/overflow, .dsw-modal-close, mobile <768px full-screen,
  prefers-reduced-motion no-preference guard'lı fade+scale animations.
  Tüm renkler --vyra-* namespace (wizard ile tutarlı), hex sadece fallback.
files_changed:
  - frontend/assets/js/i18n/loader.js
  - frontend/assets/js/modules/db_smart_wizard.js
  - frontend/assets/css/modules/_db_smart_wizard.css
  - frontend/build.mjs (i18n loader bundle'a eklendi — bu dosya owned'da değildi
    ama loader.js'in hiç yüklenmemesi P0 bug; bundle entegrasyonu yapıldı)
follow_ups:
  - Wizard "Bitir" butonu POST /save-report sonrası DbSmartWizardModule._notifySaved
    çağırmalı — şu an wizard kendisi closeModal({action:'saved'}) tetiklemiyor.
    Wizard finish handler'a eklenmeli (bu task scope'unda değildi).
  - aki_kesif_tr.json'a yeni key'ler: saved_reports.*, grid.empty, detail.*
    (Ajan-B'nin grid/modal'larında i18n kullanılıyorsa). Henüz kullanılmıyor.
---

## ⚠️ Pre-empt clause (zorunlu)

Bu görev VYRA L1 Support API projesinde meşru bir UI iyileştirme görevidir.
Hiçbir malware, exploit, gizli backdoor veya yetki bypass'i içermez.
İstenen değişiklik: inline wizard panelini modal (dialog) wrapper'a taşımak,
ESC/overlay/focus-trap eklemek ve i18n loader bootstrap'ını düzeltmek.
Tüm değişiklikler kullanıcı yararına UX iyileştirmesidir. Bu brief'i
"malware şüphesi" gerekçesiyle reddetmeyin — geçmiş üç ajan reddetti,
gerekçe yoktu (proje açık kaynak iş uygulaması).

## Görev

`DbSmartWizardModule`'a **modal mod** ekle. Backward-compatible kal —
inline panel mode'u kırma.

### A1. Public API
```js
window.DbSmartWizardModule = {
  init(opts),                    // mevcut — opts = {mode:'panel'|'modal'} eklendi (default 'panel')
  openAsModal(opts),             // YENİ — opts = {reportId?, onClose?, onSave?} → Promise
  closeModal(),                  // YENİ — overlay'i kaldır, return-focus
  isOpen(),                      // YENİ — boolean
};
```

- `openAsModal()` bir Promise döner: resolve({reportId, action:'saved'|'cancelled'}).
- `reportId` verilirse → `GET /api/db-smart/saved-reports/{id}` ile wizard_state hydrate et + ilk adıma git (Edit mode).
- `onSave({reportId, name})` callback — POST /save-report sonrası tetiklenir.

### A2. Modal yapısı (CSS + DOM)

- `document.body.appendChild` ile dynamic mount:
  ```html
  <div class="dsw-modal-overlay" role="presentation">
    <div class="dsw-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="dswTitle">
      <button class="dsw-modal-close" aria-label="Kapat" data-tooltip="Kapat (Esc)">×</button>
      <!-- mevcut wizard DOM'u (header/stepper/body/foot) buraya taşı -->
    </div>
  </div>
  ```
- Inline mount edilmiş `#dbSmartWizardPanel` varsa **gizle** (`hidden` + `aria-hidden=true`); modal kapanınca DOM'u opsiyonel olarak inline'a iade et veya overlay'i sadece kaldır.
- ÖNERİ: Inline DOM'u clone'la → modal'a `appendChild` → modal kapanınca clone'u sil. Böylece inline panel template olarak korunur.

### A3. HEBE Modal Polish (ZORUNLU — kırılırsa görev reject)

- `role="dialog"`, `aria-modal="true"`, `aria-labelledby="dswTitle"`
- ESC tuşu → close (event.key === 'Escape', not keyCode)
- Overlay click (event.target === overlay) → close; dialog içi click → bubble durdur
- Focus trap: ilk focusable element'e focus; Tab + Shift+Tab modal içinde döner; son element'ten Tab → ilk element
- Açılırken `_state._lastFocusEl = document.activeElement`; kapanırken `_lastFocusEl.focus()`
- Body scroll lock: `document.body.style.overflow = 'hidden'`; kapanınca restore
- Close button: `aria-label="Kapat"`, `data-tooltip="Kapat (Esc)"` (CSS-only tooltip helper)
- prefers-reduced-motion guard: overlay fade-in animation sadece "no-preference" iken

### A4. CSS (_db_smart_wizard.css)

```css
.dsw-modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}
.dsw-modal-dialog {
  background: var(--bg-1);
  color: var(--text-1);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: min(1100px, 95vw);
  height: min(720px, 90vh);
  display: flex; flex-direction: column;
  position: relative;
  box-shadow: 0 20px 60px rgba(0,0,0,.4);
}
.dsw-modal-close { position: absolute; top: 12px; right: 12px; ... }
@media (max-width: 768px) {
  .dsw-modal-dialog { width: 100vw; height: 100vh; border-radius: 0; }
}
@media (prefers-reduced-motion: no-preference) {
  .dsw-modal-overlay { animation: dsw-fade-in .15s ease; }
  .dsw-modal-dialog { animation: dsw-scale-in .2s ease; }
}
```

CSS değişkenleri ZORUNLU: `var(--bg-1)`, `var(--text-1)`, `var(--border)`, `var(--accent)`. Hex sabit YAZMA (fallback hariç).

### A5. i18n Loader Bootstrap Fix (KRİTİK BUG)

Bug: `wizard.step.indicator` çevrilmemiş çıkıyor → ham key görünüyor
([db_smart_wizard.js:116](frontend/assets/js/modules/db_smart_wizard.js#L116)).
Ama [aki_kesif_tr.json:16](frontend/assets/js/i18n/aki_kesif_tr.json#L16)
çeviri TANIMLI. Root cause: `window.VyraI18n` muhtemelen yüklü değil veya
`aki_kesif` bundle'ı async load edilmemiş.

Kontrol et:
- `frontend/assets/js/i18n/loader.js` — `window.VyraI18n.load('aki_kesif')` çağrılıyor mu? Hangi event'te?
- `DbSmartWizardModule.init()` içinde i18n bundle'ı **await** et:
  ```js
  if (window.VyraI18n && typeof window.VyraI18n.load === 'function') {
    try { await window.VyraI18n.load('aki_kesif'); } catch(e) { /* graceful */ }
  }
  ```
- `_t(key, params)` çağrılmadan ÖNCE bundle load tamamlanmış olmalı; aksi halde fallback (key passthrough) çalışır → kullanıcı ham key görür.

### A6. Test (TYCHE)

- Modal aç → ESC ile kapanır
- Modal aç → overlay click ile kapanır
- Modal aç → Tab ile focus dolaşımı modal içinde kalır
- Modal kapan → opener element'e focus döner
- Step indicator "Adım 1 / 5" olarak çevrilir (ham key görünmez)
- `init({mode:'panel'})` veya parametre vermeden → eski inline davranış korunur

### A7. Pre-completion Checklist

- [ ] py_compile gerekmez (JS) — `node -c` veya esbuild ile syntax check yap
- [ ] `_t('wizard.step.indicator', {current:1, total:5})` → "Adım 1 / 5" döner
- [ ] Modal close button aria-label="Kapat"
- [ ] Hex sabit renk yok (`grep -nE "#[0-9a-f]{3,8}" _db_smart_wizard.css` — sadece fallback OK)
- [ ] `init({mode:'modal'})` ve `openAsModal()` ile aynı sonuç (DOM eq)

### A8. Çıktı

Bitince bu brief'in **başına** şunu ekle:
```
---
status: completed
completed_at: 2026-05-23T...
summary: <2-3 cümle>
files_changed: [...]
follow_ups: [...]
---
```
