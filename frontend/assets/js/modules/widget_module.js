/**
 * NGSSAI Web Widget Yönetim Modülü
 * ==================================
 * Admin panelinde widget API anahtarlarını oluşturma,
 * listeleme, güncelleme ve silme işlemlerini yönetir.
 */

(function () {
    "use strict";

    const API = window.VYRA_API || window.NGSSAI_API || "";

    function getToken() {
        return localStorage.getItem("access_token") || "";
    }

    function apiRequest(method, path, body) {
        return fetch(`${API}${path}`, {
            method,
            headers: {
                "Authorization": `Bearer ${getToken()}`,
                "Content-Type": "application/json",
            },
            body: body ? JSON.stringify(body) : undefined,
        });
    }

    // ------------------------------------------------------------------
    // State
    // ------------------------------------------------------------------
    let orgs = [];
    let keys = [];

    // ------------------------------------------------------------------
    // Orgs yükle (select için)
    // ------------------------------------------------------------------
    async function loadOrgs() {
        try {
            const resp = await apiRequest("GET", "/api/organizations");
            if (resp.ok) {
                const data = await resp.json();
                orgs = Array.isArray(data) ? data : (data.items || []);
            }
        } catch {}
    }

    function populateOrgSelect() {
        const sel = document.getElementById("widgetKeyOrg");
        if (!sel) return;
        sel.innerHTML = '<option value="">Organizasyon seçin...</option>';
        orgs
            .filter(o => o.is_active)
            .forEach(o => {
                const opt = document.createElement("option");
                opt.value = o.id;
                opt.textContent = `${o.org_name} (${o.org_code})`;
                sel.appendChild(opt);
            });
    }

    // ------------------------------------------------------------------
    // Key listesini yükle ve tabloya render et
    // ------------------------------------------------------------------
    async function loadKeys() {
        const tbody = document.getElementById("widgetKeysTableBody");
        const empty = document.getElementById("widgetKeysEmpty");
        if (!tbody) return;

        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:32px">
            <i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...
        </td></tr>`;

        try {
            const resp = await apiRequest("GET", "/api/widget/keys");
            if (!resp.ok) throw new Error("Yüklenemedi");
            keys = await resp.json();
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--red);padding:24px">
                Anahtarlar yüklenemedi: ${e.message}
            </td></tr>`;
            return;
        }

        if (!keys.length) {
            tbody.innerHTML = "";
            empty?.classList.remove("hidden");
            return;
        }

        empty?.classList.add("hidden");

        tbody.innerHTML = keys.map(k => {
            const domains = Array.isArray(k.allowed_domains) && k.allowed_domains.length
                ? k.allowed_domains.map(d => `<span class="badge badge-blue" style="font-size:10px">${d}</span>`).join(" ")
                : `<span style="color:var(--text-3);font-size:12px">Herkese açık</span>`;

            const lastUsed = k.last_used_at
                ? new Date(k.last_used_at).toLocaleDateString("tr-TR")
                : `<span style="color:var(--text-3)">Hiç</span>`;

            const statusBadge = k.is_active
                ? `<span class="badge badge-green"><span class="badge-dot"></span>Aktif</span>`
                : `<span class="badge badge-red"><span class="badge-dot"></span>Pasif</span>`;

            return `
                <tr data-key-id="${k.id}">
                    <td style="font-weight:500;color:var(--text-1)">${escHtml(k.name)}</td>
                    <td><code style="font-family:monospace;font-size:12px;background:var(--bg-3);padding:2px 7px;border-radius:5px">${escHtml(k.key_prefix)}…</code></td>
                    <td><span class="badge badge-purple" style="font-size:11px">${escHtml(k.org_code)}</span></td>
                    <td>${domains}</td>
                    <td style="font-size:12px;color:var(--text-2)">${lastUsed}</td>
                    <td>${statusBadge}</td>
                    <td>
                        <div class="action-btns">
                            <button class="act-btn edit btn-toggle-key" data-key-id="${k.id}" data-active="${k.is_active}" title="${k.is_active ? 'Pasife Al' : 'Aktife Al'}">
                                <i class="fa-solid ${k.is_active ? 'fa-toggle-on' : 'fa-toggle-off'}"></i>
                            </button>
                            <button class="act-btn edit btn-snippet" data-key-id="${k.id}" title="Entegrasyon Kodunu Göster">
                                <i class="fa-solid fa-code"></i>
                            </button>
                            <button class="act-btn del btn-delete-key" data-key-id="${k.id}" title="Sil">
                                <i class="fa-solid fa-trash"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

        // Event listeners
        tbody.querySelectorAll(".btn-toggle-key").forEach(btn => {
            btn.addEventListener("click", () => toggleKey(
                parseInt(btn.dataset.keyId),
                btn.dataset.active === "true"
            ));
        });

        tbody.querySelectorAll(".btn-snippet").forEach(btn => {
            btn.addEventListener("click", () => showSnippet(parseInt(btn.dataset.keyId)));
        });

        tbody.querySelectorAll(".btn-delete-key").forEach(btn => {
            btn.addEventListener("click", () => deleteKey(parseInt(btn.dataset.keyId)));
        });
    }

    // ------------------------------------------------------------------
    // Yeni key oluştur
    // ------------------------------------------------------------------
    function openNewKeyModal() {
        const modal = document.getElementById("widgetKeyModal");
        if (!modal) return;
        populateOrgSelect();
        document.getElementById("widgetKeyName").value = "";
        document.getElementById("widgetKeyOrg").value = "";
        document.getElementById("widgetKeyDomains").value = "";
        document.getElementById("widgetKeyActive").checked = true;
        modal.classList.remove("hidden");
    }

    function closeNewKeyModal() {
        document.getElementById("widgetKeyModal")?.classList.add("hidden");
    }

    async function saveWidgetKey() {
        const name = document.getElementById("widgetKeyName")?.value.trim();
        const orgId = parseInt(document.getElementById("widgetKeyOrg")?.value);
        const domainsRaw = document.getElementById("widgetKeyDomains")?.value.trim();
        const isActive = document.getElementById("widgetKeyActive")?.checked ?? true;

        if (!name) { showToast("Anahtar adı zorunludur", "error"); return; }
        if (!orgId) { showToast("Organizasyon seçin", "error"); return; }

        const allowedDomains = domainsRaw
            ? domainsRaw.split(",").map(d => d.trim().toLowerCase()).filter(Boolean)
            : [];

        const saveBtn = document.getElementById("saveWidgetKey");
        if (saveBtn) { saveBtn.disabled = true; saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Oluşturuluyor...'; }

        try {
            const resp = await apiRequest("POST", "/api/widget/keys", {
                name, org_id: orgId, allowed_domains: allowedDomains, is_active: isActive,
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || "Oluşturulamadı");
            }

            const data = await resp.json();
            closeNewKeyModal();
            showCreatedModal(data);
            await loadKeys();

        } catch (e) {
            showToast(e.message, "error");
        } finally {
            if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '<i class="fa-solid fa-key"></i> Oluştur'; }
        }
    }

    // ------------------------------------------------------------------
    // Oluşturuldu modal
    // ------------------------------------------------------------------
    function showCreatedModal(data) {
        const modal = document.getElementById("widgetKeyCreatedModal");
        if (!modal) return;

        const keyInput = document.getElementById("widgetCreatedKey");
        const snippetEl = document.getElementById("widgetSnippet");
        const baseUrl = window.location.origin;

        if (keyInput) keyInput.value = data.api_key || "";
        if (snippetEl) {
            snippetEl.value = `<script src="${baseUrl}/widget/widget.js"\n        data-key="${data.api_key || ""}"\n        data-title="Destek Asistanı">\n<\/script>`;
        }

        modal.classList.remove("hidden");
    }

    function closeCreatedModal() {
        document.getElementById("widgetKeyCreatedModal")?.classList.add("hidden");
    }

    // ------------------------------------------------------------------
    // Snippet göster (mevcut key için)
    // ------------------------------------------------------------------
    function showSnippet(keyId) {
        const key = keys.find(k => k.id === keyId);
        if (!key) return;

        const baseUrl = window.location.origin;
        const snippet = `<script src="${baseUrl}/widget/widget.js"\n        data-key="${key.key_prefix}... (tam key'i kaydettiğiniz yerden alın)"\n        data-title="Destek Asistanı">\n<\/script>`;

        const createdModal = document.getElementById("widgetKeyCreatedModal");
        const keyInput = document.getElementById("widgetCreatedKey");
        const snippetEl = document.getElementById("widgetSnippet");

        if (keyInput) keyInput.value = `${key.key_prefix}... (güvenlik nedeniyle maskelendi)`;
        if (snippetEl) snippetEl.value = snippet;
        if (createdModal) createdModal.classList.remove("hidden");
    }

    // ------------------------------------------------------------------
    // Toggle aktif/pasif
    // ------------------------------------------------------------------
    async function toggleKey(keyId, currentlyActive) {
        try {
            const resp = await apiRequest("PUT", `/api/widget/keys/${keyId}`, {
                is_active: !currentlyActive,
            });
            if (!resp.ok) throw new Error("Güncellenemedi");
            showToast(`Anahtar ${!currentlyActive ? "aktifleştirildi" : "pasifleştirildi"}`, "success");
            await loadKeys();
        } catch (e) {
            showToast(e.message, "error");
        }
    }

    // ------------------------------------------------------------------
    // Key sil
    // ------------------------------------------------------------------
    async function deleteKey(keyId) {
        const key = keys.find(k => k.id === keyId);
        if (!confirm(`"${key?.name || 'Bu anahtar'}" silinecek. Emin misiniz?`)) return;

        try {
            const resp = await apiRequest("DELETE", `/api/widget/keys/${keyId}`);
            if (!resp.ok) throw new Error("Silinemedi");
            showToast("Anahtar silindi", "success");
            await loadKeys();
        } catch (e) {
            showToast(e.message, "error");
        }
    }

    // ------------------------------------------------------------------
    // Clipboard kopyalama
    // ------------------------------------------------------------------
    function copyToClipboard(text, label) {
        navigator.clipboard?.writeText(text)
            .then(() => showToast(`${label} kopyalandı`, "success"))
            .catch(() => {
                const ta = document.createElement("textarea");
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                ta.remove();
                showToast(`${label} kopyalandı`, "success");
            });
    }

    // ------------------------------------------------------------------
    // Toast / showToast uyumluluğu
    // ------------------------------------------------------------------
    function showToast(msg, type) {
        if (window.showToast) { window.showToast(msg, type); return; }
        const el = document.createElement("div");
        el.style.cssText = `position:fixed;bottom:24px;right:24px;z-index:9999;
            background:${type === "error" ? "#ef4444" : "#22c55e"};color:#fff;
            padding:10px 18px;border-radius:10px;font-size:13.5px;box-shadow:0 4px 16px rgba(0,0,0,.3)`;
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3000);
    }

    // ------------------------------------------------------------------
    // HTML escape
    // ------------------------------------------------------------------
    function escHtml(s) {
        return String(s || "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // ------------------------------------------------------------------
    // Başlat — tab açıldığında çağrılır
    // ------------------------------------------------------------------
    async function init() {
        // base url span
        const baseUrlSpan = document.getElementById("widgetBaseUrl");
        if (baseUrlSpan) baseUrlSpan.textContent = window.location.origin;

        await Promise.all([loadOrgs(), loadKeys()]);

        // Yeni Anahtar butonu
        document.getElementById("btnNewWidgetKey")
            ?.addEventListener("click", openNewKeyModal);

        // Modal kapat
        document.getElementById("closeWidgetKeyModal")
            ?.addEventListener("click", closeNewKeyModal);
        document.getElementById("cancelWidgetKeyModal")
            ?.addEventListener("click", closeNewKeyModal);

        // Modal kaydet
        document.getElementById("saveWidgetKey")
            ?.addEventListener("click", saveWidgetKey);

        // Oluşturuldu modal
        document.getElementById("closeWidgetCreatedModal")
            ?.addEventListener("click", closeCreatedModal);
        document.getElementById("closeWidgetCreatedOk")
            ?.addEventListener("click", closeCreatedModal);

        // Kopyala butonları
        document.getElementById("copyWidgetKey")?.addEventListener("click", () => {
            copyToClipboard(
                document.getElementById("widgetCreatedKey")?.value || "",
                "API anahtarı"
            );
        });
        document.getElementById("copyWidgetSnippet")?.addEventListener("click", () => {
            copyToClipboard(
                document.getElementById("widgetSnippet")?.value || "",
                "Entegrasyon kodu"
            );
        });

        // Modal dışına tıklayınca kapat
        ["widgetKeyModal", "widgetKeyCreatedModal"].forEach(id => {
            document.getElementById(id)?.addEventListener("click", (e) => {
                if (e.target.id === id) document.getElementById(id).classList.add("hidden");
            });
        });
    }

    // Global erişim
    window.widgetModule = { init, loadKeys };

})();
