// frontend/assets/js/api_client.js
//
// =============================================================================
// vyraFetch helper (v3.34.0 + R016/R017 v3.34.1)
// -----------------------------------------------------------------------------
// Public alias: `window.vyraFetch(path, { method, body, auth, responseType, signal })`
//   - path:         string, API_BASE_URL'e relative ("/auth/login" gibi)
//   - method:       "GET" | "POST" | ... (default "GET")
//   - body:         JS object → JSON.stringify (default null)
//   - auth:         boolean — true ise Authorization: Bearer <access_token> ekler
//                   (default true). Login/register gibi public uçlar için false.
//   - responseType: "json" (default) | "stream" | "blob" (R016)
//                   - json:   parse edilmiş JS objesi döner.
//                   - stream: raw Response döner; caller body.getReader() ile SSE/
//                             streaming consume eder.
//                   - blob:   Response.blob() döner (download/preview).
//                   Auth + 4xx/5xx friendly-error kontratı 3 path'te de aynıdır.
//   - signal:       AbortController.signal — özellikle stream iptali için.
//
// Dönüş (default): parse edilmiş JSON objesi.
//   stream → Response, blob → Blob.
//
// Ayrıca: `window.vyraFetchUI(path, opts, { onSuccess, onError, loadingEl })`
//   R017 — try/catch + loading-state + error-display boilerplate'ini
//   absorbe eder. Mevcut vyraFetch çağrıları değişmez (additive).
//
// Hata kontratı (Türkçe — kullanıcıya doğrudan gösterilebilir):
//   - Ağ hatası (TypeError / "Failed to fetch") →
//       "Sunucuya bağlanılamadı. Proxy (Nginx) çalışmıyor olabilir
//        veya ağ bağlantınızı kontrol edin."
//   - 502/503/504 (proxy / backend down, HTML response) →
//       "Backend servisi yanıt vermiyor (HTTP {status}). Lütfen sistem yöneticinize bildirin."
//   - Diğer non-JSON 5xx →
//       "Sunucu hatası ({status}). Lütfen tekrar deneyin."
//   - Non-JSON 4xx →
//       "İstek reddedildi ({status})."
//   - 401 (JSON body yoksa veya detail boşsa) →
//       "Oturum sona erdi. Lütfen yeniden giriş yapın."
//   - 403 (JSON body yoksa veya detail boşsa) →
//       "Bu işlem için yetkiniz yok."
//   - JSON body varsa: data.detail veya data.message tercih edilir.
//
// Thrown Error nesnesi şu propertyleri taşır:
//   .message  — Türkçe friendly mesaj
//   .status   — HTTP status code (network failure'da undefined)
//   .data     — parse edilmiş response body (varsa) veya { raw: text }
//
// Geriye dönük uyumluluk: `window.VYRA_API.request(...)` aynı imzayı korur,
// başka modüller (query_builder.js vb.) bu çağrı yolunu kullanmaya devam eder.
// =============================================================================

(function () {
    console.log("[NGSSAI] api_client.js loaded");

    // Backend URL (FastAPI) - Port 8002
    const API_BASE_URL = (window.API_BASE_URL || "http://localhost:8002") + "/api";

    function getTokens() {
        return {
            access: localStorage.getItem("access_token"),
            refresh: localStorage.getItem("refresh_token"),
        };
    }

    function setTokens(access, refresh) {
        if (access) localStorage.setItem("access_token", access);
        if (refresh) localStorage.setItem("refresh_token", refresh);
    }

    // ---- Friendly Turkish error builder ----
    // FIX12 (v3.34.3): error metinleri login resilience plan F1 spec'ine hizalandı.
    // Eski metinler ("Backend servisi yanıt vermiyor (HTTP {status})...") hard-coded
    // olarak başka modülde tüketilmiyor; geriye dönük .message kontrol eden bir
    // modül grep ile bulunmadı.
    //
    // Ek olarak ikinci dönüş değeri olarak bir "code" tag'i üretiyoruz; caller
    // (login.js gibi UX-sensitive yerler) error.code üzerinden mapping yapabilir,
    // mesajın exact-text değişimine duyarlı olmaz.
    function buildFriendlyMessage(status, isJson, data) {
        // 401 fast path
        if (status === 401) {
            const detail = data && (data.detail || data.message);
            return {
                msg: detail || "Oturum sona erdi. Lütfen yeniden giriş yapın.",
                code: 'AUTH_REQUIRED',
            };
        }
        // 403 fast path
        if (status === 403) {
            const detail = data && (data.detail || data.message);
            return {
                msg: detail || "Bu işlem için yetkiniz yok.",
                code: 'FORBIDDEN',
            };
        }
        // JSON-formatlı hata: backend mesajını kullan (HTML/raw scrub: JSON
        // değilse buraya hiç girmiyoruz — aşağıdaki path'ler devralır).
        if (isJson && data && (data.detail || data.message)) {
            return {
                msg: data.detail || data.message,
                code: status >= 500 ? 'SERVER_ERROR' : 'CLIENT_ERROR',
            };
        }
        // 502/503/504 — proxy/backend down (genellikle HTML body)
        if (status === 502 || status === 503 || status === 504) {
            return {
                msg: "Sunucu geçici olarak erişilemiyor. Lütfen 30 saniye sonra tekrar deneyin.",
                code: 'SERVER_5XX',
            };
        }
        // 500 generic
        if (status === 500) {
            return {
                msg: "Sunucuda beklenmeyen bir hata oluştu. Sistem yöneticinizle iletişime geçin.",
                code: 'SERVER_500',
            };
        }
        // Diğer 5xx (non-JSON)
        if (status >= 500 && status < 600) {
            return {
                msg: "Sunucuda beklenmeyen bir hata oluştu. Sistem yöneticinizle iletişime geçin.",
                code: 'SERVER_ERROR',
            };
        }
        // Non-JSON 4xx
        if (status >= 400 && status < 500) {
            return {
                msg: `İstek reddedildi (${status}).`,
                code: 'CLIENT_ERROR',
            };
        }
        // Fallback
        return {
            msg: `API error (${status})`,
            code: 'UNKNOWN',
        };
    }

    // R016 (v3.34.1): non-2xx Response'tan friendly error fırlatma helper'ı —
    // hem JSON hem stream/blob yolu tarafından paylaşılır (DRY).
    // FIX12 (v3.34.3): {msg, code} unpacking + err.code propagation.
    async function _throwFriendlyHttpError(res) {
        let raw = "";
        try { raw = await res.text(); } catch { /* body okunamadı */ }
        let data = null;
        let parsedAsJson = false;
        if (raw) {
            try { data = JSON.parse(raw); parsedAsJson = true; }
            catch { data = { raw }; }
        }
        const { msg, code } = buildFriendlyMessage(res.status, parsedAsJson, parsedAsJson ? data : null);
        const err = new Error(msg);
        err.status = res.status;
        err.data = data;
        err.code = code;
        console.error("[NGSSAI] API error:", err);
        throw err;
    }

    /**
     * Core fetch helper.
     *
     * Opts:
     *   - method, body, auth — bkz. dosya başı dokümantasyonu.
     *   - responseType (R016, v3.34.1):
     *       'json'   (default) — parsed JSON object (geriye dönük uyum).
     *       'stream' — raw Response döner; caller `res.body.getReader()` ile
     *                  SSE/streaming consume eder. Auth header + non-2xx
     *                  friendly error halen uygulanır.
     *       'blob'   — `Response.blob()` döner; caller download/preview
     *                  yapar. Auth header + non-2xx friendly error halen
     *                  uygulanır.
     *   - signal (R016) — AbortController.signal; stream iptali için pratiktir.
     */
    async function request(path, {
        method = "GET",
        body = null,
        auth = true,
        responseType = "json",
        signal = undefined,
    } = {}) {
        const url = `${API_BASE_URL}${path}`;
        const headers = {
            "Content-Type": "application/json",
        };

        if (auth) {
            const { access } = getTokens();
            if (access) {
                headers["Authorization"] = `Bearer ${access}`;
            }
        }

        console.log("[NGSSAI] API request:", method, url, responseType !== "json" ? `(${responseType})` : "");

        // ---- Outer fetch try/catch: ağ hatasını yakala ----
        let res;
        try {
            res = await fetch(url, {
                method,
                headers,
                credentials: 'include',
                body: body ? JSON.stringify(body) : null,
                signal,
            });
        } catch (netErr) {
            // AbortError'ı friendly-wrap etmiyoruz — caller intent'i (signal.abort) bilinçli.
            if (netErr && netErr.name === "AbortError") {
                throw netErr;
            }
            // TypeError = network failure / "Failed to fetch" (Nginx down, DNS, vb.)
            // FIX12 (v3.34.3): SERVER_DOWN code tag + spec-aligned mesaj.
            const friendly = "Sunucu şu anda yanıt vermiyor. Sistem ayağa kalkana kadar lütfen bekleyip tekrar deneyin.";
            const err = new Error(friendly);
            err.status = undefined;
            err.data = null;
            err.code = 'SERVER_DOWN';
            err.cause = netErr;
            console.error("[NGSSAI] API network error:", netErr);
            throw err;
        }

        // R016: stream / blob path — JSON parse atla, ham Response'u döndür.
        if (responseType === "stream") {
            if (!res.ok) {
                await _throwFriendlyHttpError(res);
            }
            return res;  // caller: res.body.getReader() / EventSource pattern
        }

        if (responseType === "blob") {
            if (!res.ok) {
                await _throwFriendlyHttpError(res);
            }
            return await res.blob();
        }

        // Default: JSON path (geriye dönük davranış).
        const text = await res.text();
        const contentType = (res.headers.get("content-type") || "").toLowerCase();
        const looksJson = contentType.includes("application/json");

        let data = null;
        let parsedAsJson = false;
        try {
            if (text) {
                data = JSON.parse(text);
                parsedAsJson = true;
            }
        } catch {
            // Parse başarısız — HTML/text response (Nginx 502 vb.)
            // RAW HTML/text İÇERİĞİ ASLA kullanıcıya gösterilmez (login.js scrub eder),
            // sadece console.error/debug için data.raw'da saklanır.
            data = { raw: text };
            parsedAsJson = false;
        }

        if (!res.ok) {
            const { msg, code } = buildFriendlyMessage(res.status, parsedAsJson, parsedAsJson ? data : null);
            const err = new Error(msg);
            err.status = res.status;
            err.data = data;
            err.code = code;
            console.error("[NGSSAI] API error:", err);
            throw err;
        }

        // FIX12 (v3.34.3): 2xx + non-JSON body (SPA fallback / proxy yanlış cevap).
        // Eski davranış: {raw: "<html>..."} dön; caller `data.access_token` undefined
        // alır, sessizce hatalı yola girer. Yeni: SERVER_DOWN tag'iyle throw.
        //
        // Tetikleme şartı: text non-boş VE JSON parse başarısız oldu. (Yalnız
        // content-type yanlış ama parse başarılı olsaydı permissive davranıyoruz
        // — bazı eski backend'ler text/plain header ile JSON gönderir.)
        if (text && !parsedAsJson) {
            const err = new Error(
                "Sunucu şu anda yanıt vermiyor. Sistem ayağa kalkana kadar lütfen bekleyip tekrar deneyin."
            );
            err.status = res.status;
            err.data = data;  // raw HTML burada; UI'ya gösterilmez.
            err.code = 'SERVER_DOWN';
            console.error("[NGSSAI] API 2xx non-JSON response — proxy/backend misconfigured:", {
                url, status: res.status, contentType,
            });
            throw err;
        }

        return data;
    }

    /**
     * Login helper.
     *
     * v3.34.0: Yeni imza — opts objesi (gerçek backend kontratı):
     *   login({ username, password, domain })  → POST /auth/login
     *
     * Eski imza (geri uyum için korunur — DEPRECATED):
     *   login(phone, password)  → POST /auth/login { phone, password }
     *   Bu imza eski telefon-tabanlı login için kullanılıyordu. Yeni kod
     *   `{username, password, domain}` formunu kullanmalıdır.
     */
    async function login(phoneOrOpts, maybePassword) {
        let body;
        if (typeof phoneOrOpts === "string") {
            // Legacy path — DEPRECATED
            console.warn("[VYRA_API] login(phone, password) DEPRECATED — use login({username, password, domain})");
            body = { phone: phoneOrOpts, password: maybePassword };
        } else {
            // Modern path — { username, password, domain }
            body = phoneOrOpts || {};
        }
        const data = await request("/auth/login", {
            method: "POST",
            body,
            auth: false,
        });
        setTokens(data.access_token, data.refresh_token);
        return data;
    }

    async function registerUser(full_name, phone, password, role = "user") {
        const data = await request("/auth/register", {
            method: "POST",
            body: { full_name, phone, password, role },
            auth: false,
        });
        return data;
    }

    async function refreshToken() {
        const { refresh } = getTokens();
        if (!refresh) return null;

        const data = await request("/auth/refresh", {
            method: "POST",
            body: { refresh_token: refresh },
            auth: false,
        });

        setTokens(data.access_token, data.refresh_token || refresh);
        return data;
    }

    window.VYRA_API = {
        request,
        login,
        registerUser,
        refreshToken,
        getTokens,
        setTokens,
    };

    // v3.34.0: Public defensive fetch alias.
    // Tek satırlık delegasyon — VYRA_API.request'in tüm error contract'ını miras alır.
    // Yeni modüller doğrudan window.vyraFetch(...) çağırmalı; legacy modüller
    // VYRA_API.request'i kullanmaya devam edebilir (her ikisi de aynı kod yolu).
    window.vyraFetch = function (path, opts) {
        return window.VYRA_API.request(path, opts);
    };

    // R017 (v3.34.1): UI-aware vyraFetch wrapper.
    // ----------------------------------------------------------------
    // Mevcut 28 modülde tekrar eden boilerplate:
    //
    //     try {
    //         const data = await vyraFetch(path, opts);
    //         render(data);
    //     } catch (err) {
    //         showError(root, "Yükleme hatası: " + err.message);
    //     }
    //
    // vyraFetchUI bunu absorbe eder:
    //
    //     await vyraFetchUI(path, opts, {
    //         onSuccess: data => render(data),
    //         onError:   err  => showError(root, err.message),
    //         loadingEl: btn,            // optional — disabled toggle
    //     });
    //
    // Opts ikinci argüman vyraFetch'inkiyle birebir aynı (method/body/auth/
    // responseType/signal). Wrapper hiçbir varsayılan değiştirmez.
    //
    // ui-opts (üçüncü argüman):
    //   - onSuccess(data)        — başarı (4xx/5xx atılmadıysa) callback.
    //   - onError(err)           — vyraFetch friendly Error yakalandığında.
    //                              Verilmezse hata RE-THROW edilir (caller
    //                              kendi try/catch'inde yakalar).
    //   - loadingEl              — opsiyonel DOM element; çağrı başında
    //                              `disabled=true` + `aria-busy="true"`,
    //                              sonunda restore.
    //
    // Dönüş: vyraFetch çıktısı (data) veya onError'dan dönen değer (varsa).
    //
    // Geriye dönük uyum: vyraFetch çağrıları HİÇ etkilenmez; bu helper
    // saf opt-in additive. Mevcut 28 modül adoption için ayrı PR (R020).
    window.vyraFetchUI = async function (path, opts, uiOpts) {
        const { onSuccess, onError, loadingEl } = uiOpts || {};

        // Loading-state on
        let prevDisabled, prevAriaBusy;
        if (loadingEl) {
            prevDisabled = loadingEl.disabled;
            prevAriaBusy = loadingEl.getAttribute("aria-busy");
            loadingEl.disabled = true;
            loadingEl.setAttribute("aria-busy", "true");
        }

        try {
            const data = await window.vyraFetch(path, opts);
            if (typeof onSuccess === "function") {
                try { onSuccess(data); }
                catch (cbErr) {
                    console.error("[vyraFetchUI] onSuccess callback threw:", cbErr);
                }
            }
            return data;
        } catch (err) {
            if (typeof onError === "function") {
                try { return onError(err); }
                catch (cbErr) {
                    console.error("[vyraFetchUI] onError callback threw:", cbErr);
                    throw err;  // orijinal hata baskın
                }
            } else {
                throw err;
            }
        } finally {
            // Loading-state off
            if (loadingEl) {
                loadingEl.disabled = prevDisabled || false;
                if (prevAriaBusy === null) {
                    loadingEl.removeAttribute("aria-busy");
                } else {
                    loadingEl.setAttribute("aria-busy", prevAriaBusy);
                }
            }
        }
    };

    // v3.32.0: Canonical Authorization header helper.
    // query_builder.js (ve diğer bundle modülleri) `window.getAuthHeader()` bekliyor;
    // daha önce hiçbir modül tanımlamıyordu → /api/query-state/preview gibi auth'lu
    // çağrılar header'sız gidip 401 dönüyordu. api_client.js bundle'da olduğu için
    // home.html'de bu helper artık her zaman tanımlı.
    if (!window.getAuthHeader) {
        window.getAuthHeader = function () {
            const { access } = getTokens();
            return access ? { Authorization: 'Bearer ' + access } : {};
        };
    }
})();
