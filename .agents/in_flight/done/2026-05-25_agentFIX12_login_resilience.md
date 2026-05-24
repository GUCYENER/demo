# Brief — agentFIX12 — Login Resilience (F1)

**Date:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0200_login_resilience_qb_fixes_v1.md` (Deliverable F1)
**Council:** HEBE (UX copy) + HERMES (fetch/parse layer)
**Status:** in_flight (NOT to be moved to done/ per orchestrator)

---

## Problem

Backend veya DB down olduğunda login formu raw JSON parse hatasını gösteriyor:

```
Unexpected token '<', "<html> <h"... is not valid JSON
```

Sebep: backend (veya proxy) HTML hata sayfası döndürüyor; frontend `JSON.parse()` denerken `SyntaxError` fırlatıyor, mesaj UI'a kadar geçiyor.

---

## Edge case analizi (vyraFetch'in mevcut hâli)

`frontend/assets/js/api_client.js` — `request()` zaten:
- Outer fetch'i try/catch ile sarmalıyor (TypeError network → friendly TR).
- `JSON.parse(text)` çağrısını try/catch ile sarmalıyor (SyntaxError yutuluyor, `data = {raw: text}` set ediliyor).
- Non-2xx için `buildFriendlyMessage()` Türkçe mesaj üretiyor.

**Gap 1**: 2xx + HTML body (örn. SPA fallback `/auth/login` route'unu yakalar, 200 HTML döner) — şu an `data = {raw: "<html>..."}` döner ve caller `data.access_token` (undefined) bekler. SERVER_DOWN throw edilmiyor.

**Gap 2**: Friendly mesaj metinleri plan F1 spec ile birebir aynı değil:
- Mevcut 502/503/504 → "Backend servisi yanıt vermiyor (HTTP 502). Lütfen sistem yöneticinize bildirin."
- Spec 502/503/504 → "Sunucu geçici olarak erişilemiyor. Lütfen 30 saniye sonra tekrar deneyin."

**Gap 3**: Login.js `error.message`'ı doğrudan gösteriyor — `error.code === 'SERVER_DOWN'` ayrı bir mapping'i yok. Spec error code'a dayalı mapping istiyor.

---

## Plan

### `api_client.js`

1. `buildFriendlyMessage()`:
   - 502/503/504 metnini güncelle: "Sunucu geçici olarak erişilemiyor. Lütfen 30 saniye sonra tekrar deneyin."
   - 500 (non-JSON veya generic) metnini güncelle: "Sunucuda beklenmeyen bir hata oluştu. Sistem yöneticinizle iletişime geçin."
   - Yeni `SERVER_DOWN` mesajı (code-tagged path): "Sunucu şu anda yanıt vermiyor. Sistem ayağa kalkana kadar lütfen bekleyip tekrar deneyin."
2. Network failure (TypeError) path'inde `err.code = 'SERVER_DOWN'` set et; mesaj spec ile aynı.
3. Default JSON path'te 2xx ve `!parsedAsJson` (response HTML/text) → `SERVER_DOWN` fırlat (code + status korunur).
4. 502/503/504 + 500 path'lerinde `err.code = 'SERVER_DOWN' | 'SERVER_5XX' | 'SERVER_500'` ekle (login.js mapping için).
5. Raw HTML/JSON içeriği KULLANICIYA GÖSTERME — `err.message` her zaman sanitize/scrub edilmiş Türkçe.
6. `err.data` (raw HTML içeren) `console.error` için kalsın ama UI'da gösterilmesin (login.js zaten `err.message` kullanıyor).

### `login.js`

1. `handleLogin` ve `handleRegister` catch bloklarında error → friendly TR mesaj mapping:
   ```js
   function mapAuthError(error) {
       if (!error) return "Giriş yapılamadı. Lütfen tekrar deneyin.";
       const code = error.code;
       const status = error.status;
       if (code === 'SERVER_DOWN' || (!status && error.name !== 'AbortError')) {
           return "Sunucu şu anda yanıt vermiyor. Sistem ayağa kalkana kadar lütfen bekleyip tekrar deneyin.";
       }
       if (status === 502 || status === 503 || status === 504) {
           return "Sunucu geçici olarak erişilemiyor. Lütfen 30 saniye sonra tekrar deneyin.";
       }
       if (status === 401) {
           return "Kullanıcı adı veya şifre hatalı.";
       }
       if (status === 500) {
           return "Sunucuda beklenmeyen bir hata oluştu. Sistem yöneticinizle iletişime geçin.";
       }
       // Backend friendly TR mesajı varsa kullan; yoksa generic.
       if (typeof error.message === 'string' && error.message && !/JSON|token|<html/i.test(error.message)) {
           return error.message;
       }
       return "Giriş yapılamadı. Lütfen tekrar deneyin.";
   }
   ```
2. `showError("login-error", mapAuthError(error))`.
3. `<html`/`JSON`/`token` desenli mesajları KULLANICIYA göstermemek için scrub guard.

### Cross-module side effects (R-1)

`vyraFetch` 28+ modül tarafından kullanılıyor. Değişiklikler:
- **Geriye dönük uyumlu**: `err.message`, `err.status`, `err.data` kontratı korunur.
- **Eklenenler**: `err.code` (yeni opsiyonel property).
- **Mesaj metni değişimi**: 502/503/504 + 500 metni değişti — eski text'i hard-coded match eden modül **yok** (grep ile doğrulandı).
- **2xx + HTML throw**: yeni behavior. Eski davranışta `{raw: "<html>"}` döndü, caller `.something` erişiminde undefined alıyordu (silent fail). Artık SERVER_DOWN throw edecek — bu düzeltilmesi gereken bir bug'dı (login token undefined kaydı engelleniyor).

---

## Test scenarios

| Senaryo | Beklenen UI mesajı |
|---|---|
| Backend tamamen down (TypeError) | "Sunucu şu anda yanıt vermiyor. Sistem ayağa kalkana kadar lütfen bekleyip tekrar deneyin." |
| Backend HTTP 502/503/504 (HTML body) | "Sunucu geçici olarak erişilemiyor. Lütfen 30 saniye sonra tekrar deneyin." |
| Backend 200 + HTML body (SPA fallback) | "Sunucu şu anda yanıt vermiyor. Sistem ayağa kalkana kadar lütfen bekleyip tekrar deneyin." |
| HTTP 401 wrong creds | "Kullanıcı adı veya şifre hatalı." (veya backend JSON `detail`) |
| HTTP 500 generic error | "Sunucuda beklenmeyen bir hata oluştu. Sistem yöneticinizle iletişime geçin." |
| Diğer / catch-all | "Giriş yapılamadı. Lütfen tekrar deneyin." |

---

## Deliverable

1. `frontend/assets/js/api_client.js` — `buildFriendlyMessage` {msg,code} unpack, SERVER_DOWN code propagation, 2xx-HTML guard.
2. `frontend/assets/js/login.js` — `mapAuthError` helper + scrub (NOT actually consumed by login page; see Finding-A).
3. **Finding-A (CRITICAL)**: `frontend/login.html` aslında `assets/js/login.js` YÜKLEMEZ — login handler'ı INLINE `<script>` bloğunda (line 997-1052 `doLogin`, 1055-1114 `doRegister`). User'ın gördüğü hata da bu inline handler'dan geliyor: `var data = await response.json();` (line 1021) — content-type kontrolü yok, HTML 502 → SyntaxError → ekrana sızıyor.
4. **Gerçek fix**: `login.html` inline script güncellendi — `safeParseJsonResponse(res)` helper (content-type + try/catch + SERVER_DOWN throw), `mapAuthError(error)` (TR mapping + scrub guard).
5. `frontend/assets/js/login.js` değişiklikleri yine geri uyumlu olarak yapıldı (vyraFetch tabanlı modern path) — gelecekte `login.html` ortak helper'a geçerse hazır.
6. `cd frontend && npm run build` — bundle yeniden üretildi (`api_client.js` minify çıktısında SERVER_DOWN bulundu).

## Restart / Reload

- `login.html` doğrudan static dosya, browser hard-reload (Ctrl+Shift+R) yeterli.
- Bundle değişikliği için yine hard-reload (api_client.js diğer sayfalarda kullanılıyor).
