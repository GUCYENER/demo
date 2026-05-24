/**
 * VYRA — Akıllı Veri Keşfi · Tablo Seçici Alt-Modal (v3.34.5)
 *
 * v3.34.5: `open(opts)` now accepts `initialSelection: { primaryId, joinIds[] }`
 * to restore previous selection state when reopened via "Seçimi düzenle".
 * =============================================================
 * Wizard step 1'deki "Tablo Seç" butonundan açılır.
 *
 * Özellikler:
 *   - Sol panel: yetkili tabloları **schema-bazlı akordeon** olarak listeler
 *     (semantic Türkçe ad + schema.object_name)
 *   - Üstte Türkçe-uyumlu (büyük/küçük + İŞĞÜÖÇı normalize) arama
 *     + arama temizleme (×) ikonu
 *   - "Sadece Seçilenler" toggle filtresi (arama ile AND)
 *   - Çoklu seçim (checkbox); ilk seçilen "ana tablo" olarak işaretlenir
 *   - Sağ panel: ana tablonun FK ilişkili tablolarını checkbox ile listeler
 *   - "Tümünü Temizle" tüm seçimleri ve FK önbelleğini sıfırlar
 *   - FK Guard: ilişkisiz ikinci tablo seçimi toast + auto-uncheck
 *   - "Seç ve Kapat" → onConfirm({ primary, joins }) callback (şema değişmedi)
 *
 * Backend: yeni endpoint gerekmez — mevcut iki endpoint reuse:
 *   GET /api/db-smart/sources/{source_id}/tables?q=<q>&limit=200
 *     (backend cap: le=500, v3.34.0; picker 200 ile çağırır — çoğu kaynak için yeterli)
 *   GET /api/db-smart/sources/{source_id}/tables/{table_id}/related?depth=1
 */
(function () {
    'use strict';

    // v3.34.0: vyraFetch /api prefix'i kendi ekliyor — burada sadece path tutuyoruz.
    const API_BASE = '/db-smart';

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

    // v3.34.0: vyraFetch delegate — Auth + JSON + friendly error helper'da.
    // FIX6 (ATHENA+HEBE+NIKE): opts forward edilir (signal için).
    async function _fetchJson(url, opts) {
        return window.vyraFetch(url, opts);
    }

    // Toast wrapper — window.showToast global (toast.js); fallback alert.
    function _toast(msg, kind) {
        try {
            if (typeof window.showToast === 'function') {
                window.showToast(msg, kind || 'warning');
                return;
            }
        } catch (e) {}
        try { console.warn('[DbSmartPicker][toast:' + (kind || 'warning') + ']', msg); } catch (e) {}
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
        fkAbortController: null,  // FIX6: in-flight FK fetch cancellation
        prevFocus: null,
        onConfirm: null,
        onCancel: null,
        initialQuery: '',
        // AGENT-B v3.34.x:
        onlySelected: false,       // "Sadece Seçilenler" toggle
        currentQuery: '',          // ham arama metni (clear ikon görünürlüğü için)
        accordionOpen: new Set(),  // schema adları (açık olanlar)
        accordionInit: false,      // ilk schema default-open uygulandı mı
        // F13 (ATHENA+POSEIDON v3.36): multi-hop FK adjacency
        adjacency: new Map(),           // Map<table_id, Set<table_id>>  (bilateral)
        fkLoadedSet: new Set(),         // table_ids whose neighbors are fully hydrated
        fkLoadingPromises: new Map(),   // Map<table_id, Promise>  (in-flight dedupe)
    };

    // ---- Selectors ----
    function $(id) { return document.getElementById(id); }

    function _show(el) { if (el) { el.hidden = false; el.classList.remove('hidden'); } }
    function _hide(el) { if (el) { el.hidden = true; el.classList.add('hidden'); } }

    // ---- AGENT-B: ekstra kontrolleri DOM'a enjekte (idempotent) ----
    function _ensureExtraControls() {
        const modal = $('dbSmartPickerModal');
        if (!modal) return;

        // (d) Arama temizle (×) ikonu — search container içinde
        const searchWrap = modal.querySelector('.dsw-picker-search');
        const searchInput = $('dswPickerSearch');
        if (searchWrap && searchInput && !$('dswPickerSearchClear')) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.id = 'dswPickerSearchClear';
            btn.className = 'dsw-picker-search-clear hidden';
            btn.setAttribute('aria-label', 'Aramayı temizle');
            btn.title = 'Aramayı temizle';
            btn.hidden = true;
            btn.textContent = '×';
            // count span'in önüne koy → input × count layout
            const count = $('dswPickerCount');
            if (count && count.parentNode === searchWrap) {
                searchWrap.insertBefore(btn, count);
            } else {
                searchWrap.appendChild(btn);
            }
        }

        // (c) "Sadece Seçilenler" toggle — search container'ın hemen altına filter bar
        const leftPane = modal.querySelector('.dsw-picker-left');
        if (leftPane && !$('dswPickerFilterBar')) {
            const bar = document.createElement('div');
            bar.id = 'dswPickerFilterBar';
            bar.className = 'dsw-picker-filter-bar';
            bar.innerHTML =
                '<label class="dsw-picker-filter-only-selected" for="dswPickerOnlySelected">' +
                  '<input type="checkbox" id="dswPickerOnlySelected" />' +
                  '<span>Sadece Seçilenler</span>' +
                '</label>' +
                '<button type="button" id="dswPickerClearAll" class="dsw-picker-clear-all-btn"' +
                  ' aria-label="Tüm seçimleri temizle" title="Tüm seçimleri temizle" disabled>' +
                  'Tümünü Temizle' +
                '</button>';
            // search wrap'ten sonra ekle
            if (searchWrap && searchWrap.parentNode === leftPane) {
                leftPane.insertBefore(bar, searchWrap.nextSibling);
            } else {
                leftPane.insertBefore(bar, leftPane.firstChild);
            }
        }
    }

    // ---- AGENT-B: schema grouping ----
    function _groupBySchema(items) {
        // Map ekleme sırasını korur → liste sırası deterministik
        const groups = new Map();
        for (let i = 0; i < items.length; i++) {
            const t = items[i];
            const sch = t.schema || '(default)';
            if (!groups.has(sch)) groups.set(sch, []);
            groups.get(sch).push(t);
        }
        return groups;
    }

    // ---- Rendering ----
    function _renderList() {
        const list = $('dswPickerList');
        const count = $('dswPickerCount');
        if (!list) return;

        // (c) Sadece Seçilenler filtresi (arama filtresi üstüne AND)
        let items = _state.filtered;
        if (_state.onlySelected) {
            items = items.filter(t =>
                t.table_id === _state.primaryId || _state.joins.has(t.table_id)
            );
        }

        count && (count.textContent = items.length + ' tablo');

        if (!items.length) {
            const msg = _state.onlySelected
                ? 'Seçili tablo yok.'
                : (_state.currentQuery ? 'Eşleşen tablo yok.' : 'Listelenecek tablo yok.');
            list.innerHTML = '<div class="dsw-picker-empty">' + _escape(msg) + '</div>';
            return;
        }

        // (a) Schema-bazlı akordeon
        const groups = _groupBySchema(items);
        const schemaNames = Array.from(groups.keys());

        // İlk yüklemede ilk schema default-open
        if (!_state.accordionInit && schemaNames.length > 0) {
            _state.accordionOpen.add(schemaNames[0]);
            _state.accordionInit = true;
        }
        // Arama aktifken: sonuç içeren schema'ları otomatik aç (kullanıcı keşfini kolaylaştırır)
        if (_state.currentQuery) {
            schemaNames.forEach(s => _state.accordionOpen.add(s));
        }
        // Tek schema varsa zorla açık
        if (schemaNames.length === 1) {
            _state.accordionOpen.add(schemaNames[0]);
        }

        const parts = [];
        for (let i = 0; i < schemaNames.length; i++) {
            const sch = schemaNames[i];
            const rows = groups.get(sch);
            const isOpen = _state.accordionOpen.has(sch);
            const panelId = 'dswPickerAcc_' + i;
            const headerId = 'dswPickerAccHdr_' + i;

            parts.push(
                '<div class="dsw-picker-accordion' + (isOpen ? ' is-open' : '') +
                  '" data-schema="' + _escape(sch) + '">' +
                  '<button type="button" class="dsw-picker-accordion-header"' +
                    ' id="' + headerId + '"' +
                    ' aria-expanded="' + (isOpen ? 'true' : 'false') + '"' +
                    ' aria-controls="' + panelId + '"' +
                    ' data-schema="' + _escape(sch) + '">' +
                    '<span class="dsw-picker-accordion-caret" aria-hidden="true">▸</span>' +
                    '<span class="dsw-picker-accordion-title">' + _escape(sch) + '</span>' +
                    '<span class="dsw-picker-accordion-count">(' + rows.length + ')</span>' +
                  '</button>' +
                  '<div class="dsw-picker-accordion-body" id="' + panelId + '"' +
                    ' role="region" aria-labelledby="' + headerId + '"' +
                    (isOpen ? '' : ' hidden') + '>'
            );

            for (let j = 0; j < rows.length; j++) {
                const t = rows[j];
                const checked = (t.table_id === _state.primaryId || _state.joins.has(t.table_id));
                const isPrimary = (t.table_id === _state.primaryId);
                const semantic = t.label || t.name || '?';
                const tech = (t.schema ? t.schema + '.' : '') + (t.name || '');
                parts.push(
                    '<label class="dsw-picker-row' + (isPrimary ? ' is-primary' : '') + (checked ? ' is-checked' : '') + '"' +
                       ' data-table-id="' + _escape(t.table_id) + '">' +
                         '<input type="checkbox" class="dsw-picker-cb" data-table-id="' + _escape(t.table_id) + '"' +
                           (checked ? ' checked' : '') + ' aria-label="' + _escape(semantic) + ' seç" />' +
                         '<span class="dsw-picker-row-main">' +
                           '<span class="dsw-picker-row-title">' + _escape(semantic) +
                             (isPrimary ? ' <em class="dsw-picker-badge">ANA</em>' : '') +
                           '</span>' +
                           '<span class="dsw-picker-row-meta">' + _escape(tech) + '</span>' +
                         '</span>' +
                       '</label>'
                );
            }

            parts.push('</div></div>');
        }
        list.innerHTML = parts.join('');
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
            // (f) FK ilişki guard placeholder
            hint && (hint.textContent = 'FK ilişkisi yok.');
            pane.innerHTML = '<div class="dsw-picker-empty dsw-picker-warning">' +
                'Bu tablo için FK ilişkili tablo bulunamadı.</div>';
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
        const clearAll = $('dswPickerClearAll');
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
        // (b) Tümünü Temizle butonu: seçim yokken disabled
        if (clearAll) clearAll.disabled = (total === 0);
    }

    function _renderSearchClear() {
        // (d) Arama temizle ikonu: yalnız input doluyken görünür
        const btn = $('dswPickerSearchClear');
        if (!btn) return;
        const has = !!(_state.currentQuery && _state.currentQuery.length);
        btn.hidden = !has;
        btn.classList.toggle('hidden', !has);
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
            // v3.34.5: initialSelection ile gelen primaryId varsa FK'yi de tetikle.
            if (_state.primaryId != null && _state.fkLoadedFor !== _state.primaryId) {
                try { _loadFk(_state.primaryId); } catch (e) { /* ignore */ }
            }
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
        // FIX6 (ATHENA+HEBE+NIKE): cancel any in-flight FK request before starting a new one
        if (_state.fkAbortController) {
            try { _state.fkAbortController.abort(); } catch (e) {}
        }
        const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        _state.fkAbortController = ctrl;
        _state.fkLoadedFor = primaryId;
        _state.fkLoading = true;
        _state.fkById = new Map();
        _renderFkPane();
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/' + primaryId + '/related?depth=1';
            const data = await _fetchJson(url, ctrl ? { signal: ctrl.signal } : undefined);
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
            // F13: seed multi-hop adjacency from same /related call
            map.forEach((meta, tid) => { _addAdjacency(primaryId, tid); });
            _state.fkLoadedSet.add(primaryId);
        } catch (e) {
            // FIX6: AbortError → silent (caller intent), other errors → warn
            if (e && (e.name === 'AbortError' || e.code === 20)) {
                return;  // newer _loadFk will render
            }
            console.warn('[DbSmartPicker] FK load failed:', e);
            if (_state.primaryId === primaryId) _state.fkById = new Map();
        } finally {
            // FIX6: only clear if this controller is still the active one
            if (_state.fkAbortController === ctrl) {
                _state.fkAbortController = null;
                _state.fkLoading = false;
                if (_state.primaryId === primaryId) _renderFkPane();
            }
        }
    }

    // ---- F13 (ATHENA+POSEIDON v3.36): Multi-hop FK helpers ----
    function _addAdjacency(a, b) {
        if (a == null || b == null) return;
        if (!_state.adjacency.has(a)) _state.adjacency.set(a, new Set());
        _state.adjacency.get(a).add(b);
        if (!_state.adjacency.has(b)) _state.adjacency.set(b, new Set());
        _state.adjacency.get(b).add(a);
    }

    // Lazy bilateral FK hydrate (no UI render). Returns promise; deduped per tableId.
    function _loadFkFor(tableId) {
        if (tableId == null) return Promise.resolve();
        if (_state.fkLoadedSet.has(tableId)) return Promise.resolve();
        if (_state.fkLoadingPromises.has(tableId)) return _state.fkLoadingPromises.get(tableId);
        const url = API_BASE + '/sources/' + _state.sourceId +
                    '/tables/' + tableId + '/related?depth=1';
        const p = _fetchJson(url).then(data => {
            const neighbors = (data.neighbors || []).concat(data.junctions || []);
            neighbors.forEach(n => {
                const tid = n.table_id != null ? n.table_id
                          : (n.id != null ? n.id : (n.schema + '.' + n.table));
                _addAdjacency(tableId, tid);
            });
            _state.fkLoadedSet.add(tableId);
        }).catch(e => {
            // Mark loaded with empty neighbors to prevent retry storm; warn only.
            console.warn('[DbSmartPicker] _loadFkFor failed for', tableId, e);
            _state.fkLoadedSet.add(tableId);
        }).then(() => {
            _state.fkLoadingPromises.delete(tableId);
        });
        _state.fkLoadingPromises.set(tableId, p);
        return p;
    }

    // Sync BFS check. Returns true/false if all required hydrated, null if needs async load.
    function _checkMultiHopFkSync(candidateId) {
        if (candidateId == null) return false;
        const need = [];
        if (_state.primaryId != null) need.push(_state.primaryId);
        _state.joins.forEach((_v, k) => need.push(k));
        need.push(candidateId);
        for (let i = 0; i < need.length; i++) {
            if (!_state.fkLoadedSet.has(need[i])) return null;
        }
        const selected = new Set();
        if (_state.primaryId != null && _state.primaryId !== candidateId) selected.add(_state.primaryId);
        _state.joins.forEach((_v, k) => { if (k !== candidateId) selected.add(k); });
        if (selected.size === 0) return true; // only primary case shouldn't reach here, but be safe
        // BFS from candidate
        const visited = new Set([candidateId]);
        const queue = [candidateId];
        while (queue.length > 0) {
            const cur = queue.shift();
            const nb = _state.adjacency.get(cur);
            if (!nb) continue;
            const it = nb.values();
            let r = it.next();
            while (!r.done) {
                const n = r.value;
                if (selected.has(n)) return true;
                if (!visited.has(n)) {
                    visited.add(n);
                    queue.push(n);
                }
                r = it.next();
            }
        }
        return false;
    }

    // Hydrate adjacency for primary + all joins + candidate, then re-evaluate; auto-check if allowed.
    async function _ensureMultiHopAdjacency(candidateId, itemMeta) {
        const ids = new Set();
        if (_state.primaryId != null) ids.add(_state.primaryId);
        _state.joins.forEach((_v, k) => ids.add(k));
        if (candidateId != null) ids.add(candidateId);
        const tasks = [];
        ids.forEach(t => tasks.push(_loadFkFor(t)));
        try { await Promise.all(tasks); } catch (e) { /* individual catches handle */ }
        if (_state.primaryId == null) return;          // user cleared mid-flight
        if (_state.joins.has(candidateId)) return;     // already accepted somewhere
        if (_state.primaryId === candidateId) return;  // primary changed to this
        const verdict = _checkMultiHopFkSync(candidateId);
        if (verdict !== true) return;
        const item = itemMeta || _state.tables.find(t => String(t.table_id) === String(candidateId));
        if (!item) return;
        _state.joins.set(candidateId, item);
        const cb = document.querySelector('.dsw-picker-cb[data-table-id="' + String(candidateId) + '"]');
        if (cb) cb.checked = true;
        _refreshListRowClasses();
        _renderSummary();
        _toast('FK ilişkisi doğrulandı — tablo seçime eklendi.', 'success');
    }

    function _applyFilter(rawQ) {
        _state.currentQuery = String(rawQ || '');
        const q = _normTR(_state.currentQuery);
        if (!q) {
            _state.filtered = _state.tables.slice();
        } else {
            _state.filtered = _state.tables.filter(t =>
                t._nl.indexOf(q) >= 0 || t._nn.indexOf(q) >= 0 || t._nf.indexOf(q) >= 0
            );
        }
        _renderList();
        _renderSearchClear();
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
                // F13 (ATHENA+POSEIDON v3.36): Multi-hop FK guard.
                // Adayın seçili tablolardan biriyle DOĞRUDAN veya DOLAYLI (FK zinciri)
                // ilişkisi varsa kabul. Tek-hop primary kontrolü yerine BFS reachability.
                const verdict = _checkMultiHopFkSync(numId);
                if (verdict === true) {
                    _state.joins.set(numId, item);
                } else if (verdict === false) {
                    cb.checked = false;
                    const row = cb.closest('.dsw-picker-row');
                    if (row) row.classList.remove('is-checked');
                    _toast('Bu tablo seçili tablolarla doğrudan veya dolaylı FK ilişkisi içermiyor.', 'warning');
                    _renderSummary();
                    return;
                } else {
                    // verdict === null → adjacency eksik; async hydrate + auto re-check
                    cb.checked = false;
                    const row = cb.closest('.dsw-picker-row');
                    if (row) row.classList.remove('is-checked');
                    _toast('FK ilişkileri kontrol ediliyor — uygunsa otomatik eklenecek...', 'info');
                    _ensureMultiHopAdjacency(numId, item).catch(() => {});
                    _renderSummary();
                    return;
                }
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

        // onlySelected aktifken seçimi kaldırmak listeyi mutate eder → full re-render
        if (_state.onlySelected) {
            _renderList();
        } else {
            _refreshListRowClasses();
        }

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
        // FK row → sol panelde aynı tablo varsa class senkronu
        _refreshListRowClasses();
        _renderSummary();
    }

    function _onSearchInput(e) {
        _applyFilter(e.target.value || '');
    }

    // (d) Arama temizle (×) — buton click veya Escape iken focus input'ta
    function _clearSearch() {
        const input = $('dswPickerSearch');
        if (input) {
            input.value = '';
            try { input.focus(); } catch (e) {}
        }
        _applyFilter('');
    }

    // (b) Tümünü Temizle
    function _clearAllSelections() {
        // FK in-flight abort
        if (_state.fkAbortController) {
            try { _state.fkAbortController.abort(); } catch (e) {}
            _state.fkAbortController = null;
        }
        _state.primaryId = null;
        _state.joins.clear();
        _state.fkById.clear();
        _state.fkLoadedFor = null;
        _state.fkLoading = false;
        // F13: clear multi-hop adjacency caches
        _state.adjacency = new Map();
        _state.fkLoadedSet = new Set();
        _state.fkLoadingPromises = new Map();
        // onlySelected'ı sıfırlamayalım — kullanıcı kasıtlı açtıysa kalsın;
        // fakat liste tamamen boş kalmasın diye otomatik kapat.
        if (_state.onlySelected) {
            _state.onlySelected = false;
            const ck = $('dswPickerOnlySelected');
            if (ck) ck.checked = false;
        }
        _renderList();
        _renderFkPane();
        _renderSummary();
    }

    // (c) Sadece Seçilenler toggle
    function _onOnlySelectedToggle(e) {
        _state.onlySelected = !!e.target.checked;
        _renderList();
    }

    // (a) Akordeon header click / keyboard
    function _toggleAccordion(schema) {
        if (_state.accordionOpen.has(schema)) {
            _state.accordionOpen.delete(schema);
        } else {
            _state.accordionOpen.add(schema);
        }
        _renderList();
    }

    function _onListMouseClick(e) {
        const hdr = e.target.closest('.dsw-picker-accordion-header');
        if (!hdr) return;
        e.preventDefault();
        const sch = hdr.getAttribute('data-schema');
        if (sch != null) _toggleAccordion(sch);
    }

    function _onListKeydown(e) {
        const hdr = e.target.closest('.dsw-picker-accordion-header');
        if (!hdr) return;
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
            e.preventDefault();
            const sch = hdr.getAttribute('data-schema');
            if (sch != null) _toggleAccordion(sch);
        }
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
        // F22d (POSEIDON 2026-05-25): initialSelection ile gelen join id'leri
        // `_state.joins.set(id, true)` flag yazıyor (table objesi yok). Normal
        // toggle flow ise tablo objesi yazıyor. Confirm anında her iki shape'i
        // de objeye normalize et — yoksa onConfirm tüketicisi `j.table_id`
        // okuyamaz, wizard `selectedTables` bozulur.
        const joins = Array.from(_state.joins.entries()).map(function (entry) {
            const id = entry[0];
            const v = entry[1];
            if (v && typeof v === 'object' && v.table_id != null) return v;
            const found = _state.tables.find(t => t.table_id === id);
            return found || { table_id: id, name: null, schema: null, label: null };
        });
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
        // F13: reset multi-hop adjacency caches
        _state.adjacency = new Map();
        _state.fkLoadedSet = new Set();
        _state.fkLoadingPromises = new Map();
        _state.prevFocus = document.activeElement;

        // v3.34.5 (POSEIDON+HERMES): "Seçimi düzenle" → wizard'dan gelen önceki seçimi
        // state'e geri yükle. _state.joins Map<tableId,bool>; primaryId number.
        if (opts.initialSelection && typeof opts.initialSelection === 'object') {
            const init = opts.initialSelection;
            if (init.primaryId != null) {
                _state.primaryId = parseInt(init.primaryId, 10);
            }
            if (Array.isArray(init.joinIds)) {
                init.joinIds.forEach(function (jid) {
                    const id = parseInt(jid, 10);
                    if (!isNaN(id)) _state.joins.set(id, true);
                });
            }
        }
        // AGENT-B reset
        _state.onlySelected = false;
        _state.currentQuery = _state.initialQuery;
        _state.accordionOpen = new Set();
        _state.accordionInit = false;

        // Ekstra kontrolleri DOM'a enjekte (idempotent; ilk açılışta bir kez)
        _ensureExtraControls();

        // "Sadece Seçilenler" checkbox state'ini reset et
        const onlyCk = $('dswPickerOnlySelected');
        if (onlyCk) onlyCk.checked = false;

        // DOM-scoped listeners are idempotent (attached once to persistent nodes).
        // Document-scoped keydown is attached per-open and removed on close to
        // avoid accumulation and to keep the global keyboard surface minimal.
        if (!modal._bound) {
            modal.addEventListener('click', _onClick);
            const search = $('dswPickerSearch');
            search && search.addEventListener('input', _onSearchInput);
            const list = $('dswPickerList');
            if (list) {
                list.addEventListener('change', _onListClick);
                list.addEventListener('click', _onListMouseClick);   // akordeon header
                list.addEventListener('keydown', _onListKeydown);    // klavye nav
            }
            const fkList = $('dswPickerFkList');
            fkList && fkList.addEventListener('change', _onFkClick);
            const overlay = modal.querySelector('[data-role="overlay"]');
            overlay && overlay.addEventListener('click', function () { close(true); });
            // AGENT-B: yeni kontroller
            const clearBtn = $('dswPickerSearchClear');
            clearBtn && clearBtn.addEventListener('click', _clearSearch);
            const onlyCkEl = $('dswPickerOnlySelected');
            onlyCkEl && onlyCkEl.addEventListener('change', _onOnlySelectedToggle);
            const clearAllBtn = $('dswPickerClearAll');
            clearAllBtn && clearAllBtn.addEventListener('click', _clearAllSelections);
            modal._bound = true;
        }
        document.addEventListener('keydown', _onKeydown);

        // Pre-populate search input
        const search = $('dswPickerSearch');
        if (search) search.value = _state.initialQuery;
        _renderSearchClear();

        // v3.34.4 — Picker DOM'unu document.body'ye taşı (stacking context escape).
        // Wizard modal openAsModal() ile overlay'ini body'ye ekliyor; picker ise
        // orijinal konumunda <section id="sectionDialog"> içinde kalıyordu. Eğer
        // herhangi bir ancestor (main.n-main, section.chat-area, vs.) transform /
        // filter / will-change / position:fixed gibi stacking-context oluşturursa
        // picker'ın `position: fixed; z-index: 1300` değeri body-level wizard
        // overlay'ine (z-index: 1000) karşı ÜSTÜNDE çizilemez. Body'ye taşıyarak
        // her iki modal'ı da aynı kök stacking context'e koyuyoruz; z-index
        // gerçekten karşılaştırılabilir hale geliyor.
        if (modal.parentNode !== document.body) {
            _state._origParent = modal.parentNode;
            _state._origNextSibling = modal.nextSibling;
            document.body.appendChild(modal);
        } else {
            _state._origParent = null;
            _state._origNextSibling = null;
        }

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
        // FIX6: abort any in-flight FK fetch before tearing down
        if (_state.fkAbortController) {
            try { _state.fkAbortController.abort(); } catch (e) {}
            _state.fkAbortController = null;
        }
        _state.fkLoading = false;
        const modal = $('dbSmartPickerModal');
        _hide(modal);
        document.body.classList.remove('dsw-picker-open');
        // v3.34.4 — open()'da body'ye taşınan picker'ı orijinal parent'a geri koy.
        // İdempotent: open her seferinde parentNode==body kontrolü yapıyor; restore
        // edilmediği takdirde tekrar açılışta _origParent kaybolur.
        if (_state._origParent && modal && modal.parentNode === document.body) {
            try {
                _state._origParent.insertBefore(modal, _state._origNextSibling || null);
            } catch (e) { /* ignore — DOM gitmiş olabilir */ }
        }
        _state._origParent = null;
        _state._origNextSibling = null;
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
