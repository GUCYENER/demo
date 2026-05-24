# agentEDIT_F8_suggestion_slots_note
**Date:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md` — deliverable F8
**Council:** APOLLO + HEBE + ATHENA
**Branch:** hira

## Scope
Two pieces in `frontend/assets/js/modules/db_smart_wizard.js` + CSS:

### Piece A — LLM suggestion slots (max 3, LRU)
- Each `✨ LLM ile öner` click stores result as a new SLOT (FIFO, max 3).
- Slots rendered above filter grid as cards (`Öneri 1/2/3`) with column preview, rationale, and `+ Bu öneriyi uygula` button.
- Apply REPLACES `_state.reportColumns` (no append). Active slot visually highlighted.
- MVP backend approach: existing `/columns/suggest-order` is called once per click — no new endpoint added in this brief (plan F8 marks `/suggest-orders?count=3` as optional). Each click yields a new slot regardless of whether the LLM's order is identical.

### Piece B — Free-text yorum textarea
- Appended at the bottom of step 3 filter grid.
- `_state.userNote = ""` (string), updated on input.
- Will be consumed by F9 (`generate-report` endpoint).

## State contract additions
```
_state.suggestions = []  // [{ id: "s1"|"s2"|"s3"|..., columns: [...same shape as reportColumns...], rationale: string, appliedAt: ts|null }]
_state.userNote   = ""   // string
```

## Render entry points
- `_renderStep3(panel, totalCount)` — inserts `<div class="dsw-suggest-slots">` above `.dsw-filter-grid`, and `<div class="dsw-user-note">` after the grid.
- New helpers: `_renderSuggestionSlots()`, `_applySuggestionSlot(id)`.
- `_suggestColumnOrder` modified: instead of replacing `_state.reportColumns`, it now pushes a slot, evicts oldest beyond 3, re-renders slot cards.

## CSS classes added (`_db_smart_wizard.css`, appended at end)
- `.dsw-suggest-slots` — flex row, gap 8px, margin-bottom 12px, flex-wrap.
- `.dsw-suggest-card` — border, padding, max-width 240px, column preview truncated.
- `.dsw-suggest-card.active` — accent border tint.
- `.dsw-suggest-card-head`, `.dsw-suggest-card-cols`, `.dsw-suggest-card-rationale`
- `.dsw-suggest-apply-btn` — full-width primary-ghost button.
- `.dsw-user-note` — margin-top 16px, label + textarea stacked.

## Build
`cd frontend && npm run build` → bundle rebuild.

## Restart / reload
- **Frontend hard-reload:** required (CSS + JS bundle changed).
- **Backend restart:** NOT required (no python touched in this brief).

## Decisions
- Stuck with existing `/columns/suggest-order` (single suggestion per call) per plan MVP note; deferred `/suggest-orders?count=3` to a future iteration.
- Slot IDs are rolling (`s1`, `s2`, `s3`, then re-uses lowest free or just `s<counter>`) — simple incrementing counter, used purely as DOM key.

## Done criteria (this brief)
- [x] State fields added.
- [x] `_suggestColumnOrder` produces a new slot (LRU 3) instead of direct replace.
- [x] Slot cards render + apply replaces `_state.reportColumns`.
- [x] Active slot highlight.
- [x] Free-text textarea + binding.
- [x] CSS classes added.
- [x] esbuild bundle rebuilt successfully.

Brief remains in `in_flight/` (NOT moved to done/) — council approval gate per MEMORY rule.
