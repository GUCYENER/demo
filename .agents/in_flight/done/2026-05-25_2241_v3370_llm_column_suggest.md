---
slug: v3370_llm_column_suggest
title: B5b — LLM column suggestion (metric-bound, 2 kategori)
created: 2026-05-25T22:41+03:00
owner: hira
target_version: v3.37.0
priority: P1
status: pending
council_brief: [METIS, HERMES, TYCHE, ARES, ZEUS]
related_plans:
  - .agents/plans/2026-05-25_2230_smart_discovery_bulgular_v3370_v1.md
---

# B5b — LLM Column Suggest Endpoint

## 1. Tetikleyici (Why)
Step 3 (Filtre/Kolon) — seçili metrik için anlamlı kolonları LLM öner: 2 kategori — (1) metric-bound (direkt metriğe bağlı), (2) related dimension (boyut/grup).

## 2. Hedef (What)
`POST /api/db/smart/llm/column-suggest`

**Request**:
```json
{
  "source_id": 42,
  "table": "satislar",
  "metric": {
    "metric_name": "Toplam Satış",
    "agg": "SUM",
    "formula": "SUM(tutar)"
  },
  "available_columns": [
    {"name": "tutar", "type": "numeric"},
    {"name": "tarih", "type": "date"},
    {"name": "musteri_id", "type": "int"},
    {"name": "sehir", "type": "varchar"}
  ]
}
```

**Response**:
```json
{
  "metric_bound": [
    {"column": "tutar", "rationale": "Metrik bu kolonun toplamı", "confidence": 1.0}
  ],
  "related_dimensions": [
    {"column": "tarih", "rationale": "Zaman bazlı grup için", "confidence": 0.95, "suggested_grain": "month"},
    {"column": "sehir", "rationale": "Coğrafi kırılım için", "confidence": 0.78}
  ],
  "cache_hit": false,
  "model": "<provider>/<model>"
}
```

## 3. Kapsam

| Subagent | Files | Op |
|----------|-------|-----|
| METIS-COLUMN | `app/api/routes/llm_column_api.py` | create |
| METIS-COLUMN | `app/services/llm_column_service.py` | create |
| METIS-COLUMN | `app/api/main.py` (router include 1 satır) | edit minimal |
| TYCHE+ARES | `tests/api/routes/test_llm_column_api.py` | create |

**Yasak**: diğer 3 LLM endpoint dosyaları (METIS-METRIC/FORMAT scope'u), db_smart_api.py, frontend.

**Çakışma uyarısı**: `app/api/main.py` 3 paralel METIS agent tarafından düzenleniyor. **Disjoint kuralı için**: agentlar router ekleme satırlarını birbirinden farklı kategorize edilmiş yorum bloğu altına eklemeli ("# LLM SMART DISCOVERY ROUTERS — METIS METRIC", "... COLUMN", "... FORMAT"). Veya tek bir agent (METIS-METRIC) main.py'a 3 router'ı tek seferde ekler, diğer 2 agent main.py'a dokunmaz. **Karar**: METIS-METRIC main.py'a 3 router include'u ekler; COLUMN ve FORMAT main.py'a DOKUNMAZ.

## 4. Implementation Notes
- `llm_column_service.suggest_columns(source_id, table, metric, columns)`:
  - Prompt: "Metrik X için kolonları 2 kategoriye ayır: (1) metric-bound, (2) related dimensions."
  - LLM: `app.core.llm.call_llm_api`
  - Cache key: `llm:column:{metric_name_hash}:{table}:{cols_hash}`, TTL 15dk.
  - date kolonları için `suggested_grain` (day/month/quarter/year) — LLM'den iste.

## 5. Test
- `test_suggest_columns_happy_path`
- `test_metric_bound_kategori_filtering`
- `test_date_grain_inferred`
- `test_cache_hit`
- `test_redis_down_fallback`
- `test_auth_required`
- `test_rate_limit`

## 6. Acceptance
- [ ] Endpoint + Pydantic schema
- [ ] 2 kategori response
- [ ] LLM `call_llm_api`
- [ ] 7 pytest PASS

## 7. Gate
- KAPI 1 / KAPI 2 standart.
