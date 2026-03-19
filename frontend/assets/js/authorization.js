/**
 * NGSSAI - Authorization & Profile Module
 * Kullanıcı yetkilendirme ve profil yönetimi
 */

(function () {
    "use strict";

    const API_BASE = (window.API_BASE_URL || "http://localhost:8002") + "/api";

    let roles = [];
    let orgs = [];  // Organizasyon grupları

    // Pagination state
    let usersCurrentPage = 1;
    let usersPerPage = 10;
    let usersTotalCount = 0;
    let usersSearchTerm = '';
    let usersSearchDebounceTimer = null;

    // ---- Authorization Functions ----
    async function loadUsers(pendingOnly = false) {
        const token = localStorage.getItem("access_token");
        if (!token) {
            console.log("[Authorization] Token yok, kullanıcılar yüklenemiyor");
            return;
        }

        try {
            const url = new URL(`${API_BASE}/users/list`);
            if (pendingOnly) url.searchParams.set("pending_only", "true");
            if (usersSearchTerm) url.searchParams.set("search", usersSearchTerm);
            url.searchParams.set("page", usersCurrentPage);
            url.searchParams.set("per_page", usersPerPage);

            // Firma bazlı filtreleme
            const compSel = document.getElementById('authCompanySelect');
            if (compSel && compSel.value) {
                url.searchParams.set("company_id", compSel.value);
            }

            console.log("[Authorization] Kullanıcılar yükleniyor...", url.toString());

            const response = await fetch(url, {
                headers: { "Authorization": `Bearer ${token}` }
            });

            console.log("[Authorization] Response status:", response.status);

            if (!response.ok) {
                const errorText = await response.text();
                console.error("[Authorization] Error response:", errorText);
                throw new Error("Kullanıcılar yüklenemedi");
            }

            const data = await response.json();
            console.log("[Authorization] Loaded users:", data);

            usersTotalCount = data.total || 0;

            renderUsersTable(data.users);
            updatePendingAlert(data.pending_count);
            renderUsersPagination(data.total, data.page, data.per_page);
            updateUsersTotalCount(data.total);

        } catch (error) {
            console.error("[Authorization] Error:", error);
            showToast(error.message, "error");
        }
    }

    function goToUsersPage(page) {
        usersCurrentPage = page;
        const pendingOnly = document.getElementById("filterPendingOnly")?.checked || false;
        loadUsers(pendingOnly);
    }

    function onUsersSearchInput(input) {
        // X butonunu göster/gizle
        const clearBtn = document.getElementById("usersSearchClear");
        if (clearBtn) {
            clearBtn.classList.toggle("hidden", !input.value);
        }

        // Debounce ile arama (150ms)
        clearTimeout(usersSearchDebounceTimer);
        usersSearchDebounceTimer = setTimeout(() => {
            usersSearchTerm = input.value.trim();
            usersCurrentPage = 1;
            const pendingOnly = document.getElementById("filterPendingOnly")?.checked || false;
            loadUsers(pendingOnly);
        }, 150);
    }

    function clearUsersSearch() {
        const input = document.getElementById("usersSearch");
        if (input) input.value = '';

        usersSearchTerm = '';
        usersCurrentPage = 1;

        const clearBtn = document.getElementById("usersSearchClear");
        if (clearBtn) clearBtn.classList.add("hidden");

        const pendingOnly = document.getElementById("filterPendingOnly")?.checked || false;
        loadUsers(pendingOnly);
    }

    function updateUsersTotalCount(total) {
        const el = document.getElementById("usersTotalCount");
        if (el) el.textContent = `Toplam: ${total} kullanıcı`;
    }

    function renderUsersPagination(total, page, perPage) {
        const container = document.getElementById("usersPagination");
        if (!container) return;

        const totalPages = Math.ceil(total / perPage) || 1;

        let html = `
            <button class="pg-btn" onclick="window.authorizationModule.goToUsersPage(${page - 1})" ${page === 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-left" style="font-size:9px"></i>
            </button>
            <button class="pg-btn pg-cur">${page} / ${totalPages}</button>
            <button class="pg-btn" onclick="window.authorizationModule.goToUsersPage(${page + 1})" ${page >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-right" style="font-size:9px"></i>
            </button>
        `;
        container.innerHTML = html;
    }

    async function loadOrgs() {
        const token = localStorage.getItem("access_token");
        if (!token) return;

        try {
            const response = await fetch(`${API_BASE}/organizations`, {
                headers: { "Authorization": `Bearer ${token}` }
            });
            if (!response.ok) throw new Error("Org yüklenemedi");
            const data = await response.json();
            orgs = data.organizations || [];
            console.log("[Authorization] Loaded orgs:", orgs);
        } catch (error) {
            console.error("[Authorization] Org load error:", error);
            orgs = [];
        }
    }

    // Firma selector'ı yükle
    async function loadCompanySelector() {
        const select = document.getElementById('authCompanySelect');
        if (!select) return;

        try {
            const token = localStorage.getItem('access_token') || '';
            const res = await fetch(`${API_BASE}/companies`, {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            if (!res.ok) return;
            const companies = await res.json();

            select.innerHTML = '<option value="">Tüm Firmalar</option>';
            companies.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.name;
                select.appendChild(opt);
            });

            // Firma değişince listeyi yeniden yükle
            select.addEventListener('change', () => {
                usersCurrentPage = 1;
                const pendingOnly = document.getElementById('filterPendingOnly')?.checked || false;
                loadUsers(pendingOnly);
            });
        } catch (err) {
            console.warn('[Authorization] Firma selector yüklenemedi:', err);
        }
    }

    // Sıralı yükleme - roller ve org'lar yüklenince users yükle
    async function loadAuthData() {
        await loadCompanySelector();
        await loadRoles();
        await loadOrgs();
        await loadUsers();
    }

    async function loadRoles() {
        const token = localStorage.getItem("access_token");
        if (!token) return;

        try {
            const response = await fetch(`${API_BASE}/users/roles`, {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!response.ok) throw new Error("Roller yüklenemedi");

            const data = await response.json();
            roles = data.roles;

        } catch (error) {
            console.error("[Authorization] Roles error:", error);
        }
    }

    function renderUsersTable(users) {
        const tbody = document.getElementById("usersTableBody");
        const empty = document.getElementById("usersEmpty");

        if (!users || users.length === 0) {
            tbody.innerHTML = "";
            empty?.classList.remove("hidden");
            return;
        }

        empty?.classList.add("hidden");

        tbody.innerHTML = users.map(user => {
            const initials = user.full_name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
            const statusBadge = user.is_approved
                ? (user.is_active !== false
                    ? '<span class="badge badge-green"><span class="badge-dot"></span>Aktif</span>'
                    : '<span class="badge badge-red"><span class="badge-dot"></span>Pasif</span>')
                : '<span class="badge badge-amber"><span class="badge-dot"></span>Beklemede</span>';
            const createdDate = new Date(user.created_at).toLocaleDateString("tr-TR");

            const roleOptions = roles.map(r =>
                `<option value="${r.id}" ${r.id === user.role_id ? "selected" : ""}>${r.name}</option>`
            ).join("");

            return `
                <tr data-user-id="${user.id}">
                    <td>
                        <div style="display:flex;align-items:center;gap:8px">
                            <div style="width:28px;height:28px;border-radius:50%;background:var(--grad-logo);display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-size:10px;color:#fff;flex-shrink:0">${initials}</div>
                            <span style="color:var(--text-1);font-weight:500">${user.full_name}</span>
                        </div>
                    </td>
                    <td style="font-family:'IBM Plex Mono',monospace;font-size:11.5px">${user.username}</td>
                    <td style="font-size:12px">${user.email}</td>
                    <td style="font-family:'IBM Plex Mono',monospace;font-size:11px">${createdDate}</td>
                    <td>
                        <select class="inp role-select" style="padding:4px 8px;height:auto;font-size:11.5px;width:auto" data-user-id="${user.id}">
                            ${roleOptions || '<option value="2">user</option>'}
                        </select>
                    </td>
                    <td>
                        <div style="display:flex;align-items:center;gap:5px" data-user-id="${user.id}">
                            <div class="org-badges-row" style="display:flex;gap:4px;flex-wrap:wrap">
                                ${getUserOrgBadges(user)}
                            </div>
                            <button class="act-btn edit btn-edit-orgs" data-user-id="${user.id}" title="Org Gruplarını Düzenle">
                                <i class="fa-solid fa-pen"></i>
                            </button>
                        </div>
                    </td>
                    <td>${statusBadge}</td>
                    <td>
                        <div class="action-btns">
                            ${!user.is_approved ? `
                                <button class="btn primary btn-approve" style="height:26px;font-size:11px;padding:0 10px" data-user-id="${user.id}" title="Onayla">Onayla</button>
                                <button class="act-btn del btn-reject" data-user-id="${user.id}" title="Reddet">
                                    <i class="fa-solid fa-times"></i>
                                </button>
                            ` : ''}
                            ${user.is_approved ? `
                                <button class="act-btn btn-toggle-active ${user.is_active !== false ? 'active' : 'inactive'}" data-user-id="${user.id}" data-is-active="${user.is_active !== false}" title="${user.is_active !== false ? 'Pasife Al' : 'Aktife Al'}">
                                    <i class="fa-solid ${user.is_active !== false ? 'fa-user-slash' : 'fa-user-check'}"></i>
                                </button>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

        // Event listeners
        tbody.querySelectorAll(".btn-approve").forEach(btn => {
            btn.addEventListener("click", () => handleApprove(btn.dataset.userId));
        });

        tbody.querySelectorAll(".btn-reject").forEach(btn => {
            btn.addEventListener("click", () => handleReject(btn.dataset.userId));
        });

        // Org düzenleme kalem ikonları
        tbody.querySelectorAll(".btn-edit-orgs").forEach(btn => {
            btn.addEventListener("click", () => openOrgSelectionModal(btn.dataset.userId));
        });

        // Aktif/Pasif toggle
        tbody.querySelectorAll(".btn-toggle-active").forEach(btn => {
            btn.addEventListener("click", () => handleToggleActive(btn.dataset.userId));
        });
    }

    function updatePendingAlert(count) {
        const alert = document.getElementById("pendingUsersAlert");
        const countEl = document.getElementById("pendingUsersCount");

        if (count > 0) {
            alert?.classList.remove("hidden");
            if (countEl) countEl.textContent = count;
        } else {
            alert?.classList.add("hidden");
        }
    }

    // Kullanıcının mevcut org badge'larını göster (tooltip ile uzun ad)
    function getUserOrgBadges(user) {
        // user.orgs varsa kullan, yoksa varsayılan ORG-DEFAULT
        const userOrgs = user.orgs || ['ORG-DEFAULT'];
        if (!userOrgs || userOrgs.length === 0) {
            return '<span class="badge badge-blue" title="Varsayılan Organizasyon" style="font-size:9px">ORG-DEFAULT</span>';
        }
        return userOrgs.map(orgCode => {
            // orgs listesinden uzun adı bul
            const orgDetails = orgs.find(o => o.org_code === orgCode);
            const orgName = orgDetails ? orgDetails.org_name : orgCode;
            return `<span class="badge badge-blue" title="${orgName}" style="font-size:9px">${orgCode}</span>`;
        }).join('');
    }

    // Org modal state
    let orgModalUserId = null;
    let orgModalSelectedIds = [];
    let orgModalSearchText = '';
    let orgModalPage = 1;

    // Org seçim modal'ını aç
    function openOrgSelectionModal(userId) {
        orgModalUserId = userId;
        orgModalSearchText = '';
        orgModalPage = 1;

        // Kullanıcının mevcut org'larını yükle
        const row = document.querySelector(`tr[data-user-id="${userId}"]`);

        // Önce dataset.selectedOrgs'a bak (daha önce modal'dan seçildiyse)
        if (row?.dataset?.selectedOrgs) {
            try {
                orgModalSelectedIds = JSON.parse(row.dataset.selectedOrgs);
                console.log('[openOrgSelectionModal] dataset\'ten yüklendi:', orgModalSelectedIds);
            } catch {
                orgModalSelectedIds = [];
            }
        } else {
            // Dataset yoksa, satırdaki badge'lardan org kodlarını al ve id'lere çevir
            const badges = row?.querySelectorAll('.org-badges-row .badge');
            if (badges && badges.length > 0) {
                const orgCodes = Array.from(badges).map(b => b.textContent.trim());
                orgModalSelectedIds = orgCodes.map(code => {
                    const org = orgs.find(o => o.org_code === code);
                    return org ? org.id : null;
                }).filter(id => id !== null);
                console.log('[openOrgSelectionModal] badge\'lardan yüklendi:', orgCodes, '->', orgModalSelectedIds);
            } else {
                orgModalSelectedIds = [];
            }
        }

        const modalHtml = `
            <div id="orgSelectionModal" class="org-modal-overlay">
                <div class="org-modal-container">
                    <div class="org-modal-header">
                        <h3><i class="fa-solid fa-building"></i> Org Grupları Seç</h3>
                        <label class="org-modal-filter-checkbox">
                            <input type="checkbox" id="orgModalOnlySelected">
                            Sadece seçili
                        </label>
                        <button class="org-modal-close" id="orgModalClose">
                            <i class="fa-solid fa-times"></i>
                        </button>
                    </div>
                    
                    <div class="org-modal-search">
                        <div class="org-search-box">
                            <i class="fa-solid fa-search"></i>
                            <input type="text" id="orgModalSearch" placeholder="Org kodu veya adı ile ara...">
                            <button id="orgModalSearchClear" class="org-search-clear hidden">
                                <i class="fa-solid fa-times-circle"></i>
                            </button>
                        </div>
                    </div>
                    
                    <div class="org-modal-list" id="orgModalList">
                        <div class="org-loading">
                            <i class="fa-solid fa-spinner fa-spin"></i> Yükleniyor...
                        </div>
                    </div>
                    
                    <!-- Footer - Stats ve Pagination -->
                    <div class="org-modal-footer-stats">
                        <div class="org-modal-footer-left">
                            <span class="org-total-count" id="orgModalTotalCount">Toplam: 0 kayıt</span>
                            <span class="org-selected-count" id="orgSelectedCount">0 seçili</span>
                        </div>
                        <div class="org-modal-pagination" id="orgModalPagination"></div>
                    </div>
                    
                    <!-- Footer - Buttons -->
                    <div class="org-modal-footer org-modal-footer-buttons">
                        <button class="btn-org-cancel" id="orgModalCancel">İptal</button>
                        <button class="btn-org-confirm" id="orgModalConfirm">
                            <i class="fa-solid fa-check"></i> Ekle
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Event listeners
        document.getElementById('orgModalClose').addEventListener('click', closeOrgModal);
        document.getElementById('orgModalCancel').addEventListener('click', closeOrgModal);
        document.getElementById('orgModalConfirm').addEventListener('click', confirmOrgSelection);

        const searchInput = document.getElementById('orgModalSearch');
        const clearBtn = document.getElementById('orgModalSearchClear');

        searchInput.addEventListener('input', (e) => {
            orgModalSearchText = e.target.value;
            clearBtn.classList.toggle('hidden', !orgModalSearchText);
            orgModalPage = 1;
            renderOrgModalList();
        });

        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            orgModalSearchText = '';
            clearBtn.classList.add('hidden');
            orgModalPage = 1;
            renderOrgModalList();
        });

        // Sadece seçili filtresi
        const onlySelectedCheckbox = document.getElementById('orgModalOnlySelected');
        onlySelectedCheckbox.addEventListener('change', () => {
            orgModalPage = 1;
            renderOrgModalList();
        });

        // ESC key
        document.addEventListener('keydown', orgModalEscHandler);

        // Load organizations
        renderOrgModalList();
    }

    function orgModalEscHandler(e) {
        if (e.key === 'Escape') closeOrgModal();
    }

    function closeOrgModal() {
        document.getElementById('orgSelectionModal')?.remove();
        document.removeEventListener('keydown', orgModalEscHandler);
        orgModalUserId = null;
        orgModalSelectedIds = [];
    }

    function renderOrgModalList() {
        const container = document.getElementById('orgModalList');
        if (!container) return;

        // Filter orgs
        let filteredOrgs = orgs.filter(o => o.is_active);

        // Sadece seçili filtresi
        const onlySelectedCheckbox = document.getElementById('orgModalOnlySelected');
        if (onlySelectedCheckbox && onlySelectedCheckbox.checked) {
            filteredOrgs = filteredOrgs.filter(o => orgModalSelectedIds.includes(o.id));
        }

        // Arama filtresi
        if (orgModalSearchText) {
            const search = orgModalSearchText.toLowerCase();
            filteredOrgs = filteredOrgs.filter(o =>
                o.org_code.toLowerCase().includes(search) ||
                o.org_name.toLowerCase().includes(search)
            );
        }

        // Pagination
        const perPage = 5;
        const totalPages = Math.max(1, Math.ceil(filteredOrgs.length / perPage));
        const startIdx = (orgModalPage - 1) * perPage;
        const pagedOrgs = filteredOrgs.slice(startIdx, startIdx + perPage);

        if (pagedOrgs.length === 0) {
            container.innerHTML = `
                <div class="org-empty">
                    <i class="fa-solid fa-folder-open"></i>
                    <p>Organizasyon bulunamadı</p>
                </div>
            `;
        } else {
            container.innerHTML = pagedOrgs.map(org => `
                <label class="org-modal-item">
                    <input type="checkbox" class="org-modal-checkbox" value="${org.id}" 
                           ${orgModalSelectedIds.includes(org.id) ? 'checked' : ''}>
                    <div class="org-modal-item-content">
                        <span class="org-modal-code">${org.org_code}</span>
                        <span class="org-modal-name">${org.org_name}</span>
                    </div>
                </label>
            `).join('');

            // Checkbox event listeners
            container.querySelectorAll('.org-modal-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const id = parseInt(e.target.value);
                    if (e.target.checked) {
                        if (!orgModalSelectedIds.includes(id)) {
                            orgModalSelectedIds.push(id);
                        }
                    } else {
                        orgModalSelectedIds = orgModalSelectedIds.filter(x => x !== id);
                    }
                    updateOrgSelectedCount();
                });
            });
        }

        // Pagination buttons - TEK SAYFA DAHİ OLSA GÖSTER
        const pagContainer = document.getElementById('orgModalPagination');
        let pagHtml = '';
        for (let i = 1; i <= totalPages; i++) {
            pagHtml += `<button class="org-pag-btn ${i === orgModalPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
        }
        pagContainer.innerHTML = pagHtml;
        pagContainer.querySelectorAll('.org-pag-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                orgModalPage = parseInt(btn.dataset.page);
                renderOrgModalList();
            });
        });

        updateOrgSelectedCount(filteredOrgs.length);
    }

    function updateOrgSelectedCount(total) {
        const countEl = document.getElementById('orgSelectedCount');
        const totalEl = document.getElementById('orgModalTotalCount');

        if (countEl) {
            countEl.textContent = `${orgModalSelectedIds.length} seçili`;
        }
        if (totalEl && total !== undefined) {
            totalEl.textContent = `Toplam: ${total} kayıt`;
        }
    }

    async function confirmOrgSelection() {
        if (orgModalSelectedIds.length === 0) {
            showToast('En az bir org grubu seçin', 'warning');
            return;
        }

        console.log('[confirmOrgSelection] selectedIds:', orgModalSelectedIds, 'userId:', orgModalUserId);

        // Backend API çağrısı - veritabanına kaydet
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/users/${orgModalUserId}/organizations`, {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ org_ids: orgModalSelectedIds })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Güncelleme hatası');
            }

            const result = await response.json();
            console.log('[confirmOrgSelection] API result:', result);

            // Row'daki badge'ları güncelle
            const row = document.querySelector(`tr[data-user-id="${orgModalUserId}"]`);
            if (row) {
                row.dataset.selectedOrgs = JSON.stringify(orgModalSelectedIds);

                // Badge'ları güncelle
                const badgesRow = row.querySelector('.org-badges-row');
                if (badgesRow) {
                    const selectedOrgCodes = orgModalSelectedIds.map(id => {
                        const org = orgs.find(o => o.id === id);
                        return org ? org.org_code : '';
                    }).filter(Boolean);

                    badgesRow.innerHTML = selectedOrgCodes.map(code => {
                        const orgDetails = orgs.find(o => o.org_code === code);
                        const orgName = orgDetails ? orgDetails.org_name : code;
                        return `<span class="badge badge-blue" title="${orgName}" style="font-size:9px">${code}</span>`;
                    }).join('');
                }
            }

            showToast(`${orgModalSelectedIds.length} org grubu kaydedildi`, 'success');

        } catch (error) {
            console.error('[confirmOrgSelection] API error:', error);
            showToast(error.message || 'Org kaydetme hatası', 'error');
            return;
        }

        // Modal'ı kapat
        closeOrgModal();
    }

    function getSelectedOrgIds(row, isAdmin) {
        // Önce modal'dan seçilen org'lara bak
        const selectedOrgsData = row?.dataset?.selectedOrgs;
        if (selectedOrgsData) {
            try {
                const parsed = JSON.parse(selectedOrgsData);
                if (parsed && parsed.length > 0) return parsed;
            } catch { }
        }

        // Fallback: admin için ORG-ADMIN (id=2), user için ORG-DEFAULT (id=1)
        return isAdmin ? [2] : [1];
    }

    async function handleApprove(userId) {
        const token = localStorage.getItem("access_token");
        const row = document.querySelector(`tr[data-user-id="${userId}"]`);
        const roleSelect = row?.querySelector(".role-select");
        const roleId = parseInt(roleSelect?.value || 2);
        const isAdmin = roleId === 1; // admin role_id = 1

        // Org seçilmiş mi kontrol et
        const orgIds = getSelectedOrgIds(row, isAdmin);

        // Eğer orgIds sadece fallback (ORG-DEFAULT/ORG-ADMIN) ise ve kullanıcı pending ise
        // uyarı göster ve org modal'ını aç
        const hasExplicitOrgSelection = row?.dataset?.selectedOrgs;
        if (!hasExplicitOrgSelection) {
            // Kullanıcıya org seçmesi gerektiğini bildir
            showToast('⚠️ Önce organizasyon grubu seçin! Kalem ikonuna tıklayıp org seçip "Ekle" butonuna basın.', 'warning');
            return;
        }

        try {
            const response = await fetch(`${API_BASE}/users/approve`, {
                method: "POST",
                headers: {
                    "Authorization": `Bearer ${token}`,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    user_id: parseInt(userId),
                    role_id: roleId,
                    is_admin: isAdmin,
                    org_ids: orgIds
                })
            });

            if (!response.ok) throw new Error("Onaylama başarısız");

            showToast("Kullanıcı onaylandı", "success");
            loadUsers(document.getElementById("filterPendingOnly")?.checked);

        } catch (error) {
            console.error("[Authorization] Approve error:", error);
            showToast(error.message, "error");
        }
    }

    async function handleReject(userId) {
        VyraModal.danger({
            title: 'Kullanıcıyı Reddet',
            message: 'Bu kullanıcıyı reddetmek istediğinize emin misiniz? Bu işlem geri alınamaz.',
            confirmText: 'Reddet',
            cancelText: 'İptal',
            onConfirm: async () => {
                const token = localStorage.getItem("access_token");

                try {
                    const response = await fetch(`${API_BASE}/users/reject`, {
                        method: "POST",
                        headers: {
                            "Authorization": `Bearer ${token}`,
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ user_id: parseInt(userId) })
                    });

                    if (!response.ok) throw new Error("Reddetme başarısız");

                    showToast("Kullanıcı reddedildi", "success");
                    loadUsers(document.getElementById("filterPendingOnly")?.checked);

                } catch (error) {
                    console.error("[Authorization] Reject error:", error);
                    showToast(error.message, "error");
                }
            }
        });
    }

    // ---- Toggle Active/Passive ----
    function showConfirmModal({ title, message, icon, iconType, confirmText, confirmClass, onConfirm }) {
        // Mevcut modal varsa kaldır
        document.querySelector(".confirm-modal-overlay")?.remove();

        const overlay = document.createElement("div");
        overlay.className = "confirm-modal-overlay";
        overlay.innerHTML = `
            <div class="confirm-modal">
                <div class="confirm-modal-icon ${iconType}">${icon}</div>
                <div class="confirm-modal-title">${title}</div>
                <div class="confirm-modal-message">${message}</div>
                <div class="confirm-modal-actions">
                    <button class="confirm-modal-btn-cancel" id="confirmModalCancel">İptal</button>
                    <button class="confirm-modal-btn-confirm ${confirmClass}" id="confirmModalOk">${confirmText}</button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add("visible"));

        const close = () => {
            overlay.classList.remove("visible");
            setTimeout(() => overlay.remove(), 200);
        };

        overlay.querySelector("#confirmModalCancel").addEventListener("click", close);
        overlay.querySelector("#confirmModalOk").addEventListener("click", () => {
            close();
            onConfirm();
        });

        // ESC ile kapat
        const escHandler = (e) => {
            if (e.key === "Escape") { close(); document.removeEventListener("keydown", escHandler); }
        };
        document.addEventListener("keydown", escHandler);
    }

    async function handleToggleActive(userId) {
        const token = localStorage.getItem("access_token");
        if (!token) return;

        const row = document.querySelector(`tr[data-user-id="${userId}"]`);
        const toggleBtn = row?.querySelector(".btn-toggle-active");
        const isCurrentlyActive = toggleBtn?.dataset.isActive === "true";
        const username = (row?.querySelector("td:nth-child(2)")?.textContent?.trim() || "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

        showConfirmModal({
            title: isCurrentlyActive ? "Kullanıcıyı Pasife Al" : "Kullanıcıyı Aktife Al",
            message: `<strong>${username}</strong> kullanıcısını ${isCurrentlyActive ? "pasife almak" : "aktife almak"} istediğinize emin misiniz?`,
            icon: isCurrentlyActive ? "⏸️" : "▶️",
            iconType: isCurrentlyActive ? "warning" : "success",
            confirmText: isCurrentlyActive ? "Pasife Al" : "Aktife Al",
            confirmClass: isCurrentlyActive ? "danger" : "success",
            onConfirm: async () => {
                try {
                    const response = await fetch(`${API_BASE}/users/${userId}/toggle-active`, {
                        method: "PUT",
                        headers: {
                            "Authorization": `Bearer ${token}`,
                            "Content-Type": "application/json"
                        }
                    });

                    if (!response.ok) {
                        const err = await response.json();
                        throw new Error(err.detail || "İşlem başarısız");
                    }

                    const data = await response.json();
                    showToast(data.message, "success");
                    loadUsers(document.getElementById("filterPendingOnly")?.checked);

                } catch (error) {
                    console.error("[Authorization] Toggle active error:", error);
                    showToast(error.message, "error");
                }
            }
        })
    }

    // ---- Profile Functions ----
    async function loadProfile() {
        const token = localStorage.getItem("access_token");
        if (!token) return;

        try {
            const response = await fetch(`${API_BASE}/users/me`, {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!response.ok) throw new Error("Profil yüklenemedi");

            const profile = await response.json();
            renderProfile(profile);

        } catch (error) {
            console.error("[Profile] Error:", error);
        }
    }

    function renderProfile(profile) {
        // Sidebar
        document.getElementById("profileFullName").textContent = profile.full_name;
        document.getElementById("profileRole").textContent = profile.role_name;

        const statusEl = document.getElementById("profileStatus");
        if (statusEl) {
            statusEl.textContent = profile.is_approved ? "AKTİF" : "ONAY BEKLİYOR";
            statusEl.className = "profile-status " + (profile.is_approved ? "status-active" : "status-pending");
        }

        // Avatar
        const avatarContainer = document.getElementById("profileAvatarContainer");
        if (avatarContainer && profile.avatar) {
            avatarContainer.innerHTML = `<img src="${profile.avatar}" alt="Avatar" class="profile-avatar-img" />`;
        }

        // Form fields
        document.getElementById("profileEditFullName").value = profile.full_name;
        document.getElementById("profileUsername").value = profile.username;
        document.getElementById("profileEditEmail").value = profile.email;
        document.getElementById("profileEditPhone").value = profile.phone;

        // ---- LDAP Kullanıcı Kontrolü ----
        const isLdap = profile.auth_type === "ldap";

        // Kurumsal bilgiler bölümü
        const ldapSection = document.getElementById("ldapCorporateSection");
        if (ldapSection) {
            if (isLdap) {
                ldapSection.classList.remove("hidden");
                document.getElementById("profileAuthType").value = "🔗 LDAP / Active Directory";
                document.getElementById("profileDomain").value = profile.domain || "-";
                document.getElementById("profileDepartment").value = profile.department || "-";
                document.getElementById("profileTitle").value = profile.title || "-";
            } else {
                ldapSection.classList.add("hidden");
            }
        }

        // LDAP uyarı banner
        const ldapNotice = document.getElementById("ldapProfileNotice");
        if (ldapNotice) ldapNotice.classList.toggle("hidden", !isLdap);

        // LDAP ise kişisel bilgiler disabled + kaydet gizle
        const editableFields = ["profileEditFullName", "profileEditEmail", "profileEditPhone"];
        editableFields.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = isLdap;
        });

        const btnSave = document.getElementById("btnSaveProfile");
        if (btnSave) btnSave.classList.toggle("hidden", isLdap);

        // LDAP ise şifre bölümü gizle
        const passwordField = document.getElementById("currentPassword");
        const passwordSection = passwordField ? passwordField.closest(".card") : null;
        if (passwordSection) {
            passwordSection.classList.toggle("hidden", isLdap);
        }
    }

    async function uploadAvatar(file) {
        const token = localStorage.getItem("access_token");

        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64 = e.target.result;

            try {
                const response = await fetch(`${API_BASE}/users/me/avatar`, {
                    method: "PUT",
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ avatar: base64 })
                });

                if (!response.ok) throw new Error("Avatar yüklenemedi");

                showToast("Avatar güncellendi", "success");
                loadProfile();

            } catch (error) {
                console.error("[Profile] Avatar error:", error);
                showToast(error.message, "error");
            }
        };
        reader.readAsDataURL(file);
    }

    async function saveProfile() {
        const token = localStorage.getItem("access_token");

        const payload = {
            full_name: document.getElementById("profileEditFullName").value.trim(),
            email: document.getElementById("profileEditEmail").value.trim(),
            phone: document.getElementById("profileEditPhone").value.trim()
        };

        if (!payload.full_name || !payload.email || !payload.phone) {
            showToast("Lütfen tüm alanları doldurun", "error");
            return;
        }

        try {
            const response = await fetch(`${API_BASE}/users/me`, {
                method: "PUT",
                headers: {
                    "Authorization": `Bearer ${token}`,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || "Güncelleme başarısız");
            }

            showToast("Profil güncellendi", "success");
            loadProfile();

        } catch (error) {
            console.error("[Profile] Save error:", error);
            showToast(error.message, "error");
        }
    }

    async function changePassword() {
        const token = localStorage.getItem("access_token");

        const currentPassword = document.getElementById("currentPassword").value;
        const newPassword = document.getElementById("newPassword").value;
        const newPasswordConfirm = document.getElementById("newPasswordConfirm").value;

        if (!currentPassword || !newPassword || !newPasswordConfirm) {
            showToast("Lütfen tüm şifre alanlarını doldurun", "error");
            return;
        }

        if (newPassword !== newPasswordConfirm) {
            showToast("Yeni şifreler eşleşmiyor", "error");
            return;
        }

        if (newPassword.length < 8) {
            showToast("Yeni şifre en az 8 karakter olmalı", "error");
            return;
        }

        try {
            const response = await fetch(`${API_BASE}/users/me/change-password`, {
                method: "POST",
                headers: {
                    "Authorization": `Bearer ${token}`,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword
                })
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || "Şifre değiştirme başarısız");
            }

            showToast("Şifre değiştirildi", "success");

            // Clear fields
            document.getElementById("currentPassword").value = "";
            document.getElementById("newPassword").value = "";
            document.getElementById("newPasswordConfirm").value = "";

        } catch (error) {
            console.error("[Profile] Password change error:", error);
            showToast(error.message, "error");
        }
    }

    // ---- Toast Helper ----
    function showToast(message, type = "info") {
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`[Toast ${type}] ${message}`);
        }
    }

    // ---- Check Admin Access ----
    function checkAdminAccess() {
        const token = localStorage.getItem("access_token");
        if (!token) return false;

        try {
            const payload = JSON.parse(atob(token.split(".")[1]));
            return payload.role === "admin" || payload.is_admin === true;
        } catch {
            return false;
        }
    }

    // ---- Initialize ----
    function init() {
        // Authorization tabs
        const tabUsersList = document.getElementById('tabUsersList');
        const tabRolePermissions = document.getElementById('tabRolePermissions');
        const contentUsersList = document.getElementById('contentUsersList');
        const contentRolePermissions = document.getElementById('contentRolePermissions');

        if (tabUsersList && tabRolePermissions) {
            tabUsersList.addEventListener('click', () => {
                tabUsersList.classList.add('active');
                tabRolePermissions.classList.remove('active');
                contentUsersList?.classList.remove('hidden');
                contentRolePermissions?.classList.add('hidden');
            });

            tabRolePermissions.addEventListener('click', () => {
                tabRolePermissions.classList.add('active');
                tabUsersList.classList.remove('active');
                contentRolePermissions?.classList.remove('hidden');
                contentUsersList?.classList.add('hidden');

                // PermissionsManager'ı tetikle
                if (window.PermissionsManager) {
                    window.PermissionsManager.loadRolePermissions('user');
                }
            });
        }

        // Authorization events
        document.getElementById("btnRefreshUsers")?.addEventListener("click", () => {
            loadUsers(document.getElementById("filterPendingOnly")?.checked);
        });

        document.getElementById("filterPendingOnly")?.addEventListener("change", (e) => {
            loadUsers(e.target.checked);
        });

        // Profile events
        document.getElementById("btnSaveProfile")?.addEventListener("click", saveProfile);
        document.getElementById("btnChangePassword")?.addEventListener("click", changePassword);

        // Avatar events
        const btnChangeAvatar = document.getElementById("btnChangeAvatar");
        const avatarInput = document.getElementById("avatarInput");

        btnChangeAvatar?.addEventListener("click", () => {
            avatarInput?.click();
        });

        avatarInput?.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (file) {
                if (file.size > 2 * 1024 * 1024) {
                    showToast("Avatar dosyası 2MB'den küçük olmalı", "error");
                    return;
                }
                uploadAvatar(file);
            }
        });

        // Show admin menu if admin
        if (checkAdminAccess()) {
            document.getElementById("menuAuthorization")?.classList.remove("hidden");
            document.getElementById("menuOrganizations")?.classList.remove("hidden");
        }
    }

    // Export functions
    window.authorizationModule = {
        loadUsers,
        loadRoles,
        loadOrgs,
        loadAuthData,  // Tek fonksiyonla sıralı yükleme
        loadProfile,
        checkAdminAccess,
        goToUsersPage,  // Pagination için
        onUsersSearchInput,  // Arama debounce
        clearUsersSearch,    // Arama temizle
        init
    };

    // Auto-init on DOM ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
