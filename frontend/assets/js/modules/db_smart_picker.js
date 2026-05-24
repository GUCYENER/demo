/**
 * VYRA — Akıllı Veri Keşfi · Tablo Seçici Alt-Modal (v3.34.0)
 * =============================================================
 * Wizard step 1'deki "Tablo Seç" butonundan açılır.
 *
 * Özellikler:
 *   - Sol panel: yetkili tabloları listeler (semantic Türkçe ad + schema.object_name)
 *   - Üstte Türkçe-uyumlu (büyük/küçük + İŞĞÜÖÇı normalize) arama
 *   - Çoklu seçim (checkbox); ilk seçilen "ana tablo" olarak işaretlenir
 *   - Sağ panel: ana tablonun FK ilişkili tablolarını checkbox ile listeler
 *   - "Seç ve Kapat" → onConfirm({ primary, joins }) callback
 *
 * Backend: yeni endpoint gerekmez — mevcut iki endpoint reuse:
 *   GET /api/db-smart/sources/{source_id}/tables?q=<q>&limit=200
 *     (backend cap: le=500, v3.34.0; picker 200 ile çağırır — çoğu kaynak için yeterli)
 *   GET /api/db-smart/sources/{source_id}/tables/{table_id}/related?depth=1
 */
(function () {
    'use strict';

    const API_BASE = '/api/db-smart';

    // ---- Türkçe normalizasyon (frontend arama için) ----
    const _TR_MAP = { 'İ': 'i', 'I': 'i', 'ı': 'i', 'Ş': 's', 'ş': 's',
                       'Ğ': 'g', 'ğ': 'g', 'Ü': 'u', 'ü': 'u',
                       'Ö': 'o', 'ö': 'o', 'Ç': 'c', 'ç': 'c' };
    function _normTR(s) {
        if (!s) return '';
        let out = '';
        const str = String(s);
        for (let i = 0; i < str.length; i++) {
            const ch = str.charAt(i);
            out += (_TR_MAP[ch] || ch);
        }
        return out.toLowerCase();
    }

    function _escape(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _authHeaders() {
        const token = localStorage.getItem('access_token') || '';
        return { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' };
    }

    async function _fetchJson(url) {
        const res = await fetch(url, { headers: _authHeaders() });
        if (!res.ok) {
            const txt = await res.text().catch(() => '');
            throw new Error(res.status + ': ' + (txt || res.statusText));
        }
        return res.json();
    }

    // ---- State ----
    const _state = {
        open: false,
        sourceId: null,
        tables: [],         // [{ table_id, schema, name, label, _nl, _nn, _nf }] — _nX = pre-normalized TR strings
        filtered: [],
        primaryId: null,    // ilk seçilen ana tablo
        joins: new Map(),   // table_id -> { table_id, schema, name, label }
        fkById: new Map(),  // table_id -> { table_id, schema, name, label, is_junction }
        fkLoadedFor: null,  // cache: skip _loadFk if same primary
        fkLoading: false,
        prevFocus: null,
        onConfirm: null,
        onCancel: null,
        initialQuery: '',
    };

    // ---- Selectors ----
    function $(id) { return document.getElementById(id); }

    function _show(el) { if (el) { el.hidden = false; el.classList.remove('hidden'); } }
    function _hide(el) { if (el) { el.hidden = true; el.classList.add('hidden'); } }

    // ---- Rendering ----
    function _renderList() {
        const list = $('dswPickerList');
        const count = $('dswPickerCount');
        if (!list) return;
        const items = _state.filtered;
        count && (count.textContent = items.length + ' tablo');
        if (!items.length) {
            list.innerHTML = '<div class="dsw-picker-empty">Eşleşen tablo yok.</div>';
            return;
        }
        const html = items.map(t => {
            const checked = (t.table_id === _state.primaryId || _state.joins.has(t.table_id));
            const isPrimary = (t.table_id === _state.primaryId);
            const semantic = t.label || t.name || '?';
            const tech = (t.schema ? t.schema + '.' : '') + (t.name || '');
            return '<label class="dsw-picker-row' + (isPrimary ? ' is-primary' : '') + (checked ? ' is-checked' : '') + '"' +
                   ' data-table-id="' + _escape(t.table_id) + '">' +
                     '<input type="checkbox" class="dsw-picker-cb" data-table-id="' + _escape(t.table_id) + '"' +
                       (checked ? ' checked' : '') + ' aria-label="' + _escape(semantic) + ' seç" />' +
                     '<span class="dsw-picker-row-main">' +
                       '<span class="dsw-picker-row-title">' + _escape(semantic) +
                         (isPrimary ? ' <em class="dsw-picker-badge">ANA</em>' : '') +
                       '</span>' +
                       '<span class="dsw-picker-row-meta">' + _escape(tech) + '</span>' +
                     '</span>' +
                   '</label>';
        }).join('');
        list.innerHTML = html;
    }

    function _renderFkPane() {
        const pane = $('dswPickerFkList');
        const hint = $('dswPickerFkHint');
        if (!pane) return;
        if (_state.primaryId == null) {
            hint && (hint.textContent = 'Önce sol panelden bir tablo seçin.');
            pane.innerHTML = '';
            return;
        }
        if (_state.fkLoading) {
            hint && (hint.textContent = 'FK ilişkiler yükleniyor…');
            pane.innerHTML = '<div class="dsw-picker-empty">Yükleniyor…</div>';
            return;
        }
        if (!_state.fkById.size) {
            hint && (hint.textContent = 'Bu tablo için FK ilişkisi bulunamadı.');
            pane.innerHTML = '<div class="dsw-picker-empty">FK ilişkisi yok.</div>';
            return;
        }
        hint && (hint.textContent = _state.fkById.size + ' ilişkili tablo');
        const parts = [];
        _state.fkById.forEach((n, tid) => {
            const checked = _state.joins.has(tid);
            const junc = n.is_junction ? ' · <em>junction</em>' : '';
            const tech = (n.schema ? n.schema + '.' : '') + n.name;
            parts.push(
                '<label class="dsw-picker-fk-row' + (checked ? ' is-checked' : '') + '" data-fk-id="' + _escape(tid) + '">' +
                  '<input type="checkbox" class="dsw-picker-fk-cb" data-fk-id="' + _escape(tid) + '"' +
                    (checked ? ' checked' : '') + ' aria-label="' + _escape(n.label) + ' join adayı" />' +
                  '<span class="dsw-picker-row-main">' +
                    '<span class="dsw-picker-row-title">' + _escape(n.label) + '</span>' +
                    '<span class="dsw-picker-row-meta">' + _escape(tech) + junc + '</span>' +
                  '</span>' +
                '</label>'
            );
        });
        pane.innerHTML = parts.join('');
    }

    function _renderSummary() {
        const sum = $('dswPickerSummary');
        const confirm = $('dswPickerConfirm');
        const primaryCount = _state.primaryId != null ? 1 : 0;
        const joinCount = _state.joins.size;
        const total = primaryCount + joinCount;
        if (sum) {
            if (!total) sum.textContent = 'Seçim yok';
            else if (primaryCount && joinCount) sum.textContent = '1 ana + ' + joinCount + ' join adayı';
            else if (primaryCount) sum.textContent = '1 ana tablo seçildi';
            else sum.textContent = joinCount + ' tablo';
        }
        if (confirm) confirm.disabled = (primaryCount === 0);
    }

    // ---- Data ----
    async function _loadTables() {
        const list = $('dswPickerList');
        if (list) list.setAttribute('aria-busy', 'true');
        try {
            const q = _state.initialQuery || '';
            const url = API_BASE + '/sources/' + _state.sourceId + '/tables?q=' +
                        encodeURIComponent(q) + '&limit=200';
            const data = await _fetchJson(url);
            // Pre-normalize label/name/full at load → filter loop becomes O(N) indexOf
            // on cached strings instead of O(N × 3 × normTR) per keystroke.
            const items = (data.tables || data.items || []).map(t => {
                const schema = t.schema_name || t.schema || null;
                const name = t.object_name || t.table_name || '';
                const label = t.business_name_tr || name || '?';
                const full = (schema ? schema + '.' : '') + name;
                return {
                    table_id: t.table_id || t.id,
                    schema: schema,
                    name: name,
                    label: label,
                    _nl: _normTR(label),
                    _nn: _normTR(name),
                    _nf: _normTR(full),
                };
            });
            _state.tables = items;
            _applyFilter('');
        } catch (e) {
            console.warn('[DbSmartPicker] table load failed:', e);
            if (list) list.innerHTML = '<div class="dsw-picker-empty">Tablolar yüklenemedi: ' + _escape(e.message) + '</div>';
        } finally {
            if (list) list.setAttribute('aria-busy', 'false');
        }
    }

    async function _loadFk(primaryId) {
        // Cache: same primary, already loaded → no refetch
        if (_state.fkLoadedFor === primaryId && !_state.fkLoading) {
            _renderFkPane();
            return;
        }
        _state.fkLoadedFor = primaryId;
        _state.fkLoading = true;
        _state.fkById = new Map();
        _renderFkPane();
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/' + primaryId + '/related?depth=1';
            const data = await _fetchJson(url);
            const neighbors = (data.neighbors || []).concat(data.junctions || []);
            const map = new Map();
            neighbors.forEach(n => {
                const tid = n.table_id != null ? n.table_id
                          : (n.id != null ? n.id : (n.schema + '.' + n.table));
                map.set(tid, {
                    table_id: tid,
                    schema: n.schema,
                    name: n.table,
                    label: n.business_name_tr || n.table,
                    is_junction: !!n.is_junction,
                });
            });
            if (_state.primaryId === primaryId) _state.fkById = map;
        } catch (e) {
            console.warn('[DbSmartPicker] FK load failed:', e);
            if (_state.primaryId === primaryId) _state.fkById = new Map();
        } finally {
            _state.fkLoading = false;
            if (_state.primaryId === primaryId) _renderFkPane();
        }
    }

    function _applyFilter(rawQ) {
        const q = _normTR(rawQ || '');
        if (!q) {
            _state.filtered = _state.tables.slice();
        } else {
            _state.filtered = _state.tables.filter(t =>
                t._nl.indexOf(q) >= 0 || t._nn.indexOf(q) >= 0 || t._nf.indexOf(q) >= 0
            );
        }
        _renderList();
    }

    // ---- Event handlers ----
    function _coerceId(raw) {
        const n = parseInt(raw, 10);
        return isNaN(n) ? raw : n;
    }

    // Update is-primary / is-checked classes on visible list rows without
    // full innerHTML rebuild (avoids reflow on every checkbox click).
    function _refreshListRowClasses() {
        const list = $('dswPickerList');
        if (!list) return;
        list.querySelectorAll('.dsw-picker-row').forEach(row => {
            const tid = _coerceId(row.getAttribute('data-table-id'));
            const isPrimary = (tid === _state.primaryId);
            const isChecked = isPrimary || _state.joins.has(tid);
            row.classList.toggle('is-primary', isPrimary);
            row.classList.toggle('is-checked', isChecked);
            const titleEl = row.querySelector('.dsw-picker-row-title');
            const hasBadge = titleEl && titleEl.querySelector('.dsw-picker-badge');
            if (isPrimary && !hasBadge && titleEl) {
                const em = document.createElement('em');
                em.className = 'dsw-picker-badge';
                em.textContent = 'ANA';
                titleEl.appendChild(document.createTextNode(' '));
                titleEl.appendChild(em);
            } else if (!isPrimary && hasBadge) {
                hasBadge.remove();
            }
            // Sync checkbox state (e.g. when primary uncheck demotes another row)
            const cb = row.querySelector('.dsw-picker-cb');
            if (cb && cb.checked !== isChecked) cb.checked = isChecked;
        });
    }

    function _onListClick(e) {
        const cb = e.target.closest('.dsw-picker-cb');
        if (!cb) return;
        const numId = _coerceId(cb.getAttribute('data-table-id'));
        const item = _state.tables.find(t => String(t.table_id) === String(numId));
        if (!item) return;

        const wasPrimary = (_state.primaryId === numId);
        const wasJoin = _state.joins.has(numId);
        let primaryChanged = false;

        if (cb.checked) {
            if (_state.primaryId == null) {
                _state.primaryId = numId;
                primaryChanged = true;
            } else if (!wasPrimary) {
                _state.joins.set(numId, item);
            }
        } else {
            if (wasPrimary) {
                _state.primaryId = null;
                _state.fkById = new Map();
                _state.fkLoadedFor = null;
                if (_state.joins.size > 0) {
                    const firstId = _state.joins.keys().next().value;
                    _state.joins.delete(firstId);
                    _state.primaryId = firstId;
                }
                primaryChanged = true;
            } else if (wasJoin) {
                _state.joins.delete(numId);
            }
        }
        _refreshListRowClasses();
        if (primaryChanged) {
            if (_state.primaryId != null) _loadFk(_state.primaryId);
            else _renderFkPane();
        }
        _renderSummary();
    }

    function _onFkClick(e) {
        const cb = e.target.closest('.dsw-picker-fk-cb');
        if (!cb) return;
        const numId = _coerceId(cb.getAttribute('data-fk-id'));
        const meta = _state.fkById.get(numId);
        if (!meta) return;
        if (cb.checked) {
            _state.joins.set(numId, meta);
        } else {
            _state.joins.delete(numId);
        }
        // Only the affected row's class toggle is needed
        const row = cb.closest('.dsw-picker-fk-row');
        if (row) row.classList.toggle('is-checked', cb.checked);
        _renderSummary();
    }

    function _onSearchInput(e) {
        _applyFilter(e.target.value || '');
    }

    function _onClick(e) {
        const action = e.target.closest('[data-action]');
        if (!action) return;
        const a = action.getAttribute('data-action');
        if (a === 'cancel') {
            close(true);
        } else if (a === 'confirm') {
            _confirm();
        }
    }

    function _onKeydown(e) {
        if (!_state.open) return;
        if (e.key === 'Escape') {
            e.stopPropagation();
            close(true);
        }
    }

    function _confirm() {
        if (_state.primaryId == null) return;
        const primary = _state.tables.find(t => t.table_id === _state.primaryId) || null;
        const joins = Array.from(_state.joins.values());
        const cb = _state.onConfirm;
        close(false);
        if (typeof cb === 'function') {
            try { cb({ primary: primary, joins: joins }); } catch (err) { console.error('[DbSmartPicker] onConfirm error:', err); }
        }
    }

    // ---- Public open / close ----
    function open(opts) {
        opts = opts || {};
        if (_state.open) return;
        const modal = $('dbSmartPickerModal');
        if (!modal) {
            console.warn('[DbSmartPicker] modal DOM bulunamadı');
            return;
        }
        _state.sourceId = opts.sourceId;
        _state.initialQuery = opts.initialQuery || '';
        _state.onConfirm = typeof opts.onConfirm === 'function' ? opts.onConfirm : null;
        _state.onCancel = typeof opts.onCancel === 'function' ? opts.onCancel : null;
        _state.primaryId = null;
        _state.joins = new Map();
        _state.fkById = new Map();
        _state.fkLoadedFor = null;
        _state.tables = [];
        _state.filtered = [];
        _state.prevFocus = document.activeElement;

        // DOM-scoped listeners are idempotent (attached once to persistent nodes).
        // Document-scoped keydown is attached per-open and removed on close to
        // avoid accumulation and to keep the global keyboard surface minimal.
        if (!modal._bound) {
            modal.addEventListener('click', _onClick);
            const search = $('dswPickerSearch');
            search && search.addEventListener('input', _onSearchInput);
            const list = $('dswPickerList');
            list && list.addEventListener('change', _onListClick);
            const fkList = $('dswPickerFkList');
            fkList && fkList.addEventListener('change', _onFkClick);
            const overlay = modal.querySelector('[data-role="overlay"]');
            overlay && overlay.addEventListener('click', function () { close(true); });
            modal._bound = true;
        }
        document.addEventListener('keydown', _onKeydown);

        // Pre-populate search input
        const search = $('dswPickerSearch');
        if (search) search.value = _state.initialQuery;

        _show(modal);
        document.body.classList.add('dsw-picker-open');
        _state.open = true;

        _renderList();
        _renderFkPane();
        _renderSummary();

        // Focus search
        setTimeout(function () { try { search && search.focus(); } catch (e) {} }, 30);

        // Load tables
        _loadTables();
    }

    function close(viaCancel) {
        if (!_state.open) return;
        const modal = $('dbSmartPickerModal');
        _hide(modal);
        document.body.classList.remove('dsw-picker-open');
        _state.open = false;
        document.removeEventListener('keydown', _onKeydown);
        const cb = _state.onCancel;
        try { _state.prevFocus && _state.prevFocus.focus(); } catch (e) {}
        if (viaCancel && typeof cb === 'function') {
            try { cb(); } catch (e) {}
        }
    }

    window.DbSmartPicker = { open: open, close: function () { close(true); } };
})();
