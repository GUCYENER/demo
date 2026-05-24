# Brief — agentEDIT10 LLM Column Order Suggest Endpoint

**Date:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0030_metric_filter_dnd_llm_v1.md` deliverable **B10**
**Council:** POSEIDON (data flow + tenant contract) + APOLLO (LLM prompt + schema validation) + ARES (backend safety, fail-closed)
**Branch:** `hira`
**Status:** in-flight (do NOT move to done without council verification)

---

## Goal

Add a new backend endpoint that proposes an "optimal" column ordering for a
BI report, based on the primary table + optional join-table FK context. The
Filtre step (B9, parallel subagent) calls it from the wizard's "✨ LLM ile
öner" button and uses the response to reorder its drag-drop list.

## LLM wrapper signature (observed in `app/core/llm.py`)

- `call_llm_api(messages: list, temperature: Optional[float] = None) -> str`
  - Reads active config from `llm_config` table (provider/model/api_url/api_token).
  - Already implements:
    - SSL verify=False (corporate proxy),
    - Timeout from config (`timeout_seconds`, default 60s),
    - Exponential backoff retry (FIX11) for 5xx/429/timeout,
    - Structured exceptions: `LLMConnectionError`, `LLMConfigError`, `LLMResponseError`.
  - Returns raw `content` string from `choices[0].message.content`.
  - No native JSON mode in this wrapper — we ask the model to return JSON and
    parse defensively (extract first `{...}` block + `json.loads`).
- Companion: `call_llm_api_with_config(messages, config)` for widget overrides
  (not used here — we use the active config).

No new dependencies required.

## Files

### Created
- `app/services/db_smart/llm_column_order.py`
  - `suggest_order(source_id, primary_table_id, join_table_ids, available_columns, current_user) -> dict`
  - Caps `available_columns` at 30 (token budget — Risk R-2 from plan).
  - Pulls table names + FK neighbor names via:
    - `ds_db_objects` (primary + join names by id, scoped to source_id),
    - `fk_graph.expand_with_fk(...)` for FK context (best-effort; failure is
      non-fatal, ordering still works with names alone).
  - Builds Turkish prompt per plan template (id → name → date → amount → fk).
  - Defensive JSON parse: strip ```json fences, locate first `{...}` block.
  - Validates `ordered` is a subset of `available_columns` names; if validation
    fails or LLM unreachable → heuristic fallback:
      `id → name/title/code → date/time → amount/number → fk → other`,
    `rationale = "LLM yanıtı doğrulanamadı; heuristik sıra uygulandı."`
    (or "LLM servisine ulaşılamadı; heuristik sıra uygulandı." on transport
    failure).

### Edited
- `app/api/routes/db_smart_api.py`
  - New Pydantic models: `ColumnInfo`, `SuggestOrderReq`, `SuggestOrderResp`.
  - New route: `POST /api/db-smart/columns/suggest-order`.
  - Tenant guard: source_id verified against `data_sources.company_id ==
    current_user.company_id` (mirrors `_resolve_source_info` in
    `query_state_api.py:171`). On mismatch → `HTTPException(status_code=403)`.

## API contract

### Request — `POST /api/db-smart/columns/suggest-order`
```json
{
  "source_id": 12,
  "primary_table_id": 345,
  "join_table_ids": [678, 901],
  "available_columns": [
    {"name": "musteri_id",  "semantic_type": "id",     "table": "musteriler"},
    {"name": "musteri_adi", "semantic_type": "name",   "table": "musteriler"},
    {"name": "fatura_tarihi","semantic_type": "date",  "table": "faturalar"},
    {"name": "tutar",       "semantic_type": "amount", "table": "faturalar"},
    {"name": "urun_id",     "semantic_type": "fk",     "table": "faturalar"}
  ]
}
```

### Response (200)
```json
{
  "ordered":   ["musteri_id", "musteri_adi", "fatura_tarihi", "tutar", "urun_id"],
  "rationale": "Identifier solda, ad ortada, tarih ve tutar takip eder, FK sona alındı.",
  "fallback":  false
}
```
- `ordered` is **always** a permutation/subset of the input `available_columns`
  names. Never invents columns.
- `fallback=true` → heuristic was used (LLM unreachable or validation failed).
  `rationale` explains in Turkish.

### Errors
- `400` — body invalid (Pydantic) or `available_columns` empty.
- `401` — no user (existing `_require_user_id`).
- `403` — source_id not owned by current_user.company_id (cross-tenant).
- `404` — source_id does not exist at all.

## Tenant isolation (POSEIDON)

Source lookup uses `data_sources WHERE id = %s AND company_id = %s`. Three
outcomes mirror `query_state_api.py:_resolve_source_info`:
- row present → proceed,
- exists but other company → `403`,
- absent entirely → `404`.

Cursor gets `apply_vyra_user_context(cur, current_user)` before any FK/object
lookup so RLS GUCs are set fail-closed.

## Verification snippet (no HTTP)

```python
from app.services.db_smart.llm_column_order import suggest_order

result = suggest_order(
    source_id=1,
    primary_table_id=1,
    join_table_ids=[],
    available_columns=[
        {"name": "id",        "semantic_type": "id",     "table": "orders"},
        {"name": "order_no",  "semantic_type": "code",   "table": "orders"},
        {"name": "customer",  "semantic_type": "name",   "table": "orders"},
        {"name": "order_date","semantic_type": "date",   "table": "orders"},
        {"name": "amount",    "semantic_type": "amount", "table": "orders"},
    ],
    current_user={"id": 1, "company_id": 1, "is_admin": True},
)
print(result)
# Expected (no LLM configured):
# {"ordered": ["id", "order_no", "customer", "order_date", "amount"],
#  "rationale": "LLM servisine ulaşılamadı; heuristik sıra uygulandı.",
#  "fallback": True}
```

If a valid LLM config exists in the `llm_config` table and the model returns
well-formed JSON, `fallback=False` and `ordered` reflects the LLM's choice.

## Restart / reload requirements (per memory rule)

- **Backend uvicorn restart REQUIRED** — new route registration only takes
  effect after restart. The Filtre step (B9) hook will 404 otherwise.
- **No npm rebuild** in B10 itself; B9 owns the frontend hook.
- **No DB migration** — uses existing `data_sources`, `ds_db_objects`,
  `llm_config` tables.

## Risks / notes

- **R-2 (plan):** Capped at 30 columns. If caller sends >30, extra columns are
  silently dropped from prompt; response still includes only the 30 we picked.
  Frontend should pre-trim if it wants determinism. The cap is enforced inside
  `suggest_order`, so even direct service callers are safe.
- **R-1 (plan):** Invalid LLM JSON → 200 with `fallback=true`, never 502.
  Caller can decide whether to show "LLM unavailable" toast based on the flag.
- **LLM cost:** Single short prompt per request, no streaming, no looping
  retries beyond what `call_llm_api` already does.
- Temperature pinned at `0.2` for determinism in ordering decisions.
