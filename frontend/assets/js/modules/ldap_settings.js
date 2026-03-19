/**
 * VYRA - LDAP Settings Module
 * Admin panelinden LDAP sunucu ayarlarının CRUD yönetimi.
 * v2.46.0
 * @module LdapSettingsModule
 */
window.LdapSettingsModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || 'http://localhost:8002';
    let editingId = null;
    let domainOrgData = []; // domain_org_permissions cache

    // ---------------------------------------------------------
    //  Helper: HTML escape (XSS koruması)
    // ---------------------------------------------------------
    function _esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(String(str)));
        return div.innerHTML;
    }

    // ---------------------------------------------------------
    //  Helper: Auth header
    // ---------------------------------------------------------
    function authHeaders() {
        const token = localStorage.getItem('access_token');
        return {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        };
    }

    // ---------------------------------------------------------
    //  Load LDAP Settings List
    // ---------------------------------------------------------
    async function load(companyId) {
        try {
            let url = `${API_BASE}/api/ldap-settings`;
            if (companyId) url += `?company_id=${companyId}`;
            const response = await fetch(url, {
                headers: authHeaders()
            });
            if (!response.ok) throw new Error('LDAP ayarları yüklenemedi');

            const data = await response.json();
            renderTable(data.settings || []);
        } catch (err) {
            console.error('[LDAP] Load error:', err);
            if (window.showToast) window.showToast('LDAP ayarları yüklenemedi', 'error');
        }
    }

    // ---------------------------------------------------------
    //  Render Table
    // ---------------------------------------------------------
    function renderTable(settings) {
        const tbody = document.getElementById('ldapSettingsBody');
        if (!tbody) return;

        if (!settings.length) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">
                        <i class="fa-solid fa-inbox"></i>
                        Henüz LDAP sunucu tanımlanmamış
                    </td>
                </tr>`;
            return;
        }

        tbody.innerHTML = settings.map(s => `
            <tr>
                <td><span class="org-code-badge">${_esc(s.domain)}</span></td>
                <td>${_esc(s.display_name)}</td>
                <td class="text-mono">${_esc(s.url)}</td>
                <td class="text-mono text-sm">${_esc(s.search_base)}</td>
                <td>
                    <span class="status-badge ${s.enabled ? 'active' : 'inactive'}">
                        ${s.enabled ? 'Aktif' : 'Pasif'}
                    </span>
                </td>
                <td class="actions-cell">
                    <button class="btn-icon btn-test" title="Bağlantı Testi" onclick="LdapSettingsModule.testConnection(${parseInt(s.id, 10)})">
                        <i class="fa-solid fa-plug-circle-check"></i>
                    </button>
                    <button class="btn-icon btn-edit" title="Düzenle" onclick="LdapSettingsModule.openEdit(${parseInt(s.id, 10)})">
                        <i class="fa-solid fa-pen"></i>
                    </button>
                    <button class="btn-icon btn-delete" title="Sil" onclick="LdapSettingsModule.deleteSetting(${parseInt(s.id, 10)}, '${_esc(s.domain)}')">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    }

    // ---------------------------------------------------------
    //  Fetch domain-org data from domain_org_permissions
    // ---------------------------------------------------------
    async function fetchDomainOrgs() {
        try {
            const resp = await fetch(`${API_BASE}/api/domain-org-permissions`, {
                headers: authHeaders()
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            domainOrgData = await resp.json();
        } catch (err) {
            console.warn('[LDAP] domain-org-permissions yukleme hatasi:', err);
            domainOrgData = [];
        }
    }

    function populateDomainDropdown(selectedDomain) {
        const sel = document.getElementById('ldapDomain');
        if (!sel) return;

        // Distinct domain'leri bul
        const domains = [...new Set(domainOrgData.map(d => d.domain))];

        sel.innerHTML = '<option value="">-- Domain Se\u00e7in --</option>';
        domains.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d;
            opt.textContent = d;
            if (d === selectedDomain) opt.selected = true;
            sel.appendChild(opt);
        });
    }

    function renderOrgCheckboxes(domain, selectedOrgs) {
        const container = document.getElementById('ldapAllowedOrgsContainer');
        if (!container) return;

        const orgs = domainOrgData.filter(d => d.domain === domain).map(d => d.org_code);

        if (!domain || orgs.length === 0) {
            container.innerHTML = '<div class="ldap-org-empty">Domain se\u00e7ildi\u011finde organizasyonlar y\u00fcklenecek</div>';
            return;
        }

        const selected = selectedOrgs || [];
        container.innerHTML = orgs.map(org => {
            const checked = selected.includes(org) ? 'checked' : '';
            return `
                <label class="ldap-org-checkbox-item">
                    <input type="checkbox" name="ldapOrgCheck" value="${_esc(org)}" ${checked}>
                    <span class="ldap-org-checkbox-label">
                        <i class="fa-solid fa-building"></i> ${_esc(org)}
                    </span>
                </label>`;
        }).join('');
    }

    function getSelectedOrgs() {
        const checks = document.querySelectorAll('input[name="ldapOrgCheck"]:checked');
        return Array.from(checks).map(c => c.value);
    }

    // ---------------------------------------------------------
    //  Open Create Modal
    // ---------------------------------------------------------
    async function openCreate() {
        editingId = null;
        const titleEl = document.getElementById('ldapModalTitle');
        if (titleEl) titleEl.innerHTML = '<i class="fa-solid fa-network-wired"></i> Yeni LDAP Sunucu';

        await fetchDomainOrgs();
        populateDomainDropdown('');
        renderOrgCheckboxes('', []);

        // Firma dropdown'ı doldur
        const compSel = document.getElementById('ldapCompanyId');
        if (compSel && window.populateCompanySelect) {
            await window.populateCompanySelect(compSel, null);
            // Global selector'dan öntanımlı firma
            const globalSel = document.getElementById('globalCompanySelect');
            if (globalSel && globalSel.value) compSel.value = globalSel.value;
        }

        // Form temizle
        const domainSel = document.getElementById('ldapDomain');
        if (domainSel) { domainSel.value = ''; domainSel.disabled = false; }
        document.getElementById('ldapDisplayName').value = '';
        document.getElementById('ldapUrl').value = '';
        document.getElementById('ldapBindDn').value = '';
        document.getElementById('ldapBindPassword').value = '';
        document.getElementById('ldapSearchBase').value = '';
        document.getElementById('ldapSearchFilter').value = '(sAMAccountName={{username}})';
        document.getElementById('ldapUseSsl').value = 'false';
        document.getElementById('ldapEnabled').value = 'true';
        document.getElementById('ldapTimeout').value = '10';

        const hint = document.getElementById('ldapPasswordHint');
        if (hint) hint.classList.add('hidden');

        const modal = document.getElementById('ldapSettingModal');
        if (modal) modal.classList.remove('hidden');
    }

    // ---------------------------------------------------------
    //  Open Edit Modal
    // ---------------------------------------------------------
    async function openEdit(id) {
        editingId = id;

        try {
            await fetchDomainOrgs();

            // Listedeki verileri kullan
            const response = await fetch(`${API_BASE}/api/ldap-settings`, {
                headers: authHeaders()
            });
            const data = await response.json();
            const setting = (data.settings || []).find(s => s.id === id);

            if (!setting) {
                if (window.showToast) window.showToast('LDAP ayari bulunamadi', 'error');
                return;
            }

            // Firma dropdown'ı doldur (setting tanımlandıktan SONRA)
            const compSel = document.getElementById('ldapCompanyId');
            if (compSel && window.populateCompanySelect) {
                await window.populateCompanySelect(compSel, setting.company_id || null);
            }

            const titleEl = document.getElementById('ldapModalTitle');
            if (titleEl) titleEl.innerHTML = `<i class="fa-solid fa-network-wired"></i> ${_esc(setting.domain)} D\u00fczenle`;

            populateDomainDropdown(setting.domain);
            const domainSel = document.getElementById('ldapDomain');
            if (domainSel) { domainSel.value = setting.domain; domainSel.disabled = true; }
            renderOrgCheckboxes(setting.domain, setting.allowed_orgs || []);

            document.getElementById('ldapDisplayName').value = setting.display_name;
            document.getElementById('ldapUrl').value = setting.url;
            document.getElementById('ldapBindDn').value = setting.bind_dn;
            document.getElementById('ldapBindPassword').value = '';
            document.getElementById('ldapSearchBase').value = setting.search_base;
            document.getElementById('ldapSearchFilter').value = setting.search_filter || '(sAMAccountName={{username}})';
            document.getElementById('ldapUseSsl').value = setting.use_ssl ? 'true' : 'false';
            document.getElementById('ldapEnabled').value = setting.enabled ? 'true' : 'false';
            document.getElementById('ldapTimeout').value = setting.timeout || '10';

            // Sifre ipucu
            const hint = document.getElementById('ldapPasswordHint');
            if (hint) {
                if (setting.bind_password_set) {
                    hint.classList.remove('hidden');
                } else {
                    hint.classList.add('hidden');
                }
            }

            const modal = document.getElementById('ldapSettingModal');
            if (modal) modal.classList.remove('hidden');

        } catch (err) {
            console.error('[LDAP] Edit load error:', err);
            if (window.showToast) window.showToast('LDAP ayari yuklenemedi', 'error');
        }
    }

    // ---------------------------------------------------------
    //  Close Modal
    // ---------------------------------------------------------
    function closeModal() {
        const modal = document.getElementById('ldapSettingModal');
        if (modal) modal.classList.add('hidden');
        editingId = null;
    }

    // ---------------------------------------------------------
    //  Save (Create or Update)
    // ---------------------------------------------------------
    async function save() {
        const domain = document.getElementById('ldapDomain').value.trim().toUpperCase();
        const displayName = document.getElementById('ldapDisplayName').value.trim();
        const url = document.getElementById('ldapUrl').value.trim();
        const bindDn = document.getElementById('ldapBindDn').value.trim();
        const bindPassword = document.getElementById('ldapBindPassword').value;
        const searchBase = document.getElementById('ldapSearchBase').value.trim();
        const searchFilter = document.getElementById('ldapSearchFilter').value.trim();
        const allowedOrgs = getSelectedOrgs();
        const useSsl = document.getElementById('ldapUseSsl').value === 'true';
        const enabled = document.getElementById('ldapEnabled').value === 'true';
        const timeout = parseInt(document.getElementById('ldapTimeout').value, 10) || 10;

        // Validation
        if (!domain || !displayName || !url || !bindDn || !searchBase) {
            if (window.showToast) window.showToast('Zorunlu alanlari doldurun', 'error');
            return;
        }

        if (!editingId && !bindPassword) {
            if (window.showToast) window.showToast('Bind sifresi zorunludur', 'error');
            return;
        }

        const body = {
            display_name: displayName,
            url,
            bind_dn: bindDn,
            search_base: searchBase,
            search_filter: searchFilter || '(sAMAccountName={{username}})',
            allowed_orgs: allowedOrgs,
            use_ssl: useSsl,
            enabled,
            timeout
        };

        if (!editingId) body.domain = domain;
        if (bindPassword) body.bind_password = bindPassword;

        // Firma ID ekle
        const compSel = document.getElementById('ldapCompanyId');
        if (compSel && compSel.value) body.company_id = parseInt(compSel.value, 10);

        try {
            const method = editingId ? 'PUT' : 'POST';
            const endpoint = editingId
                ? `${API_BASE}/api/ldap-settings/${editingId}`
                : `${API_BASE}/api/ldap-settings`;

            const response = await fetch(endpoint, {
                method,
                headers: authHeaders(),
                body: JSON.stringify(body)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'İşlem başarısız');
            }

            if (window.showToast) window.showToast(data.message || 'Başarılı', 'success');
            closeModal();
            load();
        } catch (err) {
            console.error('[LDAP] Save error:', err);
            if (window.showToast) window.showToast(err.message, 'error');
        }
    }

    // ---------------------------------------------------------
    //  Delete Setting
    // ---------------------------------------------------------
    async function deleteSetting(id, domain) {
        VyraModal.danger({
            title: 'LDAP Sunucu Sil',
            message: `"${domain}" LDAP sunucusunu silmek istediğinize emin misiniz?`,
            confirmText: 'Sil',
            cancelText: 'İptal',
            onConfirm: async () => {
                try {
                    const response = await fetch(`${API_BASE}/api/ldap-settings/${id}`, {
                        method: 'DELETE',
                        headers: authHeaders()
                    });

                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Silme başarısız');

                    if (window.showToast) window.showToast(data.message || 'Silindi', 'success');
                    load();
                } catch (err) {
                    console.error('[LDAP] Delete error:', err);
                    if (window.showToast) window.showToast(err.message, 'error');
                }
            }
        });
    }

    // ---------------------------------------------------------
    //  Test Connection
    // ---------------------------------------------------------
    async function testConnection(id) {
        if (window.showToast) window.showToast('Bağlantı testi yapılıyor...', 'info');

        try {
            const response = await fetch(`${API_BASE}/api/ldap-settings/${id}/test`, {
                method: 'POST',
                headers: authHeaders()
            });

            const data = await response.json();

            if (data.success) {
                let stepsHtml = (data.steps || []).map(s =>
                    `<div style="padding:4px 0;font-size:13px">${s.status === 'success' ? '✅' : '❌'} <strong>${s.name}</strong>: ${s.message}</div>`
                ).join('');
                if (window.showToast) window.showToast(data.message, 'success');
                VyraModal.success({
                    title: 'LDAP Bağlantı Başarılı',
                    htmlMessage: `<div style="margin-top:8px">${stepsHtml}</div>`
                });
            } else {
                let stepsHtml = (data.steps || []).map(s =>
                    `<div style="padding:4px 0;font-size:13px">${s.status === 'success' ? '✅' : '❌'} <strong>${s.name}</strong>: ${s.message}</div>`
                ).join('');
                if (window.showToast) window.showToast(data.message, 'error');
                VyraModal.error({
                    title: 'LDAP Bağlantı Hatası',
                    htmlMessage: `<div style="margin-top:8px">${stepsHtml}</div>`
                });
            }
        } catch (err) {
            console.error('[LDAP] Test error:', err);
            if (window.showToast) window.showToast('Bağlantı testi başarısız', 'error');
        }
    }

    // ---------------------------------------------------------
    //  Init Event Listeners
    // ---------------------------------------------------------
    function init() {
        const btnNew = document.getElementById('btnNewLdapSetting');
        if (btnNew) btnNew.addEventListener('click', openCreate);

        const btnClose = document.getElementById('btnCloseLdapModal');
        if (btnClose) btnClose.addEventListener('click', closeModal);

        const btnCancel = document.getElementById('btnCancelLdap');
        if (btnCancel) btnCancel.addEventListener('click', closeModal);

        const btnSave = document.getElementById('btnSaveLdap');
        if (btnSave) btnSave.addEventListener('click', save);

        // Domain secildiginde org checkbox'larini guncelle
        const domainSel = document.getElementById('ldapDomain');
        if (domainSel) {
            domainSel.addEventListener('change', () => {
                renderOrgCheckboxes(domainSel.value, []);
            });
        }

        // ESC ile kapat
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const modal = document.getElementById('ldapSettingModal');
                if (modal && !modal.classList.contains('hidden')) {
                    closeModal();
                }
            }
        });
    }

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Public API
    return {
        load,
        openCreate,
        openEdit,
        closeModal,
        save,
        deleteSetting,
        testConnection,
        init
    };
})();
