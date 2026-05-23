---
plan_id: bulk_enrichment_endpoints
title: Backend bulk-approve + bulk-discover endpoints (paralel + transaction-safe)
created: 2026-05-23
branch: hira
status: pending
version_target: v3.31.0
council_mod: 2
hebe_gate_required: true
owner_agent: HEPHAESTUS + ARES + TYCHE
trigger: v3.31.0 sprint başlangıcında
---

## Context (Neden bu değişiklik?)

v3.30.1'de DS enrichment paneli "Tümünü Onayla" / "Seçilenleri Onayla" /
"Tümünü Keşfet" akışları frontend'de 5'li `_runConcurrent` pool ile tek-tek
POST atıyor. Bu geçici çözüm:

- Backend'i 5x yükleyebilir (her POST ayrı bağlantı, ayrı transaction)
- Her POST'ta tekrarlayan `check_running_job` preflight'ı var
- Browser HTTP/1.1 host limiti (~6) tıkanma yapabiliyor
- N başarılı, K başarısız durumunda kullanıcıya tutarlı tek bir mesaj
  vermek için frontend'de manuel toparlama gerekiyor
- Network sürelerinden ötürü 50+ tablo onayı kullanıcı için yavaş

Kullanıcı isteği (2026-05-23): "backend'de `/enrichment-approve-bulk`
endpoint'i ekle. paralel tasklar aç. transaction rollback şeklinde olmalı.
hata durumunda ortalık karışmasın."

## Hedef Davranış

İki yeni endpoint:
- `POST /api/data-sources/{source_id}/enrichment-approve-bulk`
- `POST /api/data-sources/{source_id}/enrich-discover-bulk` (mevcut
  `/enrich-selected` zaten partial; bu yeni isim ile semantik aynı,
  ancak `partial=False` "tümü" yolu da bu endpoint'in `object_ids=null`
  varyantı olabilir — alternatif: eski endpoint'i koruyup yalnız onay
  bulk eklenir; karar Faz 1 sonrası)

### Approve bulk — kontrat

Request:
```json
POST /api/data-sources/{source_id}/enrichment-approve-bulk
{
  "enrichment_ids": [12, 13, 14, 27],
  "stop_on_error": false,           // default false: best-effort
  "max_parallel": 5                 // server-side cap: 1..10
}
```

Response:
```json
{
  "success": true,
  "total": 4,
  "approved": 3,
  "failed": 1,
  "errors": [
    { "enrichment_id": 14, "reason": "row_locked" }
  ],
  "schema_record_warnings": [
    { "enrichment_id": 13, "reason": "embedding_provider_unreachable" }
  ]
}
```

### Discover bulk — kontrat

Request:
```json
POST /api/data-sources/{source_id}/enrich-discover-bulk
{
  "object_ids": [101, 102, 103],    // null/missing → tüm bekleyenler
  "max_parallel": 3                  // discover ağır iş, conservative
}
```

Response: fire-and-forget gibi davranır, `job_ids` döner; polling mevcut
`/enrichment-stats` üzerinden yapılır (UI değişmez).

## Transaction Stratejisi

Kullanıcı "ortalık karışmasın" dedi → **per-item savepoint** modeli.

```
BEGIN;
for enrichment_id in batch:
    SAVEPOINT sp_<id>;
    try:
        approve_enrichment(...)       # UPDATE ds_table_enrichments
        generate_schema_record(...)   # ds_learning_results + embedding
        RELEASE SAVEPOINT sp_<id>;
        results.append(success)
    except Exception as e:
        ROLLBACK TO SAVEPOINT sp_<id>;
        if stop_on_error: raise
        results.append(failure)
COMMIT;
```

Avantajlar:
- Tek connection, tek outer transaction → minimum DB overhead
- Her item kendi savepoint'inde → bir item'ın hatası diğerlerini bozmaz
- `stop_on_error=true` modunda outer rollback ile **tam temizlik**
- `stop_on_error=false` (default): partial success, başarılı olanlar
  kalıcı; başarısızlar hiç yan-etki bırakmaz

### Schema_record üretimi (ds_learning_results + embedding)

Bu adım embedding provider çağrısı içeriyor → ağ I/O. İki seçenek:

**Seçenek A (kısa yol):** schema_record üretimini transaction içinde
yap, embedding hatası warning'e düşür (ana approve commit'lenir).
Bu mevcut single-approve davranışı ile uyumlu.

**Seçenek B (önerilen):** approve commit'lenir, schema_record üretimi
**post-commit background task** (`fastapi.BackgroundTasks`) olarak
queue'lanır. Embedding gecikmesi/hatası kullanıcı response süresine
yansımaz. Ayrı bir `ds_schema_record_jobs` tablosu gerekebilir
(retry için).

Karar: Faz 1'de A, Faz 2'de B'ye geç.

## Paralellik

**Approve bulk:**
- DB-bound iş ağırlıkta (UPDATE + INSERT + embedding HTTP)
- Per-item savepoint sıralı olmak zorunda (aynı connection)
- "Paralel" sadece embedding HTTP çağrısı için anlamlı
- Çözüm: approve UPDATE'leri sıralı, schema_record üretimi
  `concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel)`
  ile embedding'leri paralel toplar, sonra tek INSERT batch'i
  → DB transaction kısa, network paralel

**Discover bulk:**
- Zaten background thread'de çalışıyor (mevcut `enrich-selected`)
- `max_parallel` her object_id için ayrı thread değil; tek BG thread
  içinde `ds_learning_service.run_partial_enrichment` zaten kolon-bazlı
  kendi paralelizasyonunu yapıyor → endpoint sadece dispatch eder

## Frontend değişiklikleri (v3.31.0 ile aynı sprint)

`ds_enrichment_module.js`:
- `bulkApprove` + `bulkApproveAll` `_runConcurrent` yerine tek POST:
  ```js
  await fetch(`/api/.../enrichment-approve-bulk`, {
      body: JSON.stringify({ enrichment_ids: ids, stop_on_error: false })
  });
  ```
- Response'taki `approved` / `failed` / `errors` ile toast'lar:
  ```
  "12 tablo onaylandı, 2 başarısız (detay konsolda)"
  ```
- `_runConcurrent` helper kalır (başka yerlerde de işine yarayabilir)
- `discoverAll` + `bulkDiscover` `enrich-discover-bulk`'a geçer (opsiyonel,
  mevcut `enrich-selected` zaten BG dispatch yaptığı için kazancı sınırlı)

## Faz / Sıra

**Faz 1 — Approve bulk (yüksek getiri):**
1. ARES: yetki kontrolü — `source_id` sahipliği, `enrichment_id`'lerin
   o source'a ait olduğu doğrulanmalı (cross-tenant attack)
2. HEPHAESTUS: endpoint + savepoint loop + per-item error toplama
3. TYCHE: testler — happy path / 1 fail / hepsi fail / stop_on_error true,
   `max_parallel` clamp, geçersiz id, cross-source id reddi
4. Frontend entegrasyon + toast mesajları
5. v3.31.0 release

**Faz 2 — Discover bulk + post-commit schema_record:**
1. `ds_schema_record_jobs` queue tablosu + worker
2. `enrich-discover-bulk` endpoint (eski `enrich-selected` deprecated)
3. Embedding retry/backoff

## Out-of-scope

- Embedding provider değişikliği (ayrı sprint)
- Approve UI'da progress bar (response < 5sn hedeflenirse gereksiz)
- Discover endpoint backward-incompat değişiklik (mevcut tüketici var)

## Tamamlama Kriteri

- 50 tablo onayı tek POST ile < 8 saniyede tamamlanır (current pool ile
  ~25-30 sn)
- 1 item başarısız olursa diğer 49'u temiz commit'lenir (savepoint testi)
- `stop_on_error=true` ile 1 fail → 0 row değişikliği (rollback testi)
- Hiçbir orphan schema_record (approve rollback'lenmiş ama
  ds_learning_results'a giriş düşmüş) bulunmaz
- ARES: cross-source enrichment_id reddi 403 döner

## Notlar

- `_runConcurrent` frontend helper'ı bu sprint'te silinmez; başka panel
  refactor'larında pattern olarak işe yarayabilir
- v3.30.1 frontend kodu bu endpoint olmadan da çalışıyor — Faz 1
  tamamlanıp deploy edilene kadar mevcut pool davranışı geçerli
- HEBE gate: yeni response yapısı i18n string ekler (errors[] reasons);
  TR/EN mapping doğrulanmalı
