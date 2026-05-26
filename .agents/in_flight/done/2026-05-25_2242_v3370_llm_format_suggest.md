---
slug: v3370_llm_format_suggest
title: B8 — LLM rapor format galerisi (Hazır format öner)
created: 2026-05-25T22:42+03:00
owner: hira
target_version: v3.37.0
priority: P1
status: pending
council_brief: [METIS, HERMES, TYCHE, ARES, ZEUS]
related_plans:
  - .agents/plans/2026-05-25_2230_smart_discovery_bulgular_v3370_v1.md
---

# B8 — LLM Format Suggest Endpoint

## 1. Tetikleyici (Why)
Step 4 (Önizleme) — kullanıcı "Hazır rapor formatı öner" butonuna tıkladığında LLM 3-5 hazır rapor kartı önersin (chart_type + title + group_by önerisi).

## 2. Hedef (What)
`POST /api/db/smart/llm/format-suggest`

**Request**:
```json
{
  "metric": {"metric_name": "Toplam Satış", "agg": "SUM", "formula": "SUM(tutar)"},
  "columns": ["tarih", "sehir", "musteri_id"],
  "user_intent": "yönetim raporu"
}
```

**Response**:
```json
{
  "format_cards": [
    {
      "id": "fmt_1",
      "title": "Aylık Satış Trendi",
      "chart_type": "line",
      "group_by": ["MONTH(tarih)"],
      "order_by": ["MONTH(tarih) ASC"],
      "rationale": "Zaman serisi → line chart"
    },
    {
      "id": "fmt_2",
      "title": "Şehir Bazlı Satış Dağılımı",
      "chart_type": "bar",
      "group_by": ["sehir"],
      "order_by": ["SUM(tutar) DESC"],
      "rationale": "Kategorik kırılım → bar chart"
    }
  ],
  "cache_hit": false,
  "model": "<provider>/<model>"
}
```

## 3. Kapsam

| Subagent | Files | Op |
|----------|-------|-----|
| METIS-FORMAT | `app/api/routes/llm_format_api.py` | create |
| METIS-FORMAT | `app/services/llm_format_service.py` | create |
| TYCHE+ARES | `tests/api/routes/test_llm_format_api.py` | create |

**main.py'a DOKUNMAZ** — METIS-METRIC agent main.py'a 3 router'ı tek seferde ekleyecek.

**Yasak**: diğer LLM endpoint'ler, db_smart_api.py, frontend.

## 4. Implementation Notes
- `llm_format_service.suggest_formats(metric, columns, user_intent)`:
  - LLM: `app.core.llm.call_llm_api`
  - Cache key: `llm:format:{metric_hash}:{cols_hash}:{intent_hash}`, TTL 15dk.
  - Chart type whitelist: ["line", "bar", "pie", "table", "kpi", "area"].

## 5. Test
- `test_suggest_formats_happy_path`
- `test_chart_type_whitelist_enforcement`
- `test_cache_hit`
- `test_redis_down`
- `test_auth_required`
- `test_rate_limit`

## 6. Acceptance
- [ ] 3-5 format card response
- [ ] chart_type whitelist
- [ ] LLM `call_llm_api`
- [ ] 6 pytest PASS

## 7. Gate
- KAPI 1 / KAPI 2.
