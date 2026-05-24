# Brief — F15: SafeSQLExecutor `allowed_tables` case-insensitive normalize

**Date:** 2026-05-25
**Agent:** `agentEDIT_F15_allowed_tables_ci`
**Council:** ARES (SafeSQLExecutor guard) + POSEIDON (data flow / metadata case) + APOLLO (LLM prompt dialect note)
**Plan:** `.agents/plans/2026-05-25_0700_v336_smoke_bugs_v1.md` — F15

---

## Symptom

F9 "Çalıştır" → modal: *"Rapor üretilemedi. Tablo erişim yetkisi yok: vyra_test.musteriler"*.

LLM (Oracle dialect) produced:

```sql
SELECT "DESTEK_TALEPLERI"."TALEP_ID", "MUSTERILER"."AD", ...
FROM "VYRA_TEST"."DESTEK_TALEPLERI"
LEFT JOIN "VYRA_TEST"."MUSTERILER" ON ...
LEFT JOIN "VYRA_TEST"."ABONELIKLER" ON ...
FETCH FIRST 100 ROWS ONLY
```

`SafeSQLExecutor.check_table_whitelist` parser strips quotes + lowercases to
`vyra_test.musteriler`. Whitelist coming from `/generate-report` route was built
from `ds_db_objects.schema_name/object_name` without explicit case-normalization
and without guaranteed inclusion of every JOIN'd table. Either side mismatching
case (or schema prefix vs. short) caused rejection.

---

## Approach (defense in depth, both A + B)

### A. `app/services/safe_sql_executor.py`

- `execute()` and `execute_async()` now normalize the incoming `allowed_tables`
  list with `str(t).strip().lower()` before handing it to
  `check_table_whitelist`. The internal whitelist comparison already
  lowercased both sides; this hardens any direct caller that may pass a
  mixed-case list.

### B. `app/api/routes/db_smart_api.py` (`/generate-report`)

- The `allowed_tables` builder now records, for every row returned from
  `ds_db_objects`, **three variants** of both the schema-qualified and the
  short form: original, `lower()`, `upper()`. De-dup set keeps the list small.
  This makes the whitelist resilient against Oracle (UPPERCASE), PG (lower),
  and any future case-folding metadata behaviour.

### APOLLO prompt note

- `_build_prompt` in `llm_generate_report.py` user message now contains an
  F15 identifier-case rule asking the LLM to use UPPERCASE for Oracle,
  lowercase for PG/MySQL, and otherwise to mirror the metadata case verbatim.
  This is a *hint*, not a guarantee — the executor-side fix is the real safety
  net.

---

## Files changed

- `app/services/safe_sql_executor.py` — `execute()` whitelist branch
  (~ line 391) and `execute_async()` (~ line 506): `normalized_allowed = [str(t).strip().lower() for t in allowed_tables if t]` before `check_table_whitelist`.
- `app/api/routes/db_smart_api.py` — `/generate-report` allowed_tables
  loop (~ line 2292-2310): emits `{schema.obj, schema.obj.lower(),
  schema.obj.upper(), obj, obj.lower(), obj.upper()}` with `_seen` dedup.
- `app/services/db_smart/llm_generate_report.py` — `_build_prompt` user
  prompt: APOLLO F15 identifier-case note for Oracle vs PG/MySQL.

---

## Verification

1. Backend module import sanity:
   ```
   python -c "from app.services.safe_sql_executor import SafeSQLExecutor, check_table_whitelist; \
              ok, err = check_table_whitelist( \
                'SELECT * FROM \"VYRA_TEST\".\"MUSTERILER\"', \
                ['VYRA_TEST.MUSTERILER'], 'oracle'); \
              print('UPPER allowed → uppercase ref:', ok, err)"
   ```
   Expected: `True None`.

2. Mixed-case whitelist + lowercase quoted SQL:
   ```
   ok, err = check_table_whitelist(
       'SELECT * FROM "vyra_test"."musteriler"',
       ['VYRA_TEST.MUSTERILER'], 'oracle')
   # Expected: True
   ```

3. Manual integration: F9 "Çalıştır" on Oracle source with JOIN'd
   MUSTERILER/ABONELIKLER → must NOT return "Tablo erişim yetkisi yok".
   (May still surface other errors — driver / timeout / SQL syntax — those
   are out of scope for F15.)

---

## Known risks

- The new `db_smart_api` `_seen` dedup multiplies the list by ~3×; for very
  large multi-join wizards this is a few dozen entries, still trivial.
- Any external caller of `SafeSQLExecutor.execute` that depended on
  case-sensitive matching of an exotic table identifier (mixed-case
  quoted identifier in PG, e.g. `"MyTable"` ≠ `mytable`) would now match
  case-insensitively. This is the desired BI-tool behaviour; no known
  caller relies on the stricter semantics. PG mixed-case quoted
  identifiers are unusual in this codebase.
- `check_table_whitelist` already lowercased internally, so existing
  tests asserting that behaviour continue to pass; the new normalization
  is idempotent (`.lower().lower() == .lower()`).

---

## Restart requirements

- **Backend uvicorn restart REQUIRED** (route + service module changes).
- **Frontend rebuild: NOT REQUIRED** (no JS/CSS touched).

---

## Council sign-off

- ARES — executor guard preserved, normalization is additive, no new
  attack surface.
- POSEIDON — metadata dialect case discrepancy (Oracle UPPER vs PG lower)
  absorbed by both producer (route) and consumer (executor).
- APOLLO — prompt now carries explicit dialect identifier-case rule;
  prompt is a hint, executor is the guarantee.
