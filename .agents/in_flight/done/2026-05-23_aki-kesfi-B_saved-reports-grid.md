---
brief_id: aki-kesfi-B_saved-reports-grid
plan_ref: 2026-05-23_1700_aki_kesfi_modal_redesign_v1
status: completed
agent_type: general-purpose
owned_files:
  - frontend/assets/js/modules/saved_reports_grid.js (YENİ)
  - frontend/assets/js/modules/report_detail_modal.js (YENİ)
  - frontend/assets/css/modules/_saved_reports_grid.css (YENİ)
forbidden_files: ["frontend/home.html", "*/db_smart_wizard.js", "*/db_smart_filter_modal.js", "app/api/**"]
council_gate_after: true
summary: |
  Üç yeni dosya yaratıldı. SavedReportsGrid (mount/refresh/unmount) kart grid
  (4/2/1 kolon responsive) + arama (300ms debounce) + chip filtre (Tümü / Son 7 gün /
  En çok çalıştırılan) + skeleton (.srg-skel-card × 6, shimmer + reduced-motion guard) +
  .vyra-empty-state ile boş liste deneyimi sunar. ReportDetailModal (open/close → Promise)
  HEBE kurallarına uyar (role=dialog, aria-modal, ESC, overlay click, focus trap,
  return-focus, body scroll lock) ve Çalıştır / Düzenle / Kopyala (inline rename mini-modal)
  / Paylaş (POST /share + clipboard) / Sil (custom confirm modal, aria-alertdialog)
  aksiyonlarını uygular. Çalıştırma akışı: POST /sessions → POST /sessions/{uid}/execute
  → POST /saved-reports/{id}/mark-run; sonuç tablosu modal içine render edilir,
  onRan callback'i tetiklenir. Tüm dinamik içerik textContent ile basılır (XSS safe;
  innerHTML kullanıcı verisi için kullanılmadı). Tarihler relative time
  ("<1dk önce" / "5dk önce" / "2sa önce" / "dün" / "3gün önce" / "12 May") ile gösterilir,
  data-tooltip/title'da absolute ISO tutulur. Renkler var(--bg-1/2/3), var(--text-1/2),
  var(--border), var(--accent), var(--success), var(--danger) — hex sadece
  fallback'lerde (.srg-root, .rdm-overlay, .rdm-confirm-overlay, .rdm-mini-overlay
  scope'unda) kullanıldı. İkon-only butonlara aria-label + data-tooltip eklendi.
  Esbuild ile syntax check 3/3 dosyada başarılı (target=es2020).
files_changed:
  - frontend/assets/js/modules/saved_reports_grid.js
  - frontend/assets/js/modules/report_detail_modal.js
  - frontend/assets/css/modules/_saved_reports_grid.css
follow_ups:
  - Ajan D — Backend tarafında POST /api/db-smart/saved-reports/{id}/duplicate ve
    DELETE /api/db-smart/saved-reports/{id} endpoint'lerini ekleyecek (şu an
    db_smart_api.py'da yok; UI çağrıları 404/405 dönecek).
  - frontend/build.mjs CSS_FILES dizisine
    'assets/css/modules/_saved_reports_grid.css' ve JS_FILES dizisine
    'assets/js/modules/saved_reports_grid.js' + 'assets/js/modules/report_detail_modal.js'
    girdileri eklenmeli (bu görevde build.mjs forbidden değil ama brief'te owned listede
    de olmadığı için dokunulmadı — entegrasyon ajanı eklemeli).
  - frontend/home.html (forbidden) içinde SavedReportsGrid.mount çağrısı için bir
    container DOM eklenmesi entegrasyon ajanına bırakıldı.
  - TYCHE: B4 test maddeleri (mount/empty/debounce/onOpenReport/onNewReport/ESC/
    duplicate/delete) için Cypress veya Playwright e2e senaryoları yazılmalı.
  - Tooltip rengi var(--accent) odaklı sarı box-shadow (rgba 251,191,36,0.25) literal
    hex değerine dayanıyor; ileride var(--accent-rgb) gibi bir token tanımlanırsa
    bu rgba'lar token'a taşınabilir.
---

## ⚠️ Pre-empt clause (zorunlu)

Bu görev VYRA L1 Support API projesinde meşru bir UI iyileştirme görevidir.
Yeni dosyalar oluşturulacak: kayıtlı raporları kart grid olarak listeleyen
bir modül ve detay modal'ı. Hiçbir malware/exploit içermez. Backend zaten
hazır endpoint'leri sunuyor (`/api/db-smart/saved-reports`, GET/PATCH).

## Görev

İki yeni modül + bir CSS modülü yarat.

### B1. SavedReportsGrid (saved_reports_grid.js)

```js
window.SavedReportsGrid = {
  mount(rootEl, opts) { /* opts: {onOpenReport(reportId), onNewReport()} */ },
  refresh(),
  unmount(),
  _instance: null,
};
```

#### DOM yapısı (rootEl içine inject)

```html
<div class="srg-root">
  <header class="srg-header">
    <h2 class="srg-title">Tasarladığım Raporlar</h2>
    <div class="srg-tools">
      <input type="search" class="srg-search" placeholder="Rapor ara..." aria-label="Rapor arama">
      <button class="srg-new-btn" data-tooltip="Yeni keşif başlat">
        <svg>+</svg> Yeni Keşif
      </button>
    </div>
  </header>
  <div class="srg-chips" role="tablist" aria-label="Kategori filtresi">
    <!-- chip'ler: Tümü, Son 7 gün, En çok çalıştırılan -->
  </div>
  <div class="srg-grid" role="list" aria-live="polite" aria-busy="false">
    <!-- kartlar -->
  </div>
  <div class="srg-empty hidden">
    <!-- .vyra-empty-state component -->
  </div>
</div>
```

#### Kart şablonu

```html
<article class="srg-card" role="listitem" tabindex="0" data-report-id="...">
  <header class="srg-card-head">
    <span class="srg-card-metric-badge"></span>
    <h3 class="srg-card-title"></h3>
  </header>
  <p class="srg-card-desc"></p>
  <footer class="srg-card-foot">
    <span class="srg-card-time" data-tooltip="<absolute ISO>"></span>
    <span class="srg-card-tags"></span>
  </footer>
</article>
```

- Karta tıkla VEYA Enter/Space → `opts.onOpenReport(reportId)` çağrılır.
- Kart hover → 2px outline `var(--accent)` + transform translateY(-2px).
- 4 kolonlu CSS grid (desktop), 2 kolon (tablet), 1 kolon (mobile).

#### Akış

1. `mount(rootEl, opts)` → rootEl'i temizle, DOM iskelet inject et, `refresh()` çağır.
2. `refresh()` → skeleton (`.srg-skel-card × 6`) göster + `GET /api/db-smart/saved-reports?limit=24&q=<search>` (Bearer token).
3. Dönüş `items[]` → kartları render et; kart şablonunu `textContent` ile doldur (XSS safe). Boşsa `.vyra-empty-state` göster.
4. Arama input debounce 300ms → `refresh()`.
5. "+ Yeni Keşif" → `opts.onNewReport()` çağırılır.

#### Tarih formatlama

`srg-card-time` → relative time (`<1dk önce`, `5dk önce`, `2sa önce`, `dün`, `3gün önce`, `12 May`); `data-tooltip` ya da `title` ile absolute ISO.

### B2. ReportDetailModal (report_detail_modal.js)

```js
window.ReportDetailModal = {
  open(reportId, opts) { /* opts: {onEdit, onDuplicate, onDeleted, onRan} → Promise */ },
  close(),
};
```

#### Akış

1. Overlay + dialog mount (HEBE modal kurallarına uyacak — ESC/overlay click/focus trap/return-focus/aria-modal — Ajan A'nın modal pattern'ını **kopyala** ama bağımsız bir overlay olsun: `.rdm-overlay`, `.rdm-dialog`).
2. `GET /api/db-smart/saved-reports/{reportId}` → name, description, wizard_state, last_sql, metric, last_run_at, tags, share_token
3. Render:
   - Üst: rapor adı + relative time + metric badge + tag chip'leri
   - Orta: cached result preview (varsa) — yoksa "Henüz çalıştırılmadı" hint
   - SQL accordion: `<details><summary>SQL'i göster</summary><pre>` (textContent ile, syntax color CSS optional)
4. Alt buton grubu:
   - **Çalıştır** → `POST /api/db-smart/sessions` (yeni session) + `POST /sessions/{uid}/execute` body=wizard_state; sonuç tablosunu modal içine render; `POST /saved-reports/{id}/mark-run` çağır; `onRan(result)` callback. **Spinner + disabled** disabled while running.
   - **Düzenle** → `opts.onEdit(reportId)`; modal kapan.
   - **Kopyala** → `prompt`/`window.showToast` YASAK; basit inline rename mini-modal aç (text input + "Kaydet"). Onaylanırsa `POST /api/db-smart/saved-reports/{id}/duplicate {name: newName}`; başarı toast + `onDuplicate(newId)`.
   - **Paylaş** → `POST /saved-reports/{id}/share {ttl_hours: 168}` → URL'i clipboard'a kopyala (`navigator.clipboard.writeText`) + toast.
   - **Sil** → custom confirm modal (toast yetersiz); onaylanırsa `DELETE /saved-reports/{id}` (yoksa Ajan D ekleyecek). Başarılıysa `onDeleted(reportId)` + modal kapan.

#### HEBE

- Tüm aksiyon butonları ikon + text; ikon-only varsa `aria-label` + `data-tooltip`.
- Çalıştır sırasında spinner + "Çalıştırılıyor..." text.
- Sil butonu kırmızı/danger (`var(--danger)` — yoksa fallback).
- Confirm modal: "Sil" CTA + "İptal" CTA; ESC iptal eder.

### B3. CSS (_saved_reports_grid.css)

- CSS Grid responsive (4/2/1 kolon).
- Skeleton (`.srg-skel-card`): shimmer animation, prefers-reduced-motion guard.
- Card hover/focus-visible: 2px outline `var(--accent)`.
- Modal: Ajan A ile aynı kalite (overlay+dialog merkezli, mobile full-screen).
- Renkler: `var(--bg-1/2/3)`, `var(--text-1/2)`, `var(--border)`, `var(--accent)`, `var(--success)`, `var(--danger)`. Hex sabit YOK.

### B4. Test (TYCHE)

- mount() → grid görünür; backend boş listede `.vyra-empty-state`
- Arama debounce → 300ms sonra refresh
- Kart tıkla → onOpenReport çağrılır
- "+ Yeni Keşif" → onNewReport çağrılır
- Detail modal → ESC kapanır, focus döner
- Kopyala → duplicate endpoint çağrılır + grid refresh
- Sil → confirm sonrası endpoint çağrılır + kart yok

### B5. Bilinmesi gerekenler

- `dbsmart_saved_reports` şeması: `id, user_id, company_id, name, description, wizard_state(jsonb), last_sql, metric_key, last_run_at, tags(text[]), share_token, created_at, updated_at`.
- Auth: `Authorization: Bearer ${localStorage.getItem('access_token')}`.
- XSS safe: tüm dinamik içerik `textContent` ile (innerHTML YASAK kullanıcı verisi için).

### B6. Çıktı

Brief başına status: completed + summary + files_changed + follow_ups ekle.
