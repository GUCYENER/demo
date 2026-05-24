/**
 * VYRA — DB Smart AST Editor (Faz 3 / P20-A / v3.30.0)
 * =====================================================
 * Interaktif SQL AST editörü. Step 4'te mount edilir; kolon/order/filter
 * listelerini DnD + klavye ile yeniden düzenler, server ile patch + explain
 * round-trip yapar, undo/redo + diff toast desteği sunar.
 *
 * Public API:
 *   window.DbSmartAstEditor = {
 *     mount(rootEl, {sessionUid, dialect, ast, fetchJson?, onChange?}),
 *     unmount(),
 *     getAst(),
 *     getHistory(),
 *   }
 *
 * Bağımlılıklar (sibling modüller — bu modül yazmaz, çağırır):
 *   - window.DbSmartAstHistory : push/undo/redo/canUndo/canRedo/clear  (P20-B)
 *   - window.DbSmartFilterModal: open({columns,dialect}) → Promise<spec|null> (P20-C)
 *   - window.showToast(msg, type)
 *
 * HEBE Gate (§5c):
 *   - role="region" aria-label="AST düzenleyici"
 *   - role="list" + role="listitem" tabindex=0 aria-grabbed
 *   - Space=grab/drop, Arrow=move, Enter=drop, Esc=cancel-grab, Delete=remove
 *   - aria-live polite via #dswAstLive (P20-C tarafından home.html'de yer alır)
 *   - prefers-reduced-motion (CSS, P20-C tarafında)
 *
 * Idempotent global: rerun overwrite warning.
 */
(function () {
    'use strict';

    if (window.DbSmartAstEditor) {
        console.info('[DbSmartAstEditor] overwriting previous definition (rerun/hot-reload)');
    }

    // EDIT8 (ARES+POSEIDON 2026-05-25): API_BASE göreceli olmalı.
    // Wizard'ın enjekte ettiği `_fetchJson` → `vyraFetch` → `VYRA_API.request`
    // ki `request()` zaten `API_BASE_URL` (= "http://host/api") prefix ekliyor.
    // Mutlak URL geçersek: "http://host/api" + "http://host/api/db-smart/..."
    // → "http://host/apihttp://host/api/db-smart/..." → 405 (path eşleşmiyor).
    var API_BASE = '/db-smart';
    var DEBOUNCE_MS = 250;
    var COST_GREEN = 1e4;
    var COST_YELLOW = 1e6;

    // ---- State (closure-scoped, single editor instance at a time) ----
    var state = null;

    function _initState(rootEl, opts) {
        return {
            rootEl: rootEl,
            sessionUid: opts.sessionUid || null,
            dialect: opts.dialect || 'postgresql',
            ast: opts.ast || null,
            fetchJson: typeof opts.fetchJson === 'function' ? opts.fetchJson : _defaultFetchJson,
            onChange: typeof opts.onChange === 'function' ? opts.onChange : null,
            debounceTimer: null,
            pendingOps: [],          // coalesce: [{op, args, prevAst}]
            patchAbort: null,
            explainAbort: null,
            grabbed: null,           // {listKey, index} | null
            filterModalOpen: false,
            globalKeyHandler: null,
            lastExplain: null,       // {cost, cached}
            // F6 (HERMES+ATHENA 2026-05-25): user-initiated patch'leri mount-time'dan
            // ayırt etmek için son etkileşim zamanı. Toast politikası buna bakıyor.
            lastInteractionAt: 0,
        };
    }

    // F6 (HERMES+ATHENA 2026-05-25): user-initiated patch'leri işaretle.
    function _markInteraction() {
        if (state) state.lastInteractionAt = Date.now();
    }

    // ---- Default fetchJson (Bearer auth — wizard pattern mirrored) ----
    // raw fetch: AbortController signal (patch/explain debounce cancellation) — vyraFetch not applicable.
    function _defaultFetchJson(url, opts) {
        opts = opts || {};
        var token = (window.localStorage && localStorage.getItem('access_token')) || '';
        var headers = Object.assign({
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json',
        }, opts.headers || {});
        var fetchOpts = Object.assign({}, opts, { headers: headers });
        // EDIT8 (ARES+POSEIDON 2026-05-25): API_BASE göreceli olduğu için standalone
        // (wizard yokken) çağrıda host prefix'i burada eklenir. Wizard kullanılırken
        // bu fonksiyon zaten çağrılmıyor (wizard _fetchJson enjekte ediyor).
        var fullUrl = url;
        if (typeof url === 'string' && url.charAt(0) === '/') {
            var apiHost = (window.API_BASE_URL || 'http://localhost:8002');
            fullUrl = apiHost + '/api' + url;
        }
        return fetch(fullUrl, fetchOpts).then(function (res) {
            if (!res.ok) {
                return res.text().catch(function () { return ''; }).then(function (txt) {
                    var err = new Error(res.status + ': ' + (txt || res.statusText));
                    err.status = res.status;
                    err.body = txt;
                    throw err;
                });
            }
            return res.json();
        });
    }

    // ---- Utilities ----
    function _escape(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    function _announce(msg) {
        var live = document.getElementById('dswAstLive');
        if (live) live.textContent = msg || '';
    }

    function _toast(msg, type) {
        if (typeof window.showToast === 'function') {
            try { window.showToast(msg, type || 'info'); } catch (e) { /* ignore */ }
        }
    }

    function _deepClone(obj) {
        try { return JSON.parse(JSON.stringify(obj)); }
        catch (e) { return null; }
    }

    function _columnsFromAst(ast) {
        // Returns [{expr, label}] for filter modal selector.
        var out = [];
        if (!ast || !ast.select) return out;
        var sel = ast.select;
        for (var i = 0; i < sel.length; i += 1) {
            var c = sel[i];
            if (typeof c === 'string') {
                out.push({ expr: c, label: c });
            } else if (c && typeof c === 'object') {
                var expr = c.expr || c.column || c.name || '';
                if (expr) out.push({ expr: expr, label: c.alias || c.label || expr });
            }
        }
        return out;
    }

    // ---- Render ----
    function _render() {
        if (!state || !state.rootEl) return;
        var root = state.rootEl;
        if (!state.ast) {
            root.innerHTML = '<p class="dsw-ast-empty">AST henüz hazır değil.</p>';
            return;
        }
        root.innerHTML = ''
            + _renderToolbar()
            + '<div class="dsw-ast-sections">'
            + '  <section class="dsw-ast-section" data-key="select">'
            + '    <h4 class="dsw-ast-section-title">SELECT</h4>'
            + _renderSelectList()
            + '  </section>'
            + '  <section class="dsw-ast-section" data-key="order">'
            + '    <h4 class="dsw-ast-section-title">ORDER BY</h4>'
            + _renderOrderList()
            + '  </section>'
            + '  <section class="dsw-ast-section" data-key="filters">'
            + '    <h4 class="dsw-ast-section-title">WHERE</h4>'
            + _renderFilterChips()
            + '  </section>'
            + '</div>'
            + _renderCostBadge();

        _wire();
    }

    function _renderToolbar() {
        // F22 (HEBE 2026-05-25): Geri Al / Yinele butonları UI'dan kaldırıldı —
        // klavye kısayolu (Ctrl+Z / Ctrl+Y) hâlâ aktif (L783+ global key handler).
        return '';
    }

    function _renderSelectList() {
        var sel = (state.ast && state.ast.select) || [];
        var html = '<ul class="dsw-ast-list" role="list" data-list="select">';
        for (var i = 0; i < sel.length; i += 1) {
            var c = sel[i];
            var expr = (typeof c === 'string') ? c : (c && (c.expr || c.column || c.name)) || '';
            var label = (c && typeof c === 'object' && (c.alias || c.label)) || expr;
            html += ''
                + '<li class="dsw-ast-item" role="listitem" draggable="true"'
                + '    tabindex="0" aria-grabbed="false"'
                + '    data-list="select" data-index="' + i + '"'
                + '    aria-label="Kolon ' + _escape(label) + ', sürükle veya boşluk tuşu ile taşı">'
                + '  <span class="dsw-ast-item-label">' + _escape(label) + '</span>'
                + '  <button type="button" class="dsw-ast-item-remove" aria-label="Kaldır"'
                + '          data-action="remove_column" data-index="' + i + '">×</button>'
                + '</li>';
        }
        html += '</ul>';
        if (sel.length === 0) html += '<p class="dsw-ast-empty-line">Kolon seçilmedi.</p>';
        return html;
    }

    function _renderOrderList() {
        var ord = (state.ast && state.ast.order_by) || [];
        var html = '<ul class="dsw-ast-list" role="list" data-list="order">';
        for (var i = 0; i < ord.length; i += 1) {
            var o = ord[i];
            var expr = (typeof o === 'string') ? o : (o && (o.expr || o.column)) || '';
            var dir = (o && typeof o === 'object' && o.direction) ? String(o.direction).toUpperCase() : 'ASC';
            if (dir !== 'ASC' && dir !== 'DESC') dir = 'ASC';
            html += ''
                + '<li class="dsw-ast-item" role="listitem" draggable="true"'
                + '    tabindex="0" aria-grabbed="false"'
                + '    data-list="order" data-index="' + i + '"'
                + '    aria-label="Sıralama ' + _escape(expr) + ' ' + dir + '">'
                + '  <span class="dsw-ast-item-label">' + _escape(expr) + '</span>'
                + '  <button type="button" class="dsw-ast-order-toggle"'
                + '          data-action="toggle_order_dir" data-index="' + i + '"'
                + '          aria-label="Yönü değiştir, şu an ' + dir + '">' + dir + '</button>'
                + '  <button type="button" class="dsw-ast-item-remove" aria-label="Sıralamayı kaldır"'
                + '          data-action="remove_order" data-index="' + i + '">×</button>'
                + '</li>';
        }
        html += '</ul>';
        if (ord.length === 0) html += '<p class="dsw-ast-empty-line">Sıralama yok.</p>';
        return html;
    }

    function _renderFilterChips() {
        var fs = (state.ast && state.ast.filters) || [];
        var html = '<div class="dsw-ast-chips" role="list">';
        for (var i = 0; i < fs.length; i += 1) {
            var f = fs[i] || {};
            var text = (f.expr || '') + ' ' + (f.op || '');
            if (f.op !== 'IS NULL' && f.op !== 'IS NOT NULL') {
                var v = f.value;
                if (Array.isArray(v)) v = v.join(', ');
                text += ' ' + (v == null ? '' : String(v));
            }
            html += ''
                + '<button type="button" class="dsw-ast-chip" role="listitem"'
                + '        data-action="remove_filter" data-index="' + i + '"'
                + '        aria-label="Filtreyi kaldır: ' + _escape(text) + '">'
                + '  <span class="dsw-ast-chip-text">' + _escape(text) + '</span>'
                + '  <span class="dsw-ast-chip-x" aria-hidden="true">×</span>'
                + '</button>';
        }
        html += ''
            + '  <button type="button" class="dsw-ast-chip dsw-ast-chip-add"'
            + '          data-action="add_filter" aria-label="Filtre ekle">+ Ekle</button>'
            + '</div>';
        return html;
    }

    function _renderCostBadge() {
        // F22b (HEBE 2026-05-25): kullanıcı talebi — "Maliyet: ?" etiketi
        // step 4 önizlemeden kaldırıldı. Cost backend pipeline'ı henüz
        // sinyal vermediği için sürekli "?" gösteriyor → kafa karıştırıcı.
        return '';
    }

    function _formatCost(n) {
        if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
        if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
        if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
        return String(Math.round(n));
    }

    // ---- Event wiring (called after _render) ----
    function _wire() {
        var root = state.rootEl;
        root.addEventListener('click', _onRootClick);
        var lists = root.querySelectorAll('.dsw-ast-list');
        for (var i = 0; i < lists.length; i += 1) {
            _attachDnd(lists[i]);
            _attachKeyboardReorder(lists[i]);
        }
    }

    function _onRootClick(e) {
        var btn = e.target.closest && e.target.closest('[data-action]');
        if (!btn) return;
        var action = btn.dataset.action;
        var idx = parseInt(btn.dataset.index, 10);
        _markInteraction();  // F6: kullanıcı etkileşimi — toast'a yetki ver
        if (action === 'undo') { e.preventDefault(); undo(); return; }
        if (action === 'redo') { e.preventDefault(); redo(); return; }
        if (action === 'remove_column' && !isNaN(idx)) {
            _applyPatch('remove_column', { index: idx });
        } else if (action === 'remove_order' && !isNaN(idx)) {
            _applyPatch('remove_order', { index: idx });
        } else if (action === 'remove_filter' && !isNaN(idx)) {
            _applyPatch('remove_filter', { index: idx });
        } else if (action === 'toggle_order_dir' && !isNaN(idx)) {
            var ord = (state.ast && state.ast.order_by) || [];
            var cur = ord[idx] || {};
            var dir = (cur && cur.direction || 'ASC').toUpperCase();
            var next = dir === 'ASC' ? 'DESC' : 'ASC';
            _applyPatch('modify_order_dir', { index: idx, direction: next });
        } else if (action === 'add_filter') {
            _openAddFilterModal();
        }
    }

    function _openAddFilterModal() {
        if (state.filterModalOpen) return;
        var modal = window.DbSmartFilterModal;
        if (!modal || typeof modal.open !== 'function') {
            _toast('Filtre modülü yüklenmedi.', 'error');
            return;
        }
        // F6 (HERMES+ATHENA 2026-05-25): kolon kataloğu boşsa modal'ın
        // dropdown'u boş kalmasın — `*` placeholder ile en azından modal açılsın
        // ve kullanıcı operatör/değer doldurabilsin. F7 ile multi-table
        // kolon endpoint'i geldiğinde wizard buraya `state.options.columns`
        // enjekte edecek.
        var cols = _columnsFromAst(state.ast);
        if (!cols || cols.length === 0) {
            cols = [{ expr: '*', label: '*' }];
        }
        state.filterModalOpen = true;
        modal.open({ columns: cols, dialect: state.dialect })
            .then(function (spec) {
                state.filterModalOpen = false;
                if (spec) {
                    _markInteraction();  // F6: filter ekleme açık bir user aksiyonu
                    _applyPatch('add_filter', spec);
                }
            })
            .catch(function (err) {
                state.filterModalOpen = false;
                console.warn('[DbSmartAstEditor] filter modal error', err);
            });
    }

    // ---- DnD ----
    function _attachDnd(listEl) {
        var listKey = listEl.dataset.list;
        listEl.addEventListener('dragstart', function (e) {
            var li = e.target.closest && e.target.closest('.dsw-ast-item');
            if (!li || li.parentElement !== listEl) return;
            li.setAttribute('aria-grabbed', 'true');
            li.classList.add('dragging');
            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
                try { e.dataTransfer.setData('text/plain', li.dataset.index); } catch (_) { /* ignore */ }
            }
        });
        listEl.addEventListener('dragend', function (e) {
            var li = e.target.closest && e.target.closest('.dsw-ast-item');
            if (li) {
                li.setAttribute('aria-grabbed', 'false');
                li.classList.remove('dragging');
            }
            _removeDropIndicator(listEl);
        });
        listEl.addEventListener('dragover', function (e) {
            e.preventDefault();
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
            _showDropIndicator(listEl, e.clientY);
        });
        listEl.addEventListener('dragleave', function () {
            _removeDropIndicator(listEl);
        });
        listEl.addEventListener('drop', function (e) {
            e.preventDefault();
            var fromIdx = parseInt(e.dataTransfer && e.dataTransfer.getData('text/plain'), 10);
            var toIdx = _dropIndexAt(listEl, e.clientY);
            _removeDropIndicator(listEl);
            if (isNaN(fromIdx) || isNaN(toIdx) || fromIdx === toIdx) return;
            _markInteraction();  // F6: DnD bir user etkileşimi
            var op = listKey === 'select' ? 'reorder_columns' : 'reorder_order';
            _applyPatch(op, { from: fromIdx, to: toIdx });
        });
    }

    function _dropIndexAt(listEl, clientY) {
        var items = listEl.querySelectorAll('.dsw-ast-item');
        for (var i = 0; i < items.length; i += 1) {
            var rect = items[i].getBoundingClientRect();
            if (clientY < rect.top + rect.height / 2) return i;
        }
        return items.length;
    }

    function _showDropIndicator(listEl, clientY) {
        _removeDropIndicator(listEl);
        var idx = _dropIndexAt(listEl, clientY);
        var ind = document.createElement('div');
        ind.className = 'dsw-drop-indicator';
        ind.setAttribute('aria-hidden', 'true');
        var items = listEl.querySelectorAll('.dsw-ast-item');
        if (idx >= items.length) {
            listEl.appendChild(ind);
        } else {
            listEl.insertBefore(ind, items[idx]);
        }
    }

    function _removeDropIndicator(listEl) {
        var ind = listEl.querySelector('.dsw-drop-indicator');
        if (ind && ind.parentNode) ind.parentNode.removeChild(ind);
    }

    // ---- Keyboard reorder (Space=grab, Arrow=move, Enter=drop, Esc=cancel, Delete=remove) ----
    function _attachKeyboardReorder(listEl) {
        var listKey = listEl.dataset.list;
        listEl.addEventListener('keydown', function (e) {
            var li = e.target.closest && e.target.closest('.dsw-ast-item');
            if (!li || li.parentElement !== listEl) return;
            var idx = parseInt(li.dataset.index, 10);
            if (isNaN(idx)) return;
            _markInteraction();  // F6: klavye reorder/silme user etkileşimidir

            if (e.key === ' ' || e.key === 'Spacebar') {
                e.preventDefault();
                if (state.grabbed && state.grabbed.listKey === listKey && state.grabbed.index === idx) {
                    // Drop in place — clear grabbed.
                    li.setAttribute('aria-grabbed', 'false');
                    state.grabbed = null;
                    _announce('Bırakıldı.');
                } else {
                    if (state.grabbed) {
                        var prev = _findItem(state.grabbed.listKey, state.grabbed.index);
                        if (prev) prev.setAttribute('aria-grabbed', 'false');
                    }
                    li.setAttribute('aria-grabbed', 'true');
                    state.grabbed = { listKey: listKey, index: idx };
                    _announce('Tutuldu. Ok tuşlarıyla taşıyın, Enter ile bırakın, Esc ile iptal.');
                }
                return;
            }
            if (e.key === 'Escape') {
                if (state.grabbed) {
                    e.preventDefault();
                    li.setAttribute('aria-grabbed', 'false');
                    state.grabbed = null;
                    _announce('İptal edildi.');
                }
                return;
            }
            if (e.key === 'Enter') {
                if (state.grabbed && state.grabbed.listKey === listKey) {
                    e.preventDefault();
                    var from = state.grabbed.index;
                    if (from !== idx) {
                        var op = listKey === 'select' ? 'reorder_columns' : 'reorder_order';
                        _applyPatch(op, { from: from, to: idx });
                    }
                    state.grabbed = null;
                    _announce('Bırakıldı.');
                }
                return;
            }
            if (e.key === 'Delete' || e.key === 'Backspace') {
                e.preventDefault();
                var rmOp = listKey === 'select' ? 'remove_column'
                         : listKey === 'order' ? 'remove_order'
                         : 'remove_filter';
                _applyPatch(rmOp, { index: idx });
                return;
            }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                var dir = e.key === 'ArrowDown' ? 1 : -1;
                if (state.grabbed && state.grabbed.listKey === listKey && state.grabbed.index === idx) {
                    var target = idx + dir;
                    var items = listEl.querySelectorAll('.dsw-ast-item');
                    if (target < 0 || target >= items.length) return;
                    var op2 = listKey === 'select' ? 'reorder_columns' : 'reorder_order';
                    _applyPatch(op2, { from: idx, to: target });
                    state.grabbed = { listKey: listKey, index: target };
                    // Re-focus after re-render
                    setTimeout(function () {
                        var moved = _findItem(listKey, target);
                        if (moved) { moved.focus(); moved.setAttribute('aria-grabbed', 'true'); }
                    }, 0);
                } else {
                    var nextIdx = idx + dir;
                    var sib = _findItem(listKey, nextIdx);
                    if (sib) sib.focus();
                }
            }
        });
    }

    function _findItem(listKey, idx) {
        if (!state || !state.rootEl) return null;
        return state.rootEl.querySelector(
            '.dsw-ast-item[data-list="' + listKey + '"][data-index="' + idx + '"]'
        );
    }

    // ---- Patch + Explain ----
    function _applyPatch(op, args) {
        if (!state || !state.ast) return;
        var prevAst = _deepClone(state.ast);
        // Optimistic mutate (best-effort; server is authoritative)
        _optimisticApply(state.ast, op, args);
        _pushHistory(prevAst, op);
        _render();
        _debouncedPatch(op, args, prevAst);
    }

    function _optimisticApply(ast, op, args) {
        if (!ast) return;
        try {
            if (op === 'remove_column' && ast.select) {
                ast.select.splice(args.index, 1);
            } else if (op === 'remove_order' && ast.order_by) {
                ast.order_by.splice(args.index, 1);
            } else if (op === 'remove_filter' && ast.filters) {
                ast.filters.splice(args.index, 1);
            } else if (op === 'reorder_columns' && ast.select) {
                var s = ast.select.splice(args.from, 1)[0];
                ast.select.splice(args.to, 0, s);
            } else if (op === 'reorder_order' && ast.order_by) {
                var o = ast.order_by.splice(args.from, 1)[0];
                ast.order_by.splice(args.to, 0, o);
            } else if (op === 'modify_order_dir' && ast.order_by) {
                var item = ast.order_by[args.index];
                if (typeof item === 'string') {
                    ast.order_by[args.index] = { expr: item, direction: args.direction };
                } else if (item && typeof item === 'object') {
                    item.direction = args.direction;
                }
            } else if (op === 'add_filter') {
                ast.filters = ast.filters || [];
                ast.filters.push(args);
            }
        } catch (e) { /* ignore — server will return canonical */ }
    }

    function _pushHistory(prevAst, label) {
        var hist = window.DbSmartAstHistory;
        if (hist && typeof hist.push === 'function') {
            try { hist.push(prevAst, label); } catch (e) { /* ignore */ }
        }
    }

    function _debouncedPatch(op, args, prevAst) {
        if (state.debounceTimer) clearTimeout(state.debounceTimer);
        state.pendingOps.push({ op: op, args: args, prevAst: prevAst });
        state.debounceTimer = setTimeout(_flushPatch, DEBOUNCE_MS);
    }

    function _flushPatch() {
        if (!state || state.pendingOps.length === 0) return;
        var pending = state.pendingOps.slice();
        var rollbackAst = pending[0].prevAst;
        state.pendingOps = [];
        state.debounceTimer = null;
        if (!state.sessionUid) {
            _toast('Oturum hazır değil.', 'error');
            return;
        }
        // For simplicity send the LAST op; server is authoritative and will return the AST.
        var last = pending[pending.length - 1];
        if (state.patchAbort) {
            try { state.patchAbort.abort(); } catch (e) { /* ignore */ }
        }
        state.patchAbort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        var url = API_BASE + '/sessions/' + encodeURIComponent(state.sessionUid) + '/ast/patch';
        var body = {
            op: last.op,
            args: last.args,
            render_preview: true,
            dialect: state.dialect,
        };
        var fetchOpts = {
            method: 'POST',
            body: JSON.stringify(body),
        };
        if (state.patchAbort) fetchOpts.signal = state.patchAbort.signal;
        state.fetchJson(url, fetchOpts).then(function (data) {
            state.patchAbort = null;
            if (data && data.ast) {
                state.ast = data.ast;
                _render();
                if (state.onChange) {
                    try { state.onChange(data.ast, data.sql || null); } catch (e) { /* ignore */ }
                }
            }
            _refreshExplain();
        }).catch(function (err) {
            state.patchAbort = null;
            if (err && err.name === 'AbortError') return;
            var status = err && err.status;
            var now = Date.now();
            var userInitiated = state.lastInteractionAt &&
                (now - state.lastInteractionAt) < 2000;
            // F6 (HERMES+ATHENA 2026-05-25): Toast spam'ini ve "+Ekle hiçbir şey
            // yapmadı" yanılgısını gider.
            //  - 400/409 → user-meaningful (validation / conflict): rollback + toast.
            //  - 404 veya network (no status) → sessiz: rollback YOK (optimistic
            //    state kalsın), sadece console.warn. Çoğu zaman geçici/race veya
            //    mount-time çağrı; kullanıcı için anlamsız.
            //  - Diğer status → sadece kullanıcı son 2s içinde etkileşimde
            //    bulunduysa toast; aksi halde console.warn.
            if (status === 400 || status === 409) {
                state.ast = rollbackAst;
                _render();
                var msg = (status === 400)
                    ? 'Geçersiz işlem.'
                    : 'AST çakışması — sayfayı yenileyin.';
                _toast(msg, 'error');
                console.warn('[DbSmartAstEditor] patch failed', err);
                return;
            }
            if (status === 404 || !status) {
                // Optimistic state korunur — kullanıcının +Ekle ile koyduğu chip
                // ekranda kalır; backend transient ise sonraki round-trip
                // resolve eder. Toast YOK.
                console.warn('[DbSmartAstEditor] patch soft-failed (status=' +
                    (status || 'network') + '); keeping optimistic state', err);
                return;
            }
            // 5xx ve diğer hatalar: rollback + toast (yalnız user-initiated).
            state.ast = rollbackAst;
            _render();
            if (userInitiated) {
                _toast('AST yaması başarısız', 'error');
            }
            console.warn('[DbSmartAstEditor] patch failed', err);
        });
    }

    function _refreshExplain() {
        if (!state || !state.ast) return;
        // EDIT8 (ARES+POSEIDON 2026-05-25): sessionUid guard — boş/undefined/null
        // değerlerle ".../sessions/undefined/explain" gibi URL üretip 405 almayı engelle.
        var uid = state.sessionUid;
        if (!uid || typeof uid !== 'string' || uid === 'undefined' || uid === 'null') {
            return;
        }
        if (state.explainAbort) {
            try { state.explainAbort.abort(); } catch (e) { /* ignore */ }
        }
        state.explainAbort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        var url = API_BASE + '/sessions/' + encodeURIComponent(state.sessionUid) + '/explain';
        var fetchOpts = {
            method: 'POST',
            body: JSON.stringify({ ast: state.ast, dialect: state.dialect }),
        };
        if (state.explainAbort) fetchOpts.signal = state.explainAbort.signal;
        state.fetchJson(url, fetchOpts).then(function (data) {
            state.explainAbort = null;
            // F17 (ARES+POSEIDON+HERMES 2026-05-25): Backend `has_ast: false`
            // ile graceful skip dönüyor (AST type=select set edilmemiş veya
            // session AST persist edilmemiş). Cost badge'i temizle, hata olarak
            // işaretleme — sessiz devam.
            if (data && data.has_ast === false) {
                state.lastExplain = null;
                _updateCostBadge();
                return;
            }
            if (data && typeof data.cost !== 'undefined') {
                state.lastExplain = { cost: Number(data.cost), cached: !!data.cached };
            } else {
                state.lastExplain = null;
            }
            _updateCostBadge();
        }).catch(function (err) {
            state.explainAbort = null;
            if (err && err.name === 'AbortError') return;
            state.lastExplain = null;
            _updateCostBadge();
        });
    }

    function _updateCostBadge() {
        var root = state && state.rootEl;
        if (!root) return;
        var old = root.querySelector('.dsw-cost-badge');
        if (!old) return;
        var wrapper = document.createElement('div');
        wrapper.innerHTML = _renderCostBadge();
        var fresh = wrapper.firstElementChild;
        if (fresh) old.parentNode.replaceChild(fresh, old);
    }

    // ---- Undo / Redo ----
    function undo() {
        var hist = window.DbSmartAstHistory;
        if (!hist || !hist.canUndo || !hist.canUndo()) return;
        var prev = hist.undo();
        var prevAst = prev && (prev.ast || prev);  // accept either {ast,label} or ast
        if (!prevAst) return;
        var fromAst = _deepClone(state.ast);
        state.ast = _deepClone(prevAst);
        _render();
        _diffToast(fromAst, state.ast);
        _syncServerAst();
        _refreshExplain();
    }

    function redo() {
        var hist = window.DbSmartAstHistory;
        if (!hist || !hist.canRedo || !hist.canRedo()) return;
        var nxt = hist.redo();
        var nextAst = nxt && (nxt.ast || nxt);
        if (!nextAst) return;
        var fromAst = _deepClone(state.ast);
        state.ast = _deepClone(nextAst);
        _render();
        _diffToast(fromAst, state.ast);
        _syncServerAst();
        _refreshExplain();
    }

    function _syncServerAst() {
        // Tell server we replaced the AST wholesale (undo/redo).
        if (!state.sessionUid) return;
        var url = API_BASE + '/sessions/' + encodeURIComponent(state.sessionUid) + '/ast/patch';
        var body = {
            op: 'replace_ast',
            args: { ast: state.ast },
            render_preview: true,
            dialect: state.dialect,
        };
        state.fetchJson(url, { method: 'POST', body: JSON.stringify(body) })
            .then(function (data) {
                if (data && data.ast) state.ast = data.ast;
                if (state.onChange) {
                    try { state.onChange(state.ast, (data && data.sql) || null); } catch (e) { /* ignore */ }
                }
                _render();
            })
            .catch(function (err) {
                console.warn('[DbSmartAstEditor] replace_ast sync failed', err);
            });
    }

    function _diffToast(fromAst, toAst) {
        if (!state.sessionUid) return;
        var url = API_BASE + '/ast/diff';
        state.fetchJson(url, {
            method: 'POST',
            body: JSON.stringify({ from_ast: fromAst, to_ast: toAst }),
        }).then(function (data) {
            var summary = data && data.summary;
            if (!summary) return;
            var changed = summary.changed_sections || [];
            if (changed.length === 0) return;
            var trMap = {
                select: 'kolonlar', filters: 'filtreler', order_by: 'sıralama',
                group_by: 'gruplama', limit: 'limit', joins: 'birleştirmeler',
            };
            var parts = [];
            for (var i = 0; i < changed.length; i += 1) parts.push(trMap[changed[i]] || changed[i]);
            _toast('Değişti: ' + parts.join(', '), 'info');
        }).catch(function () { /* ignore */ });
    }

    // ---- Global key handler (Ctrl/Meta+Z = undo, Ctrl/Meta+Y / Shift+Z = redo) ----
    function _onGlobalKey(e) {
        if (!state) return;
        var tag = e.target && e.target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) return;
        var panel = document.getElementById('dbSmartWizardPanel');
        if (panel && !panel.contains(state.rootEl)) return;
        var mod = e.ctrlKey || e.metaKey;
        if (!mod) return;
        var k = e.key && e.key.toLowerCase();
        if (k === 'z' && !e.shiftKey) {
            e.preventDefault();
            undo();
        } else if ((k === 'y') || (k === 'z' && e.shiftKey)) {
            e.preventDefault();
            redo();
        }
    }

    // ---- Public ----
    function mount(rootEl, opts) {
        opts = opts || {};
        if (!rootEl) {
            console.warn('[DbSmartAstEditor] mount called without rootEl');
            return;
        }
        if (state) unmount();
        state = _initState(rootEl, opts);
        rootEl.setAttribute('role', 'region');
        rootEl.setAttribute('aria-label', 'AST düzenleyici');
        if (rootEl.hasAttribute('hidden')) rootEl.removeAttribute('hidden');
        state.globalKeyHandler = function (e) { _onGlobalKey(e); };
        document.addEventListener('keydown', state.globalKeyHandler);
        _render();
        _refreshExplain();
    }

    function unmount() {
        if (!state) return;
        if (state.debounceTimer) clearTimeout(state.debounceTimer);
        if (state.patchAbort) { try { state.patchAbort.abort(); } catch (e) { /* ignore */ } }
        if (state.explainAbort) { try { state.explainAbort.abort(); } catch (e) { /* ignore */ } }
        if (state.globalKeyHandler) {
            document.removeEventListener('keydown', state.globalKeyHandler);
        }
        if (state.rootEl) {
            state.rootEl.removeEventListener('click', _onRootClick);
            state.rootEl.innerHTML = '';
        }
        state = null;
    }

    function getAst() {
        return state ? _deepClone(state.ast) : null;
    }

    function getHistory() {
        return window.DbSmartAstHistory || null;
    }

    window.DbSmartAstEditor = {
        mount: mount,
        unmount: unmount,
        getAst: getAst,
        getHistory: getHistory,
    };
})();
