---
ajan: I (smart)
topic: Error Pattern Approval UI (MVP)
release: v3.32.0
status: done
created_at: 2026-05-23
updated_at: 2026-05-23
target_files:
  - app/api/routes/db_learning_api.py   # admin.py mevcut değildi → fallback
  - frontend/assets/js/modules/admin_error_review.js  # YENİ
  - migrations/versions/040_v3320_error_pattern_review.py  # YENİ
out_of_scope_touched: []
---

# Ajan-I — Error Pattern Approval UI MVP

## Brief Özeti
`self_heal_node` LLM rewrite kararlarını `learned_query_failures` tablosuna
yazıyor (record_failure + mark_corrected). Admin'in son 50 rewrite'ı görüp
tek tek onaylayabileceği/reddedebileceği basit panel.

## Keşif Bulguları
- **Tablo:** `learned_query_failures` (migration 028_v3290_query_failure_log).
  Kolonlar: id, source_id, company_id, question, failed_sql, corrected_sql,
  error_class, error_message, recurrence_count, admin_approved, pattern_hint,
  last_seen_at, created_at.
- **Yazım yeri:** `app/services/pipeline/nodes/self_heal.py` →
  `error_pattern_learner.record_failure()` ON CONFLICT UPSERT.
- **`admin_approved` BOOL mevcut**, ama "pending/approved/rejected" üçlüsü ve
  reviewer kimliği yok. Yeni kolonlar gerekli.
- **Mevcut /failure-queue endpoint'i** (db_learning_api.py:1262) per-source
  ve recurrence>=3 filtreliyor; bu MVP'nin amacı farklı (cross-source son 50
  rewrite review).

## Yapılanlar

### 1) Migration — `040_v3320_error_pattern_review.py`
- `down_revision = "038_v3320_fk_position"` (alembic heads check'inde tek head).
- Eklenen kolonlar:
  - `review_status TEXT NOT NULL DEFAULT 'pending'` (CHECK: pending|approved|rejected)
  - `reviewed_by INTEGER NULL REFERENCES users(id)`
  - `reviewed_at TIMESTAMPTZ NULL`
  - `review_note TEXT NULL`
- Backfill: mevcut `admin_approved=TRUE` → `review_status='approved'`.
- Partial index: `idx_lqf_review_status` WHERE status='pending'.

### 2) Backend — `app/api/routes/db_learning_api.py` (append)
admin.py mevcut değildi → brief'in fallback maddesi gereği db_learning_api.py'a
eklendi. Top-level import: `get_current_admin` eklendi.

Endpoint'ler (prefix `/api/data-sources`):
- `GET  /admin/error-rewrites?status=<pending|approved|rejected|all>&limit=50`
  - `corrected_sql IS NOT NULL` filtre (yalnızca gerçek rewrite kayıtları).
  - apply_company_scope + get_current_admin.
  - Response: `{items: [{id, source_id, question, error_class, error_message,
    original_sql, rewritten_sql, recurrence_count, review_status, reviewed_by,
    reviewed_at, review_note, created_at, last_seen_at}], count, status_filter, limit}`.
- `POST /admin/error-rewrites/{rewrite_id}/review`
  - Body schema: `ErrorRewriteReviewRequest{decision: 'approved'|'rejected', note?: str(<=2048)}`.
  - `approved` → review_status=approved + admin_approved=TRUE + reviewed_by/at/note.
  - `rejected` → review_status=rejected + admin_approved=FALSE + corrected_sql=NULL +
    pattern_hint=NULL + reviewed_by/at/note (LLM hint olarak verilmez).
  - Audit log: `logging_service.log_system_event("INFO", ...)` best-effort.

### 3) Frontend — `frontend/assets/js/modules/admin_error_review.js`
- ES module, public API: `export function mountErrorReview(rootEl): Promise<void>`.
- Idempotent: aynı root'a tekrar mount edilirse listener çoğalmaz (MOUNT_FLAG).
- Skeleton: status select + Yenile butonu + count + loading/error/empty + ul#aerList.
- Her satır: error_class chip, status chip, #id, source, created_at,
  question, error_message, `<details>Orijinal SQL</details>`,
  `<details>Rewrite SQL</details>`, action butonları.
- Aksiyonlar (yalnız pending satırlarda):
  - **Onayla** (`✓`) → POST decision=approved, note=null (confirm dialog YOK, HEBE).
  - **Reddet** (`✗`) → inline note textarea aç → Reddet (POST decision=rejected).
- HEBE uyum: `alert/confirm/prompt YOK`, ARIA label tüm butonlarda, hex yok
  (sınıflar: `aer-*` design token kullanıcısı), `window.showToast` proxy,
  XSS-safe `esc()`.
- Auth: `localStorage.access_token` → Bearer header (projedeki kalıp).

## Doğrulama
```
python -m py_compile app/api/routes/db_learning_api.py
python -m py_compile migrations/versions/040_v3320_error_pattern_review.py
node --check frontend/assets/js/modules/admin_error_review.js
```
Üçü de hatasız geçti.

## Branched-head Uyarısı
Alembic heads sonradan **iki dallı** görünüyor:
- `040_v3320_error_pattern_review`  (bu ajan — down_revision=038)
- `041_v3320_fernet_key_version`    (Ajan-J — down_revision=038)

İkisi de aynı 038 head'inden ayrılmış (paralel ajan çalışması). MVP brief'i
dosya scope'unu 3 ile sınırladığı için merge migration burada üretilmedi;
integration adımında bir merge revision (`alembic revision -m "merge I+J" --head=040,041`)
gerekecek.

## Mount Edilmesi (parent/build)
- `frontend/build.mjs` bu yeni modülü PARENT (coordinator) ajan ekleyecek.
- Admin panelden çağırım örneği:
  ```js
  import { mountErrorReview } from "./modules/admin_error_review.js";
  mountErrorReview(document.querySelector("#adminErrorReviewRoot"));
  ```
- CSS sınıfları (`aer-*`) için design token mapping de PARENT'ın sorumluluğunda.

## Out-of-Scope (Bilinçli Bırakılanlar)
- Test dosyaları (brief gereği yazılmadı).
- Pagination (MVP: son 50).
- CSV export / bulk approve.
- `admin.py` dosyası (mevcut değildi → fallback kullanıldı).
- `frontend/build.mjs` güncellemesi (PARENT'a bırakıldı).
- Alembic merge migration (iki head birleştirme — integration adımı).

## Report
- Tabloya kolon eklendi: `learned_query_failures` ←
  `review_status, reviewed_by, reviewed_at, review_note` (+ partial index).
- Endpoint'ler: `GET /api/data-sources/admin/error-rewrites`,
  `POST /api/data-sources/admin/error-rewrites/{id}/review`.
- Frontend mount API: `mountErrorReview(rootEl)` —
  `frontend/assets/js/modules/admin_error_review.js`.
