# Brief — agentEDIT8 explain 405 diagnostic + fix

**Date:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0030_metric_filter_dnd_llm_v1.md` deliverable B8
**Council:** ARES (backend route audit) + POSEIDON (frontend data path)
**Branch:** `hira`

---

## Trigger

Browser console (kullanıcı 3 screenshot):
```
apihttp://localhost:.../sessions/3c8efd275/explain:1 Failed to load resource: the server responded with a status of 405 (Method Not Allowed)
[NGSSAI] API error: Error: İstek reddedildi (405)
    at request (_temp_entry.js:1161)
```

405 sürekli görünüyor; özellikle Metrik step açıldığında yoğunlaşıyor.

---

## Diagnostic adımları

### 1. Backend route mevcut mu?
```bash
PYTHONIOENCODING=utf-8 python -c "from app.api.main import app; [print(r.path, r.methods) for r in app.routes if 'explain' in str(getattr(r,'path',''))]"
```
**Çıktı:** `/api/db-smart/sessions/{session_uid}/explain {'POST'}` ✅
- Route kayıtlı, method POST, prefix doğru.

### 2. Direkt curl POST (auth yok)
```bash
curl -i -X POST http://localhost:8002/api/db-smart/sessions/test123/explain \
     -H "Content-Type: application/json" -d '{"ast":{},"dialect":"postgresql"}'
```
**Sonuç:** `HTTP/1.1 401 Unauthorized` — `{"detail":"Kimlik doğrulama bilgisi yok (Authorization header eksik)"}` ✅
- 401 beklenen davranış (auth eksik); route POST kabul ediyor.

### 3. CORS preflight (OPTIONS)
```bash
curl -i -X OPTIONS http://localhost:8002/api/db-smart/sessions/test123/explain \
     -H "Origin: http://localhost:8002" \
     -H "Access-Control-Request-Method: POST" \
     -H "Access-Control-Request-Headers: content-type"
```
**Sonuç:** `HTTP/1.1 200 OK` + `access-control-allow-methods: GET, POST, PUT, DELETE, PATCH, OPTIONS` ✅
- CORS preflight sorunsuz; OPTIONS handler `CORSMiddleware` tarafından sağlanıyor.

### 4. GET (yanlış method) testi
```bash
curl -i -X GET http://localhost:8002/api/db-smart/sessions/test123/explain
```
**Sonuç:** `HTTP/1.1 405 Method Not Allowed` — `{"detail":"Method Not Allowed"}` 🎯
- **Bu cevap kullanıcının gördüğü hatayla birebir aynı.** Demek ki frontend bir şekilde POST yerine **GET** (veya hiç method olmayan bir varyant) gönderiyor — VEYA yanlış path'e POST gidiyor ve oradan 405 dönüyor.

---

## Kök neden — URL bozulması (çift API_BASE prefix)

### Bulgu

`frontend/assets/js/modules/db_smart_ast_editor.js:37`:
```js
var API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api/db-smart';
```
AST editor `API_BASE`'i **mutlak URL** üretiyor:
`http://localhost:8002/api/db-smart`

`frontend/assets/js/modules/db_smart_wizard.js:21`:
```js
const API_BASE = '/db-smart';
```
Wizard ise **göreceli** path kullanıyor.

Wizard mount sırasında AST editor'a kendi `_fetchJson`'unu enjekte ediyor (`db_smart_wizard.js:728`). Wizard'ın `_fetchJson` (line 122) → `window.vyraFetch(url, ...)` → `VYRA_API.request(path, opts)`.

`frontend/assets/js/api_client.js:143`:
```js
const url = `${API_BASE_URL}${path}`;
```
`API_BASE_URL` zaten `http://localhost:8002/api` (api_client.js:56). AST editor'dan gelen `path` mutlak URL içerdiği için sonuç:
```
http://localhost:8002/api + http://localhost:8002/api/db-smart/sessions/UID/explain
=
http://localhost:8002/apihttp://localhost:8002/api/db-smart/sessions/UID/explain
```

Bu tam olarak kullanıcının gördüğü "**apihttp://localhost:.../sessions/3c8efd275/explain**" pattern'i. Browser bu bozuk URL'yi resolve ederken `:` scheme delimiter gibi yorumlayıp path olarak normalize ediyor → backend'e farklı bir path ile POST yapıyor → o path GET-only bir route'a denk geliyorsa 405 dönüyor.

### Neden Metrik step'te tetikleniyor?

Plan'da yazıldığı gibi: kullanıcı önce Önizleme'ye (step 4) bir kere gitti → AST editor mount oldu → `mount()` fonksiyonu sonunda `_refreshExplain()` çağırdı (ast_editor.js:739) → bozuk URL üretildi → 405 console'a düştü. Sonra Metrik'e dönünce console'a tekrar bakınca o hatayı görüyor. Mount aslında sadece step 4'te oluyor, ama unmount sırasındaki AbortController + reply gecikmesi de aynı hatayı tekrarlayabiliyor.

Aynı bug `ast/patch` ve diğer AST editor endpoint'lerinde de var ama kullanıcı henüz drag-drop yapmadığı için tetiklenmemiş.

---

## Fix

### F1 — AST editor API_BASE göreceli yap
`frontend/assets/js/modules/db_smart_ast_editor.js:37`:
- Before: `var API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api/db-smart';`
- After: `var API_BASE = '/db-smart';  // göreceli — vyraFetch/_fetchJson API_BASE_URL'i kendisi ekler`

### F2 — sessionUid defensive guard
`frontend/assets/js/modules/db_smart_ast_editor.js:_refreshExplain` early-return:
```js
function _refreshExplain() {
    if (!state || !state.ast) return;
    var uid = state.sessionUid;
    if (!uid || typeof uid !== 'string' || uid === 'undefined' || uid === 'null') {
        return;  // session yok → request gönderme (URL ".../sessions/undefined/explain" 405'e yol açar)
    }
    ...
}
```

### F3 — Aynı bug `ast/patch` ve `_syncServerAst` için de geçerli
F1 düzeltmesi (göreceli API_BASE) tüm AST editor request'lerini düzeltir; ekstra değişiklik gerekmez.

---

## Verification (manuel)

- [ ] Hard-reload (bundle rebuild gerekiyor → `npm run build` veya elle ast_editor.js modifiye).
- [ ] Wizard aç → Step 4 (Önizleme) → console'da `apihttp://...` veya 405 hatası **olmamalı**.
- [ ] Metrik step'e git-gel → console temiz.
- [ ] Network sekmesinde `POST /api/db-smart/sessions/<uid>/explain` → 200 veya 401 (auth state'e göre), 405 değil.

---

## Notlar

- Backend tarafında değişiklik **gerekmiyor** — route mevcut ve doğru method ile kayıtlı.
- CORS preflight sorunsuz; OPTIONS handler ek gerekmiyor (CORSMiddleware sağlıyor).
- Bundle rebuild gerekecek — kullanıcıya AÇIK bildirilmeli (MEMORY: "Restart gereksinimlerini açıkça bildir").
- Brief `done/`a TAŞINMAYACAK — `in_flight/` kalsın; council onayı bekleyecek.

## Edits

| Dosya | Satır | Açıklama |
|---|---|---|
| `frontend/assets/js/modules/db_smart_ast_editor.js` | 37-42 | `API_BASE` mutlak → göreceli (`/db-smart`); çift prefix bug fix. |
| `frontend/assets/js/modules/db_smart_ast_editor.js` | 71-84 | `_defaultFetchJson` standalone fallback için host prefix ekler (göreceli URL koruma). |
| `frontend/assets/js/modules/db_smart_ast_editor.js` | 598-605 | `_refreshExplain` sessionUid guard (boş/undefined/null literal). |

**Restart gereksinimi (AÇIK):**
- `frontend/dist/_temp_entry.js` ve `frontend/dist/bundle.min.js` eski kodu içeriyor.
- **Çözüm:** Frontend bundle rebuild (esbuild/webpack pipeline ne ise) VEYA development mode'da modules/db_smart_ast_editor.js doğrudan yükleniyorsa hard-reload (Ctrl+Shift+R).
- Backend restart **gerekmiyor** (route zaten kayıtlı, değişiklik yok).

## Diagnostic outputs

```
Route registration:  /api/db-smart/sessions/{session_uid}/explain {'POST'}  ✅
curl POST (no auth): HTTP/1.1 401 Unauthorized                              ✅ (beklenen)
curl OPTIONS:        HTTP/1.1 200 OK + ACAM: GET,POST,PUT,DELETE,PATCH,OPTIONS  ✅
curl GET (yanlış):   HTTP/1.1 405 Method Not Allowed                        🎯 (kullanıcının gördüğü hata)
```

## Verification — kod doğrulaması

- [x] `node -c db_smart_ast_editor.js` → SYNTAX OK.
- [x] AST editor 4 URL site'i (sessions/.../ast/patch, .../explain, .../ast/patch [2], ast/diff) artık göreceli `API_BASE` kullanıyor — tek-noktadan fix.
- [ ] **Browser smoke test** (kullanıcı/diğer agent): bundle rebuild sonrası wizard aç → step 4 → console temiz olmalı.
- [ ] **TYCHE+ARES test brief**: `tests/frontend/db_smart_ast_editor.spec.js`'a `_refreshExplain` URL kompozisyon testi (mock fetch.calls[0][0] = `/db-smart/sessions/UID/explain`, başında protocol/host olmamalı).
