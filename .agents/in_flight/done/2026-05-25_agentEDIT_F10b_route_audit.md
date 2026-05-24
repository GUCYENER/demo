# Brief — F10b: Saved-reports route audit + 3 MAJOR bug fix

**Date:** 2026-05-25
**Agent:** `agentEDIT_F10b_route_audit`
**Council:** POSEIDON (data flow / wizard_state canonical source) + ARES (route + tenant scope + RLS) + ATHENA (step-state machine integrity) + HEBE (Save / Restore UX)
**Plan:** `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md` — Deliverable F10 (retro: brief dosyası eksik kalmıştı; F10b bunu da telafi eder)
**Trigger:** code review (F10 post-merge) — 3 MAJOR bug yakalandı

---

## Scope

F10 “Raporu Kaydet / Aç” akışındaki 3 silent-failure bug'ını kapatır:

1. **Bug 1 — Flat fallback route YOK (POSEIDON+ARES).** Frontend session-bound
   POST'u önce dener, başarısızsa flat `POST /api/db-smart/saved-reports`
   çağırıyor; ancak backend'de bu route hiç kayıtlı değil (sadece
   session-bound POST + GET/PATCH/DELETE var). Session drop'ta silent
   404/405 → kullanıcıya “kaydedildi” gibi görünebilir, hiçbir kayıt
   yapılmaz.

2. **Bug 2 — “Aç” button silent no-op (ATHENA+HEBE).** `_loadSavedReport`
   restore tamamlandıktan sonra `_setStep(4)` çağırıyor; ama `_setStep`
   içindeki forward-jump guard (`targetIdx > currentIdx + 1` → return)
   step 0'dan step 4'e jump'ı reddediyor. Toast “Rapor yüklendi: …”
   görünüyor, UI step 0'da kalıyor.

3. **Bug 3 — Session-bound save client wizard_state'i drop ediyor (POSEIDON).**
   Frontend `_buildWizardState()` ile canonical state hazırlıyor (`body`
   içine koyuyor), ama session-bound branch body'sine sadece
   `{name, description, tags}` yolluyor. Backend `post_save_report`
   `wizard_state`'i session context'ten (`ctx.get("wizard_state")`) okuyor.
   Session context wizard-step transition'larında auto-sync edilmediği
   için → stale/empty kayıt riski.

**Out of scope:**
- F10 plan'daki diğer alt-deliverable'lar (UI modal, listele/sil) zaten merge'lendi.
- Share token / audience / audit log F38 kapsamında.

---

## Backend changes — `app/api/routes/db_smart_api.py`

### Pydantic models

`SaveReportRequest` (line ~120): yeni opsiyonel alanlar
```python
wizard_state: Optional[Dict[str, Any]] = None
generated_sql: Optional[str] = None
metric_key: Optional[str] = None
schema_version: Optional[str] = None
```

`SaveReportFlatRequest` (yeni): session-bağımsız flat payload
```python
class SaveReportFlatRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    source_id: Optional[int] = None
    wizard_state: Dict[str, Any] = Field(default_factory=dict)
    generated_sql: Optional[str] = None
    metric_key: Optional[str] = None
    tags: Optional[List[str]] = None
    schema_version: Optional[str] = Field(default="v3.36", max_length=20)
```

### Endpoint changes

`POST /sessions/{uid}/save-report` (line ~937, `post_save_report`):
- `body.wizard_state` dolu ise canonical → kullan; aksi halde eski davranış
  (`ctx.get("wizard_state")` → `dict(ctx)` fallback).
- `body.generated_sql` varsa `last_sql` olarak tercih edilir; yoksa
  `ctx.get("last_sql")`.

`POST /saved-reports` (yeni, `post_save_report_flat`):
- Session bağımsız; tenant scoping `current_user` üzerinden RLS
  (`apply_vyra_user_context`).
- Service: mevcut `saved_reports.save(cur, current_user, …)`'i kullanır —
  signature `source_id`, `wizard_state`, `last_sql`, `description`, `tags`
  parametrelerini destekliyor; helper imzasını değiştirmedik.
- Response: aynı `SaveReportResponse {report_id, saved_at}` shape — frontend
  branch'ları tek tip parser kullanabilir.

---

## Frontend changes — `frontend/assets/js/modules/db_smart_wizard.js`

### `_setStep` (line ~136) — yeni opt param

```js
function _setStep(n, opts) {
    …
    const force = !!(opts && opts.force);
    if (!force && currentIdx >= 0 && targetIdx > currentIdx + 1) return;
    …
}
```

`force:true` yalnız trusted restore call-site'ından (şu an sadece
`_loadSavedReport`) geçilir; normal kullanıcı navigation hâlâ guarded.

### `_loadSavedReport` (line ~2009)

```js
_setStep(4, { force: true });
```

### `_saveCurrentReport` (line ~2087) — session-bound body genişletildi

```js
body: JSON.stringify({
    name, description: description || null, tags: null,
    wizard_state: wizard_state,
    generated_sql: body.generated_sql,
    metric_key: body.metric_key,
    schema_version: body.schema_version,
}),
```

Flat fallback (`else` branch) zaten doğru body'yi yolluyor → değişmedi,
artık backend route var.

---

## Accept criteria

1. **Bug 1 / route varlığı.**
   `grep -n 'saved-reports' app/api/routes/db_smart_api.py` çıktısında
   `@router.post("/saved-reports"` görünür (yeni `post_save_report_flat`).

2. **Bug 1 / e2e.** `_state.sessionUid = null` iken modal'dan
   “Kaydet” → backend log 201, `dbsmart_saved_reports` tablosunda
   yeni kayıt (user_id, company_id current_user'dan).

3. **Bug 2 / restore.** “Akıllı Keşfi” aç (step 0), listeden bir
   kayıtlı rapora “Aç” → toast “Rapor yüklendi: …” + UI **step 4**
   (Önizleme) gösterilir, lastGeneratedSql AST editor'a basılı gelir.

4. **Bug 3 / wizard_state body.** Network panel'de session-bound
   `POST /sessions/{uid}/save-report` request body'sinde
   `wizard_state` alanı dolu görünür (selectedTableId + reportColumns +
   metric + filters dahil). DB satırında `wizard_state` JSONB ≠ `{}`.

5. **Build.** `cd frontend && npm run build` hatasız tamamlanır,
   `bundle.min.js` yeni `force` token'ını içerir (`grep "force" dist/bundle.min.js`).

---

## Restart talimatı

- Backend: uvicorn restart **ŞART** — yeni route + Pydantic model değişiklik
  (FastAPI route table'ı boot'ta build edilir).
- Frontend: hard-reload (Ctrl+Shift+R) **ŞART** — `_setStep`, `_saveCurrentReport`,
  `_loadSavedReport` değişti + bundle yeniden build edildi.

---

## Smoke test senaryosu

1. **Modal-mode session yok save:**
   - DevTools console: `window.DbSmartWizard._state.sessionUid = null` (veya doğal modal flow).
   - Save modal aç → ad gir → Kaydet → 201 + “Rapor kaydedildi” toast.
   - `SELECT id, wizard_state FROM dbsmart_saved_reports ORDER BY id DESC LIMIT 1;`
     → wizard_state populated.

2. **Step 0 → restore Step 4:**
   - Wizard'ı reset (step 0) → kayıtlı rapor listesinden “Aç”.
   - UI step 4 (Önizleme) yüklensin, `lastGeneratedSql` AST editor'a yansısın.

3. **wizard_state body in session-bound save:**
   - Wizard'da source + table + metric seç → save modal → Kaydet.
   - Network: request body'de `wizard_state.selectedTableId` + `.metric` + `.reportColumns` görünür.

---

## Council sign-off (gerekli)

- POSEIDON: canonical wizard_state path (client → API → DB) verify
- ARES: yeni flat route tenant scoping + RLS (`apply_vyra_user_context`) verify
- ATHENA: `_setStep` force-bypass yalnız restore call-site'ında kullanıldığını verify
- HEBE: Save / Restore UX (toast + step transition) end-to-end manuel check
