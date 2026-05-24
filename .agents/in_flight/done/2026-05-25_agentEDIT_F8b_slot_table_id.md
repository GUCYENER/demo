# agentEDIT_F8b_slot_table_id
**Date:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md` — deliverable F8 follow-up (code-review fix)
**Council:** ATHENA + APOLLO + POSEIDON
**Branch:** hira
**Status:** in_flight (awaiting council verification before move to done/)
**Predecessor:** `2026-05-25_agentEDIT_F8_suggestion_slots_note.md` (kept in in_flight; this brief patches F8 regressions)

## Why
F8 code review caught two MAJOR bugs that silently break the F7 multi-table
feature in the LLM suggestion-slot path:

1. **`_applySuggestionSlot` drops `table_id`** — manual `_addReportColumn`
   (line ~800-806) writes `table_id`, but the slot-apply path's `cols.map(...)`
   omitted it. Result: when a slot was applied, downstream SQL generation
   could no longer qualify columns by their owning table.

2. **`_suggestColumnOrder` loses `table_id` end-to-end** — payload to
   `/columns/suggest-order` had no `table_id`, the LLM response was a
   name-only list, and the frontend's `byName[c.name] = c` lookup
   **overwrote** same-named columns from different tables (e.g. `id` in two
   tables). The slot ended up referencing the wrong table's column.

## Scope (3 files modified, 0 new files except this brief)

### Frontend — `frontend/assets/js/modules/db_smart_wizard.js`
- **`_suggestColumnOrder` payload**: `available_columns` items now include
  `table_id` (line ~928).
- **Response handling**:
  - Prefer `ordered_pairs` (F8b) over legacy `ordered` (line ~942-951).
  - Catalog indexed by both `table_id::name` (`byKey`) and `name` (`byName`,
    first-wins legacy fallback).
  - For each response item, accept string or `{name, table_id}`. If
    `table_id` present → exact pair lookup; else → first-match warning.
  - Dedupe by `(table_id, name)` so same column doesn't appear twice.
  - `newReport` items now carry `table_id`.
- **`_applySuggestionSlot`**: `cols.map(...)` mapping now includes
  `table_id: c.table_id` (with `null` fallback + console.warn for legacy
  slots).

### Backend route — `app/api/routes/db_smart_api.py`
- `ColumnInfo`: added `table_id: Optional[int] = Field(default=None, ge=1)`.
- New model `OrderedColumn { name, table_id? }`.
- `SuggestOrderResp`: added additive field `ordered_pairs: List[OrderedColumn]`
  alongside legacy `ordered: List[str]`.
- Route synthesizes `ordered_pairs` from `result['ordered_pairs']`, or
  fills `table_id=None` from `result['ordered']` if service didn't supply
  pairs (defensive).

### Backend service — `app/services/db_smart/llm_column_order.py`
- New helper `_heuristic_order_pairs()` returning `[{name, table_id}]`.
- `_build_prompt`: if any input column carries `table_id`, prompt lists
  `(name, table, table_id)` per line and demands JSON output as
  `[{name, table_id}, ...]`. Backward compatible: if no `table_id`s,
  legacy string format requested.
- `suggest_order`:
  - Input normalization dedupes by `(name, table_id)` pair (was: name-only
    overwrite). table_id preserved on each `cols_clean` item.
  - Validation uses `valid_pairs` (was: `valid_names`); LLM items accepted
    as either string (legacy fallback, first-unused match by name) or
    `{name, table_id}` (preferred).
  - When LLM returned no `table_id` but input had multi-table duplicates,
    logs a WARNING and uses first-not-yet-consumed match (heuristic
    degrade).
  - Missing-pairs tail filled with `_heuristic_order_pairs`.
  - All fallback returns (LLM error / parse fail / pair-mismatch) include
    both `ordered` (name list) and `ordered_pairs`.
  - Final return includes `ordered_pairs`; legacy `ordered` derived from it.

## Backwards compatibility strategy
- **Old frontend ↔ new backend**: old client sends no `table_id`. Backend
  treats input as legacy (single-table) → `valid_pairs` becomes
  `{(name, None), ...}`. Service still works; response includes
  `ordered_pairs` (with `table_id=None`) plus the original `ordered`
  array — old client just reads `ordered`.
- **New frontend ↔ old backend**: new client sends `table_id` (backend
  pydantic schema ignores unknown? — but `ColumnInfo` extra fields default
  Pydantic v2 = ignore). Old backend returns only `ordered`. New client
  detects missing `ordered_pairs` and falls back to legacy code path with
  console.warn.
- **Slot persisted before F8b** (already-rendered slot in browser session):
  `_applySuggestionSlot` checks `c.table_id == null` and emits
  `console.warn`; mapping is still done so the rest of the wizard continues
  to function (`_addReportColumn` already tolerates `table_id == null`
  via first-catalog-match fallback).

## Verification

### Build status
```
cd frontend && npm run build
> bundle.min.js 1.1mb, bundle.min.css 437.8kb — Done in ~1.4s, exit 0
```

### Import test
```
python -c "from app.services.db_smart.llm_column_order import suggest_order, _heuristic_order_pairs; print('OK')"
→ OK import suggest_order / OK import _heuristic_order_pairs
```

### Pydantic model construct
```
ColumnInfo(name='id', table_id=42).model_dump() →
  {'name': 'id', 'semantic_type': None, 'table': None, 'table_id': 42}
OrderedColumn(name='id', table_id=42) → {'name': 'id', 'table_id': 42}
SuggestOrderResp(...).model_dump() → ordered_pairs included
```

### Functional sanity (heuristic pairs preserve duplicates)
```
Input: id@10, id@20, ad@10, tutar@20
_heuristic_order_pairs →
  {'name':'id','table_id':10}, {'name':'id','table_id':20},
  {'name':'ad','table_id':10}, {'name':'tutar','table_id':20}
```
Both `id` rows preserved — no overwrite.

### Grep verification
```
frontend/assets/js/modules/db_smart_wizard.js:
  928: table_id: c.table_id  (payload)
  961: byKey[c.table_id + '::' + c.name]  (stable lookup)
  1000: table_id: c.table_id (newReport entry)
  1100: table_id: (c.table_id != null) ? c.table_id : null  (_applySuggestionSlot)

app/services/db_smart/llm_column_order.py:
  191: out.append({"name": nm, "table_id": c.get("table_id")})  (heuristic_pairs)
  254-280: prompt includes table_id + demands {name, table_id} output
  + suggest_order: valid_pairs validation, legacy_first_match warning
```

## LLM prompt update snippet (when table_id present)
```
Mevcut kolonlar:
- id  (tip: id, tablo: musteriler, table_id: 10)
- id  (tip: id, tablo: siparisler, table_id: 20)
- ad  (tip: name, tablo: musteriler, table_id: 10)
- tutar  (tip: amount, tablo: siparisler, table_id: 20)

Çıktı SADECE JSON: {"ordered": [{"name": "col_name", "table_id": 123}, ...],
"rationale": "kısa Türkçe açıklama"}
ÖNEMLİ: Aynı isimli kolonlar farklı tablolarda olabilir (örn. iki tabloda
`id`). Her item'da hem `name` hem `table_id` alanlarını dahil et;
`table_id` yukarıda her kolon için verildi.
```

## Known risks
1. **LLM ignores new contract and returns legacy `["id", "id", "ad", ...]`**
   → backend's string-item branch picks first-unused pair per name. If
   LLM emits the two `id`s in a non-deterministic order, the wrong one
   may land first. Mitigated by:
   - WARNING log (`legacy_first_match_used`)
   - Tail-fill via `_heuristic_order_pairs` ensures both pairs end up
     present in `ordered_pairs`
   - Final multiset check still passes (set equality with `valid_pairs`)
2. **Some LLM providers strip integer `table_id` to string** — backend
   `int(item['table_id'])` cast handles `"10"` → `10` gracefully via the
   try/except wrapper.
3. **Pydantic schema accepts `table_id=None`** (Optional) — heuristic
   fallback path produces `null` table_ids when input had none, so
   `ordered_pairs` is still consistent.
4. **Existing browser sessions** with pre-F8b slots in `_state.suggestions`
   have no `table_id`. `_applySuggestionSlot` logs a console.warn and
   continues; downstream `_addReportColumn` first-catalog-match keeps SQL
   working but may pick wrong table when names collide. **Hard-reload
   resolves.**

## Restart instructions
- **Backend (Python changed)**: uvicorn restart REQUIRED.
  `python -m uvicorn app.main:app --reload` (or whichever the dev launches)
  must be bounced to pick up the new `ColumnInfo.table_id`, `OrderedColumn`,
  service prompt + validation changes.
- **Frontend (JS changed, bundle rebuilt)**: hard-reload **Ctrl+Shift+R**
  in the browser. Bundle `dist/bundle.min.js` was regenerated.

## Acceptance checklist (council verification required before moving to done/)
- [ ] Council ATHENA reviews state contract: slot.columns[i].table_id
      persisted through suggest → apply → reportColumns → buildWizardState.
- [ ] Council APOLLO reviews LLM prompt JSON schema and validation path.
- [ ] Council POSEIDON reviews multi-table integration tests (manual + any
      added in F9 follow-up brief).
- [ ] Manual smoke: 2 tables both with `id` column → LLM suggest → apply →
      preview SQL shows both `t.id` and join-alias-qualified `id`.
