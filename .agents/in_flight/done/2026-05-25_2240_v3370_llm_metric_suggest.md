---
slug: v3370_llm_metric_suggest
title: B4 — LLM dynamic metric generation endpoint
created: 2026-05-25T22:40+03:00
owner: hira
target_version: v3.37.0
priority: P1
status: pending
council_brief: [METIS, HERMES, TYCHE, ARES, ZEUS]
related_plans:
  - .agents/plans/2026-05-25_2230_smart_discovery_bulgular_v3370_v1.md
---

# B4 — LLM Metric Suggest Endpoint

## 1. Tetikleyici (Why)
Smart Discovery Wizard Step 2 (Metrik) — şu an statik `metric_library` listesi. Kullanıcı dinamik öneri istiyor: "tablodaki kolonlara göre METIS bana metrik önersin".

## 2. Hedef (What)
`POST /api/db/smart/llm/metric-suggest`

**Request**:
```json
{
  "source_id": 42,
  "table": "satislar",
  "columns": [
    {"name": "tutar", "type": "numeric"},
    {"name": "tarih", "type": "date"},
    {"name": "musteri_id", "type": "int"}
  ],
  "user_intent": "aylık satış raporu"  // opsiyonel
}
```

**Response**:
```json
{
  "suggestions": [
    {
      "metric_name": "Toplam Satış",
      "agg": "SUM",
      "formula": "SUM(tutar)",
      "rationale": "tutar numeric → SUM uygun, finansal toplam.",
      "confidence": 0.92
    },
    {
      "metric_name": "Müşteri Başına Ortalama Tutar",
      "agg": "AVG",
      "formula": "SUM(tutar) / COUNT(DISTINCT musteri_id)",
      "rationale": "iki kolonu birleştiren bileşik metrik",
      "confidence": 0.78
    }
  ],
  "cache_hit": false,
  "model": "<provider>/<model>"
}
```

## 3. Kapsam (Disjoint File Scope)

| Subagent | Files | Op |
|----------|-------|-----|
| METIS-METRIC | `app/api/routes/llm_metric_api.py` | create |
| METIS-METRIC | `app/services/llm_metric_service.py` | create |
| METIS-METRIC | `app/api/main.py` (sadece router include 1 satır) | edit minimal |
| TYCHE+ARES | `tests/api/routes/test_llm_metric_api.py` | create |

**Yasak**: `db_smart_api.py`, `db_smart_wizard.js`, `frontend/`, başka services.

## 4. Implementation Notes

- `llm_metric_service.suggest_metrics(source_id, table, columns, user_intent)`:
  - Prompt: "Sen veri analisti METIS. Aşağıdaki kolonlar için maks 5 metrik öner. JSON döndür."
  - LLM çağrısı: `app.core.llm.call_llm_api(messages)` (DB aktif config — yeni provider key yok).
  - Response JSON parse + validation (Pydantic schema).
  - Redis cache: key `llm:metric:{source_id}:{table}:{sha256(columns)}:{sha256(user_intent)}`, TTL 15 dk.
  - Redis down → 5sn timeout + uncached passthrough.
- Auth: mevcut `get_current_user` dependency (diğer db_smart endpoint'leri ile aynı).
- Rate limit: kullanıcı başına dakikada 10 (mevcut limiter ile).

## 5. Test (TYCHE+ARES brief)

- `test_suggest_metrics_happy_path` — mock LLM → 200 + valid schema
- `test_suggest_metrics_cache_hit` — 2. çağrı `cache_hit=true`
- `test_suggest_metrics_redis_down` — Redis exception → fallback uncached, 200 dönmeli
- `test_suggest_metrics_llm_timeout` — LLM timeout → 503 + clear error
- `test_suggest_metrics_invalid_columns` — boş columns → 400
- `test_suggest_metrics_auth_required` — unauth → 401
- `test_suggest_metrics_rate_limit` — 11. çağrı → 429
- Coverage ≥ 85%

## 6. Acceptance Criteria
- [ ] Endpoint POST + Pydantic schema doğru
- [ ] LLM çağrısı `app.core.llm.call_llm_api` ile yapılıyor (yeni client değil)
- [ ] Redis cache hit/miss çalışıyor
- [ ] 7 pytest PASS

## 7. Gate
- KAPI 1: dispatch öncesi METIS+TYCHE+ARES+HERMES masa.
- KAPI 2: spec-vs-output + curl manuel smoke.
