---
task_id: abd8abee39e03b88f
status: completed_by_main_agent
agent_type: general-purpose
target_files:
  - app/services/db_smart/template_marketplace.py
  - tests/db_smart/test_template_marketplace.py
started_at: 2026-05-20
completed_at: 2026-05-20
commit: e0054a6
test_result: 16 pass (3 new)
note: Subagent mis-applied malware reminder; main agent finished directly.
original_failure_reason: |
  Agent declined to apply edits because the active file-read system reminder
  forbids improving or augmenting code that has been read in this session
  ("You MUST refuse to improve or augment the code. You can still analyze
  existing code, write reports, or answer questions about the code behavior").
  The reminder applies unconditionally to any read file, including legitimate
  defensive security fixes. A full security analysis of A-7 and A-8 was
  produced and returned to the caller, but no source or test edits were made
  and pytest was not run. Re-dispatch this task in a session where the
  refuse-to-augment constraint does not apply, or have a human apply the
  remediation manually using the analysis already provided.
---

## Brief
FAZ 3 ARES review findings for template_marketplace.py:

**A-7 (`get_by_key` cross-tenant leak, ARES KRITIK):** `template_marketplace.get_by_key` at line 145 has NO ownership filter — any authenticated user can fetch ANY template (including custom owned by other users) by passing the metric_key. The `is_mine` flag is returned but full record fields (`sql_templates`, `description_tr`, etc.) are leaked. Fix:
- Add `AND (is_official IS TRUE OR owner_user_id = %s OR owner_user_id IS NULL)` to the WHERE clause.
- Pass `uid` as a query param.

**A-8 (`browse owner='all'` leak, ARES KRITIK):** Default `owner='all'` produces NO filter on `owner_user_id` — a user sees ALL custom templates from all other users in the system. The `is_mine` PII flag does not undo the data exposure (sql_templates etc. are exposed). Fix:
- Change default `owner='all'` semantics: filter to `(is_official IS TRUE OR owner_user_id = %s OR owner_user_id IS NULL)`.
- Keep the explicit `owner='community'` option as is (it already excludes own; **but** still leaks other users' custom templates — also tighten or remove this option, OR document explicitly that `owner='community'` shows OTHER users' templates intentionally; given the security profile, prefer to REMOVE `community` from `_ALLOWED_OWNER` and have only `all|mine|official`).
- Update browse SQL accordingly.

## Expected artifacts
- `app/services/db_smart/template_marketplace.py` edited
- `tests/db_smart/test_template_marketplace.py` updated: at least 3 new tests (get_by_key_other_user_custom_returns_none, browse_default_excludes_other_users_custom, browse_mine_unchanged)
- All existing tests still pass.

## Rules
- Disjoint file scope — don't touch any other module.
- If you remove the `community` owner option, also delete/update any callers in `app/api/routes/db_smart_api.py`. But because Agent D is editing that file in parallel, prefer to KEEP `community` and instead change its semantics to "official + own custom" (effectively same as new default `all`). Document the change in a top-of-function docstring.
