/**
 * VYRA Theme Catalog Module
 * ==========================
 * Sistem Parametreleri > Tasarım sekmesinde
 * hazır + özel SaaS temalarını firma bazlı kart grid görünümünde listeler.
 * v3.2.0 — Firma filtresi, önizleme butonu, özel tema badge, aktif işareti, uygula butonu
 */
window.ThemeCatalogModule = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || '';
    let themes = [];
    let companies = [];
    let selectedCompanyId = null;
    let companyAssignments = []; // firmaya atanmış temalar
    let defaultThemeId = null;   // firmanın aktif (varsayılan) tema ID'si

    function getToken() {
        return localStorage.getItem('access_token') || '';
    }

    /* --- Companies yükle --- */
    async function loadCompanies() {
        try {
            const res = await fetch(API_BASE + '/api/companies/', {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            if (!res.ok) return;
            companies = await res.json();
            // İlk firmayı otomatik seç
            if (companies.length > 0 && !selectedCompanyId) {
                selectedCompanyId = companies[0].id;
            }
        } catch (err) {
            console.warn('[ThemeCatalog] Firma listesi alınamadı');
        }
    }

    /* --- Firmaya atanmış temaları yükle --- */
    async function loadCompanyAssignments() {
        if (!selectedCompanyId) {
            companyAssignments = [];
            defaultThemeId = null;
            return;
        }
        try {
            const res = await fetch(API_BASE + '/api/themes/company/' + selectedCompanyId, {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            if (!res.ok) { companyAssignments = []; defaultThemeId = null; return; }
            companyAssignments = await res.json();
            var def = companyAssignments.find(function (a) { return a.is_default; });
            defaultThemeId = def ? def.id : null;
        } catch (err) {
            console.warn('[ThemeCatalog] Firma tema atamaları alınamadı');
            companyAssignments = [];
            defaultThemeId = null;
        }
    }

    /* --- Firma dropdown render --- */
    function renderCompanyFilter() {
        var wrap = document.getElementById('themeCatalogFilterWrap');
        if (!wrap || companies.length === 0) return;

        var opts = companies.map(function (c) {
            return '<option value="' + c.id + '"' + (c.id === selectedCompanyId ? ' selected' : '') + '>' + escapeHtml(c.name) + '</option>';
        }).join('');

        wrap.innerHTML =
            '<div class="tc-filter-bar">' +
                '<i class="fa-solid fa-building"></i>' +
                '<label class="tc-filter-label">Firma:</label>' +
                '<select id="themeCatalogCompanySelect" class="tc-filter-select">' +
                    opts +
                '</select>' +
            '</div>';

        var sel = document.getElementById('themeCatalogCompanySelect');
        if (sel) {
            sel.addEventListener('change', function () {
                selectedCompanyId = this.value ? parseInt(this.value) : null;
                loadThemes();
            });
        }
    }

    /* --- Tema yükle --- */
    async function loadThemes() {
        var grid = document.getElementById('themeCatalogGrid');
        if (!grid) return;

        grid.innerHTML = '<div class="tc-loading"><i class="fa-solid fa-spinner fa-spin"></i> Temalar yükleniyor...</div>';

        try {
            var url = API_BASE + '/api/themes/';
            if (selectedCompanyId) {
                url += '?company_id=' + selectedCompanyId;
            } else {
                url += '?include_custom=true';
            }

            var res = await fetch(url, {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            if (!res.ok) throw new Error('Tema listesi alınamadı');
            themes = await res.json();

            themes = themes.map(function (t) {
                if (typeof t.preview_colors === 'string') {
                    try { t.preview_colors = JSON.parse(t.preview_colors); } catch (e) { /* ignore */ }
                }
                return t;
            });

            // Firma atamalarını yükle
            await loadCompanyAssignments();

            renderGrid(grid);
        } catch (err) {
            console.error('[ThemeCatalog] Yükleme hatası:', err);
            grid.innerHTML = '<p class="tc-error">Tema listesi yüklenemedi.</p>';
        }
    }

    /* --- Kart grid render --- */
    function renderGrid(grid) {
        if (!themes.length) {
            grid.innerHTML = '<div class="tc-empty"><i class="fa-solid fa-palette"></i><p>Henüz tanımlı tema yok.</p></div>';
            return;
        }

        var hazir = themes.filter(function (t) { return !t.is_custom; });
        var ozel = themes.filter(function (t) { return t.is_custom; });

        var html = '';

        // Özet banner
        html += '<div class="tc-stats-banner">';
        html += '<span class="tc-stat"><i class="fa-solid fa-palette"></i> ' + themes.length + ' Tema</span>';
        if (hazir.length > 0) html += '<span class="tc-stat tc-stat-system"><i class="fa-solid fa-cubes"></i> ' + hazir.length + ' Hazır</span>';
        if (ozel.length > 0) html += '<span class="tc-stat tc-stat-custom"><i class="fa-solid fa-wand-magic-sparkles"></i> ' + ozel.length + ' Özel</span>';
        if (defaultThemeId) {
            var activeTheme = themes.find(function (t) { return t.id === defaultThemeId; });
            if (activeTheme) {
                html += '<span class="tc-stat tc-stat-active"><i class="fa-solid fa-circle-check"></i> Aktif: ' + escapeHtml(activeTheme.name) + '</span>';
            }
        }
        html += '</div>';

        // Hazır temalar
        if (hazir.length > 0) {
            html += '<div class="tc-section-title"><i class="fa-solid fa-cubes"></i> Hazır Temalar</div>';
            html += '<div class="tc-grid">';
            html += hazir.map(renderCard).join('');
            html += '</div>';
        }

        // Özel temalar
        if (ozel.length > 0) {
            html += '<div class="tc-section-title tc-section-custom"><i class="fa-solid fa-wand-magic-sparkles"></i> Özel Temalar</div>';
            html += '<div class="tc-grid">';
            html += ozel.map(renderCard).join('');
            html += '</div>';
        }

        grid.innerHTML = html;

        // Event bindings
        grid.querySelectorAll('.tc-preview-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var themeId = parseInt(this.dataset.themeId);
                var theme = themes.find(function (t) { return t.id === themeId; });
                if (theme && window.ThemePreviewModal) {
                    window.ThemePreviewModal.open(theme);
                }
            });
        });

        grid.querySelectorAll('.tc-apply-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var themeId = parseInt(this.dataset.themeId);
                applyTheme(themeId);
            });
        });
    }

    /* --- Tema uygula --- */
    function applyTheme(themeId) {
        if (!selectedCompanyId) {
            if (window.showToast) window.showToast('Lütfen önce bir firma seçin.', 'warning');
            return;
        }

        var theme = themes.find(function (t) { return t.id === themeId; });
        var themeName = theme ? theme.name : 'Tema #' + themeId;

        // Firma adını bul
        var companyName = '';
        var comp = companies.find(function (c) { return c.id === selectedCompanyId; });
        if (comp) companyName = comp.name;

        // VyraModal ile modern onay
        if (!window.VyraModal) {
            // Fallback: VyraModal yoksa eski confirm
            if (!confirm('"' + themeName + '" teması uygulanacak. Emin misiniz?')) return;
            executeApply(themeId, themeName, companyName);
            return;
        }

        VyraModal.confirm({
            title: 'Tema Uygula',
            message: '<strong>"' + escapeHtml(themeName) + '"</strong> teması <strong>' + escapeHtml(companyName) + '</strong> firmasına atanacak.<br><br>Tema renkleri anında uygulanacaktır.',
            confirmText: 'Uygula',
            cancelText: 'Vazgeç',
            onConfirm: function () {
                executeApply(themeId, themeName, companyName);
            }
        });
    }

    /* --- Tema atama API çağrısı ve branding güncelleme --- */
    async function executeApply(themeId, themeName, companyName) {
        try {
            // Mevcut atamaları al, yeni temayı default olarak ekle
            var assignedIds = companyAssignments.map(function (a) { return a.id; });
            if (assignedIds.indexOf(themeId) === -1) {
                assignedIds.push(themeId);
            }

            var res = await fetch(API_BASE + '/api/themes/assign', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + getToken()
                },
                body: JSON.stringify({
                    company_id: selectedCompanyId,
                    theme_ids: assignedIds,
                    default_theme_id: themeId
                })
            });

            if (!res.ok) {
                var errData = await res.json().catch(function () { return {}; });
                throw new Error(errData.detail || 'Atama başarısız');
            }

            // Tema detayını (CSS variables dahil) API'den al
            var themeDetail = await fetch(API_BASE + '/api/themes/' + themeId, {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            var themeData = themeDetail.ok ? await themeDetail.json() : null;

            // BrandingEngine cache güncelle — tema anında uygulanır
            if (window.BrandingEngine && themeData) {
                var brandData = BrandingEngine.loadBranding() || {};
                brandData.theme = themeData;
                BrandingEngine.saveBranding(brandData);

                // Sadece CSS temayı uygula (login içeriklerini dokunma — layout bozar)
                if (themeData.css_variables) {
                    var cssVars = themeData.css_variables;
                    if (typeof cssVars === 'string') {
                        try { cssVars = JSON.parse(cssVars); } catch(e) { cssVars = null; }
                    }
                    if (cssVars) {
                        BrandingEngine.applyThemeForCurrentMode(cssVars);
                    }
                }
            }

            if (window.showToast) window.showToast('"' + themeName + '" teması başarıyla uygulandı!', 'success');

            // Tema kataloğunu yeniden render et (aktif tema işaretini güncelle)
            await loadCompanyAssignments();
            var grid = document.getElementById('themeCatalogGrid');
            if (grid) renderGrid(grid);

        } catch (err) {
            console.error('[ThemeCatalog] Tema uygulama hatası:', err);
            if (window.showToast) window.showToast('Tema uygulanamadı: ' + err.message, 'error');
        }
    }

    /* --- Tek kart HTML --- */
    function renderCard(t) {
        var colors = (t.preview_colors || []).map(sanitizeColor);
        var gradientBar = colors.length >= 2
            ? 'background: linear-gradient(135deg, ' + colors[0] + ' 0%, ' + colors[1] + ' 100%);'
            : 'background: ' + (colors[0] || '#666') + ';';

        var isActive = (t.id === defaultThemeId);
        var isAssigned = companyAssignments.some(function (a) { return a.id === t.id; });

        var customBadge = t.is_custom
            ? '<span class="tc-badge-custom"><i class="fa-solid fa-star"></i> Özel</span>'
            : '';

        var activeBadge = isActive
            ? '<span class="tc-badge-active"><i class="fa-solid fa-circle-check"></i> Aktif</span>'
            : '';

        var cardClass = 'tc-card';
        if (isActive) cardClass += ' tc-card-active';
        else if (isAssigned) cardClass += ' tc-card-assigned';

        var applyBtnClass = isActive ? 'tc-apply-btn tc-apply-active' : 'tc-apply-btn';
        var applyBtnText = isActive ? '<i class="fa-solid fa-check"></i> Uygulandı' : '<i class="fa-solid fa-check-circle"></i> Uygula';
        var applyDisabled = isActive ? ' disabled' : '';

        return '<div class="' + cardClass + '" data-theme-id="' + t.id + '">' +
            customBadge + activeBadge +
            '<div class="tc-card-gradient" style="' + gradientBar + '"></div>' +
            '<div class="tc-card-body">' +
                '<h4 class="tc-card-title">' + escapeHtml(t.name) + '</h4>' +
                '<p class="tc-card-desc">' + escapeHtml(t.description || '') + '</p>' +
                '<div class="tc-card-colors">' +
                    colors.map(function (c) {
                        return '<span class="tc-color-dot" style="background:' + c + ';" title="' + c + '"></span>';
                    }).join('') +
                '</div>' +
            '</div>' +
            '<div class="tc-card-footer">' +
                '<button class="tc-preview-btn" data-theme-id="' + t.id + '" title="Tema Önizleme">' +
                    '<i class="fa-solid fa-eye"></i> Önizle' +
                '</button>' +
                '<button class="' + applyBtnClass + '" data-theme-id="' + t.id + '"' + applyDisabled + '>' +
                    applyBtnText +
                '</button>' +
            '</div>' +
        '</div>';
    }

    function escapeHtml(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /** CSS color sanitize — sadece güvenli formatlar kabul edilir */
    function sanitizeColor(c) {
        if (!c || typeof c !== 'string') return '#666';
        // Hex, rgb, rgba, hsl, hsla, named colors (harf/rakam/virgül/parantez/yüzde/boşluk/nokta)
        if (/^[#a-zA-Z0-9(),%.\s]+$/.test(c)) return c;
        return '#666';
    }

    /* --- Init --- */
    async function load() {
        await loadCompanies();
        renderCompanyFilter();
        await loadThemes();
    }

    return { load: load, reload: loadThemes };
})();
