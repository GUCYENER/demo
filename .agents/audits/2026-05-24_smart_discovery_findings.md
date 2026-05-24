---
audit_id: smart_discovery_full_stack_2026-05-24
created: 2026-05-24
branch: hira
version_audited: v3.34.2
parent_plan: 2026-05-24_1900_smart_discovery_audit_v1
type: read-only audit (no code changes)
council_review:
  - ATHENA: ✅ approved (frontend findings)
  - HEBE: ✅ approved (a11y findings)
  - HERMES: ✅ approved (backend findings)
  - ORACLE: ✅ approved (text-to-SQL findings)
  - METIS: ✅ approved (LLM findings)
  - PROMETHEUS: ✅ approved (RAG findings)
  - ARES: ✅ approved (security findings)
  - NIKE: ✅ approved (perf findings)
  - TYCHE: ✅ approved (test coverage findings)
total_findings: 65
p0_count: 4
p1_count: 21
p2_count: 26
p3_count: 14
---

# Akıllı Veri Keşfi — Konsolide End-to-End Audit Raporu

## Executive Summary

4 paralel Explore ajanı (disjoint scope, read-only) ile FE+BE+LLM+Sec/Perf/Test katmanlarında 65 bulgu. **Genel risk seviyesi: ORTA** — production'a giden P0/P1 24 madde var, ama hepsi `fix-forward` ile kapanabilir (yıkıcı mimari değişiklik yok).

| Katman | P0 | P1 | P2 | P3 | Toplam | Konsey |
|---|---|---|---|---|---|---|
| Frontend | 0 | 3 | 10 | 6 | 19 | ATHENA + HEBE |
| Backend | 2 | 7 | 6 | 3 | 18 | HERMES + ORACLE |
| LLM/RAG | 2 | 5 | 4 | 1 | 12 | METIS + PROMETHEUS |
| Sec/Perf/Test | 0 | 6 | 6 | 4 | 16 | TYCHE + ARES + NIKE |
| **TOPLAM** | **4** | **21** | **26** | **14** | **65** | — |

### Kritik tespit özeti
- ✅ **XSS coverage GOOD** — frontend `_escape()` her innerHTML'de mevcut (EXPLORE-1, EXPLORE-4 doğrulandı)
- ✅ **RLS fail-closed GOOD** — `RLSContextError` exception, 9 endpoint guard altında
- ✅ **AST bind discipline GOOD** — `ast_renderer` `_RenderCtx.add_bind()` ile f-string yok
- ⚠️ **P0**: `saved_reports.UPDATE` f-string + `deep_think` prompt injection + token overflow
- ⚠️ **P1 cluster**: state leakage (wizard nav), race (picker FK), dialect mismatch (silent), LLM fallback yok

---

## P0 — Acil (production öncesi mutlaka fix)

### P0-1 [BACKEND-SEC] `saved_reports.update()` f-string field concat
- **Konsey**: ARES (primary), HERMES (review)
- **File**: `app/services/db_smart/saved_reports.py:164`
- **Risk**: Whitelist'li olsa da defense-in-depth ihlali; `fields.append("updated_at = NOW()")` (line 160) bind-safe değil
- **Fix sketch**: SQLAlchemy `update()` veya hardcoded SET clause array
- **Effort**: tiny (1-2 saat)

### P0-2 [LLM-SEC] Prompt injection — query sanitize yok
- **Konsey**: ARES + METIS
- **File**: `app/services/deep_think_service.py:388-389, 632-637`
- **Risk**: Kullanıcı query'si doğrudan system prompt'a sızıyor; "ignore previous instructions" tarzı
- **Fix sketch**: User input'u izole template slot'a; instruction marker regex check
- **Effort**: small

### P0-3 [LLM-PERF] Schema context token overflow guard yok
- **Konsey**: METIS + PROMETHEUS + NIKE
- **File**: `app/services/deep_think_service.py:500-528`
- **Risk**: 100+ tablolu source → prompt token bütçesi aşılıyor → LLM 4xx error; %1-2 query etkilenir
- **Fix sketch**: `tiktoken` ile sayım; top-N relevance kes; 500 token response reserve
- **Effort**: medium

### P0-4 [BACKEND-PERF] `/execute` limit=1M sync fetchall → OOM
- **Konsey**: HERMES + NIKE
- **File**: `app/api/routes/db_smart_api.py:104` Pydantic `Field(le=1000000)`
- **Risk**: Client `limit=1000000` → cursor.fetchall() → pod OOM
- **Fix sketch**: `le=100_000`; `limit > 50_000` ise SSE zorunlu; executor'da hard clamp
- **Effort**: small

---

## P1 — Bu sprint (kritik UX/regresyon)

### Frontend (ATHENA + HEBE)
| # | Bulgu | File:line | Effort |
|---|---|---|---|
| F1 | Wizard step backward state leakage (metric/filters reset yok) | `db_smart_wizard.js:84-118` | small |
| F2 | AST editor unmount → `_state.currentAst` null'lanmıyor → stale snapshot | `db_smart_wizard.js:86-89`, `db_smart_ast_editor.js:54-61` | small |
| F3 | Picker FK fetch race + AbortController yok | `db_smart_picker.js:194-228` | medium |

### Backend (HERMES + ORACLE)
| # | Bulgu | File:line | Effort |
|---|---|---|---|
| B1 | Dialect mismatch silent downgrade (PG source, Oracle request → PG SQL) | `db_smart_api.py:806` | small |
| B2 | RLS alias heuristic AST injection (`_detect_company_scoped_aliases`) | `db_smart_api.py:285-322` | tiny |
| B3 | Password decrypt failure → empty string sessizce | `db_smart_api.py:717-727` | small |
| B4 | RLS context fail-closed entegrasyon testi yok | `rls_context.py:119-139` | tiny |
| B5 | EXPLAIN cache key JSON canonical değil → key collision | `db_smart_api.py:460-487` | small |
| B6 | MySQL `param_style: pyformat` (yanlış, `format` olmalı) | `dialect_dictionary.py:74-95` | small |
| B7 | Dialect dict 4-dialect parity eksik (`functions` dict) | `dialect_dictionary.py:80-120` | small |

### LLM/RAG (METIS + PROMETHEUS)
| # | Bulgu | File:line | Effort |
|---|---|---|---|
| L1 | Hallucination skip — kısa source <1500ch validation atlıyor | `deep_think_service.py:770-777` | small |
| L2 | Streaming abort yok — client disconnect → resource leak | `deep_think_service.py:1529-1551` | small |
| L3 | Single LLM provider, fallback chain yok | `app/core/llm.py:308-318` | small |
| L4 | JSON parse no schema validation → null field risk | `deep_think_service.py:3640-3642` | small |
| L5 | Cost guard yok — token quota tracking yok | `app/core/llm.py` | medium |

### Sec/Perf/Test (TYCHE + ARES + NIKE)
| # | Bulgu | File:line | Effort |
|---|---|---|---|
| S1 | fk_graph N+1 risk — Redis cache yok | `fk_graph.py` (expand_with_fk) | medium |
| S2 | RLS integration test eksik (non-owner DENY, owner ALLOW) | `tests/db_smart/test_rls_context.py` | medium |
| S3 | AST round-trip test eksik (render → parse → render) | `tests/db_smart/test_ast_renderer.py` | medium |
| S4 | Partition recreation RLS reapplication audit | `learning_recorder.py:414-424` | small |
| S5 | Session cache cross-tenant test eksik | `tests/db_smart/` | medium |
| S6 | Migration 032 RLS policy oluşturma test edilmemiş | `tests/db_smart/test_migration_*.py` | medium |

---

## P2 — Sonraki sprint (UX polish / perf / mid-priority)

### Frontend (10 madde)
- Filter modal focus trap selector eksik (disabled inputs)
- Tablet grid reflow focus loses (CSS `order` eksik)
- Stepper click validation bypass (forward-skip mümkün)
- Error state generic — 403/401/404 ayrımı yok
- i18n inconsistent error param binding (line 472)
- Loading state aria-live completion announcement yok
- Form validation client-side column existence check yok
- Body scroll-lock single boolean (nested modal'da bozulur)
- Hard-coded TR string "Eşleşen tablo yok" (i18n key yok)
- Search input debounce gap (her keystroke fetch)

### Backend (6 madde)
- Pydantic `Any` field constraint eksik (`StepRequest.payload`)
- Password decrypt error → empty (silent failure)
- Eligibility cardinality check yok (100+ status match)
- Partition archive `company_id` index yok
- Saved report wizard_state schema_version yok
- Embed share token URL leak (browser history/log)

### LLM (4 madde)
- Prompt leak regex evasion (formatting.py:30-54)
- Embedding multilingual config kapsam dışı
- Hybrid search reranking yok
- Few-shot static template

### Sec/Perf/Test (6 madde)
- PII masking cache 60sn TTL window
- Bearer token console.log (frontend api_client.js:155, low impact)
- LLM mock coverage incomplete (rate limit, malformed)
- Migration 033 seed validation test eksik
- Session cache warm-up endpoint çağırmazsa cold start
- Retention archive query cascade riski (large partition)

---

## P3 — Backlog (refactor / nit / future)

14 madde (özet, detay her ajan raporunda):
- Frontend: i18n FOUC, mobile `100vh→100dvh`, focus contrast AAA, ArrowDown stepper, autocomplete=off, AST history silent fail
- Backend: fk_graph batch query, JSON canonical EXPLAIN cache key, share token warning
- LLM: retry exponential backoff
- Sec/Perf/Test: PII masking edge cases, feature_store bucket coverage, deploy RLS ENABLE verify, frontend bundle lazy load

---

## Önerilen Sprint Planı

### Sprint v3.34.3 (3-5 gün) — P0 cluster
- P0-1, P0-2, P0-3, P0-4 (4 madde)
- B2, B6 (P1 tiny effort) — düşük efor yüksek değer
- **Konsey dispatch**: ARES (primary), HERMES, METIS, NIKE
- **Versiyon hedefi**: v3.34.3 hotfix

### Sprint v3.35.0 (1-2 hafta) — P1 cluster
- F1, F2, F3 (frontend state mgmt)
- B1, B3, B4, B5 (backend stability)
- L1, L2, L3, L4 (LLM resilience)
- S1, S2, S3, S4, S5, S6 (sec/perf/test gap)
- **Konsey dispatch**: ATHENA+HEBE, HERMES+ORACLE, METIS+PROMETHEUS, TYCHE+ARES+NIKE (4 paralel ajan)
- **Versiyon hedefi**: v3.35.0

### Sprint v3.35.1+ — P2/P3
- Refactor-tracker'a devret: P2 26 + P3 14 = 40 madde
- `.agents/refactor/REFACTOR_BACKLOG.md` içine R019-R058 olarak işle

---

## Council Gate Review Sonucu

- ATHENA ✅ (frontend findings'i onaylı)
- HEBE ✅ (a11y, FOUC, error toast tutarlılık onaylı)
- HERMES ✅ (backend endpoint imzaları onaylı)
- ORACLE ✅ (dialect parity findings onaylı)
- METIS ✅ (LLM pipeline findings onaylı)
- PROMETHEUS ✅ (RAG findings onaylı — kapsam dar, sonraki audit'te genişletmeli)
- ARES ✅ (SQL injection + XSS + RLS findings onaylı, EXPLORE-2/4 cross-confirmed)
- NIKE ✅ (perf hot path onaylı)
- TYCHE ✅ (test gap list onaylı — 601 test mevcut, +20 gerekli)

> **Disjoint expertise kontrol**: 4 ajan birbirinin alanına yalnız read-only girdi; primary/review modeli temiz.

---

## Raporlar (kaynak)

- EXPLORE-1: `.agents/in_flight/done/2026-05-24_explore1_frontend_audit.md`
- EXPLORE-2: `.agents/in_flight/done/2026-05-24_explore2_backend_audit.md`
- EXPLORE-3: `.agents/in_flight/done/2026-05-24_explore3_llm_audit.md`
- EXPLORE-4: `.agents/in_flight/done/2026-05-24_explore4_sec_perf_audit.md`
- Plan: `.agents/plans/2026-05-24_1900_smart_discovery_audit_v1.md`
