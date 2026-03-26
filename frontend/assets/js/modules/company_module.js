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

    // --- Tema API (v2.60.0 → v2.60.1 UX fix) ---

    let assignedThemeIds = new Set();
    let selectedDefaultThemeId = null;  // v2.60.1: Kullanıcının seçtiği varsayılan tema

    async function fetchThemesFull() {
        try {
            const res = await fetch(API_BASE + '/api/themes/full', {
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

    async function fetchAssignedThemes(companyId) {
        if (!companyId) return [];
        try {
            const res = await fetch(API_BASE + '/api/themes/company/' + companyId, {
                headers: authHeaders()
            });
            if (!res.ok) return [];
            return await res.json();
        } catch (err) {
            console.warn('[CompanyModule] Atanmış temalar alınamadı:', err);
            return [];
        }
    }

    function renderThemeCard(theme, isAssigned, isDefault, mode) {
        var colors = theme.preview_colors || [];
        if (typeof colors === 'string') {
            try { colors = JSON.parse(colors); } catch(e) { colors = ['#666','#999']; }
        }
        var c1 = colors[0] || '#666';
        var c2 = colors[1] || '#999';
        // mode: 'pool' = havuz kartı, 'assigned' = atanmış kart
        var extraBtns = '';
        if (mode === 'assigned') {
            extraBtns = '<div class="design-card-actions">' +
                '<button type="button" class="design-card-default-btn' + (isDefault ? ' active' : '') + '" data-default-theme="' + theme.id + '" title="Varsayılan Yap">★</button>' +
                '<button type="button" class="design-card-remove-btn" data-remove-theme="' + theme.id + '" title="Kaldır">✕</button>' +
            '</div>';
        }
        return '<div class="design-theme-card ' + (isAssigned ? 'selected' : '') + '" data-theme-id="' + theme.id + '">' +
            '<div class="dt-check">✓</div>' +
            '<div class="dt-swatch">' +
                '<div class="dt-swatch-half" style="background:' + c1 + '"></div>' +
                '<div class="dt-swatch-half" style="background:' + c2 + '"></div>' +
            '</div>' +
            '<div class="dt-name">' + escapeHtml(theme.name) + '</div>' +
            (isDefault ? '<div class="dt-check dt-check-default">★</div>' : '') +
            extraBtns +
        '</div>';
    }

    /**
     * Atanmış temalar grid'ini güncel Set'e göre yeniden render eder (v2.60.1)
     */
    function updateAssignedGrid() {
        var assignedGrid = document.getElementById('companyAssignedThemes');
        if (!assignedGrid) return;

        if (assignedThemeIds.size === 0) {
            assignedGrid.innerHTML = '<p class="design-empty-hint">Henüz tema atanmadı. Aşağıdan tema seçin.</p>';
            selectedDefaultThemeId = null;
        } else {
            // Default tema kontrolü: eğer mevcut default kaldırıldıysa ilkini default yap
            if (!selectedDefaultThemeId || !assignedThemeIds.has(selectedDefaultThemeId)) {
                selectedDefaultThemeId = Array.from(assignedThemeIds)[0];
            }
            var html = '';
            assignedThemeIds.forEach(function(tid) {
                var t = themesList.find(function(th) { return th.id === tid; });
                if (t) html += renderThemeCard(t, true, tid === selectedDefaultThemeId, 'assigned');
            });
            assignedGrid.innerHTML = html;

            // Kaldır butonu
            assignedGrid.querySelectorAll('[data-remove-theme]').forEach(function(btn) {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    var tid = parseInt(this.getAttribute('data-remove-theme'), 10);
                    var theme = themesList.find(function(th) { return th.id === tid; });
                    assignedThemeIds.delete(tid);
                    updateAssignedGrid();
                    updatePoolGrid();
                    syncHiddenInput();
                    if (window.VyraToast && theme) VyraToast.info(theme.name + ' kaldırıldı');
                });
            });

            // Varsayılan yap butonu
            assignedGrid.querySelectorAll('[data-default-theme]').forEach(function(btn) {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    var tid = parseInt(this.getAttribute('data-default-theme'), 10);
                    selectedDefaultThemeId = tid;
                    var theme = themesList.find(function(th) { return th.id === tid; });
                    updateAssignedGrid();
                    syncHiddenInput();
                    if (window.VyraToast && theme) VyraToast.success(theme.name + ' varsayılan yapıldı');
                });
            });
        }
    }

    /**
     * Havuz grid'ini güncel Set'e göre yeniden render eder (v2.60.1)
     */
    function updatePoolGrid() {
        var poolGrid = document.getElementById('companyThemePool');
        if (!poolGrid) return;

        poolGrid.innerHTML = themesList.map(function(t) {
            return renderThemeCard(t, assignedThemeIds.has(t.id), t.id === selectedDefaultThemeId, 'pool');
        }).join('');

        // Kart tıklama — toggle selection
        poolGrid.querySelectorAll('.design-theme-card').forEach(function(card) {
            card.addEventListener('click', function() {
                var tid = parseInt(this.getAttribute('data-theme-id'), 10);
                var theme = themesList.find(function(th) { return th.id === tid; });
                if (assignedThemeIds.has(tid)) {
                    assignedThemeIds.delete(tid);
                    if (window.VyraToast && theme) VyraToast.info(theme.name + ' kaldırıldı');
                } else {
                    assignedThemeIds.add(tid);
                    if (window.VyraToast && theme) VyraToast.info(theme.name + ' eklendi');
                }
                updateAssignedGrid();
                updatePoolGrid();
                syncHiddenInput();
            });
        });
    }

    /**
     * Hidden input'u güncel default tema ile senkronize eder
     */
    function syncHiddenInput() {
        var hiddenInput = document.getElementById('companyThemeId');
        if (hiddenInput) hiddenInput.value = selectedDefaultThemeId || '';
    }

    async function renderDesignTab(companyId) {
        // Temaları yükle
        if (themesList.length === 0) await fetchThemesFull();

        // Firmaya atanmış temaları yükle
        var assigned = companyId ? await fetchAssignedThemes(companyId) : [];
        assignedThemeIds = new Set(assigned.map(function(a) { return a.id; }));
        selectedDefaultThemeId = null;
        assigned.forEach(function(a) { if (a.is_default) selectedDefaultThemeId = a.id; });

        // Atanmış temalar grid (v2.60.1: updateAssignedGrid kullan)
        updateAssignedGrid();

        // Tema havuzu grid (v2.60.1: updatePoolGrid kullan)
        updatePoolGrid();

        // Color picker önizleme
        var c1Input = document.getElementById('newThemeColor1');
        var c2Input = document.getElementById('newThemeColor2');
        if (c1Input && c2Input) {
            var updatePreview = function() {
                var h1 = document.getElementById('newThemePreviewHalf1');
                var h2 = document.getElementById('newThemePreviewHalf2');
                if (h1) h1.style.background = c1Input.value;
                if (h2) h2.style.background = c2Input.value;
            };
            c1Input.addEventListener('input', updatePreview);
            c2Input.addEventListener('input', updatePreview);
            updatePreview(); // v2.60.1: Başlangıç renklerini hemen uygula
        }

        // Öner butonu
        var suggestBtn = document.getElementById('btnSuggestColors');
        if (suggestBtn) {
            suggestBtn.onclick = async function() {
                var color = c1Input ? c1Input.value : '#06B6D4';
                try {
                    var res = await fetch(API_BASE + '/api/themes/suggest', {
                        method: 'POST',
                        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ color: color })
                    });
                    if (!res.ok) throw new Error('Öneri alınamadı');
                    var data = await res.json();
                    renderSuggestions(data.suggestions || []);
                } catch (err) {
                    console.error('[CompanyModule] Öneri hatası:', err);
                }
            };
        }

        // Yeni tema kaydet
        var saveBtn = document.getElementById('btnSaveNewTheme');
        if (saveBtn) {
            saveBtn.onclick = async function() {
                var name = (document.getElementById('newThemeName') || {}).value;
                var color1 = c1Input ? c1Input.value : '#06B6D4';
                var color2 = c2Input ? c2Input.value : '#3B82F6';
                if (!name) {
                    if (window.VyraToast) VyraToast.warning('Lütfen tema adı girin');
                    return;
                }
                try {
                    var res = await fetch(API_BASE + '/api/themes/', {
                        method: 'POST',
                        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name, color1: color1, color2: color2, company_id: editingId })
                    });
                    if (!res.ok) {
                        var err = await res.json().catch(function() { return {}; });
                        throw new Error(err.detail || 'Tema oluşturulamadı');
                    }
                    if (window.VyraToast) VyraToast.success('Tema oluşturuldu: ' + name);
                    // Listeyi yenile
                    themesList = [];
                    await renderDesignTab(editingId);
                } catch (err) {
                    if (window.VyraToast) VyraToast.error(err.message);
                }
            };
        }
    }

    function renderSuggestions(suggestions) {
        var container = document.getElementById('colorSuggestions');
        if (!container) return;
        container.classList.remove('hidden');
        container.innerHTML = suggestions.map(function(s) {
            return '<div class="design-suggest-card ' + (s.already_exists ? 'exists' : '') + '" data-c1="' + s.color1 + '" data-c2="' + s.color2 + '">' +
                '<div class="ds-swatch">' +
                    '<div class="ds-swatch-half" style="background:' + s.color1 + '"></div>' +
                    '<div class="ds-swatch-half" style="background:' + s.color2 + '"></div>' +
                '</div>' +
                '<div class="ds-label">' + s.label + (s.already_exists ? ' ✕' : '') + '</div>' +
            '</div>';
        }).join('');

        // Kart tıklama — renkleri color picker'a ata
        container.querySelectorAll('.design-suggest-card:not(.exists)').forEach(function(card) {
            card.addEventListener('click', function() {
                var c1 = this.getAttribute('data-c1');
                var c2 = this.getAttribute('data-c2');
                var inp1 = document.getElementById('newThemeColor1');
                var inp2 = document.getElementById('newThemeColor2');
                if (inp1) { inp1.value = c1; }
                if (inp2) { inp2.value = c2; }
                var h1 = document.getElementById('newThemePreviewHalf1');
                var h2 = document.getElementById('newThemePreviewHalf2');
                if (h1) h1.style.background = c1;
                if (h2) h2.style.background = c2;
            });
        });
    }

    // v2.59.0 eski fonksiyonlar (uyumluluk)
    function populateThemeSelect(selectedId) {
        var hiddenInput = document.getElementById('companyThemeId');
        if (hiddenInput && selectedId) hiddenInput.value = selectedId;
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

        // Tasarım sekmesi (v2.60.0)
        await renderDesignTab(companyId);

        if (companyId) {
            // Düzenleme — mevcut verileri doldur
            const company = companies.find(c => c.id === companyId);
            if (company) {
                setField('companyName', company.name);
                setField('companyAppName', company.app_name);
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

                // Logo preview (v2.60.1: onerror fallback)
                if (company.has_logo && preview) {
                    var logoImg = document.createElement('img');
                    logoImg.src = API_BASE + '/api/companies/' + company.id + '/logo';
                    logoImg.alt = 'Logo';
                    logoImg.className = 'company-logo-preview-img';
                    logoImg.onerror = function() { preview.innerHTML = '<div class="company-logo-placeholder"><i class="fa-solid fa-building"></i></div>'; };
                    preview.innerHTML = '';
                    preview.appendChild(logoImg);
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

            // v2.60.0: Tema atamaları kaydet
            var savedCompanyId = result.id || editingId;
            if (savedCompanyId) {
                var themeIds = Array.from(assignedThemeIds);
                var defaultId = selectedDefaultThemeId || (themeIds.length > 0 ? themeIds[0] : null);
                try {
                    var assignRes = await fetch(API_BASE + '/api/themes/assign', {
                        method: 'POST',
                        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            company_id: savedCompanyId,
                            theme_ids: themeIds,
                            default_theme_id: defaultId
                        })
                    });
                    if (!assignRes.ok) {
                        throw new Error('HTTP ' + assignRes.status);
                    }

                    // v2.60.0: Tema değişikliğini anlık yansıt
                    if (window.BrandingEngine && defaultId) {
                        var selectedTheme = themesList.find(function(t) { return t.id === defaultId; });
                        if (selectedTheme) {
                            var bd = BrandingEngine.loadBranding() || {};
                            bd.app_name = data.app_name || bd.app_name;
                            bd.company_id = savedCompanyId;
                            bd.theme = {
                                id: selectedTheme.id,
                                code: selectedTheme.code,
                                css_variables: selectedTheme.css_variables,
                                login_headline: selectedTheme.login_headline || (bd.theme ? bd.theme.login_headline : null),
                                login_subtitle: selectedTheme.login_subtitle || (bd.theme ? bd.theme.login_subtitle : null),
                                features_json: selectedTheme.features_json || (bd.theme ? bd.theme.features_json : null)
                            };
                            BrandingEngine.saveBranding(bd);
                            BrandingEngine.applyAll(bd);
                        }
                    }
                } catch (err) {
                    console.warn('[CompanyModule] Tema atama hatası:', err);
                    if (window.VyraToast) VyraToast.warning('Temalar atanamadı, lütfen tekrar deneyin');
                }
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
