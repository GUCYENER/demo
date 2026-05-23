# VYRA Refactor Backlog

Last updated: 2026-05-23 (R005–R010 eklendi — HEPHAESTUS DB audit v3.32.0 Council Gate)

| ID   | Priority | Scope       | Risk | Effort | Title                                              | File(s)                                         | Status     | Notes                                          |
|------|----------|-------------|------|--------|----------------------------------------------------|-------------------------------------------------|------------|------------------------------------------------|
| R001 | P2       | single-file | low  | S      | Extract `_authFetch` helper — auth header DRY      | frontend/assets/js/modules/ds_enrichment_module.js | done       | Commit e14f0ca — 13 call site DRY |
| R002 | P2       | single-file | low  | XS     | Extract `_guardNoRunningJob` — preflight DRY       | frontend/assets/js/modules/ds_enrichment_module.js | done       | v3.31.0 bulk endpoint preflight'i absorbe etti; 3 frontend preflight kaldirildi (extraction yerine eliminate). Commit: bu sprint |
| R003 | P2       | single-file | low  | S      | Move pill inline-styles to CSS class `.ds-status-pill` | frontend/assets/js/modules/ds_enrichment_module.js | done       | Commit b5afc17 — CSS class + a11y bonus |
| R004 | P3       | single-file | low  | XS     | `_runConcurrent` worker return-type inconsistency  | frontend/assets/js/modules/ds_enrichment_module.js | wontfix    | bulkApprove + bulkApproveAll v3.31.0'da bulk endpoint'e gecti -> _runConcurrent callsite kalmadi. Helper utility olarak korundu (plan kararı), inconsistency moot |
| R005 | P1       | single-file | medium | S    | RLS USING clause order drift from mig 017 canonical pattern | migrations/versions/043_v3320_bulk_phase2.py | open | H1 — HEPHAESTUS audit; v3.33.0 RLS-strict sprint hedefi |
| R006 | P1       | cross-file  | medium | M    | Missing explicit `WITH CHECK` clause on `FOR ALL` policy (mig 043) | migrations/versions/043_v3320_bulk_phase2.py, app/core/db.py | open | H2 — HEPHAESTUS audit; `apply_company_scope` silent-fail risk; v3.33.0 RLS-strict sprint hedefi |
| R007 | P2       | single-file | low  | S      | No index on `ds_schema_record_warnings.enrichment_id` FK-equivalent | migrations/versions/043_v3320_bulk_phase2.py | open | M1 — HEPHAESTUS audit; seq-scan on per-enrichment admin filter; add with admin warning panel endpoint |
| R008 | P3       | cross-file  | low  | XS     | Index naming inconsistency: `idx_ds_table_enrich_*` vs convention `idx_table_enrich_*` | migrations/versions/043_v3320_bulk_phase2.py, migrations/versions/004_ds_enrichment_tables.py | open | M2 — HEPHAESTUS audit; ALTER INDEX non-breaking rename |
| R009 | P3       | cross-file  | low  | XS     | `detail TEXT` uncapped at DB layer — only app-layer cap enforced | migrations/versions/043_v3320_bulk_phase2.py, app/api/routes/data_sources_api.py | open | L1 — HEPHAESTUS audit; VARCHAR(1000) or CHECK constraint |
| R010 | P3       | single-file | low  | XS     | BackgroundTasks SIGTERM loss — operational runbook note missing | app/api/routes/data_sources_api.py | open | L2 — HEPHAESTUS audit; approve UPDATE already committed, only embedding gap; DOC-only fix |

---

## Detailed entries

### R001 — Extract `_authFetch` helper (auth header DRY)

**Files:** `frontend/assets/js/modules/ds_enrichment_module.js`

**Evidence:** `localStorage.getItem('access_token')` appears 13 times (lines 153, 195, 685, 697, 811, 870, 1076, 1120, 1160, 1188, 1267, 1280, 1336). At least 5 of those are full `fetch(url, { method:'POST', headers:{…Authorization…}, body:JSON.stringify(…) })` blocks (e.g. lines 697-708, 811-821, 870-880, 1196-1206, 1287-1295).

**Why now:** Any future cross-cutting header concern (x-csrf-token, request-id, tenant header) must currently be applied in ~13 places. Token retrieval is also not memoised per-call so repeated `localStorage` reads are unnecessary.

**Suggested approach:** Add a module-private helper:
```js
async function _authFetch(url, { method = 'GET', body } = {}) {
    const token = localStorage.getItem('access_token');
    return fetch(url, {
        method,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {})
    });
}
```
Replace all call sites. Behaviour is unchanged.

**Tests:** 1 smoke test mocking `localStorage` + `fetch`; existing integration tests should pass unchanged.

**Dependencies:** none

---

### R002 — Extract `_guardNoRunningJob` preflight helper

**Files:** `frontend/assets/js/modules/ds_enrichment_module.js`

**Evidence:** Near-identical preflight blocks at lines 1159-1170 (`bulkApprove`) and 1265-1277 (`bulkApproveAll`). A lighter variant also appears at lines 683-694 (`approveTable`). The only per-call difference is the button element ID and its reset `innerHTML`.

**Why now:** Copy-paste maintenance risk. If the endpoint path or error message changes, 3 sites must be updated in sync.

**Suggested approach:**
```js
async function _guardNoRunningJob(btn, resetHtml) {
    try {
        const res = await _authFetch(
            `/api/data-sources/${_currentSourceId}/check-running-job`
        );
        const data = await res.json();
        if (data.has_running) {
            _showToast('Keşif işlemi devam ediyor. Tamamlanmasını bekleyin.', 'warning');
            if (btn) { btn.disabled = false; btn.innerHTML = resetHtml; }
            return true;  // caller must return
        }
    } catch (e) { /* kontrol başarısız, devam et */ }
    return false;
}
```
**Depends on:** R001 (uses `_authFetch`). Can be done independently by inlining token for now.

**v3.31.0 note:** Per `.agents/plans/bulk_enrichment_endpoints.md`, the `/enrichment-approve-bulk` backend endpoint will absorb this guard server-side. Reassess whether this refactor is worth doing before that sprint; if v3.31.0 lands first, mark R002 `wontfix`.

**Tests:** Unit-test helper isolation; existing smoke tests should pass.

**Dependencies:** R001 (soft — can land independently)

---

### R003 — Move pill button inline-styles to CSS class `.ds-status-pill`

**Files:** `frontend/assets/js/modules/ds_enrichment_module.js` (lines 535, 568, 573, 578); target CSS: `frontend/assets/css/` (existing data-sources sheet or new `ds_enrichment.css`)

**Evidence:** `_pillStyle` helper at line 535 builds a ~130-character inline style string on every render call for each of the 3 status-filter pill buttons (lines 568, 573, 578). Active state is toggled via the full style recomputation rather than a CSS class or `data-active` attribute.

**Suggested approach:**
- Add `.ds-status-pill` base class and `.ds-status-pill[data-active="true"]` variant (plus per-variant colour tokens via `data-variant` attribute) to CSS.
- JS emits only count text and `data-active="true/false"` — drops the `_pillStyle` closure entirely.
- `role="group"` + `aria-label="Durum filtresi"` are already present at line 566 (added in v3.30.1); the A11y work is already done and survives this refactor unchanged.

**Tests:** Visual regression check; no unit tests required.

**Dependencies:** none

---

### R004 — `_runConcurrent` worker return-type inconsistency (TYCHE micro-note)

**Files:** `frontend/assets/js/modules/ds_enrichment_module.js`

**Evidence:**
- `bulkApprove` worker (line 1193): returns `{ objectId, enrichmentId, success: bool }` — result array is consumed on line 1215.
- `bulkApproveAll` worker (line 1285): returns `undefined` (no return statement) — `_runConcurrent` result array is discarded (`await` without assignment).
- `_runConcurrent` itself (lines 1386-1403) stores both outcomes uniformly in `results[]` without complaint.

**Why it matters:** The contract divergence is currently harmless because `bulkApproveAll` counts `successCount`/`failCount` via closure mutation rather than the results array. However, if a future caller expects a uniform return shape, the pattern is a silent landmine.

**Suggested approach:** Either (a) standardise both workers to return a result object and consume `_runConcurrent`'s return value, or (b) add a JSDoc `@typedef` documenting the two distinct usage patterns as intentional.

**Dependencies:** none

---

## v3.33.0 RLS-strict sprint — HEPHAESTUS DB audit findings (Council Gate v3.32.0)

### R005 — RLS USING clause order drift from mig 017 canonical pattern

**Files:** `migrations/versions/043_v3320_bulk_phase2.py:88-92`

**Why:** Mig 017 canonical `_POLICY_USING_PERMISSIVE` clause order (`migrations/versions/017_v3260_rls_tenant_tables.py:55-60`):
```
IS NULL
OR = ''
OR bypass='on'
OR company_id::text = ...
```
Mig 043 reorders and drops the `IS NULL` branch (`043:88-92`):
```
bypass='on'
OR company_id::text = ...
OR = ''
```
Functionally near-equivalent on PG >= 9.6 (`current_setting(..., true)` returns `''` not NULL on unset), but the clauses are not byte-identical with the established pattern. Any future grep/audit tool searching for the mig 017 canonical string will miss `ds_schema_record_warnings`, creating a silent audit gap.

**Suggested approach:** Restore clause order to match `_POLICY_USING_PERMISSIVE` and restore the `IS NULL` branch. Consider referencing a shared SQL constant rather than repeating the literal, or add a comment citing mig 017 as the source of truth.

**Tests:** Policy behaviour is unchanged; existing integration tests should pass. Add a migration smoke test asserting clause text matches canonical form.

**Dependencies:** none — can be its own migration patch or folded into the v3.33.0 RLS-strict migration.

---

### R006 — Missing explicit `WITH CHECK` clause on `FOR ALL` policy (mig 043)

**Files:** `migrations/versions/043_v3320_bulk_phase2.py:85-93`, `app/core/db.py:314-315`

**Why:** The policy at `043:86` is `FOR ALL` with only a `USING` clause. PostgreSQL implicitly reuses `USING` for `WITH CHECK` on `FOR ALL` policies, so the current behaviour is not broken. However:
1. Mig 017 explicitly separates `USING` and `WITH CHECK` (`017:79-80`) — consistency with the established pattern is lost.
2. `apply_company_scope` in `db.py:314` has a bare `except: pass` (`db.py:314-315`). If it silently fails, `current_setting('app.current_company_id', true)` stays `''`. The PERMISSIVE empty-string branch (`043:91`) then allows INSERT — this is load-bearing for warning persistence from the BG worker, but it means any future caller that forgets `apply_company_scope` will bypass isolation silently on INSERT as well as SELECT.

**Suggested approach (v3.33.0 RLS-strict sprint):** Add an explicit `WITH CHECK` that requires `company_id::text = current_setting(...)` (no empty-string fallback for writes). The `IS NULL`/`= ''` permissive branches should remain only in `USING` (read path). Tighten `apply_company_scope` to raise instead of silently passing when `company_id` is not None.

**Tests:** Unit test for `apply_company_scope` failure path. Integration test asserting INSERT is rejected when setting is unset.

**Dependencies:** R005 (should land together in the same RLS-strict migration).

---

### R007 — No index on `ds_schema_record_warnings.enrichment_id`

**Files:** `migrations/versions/043_v3320_bulk_phase2.py:62`

**Why:** `enrichment_id` has no FK (intentional — orphan-tolerant audit log) and no index. `idx_schema_warn_source` and `idx_schema_warn_company` exist (`043:73-80`), but an admin UI panel filtering warnings per-enrichment will seq-scan the full table.

**Suggested approach:** Add alongside the admin warning panel endpoint (same sprint):
```sql
CREATE INDEX IF NOT EXISTS idx_schema_warn_enrich
    ON ds_schema_record_warnings(enrichment_id);
```

**Tests:** Query plan assertion (EXPLAIN output) in migration smoke test.

**Dependencies:** Admin warning panel endpoint (new feature, not yet scheduled) — can be batched into the same migration that adds the endpoint.

---

### R008 — Index naming inconsistency: `idx_ds_table_enrich_*` vs convention `idx_table_enrich_*`

**Files:** `migrations/versions/043_v3320_bulk_phase2.py:52-54`, `migrations/versions/004_ds_enrichment_tables.py:72-75`

**Why:** The established convention in mig 004 is `idx_table_enrich_*` (no `ds_` prefix). Mig 043 creates `idx_ds_table_enrich_source_id_pk`. Any ops grep or `pg_stat_user_indexes` query using the pattern `idx_table_enrich_%` will miss the new index.

**Suggested approach:** `ALTER INDEX idx_ds_table_enrich_source_id_pk RENAME TO idx_table_enrich_source_id_pk;` — non-breaking, zero downtime.

**Tests:** Grep assertion in CI that all enrichment-table indexes match `idx_table_enrich_%` or `idx_schema_warn_%`.

**Dependencies:** none

---

### R009 — `detail TEXT` uncapped at DB layer

**Files:** `migrations/versions/043_v3320_bulk_phase2.py:67`, `app/api/routes/data_sources_api.py:1835`

**Why:** The `detail` column is `TEXT` with no length constraint. The only cap is `str(e)[:500]` applied in the BG worker at `data_sources_api.py:1835`. A future caller that writes to `ds_schema_record_warnings` directly (e.g. a new worker or a manual INSERT) could store unbounded text, causing table bloat.

**Suggested approach:** Change to `detail VARCHAR(1000)` or add a `CHECK (char_length(detail) <= 1000)` constraint. `VARCHAR(1000)` is sufficient headroom above the current 500-char app-layer cap while providing a DB-layer safety net.

**Tests:** Existing BG worker tests pass unchanged (500 < 1000). Add a test asserting INSERT of >1000-char detail is rejected.

**Dependencies:** none

---

### R010 — BackgroundTasks SIGTERM loss — operational runbook note missing (DOC only)

**Files:** `app/api/routes/data_sources_api.py:1761-1841`

**Why:** FastAPI `BackgroundTasks` has no retry or graceful-drain guarantee. If uvicorn is restarted within ~30 seconds of a bulk approve completing, in-flight `_generate_schema_records_background` workers may be killed mid-run. The approve `UPDATE` is already committed so user state is safe, but affected `ds_schema_record_warnings` entries and embeddings will be silently absent. An admin viewing the warning panel later may see incomplete data with no indication of why.

**Suggested approach:** DOC-only fix. Add an operational note to the runbook (e.g. `docs/ops/runbook.md` or the inline docstring at `data_sources_api.py:1799`): "If uvicorn is restarted within 30 s of a bulk approve, some schema_record embeddings may be missing. Symptom: admin warning panel shows fewer entries than expected. Remediation: re-trigger embedding via the manual re-index endpoint (to be added in a future sprint)."

**Tests:** No code tests needed.

**Dependencies:** none
