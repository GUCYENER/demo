# Brief — F9: Generate-report LLM endpoint + Çalıştır popup

**Date:** 2026-05-25
**Agent:** `agentEDIT_F9_generate_report`
**Council:** APOLLO (prompt + JSON validation) + POSEIDON (data flow) + ARES (SafeSQLExecutor guard + tenant scope) + HEBE (Çalıştır button + result modal)
**Plan:** `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md` — Deliverable F9

---

## Scope

Add an LLM-powered “Çalıştır” flow on the Önizleme step that takes the entire
wizard state (primary table + join tables + FK context + report columns + metric
+ free-text user note) and asks the LLM to produce a single dialect-aware
`SELECT` statement, executes it through `SafeSQLExecutor` (5 s timeout, row cap),
and returns the result to the frontend, which renders it in a modal popup.

**Out of scope (handled by sibling agents):**
- F7 multi-column endpoint already in place; we consume it but don't change it.
- F10 “Raporu Kaydet” — F9's modal only exposes a hook (`_openSaveReportModal`).
- F11 “Grafik” popup — F9's modal only exposes a hook (`window.DbSmartChart.open`).
- Chart.js bundle inclusion is F11.

---

## Backend

### New service module: `app/services/db_smart/llm_generate_report.py`

Signature:

```python
def generate_report(
    source_id: int,
    dialect: str,
    primary_table_id: int,
    join_table_ids: List[int],
    report_columns: List[Dict[str, Any]],   # [{name, table_name?, semantic_type?}]
    metric: Optional[Dict[str, Any]],       # full metric dict from wizard
    user_note: str,
    fk_context: List[Dict[str, Any]],       # [{from_table, to_table, from_col, to_col}]
    current_user: Dict[str, Any],
    limit: int = 100,
) -> Dict[str, Any]:
    # → {"sql": str, "rationale": str, "fallback": bool, "validation_error": Optional[str]}
```

Behaviour:

1. Resolve `{primary_table_id} ∪ join_table_ids` → `schema.object_name` from
   `ds_db_objects` (RLS context applied defensively, same pattern as
   `llm_column_order`).
2. Build a dialect-aware prompt — system role pins “SELECT-only, single
   statement, dialect-correct row-limit syntax, no DML/DDL”, user role lists
   tables, FKs, requested report columns, optional metric, and the user’s
   free-text request.
3. Call `app.core.llm.call_llm_api(messages, temperature=0.3)` — wrapped in the
   same defensive try-block as `llm_column_order.suggest_order` (transport
   failures and bad responses return `fallback=True`).
4. Defensively extract JSON object from the response (handles ```json fences
   and prose noise) — `_extract_json_obj` mirror.
5. Validate SQL:
   - Non-empty string.
   - Strip trailing `;` and surrounding whitespace.
   - First word must be `SELECT` or `WITH` (case-insensitive).
   - Reject `\bUPDATE|DELETE|INSERT|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|MERGE|EXEC|EXECUTE\b`.
   - Reject multiple statements (no inner `;` after string-stripping).
   - If validation fails → `fallback=True` with a deterministic
     `SELECT * FROM <primary> FETCH FIRST <n> ROWS ONLY / LIMIT n` fallback SQL.
6. Return `{sql, rationale, fallback, validation_error}`.

### Prompt template excerpt (Turkish, system + user roles)

```
SYSTEM:
Sen kıdemli bir BI/SQL uzmanısın. Yalnızca tek bir geçerli SELECT cümlesi üret.
Asla UPDATE/DELETE/INSERT/DROP/CREATE/ALTER/TRUNCATE/GRANT/REVOKE/MERGE/EXEC kullanma.
Asla birden fazla ifade üretme (noktalı virgül ile ayrılmış zincir yok).
Çıktı SADECE şu JSON: {"sql": "...", "rationale": "kısa Türkçe açıklama"}

USER:
Dialect: <oracle|postgresql|mssql|mysql>
Satır limiti: <limit>  — Dialect kuralı:
  - oracle  → "FETCH FIRST <n> ROWS ONLY"
  - postgresql/mysql → "LIMIT <n>"
  - mssql   → "SELECT TOP (<n>) ..."

Ana tablo: <schema.object>
İlişkili tablolar: <comma list>
FK ilişkileri (varsa):
  - <from_table>.<from_col> = <to_table>.<to_col>
Rapor kolonları (kullanıcı seçti):
  - <table>.<name>  (tip: <semantic_type>)
Metrik (opsiyonel):
  - metric_key: <key>
  - applicable_when: <metadata or null>
Kullanıcı talebi: "<user_note>"

Görev: Yukarıdaki kaynakları kullanarak BI kullanıcısının talebine cevap veren
TEK bir SELECT üret. Mümkünse FK ile join yap; rapor kolonlarını öncelikli olarak
listelerken metrik aggregate'ini ek kolon olarak ekleyebilirsin. Identifier'ları
dialect quote karakteri ile kapat (PG/Oracle: çift tırnak, MSSQL: köşeli, MySQL: backtick).
Çıktı SADECE JSON.
```

### New route: `POST /api/db-smart/generate-report` (in `app/api/routes/db_smart_api.py`)

```python
class GenerateReportReq(BaseModel):
    source_id: int = Field(..., ge=1)
    primary_table_id: int = Field(..., ge=1)
    join_table_ids: List[int] = Field(default_factory=list)
    report_columns: List[Dict[str, Any]] = Field(default_factory=list)
    metric: Optional[Dict[str, Any]] = None
    user_note: str = Field(default="", max_length=2000)
    fk_context: List[Dict[str, Any]] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)


class GenerateReportResp(BaseModel):
    sql: str
    rationale: str
    columns: List[str] = []
    rows: List[List[Any]] = []
    row_count: int = 0
    elapsed_ms: int = 0
    truncated: bool = False
    success: bool
    fallback: bool = False
    error: Optional[str] = None
```

Pipeline:

1. `_require_user_id(current_user)`.
2. Tenant guard: SELECT `db_type, company_id` FROM `data_sources` WHERE id=%s;
   reject if `company_id` mismatch (mirrors existing `suggest-order` route).
3. Resolve dialect from row.
4. Resolve **allowed_tables** = primary `schema.object` + each join's
   `schema.object` (read once from `ds_db_objects`).
5. Call `llm_generate_report.generate_report(...)`.
6. Execute via `SafeSQLExecutor(timeout=5, max_rows=limit).execute(sql, source,
   dialect, allowed_tables=[...], use_result_cache=False)`.
7. Compose response. Generic Turkish error messages on failure
   (information-leak guard mirrors `query_state_api`).

---

## Frontend

### `frontend/assets/js/modules/db_smart_wizard.js`

1. Inject a **“▶️ Çalıştır”** button as the first child of `#dswStep4` panel on
   `_loadPreview()` (idempotent — `data-dsw-runbtn` flag).
2. Click handler `_runGeneratedReport()` collects:
   - `source_id` ← `_state.sourceId`
   - `primary_table_id` ← `_state.selectedTableId`
   - `join_table_ids` ← `_state.selectedTables.filter(t => t.id !== primary).map(t => t.id)`
   - `report_columns` ← `_state.reportColumns.map(c => ({name: c.column_name, table_name: c.table_name, semantic_type: c.semantic_type}))`
   - `metric` ← `_state.metric || null`
   - `user_note` ← `_state.userNote || ''`
   - `fk_context` ← `_state.selectedTables` derived join hints, or empty
   - `limit` ← `100`
3. POST `/api/db-smart/generate-report` via `_fetchJson`.
4. On response → `_openResultModal(data)` (new helper).

### Result modal `_openResultModal(data)`

Mount point: dynamically `document.body.appendChild(overlay)`. Structure:

```
.dsw-result-modal-overlay
  .dsw-result-modal
    .dsw-result-modal-header  ("Rapor Sonucu" + ✕)
    .dsw-result-modal-body
      <details><summary>📝 Üretilen SQL</summary><pre class="dsw-result-sql"></pre></details>
      <div class="dsw-result-stats">...satır, ...ms[, kesildi]</div>
      <div class="dsw-result-table-wrap"><table class="dsw-result-table">…</table></div>
      <div class="dsw-result-rationale">💡 LLM Yorumu: …</div>
    .dsw-result-modal-actions
      [📊 Grafik]  [💾 Raporu Kaydet]  [Kapat]
```

Behaviour:
- Esc closes; overlay click closes; ✕ closes.
- Chart button calls `window.DbSmartChart.open({columns, rows})` if present,
  otherwise `_notify('Grafik modülü hazırlanıyor', 'info')`.
- Save button calls `_openSaveReportModal({...payload})` if exposed by F10,
  otherwise `_notify('Kayıt akışı hazırlanıyor', 'info')`.
- Error path: same modal scaffold but body contains a friendly Türkçe
  message + collapsible technical detail.

### CSS additions in `frontend/assets/css/modules/_db_smart_wizard.css`

`.dsw-result-modal-overlay`, `.dsw-result-modal`, `.dsw-result-modal-header`,
`.dsw-result-modal-body`, `.dsw-result-modal-actions`, `.dsw-result-table`,
`.dsw-result-sql`, `.dsw-result-rationale`, `.dsw-result-stats`,
`.dsw-run-btn`. Visual tokens reuse existing `--vyra-*` variables.

---

## Restart / Reload

- **uvicorn restart:** yes (new module import + new route).
- **frontend rebuild + hard-reload:** yes (`npm run build` + Ctrl+F5).
- **DB migration:** none.

---

## Test plan (smoke)

- Python REPL — `from app.services.db_smart.llm_generate_report import generate_report` →
  call with mock-ish parameters (try ODEMELER table id=460 if present in the
  dev DB) → assert returned dict contains `sql` string and the SQL passes
  `validate_sql` from `safe_sql_executor`.
- Manual: open wizard → tablo seç → metrik → filtre (yorum: "son 3 ay ürün
  satış") → Önizleme → Çalıştır → modal popup açılır, SQL + tablo + butonlar.

