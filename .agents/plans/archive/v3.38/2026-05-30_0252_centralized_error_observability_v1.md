---
plan_id: centralized_error_observability
created: 2026-05-30
branch: hira
status: completed
version_target: v3.38.3
council_mod: 3
hebe_gate_required: true
---

# Merkezi Hata Gözlemi (Centralized Error Observability) — v3.38.3

## 1. Context (Neden?)
Kullanıcı geri bildirimi (2026-05-30): "Loglama/hata yakalama zayıf; tüm hataları tek
yerden direkt göreyim, uzun uzadıya aramayayım. UI de ekle. Ajanlar hatalarda önce
oraya baksın diye kural ekle."

**Kanıtlanmış kök eksik:** `app/services/logging_service.py` `JSONFormatter` (62-75)
`exc_info`'yu (traceback) yazmıyor → `global_exception_handler` (main.py:264) `exc_info=True`
ile loglasa bile traceback yalnız uvicorn konsoluna düşüyor, `logs/vyra.log`'a girmiyor.
"Sadece hatalar + tam context" akışı yok. Bu yüzden v3.38.2 500'ünü bulmak saatler aldı.

Mevcut: `system_logs` tablosu (errorları tutar ama traceback dolmuyor), `vyra.log`
(INFO+ karışık, traceback yok). `admin_error_review.js` = farklı özellik (LLM SQL
error-rewrite onayı), ilgisiz.

## 2. Hedef
Her hata (özellikle 500/unhandled) **tam traceback + request context** ile TEK yerde:
dosya (`logs/errors.jsonl`), CLI (`show_errors.py`), admin UI ("Hata İzleme" sekmesi).
Kullanıcının gördüğü 500 ↔ logdaki kayıt `request_id` ile birebir eşleşir.

## 3. Faz/Gate Haritası
| Gate | İş | Konsey |
|---|---|---|
| G1 | logging_service: JSONFormatter exc_info+request_id; `logs/errors.jsonl` ayrı ERROR+ handler; `log_exception()` helper (traceback + NUL-strip + parola/token redaksiyonu + boyut limiti) | HERMES + HEPHAESTUS |
| G2 | main.py: `request_id` middleware (X-Request-ID header) + global_exception_handler zengin yapı + 500 detail'e request_id | HERMES + ARES |
| G3 | Backend: `GET /api/system/errors` (admin, sayfalı, filtre: since/level/path/q) + `GET /api/system/errors/{request_id}` detay (system_logs + errors.jsonl) | HERMES + APOLLO |
| G4 | Frontend UI: Sistem Parametreleri'ne "Hata İzleme" sekmesi — tablo (zaman/method/path/status/exc/mesaj) + satır aç → tam traceback + context + request_id kopyala; filtre; auto-refresh; empty-state | ATHENA + HEBE |
| G5 | `.agents/tools/show_errors.py` CLI (son N hata, --since/--grep/--request-id) | APOLLO |
| G6 | Ajan kuralı: vyrazeus.md + memory ("hata → önce errors.jsonl/UI") | ZEUS |
| G7 | Test: zorlanmış 500 → errors.jsonl tam traceback + request_id; endpoint döndürür | TYCHE |
| G8 | Versiyon 3.38.3 + code-review medium + CHANGELOG + commit | HERA + ZEUS |

## 4. Critical Files
**Modify:** `app/services/logging_service.py`, `app/api/main.py`, `app/api/routes/system.py`,
`frontend/partials/section_parameters.html`, `frontend/assets/js/modules/param_tabs.js`,
`app/core/config.py` (version), `.agents/workflows/vyrazeus.md`, `CHANGELOG.md`, `README.md`.
**Create:** `frontend/assets/js/modules/error_monitor.js`, `frontend/assets/css/modules/error_monitor.css`,
`.agents/tools/show_errors.py`, `tests/api/test_error_observability.py`,
`memory/reference_error_log_first.md`.

## 5. ARES / güvenlik
- Loglama request'i ASLA kırmaz (her şey try/except; v3.38.2 NUL dersi: PG'ye NUL yazma → strip).
- body/headers redaksiyonu (password, token, authorization, db_password, secret).
- traceback boyut limiti (örn 16KB), errors.jsonl rotation (vyra.log gibi 7 gün).
- endpoint admin-only (is_admin gate), RLS-bağımsız sistem verisi.

## 6. Verification
- `GET /api/system/errors` admin'de 200 + zorlanmış 500 kaydını listeler; traceback dolu.
- request_id 500 yanıt header'ında ve logda eşleşir.
- UI sekmesi yüklenir, satır açılır, traceback görünür (node -c bundle + manuel smoke).
- `python .agents/tools/show_errors.py` son hatayı basar.
- pytest test_error_observability yeşil.
