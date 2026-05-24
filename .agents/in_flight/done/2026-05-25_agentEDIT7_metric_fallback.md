# Brief — agentEDIT7_metric_fallback

**Date:** 2026-05-25
**Branch:** `hira`
**Plan:** `.agents/plans/2026-05-25_0030_metric_filter_dnd_llm_v1.md` deliverable B7
**Council:** POSEIDON + ARES

---

## Problem

Wizard "Metrik" step shows: `Metrik kütüphanesi boş (migration 033 uygulanmamış olabilir)`
even though `dbsmart_metric_library` has 30 seeded metrics.

Root cause: `app/services/db_smart/metric_engine.py:list_eligible` uses `min_score=0.6`
threshold. For ODEMELER (payments) and similar tables where `ds_column_enrichments` is
empty, the default semantic_type inference yields generic `amount/other`, which causes
`_check_applicable` to mostly fail or yield strength below threshold:
`0.5 * strength + 0.3 * usage_norm(0) + 0.2 * user_pref(0)` = at most 0.5 with zero usage.
So eligible count = 0 for fresh tables → frontend renders empty-state message.

## Plan

1. Add `list_all_active(cur, limit=60)` helper in `metric_engine.py` that returns the
   full active library entries with shape matching `list_eligible`'s items
   (no scoring/bindings, `fallback=True` flag on each item).
2. Modify `app/api/routes/db_smart_api.py:list_metrics`:
   - When `table_id` is provided and `list_eligible(...)` returns 0 items, call
     `list_all_active(cur)` to fall back to full library.
   - Always set top-level `"fallback": bool` in response.
3. Use existing `_col(row, key, idx)` helper — no integer-indexing on RealDictCursor.

## Files Touched

- `app/services/db_smart/metric_engine.py` — new `list_all_active()` helper (~30 lines).
- `app/api/routes/db_smart_api.py:list_metrics` (lines ~1508–1576) — fallback path + flag.

## Acceptance

1. Verification script (see below): `eligible @ 0.6` may be 0; `eligible @ 0.0` >= 5.
2. Endpoint `/api/db-smart/metrics?source_id=3&table_id=<ODEMELER>`:
   - When eligible=0, response has `"fallback": true` and `items.length > 0`.
   - When eligible>0, response has `"fallback": false`.
3. Shape of fallback items matches existing fields:
   `metric_key, name_tr, category, description_tr, default_viz, applicable_when, sql_templates`.

## RESTART REQUIRED

- **uvicorn restart** required to pick up changes to `metric_engine.py` and
  `db_smart_api.py`.
- No frontend changes in this brief → no `npm run build` needed.

## Council Approval Pending

Per memory rule `feedback_brief_done_council_approval`, this brief stays in
`.agents/in_flight/` until council verifies the code + behavior and approves move to
`done/`.

## Verification Output

(see report)
