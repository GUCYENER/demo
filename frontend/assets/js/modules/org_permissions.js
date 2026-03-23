/* ─────────────────────────────────────────────────
   NGSSAI — Organization Permissions Module
   Parametreler → Organizasyon Yetki sekmesi
   Domain ↔ Organizasyon yetki CRUD yönetimi
   v2.46.0
   ───────────────────────────────────────────────── */

window.OrgPermissionsModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';
    const ENDPOINT = `${API_BASE}/api/domain-org-permissions`;

    // Düzenleme modu state
    let editingId = null;

    // ── HTML Escape (XSS koruması) ──
    function _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    // ── Load & Render ──
    let _currentCompanyId = null;

    async function load(companyId) {
        _currentCompanyId = companyId || null;
        try {
            const token = localStorage.getItem('access_token');
            let url = ENDPOINT;
            if (companyId) url += `?company_id=${companyId}`;
            const resp = await fetch(url, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const data = await resp.json();
            renderTable(data);
        } catch (err) {
            console.error('[OrgPermissions] Load error:', err);
            renderEmpty('Veriler yüklenirken hata oluştu');
        }
    }

    function renderTable(rows) {
        const tbody = document.getElementById('orgPermissionsBody');
        if (!tbody) return;

        if (!rows || rows.length === 0) {
            renderEmpty();
            return;
        }

        let html = '';
        let lastDomain = '';

        rows.forEach(row => {
            const isNewDomain = row.domain !== lastDomain;
            const groupClass = isNewDomain ? 'domain-group-first' : '';
            lastDomain = row.domain;

            html += `
                <tr class="${groupClass}" data-id="${parseInt(row.id, 10)}">
                    <td>
                        ${isNewDomain
                    ? `<span class="org-perm-domain-badge">
                                 <i class="fa-solid fa-network-wired"></i>
                                 ${_esc(row.domain)}
                               </span>`
                    : `<span class="org-perm-domain-badge" style="opacity: 0.3;">
                                 ${_esc(row.domain)}
                               </span>`
                }
                    </td>
                    <td>
                        <span class="org-perm-org-badge">
                            <i class="fa-solid fa-building"></i>
                            ${_esc(row.org_code)}
                        </span>
                    </td>
                    <td class="text-muted">${_esc(row.description || '-')}</td>
                    <td style="text-align: center;">
                        <div class="org-perm-actions">
                            <button class="btn-edit-org"
                                    data-id="${parseInt(row.id, 10)}"
                                    data-domain="${_esc(row.domain)}"
                                    data-org="${_esc(row.org_code)}"
                                    data-desc="${_esc(row.description || '')}"
                                    title="Düzenle">
                                <i class="fa-solid fa-pen"></i>
                            </button>
                            <button class="btn-delete-org"
                                    data-id="${parseInt(row.id, 10)}"
                                    title="Sil">
                                <i class="fa-solid fa-trash-can"></i>
                            </button>
                        </div>
                    </td>
                </tr>`;
        });

        tbody.innerHTML = html;

        // Event listeners
        tbody.querySelectorAll('.btn-delete-org').forEach(btn => {
            btn.addEventListener('click', () => handleDelete(btn.dataset.id));
        });
        tbody.querySelectorAll('.btn-edit-org').forEach(btn => {
            btn.addEventListener('click', () => startEdit(btn));
        });
    }

    function renderEmpty(msg) {
        const tbody = document.getElementById('orgPermissionsBody');
        if (!tbody) return;

        tbody.innerHTML = `
            <tr>
                <td colspan="4">
                    <div class="org-perm-empty">
                        <i class="fa-solid fa-shield-halved"></i>
                        <p>${_esc(msg || 'Henüz domain-organizasyon yetkisi tanımlanmamış')}</p>
                        <small>Yukarıdaki formu kullanarak yeni yetki ekleyebilirsiniz.</small>
                    </div>
                </td>
            </tr>`;
    }

    // ── Edit ──
    function startEdit(btn) {
        const id = btn.dataset.id;
        const domain = btn.dataset.domain;
        const org = btn.dataset.org;
        const desc = btn.dataset.desc;

        editingId = id;

        // Form alanlarını doldur
        const domainInput = document.getElementById('orgPermDomain');
        const orgInput = document.getElementById('orgPermOrgCode');
        const descInput = document.getElementById('orgPermDescription');
        const addBtn = document.getElementById('btnAddOrgPerm');
        const formTitle = document.getElementById('orgPermFormTitle');

        if (domainInput) domainInput.value = domain;
        if (orgInput) orgInput.value = org;
        if (descInput) descInput.value = desc;

        // Buton ve başlık güncelle
        if (addBtn) {
            addBtn.innerHTML = '<i class="fa-solid fa-save"></i> Güncelle';
            addBtn.classList.add('btn-update-mode');
        }
        if (formTitle) {
            formTitle.innerHTML = '<i class="fa-solid fa-pen-to-square"></i> Yetki Düzenle';
        }

        // İptal butonu göster
        showCancelBtn(true);

        // Satırı vurgula
        const tbody = document.getElementById('orgPermissionsBody');
        if (tbody) {
            tbody.querySelectorAll('tr').forEach(tr => tr.classList.remove('editing-row'));
            const editRow = tbody.querySelector(`tr[data-id="${id}"]`);
            if (editRow) editRow.classList.add('editing-row');
        }

        // Form'a odaklan
        if (domainInput) domainInput.focus();
    }

    function cancelEdit() {
        editingId = null;

        const domainInput = document.getElementById('orgPermDomain');
        const orgInput = document.getElementById('orgPermOrgCode');
        const descInput = document.getElementById('orgPermDescription');
        const addBtn = document.getElementById('btnAddOrgPerm');
        const formTitle = document.getElementById('orgPermFormTitle');

        if (domainInput) domainInput.value = '';
        if (orgInput) orgInput.value = '';
        if (descInput) descInput.value = '';

        if (addBtn) {
            addBtn.innerHTML = '<i class="fa-solid fa-plus"></i> Ekle';
            addBtn.classList.remove('btn-update-mode');
        }
        if (formTitle) {
            formTitle.innerHTML = '<i class="fa-solid fa-plus-circle"></i> Yeni Domain-Organizasyon Yetkisi Ekle';
        }

        showCancelBtn(false);

        // Satır vurgusunu kaldır
        const tbody = document.getElementById('orgPermissionsBody');
        if (tbody) {
            tbody.querySelectorAll('tr').forEach(tr => tr.classList.remove('editing-row'));
        }
    }

    function showCancelBtn(show) {
        let cancelBtn = document.getElementById('btnCancelOrgEdit');
        if (show && !cancelBtn) {
            const addBtn = document.getElementById('btnAddOrgPerm');
            if (addBtn) {
                cancelBtn = document.createElement('button');
                cancelBtn.id = 'btnCancelOrgEdit';
                cancelBtn.className = 'btn-cancel-edit';
                cancelBtn.innerHTML = '<i class="fa-solid fa-xmark"></i> İptal';
                cancelBtn.addEventListener('click', cancelEdit);
                addBtn.parentNode.insertBefore(cancelBtn, addBtn.nextSibling);
            }
        } else if (!show && cancelBtn) {
            cancelBtn.remove();
        }
    }

    // ── Add / Update ──
    async function handleAddOrUpdate() {
        const domainInput = document.getElementById('orgPermDomain');
        const orgInput = document.getElementById('orgPermOrgCode');
        const descInput = document.getElementById('orgPermDescription');

        const domain = (domainInput?.value || '').trim().toUpperCase();
        const orgCode = (orgInput?.value || '').trim().toUpperCase();
        const description = (descInput?.value || '').trim();

        if (!domain || !orgCode) {
            showToast('Domain ve Organizasyon alanları zorunludur.', 'error');
            return;
        }

        const addBtn = document.getElementById('btnAddOrgPerm');
        if (addBtn) { addBtn.disabled = true; }

        try {
            const token = localStorage.getItem('access_token');
            const isUpdate = editingId !== null;
            const url = isUpdate ? `${ENDPOINT}/${editingId}` : ENDPOINT;
            const method = isUpdate ? 'PUT' : 'POST';

            const payload = { domain, org_code: orgCode, description };
            if (_currentCompanyId) {
                payload.company_id = _currentCompanyId;
            }

            const resp = await fetch(url, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify(payload),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }

            cancelEdit(); // Formu temizle ve normal moda dön
            showToast(
                isUpdate
                    ? `${domain} / ${orgCode} güncellendi.`
                    : `${domain} / ${orgCode} yetkisi eklendi.`,
                'success'
            );
            await load(_currentCompanyId);
        } catch (err) {
            console.error('[OrgPermissions] Save error:', err);
            showToast(err.message || 'İşlem başarısız.', 'error');
        } finally {
            if (addBtn) { addBtn.disabled = false; }
        }
    }

    // ── Delete ──
    async function handleDelete(id) {
        VyraModal.danger({
            title: 'Yetki Kaydını Sil',
            message: 'Bu yetki kaydını silmek istediğinize emin misiniz?',
            confirmText: 'Sil',
            cancelText: 'İptal',
            onConfirm: async () => {
                try {
                    const token = localStorage.getItem('access_token');
                    const resp = await fetch(`${ENDPOINT}/${id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${token}` },
                    });

                    if (!resp.ok && resp.status !== 204) {
                        throw new Error(`HTTP ${resp.status}`);
                    }

                    // Eğer silinen satır düzenleniyorsa iptal et
                    if (editingId === String(id)) cancelEdit();

                    showToast('Yetki kaydı silindi.', 'success');
                    await load();
                } catch (err) {
                    console.error('[OrgPermissions] Delete error:', err);
                    showToast('Silme başarısız.', 'error');
                }
            }
        });
    }

    // ── Toast Helper ──
    function showToast(message, type) {
        if (window.NgssNotification) {
            if (type === 'error') {
                NgssNotification.error('İşlem Hatası', message);
            } else if (type === 'success') {
                NgssNotification.success('Başarılı', message);
            } else {
                NgssNotification.warning('Uyarı', message);
            }
        } else {
            console.log(`[OrgPermissions] ${type}: ${message}`);
        }
    }

    // ── Init ──
    function init() {
        const addBtn = document.getElementById('btnAddOrgPerm');
        if (addBtn) {
            addBtn.addEventListener('click', handleAddOrUpdate);
        }

        // Enter tuşu ile ekleme/güncelleme
        ['orgPermDomain', 'orgPermOrgCode', 'orgPermDescription'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        handleAddOrUpdate();
                    }
                    if (e.key === 'Escape' && editingId) {
                        cancelEdit();
                    }
                });
            }
        });
    }

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { load, init };
})();
