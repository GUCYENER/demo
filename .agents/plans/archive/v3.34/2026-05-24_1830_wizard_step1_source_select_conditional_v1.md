---
plan_id: 2026-05-24_1830_wizard_step1_source_select_conditional_v1
created: 2026-05-24 18:30
branch: hira
version_target: v3.34.2
parent_initiative: smart_discovery_picker_redesign
council_mod: 2
hebe_gate_required: true
status: dispatching
---

# Plan — Wizard Step 1 Source Select Koşullu Görünürlük

## 0. Bağlam (regression report)

AGENT-A wizard step 1 sadeleştirmesi sırasında `<select id="dswSourceSelect">` **tamamen gizlendi** (`hidden tabindex="-1" style="display:none"`). Kullanıcı geri bildirimi:

> "sağdaki kaynağı silmeyecektik. oradan kullanıcıya 1 den fazla db tanımı varsa seçeceğiz"

### Doğru davranış (kullanıcı niyeti)
- **0 source** → select gizli, "Ara" tıklayınca mevcut toast (`wizard.toast.select_source`) gösterilir.
- **1 source** → select gizli (auto-select, kullanıcıyı meşgul etme).
- **>1 source** → select **görünür**, "Ara" butonunun **yanında** veya **üstünde**, kullanıcı kaynağı seçebilir.

### Etki
- Multi-DB ortamında kullanıcı hangi kaynağı sorguladığını seçemez → kritik fonksiyonel regresyon.
- AGENT-A "_loadSources async populate edince ilk source otomatik aktif olur (browser default)" varsayımı `hidden=true` ile bozulmaz, ancak **kullanıcı seçim yapamaz** durumda.

## 1. Scope (G7-revision-1)

### G7. AGENT-D — Wizard Step 1 Source Select Conditional
- **Target files:**
  - `frontend/home.html` (yalnız `#dswStep0` içindeki `<select id="dswSourceSelect">` markup'ı — `hidden`/`style:display:none` kaldır; default'ta gizli class ekle)
  - `frontend/assets/js/modules/db_smart_wizard.js` (yalnız `_loadSources()` sonu — koşullu show/hide logic)
  - `frontend/assets/css/modules/_db_smart_wizard.css` (yalnız `.dsw-ara-source-select` veya benzeri yeni selector + `.dsw-ara-block` flex direction güncellemesi gerekirse)
- **Out of scope:**
  - `db_smart_picker.js` (DOKUNMA)
  - `saved_reports_grid.js` (DOKUNMA)
  - Backend `/sources` endpoint (DOKUNMA)
  - `.dsw-step-*` (genel step) class'ları (yalnız ara-block child)

### G8. Bundle rebuild
- `node frontend/build.mjs`

### G9. Commit + version v3.34.2

## 2. Implementasyon kuralları (AGENT-D)

### a) HTML değişikliği
- Mevcut: `<select id="dswSourceSelect" class="dsw-input" aria-label="Veri kaynağı" hidden tabindex="-1" style="display:none"></select>`
- Yeni: `<select id="dswSourceSelect" class="dsw-input dsw-ara-source-select" aria-label="Veri kaynağı" hidden></select>`
  - `style="display:none"` kaldırılır — visibility CSS class ve `hidden` attribute ile yönetilir.
  - `tabindex="-1"` kaldırılır — görünür olduğunda klavye erişimi gerekir.
  - `hidden` attribute **başlangıçta var** (default gizli; >1 source bulununca JS kaldıracak).
- `.dsw-ara-block` içinde select'i **paragraf ile buton arasında** konumlandır:
  ```html
  <div class="dsw-ara-block">
    <p class="dsw-ara-desc">…</p>
    <select id="dswSourceSelect" class="dsw-input dsw-ara-source-select" hidden></select>
    <button id="dswSearchBtn">…</button>
  </div>
  ```

### b) JS değişikliği (`_loadSources()` sonuna ekle)
- `try` bloğunun sonunda (line ~157 öncesi, `if (sel.options.length === 0)` sonrası):
  ```js
  // v3.34.2 — Koşullu görünürlük: >1 source varsa select göster
  if (sel.options.length > 1) {
      sel.hidden = false;
      sel.removeAttribute('hidden');
  } else {
      sel.hidden = true;
  }
  ```
- `if (sel.options.length === 0)` branch'inde **select gizli kalır** (kullanıcı sources yokken seçim ekranı görmesin) — değişiklik gerekmez.

### c) CSS değişikliği (`_db_smart_wizard.css` sonuna ekle)
- `.dsw-ara-source-select` selector'u:
  ```css
  /* v3.34.2 — Step 1 source select (yalnız >1 source iken görünür) */
  .dsw-ara-source-select {
      min-width: 220px;
      max-width: 360px;
      margin: 0 auto;
  }
  .dsw-ara-source-select[hidden] {
      display: none !important;
  }
  ```
- `.dsw-ara-block` flex direction zaten `column` (AGENT-A koydu), select gap ile otomatik dikey hizalanır.

### d) Browser semantic check
- `<select hidden>` HTML5 spec'inde valid. Ancak bazı tarayıcılarda `display: none !important` ek garanti.
- `sel.removeAttribute('hidden')` + `sel.hidden = false` ikisi de gerekli — bazı eski Edge davranışları için.

## 3. Constraints

- Backend `/sources` endpoint **değişmez**.
- `_openPicker()` mevcut `sourceId` okuma akışı **korunur** — select görünür olsa da olmasa da `.value` aynı kaynaktan okunur.
- `_loadSources()` API call değişmez — sadece success path'in sonuna 3-4 satır ekleme.
- AGENT-B (picker) ve AGENT-C (saved_reports) scope'larına dokunma.
- Picker DOM revert'i (önceki turda yapıldı) korunur — geri ekleme.

## 4. Verify checklist (AGENT-D rapor edecek)

1. 0 source: select gizli, "Ara" tıklayınca toast.
2. 1 source: select gizli, "Ara" tıklayınca picker doğru sourceId ile açılır.
3. >1 source: select görünür, ortalı, dropdown çalışır; "Ara" tıklayınca seçili source picker'a gider.
4. Klavye: Tab order "Ara" → select → ileri (select görünürken).
5. JS syntax OK (`node --check db_smart_wizard.js`).
6. AGENT-A `.dsw-ara-*` görselleştirmesi bozulmaz.

## 5. Risk

- **Düşük**. Üç dosyada toplam ~10-15 satır değişiklik. Public API yok, callback şeması yok, backend dokunmaz.
- Tek risk: `<select>` görünür olduğunda `.dsw-ara-block` text-align center ile select'in left-align option'ları görsel olarak garip görünebilir → CSS `text-align: center` zaten parent'ta, select kendi içinde left-align dropdown render eder, OK.

## 6. Gate akışı

- G7 (AGENT-D) → G8 (bundle) → G9 (commit + version bump)
- Council G6 review: G9 öncesi opsiyonel — değişiklik küçük, single-file scope dağınık değil.

## 7. Rollback

Hata olursa: `git checkout HEAD -- frontend/home.html frontend/assets/js/modules/db_smart_wizard.js frontend/assets/css/modules/_db_smart_wizard.css` ile son commit'e dön.
