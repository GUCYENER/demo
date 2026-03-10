// frontend/assets/js/api_client.js
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

        const res = await fetch(url, {
            method,
            headers,
            credentials: 'include',
            body: body ? JSON.stringify(body) : null,
        });

        const text = await res.text();
        let data = null;
        try {
            data = text ? JSON.parse(text) : null;
        } catch {
            data = { raw: text };
        }

        if (!res.ok) {
            const msg =
                (data && (data.detail || data.message)) ||
                `API error (${res.status})`;
            const err = new Error(msg);
            err.status = res.status;
            err.data = data;
            console.error("[NGSSAI] API error:", err);
            throw err;
        }

        return data;
    }

    async function login(phone, password) {
        const data = await request("/auth/login", {
            method: "POST",
            body: { phone, password },
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
})();
