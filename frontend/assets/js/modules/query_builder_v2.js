/**
 * VYRA Query Builder v2 — v3.29.7 G4
 * ===================================
 * Multi-table drag-drop Query Builder.
 *
 *  - 2–8 tablo: arama + ekleme (sol panel)
 *  - FK path auto-suggest (orta panel) → /api/query-builder/suggest-path
 *  - Per-tablo kolon seçimi, filtre, agg/group_by (sağ panel)
 *  - SQL preview + opsiyonel 5s sample execute → /api/query-builder/preview
 *
 * HEBE Pre-Plan Gate uyumluluğu:
 *   - role="application" + role="list"
 *   - aria-label + data-tooltip
 *   - Tam keyboard erişimi (Tab/Enter/Space/Escape/Arrows)
 *   - aria-live="polite" status announcer
 *   - prefers-reduced-motion fallback (CSS)
 *   - Basit/Gelişmiş toggle (default: Basit = 2-hop)
 *
 * window.QueryBuilderV2 = {
 *   open({ parentEl, sourceId, dialect?, tablesCatalog?, onSqlReady? }),
 *   close()
 * }
 *
 * tablesCatalog: [{ schema, table, label_tr?, columns: [{name, type}] }, ...]
 *   Eğer verilmezse /api/data-sources/{sourceId}/objects'tan çekilir.
 */
(function () {
    'use strict';

    const JOIN_TYPES = [
        { v: 'INNER', label: 'INNER' },
        { v: 'LEFT', label: 'LEFT' },
        { v: 'RIGHT', label: 'RIGHT' },
        { v: 'FULL', label: 'FULL' },
    ];

    const FILTER_OPS = [
        { v: '=', label: '=' },
        { v: '!=', label: '≠' },
        { v: '<', label: '<' },
        { v: '<=', label: '≤' },
        { v: '>', label: '>' },
        { v: '>=', label: '≥' },
        { v: 'LIKE', label: 'LIKE' },
        { v: 'ILIKE', label: 'ILIKE' },
        { v: 'IN', label: 'IN (csv)' },
        { v: 'NOT IN', label: 'NOT IN (csv)' },
        { v: 'BETWEEN', label: 'BETWEEN (a,b)' },
        { v: 'IS NULL', label: 'IS NULL' },
        { v: 'IS NOT NULL', label: 'IS NOT NULL' },
    ];

    const AGG_FUNCS = ['', 'SUM', 'COUNT', 'AVG', 'MIN', 'MAX'];

    let _activeRoot = null;

    // ───────────────────────── helpers ─────────────────────────

    function _el(tag, attrs = {}, ...children) {
        const e = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs)) {
            if (k === 'class') e.className = v;
            else if (k === 'text') e.textContent = v;
            else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
            else if (v !== undefined && v !== null) e.setAttribute(k, v);
        }
        for (const c of children) {
            if (c == null) continue;
            e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
        }
        return e;
    }

    function _announce(root, msg) {
        const live = root.querySelector('.qbv2-live');
        if (live) live.textContent = msg;
    }

    function _toast(msg, type = 'info') {
        if (window.toast && typeof window.toast[type] === 'function') {
            window.toast[type](msg);
        } else if (window.showToast) {
            window.showToast(msg, type);
        } else {
            console.warn('[qbv2]', type, msg);
        }
    }

    async function _fetchJson(url, options = {}) {
        const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
        const token = (window.apiClient && window.apiClient.getToken && window.apiClient.getToken())
            || localStorage.getItem('access_token');
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(url, { ...options, headers });
        if (!resp.ok) {
            const text = await resp.text().catch(() => '');
            throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
        }
        return resp.json();
    }

    // ───────────────────────── state ─────────────────────────

    /**
     * state = {
     *   sourceId, dialect, catalog: [{schema, table, label_tr, columns}],
     *   tables: [{ schema, table, alias }],
     *   joins: [{ from_table, from_column, to_table, to_column, join_type }],
     *   select: [{ table, column, alias?, agg? }],
     *   filters: [{ table, column, op, value }],
     *   groupBy: [{ table, column }],
     *   orderBy: { table, column, direction } | null,
     *   limit: number,
     *   advanced: boolean,
     * }
     */
    function _emptyState(sourceId, dialect) {
        return {
            sourceId, dialect: dialect || 'postgresql',
            catalog: [],
            tables: [], joins: [],
            select: [], filters: [], groupBy: [],
            orderBy: null, limit: 50, advanced: false,
        };
    }

    function _aliasFor(table) { return table; }

    // ───────────────────────── catalog load ─────────────────────────

    async function _loadCatalog(state) {
        if (state.catalog && state.catalog.length) return state.catalog;
        try {
            const data = await _fetchJson(`/api/data-sources/${state.sourceId}/objects`);
            const items = (data && (data.items || data.objects || data)) || [];
            state.catalog = items.map((o) => ({
                schema: o.schema_name || o.schema || 'public',
                table: o.table_name || o.name,
                label_tr: o.business_name_tr || o.admin_label_tr || '',
                columns: o.columns_json || o.columns || [],
            })).filter((x) => x.table);
        } catch (err) {
            console.warn('[qbv2] catalog fetch failed:', err);
            state.catalog = [];
            _toast('Şema yüklenemedi: ' + err.message, 'warning');
        }
        return state.catalog;
    }

    // ───────────────────────── render: shell ─────────────────────────

    function _renderShell(parentEl, state) {
        parentEl.innerHTML = '';
        const root = _el('div', {
            class: 'qbv2-root',
            role: 'application',
            'aria-label': 'Multi-table sorgu oluşturucu',
        });

        const header = _el('div', { class: 'qbv2-header' },
            _el('div', { class: 'qbv2-title' },
                _el('i', { class: 'fa-solid fa-diagram-project' }),
                _el('span', { text: ' Multi-table Query Builder' }),
            ),
            _el('div', { class: 'qbv2-toolbar' },
                _el('label', { class: 'qbv2-toggle', 'data-tooltip': 'Basit: 2 tablo, Gelişmiş: 3+ tablo' },
                    _el('input', {
                        type: 'checkbox',
                        class: 'qbv2-adv-checkbox',
                        'aria-label': 'Gelişmiş mod (3+ tablo)',
                        onchange: (e) => {
                            state.advanced = e.target.checked;
                            _announce(root, state.advanced ? 'Gelişmiş mod' : 'Basit mod');
                        },
                    }),
                    _el('span', { text: ' Gelişmiş' }),
                ),
                _el('button', {
                    type: 'button',
                    class: 'qbv2-btn qbv2-btn-secondary',
                    'aria-label': 'Sorgu oluşturucuyu kapat',
                    'data-tooltip': 'Kapat (Esc)',
                    onclick: () => close(),
                },
                    _el('i', { class: 'fa-solid fa-xmark' }),
                ),
            ),
        );

        const body = _el('div', { class: 'qbv2-body' },
            _el('div', { class: 'qbv2-pane qbv2-pane-left', 'aria-label': 'Tablo arama' }),
            _el('div', { class: 'qbv2-pane qbv2-pane-center', 'aria-label': 'Seçili tablolar ve join yolları' }),
            _el('div', { class: 'qbv2-pane qbv2-pane-right', 'aria-label': 'Kolon ve filtre seçimi' }),
        );

        const footer = _el('div', { class: 'qbv2-footer' },
            _el('button', {
                type: 'button',
                class: 'qbv2-btn qbv2-btn-primary',
                'data-tooltip': 'SQL üret ve önizle',
                'aria-label': 'SQL önizle',
                onclick: () => _doPreview(root, state, false),
            },
                _el('i', { class: 'fa-solid fa-eye' }),
                _el('span', { text: ' SQL Önizle' }),
            ),
            _el('button', {
                type: 'button',
                class: 'qbv2-btn qbv2-btn-success',
                'data-tooltip': '5 saniyelik örnek yürütme (20 satır)',
                'aria-label': 'Örnek çalıştır',
                onclick: () => _doPreview(root, state, true),
            },
                _el('i', { class: 'fa-solid fa-play' }),
                _el('span', { text: ' Örnek Çalıştır' }),
            ),
            _el('div', { class: 'qbv2-live', role: 'status', 'aria-live': 'polite' }),
        );

        const previewBox = _el('div', { class: 'qbv2-preview', 'aria-label': 'SQL önizleme' });

        root.appendChild(header);
        root.appendChild(body);
        root.appendChild(footer);
        root.appendChild(previewBox);
        parentEl.appendChild(root);

        // Esc → close
        root.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { e.preventDefault(); close(); }
        });

        _activeRoot = root;
        return root;
    }

    // ───────────────────────── render: left (tablo arama) ─────────────────────────

    function _renderLeftPane(root, state) {
        const pane = root.querySelector('.qbv2-pane-left');
        pane.innerHTML = '';

        pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'Tablolar' }));

        const search = _el('input', {
            type: 'search',
            class: 'qbv2-search-input',
            placeholder: 'Tablo ara…',
            'aria-label': 'Tablo arama kutusu',
            oninput: (e) => _renderTableList(pane, state, e.target.value),
        });
        pane.appendChild(search);

        const list = _el('div', {
            class: 'qbv2-table-list',
            role: 'list',
            'aria-label': 'Mevcut tablolar listesi',
        });
        pane.appendChild(list);

        _renderTableList(pane, state, '');
    }

    function _renderTableList(pane, state, filterText) {
        const list = pane.querySelector('.qbv2-table-list');
        list.innerHTML = '';
        const q = (filterText || '').trim().toLowerCase();
        const items = state.catalog.filter((c) => {
            if (!q) return true;
            return (c.table.toLowerCase().includes(q)
                || (c.label_tr || '').toLowerCase().includes(q)
                || (c.schema || '').toLowerCase().includes(q));
        }).slice(0, 50);

        if (items.length === 0) {
            list.appendChild(_el('div', {
                class: 'qbv2-empty',
                text: q ? 'Eşleşen tablo yok' : 'Tablo bulunamadı',
            }));
            return;
        }

        items.forEach((c) => {
            const alreadyAdded = state.tables.some((t) => t.schema === c.schema && t.table === c.table);
            const btn = _el('button', {
                type: 'button',
                class: 'qbv2-table-item' + (alreadyAdded ? ' qbv2-table-added' : ''),
                role: 'listitem',
                'aria-label': `${c.schema}.${c.table} tablosunu ekle`,
                'data-tooltip': c.label_tr || `${c.schema}.${c.table}`,
                disabled: alreadyAdded ? 'true' : null,
                onclick: () => _addTable(root => _renderAll(root, state), state, c),
            },
                _el('i', { class: 'fa-solid fa-table' }),
                _el('span', { class: 'qbv2-table-name', text: ` ${c.table}` }),
                _el('span', { class: 'qbv2-table-schema', text: c.schema }),
            );
            list.appendChild(btn);
        });
    }

    function _addTable(rerender, state, catalogEntry) {
        if (state.tables.length >= 8) {
            _toast('En fazla 8 tablo eklenebilir', 'warning');
            return;
        }
        if (state.tables.some((t) => t.schema === catalogEntry.schema && t.table === catalogEntry.table)) {
            return;
        }
        state.tables.push({
            schema: catalogEntry.schema,
            table: catalogEntry.table,
            alias: _aliasFor(catalogEntry.table),
            columns: catalogEntry.columns || [],
            label_tr: catalogEntry.label_tr || '',
        });
        // Otomatik path öner (2+ tablo varsa son eklenen ile birinci arası)
        if (state.tables.length >= 2) {
            _autoSuggestPath(state, state.tables[0], state.tables[state.tables.length - 1]);
        }
        rerender(_activeRoot);
        _announce(_activeRoot, `${catalogEntry.table} eklendi`);
    }

    function _removeTable(state, idx) {
        const removed = state.tables.splice(idx, 1)[0];
        if (!removed) return;
        // İlgili join/select/filter/groupBy temizle
        state.joins = state.joins.filter((j) => j.from_table !== removed.table && j.to_table !== removed.table);
        state.select = state.select.filter((s) => s.table !== removed.table);
        state.filters = state.filters.filter((f) => f.table !== removed.table);
        state.groupBy = state.groupBy.filter((g) => g.table !== removed.table);
        if (state.orderBy && state.orderBy.table === removed.table) state.orderBy = null;
    }

    async function _autoSuggestPath(state, src, dst) {
        if (!src || !dst || src.table === dst.table) return;
        try {
            const result = await _fetchJson('/api/query-builder/suggest-path', {
                method: 'POST',
                body: JSON.stringify({
                    source_id: state.sourceId,
                    src: { schema: src.schema, table: src.table },
                    dst: { schema: dst.schema, table: dst.table },
                    k: 3, max_hops: 5,
                }),
            });
            const paths = (result && (result.paths || result.results)) || [];
            if (paths.length && paths[0].edges && paths[0].edges.length) {
                paths[0].edges.forEach((edge) => {
                    const exists = state.joins.some((j) =>
                        j.from_table === edge.from_table && j.from_column === edge.from_column
                        && j.to_table === edge.to_table && j.to_column === edge.to_column);
                    if (!exists) {
                        state.joins.push({
                            from_table: edge.from_table,
                            from_column: edge.from_column,
                            to_table: edge.to_table,
                            to_column: edge.to_column,
                            join_type: 'INNER',
                        });
                    }
                });
                _announce(_activeRoot, `${paths[0].edges.length} adımlı JOIN yolu önerildi`);
                _renderCenterPane(_activeRoot, state);
            }
        } catch (err) {
            console.warn('[qbv2] suggest-path failed:', err);
        }
    }

    // ───────────────────────── render: center (selected tables + joins) ─────────────────────────

    function _renderCenterPane(root, state) {
        const pane = root.querySelector('.qbv2-pane-center');
        pane.innerHTML = '';

        pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'Seçili Tablolar' }));

        if (state.tables.length === 0) {
            pane.appendChild(_el('div', {
                class: 'qbv2-empty',
                text: 'Soldan tablo seçin (2–8 arası)',
            }));
            return;
        }

        const tableList = _el('ol', { class: 'qbv2-selected-tables', 'aria-label': 'Seçili tablolar' });
        state.tables.forEach((t, idx) => {
            tableList.appendChild(_el('li', { class: 'qbv2-selected-item' },
                _el('span', { class: 'qbv2-selected-name', text: `${t.schema}.${t.table}` }),
                _el('button', {
                    type: 'button',
                    class: 'qbv2-icon-btn',
                    'aria-label': `${t.table} tablosunu kaldır`,
                    'data-tooltip': 'Kaldır',
                    onclick: () => { _removeTable(state, idx); _renderAll(root, state); },
                },
                    _el('i', { class: 'fa-solid fa-trash' }),
                ),
            ));
        });
        pane.appendChild(tableList);

        // JOIN edge editor
        pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'JOIN Yolu' }));
        if (state.joins.length === 0) {
            pane.appendChild(_el('div', {
                class: 'qbv2-empty',
                text: state.tables.length >= 2 ? 'Otomatik öneri yok — manuel ekleyin' : '',
            }));
        } else {
            const joinList = _el('ol', { class: 'qbv2-join-list' });
            state.joins.forEach((j, idx) => {
                joinList.appendChild(_renderJoinRow(root, state, j, idx));
            });
            pane.appendChild(joinList);
        }

        // Yeni join ekle butonu
        if (state.tables.length >= 2) {
            const addBtn = _el('button', {
                type: 'button',
                class: 'qbv2-btn qbv2-btn-secondary qbv2-btn-sm',
                'data-tooltip': 'Manuel JOIN edge ekle',
                'aria-label': 'JOIN ekle',
                onclick: () => {
                    state.joins.push({
                        from_table: state.tables[0].table, from_column: '',
                        to_table: state.tables[1].table, to_column: '',
                        join_type: 'INNER',
                    });
                    _renderCenterPane(root, state);
                },
            },
                _el('i', { class: 'fa-solid fa-plus' }),
                _el('span', { text: ' JOIN ekle' }),
            );
            pane.appendChild(addBtn);
        }
    }

    function _renderJoinRow(root, state, j, idx) {
        const li = _el('li', { class: 'qbv2-join-row', role: 'group', 'aria-label': `JOIN ${idx + 1}` });

        const typeSel = _el('select', {
            class: 'qbv2-mini-select',
            'aria-label': 'JOIN tipi',
            onchange: (e) => { j.join_type = e.target.value; },
        });
        JOIN_TYPES.forEach((jt) => {
            const o = _el('option', { value: jt.v, text: jt.label });
            if (jt.v === j.join_type) o.selected = true;
            typeSel.appendChild(o);
        });

        const fromTblSel = _renderTableSelect(state, j.from_table, (v) => { j.from_table = v; j.from_column = ''; _renderCenterPane(root, state); });
        const fromColSel = _renderColumnSelect(state, j.from_table, j.from_column, (v) => { j.from_column = v; });

        const arrow = _el('span', { class: 'qbv2-arrow', text: '⟷', 'aria-hidden': 'true' });

        const toTblSel = _renderTableSelect(state, j.to_table, (v) => { j.to_table = v; j.to_column = ''; _renderCenterPane(root, state); });
        const toColSel = _renderColumnSelect(state, j.to_table, j.to_column, (v) => { j.to_column = v; });

        const delBtn = _el('button', {
            type: 'button',
            class: 'qbv2-icon-btn',
            'aria-label': 'JOIN kaldır',
            'data-tooltip': 'Kaldır',
            onclick: () => { state.joins.splice(idx, 1); _renderCenterPane(root, state); },
        }, _el('i', { class: 'fa-solid fa-trash' }));

        li.appendChild(typeSel);
        li.appendChild(fromTblSel);
        li.appendChild(_el('span', { class: 'qbv2-dot', text: '.' }));
        li.appendChild(fromColSel);
        li.appendChild(arrow);
        li.appendChild(toTblSel);
        li.appendChild(_el('span', { class: 'qbv2-dot', text: '.' }));
        li.appendChild(toColSel);
        li.appendChild(delBtn);
        return li;
    }

    function _renderTableSelect(state, current, onchange) {
        const sel = _el('select', {
            class: 'qbv2-mini-select',
            'aria-label': 'Tablo',
            onchange: (e) => onchange(e.target.value),
        });
        state.tables.forEach((t) => {
            const o = _el('option', { value: t.table, text: t.table });
            if (t.table === current) o.selected = true;
            sel.appendChild(o);
        });
        return sel;
    }

    function _renderColumnSelect(state, tableName, current, onchange) {
        const sel = _el('select', {
            class: 'qbv2-mini-select',
            'aria-label': 'Kolon',
            onchange: (e) => onchange(e.target.value),
        });
        sel.appendChild(_el('option', { value: '', text: '— kolon —' }));
        const tref = state.tables.find((t) => t.table === tableName);
        const cols = (tref && tref.columns) || [];
        cols.forEach((c) => {
            const name = typeof c === 'string' ? c : c.name;
            const o = _el('option', { value: name, text: name });
            if (name === current) o.selected = true;
            sel.appendChild(o);
        });
        return sel;
    }

    // ───────────────────────── render: right (select + filter + groupby) ─────────────────────────

    function _renderRightPane(root, state) {
        const pane = root.querySelector('.qbv2-pane-right');
        pane.innerHTML = '';

        pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'SELECT Kolonları' }));
        const selectList = _el('div', { class: 'qbv2-clause-list' });
        state.select.forEach((s, idx) => selectList.appendChild(_renderSelectRow(root, state, s, idx)));
        pane.appendChild(selectList);
        pane.appendChild(_el('button', {
            type: 'button',
            class: 'qbv2-btn qbv2-btn-secondary qbv2-btn-sm',
            'aria-label': 'SELECT kolon ekle',
            'data-tooltip': 'Yeni kolon',
            onclick: () => {
                if (state.tables.length === 0) return;
                state.select.push({ table: state.tables[0].table, column: '', alias: '', agg: '' });
                _renderRightPane(root, state);
            },
        }, _el('i', { class: 'fa-solid fa-plus' }), _el('span', { text: ' SELECT' })));

        pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'Filtreler (WHERE)' }));
        const filterList = _el('div', { class: 'qbv2-clause-list' });
        state.filters.forEach((f, idx) => filterList.appendChild(_renderFilterRow(root, state, f, idx)));
        pane.appendChild(filterList);
        pane.appendChild(_el('button', {
            type: 'button',
            class: 'qbv2-btn qbv2-btn-secondary qbv2-btn-sm',
            'aria-label': 'Filtre ekle',
            'data-tooltip': 'Yeni filtre',
            onclick: () => {
                if (state.tables.length === 0) return;
                state.filters.push({ table: state.tables[0].table, column: '', op: '=', value: '' });
                _renderRightPane(root, state);
            },
        }, _el('i', { class: 'fa-solid fa-plus' }), _el('span', { text: ' Filtre' })));

        // Gelişmiş: GROUP BY + ORDER BY
        if (state.advanced) {
            pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'GROUP BY' }));
            const gList = _el('div', { class: 'qbv2-clause-list' });
            state.groupBy.forEach((g, idx) => gList.appendChild(_renderGroupByRow(root, state, g, idx)));
            pane.appendChild(gList);
            pane.appendChild(_el('button', {
                type: 'button',
                class: 'qbv2-btn qbv2-btn-secondary qbv2-btn-sm',
                'aria-label': 'GROUP BY ekle',
                onclick: () => {
                    if (state.tables.length === 0) return;
                    state.groupBy.push({ table: state.tables[0].table, column: '' });
                    _renderRightPane(root, state);
                },
            }, _el('i', { class: 'fa-solid fa-plus' }), _el('span', { text: ' GROUP BY' })));
        }

        // ORDER BY + LIMIT
        pane.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'ORDER BY · LIMIT' }));
        pane.appendChild(_renderOrderByRow(root, state));
        pane.appendChild(_renderLimitRow(root, state));
    }

    function _renderSelectRow(root, state, s, idx) {
        const row = _el('div', { class: 'qbv2-clause-row' });
        const aggSel = _el('select', {
            class: 'qbv2-mini-select',
            'aria-label': 'Aggregate fonksiyon',
            onchange: (e) => { s.agg = e.target.value || ''; },
        });
        AGG_FUNCS.forEach((a) => {
            const o = _el('option', { value: a, text: a || '—' });
            if (a === (s.agg || '')) o.selected = true;
            aggSel.appendChild(o);
        });

        const tblSel = _renderTableSelect(state, s.table, (v) => { s.table = v; s.column = ''; _renderRightPane(root, state); });
        const colSel = _renderColumnSelect(state, s.table, s.column, (v) => { s.column = v; });
        const aliasInput = _el('input', {
            type: 'text',
            class: 'qbv2-mini-input',
            placeholder: 'alias',
            'aria-label': 'Kolon alias',
            value: s.alias || '',
            oninput: (e) => { s.alias = e.target.value; },
        });
        const delBtn = _el('button', {
            type: 'button',
            class: 'qbv2-icon-btn',
            'aria-label': 'SELECT kolon kaldır',
            onclick: () => { state.select.splice(idx, 1); _renderRightPane(root, state); },
        }, _el('i', { class: 'fa-solid fa-trash' }));

        row.appendChild(aggSel);
        row.appendChild(tblSel);
        row.appendChild(colSel);
        row.appendChild(aliasInput);
        row.appendChild(delBtn);
        return row;
    }

    function _renderFilterRow(root, state, f, idx) {
        const row = _el('div', { class: 'qbv2-clause-row' });
        const tblSel = _renderTableSelect(state, f.table, (v) => { f.table = v; f.column = ''; _renderRightPane(root, state); });
        const colSel = _renderColumnSelect(state, f.table, f.column, (v) => { f.column = v; });

        const opSel = _el('select', {
            class: 'qbv2-mini-select',
            'aria-label': 'Filtre operatörü',
            onchange: (e) => { f.op = e.target.value; _renderRightPane(root, state); },
        });
        FILTER_OPS.forEach((op) => {
            const o = _el('option', { value: op.v, text: op.label });
            if (op.v === f.op) o.selected = true;
            opSel.appendChild(o);
        });

        const needsValue = !['IS NULL', 'IS NOT NULL'].includes(f.op);
        const valueInput = needsValue ? _el('input', {
            type: 'text',
            class: 'qbv2-mini-input',
            placeholder: ['IN', 'NOT IN', 'BETWEEN'].includes(f.op) ? 'csv değer' : 'değer',
            'aria-label': 'Filtre değeri',
            value: Array.isArray(f.value) ? f.value.join(',') : (f.value || ''),
            oninput: (e) => {
                const raw = e.target.value;
                if (['IN', 'NOT IN', 'BETWEEN'].includes(f.op)) {
                    f.value = raw.split(',').map((x) => x.trim()).filter((x) => x !== '');
                } else {
                    f.value = raw;
                }
            },
        }) : null;

        const delBtn = _el('button', {
            type: 'button',
            class: 'qbv2-icon-btn',
            'aria-label': 'Filtre kaldır',
            onclick: () => { state.filters.splice(idx, 1); _renderRightPane(root, state); },
        }, _el('i', { class: 'fa-solid fa-trash' }));

        row.appendChild(tblSel);
        row.appendChild(colSel);
        row.appendChild(opSel);
        if (valueInput) row.appendChild(valueInput);
        row.appendChild(delBtn);
        return row;
    }

    function _renderGroupByRow(root, state, g, idx) {
        const row = _el('div', { class: 'qbv2-clause-row' });
        const tblSel = _renderTableSelect(state, g.table, (v) => { g.table = v; g.column = ''; _renderRightPane(root, state); });
        const colSel = _renderColumnSelect(state, g.table, g.column, (v) => { g.column = v; });
        const delBtn = _el('button', {
            type: 'button',
            class: 'qbv2-icon-btn',
            'aria-label': 'GROUP BY kaldır',
            onclick: () => { state.groupBy.splice(idx, 1); _renderRightPane(root, state); },
        }, _el('i', { class: 'fa-solid fa-trash' }));
        row.appendChild(tblSel);
        row.appendChild(colSel);
        row.appendChild(delBtn);
        return row;
    }

    function _renderOrderByRow(root, state) {
        const row = _el('div', { class: 'qbv2-clause-row' });
        const enabled = !!state.orderBy;
        const toggle = _el('input', {
            type: 'checkbox',
            'aria-label': 'ORDER BY etkin',
            onchange: (e) => {
                if (e.target.checked) {
                    state.orderBy = { table: state.tables[0]?.table || '', column: '', direction: 'ASC' };
                } else {
                    state.orderBy = null;
                }
                _renderRightPane(root, state);
            },
        });
        if (enabled) toggle.checked = true;
        row.appendChild(toggle);
        row.appendChild(_el('span', { text: ' ORDER BY ' }));

        if (state.orderBy) {
            const tblSel = _renderTableSelect(state, state.orderBy.table, (v) => { state.orderBy.table = v; state.orderBy.column = ''; _renderRightPane(root, state); });
            const colSel = _renderColumnSelect(state, state.orderBy.table, state.orderBy.column, (v) => { state.orderBy.column = v; });
            const dirSel = _el('select', { class: 'qbv2-mini-select', 'aria-label': 'Sıra yönü', onchange: (e) => { state.orderBy.direction = e.target.value; } });
            ['ASC', 'DESC'].forEach((d) => {
                const o = _el('option', { value: d, text: d });
                if (d === state.orderBy.direction) o.selected = true;
                dirSel.appendChild(o);
            });
            row.appendChild(tblSel);
            row.appendChild(colSel);
            row.appendChild(dirSel);
        }
        return row;
    }

    function _renderLimitRow(root, state) {
        const row = _el('div', { class: 'qbv2-clause-row' });
        row.appendChild(_el('span', { text: 'LIMIT ' }));
        const input = _el('input', {
            type: 'number',
            class: 'qbv2-mini-input',
            min: '1', max: '1000', step: '1',
            value: String(state.limit),
            'aria-label': 'Limit',
            'data-tooltip': '1 – 1000 arası',
            oninput: (e) => {
                const v = parseInt(e.target.value || '50', 10);
                state.limit = Math.max(1, Math.min(1000, v || 50));
            },
        });
        row.appendChild(input);
        return row;
    }

    // ───────────────────────── render: all ─────────────────────────

    function _renderAll(root, state) {
        _renderLeftPane(root, state);
        _renderCenterPane(root, state);
        _renderRightPane(root, state);
    }

    // ───────────────────────── preview ─────────────────────────

    async function _doPreview(root, state, execute) {
        if (state.tables.length === 0) {
            _toast('Önce tablo ekleyin', 'warning');
            return;
        }
        const box = root.querySelector('.qbv2-preview');
        box.innerHTML = '';
        box.appendChild(_el('div', { class: 'qbv2-loading', text: 'Önizleme hazırlanıyor…', 'aria-live': 'polite' }));

        // Build payload (yalnız değeri olanları dahil et)
        const payload = {
            source_id: state.sourceId,
            tables: state.tables.map((t) => ({ schema: t.schema, table: t.table, alias: t.alias })),
            joins: state.joins
                .filter((j) => j.from_column && j.to_column)
                .map((j) => ({
                    from_table: j.from_table, from_column: j.from_column,
                    to_table: j.to_table, to_column: j.to_column,
                    join_type: j.join_type || 'INNER',
                })),
            select: state.select
                .filter((s) => s.column)
                .map((s) => ({
                    table: s.table, column: s.column,
                    alias: s.alias || null,
                    agg: s.agg || null,
                })),
            filters: state.filters
                .filter((f) => f.column && (['IS NULL', 'IS NOT NULL'].includes(f.op) || f.value !== '' && f.value != null))
                .map((f) => ({ table: f.table, column: f.column, op: f.op, value: f.value })),
            group_by: state.groupBy
                .filter((g) => g.column)
                .map((g) => ({ table: g.table, column: g.column })),
            order_by: state.orderBy && state.orderBy.column
                ? { table: state.orderBy.table, column: state.orderBy.column, direction: state.orderBy.direction }
                : null,
            limit: state.limit,
            dialect: state.dialect,
            execute: !!execute,
        };

        try {
            const result = await _fetchJson('/api/query-builder/preview', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            _renderPreviewResult(box, result, state, execute);
            if (state._onSqlReady) {
                try { state._onSqlReady(result.sql, result.params, result.warnings); } catch (e) { console.warn(e); }
            }
        } catch (err) {
            box.innerHTML = '';
            box.appendChild(_el('div', { class: 'qbv2-error', text: 'Hata: ' + err.message }));
            _toast('Önizleme başarısız: ' + err.message, 'error');
        }
    }

    function _renderPreviewResult(box, result, state, executed) {
        box.innerHTML = '';
        box.appendChild(_el('h4', { class: 'qbv2-pane-title', text: 'SQL Önizleme' }));

        const sql = _el('pre', { class: 'qbv2-sql', tabindex: '0', 'aria-label': 'Üretilen SQL' });
        sql.textContent = result.sql || '';
        box.appendChild(sql);

        const copyBtn = _el('button', {
            type: 'button',
            class: 'qbv2-btn qbv2-btn-secondary qbv2-btn-sm',
            'aria-label': 'SQL kopyala',
            'data-tooltip': 'Panoya kopyala',
            onclick: async () => {
                try { await navigator.clipboard.writeText(result.sql || ''); _toast('SQL kopyalandı', 'success'); }
                catch { _toast('Kopyalanamadı', 'error'); }
            },
        }, _el('i', { class: 'fa-solid fa-copy' }), _el('span', { text: ' Kopyala' }));
        box.appendChild(copyBtn);

        if (result.warnings && result.warnings.length) {
            const wlist = _el('ul', { class: 'qbv2-warnings', 'aria-label': 'Uyarılar' });
            result.warnings.forEach((w) => wlist.appendChild(_el('li', { text: w })));
            box.appendChild(wlist);
        }

        if (executed && result.executed) {
            if (result.success && Array.isArray(result.rows)) {
                box.appendChild(_renderRowsTable(result.columns || [], result.rows));
                _announce(_activeRoot, `${result.row_count || result.rows.length} satır`);
            } else if (!result.success) {
                box.appendChild(_el('div', { class: 'qbv2-error', text: 'Yürütme hatası: ' + (result.execute_error || 'bilinmeyen') }));
            }
        }
    }

    function _renderRowsTable(columns, rows) {
        const cols = columns.length ? columns : (rows[0] ? Object.keys(rows[0]) : []);
        const tbl = _el('table', { class: 'qbv2-rows-table', 'aria-label': 'Örnek satırlar' });
        const thead = _el('thead', {});
        const trH = _el('tr', {});
        cols.forEach((c) => trH.appendChild(_el('th', { text: typeof c === 'string' ? c : c.name })));
        thead.appendChild(trH);
        tbl.appendChild(thead);
        const tbody = _el('tbody', {});
        rows.slice(0, 20).forEach((r) => {
            const tr = _el('tr', {});
            cols.forEach((c) => {
                const key = typeof c === 'string' ? c : c.name;
                const v = r[key];
                tr.appendChild(_el('td', { text: v === null || v === undefined ? '∅' : String(v).slice(0, 200) }));
            });
            tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        return tbl;
    }

    // ───────────────────────── public API ─────────────────────────

    async function open(opts = {}) {
        if (!opts.parentEl || !opts.sourceId) {
            console.error('[qbv2] parentEl ve sourceId zorunlu');
            return;
        }
        if (_activeRoot) close();

        const state = _emptyState(opts.sourceId, opts.dialect);
        state._onSqlReady = opts.onSqlReady;

        if (Array.isArray(opts.tablesCatalog) && opts.tablesCatalog.length) {
            state.catalog = opts.tablesCatalog.map((c) => ({
                schema: c.schema || 'public',
                table: c.table || c.name,
                label_tr: c.label_tr || '',
                columns: c.columns || [],
            }));
        }

        _renderShell(opts.parentEl, state);
        if (!state.catalog.length) {
            await _loadCatalog(state);
        }
        _renderAll(_activeRoot, state);

        return state;
    }

    function close() {
        if (_activeRoot && _activeRoot.parentNode) {
            _activeRoot.parentNode.removeChild(_activeRoot);
        }
        _activeRoot = null;
    }

    window.QueryBuilderV2 = { open, close };
})();
