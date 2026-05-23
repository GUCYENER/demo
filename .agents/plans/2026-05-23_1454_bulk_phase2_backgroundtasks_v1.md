---
plan_id: bulk_phase2_backgroundtasks
title: Bulk approve Faz 2 — BackgroundTasks + composite index (perf/scale)
created: 2026-05-23
branch: hira (v3.32.0 sprint başında yeni branch)
status: done
closed_at: 2026-05-23
last_commit: 46fabc1
version_target: v3.32.0
council_mod: 2
hebe_gate_required: false
owner_agent: HEPHAESTUS + TYCHE
trigger: v3.31.0 production'da bulk approve latency veya pool starvation sinyali alınırsa, veya 100+ tablo onayı yaygın akış olursa
predecessor: 2026-05-23_1430_bulk_enrichment_endpoints_v1.md (Faz 1 — done, last_commit 4ec2957)
closure_note: |
  Migration 043 uygulandı (composite index CONCURRENTLY + ds_schema_record_warnings RLS).
  /enrichment-approve-bulk artık fastapi.BackgroundTasks kullanıyor; response shape
  schema_record_pending (bool). Worker pool max_parallel clamp=3 korundu (pool guard).
  Failures ds_schema_record_warnings tablosuna INSERT ediliyor; ASLA raise yok.
---

## Context (Neden bu sprint?)

v3.31.0 Faz 1 bulk approve endpoint canlıda. Council Gate (4ec2957) iki maddeyi
Faz 2'ye bıraktı:

1. **HEPHAESTUS Y2** — Schema_record üretimi response'tan ÖNCE çalışıyor. 100 item ×
   OpenAI embed (≈400ms) ÷ 3 worker ≈ 13s; 10k-token batch'lerde 60s+. Nginx
   `proxy_read_timeout=60s` sınırda; büyük batch'te kullanıcı timeout görür.

2. **HEPHAESTUS Y1** — `ds_table_enrichments` üzerinde composite index
   `(source_id, id)` yok. ARES validation query `WHERE source_id=%s AND id=ANY(%s)`
   şu an PK bitmap + filter scan; 10k+ enrichment row + 100-item ANY'de
   ölçeklenebilirlik dejenere olur.

Her ikisi de current scale'de blocker değil ama Faz 2 kapsamında temizlenmeli.

## Hedef Davranış

### 1) BackgroundTasks ile post-commit schema_record async

**Şu anki akış:**
```
POST /enrichment-approve-bulk
  → SAVEPOINT loop (UPDATE)
  → conn.commit()
  → _generate_schema_records_parallel (BLOCKING - 13-60s)
  → response döner
```

**Hedef:**
```
POST /enrichment-approve-bulk
  → SAVEPOINT loop
  → conn.commit()
  → BackgroundTasks.add_task(_generate_schema_records_parallel, ...)
  → response döner (≈100-200ms)

(arka planda)
  → ThreadPool 3 worker, her biri company-RLS scoped conn
  → schema_record + embedding üretimi
  → hata varsa ds_schema_record_warnings tablosuna kaydet
     (yeni tablo, mig 036)
```

**Response shape değişikliği:**
```diff
  {
    "success": true,
    "total": 5,
    "approved": 5,
    "approved_ids": [12,13,14,27,33],
    "errors": [],
-   "schema_record_warnings": []  // sync result
+   "schema_record_pending": true,  // async
+   "schema_record_job_id": "uuid-..."  // opsiyonel: status polling
  }
```

**Frontend etkisi:**
- "Onaylandı, embedding arka planda işleniyor" toast (success)
- Warnings panel: ds_schema_record_warnings tablosundan poll edilir (opsiyonel, Faz 3)

### 2) Composite index migration

```sql
-- mig 036: ds_table_enrichments composite index
CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_ds_table_enrich_source_id_pk
    ON ds_table_enrichments (source_id, id);
```

`CONCURRENTLY` — production'da downtime'sız oluşturulabilsin diye.

### 3) (Opsiyonel) ds_schema_record_warnings tablosu

```sql
-- mig 036 (aynı dosya):
CREATE TABLE IF NOT EXISTS ds_schema_record_warnings (
    id BIGSERIAL PRIMARY KEY,
    enrichment_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    reason TEXT NOT NULL,          -- type(e).__name__ (sanitized)
    detail TEXT,                   -- server-side full str(e)[:500]
    created_at TIMESTAMP DEFAULT NOW(),
    acknowledged_at TIMESTAMP
);
CREATE INDEX idx_schema_warn_source ON ds_schema_record_warnings(source_id);
CREATE INDEX idx_schema_warn_company ON ds_schema_record_warnings(company_id);
-- Mig 017 stilinde company-RLS policy ekle (PERMISSIVE)
```

`acknowledged_at` — admin warning'i kapatabilsin diye.

## ARES Checklist

- [ ] BackgroundTasks içinde user_id, company_id, source_id açıkça parametre olarak
  taşınır; current_user context'i thread'e propagate edilmez (Pydantic dataclass
  veya dict snapshot)
- [ ] ds_schema_record_warnings tablosuna PERMISSIVE company-RLS policy
- [ ] Detail field sadece server-side log + admin endpoint için; client-facing
  reason hala sadece exception class adı
- [ ] BackgroundTask worker'da exception → schema_record_warnings INSERT, never
  raise (FastAPI BackgroundTask exception'ı kullanıcıya HTTP 500 dökerdi response
  zaten gönderilmiş olsa bile? — doğrula)

## TYCHE Checklist

- [ ] Async response semantics: frontend `approved_ids` üzerinden UI güncellemeli,
  `schema_record_warnings` UI'dan çıkartılmalı (artık sync değil)
- [ ] BackgroundTask çalışırken ardışık ikinci bulk approve gelirse pool exhaustion?
  → workers=3 sabitlendiği için en kötü senaryo: 2 paralel BG × 3 = 6 conn + ekstra
  active request'ler. maxconn=15 yeterli, ama dokümante et.
- [ ] Migration 036 production-safe (CONCURRENTLY, IF NOT EXISTS); rollback dosyası
  index DROP'lu
- [ ] Stale warning cleanup: 30 gün sonra `acknowledged_at` veya `created_at` eski
  warning'ler purge (housekeeping job)

## HEPHAESTUS Checklist

- [ ] CONCURRENTLY index creation alembic auto-transaction içinde çalışmaz;
  alembic için `op.execute("COMMIT"); op.execute("CREATE INDEX CONCURRENTLY ...")`
  veya manual `with op.get_context().autocommit_block()` patterni
- [ ] BackgroundTasks worker connection lifecycle — get_db_context_scoped exception-safe
- [ ] EXPLAIN ANALYZE composite index sonrası ARES query: bitmap → index-only scan'e
  geçtiğini doğrula

## Kabul Kriterleri

- [ ] Bulk approve response 100-item için <500ms (sync embed yok)
- [ ] Schema_record üretimi arka planda 100% complete (ds_schema_record_warnings
  tablosunda failed olanlar görünür)
- [ ] EXPLAIN ANALYZE composite index ile <5ms (1k row test datası)
- [ ] Pool exhaustion senaryosu (3 paralel istek): hiç connection wait yok
- [ ] Frontend "onaylandı, embedding arka planda" toast'u; warnings panel sonra

## Sprint Adımları (sıra)

1. Migration 036: composite index + ds_schema_record_warnings
2. `_generate_schema_records_parallel`'i BackgroundTasks parametresi alacak şekilde
   refactor; bulk endpoint `BackgroundTasks` dependency inject
3. ds_schema_record_warnings INSERT — exception path
4. Frontend response shape adaptasyonu (warnings sync → async)
5. (opsiyonel) Admin endpoint: `GET /api/data-sources/{source_id}/schema-warnings`
6. Council Gate (ARES + TYCHE + HEPHAESTUS)
7. README + plan closure
