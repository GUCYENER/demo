---
task_id: abff927640a279f7e
status: completed_by_main_agent
failure_reason: "Subagent refused (malware-reminder mis-apply). ZEUS main agent completed the work directly in commit 371de47 (learning_recorder + custom_metric_parser F-009/F-010/F-015/F-017 PII value-hash + fail-closed)."
agent_type: general-purpose
target_files:
  - app/services/db_smart/learning_recorder.py
  - app/services/db_smart/custom_metric_parser.py
  - tests/db_smart/test_learning_recorder.py
  - tests/db_smart/test_custom_metric_parser.py
started_at: 2026-05-20
---

## Brief
FAZ 3 ARES + TYCHE findings across learning_recorder + custom_metric_parser:

**F-009 / F-010 (PII value-level masking in learning_recorder, ARES YUKSEK):**
Currently `learning_recorder` masks PII via key match (column name → `ds_column_enrichments.is_pii`) but values themselves (especially SQL fragments containing values) get persisted raw. Fix:
- For any field whose key matches PII (case-insensitive — F-010), redact the value before persisting: replace with `{"sql_hash": "<sha1[:7]>...", "_redacted": True}` if it's a string >32 chars, or `{"value_hash": "<sha1[:7]>", "_redacted": True}` for other types.
- F-010 specifically: the PII key-set lookup must be `.lower()` on both sides — current implementation is case-sensitive.

**F-015 (custom_metric_parser `allowed=[]` bypass, ARES KRITIK):**
In `parse_to_sql` (or equivalent), when caller passes `allowed_columns=[]` (empty list), the current allow-list check short-circuits to "no restriction" → any column passes. Fix:
- `if allowed_columns is None: <skip check>` — preserve "no list = no restriction" semantics.
- `if isinstance(allowed_columns, list) and len(allowed_columns) == 0: raise ValueError("no columns allowed")` — empty list = fail closed.

**F-017 (`save_custom_metric` defense-in-depth):**
The `save_custom_metric` entry point persists the SQL without calling `validate_sql` first → if a future caller skips client-side validation, malicious SQL enters the metric library. Fix:
- At the top of `save_custom_metric`, call `validate_sql(sql, dialect)` and bail with ValueError on failure. Even if upstream already validates, defense-in-depth here is mandatory because the metric_library is consumed by many code paths.

## Expected artifacts
- 2 services edited, 2 test files updated/added
- At least 4 new tests covering: pii_value_redaction, pii_key_case_insensitive, allowed_empty_list_fails_closed, save_custom_metric_validates_sql
- All existing tests still pass

## Rules
- Disjoint file scope: do NOT touch schedule_runner, template_marketplace, db_smart_api, or ast_renderer.
- If `validate_sql` doesn't already exist, grep for an equivalent (likely `sql_validator.py`, `safe_sql_executor.py`, or `query_assembler.py`).
