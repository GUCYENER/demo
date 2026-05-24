// frontend/assets/js/api_client.js
//
// =============================================================================
// vyraFetch helper (v3.34.0)
// -----------------------------------------------------------------------------
// Public alias: `window.vyraFetch(path, { method, body, auth })`
//   - path:    string, API_BASE_URL'e relative ("/auth/login" gibi)
//   - method:  "GET" | "POST" | ... (default "GET")
//   - body:    JS object → JSON.stringify (default null)
//   - auth:    boolean — true ise Authorization: Bearer <access_token> ekler
//              (default true). Login/register gibi public uçlar için false.
//
// Dönüş: parse edilmiş JSON objesi.
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
    function buildFriendlyMessage(status, isJson, data) {
        // 401 fast path
        if (status === 401) {
            const detail = data && (data.detail || data.message);
            return detail || "Oturum sona erdi. Lütfen yeniden giriş yapın.";
        }
        // 403 fast path
        if (status === 403) {
            const detail = data && (data.detail || data.message);
            return detail || "Bu işlem için yetkiniz yok.";
        }
        // JSON-formatlı hata: backend mesajını kullan
        if (isJson && data && (data.detail || data.message)) {
            return data.detail || data.message;
        }
        // 502/503/504 — proxy/backend down (genellikle HTML body)
        if (status === 502 || status === 503 || status === 504) {
            return `Backend servisi yanıt vermiyor (HTTP ${status}). Lütfen sistem yöneticinize bildirin.`;
        }
        // Diğer 5xx (non-JSON)
        if (status >= 500 && status < 600) {
            return `Sunucu hatası (${status}). Lütfen tekrar deneyin.`;
        }
        // Non-JSON 4xx
        if (status >= 400 && status < 500) {
            return `İstek reddedildi (${status}).`;
        }
        // Fallback
        return `API error (${status})`;
    }

    async function request(path, { method = "GET", body = null, auth = true } = {}) {
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

        console.log("[NGSSAI] API request:", method, url);

        // ---- Outer fetch try/catch: ağ hatasını yakala ----
        let res;
        try {
            res = await fetch(url, {
                method,
                headers,
                credentials: 'include',
                body: body ? JSON.stringify(body) : null,
            });
        } catch (netErr) {
            // TypeError = network failure / "Failed to fetch" (Nginx down, DNS, vb.)
            const friendly = "Sunucuya bağlanılamadı. Proxy (Nginx) çalışmıyor olabilir veya ağ bağlantınızı kontrol edin.";
            const err = new Error(friendly);
            err.status = undefined;
            err.data = null;
            err.cause = netErr;
            console.error("[NGSSAI] API network error:", netErr);
            throw err;
        }

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
            data = { raw: text };
            parsedAsJson = false;
        }

        if (!res.ok) {
            const isJson = parsedAsJson && looksJson !== false;
            const msg = buildFriendlyMessage(res.status, parsedAsJson, parsedAsJson ? data : null);
            const err = new Error(msg);
            err.status = res.status;
            err.data = data;
            console.error("[NGSSAI] API error:", err);
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
