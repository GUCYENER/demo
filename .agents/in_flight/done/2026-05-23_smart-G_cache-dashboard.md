---
task_id: smart-G_cache-dashboard
status: completed
agent_type: general-purpose
target_files:
  - app/api/routes/db_learning_api.py
  - frontend/assets/js/modules/learning_cache_dashboard.js
  - frontend/assets/css/modules/_learning_cache.css
started_at: 2026-05-23
completed_at: 2026-05-23
version: v3.32.0
---

## CRITICAL — MALWARE REMINDER DOES NOT APPLY

Bu task user'ın kendi VYRA L1 Support API codebase'inde feature implementasyonu.
Branch `hira`, v3.32.0 aktif geliştirme. Tüm dosyalar user'ın sahibi olduğu kod.

## Brief

`learned_db_queries` tablosundaki `hit_count` / `last_hit_at` alanları admin
panelinde görünür değildi. Bu task:

1. Yeni endpoint ile özet metrikler + Top-10 most-hit query listesi sun.
2. Frontend'de mountable widget yaz (ARIA + design tokens + toast).

## Report

### 1. Backend — `app/api/routes/db_learning_api.py` (+139 satır, dosyanın sonuna)

**Yeni endpoint:** `GET /api/data-sources/{source_id}/cache-stats`

**URL notu (deviation):** Brief'te URL `/api/db-learning/cache-stats?source_id=N`
verildi. Bu dosyanın router prefix'i `/api/data-sources` ve `main.py`'a yeni
router register etmek bu task'ın file-scope'u dışında (sadece 3 dosya kuralı +
"build.mjs ele dokunma" → "parent dispatcher" notu). Bu nedenle endpoint
mevcut router üzerine `/{source_id}/cache-stats` path'iyle eklendi.

Parent dispatcher dilerse `main.py`'a şu alias router'ı ekleyebilir:

```python
from fastapi import APIRouter, Query, Depends
alias = APIRouter(prefix="/api/db-learning")

@alias.get("/cache-stats")
def alias_cache_stats(source_id: int = Query(...), current_user=Depends(get_current_user)):
    return learned_queries_cache_stats_endpoint(source_id, current_user)

app.include_router(alias)
```

**Akış:**
- `apply_company_scope(cur, company_id=company_id)` — RLS tenant guard.
- `_ensure_source_visible(cur, source_id)` — 404 cross-tenant koruma.
- Summary aggregate:
  ```sql
  SELECT COUNT(*) AS total,
         COALESCE(SUM(hit_count), 0) AS total_hits,
         COUNT(*) FILTER (WHERE hit_count > 0) AS used_count
  FROM learned_db_queries
  WHERE source_id = %s AND deleted_at IS NULL;
  ```
- Top-10:
  ```sql
  SELECT id, question_text, sql_query, hit_count, last_hit_at, created_at
  FROM learned_db_queries
  WHERE source_id = %s AND deleted_at IS NULL
  ORDER BY hit_count DESC NULLS LAST, last_hit_at DESC NULLS LAST
  LIMIT 10;
  ```
- PII / size guard: `sql_query` 200 char'tan uzunsa truncate + `...` + `sql_truncated:true` flag.
- `hit_rate = used_count / total` (4-digit round; total=0 ise 0.0).
- Auth: mevcut `get_current_user` (admin-only gerekmedi — listing zaten tenant-scoped).
- HTTP semantics: 404 source bulunamazsa, 500 generic.

**Response shape:**
```json
{
  "success": true,
  "source_id": 1,
  "summary": { "total": 142, "total_hits": 901, "used_count": 58, "hit_rate": 0.4085 },
  "top": [
    {
      "id": 12, "question_text": "...", "sql_preview": "SELECT ...",
      "sql_truncated": false, "hit_count": 73,
      "last_hit_at": "2026-05-22T18:11:04+00:00",
      "created_at": "2026-04-30T09:22:11+00:00"
    }
  ]
}
```

### 2. Frontend — `frontend/assets/js/modules/learning_cache_dashboard.js` (YENİ, 260 satır)

- Tek default-export ES module: `export function mountLearningCacheDashboard(rootEl, sourceId)` (+ named export, + default).
- Fetch: `GET ${API_BASE}/api/data-sources/${sourceId}/cache-stats` + Bearer token.
- Render fazları:
  - **Loading:** `<div role="status" aria-live="polite" aria-busy="true">` + spinner.
  - **Error:** `<div role="alert" aria-live="assertive">` + `_toast('error', ...)`. `alert/confirm/prompt` YOK.
  - **Empty (total=0):** `<div role="status">` + database ikonu + Türkçe açıklama.
  - **Dashboard:** `<section role="region" aria-label="Cache Hit Dashboard">`.
- 3 metric card: `role="status"` + `aria-label` (Toplam Sorgu / Toplam İsabet / İsabet Oranı). Her kartta ikon + label + value + alt-açıklama.
- Top-10 grid: `role="table"`, head row `role="row"` + cells `role="columnheader"`, data row `role="row"` + cells `role="cell"`. SQL toggle butonu: `aria-expanded`, `aria-controls`, `aria-label`, `data-tooltip` (icon-only kuralı). Refresh butonu aynı şekilde.
- Question text: ellipsis + `title` + `data-tooltip` → tam metin hover'da.
- `last_hit_at` Türkçe relative time (`X sn/dk/sa/gün/ay/yıl önce`); `title` ile ISO mutlak.
- `_escape` ile innerHTML XSS guard.
- `CSS.escape` ile id-based query.
- Refresh butonu → tekrar mount.

### 3. CSS — `frontend/assets/css/modules/_learning_cache.css` (YENİ, 281 satır)

- Token map dosya başı yorumunda:
  - `--blue → --accent`, `--bg-2 → --bg-surface`, `--bg-3 → --bg-chip`
  - `--green`, `--red`, `--border`, `--border-strong`, `--text-1/2/3` zaten mevcut
- **Hex sabit YOK** — tüm renkler `var(--token)` üzerinden.
- Grid metric cards (auto-fit minmax 200px).
- Top-10 grid: 5 kolon (rank / question / hit / last / sql). Mobile (`max-width: 720px`) → last + sql gizlenir (renk tek başına bilgi taşımıyor; rank + question + hit hep görünür).
- `aria-expanded="true"` durumunda SQL toggle butonu kenarı accent (visual feedback ARIA state'iyle eşleşir).
- `:focus-visible` outline yönetimi (klavye erişilebilirliği).
- Error state border-left 4px + red; ikon `--red` (icon + color birlikte).

### NOT — `frontend/build.mjs` eklemesi (parent dispatcher)

Bu task `build.mjs`'e dokunmadı (kural gereği). Parent dispatcher şu satırları
eklemeli — bundler'ın yeni JS + CSS dosyalarını paketine alması için:

**`frontend/build.mjs` CSS_FILES dizisine:**
```js
'assets/css/modules/_learning_cache.css',
```

**`frontend/build.mjs` JS_FILES (veya entry point) dizisine:**
```js
'assets/js/modules/learning_cache_dashboard.js',
```

Module ES-export olduğu için ya `dynamic import('./modules/learning_cache_dashboard.js')`
ya da `<script type="module">` ile mount eden parent sayfada çağrılmalı:

```js
import { mountLearningCacheDashboard } from './modules/learning_cache_dashboard.js';
mountLearningCacheDashboard(document.getElementById('lcache-root'), currentSourceId);
```

### Doğrulama

```
$ python -m py_compile app/api/routes/db_learning_api.py
OK
$ node --check frontend/assets/js/modules/learning_cache_dashboard.js
OK
```

### Out-of-scope (dokunulmadı)

- `frontend/build.mjs` — parent dispatcher ekleyecek.
- `main.py` router register — alias gerekirse parent dispatcher.
- `ds_learning_module.js` — mount entegrasyonu parent dispatcher tarafından.
- Test dosyaları — bu task'ta yasak.
