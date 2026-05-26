---
plan_id: 2026-05-25_2230_smart_discovery_bulgular_v3370
title: Smart Discovery v3.37.0 — bulgular.docx (B1-B8) tam kapatma
version: v1
created: 2026-05-25 22:30
council_owner: ZEUS (coord), HERMES (release), HEBE (UX), METIS (LLM), ATHENA (BE), TYCHE (test), HEPHAESTUS (refactor), HERA (governance)
target_release: v3.37.0
status: gate-1 approved 2026-05-25, dispatch ready
scope_kind: bug-fix + UX polish + LLM augmentation
risk_class: M (multi-touch UX + LLM + DB connector polish)
---

# 1. Özet

`Gecici_Dosyalar_Sil/bulgular.docx` kapsamında 8 bulgu (B1-B8) — 1 P0 (kayıtlı rapor rerun kırık), 5 P1 (UX gate + LLM endpoint), 2 P2 (kozmetik). v3.37.0 sprintinde **tek pakette** kapatılır; B8 (rapor format galerisi) v3.38'e ertelenebilir (Open Q #3).

## 1.1 Bulgu kısa özet

| Kod | Öncelik | Başlık | Sahip |
|-----|---------|--------|-------|
| B1 | P0 | Saved report rerun: "Desteklenmeyen veritabanı tipi: db_type" | ATHENA |
| B2 | P2 | SQL pretty-print önizleme | HEBE |
| B3 | P1 | Delete confirmation → grid refresh | HEBE |
| B4 | P1 | Dynamic LLM metric generation | METIS |
| B5a | P1 | Boş kolon → Next disable + toast | HEBE |
| B5b | P1 | LLM column suggestion (metric-bound) | METIS |
| B6 | P2 | "Bu rapordan ne bekliyorsunuz?" sticky footer | HEBE |
| B7a | P2 | Çalıştır button konumu | HEBE |
| B7b | P1 | ORDER BY editable | HEBE |
| B8 | P1 | "Hazır rapor formatı öner" LLM butonu | METIS |

# 2. B1 Kök Sebep Analizi (kesinleşti)

**Hata literali**: `Desteklenmeyen veritabanı tipi: db_type` → `app/services/ds_learning_service.py:80`

**Root cause**: `app/api/routes/db_smart_api.py:903-911` `_load_source` fonksiyonu kayıtlı rapor JSON'undan source yüklerken `dialect` değişkenini normalize ediyor ama `source_dict["db_type"]` literal `"db_type"` string'i olarak kalıyor. Downstream `_get_db_connector(source_dict["db_type"])` çağrısı `"db_type"` string'ini DB type olarak yorumlamaya çalışıyor → ValueError.

**Fix**: `_load_source` sonunda tek satır:
```python
source_dict["db_type"] = dialect  # normalize before downstream consumers
```

**Verify**: `tests/api/routes/test_db_smart_api.py::test_load_source_normalizes_db_type` — postgres + mssql + mysql + oracle source fixture'ları rerun → 200, payload `source.db_type == dialect`.

**Retro backfill** (Open Q #5): Mevcut `saved_reports` tablosundaki kayıtlı JSON'larda `source.db_type` literal "db_type" olarak kayıtlı olabilir. İki seçenek:
- (a) Migration `047b` ile UPDATE: `saved_reports` `source_json->>'db_type' = 'db_type'` olanları engine tipine göre düzelt (engine info `connections` tablosundan join).
- (b) Manuel — operator destekli scripti, prod'da bir kez çalışır.

# 3. Dispatch Stratejisi (4 stack, 6 agent, disjoint scope)

## Stack 1 — Backend Bug (sequential, blocker)
- **Agent 1 / ATHENA-BE** — `db_smart_api.py:_load_source` fix + `ds_learning_service` defensive raise enhance + pytest 1 dosya.

## Stack 2 — LLM Endpoints (3 parallel)
- **Agent 2 / METIS-METRIC** — POST `/api/db/smart/llm/metric-suggest` (B4): table_columns + context → metric_name + agg + formula candidate'lar; Redis TTL 15dk. Yeni dosya `app/api/routes/llm_metric_api.py` + service `app/services/llm_metric_service.py` + pytest.
- **Agent 3 / METIS-COLUMN** — POST `/api/db/smart/llm/column-suggest` (B5b): metric_name + table_columns → kategori 1 (metric-bound), kategori 2 (related dimension). Yeni dosya `app/api/routes/llm_column_api.py` + service `app/services/llm_column_service.py` + pytest.
- **Agent 4 / METIS-FORMAT** — POST `/api/db/smart/llm/format-suggest` (B8): metric + columns + ds_intent → format card list (chart_type + title + group_by). Yeni dosya `app/api/routes/llm_format_api.py` + service `app/services/llm_format_service.py` + pytest.

## Stack 3 — Frontend Bundle (single agent — db_smart_wizard.js shared scope)
- **Agent 5 / HEBE-FE** — `frontend/db_smart_wizard.js` + `frontend/db_smart_wizard.html` + `frontend/css/db_smart.css` bundle:
  - B2 SQL pretty-print (sql-formatter lib veya manual)
  - B3 delete confirm → grid reload
  - B5a empty columns disable Next + toast
  - B6 sticky footer textarea "rapordan ne bekliyorsunuz"
  - B7a Çalıştır position normalize, B7b ORDER BY editable chip
  - LLM butonları (B4/B5b/B8) — fetch + spinner + chip pick UX
- **Tests**: `tests/frontend/test_smart_wizard_ux.py` (Playwright veya jsdom — TYCHE+HEBE karar verir).

## Stack 4 — Release Close-out (HERA)
- **Agent 6 / HERA-RELEASE** — version bump 3.36.0 → 3.37.0, migration `047_v3370_release_bump.py` (app_version setting update), CHANGELOG, plan archive, BITIR commit.

# 4. Migration

Tek migration: **`migrations/047_v3370_release_bump.py`**
- `system_settings.app_version = '3.37.0'`
- B1 retro backfill (Open Q #5 onayına göre 047b ayrı dosya veya inline).

**Karar**: Schema değişikliği yok — LLM endpoint'ler stateless + Redis cache.

# 5. Cache & LLM Provider

- **Redis TTL**: 15 dk her LLM endpoint için (key: `llm:metric:{table_hash}`, `llm:column:{metric}:{table_hash}`, `llm:format:{metric}:{cols_hash}`).
- **Provider**: ✅ KARAR — `app.core.llm.call_llm_api(messages)` kullanılır. `llm_config` tablosundan `is_active=TRUE` olan provider otomatik seçilir. Yeni key/cost gerek YOK; mevcut LLM resilience (retry/backoff) miras alınır.
- **Prompt yönetimi**: Yeni 3 prompt kategorisi DB'de — `metric_suggest`, `column_suggest`, `format_suggest` (prompt_templates tablosu, get_prompt_by_category ile çekilir). Fallback prompt'lar kodda.

# 6. Test Planı (TYCHE + ARES + HEBE + POSEIDON brief)

5 yeni pytest dosyası:
1. `tests/api/routes/test_db_smart_api_load_source.py` — B1 regression (4 dialect × 2 senaryo).
2. `tests/api/routes/test_llm_metric_api.py` — B4 endpoint contract + Redis cache hit.
3. `tests/api/routes/test_llm_column_api.py` — B5b endpoint contract + metric-bound filtering.
4. `tests/api/routes/test_llm_format_api.py` — B8 endpoint contract + format card schema.
5. `tests/frontend/test_smart_wizard_ux.py` — B2/B3/B5a/B6/B7 e2e (jsdom mock OR Playwright — POSEIDON kararı).

**Coverage hedef**: yeni kod ≥ 85%; B1 regression %100.

# 7. Risk Matrisi

| ID | Risk | Olasılık | Etki | Mitigasyon |
|----|------|----------|------|------------|
| R1 | LLM provider key eksik prod'da | Y | Y | Gate-1 Open Q #4; CI smoke test env var check |
| R2 | Redis down → LLM endpoint timeout | O | O | Try/except + 5sn timeout + sync passthrough |
| R3 | B1 retro backfill prod data corruption | D | Y | Dry-run flag + rollback script |
| R4 | `db_smart_wizard.js` shared scope merge çakışması | O | O | Stack 3 tek agent (disjoint kuralı) |
| R5 | LLM hallucination metric formula | Y | O | Validation layer + manual edit önce uygula |
| R6 | sql-formatter bundle size frontend | D | D | Manuel formatter ile başla, lib opsiyonel |
| R7 | Migration 047 idempotent değil | D | Y | `if exists` koruması + alembic-like versiyon kontrolü |
| R8 | Playwright headless Windows CI sorunu | O | D | jsdom fallback |

# 8. Açık Sorular (Gate-1 — KARARLAŞTI 2026-05-25)

| # | Soru | Karar |
|---|------|-------|
| 1 | B7a Çalıştır button konumu | ✅ Sağ alt sticky |
| 2 | `metric_library` DB tablosu | ✅ Korunur, LLM fallback static list |
| 3 | B8 rapor format galerisi v3.37 mi v3.38 mi? | ✅ v3.37 (paket bütünlüğü) |
| 4 | LLM provider | ✅ `app.core.llm.call_llm_api` (DB aktif config) |
| 5 | B1 retro backfill | ✅ Migration 047b (idempotent UPDATE + dry-run) |
| 6 | Migration 047 slug | ✅ `047_v3370_release_bump` |
| 7 | Restart bildirimi scope | ✅ Operator + ops doc |

**Gate-1 STATUS**: ✅ APPROVED — dispatch izni verildi.

# 9. Versiyon & BITIR

- `app.core.config.APP_VERSION = "3.37.0"`
- Migration 047 ile `system_settings.app_version` update.
- BITIR commit: `chore(v3.37.0): BITIR — smart discovery bulgular B1-B8 + LLM aug`
- Plan archive: `.agents/plans/archive/2026-05-25_2230_smart_discovery_bulgular_v3370_v1.md`

# 10. Sister Brief Dispatch (paralel iş)

- `graphify_v1_1_report_autogen` — bu plan kapsamında DEĞİL, ayrı brief; Stack 4 tamamlandıktan sonra dispatch.

# 11. Gate'ler

- **Gate-1** (now): Council masa + 7 Open Q onayı → dispatch izni.
- **Gate-2** (subagent done): Spec-vs-output tablo + code review + test sonuç → BITIR izni.

---

**Plan author**: ZEUS (Plan subagent rendered, ZEUS persisted)
**Approval needed from**: ZEUS, HERMES, HEBE, METIS, ATHENA, TYCHE, HERA
**Next step**: Gate-1 council masa.
