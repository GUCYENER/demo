/**
 * VYRA Branding Engine
 * ====================
 * Login ve Home ekranlarında firma bazlı dinamik CSS tema,
 * uygulama adı ve logo uygulaması.
 * v2.59.0
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'vyra_company_branding';

    /**
     * CSS değişkenlerini document root'a uygular.
     * @param {Object} cssVars - { "--gold": "#xxx", ... }
     */
    function applyThemeCSS(cssVars) {
        if (!cssVars || typeof cssVars !== 'object') return;
        var root = document.documentElement;
        Object.keys(cssVars).forEach(function(key) {
            root.style.setProperty(key, cssVars[key]);
        });
    }

    /**
     * Mevcut tema moduna göre CSS variables uygular.
     * @param {Object} themeData - { dark: {...}, light: {...} }
     */
    function applyThemeForCurrentMode(themeData) {
        if (!themeData) return;
        var mode = document.documentElement.getAttribute('data-theme') || 'dark';
        var vars = themeData[mode] || themeData['dark'];
        if (vars) applyThemeCSS(vars);
    }

    /**
     * Uygulama adını tüm sayfadaki dinamik alanlara uygular.
     * @param {string} appName - Firma uygulama adı
     */
    function applyAppName(appName) {
        if (!appName) return;

        // Login ekranı
        var ngssaiName = document.querySelector('.ngssai-name');
        if (ngssaiName) ngssaiName.textContent = appName;

        // Browser title
        var titleEl = document.querySelector('title');
        if (titleEl) {
            var currentTitle = titleEl.textContent;
            titleEl.textContent = currentTitle.replace(/NGSSAI/g, appName);
        }

        // Version badge (login)
        var vBadge = document.getElementById('versionBadge');
        if (vBadge) {
            vBadge.textContent = vBadge.textContent.replace(/NGSSAI/g, appName);
        }

        // Sidebar logo name (home)
        var sbName = document.querySelector('.sb-logo-name');
        if (sbName) sbName.textContent = appName;

        // Topbar agent name (home)
        var tbName = document.querySelector('.tb-agent-name');
        if (tbName) tbName.textContent = appName + ' Asistan';

        // Status bar version (home)
        var statusVer = document.getElementById('statusVersion');
        if (statusVer) {
            statusVer.textContent = statusVer.textContent.replace(/NGSSAI/g, appName);
        }

        // Sidebar version (home)
        var sbVer = document.querySelector('.sb-version');
        if (sbVer) {
            sbVer.innerHTML = sbVer.innerHTML.replace(/NGSSAI/g, appName);
        }

        // Dialog section header
        var dialogHeader = document.querySelector('#sectionDialog .tb-agent-name');
        if (dialogHeader) dialogHeader.textContent = appName + ' Asistan';

        // Chat mode card
        var chatModeTitle = document.querySelector('#modeChat .mc-title');
        if (chatModeTitle) {
            chatModeTitle.textContent = chatModeTitle.textContent.replace(/NGSSAI/g, appName);
        }
    }

    /**
     * Login ekranı sol paneldeki headline ve subtitle'ı günceller.
     * @param {string} headline - HTML destekli headline
     * @param {string} subtitle - Alt açıklama
     */
    function applyLoginContent(headline, subtitle) {
        var h1 = document.querySelector('.brand-h1');
        if (h1 && headline) h1.innerHTML = headline;

        var sub = document.querySelector('.brand-sub');
        if (sub && subtitle) sub.textContent = subtitle;
    }

    /**
     * Login ekranı feature kartlarını günceller.
     * @param {Array} features - [{title, desc, icon}]
     */
    function applyLoginFeatures(features) {
        if (!features || !Array.isArray(features)) return;
        var stack = document.querySelector('.feature-stack');
        if (!stack) return;

        var feats = stack.querySelectorAll('.feat');
        features.forEach(function(f, i) {
            if (feats[i]) {
                var title = feats[i].querySelector('.feat-title');
                var desc = feats[i].querySelector('.feat-desc');
                if (title) title.textContent = f.title;
                if (desc) desc.textContent = f.desc;
            }
        });
    }

    /**
     * Firma logosunu sidebar'daki icon alanına uygular (home ekranı).
     * @param {string} logoUrl - Logo URL'i
     */
    function applySidebarLogo(logoUrl) {
        if (!logoUrl) return;
        var API_BASE = window.API_BASE_URL || '';

        // Sidebar logo icon — SVG yerine img koy
        var logoIcon = document.querySelector('.sb-logo-icon');
        if (logoIcon) {
            var img = new Image();
            img.onload = function() {
                logoIcon.innerHTML = '';
                img.className = 'sb-logo-company-img';
                logoIcon.appendChild(img);
            };
            img.src = API_BASE + logoUrl;
        }

        // Topbar agent avatar
        var tbAvatar = document.querySelector('.tb-agent-avatar');
        if (tbAvatar) {
            var img2 = new Image();
            img2.onload = function() {
                tbAvatar.innerHTML = '';
                img2.className = 'tb-agent-company-img';
                tbAvatar.appendChild(img2);
            };
            img2.src = API_BASE + logoUrl;
        }
    }

    /**
     * Branding bilgisini localStorage'a kaydeder.
     * @param {Object} data - { app_name, theme, logo_url, company_id, company_name }
     */
    function saveBranding(data) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
        } catch (e) {
            console.warn('[BrandingEngine] localStorage kayıt hatası:', e);
        }
    }

    /**
     * Kaydedilmiş branding bilgisini yükler.
     * @returns {Object|null}
     */
    function loadBranding() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Branding bilgisini temizler.
     */
    function clearBranding() {
        localStorage.removeItem(STORAGE_KEY);
    }

    /**
     * Tüm branding bilgilerini uygular (login veya home ekranı için).
     * @param {Object} brandData - { app_name, theme, logo_url }
     */
    function applyAll(brandData) {
        if (!brandData) return;

        // CSS Tema uygula
        if (brandData.theme && brandData.theme.css_variables) {
            applyThemeForCurrentMode(brandData.theme.css_variables);
        }

        // Uygulama adı uygula
        if (brandData.app_name && brandData.app_name !== 'NGSSAI') {
            applyAppName(brandData.app_name);
        }

        // Login içerik güncelle
        if (brandData.theme) {
            applyLoginContent(
                brandData.theme.login_headline,
                brandData.theme.login_subtitle
            );
            applyLoginFeatures(brandData.theme.features_json);
        }

        // Logo uygula
        if (brandData.logo_url) {
            applySidebarLogo(brandData.logo_url);
        }
    }

    /**
     * Tema değişikliğini dinler ve CSS'i yeniden uygular.
     */
    function watchThemeChanges() {
        var observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                if (m.attributeName === 'data-theme') {
                    var brandData = loadBranding();
                    if (brandData && brandData.theme && brandData.theme.css_variables) {
                        applyThemeForCurrentMode(brandData.theme.css_variables);
                    }
                }
            });
        });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    }

    // Public API
    window.BrandingEngine = {
        applyThemeCSS: applyThemeCSS,
        applyThemeForCurrentMode: applyThemeForCurrentMode,
        applyAppName: applyAppName,
        applyLoginContent: applyLoginContent,
        applyLoginFeatures: applyLoginFeatures,
        applySidebarLogo: applySidebarLogo,
        saveBranding: saveBranding,
        loadBranding: loadBranding,
        clearBranding: clearBranding,
        applyAll: applyAll,
        watchThemeChanges: watchThemeChanges
    };
})();
