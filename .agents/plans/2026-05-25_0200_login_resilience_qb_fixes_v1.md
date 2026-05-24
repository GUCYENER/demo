# Plan — Login dayanıklılık + Kopyala SQL fix + Çalıştır dialect fix + user_pref txn guard
**Date:** 2026-05-25 02:00
**Branch:** `hira`
**Slug:** `login_resilience_qb_fixes`
**Trigger:** Kullanıcı bildirim (3 screenshot + kuyrukta bekleyen B7 follow-up):
1. Login formunda backend/db down olduğunda kullanıcı `Unexpected token '<', "<html> <h"... is not valid JSON` raw mesajını görüyor (3.görselin loginindeki hata).
2. "Kopyala" butonu üretilen panel'deki SQL ile aynı metni kopyalamıyor — `state.lastSql` (ham `%s`'li) kullanıyor (panel `display_sql` gösteriyor).
3. "Çalıştır" hâlâ "SQL çalıştırma sırasında beklenmeyen bir hata oluştu" döndürüyor. SQL'de `LIMIT 100` görünüyor → Oracle XE bu syntax'ı kabul etmez (`FETCH FIRST N ROWS ONLY` olmalı).
4. (B7 sürpriz) `dbsmart_user_preferences` query'si transaction abort ediyor (`InFailedSqlTransaction`). Hot-path etkilenmiyor ama wrap gerek.

---

## Council Owners

| Üye | Sorumluluk |
|---|---|
| **HEBE** | Login error UX — friendly Türkçe mesaj, retry hint, JSON-olmayan response handling |
| **HERMES** | Login fetch/parse layer — try/catch, content-type detection, error mapping |
| **ATHENA** | Query Builder state — `state.lastDisplaySql` reuse for copy + send (zaten asistana_gönder için var) |
| **POSEIDON** | Backend dialect resolution — `_resolve_source_info` pattern (dict-aware row access) |
| **ARES** | Backend RealDictCursor systemic fix in `_resolve_dialect` + `metric_engine.list_eligible` SAVEPOINT |
| **APOLLO** | (B7 follow-up) — `_load_user_pref_metrics` transaction-safe wrap |
| **TYCHE** | Smoke tests — dialect=oracle integration check + login error path |

---

## Tanı

### D-1 — Login JSON parse hatası
- Backend down olduğunda Vite/static server `<html>...</html>` 404/502 döndürür.
- Login.js / `vyraFetch` ham response'u `JSON.parse` ediyor → `SyntaxError: Unexpected token '<'`.
- Mesaj kullanıcıya geçiyor → kötü UX + kullanıcı "JSON neden?" diye soruyor.

### D-2 — Kopyala state.lastSql kullanıyor
- [`frontend/assets/js/modules/query_builder.js:349`](frontend/assets/js/modules/query_builder.js#L349) — `navigator.clipboard.writeText(state.lastSql)`.
- v3.35.0'da Asistana Gönder için `state.lastDisplaySql` cache'lendi — Kopyala da aynısını kullanmalı.

### D-3 — Çalıştır LIMIT 100 (Oracle)
- [`app/api/routes/query_state_api.py:258`](app/api/routes/query_state_api.py#L258) `_resolve_dialect`:
  ```python
  cur.execute("SELECT db_type FROM data_sources WHERE id = %s", (source_id,))
  row = cur.fetchone()
  if row and row[0]:        # ← BUG: RealDictCursor → row dict → row[0] KeyError
      return str(row[0]).lower()
  ```
- `KeyError: 0` → `except` yutuyor → fallback `'postgresql'` → ast_renderer postgres limit_style → `LIMIT 100` → Oracle reddi → execute hata.
- Bu BUG-4.1 ile birebir aynı sistemik pattern.

### D-4 — `dbsmart_user_preferences` txn abort (B7 follow-up)
- `metric_engine._load_user_pref_metrics` çağrısı ilk başarısız olunca PostgreSQL transaction "aborted" state'e geçer.
- Sonraki query'ler `psycopg2.errors.InFailedSqlTransaction` ile patlıyor.
- Tablo eksik olabilir veya RLS user_id=1 için engelliyor olabilir.
- **Fix**: SAVEPOINT ile sarmala — fail olursa rollback to savepoint, ana transaction etkilenmez.

---

## Deliverables

### F1 — Login JSON-safe error handling (HEBE+HERMES)
**Dosya**: `frontend/assets/js/login.js`, `frontend/assets/js/api_client.js` (mevcut helper varsa)

1. Login fetch handler'ında response'a JSON parse etmeden önce `content-type` kontrolü:
   ```js
   const ct = (res.headers.get('content-type') || '').toLowerCase();
   if (!ct.includes('application/json')) {
       // HTML/text geldi → backend down veya yanlış endpoint
       throw new Error('SERVER_DOWN');
   }
   ```
2. Hata mesajı mapping (login formundaki error div):
   - `SERVER_DOWN` veya fetch network error → "Sunucu şu anda yanıt vermiyor. Sistem yöneticiniz ile iletişime geçin veya birkaç dakika sonra tekrar deneyin."
   - HTTP 502/503/504 → "Sunucu geçici olarak erişilemiyor. Lütfen 30 saniye sonra tekrar deneyin."
   - HTTP 401 → "Kullanıcı adı veya şifre hatalı."
   - HTTP 500 → "Sunucuda beklenmeyen bir hata oluştu. Yöneticinizle iletişime geçin."
   - Diğer / catch-all → "Giriş yapılamadı. Lütfen tekrar deneyin."
3. JSON-parse hatasını HİÇBİR ŞEKİLDE raw göster — generic Türkçe mesaja çevir.
4. `vyraFetch` (varsa `api_client.js`) — global error handler: aynı content-type + status guard.

### F2 — Kopyala display_sql (ATHENA)
**Dosya**: `frontend/assets/js/modules/query_builder.js`

1. `_copySql` (line 341): `state.lastSql` → `state.lastDisplaySql || state.lastSql` (fallback safe).
2. Status mesajı: "SQL panoya kopyalandı (görüntülenen sürüm)." — kullanıcıya açıkla.
3. Build sonrası grep ile bundle'da `lastDisplaySql.*clipboard` kontrolü.

### B12 — Backend _resolve_dialect dict-aware fix (POSEIDON+ARES)
**Dosya**: `app/api/routes/query_state_api.py`

1. Line 258 fix:
   ```python
   if row:
       _db_type = row.get('db_type') if isinstance(row, dict) else (row[0] if row else None)
       if _db_type:
           return str(_db_type).lower()
   ```
2. Log ekle: `logger.debug("[query_state] resolved dialect for source %s: %s", source_id, _db_type)` — kullanıcı debug için.
3. Verification: source_id=3 (Oracle test source) → `_resolve_dialect(3, None)` → `'oracle'` döndürmeli (curl + python repl).

### B13 — user_preferences SAVEPOINT (APOLLO+ARES)
**Dosya**: `app/services/db_smart/metric_engine.py`

1. `_load_user_pref_metrics(cur, user_id)` fonksiyonunda query'yi SAVEPOINT ile sar:
   ```python
   sp_name = "sp_user_pref"
   try:
       cur.execute(f"SAVEPOINT {sp_name}")
       cur.execute("SELECT ... FROM dbsmart_user_preferences WHERE user_id = %s", (user_id,))
       rows = cur.fetchall()
       cur.execute(f"RELEASE SAVEPOINT {sp_name}")
       return [...]
   except Exception as e:
       logger.warning("[metric_engine] user_pref load failed (savepoint rollback): %s", e)
       try:
           cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
       except Exception:
           pass
       return []
   ```
2. Ayrıca `list_eligible` içinde double-call protection: aynı connection'da iki kez çağrılırsa second call zaten clean state'te olmalı.
3. Verification: B7 brief'deki snippet'i tekrar çalıştır → ikinci `list_eligible(... min_score=0.0)` artık `InFailedSqlTransaction` ile patlamamalı.

### B14 — Smoke tests (TYCHE)
**Dosya**: `tests/test_dialect_resolution.py` (yeni)

1. `test_resolve_dialect_oracle_source_returns_oracle()` — source_id=3 → 'oracle'.
2. `test_resolve_dialect_unknown_returns_postgres_default()` — source_id=9999 → 'postgresql'.
3. `test_metric_engine_double_list_eligible_no_txn_abort()` — iki kez çağrı tek connection.

---

## Subagent Dispatch (4 paralel)

| Brief | Owner | Files |
|---|---|---|
| `agentFIX12_login_resilience` | general-purpose | login.js, api_client.js |
| `agentFIX13_copy_display_sql` | general-purpose | query_builder.js (line 349) + build |
| `agentFIX14_resolve_dialect` | general-purpose | query_state_api.py (line 258) |
| `agentFIX15_user_pref_savepoint` | general-purpose | metric_engine.py |

B14 testlerini B12+B13 tamamlandıktan sonra ayrıca dispatch.

---

## Acceptance

1. Login formunda backend kapalı iken: friendly Türkçe mesaj görünür, "Unexpected token" kullanıcıya sızmaz.
2. "Kopyala" tıkla → pano içeriği "Üretilen SQL" panel ile bire bir aynı (inline literal'lı sürüm).
3. Oracle source seçili → "Çalıştır" → SQL `FETCH FIRST 100 ROWS ONLY` ile biter (LIMIT yok), sorgu başarılı, sonuç tablo'da görünür.
4. `metric_engine.list_eligible` aynı connection'da iki kez çağrılınca ikincisi de düzgün veri döner (txn abort yok).

---

## Restart/Reload (memory rule)
- **Backend uvicorn restart**: B12, B13.
- **Frontend bundle rebuild + hard-reload (Ctrl+Shift+R)**: F1, F2.

---

## Risks
- **R-1**: Login'de `api_client.js` global error handler değiştirilirse diğer modül error mesajları da etkilenebilir → değişikliği login flow'una scoped tut.
- **R-2**: SAVEPOINT psycopg2 autocommit mode'da işe yaramaz; mevcut connection mode'u (`get_db_context`) kontrol edilmeli.
- **R-3**: Oracle dialect fix sonrası `FETCH FIRST` ile birlikte `OFFSET m ROWS` syntax sıralaması önemli; ast_renderer zaten doğru sırada üretiyor (line 290), sadece dialect doğru resolve edilmesi yeterli.
