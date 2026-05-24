# agentFIX13 + agentFIX14 — Copy display_sql & Resolve Dialect

**Date:** 2026-05-25
**Council:** ATHENA (UX consistency) + POSEIDON (DB dialect correctness) + ARES (regression safety)
**Plan:** `.agents/plans/2026-05-25_0200_login_resilience_qb_fixes_v1.md`
**Deliverables:** F2 (frontend) + B12 (backend)
**Status:** Implemented — awaiting council verification before done/ move

---

## F2 — `_copySql` uses `lastDisplaySql` instead of raw `lastSql`

**File:** `frontend/assets/js/modules/query_builder.js`
**Function:** `_copySql` (line ~341)

### Problem
- "Üretilen SQL" panel renders `data.display_sql` (literals inlined, human-readable).
- "Kopyala" button copied `state.lastSql` (raw `%s` placeholders).
- User mismatch: paste into external SQL client → broken query.

### Fix
- Introduce local `sqlToCopy = state.lastDisplaySql || state.lastSql` (fallback-safe — older snapshots without lastDisplaySql still copy something instead of erroring).
- Apply to BOTH clipboard.writeText path AND textarea fallback path.
- Status text updated: `"SQL panoya kopyalandı (görüntülenen sürüm)."`

### Edited lines
- Line ~347-368 (try block of `_copySql`).

### Council notes
- ATHENA: WCAG — `_announce` and `showToast` strings unchanged (only inline status got "(görüntülenen sürüm)" suffix; screen-reader announcement remains short).
- ARES: Fallback path preserves behavior if `lastDisplaySql` was never set (e.g., very old session before v3.35.0 cache).

---

## B12 — `_resolve_dialect` RealDictCursor `KeyError` bug

**File:** `app/api/routes/query_state_api.py`
**Function:** `_resolve_dialect` (line 250-262 → now 250-268)

### Problem
```python
row = cur.fetchone()
if row and row[0]:        # RealDictCursor returns dict → row[0] → KeyError(0)
    return str(row[0]).lower()
```
- `KeyError(0)` caught by outer `except Exception` → silently fell back to `'postgresql'`.
- Downstream AST renderer emitted `LIMIT 100` for Oracle XE sources → ORA-00933 / generic "Çalıştır" error: *"SQL çalıştırma sırasında beklenmeyen bir hata oluştu"*.

### Fix
- Dict-aware row access matching `_resolve_source_info` (line 224-227) pattern:
```python
if row:
    _db_type = row.get('db_type') if isinstance(row, dict) else (row[0] if row else None)
    if _db_type:
        logger.debug("[query_state] resolved dialect for source %s: %s", source_id, _db_type)
        return str(_db_type).lower()
```
- Added `logger.debug` for traceability (operator can confirm dialect resolution in dev logs).

### Council notes
- POSEIDON: Dialect mapping fed into AST renderer (`FETCH FIRST n ROWS ONLY` vs `LIMIT n`) — Oracle pathway now reachable.
- ARES: Outer `except` retained — any future schema drift (column rename, type change) still logged via `logger.warning` instead of crashing the request.

---

## Verification Plan

1. Frontend rebuild + bundle grep for `lastDisplaySql` reachability in `_copySql`.
2. Python snippet validating `_resolve_dialect(3, None) == 'oracle'` and fallback for nonexistent source.

### Results

**Frontend build:**
```
dist\bundle.min.css      422.4kb
dist\bundle.min.js       873.6kb
Done in 198ms / 323ms — no warnings, no errors.
CSS: 660KB → 422KB (36% küçüldü) | JS: 1729KB → 874KB (49% küçüldü)
```

**Bundle grep — `lastDisplaySql`:**
- 4 raw occurrences in `dist/bundle.min.js`.
- Critical clipboard path confirmed: `const n=c.lastDisplaySql||c.lastSql;if(navigator.clipb…`
- Cache write path confirmed: `c.lastDisplaySql=o.display_sql||o.sql||""`
- Reset path confirmed: `c.lastDisplaySql=""`

**Python `_resolve_dialect` snippet:**
```
source=3: oracle
source=9999: postgresql
explicit oracle override: oracle
```
Matches all three expected outcomes — B12 fix verified: Oracle source_id=3 now correctly resolves to `'oracle'` instead of silently falling back to `'postgresql'`.

---

## Restart / Reload Requirements
- **Backend:** Restart uvicorn — `_resolve_dialect` is module-level Python.
- **Frontend:** Hard reload after `npm run build` — `bundle.min.js` regenerated.
- **No migration / no config change.**
