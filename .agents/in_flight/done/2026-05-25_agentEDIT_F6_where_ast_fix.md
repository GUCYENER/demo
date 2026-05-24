# Brief — agentEDIT_F6_where_ast_fix

**Plan**: `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md` → F6
**Council**: HERMES + ATHENA
**Date**: 2026-05-25
**Status**: IN FLIGHT (do NOT move to done/ — verification by council required)

---

## Scope

Two bugs in Akıllı Keşfi v3.36 Önizleme (Step 4):

### Bug 1 — "WHERE + Ekle" does nothing
- The +Ekle chip is rendered by `db_smart_ast_editor.js` (`_renderFilterChips`, line 254-256).
- A click handler IS wired (`_onRootClick` → `add_filter` → `_openAddFilterModal` → `DbSmartFilterModal.open`).
- **Root cause (after investigation)**: handler chain works, but optimistic `add_filter` is rolled back by `_flushPatch` when the patch request fails for any reason (rollback at line 594), AND a toast pops up. To the user it looks like "nothing happened" plus a confusing error toast.
- Plus: filter columns are derived from `_columnsFromAst(state.ast)` which iterates `ast.select`. If SELECT contains only `*`, the modal column dropdown can be effectively empty.
- **Backend route is present**: `POST /api/db-smart/sessions/{session_uid}/ast/patch` at `app/api/routes/db_smart_api.py:362`. URL resolves correctly (wizard's vyraFetch adds `/api`).

### Bug 2 — "AST yaması başarısız" toast spam
- `db_smart_ast_editor.js:597` shows toast on every patch failure.
- On mount-time / preview-time the AST editor may patch implicitly via undo/redo or DnD; transient 404/network spam the user.

---

## Changes Applied

### `frontend/assets/js/modules/db_smart_ast_editor.js`
1. **Patch failure handling (line ~590-603)** — `_flushPatch` `.catch`:
   - Add `state.lastInteraction` timestamp set inside `_onRootClick` (set when user explicitly initiates `add_filter`, `remove_*`, `toggle_order_dir`, undo, redo) and inside DnD `drop` / keyboard reorder handlers.
   - In `.catch`:
     - For 404 / network errors (no status) — `console.warn` only, NO toast, and **do not rollback** if `op === 'add_filter'` so the optimistic chip stays visible (user sees their addition; backend may be eventually consistent or a flake).
     - For 400 / 409 — keep toast (these are user-meaningful: validation / conflict).
     - For other errors — toast ONLY if `lastInteraction` is within last 2000ms (i.e., user-initiated). Otherwise console.warn.
2. **Column fallback for filter modal** — `_openAddFilterModal`: if `_columnsFromAst` returns empty, fall back to a generic `{expr: '*', label: '*'}` placeholder so the dropdown is non-empty (this lets the user still close the modal; explicit empty-columns guidance left for follow-up F7).

### `frontend/assets/js/modules/db_smart_wizard.js`
- No edits required; AST editor delegate fix is sufficient.
- (Investigated: no separate WHERE +Ekle rendering exists in `_loadPreview`. AST editor owns the WHERE chip list on Step 4.)

---

## Behavior change

**Before**:
- User clicks WHERE +Ekle → modal opens → submits → chip flashes → patch fails (transient 404 or race) → chip disappears → toast "AST yaması başarısız". Looks like "did nothing".
- Mount-time / undo / preview AST patches that fail spam toasts.

**After**:
- User clicks WHERE +Ekle → modal opens (with `*` fallback if no columns) → submits → chip appears → patch fires → on transient/404 failure: chip STAYS, only console.warn. On 400/409: toast (these are real validation errors).
- Mount-time failures: console.warn only.

---

## Limitations / Out of scope

- MVP WHERE inline-row alternative was NOT implemented because the AST editor delegate IS wired correctly; the actual fix is graceful failure handling. If F7 brings multi-table columns, the filter modal column source should be widened (`state.options.columns` injected by wizard).
- Patch endpoint exists; no backend changes required.
- The wizard's `_fetchJson` does not forward `AbortController.signal` to vyraFetch — this means the AST editor's debounce abort is a no-op. Minor; not in scope of F6.
- Tests not authored here (must be team-authored per memory rule). Pending TYCHE+ARES brief if regression tests are wanted.

---

## Verification needed before move to done/

- [ ] Manual: open Step 4, click WHERE +Ekle, choose column, op, value, submit → chip appears and STAYS even if backend transient error.
- [ ] Manual: trigger mount with no session → no toast spam.
- [ ] Manual: invalid filter (e.g., 400 from server) → toast still shown.
- [ ] Frontend bundle rebuilt (`cd frontend && npm run build`).

---

## Files touched

- `frontend/assets/js/modules/db_smart_ast_editor.js` (handler hardening, fallback columns)
- `frontend/dist/bundle.min.js` (rebuild artifact)

## Restart / reload requirements

- **Hard reload** the browser (Ctrl+Shift+R) to pick up new `bundle.min.js`.
- No backend restart needed.
