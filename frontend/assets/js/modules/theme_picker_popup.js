/* ----------------------------------
   VYRA - Theme Picker Popup
   Ay butonuna tıklayınca firma bazlı
   tema seçici popup gösterir (v2.60.0)
---------------------------------- */

window.ThemePickerPopup = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || '';
    let popupEl = null;
    let isOpen = false;

    function getToken() {
        return localStorage.getItem('access_token') || '';
    }

    function authHeaders() {
        return { 'Authorization': 'Bearer ' + getToken() };
    }

    /**
     * Popup HTML oluştur ve DOM'a ekle
     */
    function createPopup() {
        if (popupEl) return;

        popupEl = document.createElement('div');
        popupEl.id = 'themePickerPopup';
        popupEl.className = 'tp-popup hidden';
        popupEl.innerHTML = `
            <div class="tp-header">
                <span class="tp-title">Tema Seç</span>
                <button class="tp-close" id="tpCloseBtn">&times;</button>
            </div>
            <div class="tp-mode-toggle">
                <button class="tp-mode-btn active" data-mode="dark">
                    <svg viewBox="0 0 24 24" width="14" height="14"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
                    Koyu
                </button>
                <button class="tp-mode-btn" data-mode="light">
                    <svg viewBox="0 0 24 24" width="14" height="14"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                    Açık
                </button>
            </div>
            <div class="tp-themes-grid" id="tpThemesGrid">
                <div class="tp-loading">Yükleniyor...</div>
            </div>
        `;
        document.body.appendChild(popupEl);

        // Close butonu
        popupEl.querySelector('#tpCloseBtn').addEventListener('click', close);

        // Dark/Light toggle
        popupEl.querySelectorAll('.tp-mode-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var mode = this.getAttribute('data-mode');
                document.documentElement.setAttribute('data-theme', mode);
                popupEl.querySelectorAll('.tp-mode-btn').forEach(function(b) { b.classList.remove('active'); });
                this.classList.add('active');
                // Branding engine tema değişikliğini MutationObserver ile yakalar
            });
        });

        // Dışarı tıklama kapatmasın (kural: overlay koruması)
        // ESC desteği
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isOpen) close();
        });
    }

    /**
     * Mevcut dark/light modunu sync et
     */
    function syncModeToggle() {
        if (!popupEl) return;
        var currentMode = document.documentElement.getAttribute('data-theme') || 'dark';
        popupEl.querySelectorAll('.tp-mode-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.getAttribute('data-mode') === currentMode);
        });
    }

    /**
     * Firma temaları yükle ve grid'e render et
     */
    async function loadThemes() {
        var grid = popupEl.querySelector('#tpThemesGrid');
        grid.innerHTML = '<div class="tp-loading">Yükleniyor...</div>';

        try {
            // Firma ID'yi branding verilerinden al
            var bd = window.BrandingEngine ? BrandingEngine.loadBranding() : null;
            var companyId = bd ? bd.company_id : null;

            if (!companyId) {
                grid.innerHTML = '<div class="tp-empty">Firma teması bulunamadı</div>';
                return;
            }

            var res = await fetch(API_BASE + '/api/themes/company/' + companyId, {
                headers: authHeaders()
            });

            if (!res.ok) throw new Error('Tema listesi alınamadı');
            var themes = await res.json();

            if (!themes.length) {
                grid.innerHTML = '<div class="tp-empty">Bu firma için tanımlı tema yok</div>';
                return;
            }

            // Mevcut aktif tema
            var activeThemeId = bd.theme ? (bd.theme.id || null) : null;

            grid.innerHTML = '';
            themes.forEach(function(t) {
                var colors = t.preview_colors || [];
                if (typeof colors === 'string') {
                    try { colors = JSON.parse(colors); } catch(e) { colors = []; }
                }
                if (!Array.isArray(colors)) colors = [];
                var c1 = colors[0] || '#666';
                var c2 = colors[1] || '#999';

                var card = document.createElement('button');
                card.className = 'tp-theme-card' + (t.id === activeThemeId ? ' active' : '') + (t.is_default ? ' default' : '');
                card.innerHTML = `
                    <div class="tp-color-swatch">
                        <div class="tp-swatch-half" style="background:${c1}"></div>
                        <div class="tp-swatch-half" style="background:${c2}"></div>
                    </div>
                    <span class="tp-theme-name">${t.name}</span>
                    ${t.is_default ? '<span class="tp-default-badge">Varsayılan</span>' : ''}
                `;
                card.addEventListener('click', function() {
                    applyTheme(t);
                    // Aktif kartı güncelle
                    grid.querySelectorAll('.tp-theme-card').forEach(function(c) { c.classList.remove('active'); });
                    card.classList.add('active');
                });
                grid.appendChild(card);
            });

        } catch (err) {
            console.error('[ThemePicker] Hata:', err);
            grid.innerHTML = '<div class="tp-empty">Temalar yüklenemedi</div>';
        }
    }

    /**
     * Seçilen temayı uygula
     */
    function applyTheme(themeData) {
        if (!window.BrandingEngine) return;

        var bd = BrandingEngine.loadBranding() || {};

        // Sadece tema CSS verilerini güncelle (login içeriği dokunma)
        bd.theme = {
            id: themeData.id,
            code: themeData.code,
            name: themeData.name,
            css_variables: themeData.css_variables,
            login_headline: themeData.login_headline || (bd.theme ? bd.theme.login_headline : null),
            login_subtitle: themeData.login_subtitle || (bd.theme ? bd.theme.login_subtitle : null),
            features_json: themeData.features_json || (bd.theme ? bd.theme.features_json : null)
        };

        // Kaydet
        BrandingEngine.saveBranding(bd);

        // Sadece CSS temayı uygula (login content/logo/features dokunma)
        if (bd.theme && bd.theme.css_variables) {
            var cssVars = bd.theme.css_variables;
            if (typeof cssVars === 'string') {
                try { cssVars = JSON.parse(cssVars); } catch(e) { cssVars = null; }
            }
            if (cssVars) {
                BrandingEngine.applyThemeForCurrentMode(cssVars);
            }
        }

        if (window.showToast) {
            showToast(themeData.name + ' teması uygulandı', 'success');
        }
    }

    /**
     * Popup aç
     */
    function open() {
        createPopup();
        syncModeToggle();
        loadThemes();
        popupEl.classList.remove('hidden');
        isOpen = true;
    }

    /**
     * Popup kapat
     */
    function close() {
        if (popupEl) popupEl.classList.add('hidden');
        isOpen = false;
    }

    /**
     * Toggle
     */
    function toggle() {
        if (isOpen) close(); else open();
    }

    return {
        open: open,
        close: close,
        toggle: toggle
    };
})();
