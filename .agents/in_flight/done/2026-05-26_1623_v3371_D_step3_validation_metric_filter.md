---
slug: v3371_D_step3_validation_metric_filter
title: v3.37.1 D — Step3 filtre validation + metric-aware kolon LLM ayrı kategori
created: 2026-05-26T20:23+03:00
owner: ZEUS
council: [ATHENA (semantic logic), METIS (LLM prompt), HEBE (UI), POSEIDON (validation), TYCHE (regression)]
related_audit: .agents/audits/v3371_bulgular_audit.md (Madde 5)
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
gate_1_status: pending
gate_2_status: pending
dispatch_target: HERMES subagent (mixed backend + frontend)
---

# v3.37.1 D — Step3 Filter Validation + Metric-Aware LLM Kategori

## Verbatim Spec (Madde 5)

> Filtre kolon validation + toast + metric-aware kolon LLM ayrı kategori

İki ayrı gap:
1. **Validation:** seçilen kolonlar metric ile uyumsuzsa toast
2. **Metric-aware kategori:** LLM'den metric için en uygun kolonları ayrı bir kategori altında öner

## Sorun

`_renderStep3` ([db_smart_wizard.js:977-1068](frontend/assets/js/modules/db_smart_wizard.js#L977-L1068)):
- Sadece tablo-grup flat catalog gösteriyor
- Metric-aware ayrı kategori yok
- `_addReportColumn` ([:1104](frontend/assets/js/modules/db_smart_wizard.js#L1104)) sadece duplicate check yapıyor; metric semantic uyumu kontrolü yok

## Scope

**Backend (yeni endpoint veya mevcut genişletme):**
- `app/api/routes/db_smart_api.py` — `POST /db-smart/llm/column-filter-suggest` (ya da mevcut `/llm/column-suggest` metric-aware payload destekle)
- `app/services/ds_learning_service.py` veya `services/db_smart/metric_engine.py` — metric vs column semantic-type uyum kuralları
- Yeni prompt: METIS sorumluluğunda — metric_key + columns → relevance ranked subset + rationale

**Frontend:**
- `frontend/assets/js/modules/db_smart_wizard.js` — `_renderStep3` içinde "✨ Metrik için uygun kolonlar" kategorisi (open by default), `_addReportColumn` içinde validation + toast

### Backend kontratı

**Request:**
```json
POST /api/db-smart/llm/column-filter-suggest
{
  "source_id": 12,
  "metric_key": "monthly_revenue_growth",
  "candidates": [{"name":"...","semantic_type":"...","table_id":"..."}],
  "user_intent": "..."
}
```

**Response:**
```json
{
  "ok": true,
  "metric_key": "monthly_revenue_growth",
  "recommended": [
    {"column_name":"...","table_id":1,"rationale":"...","relevance":0.9}
  ],
  "warn_columns": [
    {"column_name":"...","reason":"semantic_mismatch"}
  ],
  "cache_hit": false
}
```

**Validation kuralları (POSEIDON):**
- Metric `amount`/`sum` türünde ise → `numeric` semantic_type tercih edilir
- Metric `growth`/`trend` ise → `datetime` + numeric çifti gerekir
- Metric `count` ise → herhangi PK/kategorik OK

### Frontend değişiklik

1. `_renderStep3` içinde `leftHtml` başına `metricAwareHtml` blok eklenir:
   ```javascript
   const metricAwareHtml = '<div class="dsw-metric-aware" data-category="metric-aware">' +
       '<h5 class="dsw-table-group dsw-cat-metric-aware">✨ Metrik için uygun kolonlar</h5>' +
       '<ul class="dsw-col-catalog" data-metric-aware-list></ul>' +
       '</div>';
   ```
2. `_loadMetricAwareColumns()` helper — POST endpoint çağrısı, response → render
3. `_addReportColumn(colName, tableId)` validation:
   ```javascript
   const warn = (_state._metricAwareWarn || []).find(w => w.column_name === colName);
   if (warn) {
       _notify('⚠️ "' + cat.label + '" seçili metrik ile uyumsuz: ' + warn.reason, 'warning');
       // Devam et — yine de ekle, kullanıcı override edebilir
   }
   ```

## Acceptance

1. Step3 girişi → `_loadMetricAwareColumns()` background çağrı, kategori "yükleniyor" spinner
2. Endpoint döner → "✨ Metrik için uygun kolonlar" listesi (rationale tooltip)
3. Kullanıcı catalog'dan metric-uyumsuz bir kolon eklerse toast "⚠️ uyumsuz: ..." görünür, ekleme yine de yapılır
4. Kullanıcı metric-aware kategoriden ekleyince toast yok
5. Metric değişirse (önceki step'ten geri gelinirse) kategori yeniden fetch edilir
6. Cache hit → "(önbellek)" hint görünür

## Gate-1 Self-Review

| Kontrol | Durum |
|---------|-------|
| Spec verbatim eşleşme | ✅ Madde 5 iki sub-bölüm |
| Council üyesi atandı | ✅ ATHENA, METIS, HEBE, POSEIDON, TYCHE |
| Scope büyüklüğü | 🟡 Mixed backend + frontend — D en geniş brief |
| Restart | Backend restart + frontend bundle rebuild **ŞART** |
| Test stratejisi | TYCHE + ARES: backend endpoint unit test + frontend mock test |
| Migration | Yok (read-only endpoint) |
| Malware risk (sub-agent refusal) | Backend sub-agent malware-paranoia tetikleyebilir → ZEUS direct-apply Plan B hazır |

## Gate-2 Verification Plan

- HERMES çıktısı: backend endpoint + frontend render
- ZEUS verifies: endpoint smoke (curl), frontend build, mock data ile katmanlı test
- TYCHE+ARES: test brief ayrı dispatch (D-Test brief'i bu brief'in done'a hareketinden önce zorunlu)
- METIS: prompt review
- POSEIDON: validation kuralları audit

## Restart Notes

- Backend restart **şart** (`stop.ps1 && start.ps1`)
- Frontend bundle rebuild **şart**
- Hard reload kullanıcı

## Dispatch Stratejisi

D, en büyük ve mixed scope. Önce **küçük 3 brief (E, F, G)** ship'lensin (HERMES tek dispatch ile zincirleme), sonra D ayrı dispatch:

1. Wave-1: E + F + G — frontend-only zincir
2. Wave-2: D — backend + frontend, ayrı dispatch, malware-refusal Plan B hazır

## Dispatch

HERMES (Wave-2) — eğer sub-agent refusal olursa ZEUS direct-apply.
