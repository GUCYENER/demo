# agentFIX15 — user_pref SAVEPOINT (B13)

**Council:** APOLLO + ARES
**Plan:** `.agents/plans/2026-05-25_0200_login_resilience_qb_fixes_v1.md` deliverable B13
**Date:** 2026-05-25
**Status:** in_flight (do NOT move to done/ — council verification required)

## Problem (carried from B7 surprise finding)

`app/services/db_smart/metric_engine.py::_load_user_pref_metrics` queries
`dbsmart_user_preferences` inside a `try/except`. The Python exception is
swallowed, BUT the underlying PostgreSQL transaction has already been marked
aborted (psycopg2's `InFailedSqlTransaction`). Any subsequent `cur.execute(...)`
on the **same connection** raises:

    psycopg2.errors.InFailedSqlTransaction:
    current transaction is aborted, commands ignored until end of transaction block

### Repro (B7)

```python
with get_db_context() as conn:
    cur = conn.cursor()
    apply_vyra_user_context(cur, uctx)
    sig = metric_engine.load_table_signature(cur, 3, tid)
    metric_engine.list_eligible(cur, sig, uctx, min_score=0.6)  # OK
    metric_engine.list_eligible(cur, sig, uctx, min_score=0.0)  # FAIL
```

Why hot-path is "safe": each HTTP request gets a fresh pooled connection +
`get_db_context()` opens a new transaction. Within a single request, the
metric engine is typically called once. But:
- Tests / REPL / batch scripts that reuse one connection trip on this
- Future code that calls `list_eligible` then any other query in the same
  connection is silently broken
- A latent bug — should be defended at the source

## Autocommit finding

Read `app/core/db.py`:
- `_get_pool()` builds `ThreadedConnectionPool` **without** setting `autocommit`
- `get_db_conn()` direct-connection fallback also leaves autocommit at default
- Default psycopg2 behavior: `autocommit = False` (i.e., an implicit
  transaction is started on the first statement)
- `get_db_context()` uses explicit `conn.commit()` / `conn.rollback()` —
  consistent with autocommit=False

**Conclusion:** SAVEPOINT works correctly because we are always inside a
transaction. No need for a `BEGIN` shim.

## Fix design

Wrap the `SELECT frequent_metrics FROM dbsmart_user_preferences ...` in a
PostgreSQL SAVEPOINT block:

```python
sp = "sp_user_pref"
try:
    cur.execute(f"SAVEPOINT {sp}")
    cur.execute("SELECT frequent_metrics FROM dbsmart_user_preferences "
                "WHERE user_id = %s LIMIT 1", (uid,))
    row = cur.fetchone()
    cur.execute(f"RELEASE SAVEPOINT {sp}")
    # ... process row ...
except Exception as e:
    logger.warning("[metric_engine] user_pref load failed (savepoint rollback): %s", e)
    try:
        cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
    except Exception:
        pass
    return set()
```

Effect: when the inner SELECT fails (table missing, RLS deny, anything else),
`ROLLBACK TO SAVEPOINT` returns the transaction to a usable state. The
caller's connection remains healthy for subsequent statements.

## Why NOT conn.rollback()

Rolling back the entire connection in a helper would discard any pending
writes the caller has staged in the same transaction — silent data loss.
SAVEPOINT is the correct surgical tool here.

## Files touched

- `app/services/db_smart/metric_engine.py` — `_load_user_pref_metrics` only

## Restart

- **uvicorn restart REQUIRED** to pick up the new metric_engine code path
  (Python module reload)
- Frontend: no changes — no bundle rebuild needed
- DB: no schema changes — no migration needed

## Extra finding (CONFIRMED via verification run)

`dbsmart_user_preferences` table **exists**, but the `frequent_metrics`
**column does not exist**. The verification run surfaced (now at WARN level):

    [metric_engine] user_pref load failed (savepoint rollback):
    column "frequent_metrics" does not exist
    LINE 2:             SELECT frequent_metrics

Previously this was logged at DEBUG and silently dropped — root cause was
invisible. The B13 fix bumped the log to WARN so the schema drift surfaces.

**Follow-up recommendation (NOT in B13 scope):**
- Either add a migration that creates the `frequent_metrics JSONB` column on
  `dbsmart_user_preferences`, or
- Update `_load_user_pref_metrics` to query the actually-existing user_pref
  schema (whatever column carries the user's favorite metric_keys today)
- File a B14+ ticket — outside B13's "stop the transaction-abort cascade"
  remit

## Verification (PASSED 2026-05-25)

```
call 1 eligible @ 0.6: 0
call 2 eligible @ 0.0: 5
call 3 list_all_active: 30
```

All three calls succeeded on the same connection. Previously call 2 would
have raised `InFailedSqlTransaction`. WARN log appears twice (once per
list_eligible call), proving the savepoint correctly contained the failure
and the caller's transaction stayed usable.
