---
plan_id: ux_modern_tooltips_concurrent_gate
title: UX paketi — modern tooltip component + concurrent operation button gating
created: 2026-05-23
branch: hira (v3.32.0 sprint)
status: done
closed_at: 2026-05-23
last_commit: 33e01b2
version_target: v3.32.0
council_mod: 1
hebe_gate_required: false
owner_agent: ATHENA + TYCHE
trigger: kullanıcı feedback (2026-05-23) — DS enrichment paneli native browser tooltip görünümü SaaS-modern değil; ayrıca keşif çalışırken onay butonu basılabiliyor ama backend reddediyor (UX confusion)
closure_note: |
  Global [data-tt] tooltip utility (ui_tooltip.css) build.mjs CSS_FILES'a eklendi.
  19 data-tt occurrence bundle'da, 0 native title= source'ta.
  _runningJob state machine — 3s poll + exponential backoff (max 30s), openPanel/
  closePanel lifecycle'a hook'lu. 4 bulk action buton state-aware (disabled +
  dynamic tooltip).
---

## Context

### Sorun 1 — Native browser tooltips

DS enrichment paneli ([frontend/assets/js/modules/ds_enrichment_module.js](frontend/assets/js/modules/ds_enrichment_module.js))
açıklama hücreleri, pill butonları, action butonları HTML `title=""` attribute'u
kullanıyor (line 432, 435, 450, 461, 466, 469, 534, 564, 570, 576, 585, 591, 597,
603, 624).

Native tooltip:
- ~500ms gecikme ile gösterilir, kontrol edilemez
- Sistem-tema font kullanır, dark UI ile uyumsuz beyaz/sarı background
- A11y olarak screen reader'lar için zayıf
- Modern SaaS (Linear, Notion, Vercel dashboard) tarzı değil

Screenshot kanıt: kullanıcı 2026-05-23 — "Müşterilerin farklı hizmetlere ait
abonelik bilgilerini..." beyaz pop-up modal-üstü konumda görünüyor.

### Sorun 2 — Concurrent operation UX gap

v3.31.0 backend `check_running_job` ile aynı source_id üzerinde paralel
keşif/onay reddediyor (response: `code:"running_job"`). Frontend butonları
durum-farkındalıksız:

- "Tümünü Keşfet" çalışırken kullanıcı "Tümünü Onayla"ya basabilir
- Backend toast atar: "Bu kaynak için çalışan bir iş var (...). Tamamlanmasını bekleyin."
- Kullanıcı kafası karışır: "neden butona basabildim ama hata aldım?"

Mevcut akış kararlılık açısından doğru (pessimistic lock pattern), ama frontend
state UI'a yansıtılmıyor.

## Hedef Davranış

### 1) Modern tooltip component

**Custom tooltip CSS-only çözüm (popper.js bağımlılığı yok):**

```css
/* frontend/assets/css/modules/ui_tooltip.css (yeni) */
[data-tt] {
    position: relative;
}
[data-tt]:hover::after,
[data-tt]:focus-visible::after {
    content: attr(data-tt);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
    padding: 6px 10px;
    background: rgba(17, 24, 39, 0.96);  /* dark surface */
    color: #e5e7eb;
    font-size: 0.75rem;
    line-height: 1.4;
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    white-space: nowrap;
    max-width: 320px;
    pointer-events: none;
    opacity: 0;
    animation: tt-fade-in 120ms ease-out 250ms forwards;  /* 250ms hover delay */
}
[data-tt][data-tt-multiline]:hover::after {
    white-space: normal;
    width: 280px;
}
@keyframes tt-fade-in {
    from { opacity: 0; transform: translateX(-50%) translateY(2px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
```

**Migration stratejisi:**

`title="..."` → `data-tt="..."` global replace. JS template literal'lerde:

```diff
- <td class="ds-desc-cell" title="${_escapeHtml(item.description_tr || '(Açıklama yok)')}">
+ <td class="ds-desc-cell" data-tt-multiline data-tt="${_escapeHtml(item.description_tr || '(Açıklama yok)')}">
```

**Edge cases:**
- Disabled button (`disabled title="Zaten onaylandı"`) → tooltip yine
  data-tt ile çalışmalı; CSS `:hover` disabled'da da tetiklenir
- Position auto-flip: bottom-overflow'da tooltip yukarıdan çıkar (CSS
  custom property veya JS detection)
- A11y: data-tt yanına `aria-label="..."` ekle (screen reader fallback)

### 2) Concurrent operation button gating

**State machine:**

Frontend kendi state'ini tutar: `_runningJob = { type: 'discover_all' | 'approve_all' | 'enrich_selected' | null }`.

İş başlatıldığında:
1. Bulk POST atılır
2. `_runningJob = { type, started_at }` set
3. Polling: `GET /api/data-sources/{source_id}/check-running-job` her 3s'de bir
4. Job bittiğinde `_runningJob = null`
5. UI re-render → butonlar açılır

İş başlamamışken kullanıcı bir butona basarsa:
- Önce `check-running-job` GET (zaten frontend'de var, R002'de elemine ettik;
  geri ekle ama bu kez "running job varsa butonları disable et" amacıyla)
- Server-side reddi de yine korunur (backend guard sağlam kalır)

**Butonların durum-farkındalıklı görselleri:**

```js
// Tümünü Keşfet
disabled: _runningJob !== null
title (data-tt):
  - null: "Henüz keşfedilmemiş tüm tabloları sırayla keşfet"
  - 'discover_all': "Keşif devam ediyor: 23/87 tablo tamamlandı"
  - 'approve_all':  "Onay işlemi devam ediyor — keşif bekliyor"

// Tümünü Onayla
disabled: _runningJob !== null
title:
  - null: "Tüm sayfa-dışı onay bekleyenleri toplu onayla"
  - 'discover_all': "Keşif devam ediyor — onay bekliyor"
  - 'approve_all':  "Onay devam ediyor"
```

**Progress göstergesi:**

Job ID'den progress (eğer backend `ds_discovery_jobs.progress_percent` field'ı varsa)
butonun altında ince bir progress bar veya buton text'inde sayaç:
`"Tümünü Keşfet (23/87)"`. Backend zaten `job_type` + `started_at` döndürüyor;
progress field var mı doğrula.

## ARES Checklist

- [ ] data-tt değeri user input'tan geliyorsa _escapeHtml ile sanitize (description_tr
  zaten HTML escape ediliyor — pattern uyumu doğrula)
- [ ] check-running-job polling intervali user-controlled olmasın (sabit 3s)
- [ ] Polling endpoint sadece authenticated user için (mevcut endpoint zaten)

## TYCHE Checklist

- [ ] Tooltip overflow modal/popup içinde clip olmuyor (z-index 1000 yeterli mi?)
- [ ] Disabled button click → no-op (event.preventDefault); butona basanın
  beklemesi gerektiği tooltip ile iletilir
- [ ] Job tamamlandığında polling durur (otherwise idle traffic)
- [ ] Polling sırasında network down → exponential backoff (3s, 6s, 12s, max 30s)
- [ ] Sayfa kapanırsa polling cleanup (setInterval clear on module destroy)
- [ ] Mobile tap: hover yok → tap-and-hold ya da focus-visible ile tooltip görünür mü?

## ATHENA Checklist

- [ ] Tooltip dark theme tutarlılığı (var(--bg-card), var(--text-primary) token
  kullanımı)
- [ ] Animation prefers-reduced-motion respect
- [ ] Disabled button visual: opacity:0.5 + cursor:not-allowed + filtre
- [ ] Tooltip position: small viewports'ta sağ/sol overflow yok

## Kabul Kriterleri

- [ ] DS enrichment paneli'nde tüm `title=""` → `data-tt=""` (en az 15 yer)
- [ ] Native browser tooltip artık görünmüyor (screenshot doğrulama)
- [ ] Tümünü Keşfet çalışırken Tümünü Onayla butonu disabled + açıklayıcı tooltip
- [ ] Job tamamlandığında butonlar otomatik açılır (manual refresh gerekmez)
- [ ] A11y: screen reader tooltip metnini okuyabilir (aria-label fallback)

## Sprint Adımları (sıra)

1. `ui_tooltip.css` ekle (global utility)
2. `ds_enrichment.css` ile birleştir veya ayrı dosya
3. ds_enrichment_module.js — tüm `title=""` → `data-tt=""` replace
4. `_runningJob` state machine + polling (3s interval, exponential backoff)
5. Buton render fonksiyonlarına `disabled + data-tt` durum-farkındalıklı tooltip
6. Build + manuel test (3 senaryo: idle, discover_all running, approve_all running)
7. Council Gate (ATHENA + TYCHE)
8. README footer + plan closure
