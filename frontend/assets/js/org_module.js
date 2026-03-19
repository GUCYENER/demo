/**
 * NGSSAI - Organization Management Module
 * home.html içinde sağ bölümde çalışır
 */

(function () {
    "use strict";

    const API_BASE = (window.API_BASE_URL || "http://localhost:8002") + "/api";

    let orgs = [];
    let currentPage = 1;
    let perPage = 10;
    let searchTerm = '';
    let filterActive = null;
    let editingOrgId = null;

    // ---- Load Organizations ----
    async function loadOrganizations() {
        const token = localStorage.getItem("access_token");
        if (!token) return;

        const loading = document.getElementById("orgLoading");
        const empty = document.getElementById("orgEmpty");
        const tbody = document.getElementById("orgTableBody");

        loading?.classList.remove("hidden");
        empty?.classList.add("hidden");

        try {
            const params = new URLSearchParams({ page: currentPage, per_page: perPage });
            if (searchTerm) params.append("search", searchTerm);
            if (filterActive !== null) params.append("is_active", filterActive);

            const response = await fetch(`${API_BASE}/organizations?${params}`, {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!response.ok) throw new Error("Organizasyonlar yüklenemedi");

            const data = await response.json();
            orgs = data.organizations || [];

            renderOrganizations();
            renderPagination(data.total, data.page, data.per_page);
            updateTotalCount(data.total);

        } catch (error) {
            console.error("[OrgModule] Error:", error);
            showToast(error.message, "error");
        } finally {
            loading?.classList.add("hidden");
        }
    }

    function renderOrganizations() {
        const tbody = document.getElementById("orgTableBody");
        const empty = document.getElementById("orgEmpty");

        if (!orgs || orgs.length === 0) {
            tbody.innerHTML = "";
            empty?.classList.remove("hidden");
            return;
        }

        empty?.classList.add("hidden");

        tbody.innerHTML = orgs.map(org => `
            <tr>
                <td><span class="badge badge-blue">${escapeHtml(org.org_code)}</span></td>
                <td style="font-weight:500;color:var(--text-1)">${escapeHtml(org.org_name)}</td>
                <td><span class="badge ${org.is_active ? 'badge-green' : 'badge-red'}"><span class="badge-dot"></span>${org.is_active ? 'Aktif' : 'Pasif'}</span></td>
                <td>${org.user_count || 0}</td>
                <td>${org.document_count || 0}</td>
                <td>
                    <div class="action-btns">
                        <button class="act-btn edit" onclick="window.orgModule.openEditModal(${org.id})" title="Düzenle">
                            <i class="fa-solid fa-edit" style="font-size:11px"></i>
                        </button>
                        <button class="act-btn del" onclick="window.orgModule.deleteOrg(${org.id}, '${escapeHtml(org.org_code)}')" title="Sil"
                                ${['ORG-DEFAULT', 'ORG-ADMIN'].includes(org.org_code) ? 'disabled style="opacity:0.4;cursor:not-allowed;"' : ''}>
                            <i class="fa-solid fa-trash" style="font-size:11px"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `).join("");
    }

    function renderPagination(total, page, perPage) {
        const container = document.getElementById("orgPagination");
        if (!container) return;

        const totalPages = Math.ceil(total / perPage) || 1;

        // Her zaman göster (tek sayfa olsa bile navigasyon bilgisi için)
        let html = `
            <button class="pg-btn" onclick="window.orgModule.goToPage(1)" ${page === 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-angles-left" style="font-size:10px"></i>
            </button>
            <button class="pg-btn" onclick="window.orgModule.goToPage(${page - 1})" ${page === 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-left" style="font-size:10px"></i>
            </button>
            <span class="pg-btn pg-cur">${page} / ${totalPages}</span>
            <button class="pg-btn" onclick="window.orgModule.goToPage(${page + 1})" ${page >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-right" style="font-size:10px"></i>
            </button>
            <button class="pg-btn" onclick="window.orgModule.goToPage(${totalPages})" ${page >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-angles-right" style="font-size:10px"></i>
            </button>
        `;
        container.innerHTML = html;
    }

    function goToPage(page) {
        currentPage = page;
        loadOrganizations();
    }

    function updateTotalCount(total) {
        const el = document.getElementById("orgTotalCount");
        if (el) {
            el.textContent = `Toplam: ${total} kayıt`;
        }
    }

    // ---- Create/Edit Modal ----
    function openCreateModal() {
        editingOrgId = null;
        showOrgModal("Yeni Organizasyon", { org_code: "", org_name: "", description: "", is_active: true });
    }

    async function openEditModal(orgId) {
        const token = localStorage.getItem("access_token");
        try {
            const response = await fetch(`${API_BASE}/organizations/${orgId}`, {
                headers: { "Authorization": `Bearer ${token}` }
            });
            if (!response.ok) throw new Error("Org yüklenemedi");
            const org = await response.json();
            editingOrgId = orgId;
            showOrgModal("Organizasyon Düzenle", org);
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    function showOrgModal(title, org) {
        const modalHtml = `
            <div id="orgModalOverlay" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 9999;">
                <div style="background: #1f2937; border-radius: 16px; padding: 24px; width: 450px; max-width: 90%;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                        <h3 style="font-size: 1.25rem; font-weight: 600;"><i class="fa-solid fa-building" style="color: #f59e0b; margin-right: 8px;"></i>${title}</h3>
                        <button onclick="window.orgModule.closeModal()" style="background: none; border: none; color: #9ca3af; cursor: pointer; font-size: 1.25rem;">
                            <i class="fa-solid fa-times"></i>
                        </button>
                    </div>
                    <form id="orgModalForm" onsubmit="window.orgModule.saveOrg(event)">
                        <div style="margin-bottom: 16px;">
                            <label style="display: block; margin-bottom: 6px; color: #9ca3af; font-size: 0.875rem;">Org Kodu *</label>
                            <input type="text" id="modalOrgCode" value="${escapeHtml(org.org_code || '')}" 
                                   style="width: 100%; padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid #374151; border-radius: 8px; color: white;"
                                   placeholder="ORG-IT" required pattern="[A-Z0-9\\-]+" ${editingOrgId ? 'disabled' : ''}>
                        </div>
                        <div style="margin-bottom: 16px;">
                            <label style="display: block; margin-bottom: 6px; color: #9ca3af; font-size: 0.875rem;">Org Adı *</label>
                            <input type="text" id="modalOrgName" value="${escapeHtml(org.org_name || '')}" 
                                   style="width: 100%; padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid #374151; border-radius: 8px; color: white;"
                                   placeholder="IT Departmanı" required>
                        </div>
                        <div style="margin-bottom: 16px;">
                            <label style="display: block; margin-bottom: 6px; color: #9ca3af; font-size: 0.875rem;">Açıklama</label>
                            <textarea id="modalOrgDesc" style="width: 100%; padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid #374151; border-radius: 8px; color: white; min-height: 80px;"
                                      placeholder="Organizasyon açıklaması...">${escapeHtml(org.description || '')}</textarea>
                        </div>
                        <div style="margin-bottom: 20px;">
                            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="checkbox" id="modalOrgActive" ${org.is_active ? 'checked' : ''} style="width: 18px; height: 18px;">
                                <span>Aktif</span>
                            </label>
                        </div>
                        <div style="display: flex; gap: 12px; justify-content: flex-end;">
                            <button type="button" onclick="window.orgModule.closeModal()" 
                                    style="padding: 10px 20px; background: #374151; color: white; border: none; border-radius: 8px; cursor: pointer;">
                                İptal
                            </button>
                            <button type="submit" 
                                    style="padding: 10px 20px; background: linear-gradient(135deg, #6366f1, #818cf8); color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">
                                <i class="fa-solid fa-save"></i> Kaydet
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML("beforeend", modalHtml);

        // ESC key
        document.addEventListener("keydown", escKeyHandler);
    }

    function escKeyHandler(e) {
        if (e.key === "Escape") closeModal();
    }

    function closeModal() {
        document.getElementById("orgModalOverlay")?.remove();
        document.removeEventListener("keydown", escKeyHandler);
    }

    async function saveOrg(event) {
        event.preventDefault();
        const token = localStorage.getItem("access_token");

        const payload = {
            org_name: document.getElementById("modalOrgName").value.trim(),
            description: document.getElementById("modalOrgDesc").value.trim() || null,
            is_active: document.getElementById("modalOrgActive").checked
        };

        if (!editingOrgId) {
            payload.org_code = document.getElementById("modalOrgCode").value.trim().toUpperCase();
        }

        try {
            const url = editingOrgId ? `${API_BASE}/organizations/${editingOrgId}` : `${API_BASE}/organizations`;
            const method = editingOrgId ? "PUT" : "POST";

            const response = await fetch(url, {
                method,
                headers: {
                    "Authorization": `Bearer ${token}`,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Kayıt başarısız");
            }

            showToast(editingOrgId ? "Organizasyon güncellendi" : "Organizasyon oluşturuldu", "success");
            closeModal();
            loadOrganizations();

        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function deleteOrg(orgId, orgCode) {
        if (['ORG-DEFAULT', 'ORG-ADMIN'].includes(orgCode)) {
            showToast("Varsayılan organizasyonlar silinemez", "error");
            return;
        }

        VyraModal.danger({
            title: 'Organizasyon Sil',
            message: `"${orgCode}" organizasyonunu silmek istediğinize emin misiniz?`,
            confirmText: 'Sil',
            cancelText: 'İptal',
            onConfirm: async () => {
                const token = localStorage.getItem("access_token");
                try {
                    const response = await fetch(`${API_BASE}/organizations/${orgId}`, {
                        method: "DELETE",
                        headers: { "Authorization": `Bearer ${token}` }
                    });

                    if (!response.ok) throw new Error("Silme başarısız");

                    showToast("Organizasyon silindi", "success");
                    loadOrganizations();

                } catch (error) {
                    showToast(error.message, "error");
                }
            }
        });
    }

    function escapeHtml(text) {
        if (!text) return "";
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    // ---- Event Listeners ----
    function setupEventListeners() {
        // New Org Button
        document.getElementById("btnNewOrg")?.addEventListener("click", openCreateModal);

        // Search Input
        const searchInput = document.getElementById("orgSearchInput");
        const clearBtn = document.getElementById("orgSearchClear");

        if (searchInput) {
            let timeout;
            searchInput.addEventListener("input", (e) => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    searchTerm = e.target.value;
                    currentPage = 1;
                    loadOrganizations();

                    // Toggle clear button
                    if (clearBtn) {
                        clearBtn.classList.toggle("hidden", !searchTerm);
                    }
                }, 150);  // Daha hızlı tepki
            });
        }

        // Search Clear Button
        if (clearBtn) {
            clearBtn.addEventListener("click", () => {
                searchInput.value = '';
                searchTerm = '';
                clearBtn.classList.add("hidden");
                currentPage = 1;
                loadOrganizations();
            });
        }

        // Filter Buttons
        document.querySelectorAll("#sectionOrganizations .org-filter-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const clicked = e.target.closest('.org-filter-btn');
                if (!clicked) return;
                document.querySelectorAll("#sectionOrganizations .org-filter-btn").forEach(b => {
                    b.classList.remove("active");
                });
                clicked.classList.add("active");

                const filter = clicked.dataset.filter;
                filterActive = filter === "all" ? null : (filter === "active");
                currentPage = 1;
                loadOrganizations();
            });
        });
    }

    // ---- Init ----
    function init() {
        setupEventListeners();
    }

    // Export
    window.orgModule = {
        loadOrganizations,
        openCreateModal,
        openEditModal,
        closeModal,
        saveOrg,
        deleteOrg,
        goToPage,
        init
    };

    // Auto-init
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
