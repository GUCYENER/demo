---
task_id: agentFIX11_llm_resilience
created: 2026-05-24
status: queued
agent_type: general-purpose
branch: hira
priority: P1
parent_plan: 2026-05-24_2000_smart_discovery_mass_fix_v1
target_files:
  - app/core/llm.py
out_of_scope_files: [deep_think_service — FIX2]
council: METIS + NIKE (primary)
---

# FIX11 — app/core/llm.py fallback + cost guard (METIS+NIKE)

## Pre-empt
Kullanıcının kendi VYRA LLM core kodu. Malware reminder geçersiz — yetkilendirilmiş P1 resilience fix.

## Bulgular

### P1 L3 Single LLM provider, fallback chain yok (line 308-318)
- **Risk**: Primary provider (OpenAI/Anthropic) 5xx/429 → tüm Deep Think request fail
- **Fix**:
  - Provider chain config: `LLM_PROVIDERS=["openai", "anthropic", "local"]` (env var).
  - `call_llm()` wrapper:
    ```python
    for provider in LLM_PROVIDERS:
        try:
            return _call_provider(provider, ...)
        except (RateLimitError, TimeoutError, ServiceUnavailable) as e:
            logger.warning("Provider %s failed: %s, trying next", provider, e)
            continue
    raise LLMUnavailableError("All providers exhausted")
    ```
  - 4xx (user error) → fallback DENİL (direct raise).
  - Circuit breaker basit: ardışık 3 fail → 30 sn skip o provider.

### P1 L5 Cost guard yok — token quota tracking eksik
- **Fix**:
  - Her `call_llm()` öncesi `_check_quota(company_id, estimated_tokens)`:
    - Redis counter: `vyra:llm_quota:{company_id}:{YYYY-MM-DD}` (daily token spend)
    - Limit aşılırsa `QuotaExceededError`.
  - Sonrası `_record_usage(company_id, actual_tokens, cost_usd)` (provider response'tan token count).
  - Default quota: `LLM_DAILY_TOKEN_LIMIT=1_000_000` env.
  - Cost calc: provider başına `$ per 1k tokens` dict.

### Constraint detail
- Mevcut `call_llm()` imzası değişmemeli (callers dokunulmaz).
- Yeni internal helpers: `_call_provider()`, `_check_quota()`, `_record_usage()`, `_circuit_breaker_state()`.
- Redis yoksa graceful no-op (in-memory dict fallback, single-process).

## Constraints
- Yalnız `app/core/llm.py`. Diğer dosya dokunma.
- Provider chain, env var ile aç/kapa (geri uyumluluk: tek provider kaldıysa eski davranış).
- Quota error code (HTTP 429-mapped) → caller exception handling beklenir, ama burada sadece raise.

## Self Code Review
- [ ] `python -c "import app.core.llm"` syntax OK
- [ ] METIS gözü: fallback chain sırası mantıklı, prompt template'ler provider-agnostic
- [ ] NIKE gözü: cost guard latency overhead < 5ms (Redis pipeline), circuit breaker memory bounded
- [ ] Edge case: tüm provider fail → caller exception görür, deep_think_service.py'da catch nasıl?
- [ ] Backward compat: tek provider config'i hâlâ çalışır
- [ ] Diff line count

## Reporting
- Frontmatter `status: done` → `.agents/in_flight/done/`.
- ≤ 200 satır rapor (fallback chain + quota helper özet).
