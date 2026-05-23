/**
 * VYRA Query Builder Module — v3.28.3 G4
 * =======================================
 * Pre-execute Drag-Drop Query Builder.
 *
 * Kullanıcı bir tablo seçtikten sonra:
 *   - Kolon chip'lerini SEÇİLDİ paneline drag-drop ile alır (sıra önemli)
 *   - Filtre satırı ekler (kolon + operatör + value)
 *   - Order by + limit ayarlar
 *   - "SQL Önizle" tıklayınca POST /api/query-state/preview
 *
 * SaaS / HEBE checklist:
 *   - role="application" (drag-drop kabı)
 *   - role="list" + role="listitem" alt kapsamlar
 *   - aria-grabbed (legacy) + aria-pressed
 *   - Tam keyboard alternatifi:
 *       Space: tutucu seç (grab) / bırak (drop)
 *       ArrowUp/Down: seçili kolonu yukarı/aşağı taşı (order)
 *       Enter: kolonu seçilenler panelinin sonuna ekle
 *       Escape: tutucudan vazgeç
 *   - data-tooltip ile yardım metni
 *   - aria-live="polite" status mesajı
 *
 * window.QueryBuilder = { open(opts), close() }
 *   opts:
 *     parentEl: HTMLElement       → component buraya inject edilir
 *     sourceId: number            → /api/query-state/preview body.source_id
 *     schema: string|null
 *     table: string
 *     columns: [{name, type}]     → ds_db_objects.columns_json içeriği
 *     dialect: 'postgresql'|...   → opsiyonel
 *     onSqlReady(sql, params, warnings) → SQL üretilince çağrılır
 */
(function () {
    'use strict';

    const ALLOWED_OPS = [
        { v: '=', label: '=' },
        { v: '!=', label: '≠' },
        { v: '<', label: '<' },
        { v: '<=', label: '≤' },
        { v: '>', label: '>' },
        { v: '>=', label: '≥' },
        { v: 'LIKE', label: 'LIKE' },
        { v: 'ILIKE', label: 'ILIKE' },
        { v: 'IS NULL', label: 'IS NULL' },
        { v: 'IS NOT NULL', label: 'IS NOT NULL' },
        { v: 'IN', label: 'IN (csv)' },
    ];

    /** Mevcut açık builder referansı (tek aktif builder) */
    let _activeRoot = null;

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
        const live = root.querySelector('.qb-live');
        if (live) live.textContent = msg;
    }

    function _renderAvailableColumn(col, state, root) {
        const chip = _el('button', {
            type: 'button',
            class: 'qb-col-chip',
            'data-col': col.name,
            'data-type': col.type || '',
            'aria-grabbed': 'false',
            'aria-pressed': 'false',
            'data-tooltip': `${col.name} (${col.type || '?'})`,
            title: `${col.name} (${col.type || '?'})`,
            text: col.name,
        });

        chip.addEventListener('click', () => {
            if (!state.selected.includes(col.name)) {
                state.selected.push(col.name);
                _renderSelected(state, root);
                _announce(root, `${col.name} seçildi`);
            }
        });

        chip.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                chip.click();
            }
        });

        // Drag start (mouse)
        chip.draggable = true;
        chip.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', col.name);
            e.dataTransfer.effectAllowed = 'copy';
            chip.setAttribute('aria-grabbed', 'true');
        });
        chip.addEventListener('dragend', () => chip.setAttribute('aria-grabbed', 'false'));

        return chip;
    }

    function _renderSelected(state, root) {
        const list = root.querySelector('.qb-selected-list');
        list.innerHTML = '';
        if (state.selected.length === 0) {
            list.appendChild(_el('li', {
                class: 'qb-selected-empty',
                role: 'note',
                text: 'Henüz kolon seçilmedi. Kolon chip\'ine tıklayın veya buraya sürükleyin.',
            }));
            return;
        }
        state.selected.forEach((colName, idx) => {
            const li = _el('li', {
                class: 'qb-selected-item',
                role: 'listitem',
                tabindex: '0',
                'data-idx': String(idx),
                'aria-label': `${colName} — sıra ${idx + 1}`,
            });
            li.appendChild(_el('span', { class: 'qb-selected-handle', 'aria-hidden': 'true', text: '⋮⋮' }));
            li.appendChild(_el('span', { class: 'qb-selected-name', text: colName }));
            const rmBtn = _el('button', {
                type: 'button',
                class: 'qb-selected-remove',
                'aria-label': `${colName} kaldır`,
                title: 'Kaldır',
                text: '×',
            });
            rmBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                state.selected.splice(idx, 1);
                _renderSelected(state, root);
                _announce(root, `${colName} kaldırıldı`);
            });
            li.appendChild(rmBtn);

            // Keyboard: ArrowUp/Down = swap; Space = grab/drop toggle; Delete = remove
            li.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowUp' && idx > 0) {
                    e.preventDefault();
                    [state.selected[idx - 1], state.selected[idx]] = [state.selected[idx], state.selected[idx - 1]];
                    _renderSelected(state, root);
                    const items = list.querySelectorAll('.qb-selected-item');
                    if (items[idx - 1]) items[idx - 1].focus();
                    _announce(root, `${colName} yukarı taşındı`);
                } else if (e.key === 'ArrowDown' && idx < state.selected.length - 1) {
                    e.preventDefault();
                    [state.selected[idx + 1], state.selected[idx]] = [state.selected[idx], state.selected[idx + 1]];
                    _renderSelected(state, root);
                    const items = list.querySelectorAll('.qb-selected-item');
                    if (items[idx + 1]) items[idx + 1].focus();
                    _announce(root, `${colName} aşağı taşındı`);
                } else if (e.key === 'Delete' || e.key === 'Backspace') {
                    e.preventDefault();
                    rmBtn.click();
                } else if (e.key === 'Escape') {
                    li.blur();
                }
            });
            list.appendChild(li);
        });
    }

    function _renderFilters(state, root) {
        const wrap = root.querySelector('.qb-filters-list');
        wrap.innerHTML = '';
        state.filters.forEach((f, i) => {
            const row = _el('div', { class: 'qb-filter-row', role: 'group', 'aria-label': `Filtre ${i + 1}` });

            // Column select
            const colSel = _el('select', { class: 'qb-filter-col', 'aria-label': 'Kolon' });
            colSel.appendChild(_el('option', { value: '', text: '— kolon —' }));
            state.columns.forEach(c => {
                const opt = _el('option', { value: c.name, text: c.name });
                if (c.name === f.column) opt.selected = true;
                colSel.appendChild(opt);
            });
            colSel.addEventListener('change', () => { f.column = colSel.value; });

            // Op select
            const opSel = _el('select', { class: 'qb-filter-op', 'aria-label': 'Operatör' });
            ALLOWED_OPS.forEach(o => {
                const opt = _el('option', { value: o.v, text: o.label });
                if (o.v === f.op) opt.selected = true;
                opSel.appendChild(opt);
            });
            opSel.addEventListener('change', () => {
                f.op = opSel.value;
                _renderFilters(state, root);
            });

            // Value input (IS NULL/IS NOT NULL → gizli)
            const isNullOp = f.op === 'IS NULL' || f.op === 'IS NOT NULL';
            const valInput = _el('input', {
                type: 'text',
                class: 'qb-filter-val',
                'aria-label': 'Değer',
                placeholder: f.op === 'IN' ? 'a,b,c' : 'değer',
                value: f.value != null ? String(f.value) : '',
            });
            if (isNullOp) valInput.style.visibility = 'hidden';
            valInput.addEventListener('input', () => { f.value = valInput.value; });

            // Remove
            const rmBtn = _el('button', {
                type: 'button',
                class: 'qb-filter-remove',
                'aria-label': `Filtre ${i + 1} kaldır`,
                title: 'Kaldır',
                text: '×',
            });
            rmBtn.addEventListener('click', () => {
                state.filters.splice(i, 1);
                _renderFilters(state, root);
            });

            row.appendChild(colSel);
            row.appendChild(opSel);
            row.appendChild(valInput);
            row.appendChild(rmBtn);
            wrap.appendChild(row);
        });
    }

    function _coerceFilters(filters) {
        return filters
            .filter(f => f.column && f.op)
            .map(f => {
                if (f.op === 'IS NULL' || f.op === 'IS NOT NULL') {
                    return { column: f.column, op: f.op };
                }
                if (f.op === 'IN') {
                    const vals = String(f.value || '')
                        .split(',').map(s => s.trim()).filter(Boolean);
                    return { column: f.column, op: 'IN', value: vals };
                }
                let v = f.value;
                if (v != null && /^-?\d+(\.\d+)?$/.test(String(v).trim())) {
                    v = Number(v);
                }
                return { column: f.column, op: f.op, value: v };
            });
    }

    async function _fetchPreview(state, root) {
        const statusEl = root.querySelector('.qb-status');
        const sqlBox = root.querySelector('.qb-sql-output');
        statusEl.textContent = 'Sorgu inşa ediliyor...';
        statusEl.setAttribute('aria-busy', 'true');
        sqlBox.textContent = '';

        const body = {
            source_id: state.sourceId || null,
            schema: state.schema || null,
            table: state.table,
            dialect: state.dialect || null,
            selected_columns: state.selected,
            filters: _coerceFilters(state.filters),
            order_by: state.orderColumn ? {
                column: state.orderColumn,
                direction: state.orderDir || 'ASC',
            } : null,
            limit: Number(state.limit) || 100,
        };

        try {
            const apiBase = (window.VYRA_API_BASE || '');
            const resp = await fetch(`${apiBase}/api/query-state/preview`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    ...(window.getAuthHeader ? window.getAuthHeader() : {}),
                },
                body: JSON.stringify(body),
            });
            const data = await resp.json().catch(() => ({}));
            statusEl.removeAttribute('aria-busy');

            if (!resp.ok || !data.valid) {
                const errs = (data.warnings || [data.detail || 'Bilinmeyen hata']).join('; ');
                statusEl.textContent = `Hata: ${errs}`;
                statusEl.classList.add('qb-status-error');
                return;
            }
            statusEl.classList.remove('qb-status-error');
            statusEl.textContent = data.warnings && data.warnings.length
                ? `Uyarılar: ${data.warnings.join('; ')}`
                : 'SQL hazır.';
            sqlBox.textContent = data.sql || '';
            _announce(root, 'SQL üretildi');

            // v3.32.0: SQL'i state'e cache'le ve action butonlarını aktif et
            state.lastSql = data.sql || '';
            state.lastParams = data.params || [];
            _enableActionButtons(root, !!state.lastSql);

            if (typeof state.onSqlReady === 'function') {
                state.onSqlReady(data.sql, data.params || [], data.warnings || []);
            }
        } catch (err) {
            statusEl.removeAttribute('aria-busy');
            statusEl.textContent = `Ağ hatası: ${err.message}`;
            statusEl.classList.add('qb-status-error');
        }
    }

    // ── v3.32.0: Action helpers ────────────────────────────────────────

    function _enableActionButtons(root, enabled) {
        for (const cls of ['.qb-copy-btn', '.qb-exec-btn', '.qb-send-btn']) {
            const btn = root.querySelector(cls);
            if (!btn) continue;
            if (enabled) btn.removeAttribute('disabled');
            else btn.setAttribute('disabled', 'true');
        }
    }

    async function _copySql(state, root) {
        const statusEl = root.querySelector('.qb-status');
        if (!state.lastSql) {
            statusEl.textContent = 'Önce "SQL Önizle" tıklayın.';
            return;
        }
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(state.lastSql);
            } else {
                // Fallback: textarea trick
                const ta = document.createElement('textarea');
                ta.value = state.lastSql;
                ta.setAttribute('readonly', '');
                ta.style.position = 'absolute';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            statusEl.classList.remove('qb-status-error');
            statusEl.textContent = 'SQL panoya kopyalandı.';
            if (window.showToast) window.showToast('SQL panoya kopyalandı', 'success');
            _announce(root, 'SQL panoya kopyalandı');
        } catch (err) {
            statusEl.classList.add('qb-status-error');
            statusEl.textContent = `Kopyalama hatası: ${err.message}`;
        }
    }

    async function _executeSql(state, root) {
        const statusEl = root.querySelector('.qb-status');
        const resultSection = root.querySelector('.qb-result-section');
        const resultMeta = root.querySelector('.qb-result-meta');
        const resultBody = root.querySelector('.qb-result-body');

        if (!state.lastSql) {
            statusEl.textContent = 'Önce "SQL Önizle" tıklayın.';
            return;
        }
        if (!state.sourceId) {
            statusEl.classList.add('qb-status-error');
            statusEl.textContent = 'source_id eksik — execute mümkün değil.';
            return;
        }

        // execute=true ile aynı preview endpoint'ini çağırıyoruz; backend
        // params'ı strict whitelist ile inline edip SafeSQLExecutor üzerinden
        // 5sn timeout + 100 satır cap ile çalıştırır.
        const body = {
            source_id: state.sourceId,
            schema: state.schema || null,
            table: state.table,
            dialect: state.dialect || null,
            selected_columns: state.selected,
            filters: _coerceFilters(state.filters),
            order_by: state.orderColumn ? {
                column: state.orderColumn,
                direction: state.orderDir || 'ASC',
            } : null,
            limit: Number(state.limit) || 100,
            execute: true,
        };

        statusEl.textContent = 'Çalıştırılıyor (5sn timeout)...';
        statusEl.setAttribute('aria-busy', 'true');
        statusEl.classList.remove('qb-status-error');
        resultSection.setAttribute('hidden', 'hidden');
        resultBody.innerHTML = '';
        resultMeta.textContent = '';

        try {
            const apiBase = (window.VYRA_API_BASE || '');
            const resp = await fetch(`${apiBase}/api/query-state/preview`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    ...(window.getAuthHeader ? window.getAuthHeader() : {}),
                },
                body: JSON.stringify(body),
            });
            const data = await resp.json().catch(() => ({}));
            statusEl.removeAttribute('aria-busy');

            if (!resp.ok) {
                statusEl.classList.add('qb-status-error');
                statusEl.textContent = `HTTP ${resp.status}: ${(data && (data.detail || data.execute_error)) || 'Hata'}`;
                return;
            }
            if (data.success === false) {
                resultSection.removeAttribute('hidden');
                resultMeta.textContent = '⚠ Çalıştırma hatası';
                resultBody.innerHTML = `<div class="qb-result-error">${_escHtml(data.execute_error || 'Bilinmeyen hata')}</div>`;
                statusEl.classList.add('qb-status-error');
                statusEl.textContent = 'Sorgu hata döndürdü — detay için sonuç alanına bakın.';
                return;
            }
            // Başarılı — sonucu render et
            const rows = Array.isArray(data.rows) ? data.rows : [];
            const cols = Array.isArray(data.columns) && data.columns.length
                ? data.columns
                : (rows[0] && typeof rows[0] === 'object' ? Object.keys(rows[0]) : []);
            resultSection.removeAttribute('hidden');
            resultMeta.textContent = `${rows.length} satır`
                + (data.row_count && data.row_count !== rows.length ? ` (toplam: ${data.row_count})` : '')
                + (data.truncated ? ' • cap uygulandı' : '')
                + (data.elapsed_ms ? ` • ${Math.round(data.elapsed_ms)}ms` : '');
            resultBody.innerHTML = _renderResultTable(cols, rows);
            statusEl.textContent = 'Sorgu çalıştırıldı.';
            if (window.showToast) window.showToast(`Sorgu başarılı (${rows.length} satır)`, 'success');
            _announce(root, `Sorgu çalıştırıldı, ${rows.length} satır`);
        } catch (err) {
            statusEl.removeAttribute('aria-busy');
            statusEl.classList.add('qb-status-error');
            statusEl.textContent = `Ağ hatası: ${err.message}`;
        }
    }

    function _sendSqlToChat(state, root) {
        const statusEl = root.querySelector('.qb-status');
        if (!state.lastSql) {
            statusEl.textContent = 'Önce "SQL Önizle" tıklayın.';
            return;
        }
        const inp = document.getElementById('dialogInput');
        if (!inp) {
            statusEl.classList.add('qb-status-error');
            statusEl.textContent = 'Sohbet kutusu bulunamadı.';
            return;
        }
        const prefix = `Şu SQL'i çalıştırıp sonucunu açıklar mısın:\n\`\`\`sql\n${state.lastSql}\n\`\`\``;
        inp.value = prefix;
        inp.focus();
        // textarea ise yüksekliği güncellesin
        try { inp.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
        statusEl.classList.remove('qb-status-error');
        statusEl.textContent = 'SQL sohbet kutusuna kopyalandı — göndermek için Enter\'a basın.';
        if (window.showToast) window.showToast('SQL sohbet kutusuna yapıştırıldı', 'info');
        _announce(root, 'SQL sohbet kutusuna kopyalandı');
    }

    function _escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _renderResultTable(cols, rows) {
        if (!rows || !rows.length) {
            return '<div class="qb-result-empty">Sonuç boş.</div>';
        }
        const colList = (cols && cols.length) ? cols : Object.keys(rows[0] || {});
        let html = '<div class="qb-result-table-wrap"><table class="qb-result-table"><thead><tr>';
        for (const c of colList) html += `<th>${_escHtml(c)}</th>`;
        html += '</tr></thead><tbody>';
        for (const r of rows) {
            html += '<tr>';
            for (const c of colList) {
                const v = r && typeof r === 'object' ? r[c] : null;
                const txt = v == null ? '' : String(v);
                const trunc = txt.length > 120 ? txt.slice(0, 117) + '…' : txt;
                html += `<td title="${_escHtml(txt)}">${_escHtml(trunc)}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';
        return html;
    }

    function open(opts) {
        if (!opts || !opts.parentEl || !opts.table) {
            console.warn('[query_builder] parentEl ve table zorunlu');
            return null;
        }

        // Tekil aktif builder — eskiyi kapat
        if (_activeRoot && _activeRoot.parentNode) {
            _activeRoot.parentNode.removeChild(_activeRoot);
        }

        const state = {
            sourceId: opts.sourceId,
            schema: opts.schema || null,
            table: opts.table,
            dialect: opts.dialect || null,
            columns: Array.isArray(opts.columns) ? opts.columns.filter(c => c && c.name) : [],
            selected: [],
            filters: [],
            orderColumn: '',
            orderDir: 'ASC',
            limit: 100,
            onSqlReady: opts.onSqlReady,
        };

        const titleId = `qb-title-${Date.now()}`;

        const root = _el('section', {
            class: 'qb-card',
            role: 'application',
            'aria-labelledby': titleId,
            'aria-roledescription': 'sorgu inşa aracı',
        });

        // Header
        const header = _el('header', { class: 'qb-header' });
        header.appendChild(_el('h3', {
            id: titleId,
            class: 'qb-title',
            text: `Query Builder — ${opts.schema ? opts.schema + '.' : ''}${opts.table}`,
        }));
        const closeBtn = _el('button', {
            type: 'button',
            class: 'qb-close',
            'aria-label': 'Kapat',
            title: 'Kapat (Esc)',
            text: '×',
        });
        closeBtn.addEventListener('click', close);
        header.appendChild(closeBtn);
        root.appendChild(header);

        // Available columns
        const availSection = _el('div', { class: 'qb-section qb-available-section' });
        availSection.appendChild(_el('h4', { class: 'qb-section-title', text: 'Kolonlar' }));
        availSection.appendChild(_el('p', {
            class: 'qb-section-hint',
            text: 'Tıklayın veya seçildi paneline sürükleyin.',
        }));
        const availList = _el('div', {
            class: 'qb-col-list',
            role: 'list',
            'aria-label': 'Mevcut kolonlar',
        });
        state.columns.forEach(c => availList.appendChild(_renderAvailableColumn(c, state, root)));
        if (state.columns.length === 0) {
            availList.appendChild(_el('span', {
                class: 'qb-empty-inline',
                text: 'Bu tabloda kolon bilgisi yok.',
            }));
        }
        availSection.appendChild(availList);
        root.appendChild(availSection);

        // Selected (drag target)
        const selSection = _el('div', { class: 'qb-section qb-selected-section' });
        selSection.appendChild(_el('h4', { class: 'qb-section-title', text: 'Seçilen kolonlar (sıra korunur)' }));
        const selList = _el('ol', {
            class: 'qb-selected-list',
            role: 'list',
            'aria-label': 'Seçilen kolonlar — Ok tuşları ile sıralayın, Delete ile kaldırın',
        });
        selSection.appendChild(selList);

        // Drop zone behaviour
        selList.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
            selList.classList.add('qb-drop-active');
        });
        selList.addEventListener('dragleave', () => selList.classList.remove('qb-drop-active'));
        selList.addEventListener('drop', (e) => {
            e.preventDefault();
            selList.classList.remove('qb-drop-active');
            const col = e.dataTransfer.getData('text/plain');
            if (col && !state.selected.includes(col)) {
                state.selected.push(col);
                _renderSelected(state, root);
                _announce(root, `${col} eklendi`);
            }
        });
        root.appendChild(selSection);

        // Filters
        const filterSection = _el('div', { class: 'qb-section qb-filter-section' });
        filterSection.appendChild(_el('h4', { class: 'qb-section-title', text: 'Filtreler (WHERE)' }));
        const filtersList = _el('div', { class: 'qb-filters-list' });
        filterSection.appendChild(filtersList);
        const addFilterBtn = _el('button', {
            type: 'button',
            class: 'qb-add-filter',
            text: '+ Filtre ekle',
        });
        addFilterBtn.addEventListener('click', () => {
            state.filters.push({ column: '', op: '=', value: '' });
            _renderFilters(state, root);
        });
        filterSection.appendChild(addFilterBtn);
        root.appendChild(filterSection);

        // Order/Limit
        const orderSection = _el('div', { class: 'qb-section qb-order-section' });
        orderSection.appendChild(_el('h4', { class: 'qb-section-title', text: 'Sıralama & Limit' }));
        const orderRow = _el('div', { class: 'qb-order-row' });

        const orderColSel = _el('select', { class: 'qb-order-col', 'aria-label': 'Sırala' });
        orderColSel.appendChild(_el('option', { value: '', text: '— sıra yok —' }));
        state.columns.forEach(c => orderColSel.appendChild(_el('option', { value: c.name, text: c.name })));
        orderColSel.addEventListener('change', () => { state.orderColumn = orderColSel.value; });

        const dirSel = _el('select', { class: 'qb-order-dir', 'aria-label': 'Yön' });
        ['ASC', 'DESC'].forEach(d => dirSel.appendChild(_el('option', { value: d, text: d })));
        dirSel.addEventListener('change', () => { state.orderDir = dirSel.value; });

        const limitInput = _el('input', {
            type: 'number',
            class: 'qb-limit',
            'aria-label': 'Limit',
            min: '1',
            max: '10000',
            value: '100',
        });
        limitInput.addEventListener('input', () => { state.limit = Number(limitInput.value) || 100; });

        orderRow.appendChild(orderColSel);
        orderRow.appendChild(dirSel);
        orderRow.appendChild(_el('label', { class: 'qb-limit-label', text: 'Limit:' }));
        orderRow.appendChild(limitInput);
        orderSection.appendChild(orderRow);
        root.appendChild(orderSection);

        // Action bar
        const actions = _el('div', { class: 'qb-actions' });
        const previewBtn = _el('button', {
            type: 'button',
            class: 'qb-preview-btn',
            text: 'SQL Önizle',
            'data-tooltip': 'Parametrize SELECT SQL üretir (yürütmez)',
        });
        previewBtn.addEventListener('click', () => _fetchPreview(state, root));
        actions.appendChild(previewBtn);

        // v3.32.0: Kopyala
        const copyBtn = _el('button', {
            type: 'button',
            class: 'qb-copy-btn',
            text: '📋 Kopyala',
            disabled: 'true',
            'aria-label': 'SQL\'i panoya kopyala',
            'data-tooltip': 'Üretilen SQL\'i panoya kopyalar (dış DB tool için)',
        });
        copyBtn.addEventListener('click', () => _copySql(state, root));
        actions.appendChild(copyBtn);

        // v3.32.0: Çalıştır
        const execBtn = _el('button', {
            type: 'button',
            class: 'qb-exec-btn',
            text: '▶️ Çalıştır',
            disabled: 'true',
            'aria-label': 'SQL\'i veritabanında çalıştır',
            'data-tooltip': '5sn timeout, 100 satır cap ile yürütür',
        });
        execBtn.addEventListener('click', () => _executeSql(state, root));
        actions.appendChild(execBtn);

        // v3.32.0: Asistana Gönder
        const sendBtn = _el('button', {
            type: 'button',
            class: 'qb-send-btn',
            text: '💬 Asistana Gönder',
            disabled: 'true',
            'aria-label': 'SQL\'i sohbet kutusuna gönder',
            'data-tooltip': 'SQL\'i sohbet kutusuna yapıştırır — manuel gönderirsin',
        });
        sendBtn.addEventListener('click', () => _sendSqlToChat(state, root));
        actions.appendChild(sendBtn);

        root.appendChild(actions);

        // SQL output
        const sqlSection = _el('div', { class: 'qb-section qb-sql-section' });
        sqlSection.appendChild(_el('h4', { class: 'qb-section-title', text: 'Üretilen SQL' }));
        const sqlBox = _el('pre', {
            class: 'qb-sql-output',
            tabindex: '0',
            'aria-label': 'Üretilen SQL (parametrize)',
        });
        sqlSection.appendChild(sqlBox);
        root.appendChild(sqlSection);

        // v3.32.0: Execute sonucu (gizli, dolduğunda görünür)
        const resultSection = _el('div', {
            class: 'qb-section qb-result-section',
            hidden: 'hidden',
            'aria-label': 'SQL çalıştırma sonucu',
        });
        resultSection.appendChild(_el('h4', { class: 'qb-section-title', text: 'Sonuç' }));
        resultSection.appendChild(_el('div', { class: 'qb-result-meta', role: 'status', 'aria-live': 'polite' }));
        resultSection.appendChild(_el('div', { class: 'qb-result-body' }));
        root.appendChild(resultSection);

        // Live region + status
        root.appendChild(_el('div', {
            class: 'qb-live',
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
        }));
        root.appendChild(_el('div', { class: 'qb-status', role: 'status', 'aria-live': 'polite' }));

        // Mount
        opts.parentEl.appendChild(root);
        _activeRoot = root;
        _renderSelected(state, root);

        // Global keyboard: Esc → close
        const escHandler = (e) => {
            if (e.key === 'Escape' && _activeRoot === root) {
                close();
            }
        };
        root.addEventListener('keydown', escHandler);

        // Focus first chip for keyboard users
        setTimeout(() => {
            const firstChip = root.querySelector('.qb-col-chip');
            if (firstChip) firstChip.focus();
        }, 50);

        return { root, state };
    }

    function close() {
        if (_activeRoot && _activeRoot.parentNode) {
            _activeRoot.parentNode.removeChild(_activeRoot);
        }
        _activeRoot = null;
    }

    window.QueryBuilder = { open, close };
})();
