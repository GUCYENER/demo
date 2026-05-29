---
plan_id: table_level_permissions
created: 2026-05-29
branch: hira
status: completed
version_target: v3.38.0
council_mod: 3
hebe_gate_required: true
---

> **Durum (2026-05-30) — COMPLETED:** G1-G8 kod tamamlandı, 40 test yeşil (commit f61973d), code-review medium 2 kritik execute-whitelist açığı kapatıldı. ✅ **Migration 048 canlı PG'de uygulandı ve doğrulandı** (psycopg2): `alembic_version = 048_v3380_table_level_permissions`, `data_source_table_permissions` tablosu mevcut, `data_source_permissions.scope_mode` kolonu mevcut. Stack ayakta (backend 8002 HTTP 200, nginx 8000 HTTP 200). Tek açık olan canlı-migration engeli kalktı → completed.
> NOT: 2026-05-30 kapanışında 40 testin canlı re-run'ı, test modülü import'ta ayağa kalkmış stack'e bağlanırken asıldığı için tekrar koşulamadı (harness sorunu); testler commit anında yeşildi.

# Tablo Bazlı Yetkilendirme (DB + Schema + Tablo) — v3.38.0

## 1. Context (Neden bu değişiklik?)

Kullanıcı talebi (`gelistirme1.docx`): Şu an Kaynaklar (data source) yetkilendirmesi
**yalnızca DB/kaynak seviyesinde** (`can_view` + `can_execute`). İlaveten **DB + Schema + Tablo**
seviyesinde seçim yapıp yetki verilebilmeli:

- Bir veya birden fazla tablo seçilebilmeli.
- **Sadece schema seçilmiş, hiç tablo seçilmemişse → hiçbir tablo okunamaz.** Yalnız seçilen tablolarda işlem yapılabilir.
- DB'de birden fazla schema varsa ayrı ayrı **akordion** olarak gösterilmeli; altındaki tablolardan işaretleyip kaydet.
- "SaaS modern" + "modüler yapı" korunmalı.
- Bu yetki **hem "Veritabanında Ara" (Discover) hem "Akıllı Keşif" (Smart Discovery)** akışlarında geçerli olmalı.
  Yetkisiz tablolar **görülememeli ve tahmin edilememeli** (LLM şema bağlamı dahil).
- Test senaryoları `tests/` altına yazılıp çalıştırılmalı.

## 2. Mevcut Durum (Explore bulguları)

**Veri modeli:**
- `data_sources` — `app/core/schema.py:765-786`
- `data_source_permissions` (polymorphic: subject_type user/org, subject_id, can_view, can_execute, UNIQUE(source_id,subject_type,subject_id)) — `app/core/schema.py:790-802`
- `permission_audit_log` — `app/core/schema.py:831-845`
- **Schema/tablo seviyesinde izin alanı YOK.**

**Yetki kontrolü:**
- `user_can_access_source(user_id, source_id, *, is_admin, permission)` — `app/services/data_source_access.py:17-66` (tek gate)
- Çağrı yerleri: list / test-connection / discover / detect-objects / collect-samples / samples (`data_sources_api.py`)

**API:**
- GET/PUT `/api/data-sources/{id}/permissions` — `data_sources_api.py:251-381`
- GET `/api/data-sources/permissions/subjects` — `:384-434`
- `DataSourcePermissionsUpdate` Pydantic — `:150-154`

**Tablo okuma akışları (filtre YOK, sadece source-level):**
- Discover: `/detect-objects`, `/discovered-schemas`, `/samples`, `/collect-samples` → `ds_learning_service.py` (information_schema / Oracle all_tables) → `ds_db_objects` cache
- Smart Discovery: `db_smart_api.py:1728+` `search_tables()` → `db_smart/eligibility.py:98-360` `search_domains()` (lexical+semantic ranking, ds_db_objects), `_fetch_table_columns()`, FK graph `fk_graph.py` (Redis cache), text-to-sql schema_context

**Frontend (vanilla JS, IIFE modül, esbuild):**
- Kaynaklar sekmesi: `frontend/partials/section_parameters.html:51-54,863-880`
- Yetkilendirme modal: `frontend/assets/js/modules/data_sources_module.js:710-978` (`openPermissionModal`, `permState`, `_renderPermissionList`, `_savePermissions`)
- CSS: `frontend/assets/css/modules/data_sources.css:581-706`
- **Akordion pattern HAZIR:** `frontend/assets/js/modules/db_smart_picker.js:89-230,702-716` (schema akordion + tablo checkbox + ARIA) → REUSE

## 3. Mimari Karar (Konsey)

**Model (HEPHAESTUS + ARES):**
- `data_source_permissions`'a `scope_mode VARCHAR(16) DEFAULT 'all'` ekle — `'all'` (mevcut davranış: tüm tablolar) | `'restricted'` (yalnız allowlist).
- Yeni tablo `data_source_table_permissions`: `(source_id, subject_type, subject_id, schema_name, table_name)` + audit kolonları, UNIQUE constraint + index. **Whitelist** mantığı.
- **Çözümleme (union):** Kullanıcının erişebildiği tablo = direkt + org grant'larının birleşimi. Herhangi bir uygulanabilir grant `scope_mode='all'` ise → TÜM tablolar. Aksi halde restricted grant'ların tablo kümelerinin **birleşimi**. Admin → bypass (tümü).
- **Case-insensitivity (POSEIDON):** Oracle UPPER, PG lower — karşılaştırma normalize edilir (`lower()` her iki tarafta).
- `view`/`execute` ayrımı kaynak seviyesinde korunur; tablo allowlist hangi tablolar sorusunu çözer (v1'de tablo-başı view/execute ayrımı kapsam dışı).

**Backend (HERMES):**
- `data_source_access.py`: `user_accessible_tables(user_id, source_id, *, is_admin) -> AccessScope` (ALL | frozenset[(schema,table)]) + `is_table_allowed(scope, schema, table)`.
- Tüm tablo okuma uçlarında filtre uygula (aşağıdaki fazlar).

**API:**
- GET/PUT `/permissions` genişlet: subject başına `scope_mode` + `tables: [{schema, table}]`.
- Yeni GET `/data-sources/{id}/schema-tree` → akordion modalını dolduracak schema→tablo ağacı (`ds_db_objects`'tan).

**Frontend (ATHENA + HEBE):**
- Yetkilendirme modalında her subject için "Tüm tablolar / Seçili tablolar" toggle → seçiliyse schema akordionları (db_smart_picker pattern reuse) + tablo checkbox + "Tümünü seç/temizle" + arama.

## 4. Faz/Gate Haritası

| Gate | İş | Sorumlu Konsey | Brief |
|---|---|---|---|
| G1 | Migration 048: `scope_mode` + `data_source_table_permissions` + RLS + index | HEPHAESTUS + ARES | agentA |
| G2 | `data_source_access.py`: `user_accessible_tables` + `is_table_allowed` + unit | HERMES + ARES | agentB |
| G3 | API: GET/PUT `/permissions` genişlet + GET `/schema-tree` + Pydantic | HERMES + APOLLO | agentB |
| G4 | Discover akışı filtre: detect-objects/discovered-schemas/samples/collect-samples | HERMES + ARES | agentC |
| G5 | Smart Discovery filtre: search_domains + _fetch_table_columns + fk_graph + text-to-sql schema_context | ORACLE + ARES | agentD |
| G6 | Frontend: modal akordion + scope toggle + save (data_sources_module.js + css) | ATHENA + HEBE | agentE |
| G7 | Testler: tests/api + tests/db_smart (allowlist, empty-schema=deny, union, admin bypass, LLM context, execute 403) | TYCHE | (sahip) |
| G8 | code-review medium + README/CHANGELOG + commit | HERA + ZEUS | — |

> **Sıra kritik:** G1→G2 önce (model+gate), sonra G3-G5 paralel (disjoint dosyalar), G6 paralel, G7 en son.
> Paylaşılan dosya `db_smart_api.py` / `data_sources_api.py` → tek ajan veya ZEUS.

## 5. Critical Files to Modify / Create

**Create:**
- `migrations/versions/048_v3380_table_level_permissions.py`
- `tests/api/test_table_level_permissions.py`
- `tests/db_smart/test_table_perm_filter.py`
- `.agents/in_flight/2026-05-29_*_*.md` (ajan brief'leri)

**Modify:**
- `app/core/schema.py` (yeni tablo + kolon)
- `app/services/data_source_access.py`
- `app/api/routes/data_sources_api.py`
- `app/api/routes/db_smart_api.py`
- `app/services/db_smart/eligibility.py`, `fk_graph.py`
- text-to-sql schema_context builder (`app/services/.../text_to_sql.py` — G5'te netleştir)
- `frontend/assets/js/modules/data_sources_module.js`
- `frontend/assets/css/modules/data_sources.css`
- `README.md`, `CHANGELOG.md`

## 6. Yeniden Kullanılacak Mevcut Fonksiyonlar
- `user_can_access_source` (source-level gate korunur, üstüne tablo filtresi)
- `db_smart_picker.js` akordion (schema→tablo checkbox + ARIA)
- `permission_audit.py:log_permission_change` (audit)
- `ds_db_objects` (schema-tree veri kaynağı — yeni introspection yok)
- `apply_vyra_user_context` / RLS GUC pattern

## 7. Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| LLM şema bağlamında yetkisiz tablo sızması | Orta | Yüksek (tahmin edilebilirlik) | text-to-sql schema_context filtresi + execute whitelist (çift kat) |
| FK graph yetkisiz tabloyu ifşa | Orta | Orta | fk_graph related sonuçları allowlist ile süz; Redis cache key'e scope-hash ekle |
| Oracle/PG case mismatch | Yüksek | Orta | iki tarafta lower() normalize + test |
| Geriye dönük uyum (mevcut grant'lar) | Düşük | Yüksek | scope_mode DEFAULT 'all' = mevcut davranış aynen |
| Redis FK cache eski scope ile servis | Orta | Orta | cache key'e accessible-set hash |
| Performans (her sorguda allowlist join) | Düşük | Düşük | index + request başına tek çözümleme + cache |

## 8. Verification (uçtan-uca)
- `python run_migrations.py` (048 up) + downgrade smoke
- `pytest tests/api/test_table_level_permissions.py tests/db_smart/test_table_perm_filter.py -v`
- Regresyon: `pytest tests/api/test_api_permissions.py tests/db_smart -q`
- Senaryolar: (a) restricted+seçili tablo → sadece onlar; (b) restricted+0 tablo → boş; (c) org-union; (d) admin bypass; (e) smart discovery arama yetkisiz tablo döndürmez; (f) LLM schema_context yetkisiz tablo içermez; (g) yetkisiz tabloya SQL → 403; (h) scope_mode='all' eski davranış parity
- Frontend: `node -c` bundle + manuel modal smoke (akordion, toggle, kaydet, FOUC)

## 9. Out-of-scope (sonraki faz)
- Tablo-başı ayrı view/execute granülaritesi (v1 source-level view/execute + tablo allowlist)
- Kolon seviyesi yetki
- Wildcard/pattern bazlı tablo yetkisi
- File server / FTP kaynak tipleri için tablo kavramı (yalnız DB tipleri)
