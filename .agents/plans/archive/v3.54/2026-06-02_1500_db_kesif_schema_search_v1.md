---
plan_id: db_kesif_schema_search
created: 2026-06-02
branch: hira
status: completed
version_target: v3.54.0
closed: 2026-06-02
closure_note: "ds_learning_module _renderSchemaSelect: .ds-scope-search reuse arama + Seçilenleri Göster toggle + _applySchemaFilter + boş-durum. CSS minimal. node -c + build OK. Code-review temiz (select-all=tüm liste bilinçli korundu)."
council_mod: 2
hebe_gate_required: true
---

# DB Keşif "Örneklenecek Şemaları Seçin" — şema arama + "Seçilenleri Göster"

## Context
Kullanıcı: DB Keşif → Veri Toplama adımındaki şema seçim listesine (55 şema) arama kutusu
(ara + temizle ikonu) + "Seçilenleri Göster" toggle ekle. Büyük listede şema bulmayı/gözden
geçirmeyi kolaylaştırır.

## Mevcut Durum (kanıtlı)
- `frontend/assets/js/modules/ds_learning_module.js` `_renderSchemaSelect` (~satır 298-364):
  `.ds-schema-list` (`.ds-schema-check` label + `.ds-schema-cb` checkbox) + actions (Tümünü Seç/
  Temizle/count `dsSchemaSelectedCount`) + "Seçili Şemaları Örnekle" butonu. Arama/filtre YOK.
- Yeniden kullanılacak pattern: `.ds-scope-search` + `.ds-scope-search-input` + `.ds-search-clear`
  (data_sources.css:742-836 — magnifier sol absolute + input padding + clear sağ absolute, hidden-when-empty).
  Global CSS (bundle'da) → YENİ CSS GEREKMEZ, Yetkilendirme arama kutusuyla piksel-tutarlı.
- "Seçilenleri Göster" deseni: db_smart_picker "Sadece Seçilenler" toggle.

## Faz/Gate (Konsey: ATHENA primary, HEBE review)
- **G1 (ATHENA):** `_renderSchemaSelect` HTML'ine header↔liste arası `.ds-scope-search` arama kutusu
  (fa-search + input#dsSchemaSearch + clear#dsSchemaSearchClear) + "Seçilenleri Göster"
  checkbox#dsSchemaShowSelected + boş-durum #dsSchemaEmpty.
- **G2 (ATHENA):** `_applySchemaFilter()` — ad (toLocaleLowerCase('tr') substring) + show-selected
  birleşik filtre; `.ds-schema-check` display toggle; clear butonu boşken hidden; boş-durum göster.
  input/clear/toggle event + select-all/deselect/checkbox sonrası re-filter. Count tüm-checked sayar.
- **G3 (HEBE):** aria-label (input, clear), aria-hidden (magnifier), empty-state, marka renk (reuse var).
- **G4:** `node frontend/build.mjs` bundle rebuild.
- **G5 (TYCHE):** `node -c` JS syntax + build exit 0 + manuel mantık doğrulaması.
- **G6:** /code-review medium.
- **G7:** versiyon v3.54.0 + (gerekirse) home.html ?v= (build otomatik).

## Critical Files
- `frontend/assets/js/modules/ds_learning_module.js` (_renderSchemaSelect)
- `frontend/dist/*` (rebuild) + `app/core/config.py` (versiyon)
- CSS: reuse (yeni dosya yok). Gerekirse ds_learning.css'e minik `.ds-schema-empty`.

## Risk
| Risk | Mit |
|---|---|
| Filtre count'u bozar | count tüm `.ds-schema-cb:checked` sayar (görünürlükten bağımsız) |
| Gizli (filtreli) şema seçili kalır + örneklenir | KASITLI — filtre yalnız görünüm; seçim korunur (Tümünü Seç/Temizle tüm liste) |
| show-selected + deselect → liste boşalır | boş-durum mesajı + clear/toggle ile geri gelir |
| bundle rebuild atlanır | KAP 4 build zorunlu |

## Verification
- node -c ds_learning_module.js + node build.mjs exit 0.
- Mantık: ara→filtrele, clear→geri, toggle→yalnız seçili, count doğru, boş-durum, a11y.
- /code-review medium.

## Out-of-scope
- Backend değişikliği yok (schema listesi + collect-samples aynı).
</content>
