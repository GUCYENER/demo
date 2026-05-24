# EDIT — F14: Metrik step UX rebuild (akordion + arama + multi-checkbox)

- **Tarih:** 2026-05-25
- **Branch:** hira
- **Council:** HEBE (UX a11y), HERMES (i18n + interaction), ATHENA (state + payload contracts)
- **Plan kaynak:** `.agents/plans/2026-05-25_0700_v336_smoke_bugs_v1.md` (F14 bölümü)
- **Scope:** UI yalnız — F9 backend prompt değişikliği YOK (F14b follow-up).

## Problem

Step 2 (Metrik) önceden 30 metriği düz `<div>` listesi olarak gösteriyordu:
- Kategori grupları sadece `<h4>` başlığıyla ayrılıyordu (collapse yok).
- Tekil seçim (radio-like, `_state.metric`) — multi-metric mümkün değildi.
- Arama yoktu; uzun listede metric bulmak zor.
- "İleri" geçişi metric seçimi zorunlu kılmıyordu ama akış ergonomik değildi.

## Çözüm

### State değişiklikleri (`frontend/assets/js/modules/db_smart_wizard.js`)

```js
_state = {
  ...,
  metric: null,                  // backwards-compat (son seçilen item)
  selectedMetrics: new Set(),    // F14: multi-select metric_key set
  _metricsIndex: {},             // metric_key → item hash (son fetch)
  _metricCategories: {},         // category → items[] gruplaması
  ...
}
```

Back-nav (target step < 2) → `selectedMetrics.clear()` + `metric = null` (stale guard).

### Render structure (`_renderStep2`)

```html
<p class="dsw-hint">Metrik kütüphanesi (30)</p>
<div class="dsw-metric-toolbar">
  <div class="dsw-metric-search-wrap">
    <input type="search" id="dswMetricSearch" class="dsw-metric-search" placeholder="Metrik ara...">
    <button id="dswMetricSearchClear" class="dsw-metric-search-clear">×</button>
  </div>
  <button id="dswMetricClearAll" class="dsw-metric-clear-all">Tümünü temizle</button>
  <span id="dswMetricSelectedCount" class="dsw-metric-selected-count" aria-live="polite">3 seçili</span>
</div>
<div class="dsw-metric-categories">
  <details class="dsw-metric-category" open data-category="GENERIC">
    <summary class="dsw-metric-category-summary">
      <span class="dsw-metric-category-name">GENERIC</span>
      <span class="dsw-metric-category-count">8</span>
    </summary>
    <ul class="dsw-metric-list">
      <li class="dsw-metric-item" data-metric-key="row_count" data-search="kayıt sayısı row count...">
        <label class="dsw-metric-item-label">
          <input type="checkbox" class="dsw-metric-checkbox" data-metric-key="row_count">
          <span class="dsw-metric-item-body">
            <strong class="dsw-metric-item-title">Kayıt Sayısı</strong>
            <span class="dsw-metric-item-desc">Toplam satır sayısı</span>
            <span class="dsw-metric-item-meta">table</span>
          </span>
        </label>
      </li>
      ...
    </ul>
  </details>
  <details class="dsw-metric-category" data-category="KPI">...</details>
  ...
</div>
```

- İlk kategori `open`, diğerleri closed.
- Kategori belirsizse `m.category || m.applicable_when?.category || 'Diğer'`.
- Item başına `data-search` öznitelikte pre-computed TR-normalized hay var (label + description + key).

### Search filter mantığı

- Yeni helper `_trNormalize(s)`: `toLocaleLowerCase('tr-TR')` + diakritik düşürme (`ş→s, ç→c, ğ→g, ü→u, ö→o, ı→i, â→a, î→i, û→u`).
- `input` event'inde sorgu normalize edilir; her item için `data-search.indexOf(q) !== -1` ise `display: ''`, değilse `display: none`.
- Kategori altındaki tüm child gizliyse kategori de gizlenir.
- Arama aktifken eşleşen kategoriler `open` attribute alır.
- `× temizle` butonu input'u sıfırlar ve `input` event'i tetikler.

### Multi-select etkileşim

- Checkbox `change`: `selectedMetrics.add/delete(mk)`, `li.classList.toggle('selected')`.
- `metric` (tekil) = `Array.from(set).slice(-1)[0]` indeks'inden lookup — F9 payload backwards-compat.
- "Tümünü temizle" → `set.clear()`, tüm checkbox'ları uncheck, `metric = null`.
- `selectedCount` aria-live polite güncelleme.

### F9 payload uyum stratejisi (`_buildGenerateReportPayload`)

```js
return {
  ...
  metric: _state.metric || null,       // tekil — F9 prompt mevcut tüketim noktası
  metrics: metricsArr,                  // F14 multi-select array — F14b'de prompt revize edilecek
  ...
};
```

`_buildWizardState` (preview path) de aynı çift-alan stratejisini izler. Save-report ve restore path'leri (`_loadSavedReport`, `_hydrateFromSavedReport`) `ws.metrics` array varsa onu kullanır; yoksa tekil `ws.metric.metric_key`'den Set inşa eder.

### CSS (`frontend/assets/css/modules/_db_smart_wizard.css`)

Eklenen sınıflar:
- `.dsw-metric-toolbar` flex row, gap 12px, wrap.
- `.dsw-metric-search` border, focus halo (accent-color), 9/36/9/12 padding.
- `.dsw-metric-search-clear` absolute, 26x26.
- `.dsw-metric-clear-all` outline button.
- `.dsw-metric-selected-count` accent renkli, aria-live polite (HTML'de).
- `.dsw-metric-category` rounded, `border-left: 3px solid accent`.
- `.dsw-metric-category-summary` flex, custom `::before` chevron (▸ → ▾ rotate).
- `.dsw-metric-item-label` flex, padding 10/12, cursor pointer.
- `.dsw-metric-checkbox` 22×22, `accent-color: var(--vyra-accent)`.
- `.dsw-metric-item:hover` background highlight, `.selected` accent border + bg tint.
- `@media (max-width: 880px)` responsive: search full-width, checkbox 20×20, title 13px.

## Boş geçiş & validation

- "İleri" butonu/step navigation `selectedMetrics.size === 0` durumunda hiçbir kısıtlama uygulamaz — kullanıcı metrik seçmeden ilerleyebilir.
- F9 payload: `metric: null, metrics: []` — backend hâlihazırda `metric || null` tüketiyor.

## Verification

```
$ grep -n "selectedMetrics\|dsw-metric-category\|dswMetricSearch" frontend/assets/js/modules/db_smart_wizard.js
... (39 hit — state, render, events, payload, restore)

$ cd frontend && npm run build
  dist\bundle.min.css      441.6kb
  dist\bundle.min.js       1.1mb
  CSS: 687KB → 442KB  (36% küçüldü)
  JS:  2005KB → 1112KB (45% küçüldü)

$ grep "dsw-metric-category" frontend/dist/bundle.min.css
1 occurrence (minified rule block)
```

## Restart gereksinimleri

- **Backend:** YOK.
- **Frontend:** Hard-reload (Ctrl+Shift+R) ŞART — bundle.min.{js,css} yeniden derlendi, cache invalidation gerek.

## Bilinen follow-up

- **F14b (HERMES+APOLLO+ATHENA):** F9 `/generate-report` prompt'u şu an tek `metric` field tüketiyor. Multi-metric için:
  1. Backend `app/services/db_smart/sql_assembler.py` (veya prompt builder) `metrics: [...]` array kabul edecek şekilde revize.
  2. LLM prompt template'i her metric için ayrı SELECT/SUBQUERY/CTE öner.
  3. F14 UI tarafı zaten array gönderiyor (`metrics`), backend tarafı async.
- **TR-normalize util:** Şu an `db_smart_wizard.js`'e gömülü (`_trNormalize`). Picker ve filter modal'larında benzer ihtiyaç varsa `frontend/assets/js/utils/tr_normalize.js` modülüne çıkarma değerlendirilebilir (R-3 refactor backlog).

## Council onay matrisi

| Üye    | Konu                           | Onay |
|--------|--------------------------------|------|
| HEBE   | a11y (aria-live, checkbox label, keyboard summary toggle native) | bekleniyor |
| HERMES | TR-normalize + search interaction + Türkçe label/desc | bekleniyor |
| ATHENA | State shape + restore path + F9 payload backwards-compat | bekleniyor |

## Dosyalar

- `frontend/assets/js/modules/db_smart_wizard.js` — state + `_loadMetrics` + `_renderStep2` + `_trNormalize` + payload + restore.
- `frontend/assets/css/modules/_db_smart_wizard.css` — F14 stil bloğu (tail).
- `frontend/dist/bundle.min.{js,css,js.map,css.map}` — rebuild edildi.
