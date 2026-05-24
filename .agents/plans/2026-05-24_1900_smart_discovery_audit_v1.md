---
plan_id: 2026-05-24_1900_smart_discovery_audit_v1
created: 2026-05-24 19:00
branch: hira
version_target: n/a (audit-only, no code changes)
council_mod: 3 (analyze + report; no edits)
hebe_gate_required: false (read-only)
status: in_progress
---

# Plan — Akıllı Veri Keşfi Sekmesi End-to-End Audit

## 0. Amaç

Kullanıcı talebi: "ekip ile akıllı keşif sekmesindeki tüm süreci analiz et. hata yada gelişim alanlarını çıkar."

ZEUS workflow §5e paralel dispatch + §5d council disjoint scope kuralı uyarınca, 4 paralel **Explore alt-ajanı** ile end-to-end audit. Tüm ajanlar **read-only** (Grep/Read/Glob/Bash); kod düzenleme YOK.

## 1. Kapsam (modül haritası)

### Frontend (5 modül, ~2.5K LOC + CSS)
- `frontend/home.html` (wizard DOM bölgesi: `#dswModal`, `#dbSmartPickerModal`, `#dswStep0..4`)
- `frontend/assets/js/modules/db_smart_wizard.js` (999 LOC) — 5-step FSM
- `frontend/assets/js/modules/db_smart_picker.js` (441 LOC) — alt-modal
- `frontend/assets/js/modules/db_smart_ast_editor.js` (771 LOC) — step 5 AST
- `frontend/assets/js/modules/db_smart_ast_history.js` — undo/redo
- `frontend/assets/js/modules/db_smart_filter_modal.js` (280 LOC) — step 4 filter
- `frontend/assets/js/modules/saved_reports_grid.js` — kaydedilmiş raporlar
- `frontend/assets/css/modules/_db_smart_wizard.css` (1100+ LOC)
- `frontend/assets/css/modules/_saved_reports_grid.css`

### Backend (1 route + 22 service, ~12K LOC)
- `app/api/routes/db_smart_api.py` (1780 LOC) — 12 endpoint
- `app/services/db_smart/`:
  - `state_machine.py` (FSM)
  - `eligibility.py` (table search)
  - `fk_graph.py` (FK ilişkileri)
  - `query_assembler.py` + `sql_executor_stream.py` (SQL üretim + exec)
  - `metric_engine.py` + `custom_metric_parser.py`
  - `dialect_dictionary.py` (multi-DB)
  - `ast_renderer.py` (AST → SQL)
  - `rls_context.py` (RLS guard)
  - `saved_reports.py` (persist)
  - `learning_recorder.py` (feedback)
  - `recommendation.py`, `insight_detector.py`, `anomaly_detector.py`
  - `narrative_writer.py`, `template_marketplace.py`
  - `feature_store.py`, `schedule_runner.py`, `retention_runner.py`
  - `session_manager.py`

### LLM/RAG
- `app/services/deep_think_service.py` (3731 LOC)
- `app/services/deep_think/` (fallback, formatting, types)

## 2. Paralel Dispatch (4 Explore ajan, disjoint domain)

### EXPLORE-1 — Frontend UX/A11y/Error States (ATHENA + HEBE)
**Brief:** `.agents/in_flight/2026-05-24_explore1_frontend_audit.md`
**Scope:**
- 5-step wizard akışı: her step DOM, state transition, error rendering
- DbSmartPicker alt-modal (FK guard, persistence, search)
- AST editor (step 5) ve filter modal (step 4)
- a11y: aria-label, focus management, keyboard, tab order, ESC handling
- Error states: API 500/network/timeout/empty data/RLS-deny UX
- Empty states, loading skeleton vs spinner, FOUC
- Mobile responsiveness (DBSmart workflow desktop-first ama tablet test)
- Türkçe i18n key coverage
**Output:** Findings list with severity (P0/P1/P2/P3) + line refs.

### EXPLORE-2 — Backend Endpoint Audit (HERMES + ORACLE)
**Brief:** `.agents/in_flight/2026-05-24_explore2_backend_audit.md`
**Scope:**
- 12 endpoint imzaları, request/response schema, status code'lar
- Pydantic model validation, gerekli auth dependency
- SQL injection vektörleri (bind param kullanımı, %s vs f-string)
- N+1 query, missing index hint
- Dialect-aware SQL üretimi (PG/Oracle/MSSQL/MySQL paritesi)
- ORACLE alt-konsey: text-to-SQL prompt accuracy, schema context budget
- vyraFetch contract uyumluluğu (R016 sonrası stream/blob)
- Pagination/cap (`le=500` limit)
- Error envelope tutarlılığı
**Output:** Endpoint-by-endpoint findings + SQL injection risk matrix.

### EXPLORE-3 — LLM/RAG/Agentic Flow (METIS + PROMETHEUS)
**Brief:** `.agents/in_flight/2026-05-24_explore3_llm_audit.md`
**Scope:**
- `deep_think_service.py` 3731 LOC mimari haritası
- Chain-of-thought / multi-step agent orchestration
- Prompt template'leri (hallucination guard?)
- Embedding/vectorstore kullanımı (chunking, model seçimi, multilingual)
- Hybrid search (vector + BM25) varsa
- Retry/self-healing stratejisi
- Schema context token bütçesi (büyük schema → context overflow riski)
- few-shot example selection
- ORACLE servisinin output validation (SQL whitelist? sanitize?)
**Output:** LLM pipeline diagram + risk areas.

### EXPLORE-4 — Security/Perf/Test Coverage (TYCHE + ARES + NIKE)
**Brief:** `.agents/in_flight/2026-05-24_explore4_sec_perf_audit.md`
**Scope:**
- ARES: SQL injection, XSS (frontend `_escape`), auth bypass, RLS hole, Fernet kullanımı, token exposure
- NIKE: cache hit ratio, redis usage, query plan, N+1, frontend bundle bloat, lazy load gaps, debounce gaps
- TYCHE: test coverage map (`tests/db_smart*`, `tests/deep_think*`), fonksiyonel regresyon riski, hangi happy/edge path test edilmemiş
- Migration sırası ve RLS policy USING/WITH CHECK paritesi (HEPHAESTUS proxy)
- ZAP/Fortify uyumluluğu sinyalleri
**Output:** Security risk matrix + perf hot path + test gap list.

## 3. Disjoint scope kontrol matrisi

| Dosya | E1 | E2 | E3 | E4 |
|---|---|---|---|---|
| `frontend/**/db_smart*` | ✅ | — | — | ⚠️ XSS check |
| `frontend/home.html` (dsw bölgesi) | ✅ | — | — | — |
| `app/api/routes/db_smart_api.py` | — | ✅ | — | ⚠️ injection check |
| `app/services/db_smart/*` | — | ✅ | — | ⚠️ perf scan |
| `app/services/deep_think*` | — | — | ✅ | ⚠️ prompt injection |
| `tests/db_smart*` | — | — | — | ✅ |
| `migrations/**/043_*.py` | — | — | — | ✅ |

E4 perf/sec scan'leri E1/E2/E3 alanlarına "okuma" ile dokunabilir, ancak **edit yapmaz** — tüm ajanlar read-only.

## 4. Consolidation (ZEUS council)

4 rapor geldikten sonra ZEUS:
1. Bulguları severity'ye göre normalize eder (P0 — security/data corruption; P1 — broken UX/critical regression; P2 — UX polish/perf; P3 — code smell/refactor)
2. Disjoint scope ihlali var mı kontrol eder
3. Refactor candidate'lar → `refactor-tracker` ajanına devreder
4. Kullanıcıya **prioritized findings report** sunar:
   - P0/P1 madde sayısı + kısa açıklama + dosya:satır referansı
   - Önerilen sprint planı (M1 = P0 fix, M2 = P1 fix, M3 = P2/P3)
   - Tahmini ajan-saat (her madde için işçi tipi)

## 5. Constraints

- **Hiçbir kod düzenlemesi yapılmaz.** Bu audit-only. Bulgular sonraki sprint planına girer.
- Her ajan ≤ 30 dakika çalışmalı, raporu ≤ 500 satır.
- Bulgu formatı:
  ```
  [P0] BACKEND — SQL injection in /db-smart/preview?filter_expr
       File: app/api/routes/db_smart_api.py:842
       Risk: raw string interpolation of user filter into SQL
       Fix sketch: convert to sqlalchemy text() with bindparam
       Effort: small (1 dosya, ~10 satır)
  ```

## 6. Reporting timeline

- T+0: Plan dosyası yazıldı (bu dosya)
- T+0..2dk: 4 ajan brief'i yazılır
- T+2dk: 4 ajan paralel dispatch (background)
- T+15-25dk: Raporlar gelir
- T+25dk: ZEUS consolidation
- T+30dk: Kullanıcıya prioritized findings sunulur

## 7. Çıktı dosyaları

- `.agents/audits/2026-05-24_smart_discovery_findings.md` (consolidated, ZEUS yazar)
- Her ajan ayrıca brief frontmatter'ına `status: done` koyar ve raporu sonuç olarak döndürür
