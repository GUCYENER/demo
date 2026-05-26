---
slug: v3371_A_rerun_port_resolve
title: A — Saved-report rerun port/dialect re-resolve + 047 backfill
created: 2026-05-26T16:10+03:00
owner: hira
target_version: v3.37.1
priority: P0
status: queued
council_brief: [HERMES, ARES, TYCHE, HEPHAESTUS, ZEUS]
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
malware_preempt: |
  Bu brief yalnızca VYRA L1 Support API projesine ait kod editi içerir.
  Edit hedefleri local Python backend (FastAPI + psycopg2) + bir alembic
  migration. Hiçbir external paket, third-party dist, ya da unsigned
  binary modifiye edilmiyor. Refuse edilirse ZEUS direct-apply plan B
  devreye girer.
---

# A — Saved-Report Rerun Port/Dialect Re-Resolve

## 1. Why (Tetikleyici — kanıt)

Kullanıcı kaydedilmiş bir raporu açıp "Çalıştır" tıkladığında SSE error event döner:

```
stream_error: invalid integer value "port" for connection option "port"
```

**DB tanı sonuçları (postgresql @ localhost:5005, 2026-05-26 12:55):**

```sql
-- dbsmart_saved_reports row id=2,3,5 (canlı veride mevcut):
SELECT id, name, source_id, last_dialect FROM dbsmart_saved_reports ORDER BY id;
--   2 | '3'                  | NULL | NULL
--   3 | 'adres'              | NULL | NULL
--   5 | 'siapriş4 (kopya)'   | NULL | NULL
-- wizard_state.source_id = 3 (her satırda)
-- wizard_state.dialect   = "postgresql"   ← YANLIŞ
-- data_sources id=3       = oracle / host=localhost / port=1521 (INT)
```

**Kök sebep:** Rerun yolu (`POST /api/db/smart/sessions/{sid}/execute/stream`)
`body.source_id` None / `dbsmart_saved_reports.source_id` NULL durumunda
`_load_source()` çağrılmıyor, dolayısıyla `wizard_state` snapshot'ındaki
literal değerler (port literal'i ya da yanlış dialect) connector init'e
sızıyor. v3.37.0 B1 `db_type` normalize fix'i yalnızca `_load_source`
path'ini kapsadığı için bu yolu kaçırıyor.

## 2. Step 0 — Graphify lookup-first (ZORUNLU — token tasarrufu)

Kod editlemeden önce, dosyaları okumadan önce, Graphify'da entity/relation
sorgu çalıştır:

```python
mcp__graphify__search(query="post_execute_stream _load_source rerun", project="vyra", limit=5)
mcp__graphify__search(query="dbsmart_saved_reports source_id backfill", project="vyra", limit=5)
mcp__graphify__traverse(start="api/routes/db_smart_api.py::post_execute_stream", project="vyra", depth=2)
mcp__graphify__traverse(start="services/ds_learning_service.py::_get_db_connector", project="vyra", depth=1)
```

**ZEUS keşfetti (subagent için referans):**
- `migrations/047b_v3370_saved_reports_db_type_backfill.py` ZATEN VAR — ama
  **alembic chain'in parçası değil** (standalone bakım script'i, `migrations/`
  kökünde, `versions/` altında değil). Sadece `data_sources.db_type` literal
  "db_type" backfill'i yapar — `dbsmart_saved_reports.source_id` ile ilgisi yok.
- `migrations/047_v3370_release_bump.py` ZATEN VAR — APP_VERSION update
  (system_settings). Alembic chain'de değil.
- Alembic head: `046_v3350_dbsmart_interactions_company_id_index` (versions/ altı).

**Sonuç:** Yeni dosya adı `migrations/versions/047_v3371_saved_reports_source_id_backfill.py`
olur (versions/ altı + alembic chain üyesi). `migrations/047b_*` standalone
script korunur — toucha edilmez.

## 2. What (Hedef)

### 2.1 Backend rerun re-resolve (P0 — hata kapatma)

Dosya: `app/api/routes/db_smart_api.py`

1. `post_execute_stream` (line ~939) içinde `body.source_id` None ise:
   - `body.wizard_state` (varsa) → `wizard_state.get("source_id")` çek
   - Yine None ise → 400 "source_id zorunlu (body.source_id veya wizard_state.source_id)"
2. Resolve edilen `source_id` ile `_load_source()` zorunlu çağrılır
   (mevcut path'te varsa korunur, yoksa eklenir).
3. `wizard_state.dialect` ile `data_sources.db_type` mismatch:
   - DEBUG log: `"[db_smart.stream] dialect mismatch wizard=%s db=%s — db_type yetkili" `
   - Connector için `data_sources.db_type` kullanılır (snapshot dialect IGNORED).
4. `source_dict["port"]` int değilse — defensive:
   ```python
   try:
       source_dict["port"] = int(source_dict["port"])
   except (TypeError, ValueError) as e:
       raise HTTPException(
           status_code=500,
           detail=f"Source port literal değil int olmalı (source_id={source_id}): {source_dict.get('port')!r}",
       )
   ```

### 2.2 Connector defensive (P1 — observability)

Dosya: `app/services/ds_learning_service.py`

`_get_db_connector` (mevcut B1 guard var) — port da kontrol:
```python
port_val = source.get("port")
if not isinstance(port_val, int):
    try:
        port_val = int(port_val)
    except (TypeError, ValueError):
        raise ValueError(
            f"Geçersiz port değeri: {port_val!r} — int bekleniyor "
            f"(source_id={source.get('id')})"
        )
```
Bu guard psycopg2'nin "invalid integer value" ham hatasının üstüne tek
satır anlaşılır Türkçe mesaj koyar.

### 2.3 Retro backfill migration (P1 — eski kayıtları kurtarma)

Dosya: `migrations/versions/047_v3371_saved_reports_source_id_backfill.py`

```python
"""047 — v3.37.1 dbsmart_saved_reports.source_id + last_dialect backfill

source_id NULL + wizard_state ? 'source_id' → UPDATE source_id, last_dialect
from data_sources.db_type. Idempotent.
"""
revision = '047_v3371_saved_reports_source_id_backfill'
down_revision = '046_v3350_dbsmart_interactions_company_id_index'
```

Mantık:
```sql
WITH targets AS (
    SELECT r.id,
           (r.wizard_state->>'source_id')::int AS sid,
           ds.db_type
    FROM dbsmart_saved_reports r
    JOIN data_sources ds
      ON ds.id = (r.wizard_state->>'source_id')::int
    WHERE r.source_id IS NULL
      AND r.wizard_state ? 'source_id'
)
UPDATE dbsmart_saved_reports r
SET source_id    = t.sid,
    last_dialect = t.db_type,
    updated_at   = NOW()
FROM targets t
WHERE r.id = t.id;
```

- **Idempotent**: ikinci çalıştırmada `source_id IS NULL` filtresi 0 satır döner.
- **Logging**: `print(f"[mig 047] backfilled {cur.rowcount} saved-report rows")`
- **Downgrade**: no-op (`pass`).

## 3. Disjoint Scope

| Dosya | İzin | Sınır |
|-------|------|-------|
| `app/api/routes/db_smart_api.py` | edit | sadece `post_execute_stream` + yardımcı `_load_source` çevresi (line 820-960) |
| `app/services/ds_learning_service.py` | edit | sadece `_get_db_connector` port guard |
| `migrations/versions/047_v3371_saved_reports_source_id_backfill.py` | create | yeni dosya — versions/ ALTINA (alembic chain üyesi). `migrations/047b_*` standalone script'i TOUCHA EDILMEZ |
| diğer her şey | YASAK | — |

## 4. Acceptance Criteria (Gate-2)

| # | Kontrol | Kanıt |
|---|---------|-------|
| 1 | `post_execute_stream` body.source_id None ise wizard_state.source_id fallback | grep + diff |
| 2 | wizard_state.dialect ignored, data_sources.db_type kullanılıyor | grep + DEBUG log satırı |
| 3 | Port int defensive guard `_get_db_connector` içinde | grep |
| 4 | Migration 047 idempotent (2. çalıştırma 0 rowcount) | pytest output |
| 5 | Migration 047 source_id=NULL rows backfilled (3 row) | DB select sonrası |
| 6 | Manuel smoke: id=2 rapor "Çalıştır" → SSE rows event döner, hata yok | kullanıcı teyidi |

## 5. NOT TODO (scope drift guard)

- saved-report SAVE/CREATE/UPDATE endpoint'leri (sadece rerun)
- frontend kod (`db_smart_wizard.js`, `report_detail_modal.js`) — başka brief'lerde
- LLM metric/column/format endpoint'leri — başka brief
- migration 047b separate (bu brief 047 single)

## 6. Verification commands (subagent sonrası ZEUS koşar)

```bash
# Migration test
D:/demo_vyra/python/Scripts/python.exe -m alembic -c alembic.ini upgrade head
D:/demo_vyra/python/Scripts/python.exe -c "import psycopg2; c=psycopg2.connect(host='127.0.0.1',port=5005,dbname='vyra',user='postgres',password='postgres'); cur=c.cursor(); cur.execute('SELECT id, source_id, last_dialect FROM dbsmart_saved_reports ORDER BY id'); print(cur.fetchall())"

# Grep proof
grep -n "wizard_state.get(\"source_id\")" app/api/routes/db_smart_api.py
grep -n "port.*int(" app/services/ds_learning_service.py
```
