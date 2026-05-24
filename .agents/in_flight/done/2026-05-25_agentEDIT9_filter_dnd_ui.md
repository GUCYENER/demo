# agentEDIT9 — Filtre Step DnD UI + LLM Öner

**Date:** 2026-05-25
**Branch:** `hira`
**Council:** HEBE + HERMES + ATHENA
**Plan ref:** `.agents/plans/2026-05-25_0030_metric_filter_dnd_llm_v1.md` deliverable **B9**

---

## Problem

"Akıllı Veri Keşfi" wizard step 3 (Filtre, `data-step=3`, panel `#dswStep3`) is
currently a placeholder — `_loadFilters` (`_loadColumns` in source) prints only
a column catalogue with the hint "FAZ 1 P3'te tam UI". The user has no way to
choose which columns appear in the final report, or in what order. The
generated SQL in the Önizleme step (`_loadPreview`) therefore always uses
`SELECT *`.

## Goals

1. Two-panel layout inside `#dswStep3`:
   - **Left** — existing column catalogue, each row gains a `+ Ekle` button
     that pushes the column into the right panel (no duplicates).
   - **Right** — drag-drop ordered list (`#dswReportColumns`) of "report
     columns" the user wants to see, with `×` chips to remove, an empty-state
     placeholder, and a `✨ LLM ile öner` button.
2. New wizard state field `_state.reportColumns = []` (ordered array of
   `{ column_name, semantic_type, table_name, label }`).
3. `_loadPreview` honours `_state.reportColumns` — if non-empty, the wizard
   state passes `selected_columns` in that order instead of `*`.
4. `✨ LLM ile öner` calls `POST /api/db-smart/columns/suggest-order` with
   `{ source_id, primary_table_id, join_table_ids, available_columns }` and
   re-renders the DnD list with `response.ordered`; shows `rationale` via
   toast. Endpoint may not yet exist — wrap fetch in try/catch and surface a
   friendly error toast on failure.
5. Keyboard accessibility on DnD items: `ArrowUp`/`ArrowDown` swap with
   neighbour, `Delete` removes.

## Files

| File | Change |
|---|---|
| `frontend/assets/js/modules/db_smart_wizard.js` | `_state.reportColumns` init; rewrite `_loadColumns` (the step-3 handler — currently named `_loadColumns`, brief calls it `_loadFilters`); add helpers `_renderReportColumns`, `_addReportColumn`, `_removeReportColumn`, `_moveReportColumn`, `_attachDnd`, `_suggestColumnOrder`; teach `_buildWizardState` to use `_state.reportColumns` when non-empty. |
| `frontend/assets/css/modules/_db_smart_wizard.css` | Append `.dsw-filter-grid`, `.dsw-filter-catalog`, `.dsw-filter-report`, `.dsw-dnd-list`, `.dsw-dnd-item`, `.dsw-dnd-item.dragging`, `.dsw-dnd-item:focus-visible`, `.dsw-dnd-empty`, `.dsw-suggest-btn`, `.dsw-col-add-btn`. |
| `frontend/dist/bundle.min.{js,css}` | Re-build via `npm run build`. |

## Plan

1. Write brief (this file).
2. Edit `db_smart_wizard.js`:
   - Add `reportColumns: []` to `_state` initialization.
   - Rewrite `_loadColumns` for two-panel HTML.
   - Add `_renderReportColumns`, `_addReportColumn`, `_removeReportColumn`,
     `_moveReportColumn`, `_attachReportColumnsDnd`, `_suggestColumnOrder`.
   - Patch `_buildWizardState` so `selected_columns` honour
     `_state.reportColumns` ordering (fallback to `[{ expr: '*' }]`).
3. Append CSS rules.
4. `cd frontend && npm run build`, then grep bundle for `dswReportColumns`.
5. **Do NOT** move brief to `done/` (council approval rule from memory).

## Risks

- Endpoint `/columns/suggest-order` may not be live yet (B10). Wrapped in
  try/catch — user sees friendly toast; UI stays functional.
- `_buildWizardState` patch must not break the existing AST editor mount path;
  fallback path (`reportColumns.length === 0`) keeps `[{ expr: '*' }]`.
- Backend SQL assembler must accept the new `selected_columns` payload shape;
  current code already maps `selected_columns: [{ expr: ... }]` so we keep
  that contract (each entry: `{ expr: column_name, alias?: label }`).

## Restart / reload

- Frontend-only change. After `npm run build`, browser **hard reload**
  (Ctrl+Shift+R) needed.
- No backend restart from this brief alone.
