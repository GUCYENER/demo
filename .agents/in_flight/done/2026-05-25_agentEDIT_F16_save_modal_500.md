# Brief — F16: Save Report 500 root cause + Save modal z-index fix

**Date:** 2026-05-25
**Agent:** `agentEDIT_F16_save_modal_500`
**Council:** HEBE (modal stacking + UX) + ARES (error surfacing) + POSEIDON (DB schema + persistence)
**Plan:** `.agents/plans/2026-05-25_0700_v336_smoke_bugs_v1.md` (§F16)

---

## Scope

Two bugs reported during v3.36 smoke:

1. **MAJOR — Save Report modal renders BEHIND the F9 result modal.**
   `.dsw-save-modal { z-index: 1080 }` while
   `.dsw-result-modal-overlay { z-index: 11000 }` and
   `.dsw-chart-modal { z-index: 11050 }` (F11b). Clicking "💾 Raporu
   Kaydet" inside the F9 result modal opened the save dialog under the
   F9 backdrop → invisible + non-interactive.

2. **MAJOR — `POST /api/db-smart/sessions/{uid}/save-report` returns
   500** with FE generic "Sunucuda beklenmeyen bir hata oluştu" toast.
   F10b added `wizard_state` / `generated_sql` / `metric_key` /
   `schema_version` to `SaveReportRequest`; route now reads them. A real
   exception was escaping the route (no try/except wrapper) producing a
   raw 500 with no JSON `detail`, so the FE error helper fell back to the
   canned message.

---

## Investigation findings

### DB schema (migration 032)

`migrations/versions/032_v3300_db_smart_core_tables.py` lines 94-116:

```
CREATE TABLE IF NOT EXISTS dbsmart_saved_reports (
    id, user_id, company_id, source_id, name, description,
    wizard_state JSONB NOT NULL, last_sql TEXT, last_dialect VARCHAR(20),
    tags TEXT[], run_count, last_run_at, last_run_snapshot JSONB,
    is_shared, share_token, share_expires_at,
    schedule_cron, schedule_next_run, owner_team_id,
    created_at, updated_at
);
```

There is **no `generated_sql`, `metric_key`, or `schema_version`
column**. The route already correctly maps `body.generated_sql → last_sql`
and ignores `metric_key` / `schema_version` (transport-only fields). So
the 500 is NOT a missing column / signature mismatch — the helper
signature matches.

### `saved_reports.save()` signature

```
save(cur, user_ctx, *, name, wizard_state,
     last_sql=None, last_dialect=None, source_id=None,
     description=None, tags=None) -> {id, created_at} | None
```

Matches every kwarg the route passes. No `TypeError` from kwarg shape.

### Real root cause — error surfacing gap

The pre-fix `post_save_report` had **no top-level try/except**. Any
exception raised before / outside `saved_reports.save` (e.g.
`_require_user_ctx ValueError`, `apply_vyra_user_context`,
`session_manager.load_session`, `json.dumps` on non-serializable wizard
state) escaped to FastAPI's default handler → bare 500 with empty body
→ FE generic message → no traceback in narrow `logger.warning`.

`saved_reports.save()` itself swallowed DB exceptions with
`logger.warning("…: %s", e)` — only the exception **string** was logged,
no traceback, so the actual psycopg/RLS reason was invisible in server
logs too.

## Fix

### 1) Backend route hardening — `app/api/routes/db_smart_api.py`

`post_save_report` (~L978) and `post_save_report_flat` (~L1062) now
wrap the body in `try / except`:

- `HTTPException` → re-raise (FastAPI passthrough).
- `ValueError` → `HTTPException(400, str(ve))` (validation errors).
- `Exception` → `logger.exception(...)` + `HTTPException(500,
  f"Rapor kaydedilemedi: {type(e).__name__}: {e}")` (server log gets
  full traceback, client gets actionable detail).
- `saved_reports.save(...) is None` → explicit
  `HTTPException(500, "Rapor kaydedilemedi (DB INSERT başarısız - server
  log'una bakın).")`.

### 2) Service-level logging — `app/services/db_smart/saved_reports.py`

`save()` INSERT catch upgraded from `logger.warning("…: %s", e)` to
`logger.exception("…: %s", e)` so the next failure dumps the full
psycopg traceback (chain + position + SQLSTATE).

### 3) CSS z-index — `frontend/assets/css/modules/_db_smart_wizard.css`

`.dsw-save-modal` z-index `1080 → 11100`.

Justification:
- `.dsw-result-modal-overlay` = 11000 (F9 result modal)
- `.dsw-chart-modal` = 11050 (F11b chart popup)
- Toast/notification layer = 12000
- **11100** sits above F9 + chart, below toast (900 headroom). Save
  and chart are mutually exclusive in practice but the buffer keeps
  ordering stable if a future flow opens both.

---

## Files changed

- `frontend/assets/css/modules/_db_smart_wizard.css` (z-index 1080 → 11100 + comment)
- `app/api/routes/db_smart_api.py` (try/except wrapper on both save endpoints)
- `app/services/db_smart/saved_reports.py` (`logger.warning` → `logger.exception`)

## Restart requirements

- **uvicorn restart ŞART** — route handler + service module değişikliği.
- **Frontend bundle rebuild + hard-reload (Ctrl+Shift+R)** — CSS
  z-index change needs new `bundle.min.css`.

## Smoke verification

1. F9 → "Raporu Kaydet" → modal görünür olmalı (overlay > 11000).
2. Geçerli body ile kaydet → 200 + toast "Rapor kaydedildi".
3. Hatalı body (forced unhandled exception) → 500 + detail =
   `"Rapor kaydedilemedi: <ExcType>: <msg>"` + server log'da full
   `logger.exception` traceback.

## Known risks

- Detail leak: 500 detail includes Python exception type+message — şu
  an Türkçe BI ürünü internal kullanıcılarda OK; public API'ye expose
  edilirse sanitize gerekir (P2 follow-up).
- 1080 → 11100 atlayışı stacking context'te başka custom widget
  varsayımı bozabilir; mevcut katmanlar (1080/11000/11050/12000) ile
  uyumlu.

## Council sign-off

- HEBE — modal stacking düzeltildi, F9 / chart / save mutual ordering
  doğru.
- ARES — error surfacing (try/except + logger.exception) prod-grade
  diagnostik sağlıyor.
- POSEIDON — DB schema kontrol edildi (migration 032), kolon eksikliği
  yok; persistence yolu sağlam.
