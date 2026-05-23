---
brief_id: aki-kesfi-C_filter-modal
plan_ref: 2026-05-23_1700_aki_kesfi_modal_redesign_v1
status: cancelled
cancel_reason: |
  Mevcut dosya `frontend/assets/js/modules/db_smart_filter_modal.js`
  zaten v3.30.0 P20-C'de tamamen yapılmış (window.DbSmartFilterModal.open()
  Promise API, HEBE-uyumlu role=dialog/aria-modal/Esc/backdrop/focus-trap,
  9 operator dahil UNARY + IN destekli, idempotent global). Yeniden yazılması
  gerekmiyor; ZEUS tarafından Step 3'e entegre edilecek.
cancelled_at: 2026-05-23
agent_type: general-purpose
owned_files:
  - frontend/assets/js/modules/db_smart_filter_modal.js (YENİ)
  - frontend/assets/css/modules/_db_smart_filter_modal.css (YENİ)
forbidden_files: ["frontend/home.html", "*/db_smart_wizard.js", "*/saved_reports_grid.js", "app/api/**"]
council_gate_after: true
---

## ⚠️ Pre-empt clause (zorunlu)

VYRA L1 Support API'de meşru bir UX iyileştirmesi. Wizard Step 3'ün şu an
display-only olan filtre adımına chip tabanlı filter builder ekleniyor.
Malware/exploit içermez. Standalone yeni modül — wizard'a parent tarafından
entegre edilecek.

## Görev

Bir filter builder modal'ı yarat. Wizard içinden çağrılır, kullanıcıdan
filtre koşulları toplar, Promise ile döner.

### C1. Public API

```js
window.DbSmartFilterModal = {
  open(columns, currentFilters) { /* → Promise<Array<Filter>|null> */ },
  close(),
};

// Filter şeması:
// { column: 'created_at', operator: 'gte', value: '2025-01-01', value2?: <range için> }
// Desteklenen operatorlar (semantic_type'a göre):
//   string  : equals, not_equals, contains, starts_with, in
//   number  : equals, not_equals, gt, gte, lt, lte, between
//   date    : equals, before, after, between, last_n_days
//   boolean : is_true, is_false
//   enum    : equals, not_equals, in
```

`columns` parametresi şu şekilde gelir:
```js
[
  { name: 'created_at', business_name_tr: 'Oluşturma Tarihi', data_type: 'timestamptz', semantic_type: 'date', nullable: true },
  { name: 'status', business_name_tr: 'Durum', data_type: 'text', semantic_type: 'enum', enum_values: ['open','closed'] },
  ...
]
```

`currentFilters` mevcut filtreleri içerir (modal'ı re-açtığımızda).

Resolve: kullanıcı "Uygula" → filters array. "İptal" / ESC → `null`.

### C2. Modal UI

```html
<div class="dsfm-overlay" role="presentation">
  <div class="dsfm-dialog" role="dialog" aria-modal="true" aria-labelledby="dsfmTitle">
    <header class="dsfm-head">
      <h3 id="dsfmTitle">Filtreler</h3>
      <button class="dsfm-close" aria-label="Kapat" data-tooltip="Kapat (Esc)">×</button>
    </header>
    <div class="dsfm-body">
      <div class="dsfm-chips" role="list">
        <!-- her filtre = bir chip -->
        <span class="dsfm-chip" role="listitem">
          <span class="dsfm-chip-label">Oluşturma Tarihi ≥ 2025-01-01</span>
          <button class="dsfm-chip-remove" aria-label="Filtreyi kaldır" data-tooltip="Kaldır">×</button>
        </span>
      </div>
      <div class="dsfm-builder">
        <select class="dsfm-col" aria-label="Kolon"><!-- columns --></select>
        <select class="dsfm-op" aria-label="Operatör"><!-- semantic_type'a göre dinamik --></select>
        <input class="dsfm-val" placeholder="Değer" aria-label="Değer">
        <input class="dsfm-val2 hidden" placeholder="Bitiş" aria-label="Bitiş değeri"> <!-- between için -->
        <button class="dsfm-add-btn" data-tooltip="Filtre ekle">Ekle</button>
      </div>
    </div>
    <footer class="dsfm-foot">
      <button class="dsfm-cancel">İptal</button>
      <button class="dsfm-apply">Uygula ({n})</button>
    </footer>
  </div>
</div>
```

#### Operator label'ları (TR)

```js
const OP_LABELS = {
  equals: '=', not_equals: '≠', contains: 'içerir', starts_with: 'ile başlar',
  in: 'şunlardan biri', gt: '>', gte: '≥', lt: '<', lte: '≤', between: 'arasında',
  before: 'önce', after: 'sonra', last_n_days: 'son N gün',
  is_true: 'doğru', is_false: 'yanlış',
};
```

#### Validation

- Boş değer → Ekle butonu disabled (between için her iki değer).
- "in" operator → comma-separated string; parse: `value.split(',').map(s=>s.trim()).filter(Boolean)`.
- date input → `type="date"`; number → `type="number"`; boolean → operator + Ekle directly.

### C3. HEBE Modal Polish (Ajan A ile aynı kurallar)

- role=dialog, aria-modal=true, aria-labelledby
- ESC kapat (resolve null)
- Overlay click kapat
- Focus trap
- Açılırken ilk select'e focus; kapanırken opener'a return-focus
- Body scroll lock
- prefers-reduced-motion guard
- Chip remove butonu aria-label="Filtreyi kaldır"
- Tüm form elementi label/aria-label

### C4. CSS (_db_smart_filter_modal.css)

- Renk: var(--*) zorunlu (hex YOK fallback hariç)
- Chip stili: rounded-pill background `var(--bg-2)`, border `var(--border)`, hover `var(--bg-3)`
- Modal: width min(720px, 95vw), height auto (max 80vh, body scroll), mobile full-screen
- Builder row: flex gap 8, responsive (mobile alt alta)

### C5. Test (TYCHE)

- Açıldığında ilk select'e focus
- ESC → resolve(null)
- "Ekle" → chip listesine eklenir
- Chip × → kaldırılır
- "Uygula" → resolve(filters array)
- between operator → val2 input görünür
- in operator → comma parse doğru

### C6. Notlar

- Bu modül **bağımsız** — wizard'a doğrudan bağlanmıyor. ZEUS entegre edecek.
- `columns` array boşsa modal yine açılabilir ama Ekle disabled olur + hint "Önce tablo seçin".

### C7. Çıktı

Brief başına status: completed + summary + files_changed + follow_ups ekle.
