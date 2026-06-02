---
plan_id: fk_synthetic_discovered_tables_only
created: 2026-06-02
branch: hira
status: completed
version_target: v3.48.0
council_mod: 3
hebe_gate_required: false
closed: 2026-06-02
closure_note: "v3.48.0 commit a23648e ile sevk edildi (EXISTS ds_db_objects filtresi + 48 test). Frontmatter status flip gecikmişti."
---

# FK Loop Sentetik SQL — Yalnız Keşfedilen Tablolar İçin

## Context (Neden?)
Kullanıcı (ekran görüntüsü): "DB Öğrenme Loop — Sentetik SQL Üret (FK Loop)" sentetik
sorguları, keşfedilmemiş (ds_db_objects'te olmayan) tabloları da kapsayan FK ilişkileri
için üretiyor. İstek: **sentetik SQL yalnız KEŞFEDİLEN tablolar için üretilmeli.**
"Keşfedilen" = `ds_db_objects`'te kayıtlı nesne (detect_objects çıktısı).

## Mevcut Durum (Explore bulguları — kanıtlı)
- `fk_synthetic_generator._fetch_relationships` (satır 373) → `generate_for_source`'un
  TEK ilişki kaynağı (satır 773 `rels = _fetch_relationships(cur, source_id)`).
- SELECT (satır 399-422) `ds_db_relationships WHERE source_id = %s` + şema-dışlama (P0)
  + confidence/inferred filtre + `rejected_at IS NULL`. **ds_db_objects üyelik kontrolü YOK.**
- `ds_db_objects` (schema.py:909): id, source_id, schema_name, object_name, object_type,
  columns_json, ... → keşfedilen tablolar/view'lar.
- `ds_db_relationships` (schema.py): from_schema/from_table, to_schema/to_table (FK çiftleri).
- Her ikisi VYRA iç PG tabloları, aynı scoped `cur` (apply_company_scope + source GUC) ile
  sorgulanır → dialect/RLS ek-endişesi yok.
- Mock testler (`tests/test_fk_loop_improvements.py`) SQL-substring eşleştirir
  (`"from ds_db_relationships"`) → DB-tarafı EXISTS eklenince mevcut testler KIRILMAZ.

## Faz/Gate Haritası
- **G1 — Filtre (HEPHAESTUS + ORACLE):** `_fetch_relationships` SELECT'ine iki
  `EXISTS(ds_db_objects)` (from_table + to_table keşfedilmiş olmalı). Şema eşleşmesi
  NULL-tolerant (tablo adı eşit + şema yalnız iki tarafta da doluysa eşit).
- **G2 — Test (TYCHE):** Üretilen SQL'de `ds_db_objects` EXISTS var (string assert) +
  mevcut 109+512 suite yeşil kalır (parity, daraltma-only).
- **G3 — Code review (ZORUNLU):** `/code-review medium` → bulgular inline/backlog.
- **G4 — Versiyon/Build (HERA):** README + config.py APP_VERSION → v3.48.0, CHANGELOG.

## Critical Files to Modify
- `app/services/db_learning/fk_synthetic_generator.py` (_fetch_relationships SELECT)
- `tests/test_fk_loop_improvements.py` (yeni test: discovered-only SQL assert)
- `README.md` + `app/core/config.py` (versiyon)

## Yeniden Kullanılacak Mevcut Fonksiyonlar
- Mevcut `_fetch_relationships` SELECT yapısı + `_MockCursor` test deseni.

## Tasarım (G1 — kesin SQL)
`_fetch_relationships` WHERE'ine eklenecek (parametre yok, alt-sorgu korelasyonlu):
```sql
AND EXISTS (
    SELECT 1 FROM ds_db_objects o
    WHERE o.source_id = ds_db_relationships.source_id
      AND LOWER(o.object_name) = LOWER(ds_db_relationships.from_table)
      AND (ds_db_relationships.from_schema IS NULL OR o.schema_name IS NULL
           OR LOWER(o.schema_name) = LOWER(ds_db_relationships.from_schema))
)
AND EXISTS (
    SELECT 1 FROM ds_db_objects o2
    WHERE o2.source_id = ds_db_relationships.source_id
      AND LOWER(o2.object_name) = LOWER(ds_db_relationships.to_table)
      AND (ds_db_relationships.to_schema IS NULL OR o2.schema_name IS NULL
           OR LOWER(o2.schema_name) = LOWER(ds_db_relationships.to_schema))
)
```
- object_type filtresi YOK (FK endpoint adı ds_db_objects'te varsa "keşfedilmiş" sayılır).
- NULL-tolerant şema → geçerli keşfedilmiş tabloyu over-filter etmez.

## Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Over-filter (geçerli keşfedilmiş tablo elenir) | Düşük | Sentetik azalır | NULL-tolerant şema eşleşmesi |
| Şema repr drift (FK vs objects) | Düşük | bazı çift elenir | tablo-adı eşleşmesi yeterli, şema opsiyonel |
| Tüm ilişkiler zaten keşfedilmiş | — | no-op (güvenli) | daraltma yalnız fazlalığı eler |
| Perf (EXISTS) | Düşük | minimal | ilişki seti küçük + idx_source |

## Verification
- `pytest tests/test_fk_loop_improvements.py tests/test_synthetic_templates.py
  tests/test_few_shot_auto_populator.py -q` → yeşil
- Yeni test: `_fetch_relationships` SQL'inde `ds_db_objects` + iki EXISTS geçer
- py_compile temiz
- /code-review medium

## Durum (2026-06-02)
- ✅ G1: `_fetch_relationships` SELECT'e iki NULL-tolerant `EXISTS(ds_db_objects)` eklendi.
- ✅ G2: yeni test `test_only_discovered_tables_filter_in_sql` + parity (48 passed, mevcut suite yeşil), py_compile OK.
- ✅ G3 code-review (medium): **CONFIRMED bug YOK.** Kritik risk (RLS→total-filter) REFUTED:
  mig 007/008 → ds_db_objects ve ds_db_relationships AYNI `rls_source_scoped` policy
  (source_id=app.current_source_id veya bypass); EXISTS ayrıca açık `o.source_id=...source_id`
  korelasyonu taşır → hem RLS-aktif hem superuser-bypass modunda doğru. Tek düşük-öncelik not:
  ds_db_objects(object_name) index'i yok (arka-plan job + küçük veri → kabul, aksiyon gerekmez).
- ⏳ G4: versiyon bump (v3.48.0) + commit — kullanıcı onayı bekliyor.

## Out-of-scope
- "Yalnız zenginleştirilmiş (enrichment'lı) tablolar" semantiği (detected aldık; enriched
  istenirse ds_db_object_enrichments join'i ayrı faz).
- ds_db_relationships'e fiziksel company_id kolonu (source-based RLS yeterli).
</content>
