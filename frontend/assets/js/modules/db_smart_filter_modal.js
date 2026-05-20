/**
 * VYRA — DB Smart Filter Modal (Faz 3 / P20-C / v3.30.0)
 * ======================================================
 * Small modal to compose a filter spec {expr, op, value} for the AST editor
 * (`window.DbSmartAstEditor`). Lazy-mounted via ensureModal() on first open.
 *
 * Public API:
 *   window.DbSmartFilterModal = {
 *     open({columns, dialect}) → Promise<spec|null>
 *   }
 *
 *   spec = {expr: "alias.col", op: "=", value: "v"}     // value-bearing ops
 *   spec = {expr: "alias.col", op: "IS NULL"}            // unary ops (no value)
 *   spec = {expr: "alias.col", op: "IN", value: [...]}   // IN list (csv split)
 *   open(...) resolves null on Esc / backdrop / cancel.
 *
 * HEBE Gate (HEBE §5c):
 *   - role="dialog" + aria-modal="true" + aria-labelledby
 *   - Focus trap (Tab cycle first↔last) + ilk açılışta first field focus
 *   - Esc → cancel (resolve null) + return focus to opener
 *   - Backdrop click → cancel; content click not propagated
 *   - Invalid value → role="alert" inline error; submit blocked
 *   - prefers-reduced-motion: CSS guard'lı (CSS tarafında)
 *
 * Idempotent global: rerun overwrite uyarısı.
 */
(function () {
    'use strict';

    if (window.DbSmartFilterModal) {
        console.info('[DbSmartFilterModal] overwriting previous definition (rerun/hot-reload)');
    }

    var MODAL_ID = 'dswFilterModal';
    var TITLE_ID = 'dswFilterTitle';
    var FORM_ID = 'dswFilterForm';
    var COL_ID = 'dswFmColumn';
    var OP_ID = 'dswFmOp';
    var VAL_ID = 'dswFmValue';
    var ERR_ID = 'dswFmError';

    var UNARY_OPS = ['IS NULL', 'IS NOT NULL'];
    var ALL_OPS = ['=', '!=', '<', '<=', '>', '>=', 'LIKE', 'ILIKE', 'IS NULL', 'IS NOT NULL', 'IN'];

    // Resolver kapsamı — open() çağrısı boyunca tek modal/promise.
    var currentResolve = null;
    var openerEl = null;

    function $(id) { return document.getElementById(id); }

    function ensureModal() {
        if ($(MODAL_ID)) return;
        var root = document.createElement('div');
        root.id = MODAL_ID;
        root.className = 'dsw-fm-modal';
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        root.setAttribute('aria-labelledby', TITLE_ID);
        root.hidden = true;

        root.innerHTML = ''
            + '<div class="dsw-fm-backdrop" data-action="close" tabindex="-1"></div>'
            + '<div class="dsw-fm-dialog" role="document">'
            + '  <div class="dsw-fm-header">'
            + '    <h2 id="' + TITLE_ID + '" class="dsw-fm-title">Filtre Ekle</h2>'
            + '    <button type="button" class="dsw-fm-close" data-action="close" aria-label="Kapat">×</button>'
            + '  </div>'
            + '  <form id="' + FORM_ID + '" class="dsw-fm-body" novalidate>'
            + '    <label class="dsw-fm-field">'
            + '      <span class="dsw-fm-label">Kolon</span>'
            + '      <select id="' + COL_ID + '" required></select>'
            + '    </label>'
            + '    <label class="dsw-fm-field">'
            + '      <span class="dsw-fm-label">İşleç</span>'
            + '      <select id="' + OP_ID + '" required></select>'
            + '    </label>'
            + '    <label class="dsw-fm-field" id="dswFmValueWrap">'
            + '      <span class="dsw-fm-label">Değer</span>'
            + '      <input id="' + VAL_ID + '" type="text" autocomplete="off"'
            + '             aria-describedby="' + ERR_ID + '" />'
            + '    </label>'
            + '    <div id="' + ERR_ID + '" class="dsw-fm-error" role="alert" aria-live="assertive"></div>'
            + '  </form>'
            + '  <div class="dsw-fm-foot">'
            + '    <button type="button" class="dsw-fm-btn-ghost" data-action="close">İptal</button>'
            + '    <button type="button" class="dsw-fm-btn" data-action="submit">Ekle</button>'
            + '  </div>'
            + '</div>';
        document.body.appendChild(root);

        // Op select doldur (ilk ensureModal'da; her open'da güncellenmez — sabit liste).
        var opSel = $(OP_ID);
        for (var i = 0; i < ALL_OPS.length; i += 1) {
            var o = document.createElement('option');
            o.value = ALL_OPS[i];
            o.textContent = ALL_OPS[i];
            opSel.appendChild(o);
        }

        // Event wiring.
        root.addEventListener('click', _onRootClick);
        root.addEventListener('keydown', _onKeyDown);
        opSel.addEventListener('change', _onOpChange);
    }

    function _onRootClick(e) {
        var t = e.target;
        if (!t || !t.dataset) return;
        if (t.dataset.action === 'close') {
            e.preventDefault();
            _close(null);
        } else if (t.dataset.action === 'submit') {
            e.preventDefault();
            _submit();
        }
    }

    function _onKeyDown(e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            _close(null);
            return;
        }
        if (e.key === 'Enter' && e.target && e.target.tagName !== 'BUTTON') {
            // Enter on a field → submit.
            e.preventDefault();
            _submit();
            return;
        }
        if (e.key === 'Tab') {
            _trapTab(e);
        }
    }

    function _trapTab(e) {
        var root = $(MODAL_ID);
        if (!root) return;
        var focusables = root.querySelectorAll(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        var active = document.activeElement;
        if (e.shiftKey && active === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && active === last) {
            e.preventDefault();
            first.focus();
        }
    }

    function _onOpChange() {
        var op = $(OP_ID).value;
        var wrap = $('dswFmValueWrap');
        var input = $(VAL_ID);
        var isUnary = UNARY_OPS.indexOf(op) !== -1;
        if (wrap) wrap.hidden = isUnary;
        if (input) {
            input.required = !isUnary;
            if (isUnary) input.value = '';
        }
        _setError('');
    }

    function _setError(msg) {
        var el = $(ERR_ID);
        if (!el) return;
        el.textContent = msg || '';
        el.classList.toggle('dsw-fm-error-visible', !!msg);
    }

    function _validate() {
        var expr = $(COL_ID).value;
        var op = $(OP_ID).value;
        var raw = $(VAL_ID).value;
        if (!expr) {
            _setError('Kolon seçin.');
            $(COL_ID).focus();
            return null;
        }
        if (ALL_OPS.indexOf(op) === -1) {
            _setError('Geçersiz işleç.');
            $(OP_ID).focus();
            return null;
        }
        var isUnary = UNARY_OPS.indexOf(op) !== -1;
        if (isUnary) {
            return { expr: expr, op: op };
        }
        if (raw === '' || raw == null) {
            _setError('Değer boş olamaz.');
            $(VAL_ID).focus();
            return null;
        }
        if (op === 'IN') {
            // CSV split + trim; boş öğeleri at.
            var parts = raw.split(',').map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 0; });
            if (parts.length === 0) {
                _setError('IN listesi boş.');
                $(VAL_ID).focus();
                return null;
            }
            return { expr: expr, op: op, value: parts };
        }
        return { expr: expr, op: op, value: raw };
    }

    function _submit() {
        var spec = _validate();
        if (spec) _close(spec);
    }

    function _close(result) {
        var root = $(MODAL_ID);
        if (root) root.hidden = true;
        document.body.classList.remove('dsw-fm-open');
        var resolver = currentResolve;
        var prevOpener = openerEl;
        currentResolve = null;
        openerEl = null;
        if (prevOpener && typeof prevOpener.focus === 'function') {
            try { prevOpener.focus(); } catch (e) { /* ignore */ }
        }
        if (resolver) resolver(result);
    }

    function _populateColumns(columns) {
        var sel = $(COL_ID);
        sel.innerHTML = '';
        var arr = Array.isArray(columns) ? columns : [];
        for (var i = 0; i < arr.length; i += 1) {
            var c = arr[i];
            var opt = document.createElement('option');
            if (typeof c === 'string') {
                opt.value = c;
                opt.textContent = c;
            } else if (c && typeof c === 'object') {
                opt.value = c.expr || c.value || c.name || '';
                opt.textContent = c.label || c.name || opt.value;
            } else {
                continue;
            }
            sel.appendChild(opt);
        }
    }

    // ---- Public ----
    function open(opts) {
        opts = opts || {};
        ensureModal();
        if (currentResolve) {
            // Önceki açılış henüz kapanmadı — onu cancel'la.
            _close(null);
        }
        openerEl = document.activeElement;
        _populateColumns(opts.columns || []);
        // Op select default = "=" (ilk seçenek)
        var opSel = $(OP_ID);
        if (opSel.options.length > 0) opSel.selectedIndex = 0;
        _onOpChange();
        $(VAL_ID).value = '';
        _setError('');

        var root = $(MODAL_ID);
        root.hidden = false;
        document.body.classList.add('dsw-fm-open');

        // Initial focus = column select.
        setTimeout(function () {
            try { $(COL_ID).focus(); } catch (e) { /* ignore */ }
        }, 0);

        return new Promise(function (resolve) { currentResolve = resolve; });
    }

    window.DbSmartFilterModal = { open: open };
})();
