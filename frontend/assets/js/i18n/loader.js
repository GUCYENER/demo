/**
 * VYRA i18n Loader (v3.30.0 FAZ 5 P34)
 * =====================================
 * Hafif, dependency-free i18n yardımcısı. DB Smart Wizard ("Akıllı Veri
 * Keşfi") modülü için TR (default) + EN bundle yüklemeyi yönetir.
 *
 * API:
 *   window.VyraI18n.init()                         → detect + load active bundle
 *   window.VyraI18n.t(key, params?)                → string lookup + fallback
 *   window.VyraI18n.applyTranslations(rootEl)      → [data-i18n] + [data-i18n-attr] sweep
 *   window.VyraI18n.setLang(lang)                  → switch + persist
 *   window.VyraI18n.getLang()                      → current ('tr' | 'en')
 *
 * Bundle path: /assets/js/i18n/aki_kesif_<lang>.json
 *   (FastAPI StaticFiles mount '/assets' → frontend/assets)
 *
 * Detection priority:
 *   1) URL ?lang=tr|en
 *   2) localStorage 'vyra.lang'
 *   3) navigator.language slice(0,2)
 *   4) FALLBACK 'tr'
 *
 * ARES gate: t() çıktısı yalnız textContent (innerHTML değil). XSS yok.
 */
(function () {
    'use strict';
    const STORAGE_KEY = 'vyra.lang';
    const FALLBACK = 'tr';
    const SUPPORTED = ['tr', 'en'];
    const _bundles = {};   // {lang: {key: str}}
    let _currentLang = null;

    function detectLang() {
        // Priority: URL > localStorage > navigator.language > FALLBACK
        try {
            const u = new URLSearchParams(window.location.search).get('lang');
            if (u && SUPPORTED.includes(u)) return u;
        } catch (e) { /* ignore */ }
        try {
            const s = localStorage.getItem(STORAGE_KEY);
            if (s && SUPPORTED.includes(s)) return s;
        } catch (e) { /* ignore */ }
        try {
            const n = (navigator.language || 'tr').slice(0, 2).toLowerCase();
            if (SUPPORTED.includes(n)) return n;
        } catch (e) { /* ignore */ }
        return FALLBACK;
    }

    async function loadBundle(lang) {
        if (_bundles[lang]) return _bundles[lang];
        try {
            const res = await fetch('/assets/js/i18n/aki_kesif_' + lang + '.json',
                                    { cache: 'no-cache' });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            _bundles[lang] = await res.json();
            return _bundles[lang];
        } catch (e) {
            console.warn('[i18n] bundle load failed', lang, e);
            if (lang !== FALLBACK) return loadBundle(FALLBACK);
            _bundles[lang] = {};
            return {};
        }
    }

    async function init() {
        _currentLang = detectLang();
        await loadBundle(_currentLang);
        // <html lang="…"> — SR + Lighthouse i18n
        try { document.documentElement.setAttribute('lang', _currentLang); } catch (e) { /* ignore */ }
        return _currentLang;
    }

    function t(key, params) {
        const bundle = _bundles[_currentLang] || {};
        let raw = bundle[key];
        if (raw === undefined && _currentLang !== FALLBACK) {
            raw = (_bundles[FALLBACK] || {})[key];
        }
        if (raw === undefined) return key;   // debug passthrough
        if (params && typeof params === 'object') {
            return String(raw).replace(/\{(\w+)\}/g, function (m, k) {
                return (k in params) ? String(params[k]) : m;
            });
        }
        return raw;
    }

    function applyTranslations(rootEl) {
        if (!rootEl || typeof rootEl.querySelectorAll !== 'function') return;
        rootEl.querySelectorAll('[data-i18n]').forEach(function (el) {
            const key = el.getAttribute('data-i18n');
            const paramsAttr = el.getAttribute('data-i18n-params');
            let p = null;
            if (paramsAttr) { try { p = JSON.parse(paramsAttr); } catch (e) { /* ignore */ } }
            // textContent — innerHTML değil (ARES XSS gate)
            el.textContent = t(key, p);
        });
        rootEl.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
            // data-i18n-attr="title:tooltip.help;aria-label:button.save"
            const spec = el.getAttribute('data-i18n-attr') || '';
            spec.split(';').forEach(function (pair) {
                const parts = pair.split(':').map(function (s) { return s.trim(); });
                const attr = parts[0], key = parts[1];
                if (attr && key) el.setAttribute(attr, t(key));
            });
        });
    }

    function setLang(lang) {
        if (!SUPPORTED.includes(lang)) return Promise.resolve(_currentLang);
        try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* ignore */ }
        return loadBundle(lang).then(function () {
            _currentLang = lang;
            try { document.documentElement.setAttribute('lang', lang); } catch (e) { /* ignore */ }
            return lang;
        });
    }

    function getLang() { return _currentLang; }

    // v3.33.0 — idempotent init + ready promise
    // Bug fix: hiçbir yer init() çağırmadığı için aki_kesif bundle yüklenmiyor,
    // wizard.step.indicator gibi key'ler ham görünüyordu.
    let _initPromise = null;
    function ensureInit() {
        if (!_initPromise) _initPromise = init();
        return _initPromise;
    }

    window.VyraI18n = {
        init: init,
        ensureInit: ensureInit,
        t: t,
        applyTranslations: applyTranslations,
        setLang: setLang,
        getLang: getLang,
        SUPPORTED: SUPPORTED,
    };

    // Auto-bootstrap: DOMContentLoaded'da (veya hemen) ensureInit() tetikle.
    function _autoBoot() { ensureInit().catch(function (e) { console.warn('[i18n] auto-init failed', e); }); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _autoBoot, { once: true });
    } else {
        _autoBoot();
    }
})();
