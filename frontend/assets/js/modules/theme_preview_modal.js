/**
 * VYRA Theme Preview Modal
 * ========================
 * Login ekranını tema renkleriyle önizleme modalı.
 * iframe içinde login.html yüklenir, CSS variables inject edilir.
 * v3.2.0
 */
window.ThemePreviewModal = (function () {
    'use strict';

    const API_BASE = window.API_BASE_URL || '';
    let currentTheme = null;
    let currentMode = 'dark';
    let modalEl = null;

    function getToken() {
        return localStorage.getItem('access_token') || '';
    }

    /* --- Modal HTML oluştur --- */
    function ensureModal() {
        if (modalEl) return;

        var div = document.createElement('div');
        div.id = 'themePreviewOverlay';
        div.className = 'tpm-overlay';
        div.innerHTML =
            '<div class="tpm-container">' +
                '<div class="tpm-header">' +
                    '<div class="tpm-header-left">' +
                        '<div class="tpm-icon"><i class="fa-solid fa-eye"></i></div>' +
                        '<div>' +
                            '<h3 class="tpm-title">Tema Önizleme</h3>' +
                            '<span class="tpm-subtitle" id="tpmThemeName"></span>' +
                        '</div>' +
                    '</div>' +
                    '<div class="tpm-header-actions">' +
                        '<div class="tpm-mode-toggle">' +
                            '<button class="tpm-mode-btn active" data-mode="dark">' +
                                '<i class="fa-solid fa-moon"></i> Dark' +
                            '</button>' +
                            '<button class="tpm-mode-btn" data-mode="light">' +
                                '<i class="fa-solid fa-sun"></i> Light' +
                            '</button>' +
                        '</div>' +
                        '<button class="tpm-close" id="tpmClose" title="Kapat">' +
                            '<i class="fa-solid fa-xmark"></i>' +
                        '</button>' +
                    '</div>' +
                '</div>' +
                '<div class="tpm-body">' +
                    '<div class="tpm-iframe-wrap">' +
                        '<iframe id="tpmIframe" src="about:blank" class="tpm-iframe"></iframe>' +
                    '</div>' +
                '</div>' +
                '<div class="tpm-footer">' +
                    '<div class="tpm-footer-info">' +
                        '<i class="fa-solid fa-circle-info"></i> ' +
                        'Bu önizleme yalnızca görsel değerlendirme amaçlıdır. Uygulamak için firmaya tema atayın.' +
                    '</div>' +
                    '<button class="tpm-close-btn" id="tpmCloseBtn">Kapat</button>' +
                '</div>' +
            '</div>';

        document.body.appendChild(div);
        modalEl = div;

        // Event bindings
        document.getElementById('tpmClose').addEventListener('click', close);
        document.getElementById('tpmCloseBtn').addEventListener('click', close);

        // Mode toggle
        div.querySelectorAll('.tpm-mode-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                div.querySelectorAll('.tpm-mode-btn').forEach(function (b) { b.classList.remove('active'); });
                this.classList.add('active');
                currentMode = this.dataset.mode;
                applyThemeToIframe();
            });
        });

        // ESC desteği
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modalEl && !modalEl.classList.contains('hidden')) {
                close();
            }
        });
    }

    /* --- Tema CSS variables'ı API'den al --- */
    async function fetchThemeFull(themeId) {
        try {
            var res = await fetch(API_BASE + '/api/themes/' + themeId, {
                headers: { 'Authorization': 'Bearer ' + getToken() }
            });
            if (!res.ok) return null;
            return await res.json();
        } catch (err) {
            console.error('[ThemePreview] Tema detayı alınamadı:', err);
            return null;
        }
    }

    /* --- Modal aç --- */
    async function open(theme) {
        ensureModal();

        document.getElementById('tpmThemeName').textContent = theme.name || '';

        // Tema detayını (CSS variables dahil) API'den al
        var fullTheme = await fetchThemeFull(theme.id);
        if (!fullTheme) {
            if (window.showToast) window.showToast('Tema detayı alınamadı', 'error');
            return;
        }

        currentTheme = fullTheme;

        // CSS variables parse
        if (typeof currentTheme.css_variables === 'string') {
            try { currentTheme.css_variables = JSON.parse(currentTheme.css_variables); } catch (e) { /* ignore */ }
        }

        currentMode = 'dark';
        modalEl.querySelectorAll('.tpm-mode-btn').forEach(function (b) {
            b.classList.toggle('active', b.dataset.mode === 'dark');
        });

        modalEl.classList.remove('hidden');
        modalEl.classList.add('visible');
        document.body.style.overflow = 'hidden';

        // iframe yükle
        loadIframe();
    }

    /* --- iframe login.html yükle --- */
    var originalBranding = null; // orijinal cache yedek
    var previewTimers = [];      // timer ID'leri — close'da temizlenir

    function clearPreviewTimers() {
        previewTimers.forEach(function(id) { clearTimeout(id); });
        previewTimers = [];
    }

    function loadIframe() {
        var iframe = document.getElementById('tpmIframe');
        if (!iframe) return;

        // Önceki timer'ları temizle
        clearPreviewTimers();

        // Orijinal branding cache'ini yedekle
        originalBranding = localStorage.getItem('vyra_company_branding');

        // Geçici olarak preview temasını localStorage'a yaz
        injectPreviewBranding();

        iframe.onload = function () {
            // Branding engine asenkron çalışıyor — birden fazla kez dene
            previewTimers.push(
                setTimeout(function () { forcePreviewTheme(); }, 600)
            );
            previewTimers.push(
                setTimeout(function () { forcePreviewTheme(); }, 1500)
            );
            previewTimers.push(
                setTimeout(function () {
                    forcePreviewTheme();
                    restoreOriginalBranding();
                }, 2500)
            );
        };

        // Login sayfasını yükle
        iframe.src = '/login.html?preview=1';
    }

    /* --- Preview temasını localStorage'a geçici yaz --- */
    function injectPreviewBranding() {
        if (!currentTheme) return;
        try {
            var brandData = originalBranding ? JSON.parse(originalBranding) : {};
            brandData.theme = currentTheme;
            localStorage.setItem('vyra_company_branding', JSON.stringify(brandData));
        } catch (e) {
            console.warn('[ThemePreview] branding cache yazma hatası:', e);
        }
    }

    /* --- Orijinal branding cache'ini geri yükle --- */
    function restoreOriginalBranding() {
        try {
            if (originalBranding) {
                localStorage.setItem('vyra_company_branding', originalBranding);
            } else {
                localStorage.removeItem('vyra_company_branding');
            }
        } catch (e) { /* ignore */ }
    }

    /* --- iframe'deki temayı zorla preview temasına çevir --- */
    function forcePreviewTheme() {
        var iframe = document.getElementById('tpmIframe');
        if (!iframe || !iframe.contentDocument || !currentTheme) return;

        try {
            var doc = iframe.contentDocument;
            var iframeWin = iframe.contentWindow;
            var root = doc.documentElement;

            root.setAttribute('data-theme', currentMode);

            var cssVars = currentTheme.css_variables;
            if (!cssVars) return;
            var modeVars = cssVars[currentMode] || cssVars.dark || {};

            // 1) Branding engine'in oluşturduğu accent override'ı KESİNLİKLE KALDIR
            var accentOverride = doc.getElementById('vyra-accent-override');
            if (accentOverride) accentOverride.remove();

            // 2) iframe BrandingEngine varsa preview temasıyla yeniden çağır
            if (iframeWin && iframeWin.BrandingEngine) {
                // Önce CSS kök değişkenleri uygula
                iframeWin.BrandingEngine.applyThemeCSS(modeVars);
                // Sonra accent override'ı DOĞRU renklerle oluştur
                iframeWin.BrandingEngine.applyThemeForCurrentMode(cssVars);
            }

            // 3) Kendi CSS değişkenlerimizi !important ile en sona ekle
            var existingStyle = doc.getElementById('theme-preview-inject');
            if (existingStyle) existingStyle.remove();

            var cssText = ':root, :root[data-theme="' + currentMode + '"] {\n';
            for (var key in modeVars) {
                if (modeVars.hasOwnProperty(key)) {
                    cssText += '  ' + key + ': ' + modeVars[key] + ' !important;\n';
                }
            }
            cssText += '}\n';

            var style = doc.createElement('style');
            style.id = 'theme-preview-inject';
            style.textContent = cssText;
            doc.head.appendChild(style);

            // 4) Önizleme badge
            if (!doc.getElementById('preview-badge')) {
                var badge = doc.createElement('div');
                badge.id = 'preview-badge';
                badge.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:9999;' +
                    'background:rgba(0,0,0,0.7);backdrop-filter:blur(12px);color:#fff;padding:6px 16px;' +
                    'border-radius:20px;font-size:11px;font-weight:500;letter-spacing:0.5px;' +
                    'display:flex;align-items:center;gap:6px;pointer-events:none;';
                badge.innerHTML = '<span style="width:6px;height:6px;border-radius:50%;background:#22c55e;"></span> ÖNİZLEME MODU';
                doc.body.appendChild(badge);
            }
        } catch (err) {
            console.warn('[ThemePreview] forcePreviewTheme hatası:', err);
        }
    }

    /* --- Mod değişikliğinde tema yeniden uygula (dark/light toggle) --- */
    function applyThemeToIframe() {
        forcePreviewTheme();
    }

    /* --- Modal kapat --- */
    function close() {
        if (!modalEl) return;
        modalEl.classList.remove('visible');
        modalEl.classList.add('hidden');
        document.body.style.overflow = '';

        // Aktif timer'ları temizle (forcePreviewTheme artık çalışmasın)
        clearPreviewTimers();

        // Orijinal branding cache'ini geri yükle
        restoreOriginalBranding();

        // iframe temizle
        var iframe = document.getElementById('tpmIframe');
        if (iframe) iframe.src = 'about:blank';

        currentTheme = null;
    }

    return { open: open, close: close };
})();
