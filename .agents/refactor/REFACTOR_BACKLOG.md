# VYRA Refactor Backlog

Last updated: 2026-05-23 by refactor-tracker

| ID   | Priority | Scope       | Risk | Effort | Title                                              | File(s)                                         | Status | Notes                                          |
|------|----------|-------------|------|--------|----------------------------------------------------|-------------------------------------------------|--------|------------------------------------------------|
| R001 | P2       | single-file | low  | S      | Extract `_authFetch` helper — auth header DRY      | frontend/assets/js/modules/ds_enrichment_module.js | open   | 13 `localStorage.getItem` call sites; 5+ full fetch boilerplate copies |
| R002 | P2       | single-file | low  | XS     | Extract `_guardNoRunningJob` — preflight DRY       | frontend/assets/js/modules/ds_enrichment_module.js | open   | May become obsolete after v3.31.0 bulk endpoint; see .agents/plans/bulk_enrichment_endpoints.md |
| R003 | P2       | single-file | low  | S      | Move pill inline-styles to CSS class `.ds-status-pill` | frontend/assets/js/modules/ds_enrichment_module.js | open   | A11y bonus: `role="group"` already present (line 566); HEBE noted |
| R004 | P3       | single-file | low  | XS     | `_runConcurrent` worker return-type inconsistency  | frontend/assets/js/modules/ds_enrichment_module.js | open   | TYCHE micro-note — `bulkApprove` worker returns object, `bulkApproveAll` worker returns undefined |

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
