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
     * Tema accent rengine göre hardcoded mavi renkleri override eden dinamik CSS inject eder.
     * @param {Object} modeVars - Aktif mod CSS değişkenleri { "--gold": "#xxx", ... }
     */
    function injectAccentOverride(modeVars) {
        if (!modeVars || !modeVars['--gold']) return;
        var accent = modeVars['--gold'];
        var accent2 = modeVars['--gold-2'] || accent;
        var accentDim = modeVars['--gold-dim'] || 'rgba(234,179,8,0.12)';
        var accentGlow = modeVars['--gold-glow'] || 'rgba(234,179,8,0.18)';
        var gradAcc = modeVars['--grad-acc'] || 'linear-gradient(135deg,' + accent + ',' + accent2 + ')';
        var gradBtn = modeVars['--grad-btn'] || gradAcc;

        // Eski style varsa kaldır
        var old = document.getElementById('vyra-accent-override');
        if (old) old.remove();

        var style = document.createElement('style');
        style.id = 'vyra-accent-override';
        style.textContent = [
            /* ==============================================
               GLOBAL CSS KÖK DEĞİŞKEN OVERRIDE
               var() kullanan TÜM dosyalar otomatik düzelir
               ============================================== */
            ':root {',
            /* global.css değişkenleri */
            '  --secondary: ' + accent + ' !important;',
            '  --secondary-light: ' + accent + ' !important;',
            '  --secondary-dark: ' + accent2 + ' !important;',
            '  --accent-purple: ' + accent + ' !important;',
            '  --accent-indigo: ' + accent + ' !important;',
            '  --accent-indigo-light: ' + accent + ' !important;',
            '  --accent-indigo-subtle: ' + accent + ' !important;',
            '  --primary: ' + accent + ' !important;',
            '  --primary-light: ' + accent + ' !important;',
            '  --primary-dark: ' + accent2 + ' !important;',
            '  --primary-darker: ' + accent2 + ' !important;',
            '  --shadow-primary: 0 4px 16px ' + accentGlow + ' !important;',
            '  --shadow-secondary: 0 4px 16px ' + accentGlow + ' !important;',
            '  --border-focus: ' + accent + ' !important;',
            /* home.html inline CSS değişkenleri */
            '  --accent: ' + accent + ' !important;',
            '  --accent-2: ' + accent2 + ' !important;',
            '  --accent-glow: ' + accentGlow + ' !important;',
            '  --accent-subtle: ' + accentDim + ' !important;',
            '  --grad-logo: ' + gradBtn + ' !important;',
            '  --grad-acc: ' + gradAcc + ' !important;',
            '  --grad-send: ' + gradBtn + ' !important;',
            '  --border-accent: ' + (modeVars['--border-accent'] || accentGlow) + ' !important;',
            '  --text-acc: ' + accent + ' !important;',
            '  --bg-msg-user: ' + accentDim + ' !important;',
            '  --orb-1: ' + accentDim + ' !important;',
            '  --orb-2: ' + accentDim + ' !important;',
            '  --shadow-input: ' + (modeVars['--shadow-input'] || '0 0 0 1px ' + accent + ', 0 0 18px ' + accentDim) + ' !important;',
            '}',
            /* ==============================================
               HOME.CSS - Sidebar, Tab, Button, İnput
               ============================================== */
            // Sidebar active
            '.menu-item.active { background: linear-gradient(135deg, ' + accentDim + ' 0%, rgba(0,0,0,0.05) 100%) !important; color: ' + accent + ' !important; border-color: ' + accentGlow + ' !important; box-shadow: 0 4px 12px ' + accentGlow + ' !important; }',
            '.menu-item.active i { color: ' + accent + ' !important; }',
            // Sidebar logo
            '.sb-logo-icon { background: ' + gradBtn + ' !important; box-shadow: 0 0 0 1px rgba(255,255,255,0.10), 0 0 40px ' + accentGlow + ', 0 8px 28px rgba(0,0,0,0.4) !important; }',
            // Topbar
            '.tb-btn-primary { background: ' + gradBtn + ' !important; }',
            '.tb-agent-avatar { background: ' + gradBtn + ' !important; }',
            // Tab active/hover
            '.modern-tab:hover, .tab-button:hover, .tab:hover { border-color: ' + accent + ' !important; }',
            '.modern-tab.active, .tab-button.active, .tab.active { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            // Avatar
            '.avatar-initials { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.profile-avatar-wrapper img { border-color: ' + accent + ' !important; }',
            '.role-badge.admin { background: ' + gradBtn + ' !important; border-color: ' + accent + ' !important; }',
            // Buttons
            '.main-btn { background: ' + gradBtn + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.textarea-send-btn:not(:disabled) { background: ' + gradBtn + ' !important; box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.logout-btn { background: ' + gradBtn + ' !important; }',
            '.tab-fav-btn:hover, .tab-fav-btn.favorited { color: ' + accent + ' !important; }',
            // Input focus
            '.input-textarea:focus { border-color: ' + accent + ' !important; box-shadow: 0 0 0 4px ' + accentDim + ' !important; }',
            '.textarea-attach-btn:hover { background: ' + accentDim + ' !important; border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            '.loading-box { border-left-color: ' + accent + ' !important; }',
            /* ==============================================
               DIALOG-CHAT.CSS - Sohbet ikonları, butonları
               ============================================== */
            '.mode-card:hover { border-color: ' + accent + ' !important; }',
            '.mode-card.active { border-color: ' + accent + ' !important; box-shadow: 0 0 16px ' + accentGlow + ' !important; }',
            '.msg-badge-score { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            '.dt-enhance-btn { background: ' + gradBtn + ' !important; }',
            '.dt-enhance-btn:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            '.sohbet-btn { background: ' + gradBtn + ' !important; }',
            '.sohbet-btn:hover { box-shadow: 0 6px 20px ' + accentGlow + ' !important; }',
            '.chat-bubble-assistant .source-link { color: ' + accent + ' !important; }',
            '.streaming-cursor { background: ' + accent + ' !important; }',
            /* ==============================================
               RAG_UPLOAD.CSS - Dosya yükleme, arama
               ============================================== */
            '.rag-upload-zone:hover, .rag-upload-zone.drag-over { border-color: ' + accent + ' !important; }',
            '.rag-action-btn { color: ' + accent + ' !important; }',
            '.rag-action-btn:hover { background: ' + accentDim + ' !important; }',
            '.source-badge { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               MODAL.CSS - Modal butonları
               ============================================== */
            '.modal-btn-primary, .vyra-modal-ok { background: ' + gradBtn + ' !important; color: #fff !important; }',
            '.modal-btn-primary:hover, .vyra-modal-ok:hover { box-shadow: 0 4px 16px ' + accentGlow + ' !important; }',
            /* ==============================================
               AUTHORIZATION.CSS - Yetkilendirme
               ============================================== */
            '.auth-toggle-active { background: ' + gradBtn + ' !important; }',
            '.auth-role-badge.active { background: ' + accentDim + ' !important; border-color: ' + accent + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               TICKET-HISTORY.CSS - Ticket kartları
               ============================================== */
            '.ticket-status-badge.open { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }',
            /* ==============================================
               NOTIFICATION + MATURITY + DS_LEARNING
               ============================================== */
            '.notification-action-btn { color: ' + accent + ' !important; }',
            '.maturity-bar-fill { background: ' + gradBtn + ' !important; }',
            '.cl-status-running { color: ' + accent + ' !important; }',
            '.cl-countdown { background: ' + accentDim + ' !important; color: ' + accent + ' !important; }'
        ].join('\n');
        document.head.appendChild(style);
    }

    /**
     * Mevcut tema moduna göre CSS variables uygular.
     * @param {Object} themeData - { dark: {...}, light: {...} }
     */
    function applyThemeForCurrentMode(themeData) {
        if (!themeData) return;
        var mode = document.documentElement.getAttribute('data-theme') || 'dark';
        var vars = themeData[mode] || themeData['dark'];
        if (vars) {
            applyThemeCSS(vars);
            injectAccentOverride(vars);
        }
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
     * Login ekranındaki sol üst logoyu firma logosuyla değiştirir.
     * @param {string} logoUrl - Logo URL'i
     */
    function applyLoginLogo(logoUrl) {
        if (!logoUrl) return;
        var API_BASE = window.API_BASE_URL || '';
        var logoIcon = document.querySelector('.ngssai-icon');
        if (!logoIcon) return;

        var img = new Image();
        img.onload = function() {
            logoIcon.innerHTML = '';
            img.className = 'login-company-logo-img';
            logoIcon.appendChild(img);
        };
        img.src = API_BASE + logoUrl;
    }

    /**
     * Browser tab favicon'ı firma logosuna günceller.
     * @param {string} logoUrl - Logo URL'i
     */
    function applyFavicon(logoUrl) {
        if (!logoUrl) return;
        var API_BASE = window.API_BASE_URL || '';
        var fav = document.getElementById('faviconLink');
        if (!fav) {
            fav = document.createElement('link');
            fav.id = 'faviconLink';
            fav.rel = 'icon';
            document.head.appendChild(fav);
        }
        fav.type = 'image/png';
        fav.href = API_BASE + logoUrl;
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
     * Logo yoksa sidebar, topbar ve login ikonlarını firma ilk harfiyle günceller.
     * @param {string} letter - Gösterilecek harf
     */
    function applyInitialLetter(letter) {
        if (!letter) return;
        var svgHtml = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" overflow="hidden" style="width:100%;height:100%">' +
            '<text x="12" y="17" font-family="Geist,Arial,sans-serif" font-size="14" font-weight="700" fill="white" text-anchor="middle">' +
            letter + '</text></svg>';

        // Sidebar logo
        var sbIcon = document.querySelector('.sb-logo-icon');
        if (sbIcon) sbIcon.innerHTML = svgHtml;

        // Topbar agent avatar
        var tbAvatar = document.querySelector('.tb-agent-avatar');
        if (tbAvatar) tbAvatar.innerHTML = svgHtml;

        // Login sol üst ikon
        var loginIcon = document.querySelector('.ngssai-icon');
        if (loginIcon) loginIcon.innerHTML = svgHtml;
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

        // CSS Tema uygula (JSON string → obje parse)
        if (brandData.theme && brandData.theme.css_variables) {
            var cssVars = brandData.theme.css_variables;
            if (typeof cssVars === 'string') {
                try { cssVars = JSON.parse(cssVars); } catch(e) { cssVars = null; }
            }
            if (cssVars) applyThemeForCurrentMode(cssVars);
        }

        // Uygulama adı uygula (app_name NGSSAI ise firma adını kullan)
        var displayName = brandData.app_name;
        if (!displayName || displayName === 'NGSSAI') {
            displayName = brandData.company_name || displayName;
        }
        if (displayName) {
            applyAppName(displayName);
        }

        // Login içerik güncelle
        if (brandData.theme) {
            applyLoginContent(
                brandData.theme.login_headline,
                brandData.theme.login_subtitle
            );
            // features_json JSON string → dizi parse
            var features = brandData.theme.features_json;
            if (typeof features === 'string') {
                try { features = JSON.parse(features); } catch(e) { features = null; }
            }
            applyLoginFeatures(features);
        }

        // Logo / ilk harf — önce ilk harfi uygula, logo varsa üzerine yaz
        var initial = ((displayName || brandData.company_name || 'N').charAt(0)).toUpperCase();

        // Favicon için SVG oluştur
        var accentColor = '%237C3AED';
        if (brandData.theme && brandData.theme.css_variables) {
            var cv = brandData.theme.css_variables;
            if (typeof cv === 'string') { try { cv = JSON.parse(cv); } catch(e) { cv = null; } }
            if (cv && cv.dark && cv.dark['--gold']) {
                accentColor = encodeURIComponent(cv.dark['--gold']);
            }
        }
        var svgFav = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>" +
            "<rect width='32' height='32' rx='6' fill='" + accentColor + "'/>" +
            "<text x='16' y='22' font-family='Arial' font-size='18' font-weight='bold' fill='white' text-anchor='middle'>" + initial + "</text></svg>";
        var fav = document.getElementById('faviconLink');
        if (fav) { fav.type = 'image/svg+xml'; fav.href = svgFav; }

        // Sidebar, topbar ve login ikonlarını ilk harf ile güncelle (anında)
        applyInitialLetter(initial);

        // Logo varsa üzerine yaz (asenkron — img yüklenince)
        if (brandData.logo_url) {
            applyFavicon(brandData.logo_url);
            applyLoginLogo(brandData.logo_url);
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
                        var cssVars = brandData.theme.css_variables;
                        if (typeof cssVars === 'string') {
                            try { cssVars = JSON.parse(cssVars); } catch(e) { cssVars = null; }
                        }
                        if (cssVars) applyThemeForCurrentMode(cssVars);
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
        applyLoginLogo: applyLoginLogo,
        applyFavicon: applyFavicon,
        applySidebarLogo: applySidebarLogo,
        saveBranding: saveBranding,
        loadBranding: loadBranding,
        clearBranding: clearBranding,
        applyAll: applyAll,
        watchThemeChanges: watchThemeChanges
    };
})();
