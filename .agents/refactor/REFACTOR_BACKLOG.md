# VYRA Refactor Backlog

Last updated: 2026-05-24 (Target + Created kolonları eklendi — BAŞLA gate v1)

> **BAŞLA Gate Tetikleyici (vyrazeus.md §3.7):** `Status: open` AND
> (`Priority: P1` AND `Target <= current_version`) OR (`Risk: critical`)
> OR (`Priority: P1` AND `Created` 14+ gün önce) → oturum başında karar şart.

| ID   | Priority | Scope       | Risk | Effort | Target  | Created    | Title                                              | File(s)                                         | Status     | Notes                                          |
|------|----------|-------------|------|--------|---------|------------|----------------------------------------------------|-------------------------------------------------|------------|------------------------------------------------|
| R001 | P2       | single-file | low  | S      | v3.31.0 | 2026-04-15 | Extract `_authFetch` helper — auth header DRY      | frontend/assets/js/modules/ds_enrichment_module.js | done       | Commit e14f0ca — 13 call site DRY |
| R002 | P2       | single-file | low  | XS     | v3.31.0 | 2026-04-15 | Extract `_guardNoRunningJob` — preflight DRY       | frontend/assets/js/modules/ds_enrichment_module.js | done       | v3.31.0 bulk endpoint preflight'i absorbe etti; 3 frontend preflight kaldirildi (extraction yerine eliminate). Commit: bu sprint |
| R003 | P2       | single-file | low  | S      | v3.31.0 | 2026-04-15 | Move pill inline-styles to CSS class `.ds-status-pill` | frontend/assets/js/modules/ds_enrichment_module.js | done       | Commit b5afc17 — CSS class + a11y bonus |
| R004 | P3       | single-file | low  | XS     | —       | 2026-04-15 | `_runConcurrent` worker return-type inconsistency  | frontend/assets/js/modules/ds_enrichment_module.js | wontfix    | bulkApprove + bulkApproveAll v3.31.0'da bulk endpoint'e gecti -> _runConcurrent callsite kalmadi. Helper utility olarak korundu (plan kararı), inconsistency moot |
| R005 | P1       | single-file | medium | S    | v3.33.0 | 2026-05-10 | RLS USING clause order drift from mig 017 canonical pattern | migrations/versions/043_v3320_bulk_phase2.py | open | H1 — HEPHAESTUS audit; v3.33.0 RLS-strict sprint hedefi |
| R006 | P1       | cross-file  | medium | M    | v3.33.0 | 2026-05-10 | Missing explicit `WITH CHECK` clause on `FOR ALL` policy (mig 043) | migrations/versions/043_v3320_bulk_phase2.py, app/core/db.py | open | H2 — HEPHAESTUS audit; `apply_company_scope` silent-fail risk; v3.33.0 RLS-strict sprint hedefi |
| R007 | P2       | single-file | low  | S      | v3.34.0 | 2026-05-10 | No index on `ds_schema_record_warnings.enrichment_id` FK-equivalent | migrations/versions/043_v3320_bulk_phase2.py | open | M1 — HEPHAESTUS audit; seq-scan on per-enrichment admin filter; add with admin warning panel endpoint |
| R008 | P3       | cross-file  | low  | XS     | v3.34.0 | 2026-05-10 | Index naming inconsistency: `idx_ds_table_enrich_*` vs convention `idx_table_enrich_*` | migrations/versions/043_v3320_bulk_phase2.py, migrations/versions/004_ds_enrichment_tables.py | open | M2 — HEPHAESTUS audit; ALTER INDEX non-breaking rename |
| R009 | P3       | cross-file  | low  | XS     | v3.34.0 | 2026-05-10 | `detail TEXT` uncapped at DB layer — only app-layer cap enforced | migrations/versions/043_v3320_bulk_phase2.py, app/api/routes/data_sources_api.py | open | L1 — HEPHAESTUS audit; VARCHAR(1000) or CHECK constraint |
| R010 | P3       | single-file | low  | XS     | v3.34.0 | 2026-05-10 | BackgroundTasks SIGTERM loss — operational runbook note missing | app/api/routes/data_sources_api.py | open | L2 — HEPHAESTUS audit; approve UPDATE already committed, only embedding gap; DOC-only fix |
| R011 | P1       | cross-file  | medium | M    | v3.33.0 | 2026-05-20 | Tooltip clipping in table cells — portal or fixed-position variant needed | frontend/assets/css/modules/ui_tooltip.css, frontend/assets/css/modules/ds_enrichment.css, frontend/assets/js/modules/ds_enrichment_module.js | open | Y1 — ATHENA audit; `::after` clipped by ancestor overflow:hidden; JS portal helper needed; v3.33.0 |
| R012 | P2       | single-file | low  | S      | v3.33.0 | 2026-05-20 | Tooltip vertical auto-flip missing — hard-pinned `bottom` clips near viewport top | frontend/assets/css/modules/ui_tooltip.css | open | O2 — ATHENA audit; `bottom: calc(100% + 6px)` only; can share R011 JS helper; v3.33.0 |
| R013 | P3       | cross-file  | low  | XS     | v3.34.0 | 2026-05-20 | `[disabled]` checkbox missing `cursor: not-allowed` — UX consistency gap | frontend/assets/css/modules/ui_tooltip.css, frontend/assets/js/modules/ds_enrichment_module.js | open | O3 — ATHENA audit; bulk buttons OK (inline cursor), `.ds-bulk-chk[disabled]` uncovered; global CSS fix |
| R014 | P3       | single-file | low  | M      | v3.34.0 | 2026-05-20 | `_runningJobPoll` unconditional re-render — state-unchanged renders on every 3s tick | frontend/assets/js/modules/ds_enrichment_module.js | open | D3 — ATHENA audit; `applyFilterAndRender()` line 244 called regardless of state change; state-hash guard needed |
| R015 | P3       | single-file | low  | XS     | v3.34.0 | 2026-05-20 | Dark surface token drift — tooltip bg hard-coded, not using `--tt-bg` CSS variable | frontend/assets/css/modules/ui_tooltip.css | open | D3 — ATHENA audit; `rgba(17,24,39,0.96)` at line 19 should be `var(--tt-bg)`; align with `--bg-card` token pattern |

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

---

## v3.33.0 UX sprint — ATHENA UX audit findings (Council Gate v3.32.0)

### R011 — Tooltip clipping in table cells — JS portal variant needed

**Files:**
- `frontend/assets/css/modules/ui_tooltip.css:13` (`[data-tt] { position: relative }`)
- `frontend/assets/css/modules/ds_enrichment.css:131-135` (`.ds-enrich-table-wrap { overflow-x: auto }`)
- `frontend/assets/css/modules/ds_enrichment.css:151-156` (`.ds-table-name-cell { overflow: hidden; max-width: 0 }`)
- `frontend/assets/css/modules/ds_enrichment.css:284-291` (`.ds-desc-cell { overflow: hidden; max-width: 0 }`)

**Why now:** `[data-tt]` renders its tooltip via `::after` with `position: absolute`. The tooltip is therefore contained within the nearest `position: relative` ancestor. Both `.ds-table-name-cell` and `.ds-desc-cell` have `overflow: hidden` (for text ellipsis) and their ancestor `.ds-enrich-table-wrap` has `overflow-x: auto`. The `::after` content is clipped exactly where tooltips provide the most value — hovering truncated table names and descriptions shows nothing or a partial strip. This is a net regression vs. the `title=""` baseline that was replaced by the v3.32.0 tooltip utility.

**ATHENA verdict context:** K1 and Y2 were hotfixed in this sprint. R011 (Y1) is deferred to v3.33.0 because it requires a JS helper; it is not a net regression (table cells had no tooltip before v3.32.0 — `data-tt` was just not applied there).

**Suggested approach (preferred: option #1 — JS portal):**
Add a small `ui_tooltip.js` helper. On `mouseenter` of any `[data-tt-portal]` element, create a `<div class="tt-portal">` appended to `<body>`, position it via `getBoundingClientRect()` + `window.scrollY`, populate with `dataset.tt` text. Remove on `mouseleave`. Existing `[data-tt]` (CSS-only) utility is preserved unchanged for all non-clipped contexts.

Alternative option #2: `[data-tt-fixed]` variant — JS hover handler writes `--tt-x` / `--tt-y` CSS variables on the element; `::after` uses `position: fixed; left: var(--tt-x); top: var(--tt-y)`. Simpler but requires reflow on scroll.

Option #3 (`title=` fallback) is rejected — breaks dark-theme consistency, is a UX regression.

**Tests:** Manual visual test on long table names (`>22%` column width). Unit test for portal helper: mock `getBoundingClientRect`, assert portal `<div>` appended to body on hover and removed on leave.

**Dependencies:** none — new `ui_tooltip.js` file; does not touch existing `ui_tooltip.css`.

---

### R012 — Tooltip vertical auto-flip missing

**Files:** `frontend/assets/css/modules/ui_tooltip.css:14` (`bottom: calc(100% + 6px)`)

**Why:** The tooltip is always rendered above the trigger element. Elements near the top of the viewport (`.ds-enrich-filter-bar` buttons) or immediately below the sticky `<thead>` will render the tooltip partially or fully outside the visible area. The CSS `anchor-position` API (Chrome 125+) is not yet cross-browser viable.

**Suggested approach:** Implement flip logic inside the R011 JS portal helper. When placing a portal tooltip, check if the computed `top` coordinate would be < 8px (viewport bleed); if so, render below the trigger instead. This collapses R011 and R012 into a single JS helper with two responsibilities.

Alternatively, if R011 is deferred past v3.33.0, a standalone IntersectionObserver-based flip on the CSS `::after` approach can be explored, but is significantly more complex for marginal gain.

**Tests:** Unit test: mock trigger with `top: 5px` in viewport, assert portal renders below rather than above.

**Dependencies:** R011 (strongly recommended to land together — same helper file).

---

### R013 — `[disabled]` checkbox missing `cursor: not-allowed`

**Files:**
- `frontend/assets/js/modules/ds_enrichment_module.js:577` (`<input type="checkbox" class="ds-bulk-chk ...">` — no cursor style on disabled state)
- `frontend/assets/js/modules/ds_enrichment_module.js:739,745,751,757` (4 bulk action buttons — inline `cursor: not-allowed` when disabled, correct)

**Why:** The 4 bulk action buttons apply inline `cursor: ${gate ? 'not-allowed' : 'pointer'}` correctly. However, approved-row checkboxes rendered with the `disabled` attribute (line 577) receive no cursor override. Browsers default to `default` cursor on `[disabled]` inputs, not `not-allowed`. The inconsistency is cosmetic but contradicts the existing convention in the same component.

**Suggested approach:** Add to a global or component CSS sheet:
```css
*[disabled],
*[disabled]:hover {
    cursor: not-allowed !important;
}
```
Or more scoped: `.ds-bulk-chk[disabled] { cursor: not-allowed; }`.

**Tests:** No automated tests needed. Visual check in dark theme.

**Dependencies:** none.

---

### R014 — `_runningJobPoll` unconditional re-render on every tick

**Files:** `frontend/assets/js/modules/ds_enrichment_module.js:201-251`

**Evidence:** `_pollRunningJob` at line 244 calls `applyFilterAndRender()` on every successful poll response where `activeElement` is not an INPUT — regardless of whether `_runningJob` state actually changed. With the default 3-second interval and 100+ rows, this rebuilds the full panel innerHTML every 3 seconds silently.

**Why now:** At ≤50 rows this is imperceptible. At 100+ rows (large source catalogues) `applyFilterAndRender` triggers full DOM reconstruction including `innerHTML` assignment on `#dsEnrichBody`, which:
1. Causes visible layout jank on slower hardware / integrated GPU.
2. Resets any inline edit focus not guarded by the `activeElement !== INPUT` check (e.g. a focused `<select>` or `<textarea>`).

**Suggested approach:** Introduce a lightweight state fingerprint:
```js
const _stateHash = () => `${_runningJob ? _runningJob.type : 'null'}|${_runningJob ? _runningJob.started_at : ''}`;
```
Store `_lastPollHash` on module scope. In `_pollRunningJob`, after updating `_runningJob`, compare `_stateHash()` to `_lastPollHash`; skip `applyFilterAndRender()` if unchanged. Update hash on state-changing transitions only.

**Tests:** Unit test: call `_pollRunningJob` twice with identical mock response; assert `applyFilterAndRender` called once (or spy call count = 1, not 2).

**Dependencies:** none — self-contained within `_pollRunningJob`.

---

### R015 — Dark surface token drift in `ui_tooltip.css`

**Files:** `frontend/assets/css/modules/ui_tooltip.css:19`

**Evidence:** Tooltip background is `rgba(17, 24, 39, 0.96)` — hard-coded literal. App canonical card surface is `--bg-card: #1f2937` (verified in `frontend/assets/css/global.css:41`). The tooltip uses `#111827` (one shade darker, intentional overlay convention), but it is not expressed as a CSS variable, so it cannot participate in theming or be found by a design-token audit grep.

**Suggested approach:**
1. Define `--tt-bg: rgba(17, 24, 39, 0.96)` in the `:root` block of `global.css` (or in `ui_tooltip.css`'s own `:root` block).
2. Replace the literal in `ui_tooltip.css:19` with `background: var(--tt-bg)`.
3. Optionally define `--tt-color: #e5e7eb` and `--tt-border: rgba(255,255,255,0.08)` for full token coverage of the `::after` rule.

**Tests:** No automated tests. Visual check that tooltip background is unchanged after the substitution.

**Dependencies:** none.
