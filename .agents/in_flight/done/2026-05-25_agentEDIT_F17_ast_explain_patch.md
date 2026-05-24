# F17 — AST explain/patch backend hata tanı + fix

**Tarih:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0700_v336_smoke_bugs_v1.md` (F17 bölümü)
**Council:** ARES + POSEIDON + HERMES
**Branch:** `hira`
**Restart gerekli:** Backend uvicorn restart + frontend hard-reload (Ctrl+Shift+R)

## Bağlam

F9 (generate-report) sonrası kullanıcı sonuç popup'ını açtığında console'da iki backend hata spam'i:

- **Bug 1:** `POST /api/db-smart/sessions/{uid}/explain` → 400 Bad Request. (Brief'te "GET" yazıyordu ama gerçekte frontend POST kullanıyor — `db_smart_ast_editor.js:670`.)
  - Backend mesajı: `AST geçersiz (type=select bekleniyor)`
- **Bug 2:** `POST /api/db-smart/sessions/{uid}/ast/patch` → 500 Internal Server Error.

F6 frontend toast policy 404/network için sessiz, 4xx/5xx için sadece "interaction window" içinde toast atıyor → user-visible toast yok ama console spam var.

## Root Cause Analysis

### Bug 1 — `/explain` 400

- Frontend `db_smart_ast_editor.js:_refreshExplain()` POST body: `{ ast: state.ast, dialect }`.
- `state.ast` initial mount'ta `_buildStarterAst()` çıktısıyla doluyor (`db_smart_wizard.js:1743`):
  ```js
  return { dialect, from: {...}, select: [...], filters: [], ... };
  // ⚠️ 'type: select' YOK!
  ```
- Backend `db_smart_api.py:625`:
  ```python
  if not ast or ast.get("type") != "select":
      raise HTTPException(status_code=400, detail="AST geçersiz (type=select bekleniyor).")
  ```
- AST mount tetikler `_refreshExplain` → starter AST → backend 400.

### Bug 2 — `/ast/patch` 500

- Backend `post_ast_patch` 400/404/409'u doğru maps ediyor ama:
  - `session_manager.load_session` / `update_context` DB hatası
  - `apply_vyra_user_context` failure
  - `ast_renderer.inject_rls` / `render` non-ValueError/TypeError istisnası
  - frontend'in gönderdiği op whitelist'te değil ama args mismatch yerine başka exception (örn. `reorder_order`, `modify_order_dir` → AttributeError yerine 400 dönmesi gereken yer)
  - `conn.commit()` veya RLS context hatası
- Bu path'lerin hiçbiri 5xx-friendly exception handler ile sarılmamış → FastAPI default 500 + traceback log.

Tetikleyici: F9 sonrası state'e bağlı early-mount race veya bilgi olmayan op (örn. AST editor optimistic local-apply'ı `reorder_order` gönderiyor ama backend whitelist'te yok). Bu durumda whitelist guard 400 vermeli — eğer 500 alıyorsa, ya whitelist guard'a ulaşmadan exception oluyor ya da render_preview path'inde sonradan.

### Yaklaşım

Brief'in önerdiği "A + Bug 2 exception handler" yaklaşımını uyguluyorum:

- **A (explain graceful):** AST yoksa veya `type != 'select'` ise 400 yerine 200 + `{ has_ast: false, sql: '', explain: {}, ... }` döndür. Frontend `_refreshExplain` `data.has_ast === false` ise silent skip + cost badge clear.
- **Bug 2 handler:** `/ast/patch` route'unu top-level try/except ile sar. ValueError/TypeError zaten 400 olarak yakalanıyor — generic Exception 500 dönsün ama `logger.exception` ile traceback'i log'a düşür + clean JSON body.
- Frontend `_buildStarterAst` çıktısına `type: 'select'` ekle — defansif (backend artık tolere etse de starter AST canonical olsun).

## Yapılan Değişiklikler

### Backend — `app/api/routes/db_smart_api.py`

1. `/explain` (line ~608): AST eksik/invalid ise 400 raise yerine 200 + `{has_ast: false, sql: '', dialect, explain: {}, streaming_strategy: 'direct', cached: false}`.
2. `/ast/patch` (line ~430): outer try/except — generic Exception → `logger.exception` + 500 JSON body. (HTTPException re-raise edilir.)

### Frontend — `frontend/assets/js/modules/db_smart_ast_editor.js`

1. `_refreshExplain` response handler: `data.has_ast === false` → `state.lastExplain = null` + badge clear, hata olarak işleme.

### Frontend — `frontend/assets/js/modules/db_smart_wizard.js`

1. `_buildStarterAst`: `type: 'select'` ekle (defansif canonical shape).

### Build

- `cd frontend && npm run build`

## Verification

1. `curl -X POST "http://localhost:8000/api/db-smart/sessions/XXXX/explain" -H "Content-Type: application/json" -d '{"ast":{},"dialect":"postgresql"}'` → 200 `{has_ast: false}` (eskiden 400).
2. `curl -X POST .../ast/patch -d '{"op":"INVALID","args":{}}'` → 400 (whitelist).
3. Manual: F9 Çalıştır → sonuç popup → console temiz olmalı.

## Bilinen Riskler

- **R-4:** `ast_editor.js`'in `has_ast=false` handling'i diğer flow'larda regression yaratabilir (undo/redo, history). Mitigasyon: `_refreshExplain` sadece badge'i temizler — state.ast'a dokunmaz.
- **R-2:** Backend `/explain` artık invalid AST için 400 atmıyor — manual test edenler bunu false-positive sanabilir. Response body `has_ast: false` ile açık.

## Follow-up

- **Yaklaşım B (next sprint):** F9 `generate-report` başarısından sonra SQL → AST parser çağrısı ile session AST'ı persist et. Bu, AST editor'a anlamlı state verir. Maliyet: SQL→AST parser geliştirme.
- F8b/F9 entegrasyonunda `_runGeneratedReport` sonucu session context'e SQL/AST snapshot persist edilmeli (saved_reports için zaten gerek var).

## Council Onayı

- **ARES:** explain graceful fallback security açısından no-op (sadece status code/body değişiyor, RLS path'i etkilenmiyor).
- **POSEIDON:** `_buildStarterAst` `type:'select'` eklemesi backward-compatible — sunucu zaten bu shape'i bekliyor.
- **HERMES:** Frontend has_ast=false handling silent (toast yok) → UX gürültüsüz.
