# VYRA Changelog

## v3.38.1 — 2026-05-30 — Bulgular4 Round 2 (5 Smart Discovery fix)

> Kullanıcı: "bu bulguları daha önce düzeltmiştin ama sorun değişti" (v3.37.9 eksik/regresyon).
> Kök nedenler **kanıtla** doğrulandı (kod okundu + regex test + DB sorgulandı). Plan:
> `.agents/plans/2026-05-29_2336_bulgular4_round2_v1.md`. Konsey: ORACLE+HERMES (B4-1),
> ORACLE+ARES (B4-2), ATHENA+HEBE (B4-3), HERMES+POSEIDON (B4-4), ATHENA+APOLLO+HEBE (B4-5).

- **B4-1 — WHERE kriter ekleyince 400 "kabul etmiyor":** FE filtreyi DÜZ `{expr,op,value}`
  olarak `/ast/patch` `args`'ında gönderiyordu; backend `add_filter(ast, **args)` ama imza tek
  `filt` dict → **TypeError → 400 "AST args hatası"**. `ast_renderer.add_filter` artık hem düz
  alanları (expr/op/value/column) hem `{filt:{...}}` kabul eder (geriye uyumlu).
- **B4-2 — "Çalıştır"da W0SELECT/W0FROM garbage devam:** `_GLUED_KW_RE` anchor'ı `(?<![^\n])`
  YALNIZ satır başı garbage'ını yakalıyordu; LLM tek-satır SQL üretince `W0FROM` (boşluk sonrası)
  kaçıyordu (regex testiyle kanıtlandı). Anchor → `(?:^|(?<=\s))` (satır başı VEYA whitespace
  sonrası). String-literal/quoted-ident FP guard'ları korundu.
- **B4-3 — Silinen kayıtlı rapor ekrandan hemen kaybolmuyor:** `refresh()` taze GET'i DELETE
  commit'ini race ediyordu. `SavedReportsGrid.removeItem(id)` (optimistic) eklendi; `onDeleted(id)`
  kartı anında çıkarır, sonra refresh ile reconcile.
- **B4-4 — Kayıtlı raporu çalıştır → "Veri kaynağı bilgisi bozuk veya eksik":** DB sorgusu
  rapor source_id kolonunun **NULL** kaldığını gösterdi (save endpoint client'a güveniyordu,
  wizard_state.source_id'ye düşmüyordu; last_dialect hep None). Save (`post_save_report_flat` +
  session) artık `source_id`/`dialect`'i wizard_state'ten fallback eder; mevcut NULL rapor
  wizard_state'ten backfill edildi.
- **B4-5 — "Yeni Keşif" fresh değil + çevrilmemiş i18n key:** (a) `_resetWizardState` `#dswResults`
  (Seçilen tablolar özeti) DOM'unu temizlemiyordu → panel reuse'da eski raporun tabloları
  görünüyordu; reset'e temizlik eklendi. (b) Kod `wizard.toast.select_table_first` çağırıyordu
  ama i18n'de yalnız `wizard.hint.*` vardı → ham key; toast key TR/EN eklendi.
- **Test:** `tests/db_smart/test_bulgular4_round2.py` 11/11 PASS (add_filter flat/wrapped/
  positional/unary/value-0/missing-expr + regex inline/linestart/literal-FP/quoted-FP/clean).
- ⚠️ Backend `--reload` yok → bu fix'ler için uvicorn restart edildi; frontend bundle rebuild.

## v3.38.0 — 2026-05-29 — Tablo Bazlı Yetkilendirme (DB + Schema + Tablo)

> Konsey: HEPHAESTUS + ARES (model/migration) · HERMES + APOLLO (API) · ORACLE + ARES (Smart Discovery/text-to-sql filtre) · ATHENA + HEBE (frontend) · TYCHE (test). Plan: `.agents/plans/2026-05-29_2158_table_level_permissions_v1.md`.

Kaynak (data source) yetkilendirmesi DB seviyesinden **DB + schema + tablo** seviyesine indirildi. Bir subject (kullanıcı/org) için kaynak bazlı `scope_mode`: `all` (tüm tablolar, geriye uyumlu varsayılan) veya `restricted` (yalnız seçili tablo allowlist'i). **Yalnız schema seçilip tablo seçilmezse hiçbir tablo okunamaz.** Kullanıcının nihai erişimi direkt + org grant'larının birleşimidir; herhangi bir grant `all` ise tüm tablolar.

- **Model (mig 048):** `data_source_permissions.scope_mode` kolonu + yeni `data_source_table_permissions` (source, subject, schema, table allowlist). RLS yok (admin-yönetimli, mevcut izin tabloları ile tutarlı). schema.py fresh-install DDL'i de güncellendi.
- **Gate:** `data_source_access.user_accessible_tables() → AccessScope` (case-insensitive, admin bypass, union, fail-closed) + `db_smart/table_scope.resolve_scope()` sarmalayıcı.
- **API:** GET/PUT `/data-sources/{id}/permissions` `scopes` (scope_mode + tables) ile genişletildi; yeni GET `/data-sources/{id}/schema-tree` (akordion ağacı). Audit before/after `scope_mode` taşır.
- **Uçtan uca filtre (yetkisiz tablo görülemez/tahmin edilemez):** Discover (`discovered-schemas`/`samples`), Smart Discovery (`search_tables`, `related` FK graph node+edge, `list_columns`/`multi` → 404/skip), **text-to-sql `get_schema_context` LLM bağlamı** (tek choke-point), `deep_think` ML schema_record, ve **SQL execute whitelist** (`deep_think` DB-Only + `generate_report`) kullanıcının `can_execute` kapsamıyla kesiştirilir; boş restricted kapsam → çalıştırma reddedilir (allow-all'a düşmez).
- **Frontend:** Yetkilendirme modalında subject başına "Tüm tablolar / Seçili tablolar" + schema akordion + tablo checkbox + arama (db_smart_picker pattern reuse, ARIA/escape/toast korunur).
- **Test:** `tests/api/test_table_level_permissions.py` (16) + `tests/db_smart/test_table_perm_filter.py` (4) — allowlist, restricted+0 tablo=deny, union, admin bypass, case-insensitive, fail-closed. 35 ilgili + 35 deep_think regresyon yeşil.
- **code-review (medium):** deep_think DB-Only execute whitelist ve generate_report `allowed_tables or None` boş-liste→allow-all açıkları kapatıldı (scope-kesişimi + boş→reddet); `get_schema_context` opt-in süzgeç tüm production caller'larda `user_ctx` geçtiği doğrulandı.
- ⚠️ **Deploy:** Migration 048 PG kapalı olduğu için bu oturumda uygulanmadı — `python run_migrations.py` ile çalıştırılmalı.

## Graphify v1.2 → v1.2.2 — 2026-05-26 — Coverage + Embedding + Bug-fix + Concurrency Sprint

> Graphify paketinin geliştirme adımları VYRA `CHANGELOG.md`'de izlenir; paket kendi git repo'sundadır (`General_Graphify/` initial commit `77330ab`, Wave D `d266249`). Tam detay: [`.agents/workflows/graphify_v12_release_notes.md`](.agents/workflows/graphify_v12_release_notes.md).

- **Wave A (G1-G8)** — File entity (55→633), Function AST emit (0→2102), `defined_in`/`imports`/`calls` predicate emission (0→16 621), post-mine embedding sweep (%0→%100), mine path resolution, KAP 10c.3 coverage threshold assert, `coverage-report` CLI subcommand.
- **Wave B (T1-T8)** — pytest paketi 171→186 test (%74 coverage); HEBE config (`pytest.ini` + `conftest.py`); ARES F1-F5 spec drift kaydı.
- **Wave C (v1.2.1)** — BUG-G1 `__pycache__` leak fix, BUG-G2 `database is locked` race partial fix (`PRAGMA busy_timeout=30000` + `_RetryingConnection` proxy; cross-instance race xfail strict=False → Wave D), R5 Class count UNION (0→298), BUG-G3 T7 entity-relative assertion düzeltmesi.
- **Wave D (v1.2.2)** — BUG-G2 final closure: class-level `_RetryingConnection._locks: Dict[str, threading.RLock]` map keyed by `db_path`; cross-instance writer serialization; `_tx()` lock-across-BEGIN/COMMIT; `_is_write_sql()` heuristic (SELECT/PRAGMA-read bypass). xfail kaldırıldı + yeni `test_two_instances_serialize_on_same_db_path` (40 yazım/2 thread, <5s).
- **Workflow** — `vyrazeus.md` KAP 10c.3 coverage threshold gate (`--threshold 0.95`); Graphify-first lookup + mine-after-fix kuralları (memory); sub-agent malware-reminder refusal pattern (memory feedback).
- **Final test**: 187/187 PASS, coverage %74.

## v3.37.0 — 2026-05-26 — Smart Discovery bulgular B1-B8 + LLM augmentation

- **B1** — Smart Discovery saved-report rerun fix (`_load_source` db_type normalize + DS guard + backfill 047b).
- **B2** — SQL pretty-print önizleme paneli (keyword newlines).
- **B3** — Saved report delete → grid auto-refresh + toast.
- **B4** — LLM Metric Suggest endpoint (`POST /api/db/smart/llm/metric-suggest`).
- **B5a** — Step 3 Next disable + toast (empty columns).
- **B5b** — LLM Column Suggest endpoint (2 kategori: metric-bound + dimensions).
- **B6** — "Bu rapordan ne bekliyorsunuz?" sticky footer textarea + `state.user_intent`.
- **B7a/B7b** — Çalıştır button sticky bottom-right + ORDER BY editable chip (ASC/DESC + drag-reorder).
- **B8** — LLM Format Suggest endpoint (3-5 format card + `chart_type` whitelist).
- **Migration** — 047 (app_version bump) + 047b (saved_reports db_type backfill — standalone).
- **Tests** — 79 yeni pytest PASS (10 + 8 + 17 + 20 + 15 + 9).
