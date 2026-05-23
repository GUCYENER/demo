/* v3.33.0 — Portal tooltip helper (R011 + R012)
   ================================================
   Use cases
   ---------
   - `[data-tt]`  → CSS-only `::after` tooltip (mevcut ui_tooltip.css).
                     Container'da `overflow:hidden`/scroll yoksa tercih et.
   - `[data-tt-portal]` → JS portal tooltip (BU DOSYA).
                     Container `overflow:hidden` (table cell, modal vs.) ise
                     `::after` clipping yapar; portal `<body>`'ye render
                     edildiği için clipping olmaz + viewport auto-flip.

   API
   ---
   Otomatik bind: DOMContentLoaded'da MutationObserver kurar; dinamik olarak
   eklenen `[data-tt-portal]` elementleri otomatik tanır.

   A11y
   ----
   - Hover + focus-visible'da gösterilir.
   - aria-label fallback'i mevcut ds_enrichment_module.js MutationObserver'ı
     `data-tt` üzerinden yaptığı için, portal varyantına da `data-tt`
     attribute'u verilmesi yeterli (aria-label otomatik mirror edilir).
   - prefers-reduced-motion → fade-in animasyonu atlanır (CSS'te tanımlı).
   - Escape tuşu → açık tooltip'i kapatır.
*/

(function () {
    'use strict';

    if (window.VyraTooltipPortal && window.VyraTooltipPortal._installed) {
        return;
    }

    const PORTAL_CLASS = 'tt-portal';
    const VIEWPORT_MARGIN = 8;   // viewport kenar tampon
    const TRIGGER_GAP = 6;        // tetikleyici ile tooltip arası

    let _currentPortal = null;
    let _currentTrigger = null;

    function _escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function _hide() {
        if (_currentPortal && _currentPortal.parentNode) {
            _currentPortal.parentNode.removeChild(_currentPortal);
        }
        _currentPortal = null;
        _currentTrigger = null;
    }

    function _show(trigger) {
        if (_currentTrigger === trigger && _currentPortal) {
            return;
        }
        _hide();

        const text = trigger.getAttribute('data-tt');
        if (!text) {
            return;
        }

        const multiline = trigger.hasAttribute('data-tt-multiline');

        const portal = document.createElement('div');
        portal.className = PORTAL_CLASS + (multiline ? ' tt-portal--multiline' : '');
        portal.setAttribute('role', 'tooltip');
        portal.innerHTML = _escapeHtml(text);
        // İlk render — measure için body'ye ekle, sonra position.
        portal.style.position = 'fixed';
        portal.style.top = '0px';
        portal.style.left = '0px';
        portal.style.visibility = 'hidden';
        document.body.appendChild(portal);

        const rect = trigger.getBoundingClientRect();
        const ttRect = portal.getBoundingClientRect();
        const vpH = window.innerHeight;
        const vpW = window.innerWidth;

        // R012 — Vertical auto-flip: tercihen tetikleyicinin ÜSTÜNDE; yoksa altına.
        let top = rect.top - ttRect.height - TRIGGER_GAP;
        if (top < VIEWPORT_MARGIN) {
            top = rect.bottom + TRIGGER_GAP;
            // Alta da sığmazsa viewport içine clamp et.
            if (top + ttRect.height > vpH - VIEWPORT_MARGIN) {
                top = Math.max(VIEWPORT_MARGIN, vpH - ttRect.height - VIEWPORT_MARGIN);
            }
        }

        // Horizontal center, viewport içine clamp.
        let left = rect.left + (rect.width / 2) - (ttRect.width / 2);
        if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN;
        if (left + ttRect.width > vpW - VIEWPORT_MARGIN) {
            left = vpW - ttRect.width - VIEWPORT_MARGIN;
        }

        portal.style.top = `${Math.round(top)}px`;
        portal.style.left = `${Math.round(left)}px`;
        portal.style.visibility = 'visible';

        _currentPortal = portal;
        _currentTrigger = trigger;
    }

    function _onPointerOver(e) {
        const trigger = e.target.closest('[data-tt-portal]');
        if (trigger) _show(trigger);
    }

    function _onPointerOut(e) {
        const trigger = e.target.closest('[data-tt-portal]');
        if (trigger && trigger === _currentTrigger) {
            // relatedTarget hala trigger içinde mi?
            const rel = e.relatedTarget;
            if (rel && trigger.contains(rel)) return;
            _hide();
        }
    }

    function _onFocusIn(e) {
        const trigger = e.target.closest('[data-tt-portal]');
        if (trigger) _show(trigger);
    }

    function _onFocusOut(e) {
        const trigger = e.target.closest('[data-tt-portal]');
        if (trigger && trigger === _currentTrigger) _hide();
    }

    function _onScrollOrResize() {
        if (_currentTrigger) _hide();
    }

    function _onKeyDown(e) {
        if (e.key === 'Escape' && _currentPortal) _hide();
    }

    function _install() {
        document.addEventListener('pointerover', _onPointerOver, true);
        document.addEventListener('pointerout', _onPointerOut, true);
        document.addEventListener('focusin', _onFocusIn, true);
        document.addEventListener('focusout', _onFocusOut, true);
        window.addEventListener('scroll', _onScrollOrResize, true);
        window.addEventListener('resize', _onScrollOrResize);
        document.addEventListener('keydown', _onKeyDown);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _install, { once: true });
    } else {
        _install();
    }

    window.VyraTooltipPortal = {
        _installed: true,
        hide: _hide,
        show: _show
    };
})();
