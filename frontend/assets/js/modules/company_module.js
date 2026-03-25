/* ----------------------------------
   VYRA - Company Module
   Firma yönetimi CRUD modülü (v2.59.0)
   app_name, theme_id branding desteği
---------------------------------- */

/**
 * CompanyModule - Firma CRUD, logo ve adres yönetimi
 * @module CompanyModule
 */
window.CompanyModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || '';
    let companies = [];
    let editingId = null;
    let addressCache = { provinces: null, districts: {}, neighborhoods: {} };
    let themesList = []; // v2.59.0: Tema listesi cache

    // --- Token helper ---
    function getToken() {
        return localStorage.getItem('access_token') || '';
    }

    function authHeaders() {
        return {
            'Authorization': 'Bearer ' + getToken(),
            'Content-Type': 'application/json'
        };
    }

    // --- API Çağrıları ---

    async function fetchCompanies() {
        try {
            const res = await fetch(API_BASE + '/api/companies/', {
                headers: authHeaders()
            });
            if (!res.ok) throw new Error('Firma listesi alınamadı');
            companies = await res.json();
            return companies;
        } catch (err) {
            console.error('[CompanyModule] fetch error:', err);
            return [];
        }
    }

    async function saveCompany(data) {
        const url = editingId
            ? API_BASE + '/api/companies/' + editingId
            : API_BASE + '/api/companies/';
        const method = editingId ? 'PUT' : 'POST';

        const res = await fetch(url, {
            method: method,
            headers: authHeaders(),
            body: JSON.stringify(data)
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Kaydetme hatası');
        }
        return await res.json();
    }

    async function deleteCompany(id) {
        const res = await fetch(API_BASE + '/api/companies/' + id, {
            method: 'DELETE',
            headers: authHeaders()
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Silme hatası');
        }
        return await res.json();
    }

    async function uploadLogo(companyId, file) {
        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch(API_BASE + '/api/companies/' + companyId + '/logo', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + getToken() },
            body: formData
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Logo yükleme hatası');
        }
        return await res.json();
    }

    // --- Tema API (v2.59.0) ---

    async function fetchThemes() {
        try {
            const res = await fetch(API_BASE + '/api/themes/', {
                headers: authHeaders()
            });
            if (!res.ok) return [];
            themesList = await res.json();
            return themesList;
        } catch (err) {
            console.warn('[CompanyModule] Tema listesi alınamadı:', err);
            return [];
        }
    }

    function populateThemeSelect(selectedId) {
        const select = document.getElementById('companyThemeId');
        if (!select) return;
        select.innerHTML = '<option value="">Varsayılan (Okyanus Mavisi)</option>';
        themesList.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.name + ' — ' + (t.description || '');
            if (selectedId && t.id === selectedId) opt.selected = true;
            select.appendChild(opt);
        });
    }

    // --- Tema Önizleme (v2.59.0) ---

    function previewTheme() {
        var select = document.getElementById('companyThemeId');
        if (!select || !select.value) {
            if (typeof showToast === 'function') showToast('Lütfen önce bir tema seçin', 'warning');
            return;
        }
        var theme = themesList.find(function(t) { return t.id === parseInt(select.value, 10); });
        if (!theme) return;

        // Renk noktalarını hazırla
        var colors = theme.preview_colors || [];
        if (typeof colors === 'string') { try { colors = JSON.parse(colors); } catch(e) { colors = []; } }
        var gradBar = colors.length >= 2
            ? 'linear-gradient(135deg, ' + colors[0] + ' 0%, ' + colors[1] + ' 100%)'
            : (colors[0] || '#666');
        var colorDots = colors.map(function(c) {
            return '<span style="display:inline-block;width:18px;height:18px;border-radius:50%;background:' + c + ';border:2px solid rgba(255,255,255,0.2);"></span>';
        }).join(' ');

        // CSS değişkenlerini göster
        var cssVars = theme.css_variables || {};
        var darkVars = cssVars.dark || {};
        var varList = Object.keys(darkVars).slice(0, 6).map(function(k) {
            return '<div style="display:flex;align-items:center;gap:8px;margin:2px 0;">' +
                '<span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:' + darkVars[k] + ';"></span>' +
                '<code style="font-size:11px;color:#ccc;">' + k + '</code>' +
                '</div>';
        }).join('');

        VyraModal.info({
            title: '🎨 ' + (theme.name || 'Tema Önizleme'),
            message: '<div style="text-align:center;">' +
                '<div style="height:60px;border-radius:10px;margin-bottom:16px;background:' + gradBar + ';"></div>' +
                '<p style="color:#aaa;margin-bottom:12px;">' + (theme.description || '') + '</p>' +
                '<div style="margin-bottom:12px;">' + colorDots + '</div>' +
                '<div style="text-align:left;background:rgba(0,0,0,0.2);border-radius:8px;padding:10px 14px;">' +
                '<p style="color:#888;font-size:11px;margin-bottom:6px;">CSS Değişkenleri (dark):</p>' +
                varList +
                '</div>' +
                '</div>',
            confirmText: 'Tamam'
        });
    }

    // --- Türkiye Adres API ---

    async function loadProvinces() {
        const select = document.getElementById('companyAddressIl');
        if (!select) return;

        // Cache varsa kullan
        if (addressCache.provinces) {
            populateSelect(select, addressCache.provinces, 'İl Seçin...');
            return;
        }

        select.innerHTML = '<option value="">Yükleniyor...</option>';
        try {
            const res = await fetch(API_BASE + '/api/address/provinces');
            if (!res.ok) throw new Error('İl listesi alınamadı');
            const data = (await res.json())
                .map(p => ({ value: p.name, label: p.name, id: p.id }))
                .sort((a, b) => a.label.localeCompare(b.label, 'tr'));
            addressCache.provinces = data;
            populateSelect(select, data, 'İl Seçin...');
        } catch (err) {
            console.warn('[CompanyModule] İl API hatası:', err);
            select.innerHTML = '<option value="">İl Seçin (veri yüklenmedi)...</option>';
        }
    }

    async function loadDistricts(provinceName) {
        const select = document.getElementById('companyAddressIlce');
        const mahalleSelect = document.getElementById('companyAddressMahalle');
        if (!select) return;

        // Mahalle temizle
        if (mahalleSelect) {
            mahalleSelect.innerHTML = '<option value="">Önce ilçe seçin...</option>';
            mahalleSelect.disabled = true;
        }

        if (!provinceName) {
            select.innerHTML = '<option value="">Önce il seçin...</option>';
            select.disabled = true;
            return;
        }

        // İl ID'sini bul
        const province = (addressCache.provinces || []).find(p => p.value === provinceName);
        if (!province) return;

        // Cache varsa kullan
        if (addressCache.districts[province.id]) {
            populateSelect(select, addressCache.districts[province.id], 'İlçe Seçin...');
            select.disabled = false;
            return;
        }

        select.innerHTML = '<option value="">Yükleniyor...</option>';
        select.disabled = true;

        try {
            const res = await fetch(API_BASE + '/api/address/districts/' + province.id);
            if (!res.ok) throw new Error('İlçe listesi alınamadı');
            const districts = (await res.json())
                .map(d => ({ value: d.name, label: d.name, id: d.id }))
                .sort((a, b) => a.label.localeCompare(b.label, 'tr'));
            addressCache.districts[province.id] = districts;
            populateSelect(select, districts, 'İlçe Seçin...');
            select.disabled = false;
        } catch (err) {
            console.warn('[CompanyModule] İlçe API hatası:', err);
            select.innerHTML = '<option value="">İlçe Seçin (veri yüklenmedi)...</option>';
            select.disabled = false;
        }
    }

    async function loadNeighborhoods(provinceName, districtName) {
        const select = document.getElementById('companyAddressMahalle');
        if (!select) return;

        if (!districtName) {
            select.innerHTML = '<option value="">Önce ilçe seçin...</option>';
            select.disabled = true;
            return;
        }

        // İlçe ID'sini bul
        const province = (addressCache.provinces || []).find(p => p.value === provinceName);
        if (!province) return;
        const district = (addressCache.districts[province.id] || []).find(d => d.value === districtName);
        if (!district) return;

        // Cache varsa kullan
        const cacheKey = province.id + '_' + district.id;
        if (addressCache.neighborhoods[cacheKey]) {
            populateSelect(select, addressCache.neighborhoods[cacheKey], 'Mahalle Seçin...');
            select.disabled = false;
            return;
        }

        select.innerHTML = '<option value="">Yükleniyor...</option>';
        select.disabled = true;

        try {
            const res = await fetch(API_BASE + '/api/address/neighborhoods/' + district.id);
            if (!res.ok) throw new Error('Mahalle listesi alınamadı');
            const neighborhoods = (await res.json())
                .map(n => ({ value: n.name, label: n.name }))
                .sort((a, b) => a.label.localeCompare(b.label, 'tr'));
            addressCache.neighborhoods[cacheKey] = neighborhoods;
            populateSelect(select, neighborhoods, 'Mahalle Seçin...');
            select.disabled = false;
        } catch (err) {
            console.warn('[CompanyModule] Mahalle API hatası:', err);
            select.innerHTML = '<option value="">Mahalle Seçin (veri yüklenmedi)...</option>';
            select.disabled = false;
        }
    }

    function populateSelect(select, items, placeholder) {
        let html = '<option value="">' + placeholder + '</option>';
        items.forEach(item => {
            html += '<option value="' + escapeHtml(item.value) + '">' + escapeHtml(item.label) + '</option>';
        });
        select.innerHTML = html;
    }

    // --- Render ---

    function render() {
        const grid = document.getElementById('companyGrid');
        const empty = document.getElementById('companyEmptyState');
        if (!grid) return;

        if (!companies || companies.length === 0) {
            grid.innerHTML = '';
            if (empty) {
                grid.appendChild(empty);
                empty.style.display = '';
            }
            return;
        }

        // empty state gizle
        if (empty) empty.style.display = 'none';

        const cards = companies.map(c => {
            const logoUrl = c.has_logo
                ? (API_BASE + '/api/companies/' + c.id + '/logo')
                : '';
            const taxLabel = c.tax_type === 'tckn' ? 'TCKN' : 'VD';
            const statusBadge = c.is_active
                ? '<span class="company-badge active"><i class="fa-solid fa-circle"></i> Aktif</span>'
                : '<span class="company-badge inactive"><i class="fa-solid fa-circle"></i> Pasif</span>';

            return `
            <div class="company-card" data-id="${c.id}">
                <div class="company-card-top">
                    <div class="company-logo-wrap">
                        ${logoUrl
                            ? '<img src="' + logoUrl + '" alt="Logo" class="company-logo-img">'
                            : '<div class="company-logo-placeholder"><i class="fa-solid fa-building"></i></div>'
                        }
                    </div>
                    <div class="company-card-actions">
                        ${statusBadge}
                        <button class="btn-icon" title="Düzenle" data-company-edit="${c.id}">
                            <i class="fa-solid fa-pen"></i>
                        </button>
                        <button class="btn-icon btn-icon-danger" title="Deaktif Et" data-company-delete="${c.id}">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="company-card-body">
                    <h3 class="company-name">${escapeHtml(c.name)}</h3>
                    <div class="company-meta-grid">
                        <div class="company-meta-item">
                            <i class="fa-solid fa-hashtag"></i>
                            <span>${taxLabel}: ${escapeHtml(c.tax_number)}</span>
                        </div>
                        <div class="company-meta-item">
                            <i class="fa-solid fa-phone"></i>
                            <span>${escapeHtml(c.phone)}</span>
                        </div>
                        <div class="company-meta-item">
                            <i class="fa-solid fa-envelope"></i>
                            <span>${escapeHtml(c.email)}</span>
                        </div>
                        ${c.website ? `
                        <div class="company-meta-item">
                            <i class="fa-solid fa-globe"></i>
                            <span><a href="${escapeHtml(c.website)}" target="_blank" class="company-website-link">${escapeHtml(c.website)}</a></span>
                        </div>` : ''}
                        <div class="company-meta-item">
                            <i class="fa-solid fa-user-tie"></i>
                            <span>${escapeHtml(c.contact_name)} ${escapeHtml(c.contact_surname)}</span>
                        </div>
                        ${c.address_il ? `
                        <div class="company-meta-item">
                            <i class="fa-solid fa-location-dot"></i>
                            <span>${escapeHtml(c.address_il)}${c.address_ilce ? ' / ' + escapeHtml(c.address_ilce) : ''}</span>
                        </div>` : ''}
                    </div>
                </div>
            </div>`;
        }).join('');

        grid.innerHTML = cards;
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // --- Modal ---

    async function openModal(companyId) {
        editingId = companyId || null;
        const modal = document.getElementById('companyModal');
        if (!modal) return;

        const title = document.getElementById('companyModalTitle');
        const form = document.getElementById('companyForm');

        if (title) {
            title.innerHTML = companyId
                ? '<i class="fa-solid fa-building"></i> Firma Düzenle'
                : '<i class="fa-solid fa-building"></i> Yeni Firma Ekle';
        }

        // Form temizle
        if (form) form.reset();

        // Logo preview temizle
        const preview = document.getElementById('companyLogoPreview');
        if (preview) preview.innerHTML = '';

        // Tax type default
        const taxTypeSelect = document.getElementById('companyTaxType');
        if (taxTypeSelect) taxTypeSelect.value = 'vd';

        // İlçe ve Mahalle resetle
        const ilceSelect = document.getElementById('companyAddressIlce');
        const mahalleSelect = document.getElementById('companyAddressMahalle');
        if (ilceSelect) { ilceSelect.innerHTML = '<option value="">Önce il seçin...</option>'; ilceSelect.disabled = true; }
        if (mahalleSelect) { mahalleSelect.innerHTML = '<option value="">Önce ilçe seçin...</option>'; mahalleSelect.disabled = true; }

        // İl listesini yükle
        await loadProvinces();

        // Tema listesini yükle (v2.59.0)
        if (themesList.length === 0) await fetchThemes();
        populateThemeSelect(null);

        if (companyId) {
            // Düzenleme — mevcut verileri doldur
            const company = companies.find(c => c.id === companyId);
            if (company) {
                setField('companyName', company.name);
                setField('companyAppName', company.app_name); // v2.59.0
                populateThemeSelect(company.theme_id); // v2.59.0
                if (taxTypeSelect) taxTypeSelect.value = company.tax_type || 'vd';
                setField('companyTaxNumber', company.tax_number);
                setField('companyAddressText', company.address_text);
                setField('companyPhone', company.phone);
                setField('companyEmail', company.email);
                setField('companyWebsite', company.website);
                setField('companyContactName', company.contact_name);
                setField('companyContactSurname', company.contact_surname);

                // Adres dropdown'larını cascade olarak yükle
                if (company.address_il) {
                    setField('companyAddressIl', company.address_il);
                    await loadDistricts(company.address_il);
                    if (company.address_ilce) {
                        setField('companyAddressIlce', company.address_ilce);
                        await loadNeighborhoods(company.address_il, company.address_ilce);
                        if (company.address_mahalle) {
                            setField('companyAddressMahalle', company.address_mahalle);
                        }
                    }
                }

                // Logo preview
                if (company.has_logo && preview) {
                    preview.innerHTML = '<img src="' + API_BASE + '/api/companies/' + company.id + '/logo" alt="Logo" class="company-logo-preview-img">';
                }
            }
        }

        modal.classList.remove('hidden');
    }

    function closeModal() {
        const modal = document.getElementById('companyModal');
        if (modal) modal.classList.add('hidden');
        editingId = null;
    }

    function setField(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value || '';
    }

    // --- Save Handler ---

    async function handleSave() {
        // v2.59.0: app_name ve theme_id eklendi
        const themeVal = (document.getElementById('companyThemeId') || {}).value;
        const data = {
            name: (document.getElementById('companyName') || {}).value || '',
            app_name: (document.getElementById('companyAppName') || {}).value || null,
            theme_id: themeVal ? parseInt(themeVal, 10) : null,
            tax_type: (document.getElementById('companyTaxType') || {}).value || 'vd',
            tax_number: (document.getElementById('companyTaxNumber') || {}).value || '',
            address_il: (document.getElementById('companyAddressIl') || {}).value || null,
            address_ilce: (document.getElementById('companyAddressIlce') || {}).value || null,
            address_mahalle: (document.getElementById('companyAddressMahalle') || {}).value || null,
            address_text: (document.getElementById('companyAddressText') || {}).value || null,
            phone: (document.getElementById('companyPhone') || {}).value || '',
            email: (document.getElementById('companyEmail') || {}).value || '',
            website: (document.getElementById('companyWebsite') || {}).value || null,
            contact_name: (document.getElementById('companyContactName') || {}).value || '',
            contact_surname: (document.getElementById('companyContactSurname') || {}).value || ''
        };

        // Validasyon
        if (!data.name || !data.tax_number || !data.phone || !data.email || !data.contact_name || !data.contact_surname) {
            if (typeof Swal !== 'undefined') {
                Swal.fire('Uyarı', 'Zorunlu alanları doldurun.', 'warning');
            }
            return;
        }

        try {
            const result = await saveCompany(data);

            // Logo dosyası seçildiyse yükle
            const logoInput = document.getElementById('companyLogoFile');
            if (logoInput && logoInput.files && logoInput.files[0]) {
                const companyId = result.id || editingId;
                await uploadLogo(companyId, logoInput.files[0]);
            }

            closeModal();
            await load();

            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    icon: 'success',
                    title: editingId ? 'Firma güncellendi' : 'Firma eklendi',
                    timer: 1500,
                    showConfirmButton: false
                });
            }
        } catch (err) {
            if (typeof Swal !== 'undefined') {
                Swal.fire('Hata', err.message, 'error');
            }
        }
    }

    // --- Delete Handler ---

    async function handleDelete(id) {
        const company = companies.find(c => c.id === id);
        if (!company) return;

        if (typeof Swal !== 'undefined') {
            const result = await Swal.fire({
                title: 'Firmayı Deaktif Et?',
                html: '<strong>' + escapeHtml(company.name) + '</strong> firması deaktif edilecek.',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Evet, Deaktif Et',
                cancelButtonText: 'İptal',
                confirmButtonColor: '#ef4444'
            });
            if (!result.isConfirmed) return;
        }

        try {
            await deleteCompany(id);
            await load();
        } catch (err) {
            if (typeof Swal !== 'undefined') {
                Swal.fire('Hata', err.message, 'error');
            }
        }
    }

    // --- Logo Preview ---

    function handleLogoPreview(e) {
        const file = e.target.files[0];
        const preview = document.getElementById('companyLogoPreview');
        if (!file || !preview) return;

        const reader = new FileReader();
        reader.onload = function (ev) {
            preview.innerHTML = '<img src="' + ev.target.result + '" alt="Logo" class="company-logo-preview-img">';
        };
        reader.readAsDataURL(file);
    }

    // --- Load ---

    async function load() {
        await fetchCompanies();
        render();
    }

    // --- Event Delegation ---

    function setupEvents() {
        // Yeni Firma butonu
        const btnNew = document.getElementById('btnNewCompany');
        if (btnNew) {
            btnNew.addEventListener('click', () => openModal(null));
        }

        // Modal kapat
        const btnClose = document.getElementById('btnCloseCompanyModal');
        if (btnClose) btnClose.addEventListener('click', closeModal);

        const btnCancel = document.getElementById('btnCancelCompany');
        if (btnCancel) btnCancel.addEventListener('click', closeModal);

        // ESC ile kapat
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const modal = document.getElementById('companyModal');
                if (modal && !modal.classList.contains('hidden')) {
                    closeModal();
                }
            }
        });

        // Kaydet
        const btnSave = document.getElementById('btnSaveCompany');
        if (btnSave) btnSave.addEventListener('click', handleSave);

        // Tema önizleme butonu (v2.59.0)
        var btnPreview = document.getElementById('btnThemePreview');
        if (btnPreview) btnPreview.addEventListener('click', previewTheme);

        // Logo dosya seçimi preview
        const logoInput = document.getElementById('companyLogoFile');
        if (logoInput) logoInput.addEventListener('change', handleLogoPreview);

        // İl → İlçe cascade
        const ilSelect = document.getElementById('companyAddressIl');
        if (ilSelect) {
            ilSelect.addEventListener('change', () => {
                loadDistricts(ilSelect.value);
            });
        }

        // İlçe → Mahalle cascade
        const ilceSelect = document.getElementById('companyAddressIlce');
        if (ilceSelect) {
            ilceSelect.addEventListener('change', () => {
                const ilVal = (document.getElementById('companyAddressIl') || {}).value || '';
                loadNeighborhoods(ilVal, ilceSelect.value);
            });
        }

        // Event delegation: düzenle ve sil butonları
        const grid = document.getElementById('companyGrid');
        if (grid) {
            grid.addEventListener('click', (e) => {
                const editBtn = e.target.closest('[data-company-edit]');
                if (editBtn) {
                    const id = parseInt(editBtn.dataset.companyEdit, 10);
                    openModal(id);
                    return;
                }

                const deleteBtn = e.target.closest('[data-company-delete]');
                if (deleteBtn) {
                    const id = parseInt(deleteBtn.dataset.companyDelete, 10);
                    handleDelete(id);
                }
            });
        }
    }

    // --- Init ---

    function init() {
        setupEvents();
    }

    // Public API
    return {
        init: init,
        load: load,
        openModal: openModal
    };
})();

// Otomatik init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.CompanyModule.init);
} else {
    window.CompanyModule.init();
}
