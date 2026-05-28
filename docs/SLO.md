# VYRA Service Level Objectives — v3.39.0 baseline

> **Status:** Living document. Owners may update SLO targets after
> reviewing four consecutive weekly burn-rate reports.
> Last updated: 2026-05-28 (initial baseline, KAP 6 bootstrap).

This document is the authoritative SLO contract for VYRA L1 Support API.
It is wired into BITIR `KAP 6 — Observability` (vyrazeus §8): every
user-visible flow change is checked against the targets below, and any
sustained burn-rate ≥ 2× the baseline shows up as a 🔴 line in the
session-end report.

## How to read this file

- **SLI** — the metric we actually measure (request latency, success
  ratio, availability). It must come from a stable signal already
  emitted by the service — OTEL span attribute, Prometheus histogram,
  or Nginx access log. If it isn't emitted, it isn't an SLI.
- **SLO** — the target the SLI must stay within over the **rolling
  30-day window**. Single-day excursions are allowed; the window is
  what we defend.
- **Error budget** — `1 − SLO`, expressed as the share of bad events
  the service is allowed in the window. A 99% SLO buys a 1% error
  budget (≈ 7h 12m of downtime / month for an availability SLI).
- **Burn-rate alert** — fires when the *recent* error rate would
  exhaust the budget faster than the window allows. We use the
  Google SRE workbook two-window approach: a fast burn (1h window,
  14.4× burn-rate, page-grade) and a slow burn (6h window, 6× burn-rate,
  ticket-grade).

## Baseline services & targets

The four services below are the **release-blocking surfaces**. New
services should land with their own row before they receive user
traffic.

### 1. text-to-sql — `app/services/text_to_sql.py`

| Field | Value |
|---|---|
| User question | "When the user asks the DB chat a question, do they get a result fast enough?" |
| SLI | `vyra_text_to_sql_request_duration_seconds` histogram, `p95` quantile, scoped `endpoint="/api/db-smart/sessions/{sid}/execute/stream"` |
| SLO | `p95 < 3.0s` over rolling 30 days, excluding self-heal retries (those have their own budget) |
| Error budget | 5% of requests may exceed the threshold |
| Fast-burn (page) | p95 > 3s for ≥ 5 min AND error-budget burn ≥ 14.4× → page on-call |
| Slow-burn (ticket) | p95 > 3s for ≥ 60 min AND burn ≥ 6× → file ticket |
| Dependencies that move the needle | LLM provider RTT, Oracle/MSSQL driver TCP RTT, `safe_sql_executor` 5s timeout |

### 2. deep-think — `app/services/deep_think_service.py`

| Field | Value |
|---|---|
| User question | "Does the multi-step planner finish with a usable answer?" |
| SLI | `(success / total)` from `vyra_deep_think_run_total{outcome="success"}` Prometheus counter; "success" means the planner emitted a final answer, not a fallback |
| SLO | success rate `> 99%` over rolling 30 days |
| Error budget | 1% of runs may end in fallback / planner-error |
| Fast-burn (page) | success rate < 95% for ≥ 5 min AND burn ≥ 14.4× → page |
| Slow-burn (ticket) | success rate < 98% for ≥ 60 min AND burn ≥ 6× → ticket |
| Dependencies that move the needle | LLM provider availability, RAG retrieval, prompt-injection guard rejections (which **do** count as failures — they're contract failures, not legitimate user behaviour) |

### 3. RAG search — `app/services/rag_service.py`

| Field | Value |
|---|---|
| User question | "Does knowledge-base search feel instant?" |
| SLI | `vyra_rag_search_request_duration_seconds` histogram, `p95` quantile, scoped `endpoint="/api/rag/search"` |
| SLO | `p95 < 800ms` over rolling 30 days |
| Error budget | 5% of requests may exceed the threshold |
| Fast-burn (page) | p95 > 800ms for ≥ 5 min AND burn ≥ 14.4× → page |
| Slow-burn (ticket) | p95 > 800ms for ≥ 60 min AND burn ≥ 6× → ticket |
| Dependencies that move the needle | pgvector HNSW recall settings, hybrid-search reranker, embedding-model RTT |

### 4. API gateway — Nginx in front of the FastAPI app

| Field | Value |
|---|---|
| User question | "Is the site up?" |
| SLI | `(2xx + 3xx + 4xx) / total` from Nginx access log; 5xx and connection-refused count as failures, 4xx counts as success because those are client mistakes |
| SLO | availability `> 99.5%` over rolling 30 days |
| Error budget | 0.5% — about 3h 36m / month |
| Fast-burn (page) | availability < 95% for ≥ 5 min AND burn ≥ 14.4× → page |
| Slow-burn (ticket) | availability < 99% for ≥ 60 min AND burn ≥ 6× → ticket |
| Dependencies that move the needle | uvicorn worker health, Docker daemon, host TCP stack |

## RED method coverage requirement

Every new endpoint or service touched in a BITIR-eligible PR must emit
the three RED signals, otherwise the KAP 6 check refuses to pass:

- **Rate** — counter incremented on each call (`*_request_total`)
- **Errors** — counter scoped to non-2xx / fallback / exception
  (`*_errors_total`), labelled so the cause is queryable
- **Duration** — histogram with buckets that cover the SLO threshold
  (`*_request_duration_seconds`)

The shared helper in `app/services/observability/prometheus_metrics.py`
wraps these — call sites should not declare metrics by hand.

## Operating procedure when an SLO breaks

1. **Acknowledge** — the on-call confirms the page within 5 min so the
   alert doesn't auto-escalate.
2. **Stabilise** — restore service first, debug later. If a recent
   deploy is the suspect, revert via `git revert <hash>` and redeploy;
   if a dependency (LLM provider, DB) is the suspect, fail closed with
   the existing graceful-degradation path.
3. **Burn-rate freeze** — while the budget is exhausted, freeze
   non-critical merges. The `merge freeze` label on the PR queue
   makes this visible.
4. **Post-mortem** — within 5 business days, file
   `.agents/incidents/YYYY-MM-DD_<slug>.md` (template TBD; see
   vyrazeus orta-öncelik backlog). Blameless, evidence-first.
5. **SLO review** — if the same SLO breaks twice in 30 days for the
   same root cause, the SLO target itself is wrong (or the architecture
   is) — the document gets updated, not the on-call rotation.

## What is NOT yet in scope

These are deliberate omissions to keep the v3.39.0 baseline shippable:

- **Per-tenant SLOs** — single global budget for now; per-company
  multi-tenant SLO (RLS-aware) lands when the customer count makes
  it worth the dashboard complexity.
- **Saturation/Latency-of-the-bottleneck** — the USE method
  (Utilisation, Saturation, Errors) for backing stores (PG connection
  pool, Redis queue depth, Oracle wait events) will get its own
  document once we have the dashboards.
- **Synthetic probes** — no external blackbox-exporter yet; the
  availability SLI is derived from real traffic only. If real
  traffic is low (off-hours), the signal is noisy.
- **Mobile / PWA latency** — out of scope until there is a mobile
  surface.

## References

- Google SRE Workbook, ch. 5 "Alerting on SLOs": fast/slow burn-rate
  windows and thresholds we adopted.
- vyrazeus §8 KAP 6 — gate that enforces this document.
- `app/services/observability/otel_setup.py`, `prometheus_metrics.py` —
  the actual emission helpers.
