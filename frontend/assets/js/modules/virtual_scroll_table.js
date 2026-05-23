/**
 * VYRA — Virtual Scroll Table (Faz 6, v3.30.0)
 * ==============================================
 * Büyük DB sorgu sonuçları (>200 satır) için virtual scroll.
 * Sadece görünen satırları + tampon DOM'a yazar; scroll'da günceller.
 *
 * Entegrasyon: renderSQLResultTable büyük sonuçlarda bu modüle delege eder.
 * DBTableUI drag-drop + kolon visibility ile uyumlu.
 *
 * Kullanım:
 *   const el = VirtualScrollTable.create(columns, rows, meta);
 *   container.appendChild(el);
 */
window.VirtualScrollTable = (function () {
    'use strict';

    var ROW_HEIGHT  = 32;   // px — her satır sabit yükseklik
    var BUFFER      = 20;   // viewport üstü/altı ekstra satır
    var THRESHOLD   = 200;  // bu satır sayısının altında normal render

    var escapeHtml = window.DialogChatUtils
        ? window.DialogChatUtils.escapeHtml
        : function (s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; };

    // ── helpers ──────────────────────────────────────────────────────────

    function _colAttr(col) {
        return escapeHtml(col).replace(/"/g, '&quot;');
    }

    function _cellHtml(val) {
        if (val === null || val === undefined) return '<span class="null-val">\u2014</span>';
        return escapeHtml(String(val));
    }

    // ── public: create ──────────────────────────────────────────────────

    /**
     * Virtual scroll tablolu bir DOM element döner.
     * @param {string[]} columns
     * @param {Object[]} rows
     * @param {Object}   meta  - {row_count, rows_shown, source_db}
     * @returns {HTMLElement}
     */
    function create(columns, rows, meta) {
        var rowCount  = (meta && meta.row_count)  || rows.length;
        var rowsShown = (meta && meta.rows_shown)  || rows.length;
        var sourceDb  = (meta && meta.source_db)   || '';
        var truncated = rowCount > rowsShown;

        var tableId = 'dbtbl_' + Date.now().toString(36) + '_' + Math.floor(Math.random() * 1e6).toString(36);

        // Outer wrapper
        var wrap = document.createElement('div');
        wrap.className = 'db-result-table-wrap';
        wrap.setAttribute('data-table-id', tableId);
        wrap.setAttribute('data-virtual', 'true');

        // Meta bar
        var metaBar = document.createElement('div');
        metaBar.className = 'db-result-meta';
        var metaHtml = '';
        if (sourceDb) metaHtml += '<span class="db-result-db">\uD83D\uDDC4\uFE0F ' + escapeHtml(sourceDb) + '</span>';
        metaHtml += '<span class="db-result-count">\uD83D\uDCCA ' + rowsShown + ' kay\u0131t';
        if (truncated) metaHtml += ' <span class="db-truncated-badge">(toplam ' + rowCount + ')</span>';
        metaHtml += '</span>';
        metaHtml += '<span class="db-vs-badge" title="Virtual scroll aktif">\u26A1 VS</span>';
        metaHtml += '<button type="button" class="db-cols-btn" onclick="window.DBTableUI.toggleColMenu(\'' + tableId + '\', event)" title="Kolonlar\u0131 g\u00f6ster/gizle ve s\u00fcr\u00fckleyerek yeniden s\u0131rala">\u2699\uFE0F Kolonlar</button>';
        metaBar.innerHTML = metaHtml;
        wrap.appendChild(metaBar);

        // Column menu (hidden)
        var colMenu = document.createElement('div');
        colMenu.className = 'db-cols-menu';
        colMenu.id = tableId + '_menu';
        colMenu.hidden = true;
        var menuHtml = '<div class="db-cols-menu-head"><span>G\u00f6r\u00fcn\u00fcr kolonlar</span>'
            + '<button type="button" class="db-cols-menu-close" onclick="window.DBTableUI.toggleColMenu(\'' + tableId + '\')" aria-label="Kapat">\u00d7</button></div>'
            + '<div class="db-cols-menu-actions">'
            + '<button type="button" class="db-cols-mini" onclick="window.DBTableUI.allCols(\'' + tableId + '\', true)">T\u00fcm\u00fcn\u00fc g\u00f6ster</button>'
            + '<button type="button" class="db-cols-mini" onclick="window.DBTableUI.allCols(\'' + tableId + '\', false)">T\u00fcm\u00fcn\u00fc gizle</button>'
            + '</div><div class="db-cols-menu-list">';
        columns.forEach(function (col) {
            var safeCol = escapeHtml(col);
            var ca = _colAttr(col);
            menuHtml += '<label class="db-col-item"><input type="checkbox" checked data-col="' + ca
                + '" onchange="window.DBTableUI.toggleCol(\'' + tableId + '\', this.dataset.col, this.checked)"><span>' + safeCol + '</span></label>';
        });
        menuHtml += '</div>';
        colMenu.innerHTML = menuHtml;
        wrap.appendChild(colMenu);

        // Scroll viewport
        var viewport = document.createElement('div');
        viewport.className = 'db-vs-viewport';
        viewport.style.maxHeight = '480px';
        viewport.style.overflowY = 'auto';
        viewport.style.position  = 'relative';
        viewport.setAttribute('role', 'grid');
        viewport.setAttribute('aria-label', 'Sorgu sonu\u00e7lar\u0131 — virtual scroll');

        // Spacer (total height)
        var totalHeight = rows.length * ROW_HEIGHT;
        var spacer = document.createElement('div');
        spacer.className = 'db-vs-spacer';
        spacer.style.height = totalHeight + 'px';
        spacer.style.position = 'relative';

        // Table (fixed header outside scroll)
        var headerTable = document.createElement('table');
        headerTable.className = 'db-result-table db-vs-header';
        headerTable.setAttribute('data-table-id', tableId);
        var thead = document.createElement('thead');
        var headerRow = document.createElement('tr');
        columns.forEach(function (col) {
            var th = document.createElement('th');
            th.setAttribute('draggable', 'true');
            th.setAttribute('data-col', _colAttr(col));
            th.setAttribute('ondragstart', 'window.DBTableUI.onDragStart(event)');
            th.setAttribute('ondragover', 'window.DBTableUI.onDragOver(event)');
            th.setAttribute('ondragenter', 'window.DBTableUI.onDragEnter(event)');
            th.setAttribute('ondragleave', 'window.DBTableUI.onDragLeave(event)');
            th.setAttribute('ondrop', 'window.DBTableUI.onDrop(event)');
            th.setAttribute('ondragend', 'window.DBTableUI.onDragEnd(event)');
            th.innerHTML = '<span class="th-grip" aria-hidden="true">\u22EE\u22EE</span><span class="th-label">' + escapeHtml(col) + '</span>';
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        headerTable.appendChild(thead);

        // Body container (inside spacer)
        var bodyContainer = document.createElement('div');
        bodyContainer.className = 'db-vs-body';
        bodyContainer.style.position = 'absolute';
        bodyContainer.style.left = '0';
        bodyContainer.style.right = '0';

        spacer.appendChild(bodyContainer);

        // Scroll wrapper for header + viewport
        var scrollWrap = document.createElement('div');
        scrollWrap.className = 'db-table-scroll';
        scrollWrap.appendChild(headerTable);
        viewport.appendChild(spacer);
        scrollWrap.appendChild(viewport);
        wrap.appendChild(scrollWrap);

        // State object
        var state = {
            tableId:   tableId,
            columns:   columns,
            rows:      rows,
            viewport:  viewport,
            body:      bodyContainer,
            spacer:    spacer,
            lastStart: -1,
            lastEnd:   -1,
            rafId:     0
        };

        // Initial render
        _renderSlice(state);

        // Scroll handler (throttled via rAF) — named for cleanup
        var scrollHandler = function () {
            if (state.rafId) return;
            state.rafId = requestAnimationFrame(function () {
                state.rafId = 0;
                _renderSlice(state);
            });
        };
        viewport.addEventListener('scroll', scrollHandler);

        // Cleanup: MutationObserver detects DOM removal → detach listener + cancel rAF
        if (typeof MutationObserver !== 'undefined') {
            var obs = new MutationObserver(function (mutations) {
                for (var m = 0; m < mutations.length; m++) {
                    for (var r = 0; r < mutations[m].removedNodes.length; r++) {
                        var removed = mutations[m].removedNodes[r];
                        if (removed === wrap || (removed.contains && removed.contains(wrap))) {
                            viewport.removeEventListener('scroll', scrollHandler);
                            if (state.rafId) cancelAnimationFrame(state.rafId);
                            state.rows = null; // release data reference
                            obs.disconnect();
                            return;
                        }
                    }
                }
            });
            // Observe closest scrollable ancestor or body
            var observeTarget = wrap.parentNode || document.body;
            requestAnimationFrame(function () {
                observeTarget = wrap.parentNode || document.body;
                obs.observe(observeTarget, { childList: true, subtree: true });
            });
        }

        // Truncated note
        if (truncated) {
            var note = document.createElement('div');
            note.className = 'db-truncated-note';
            note.textContent = '\u26A0\uFE0F Toplam ' + rowCount + ' kay\u0131ttan ilk ' + rowsShown + ' tanesi g\u00f6steriliyor. T\u00fcm\u00fcn\u00fc g\u00f6rmek i\u00e7in Excel\'e aktar\u0131n.';
            wrap.appendChild(note);
        }

        return wrap;
    }

    // ── internal: render visible slice ──────────────────────────────────

    function _renderSlice(state) {
        var scrollTop    = state.viewport.scrollTop;
        var viewHeight   = state.viewport.clientHeight;
        var totalRows    = state.rows.length;
        var cols         = state.columns;

        var startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER);
        var endIdx   = Math.min(totalRows, Math.ceil((scrollTop + viewHeight) / ROW_HEIGHT) + BUFFER);

        // Skip re-render if range unchanged
        if (startIdx === state.lastStart && endIdx === state.lastEnd) return;
        state.lastStart = startIdx;
        state.lastEnd   = endIdx;

        // Position body container
        state.body.style.top = (startIdx * ROW_HEIGHT) + 'px';

        // Build rows HTML
        var html = '<table class="db-result-table db-vs-rows" data-table-id="' + state.tableId + '">';
        html += '<tbody>';
        for (var i = startIdx; i < endIdx; i++) {
            var row = state.rows[i];
            var cls = i % 2 === 0 ? '' : ' class="alt-row"';
            html += '<tr' + cls + ' data-row-idx="' + i + '">';
            for (var c = 0; c < cols.length; c++) {
                var col = cols[c];
                var ca  = _colAttr(col);
                html += '<td data-col="' + ca + '">' + _cellHtml(row[col]) + '</td>';
            }
            html += '</tr>';
        }
        html += '</tbody></table>';

        state.body.innerHTML = html;
    }

    // ── public API ──────────────────────────────────────────────────────

    return {
        create:    create,
        THRESHOLD: THRESHOLD
    };
})();
