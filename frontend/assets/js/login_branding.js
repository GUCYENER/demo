/**
 * VYRA Login Branding Module
 * ===========================
 * Login ekranında firma logosu ve adını gösterir.
 * URL'den firma eşleşmesi yapılır, read-only modda gösterilir.
 * 
 * Kullanım: login.html'de <script src="assets/js/login_branding.js"> ile yüklenir.
 * initLoginBranding() DOMContentLoaded'da otomatik çağrılır.
 */
(function() {
    'use strict';

    var API_BASE = window.API_BASE_URL || '';

    /**
     * Login ekranında firma branding'ini başlatır.
     * Mevcut URL'yi backend'e gönderip firma eşleşmesi yapar.
     */
    async function initLoginBranding() {
        var container = document.getElementById('companyBrandingBlock');
        if (!container) return;

        var currentUrl = window.location.href;

        try {
            var response = await fetch(API_BASE + '/api/companies/by-url?url=' + encodeURIComponent(currentUrl));
            if (!response.ok) {
                hideBlock(container);
                return;
            }

            var data = await response.json();

            if (!data.found || !data.company) {
                hideBlock(container);
                return;
            }

            var company = data.company;

            // Global: login işleminde kullanılacak firma ID
            window.__companyId = company.id;

            // Logo
            var logoEl = document.getElementById('companyBrandLogo');
            var placeholderEl = document.getElementById('companyBrandPlaceholder');

            if (company.has_logo && company.logo_url) {
                var img = new Image();
                img.onload = function() {
                    if (logoEl) {
                        logoEl.src = API_BASE + company.logo_url;
                        logoEl.style.display = 'block';
                    }
                    if (placeholderEl) placeholderEl.style.display = 'none';
                };
                img.onerror = function() {
                    showPlaceholder(placeholderEl, company.name);
                    if (logoEl) logoEl.style.display = 'none';
                };
                img.src = API_BASE + company.logo_url;
            } else {
                showPlaceholder(placeholderEl, company.name);
                if (logoEl) logoEl.style.display = 'none';
            }

            // Firma Adı
            var nameEl = document.getElementById('companyBrandName');
            if (nameEl) nameEl.textContent = company.name;

            // Bloğu göster
            container.classList.add('visible');

        } catch (err) {
            console.warn('[LoginBranding] Firma eşleşme hatası:', err.message);
            hideBlock(container);
        }
    }

    function showPlaceholder(el, name) {
        if (!el) return;
        el.style.display = 'flex';
        // İlk harf
        var initial = (name || '?').charAt(0).toUpperCase();
        el.textContent = initial;
    }

    function hideBlock(container) {
        if (container) container.classList.remove('visible');
    }

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initLoginBranding);
    } else {
        initLoginBranding();
    }

    // Re-init desteği
    window.initLoginBranding = initLoginBranding;
})();
