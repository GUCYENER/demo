/**
 * VYRA Akıllı Veri Keşfi — Grafik Popup (v3.36.0 F11)
 * =============================================================
 * Council: DIONYSOS (chart UX) + HEBE (a11y/modal gate) + HERMES (i18n)
 *
 * API:
 *   window.DbSmartChart.open({ columns, rows, suggestedType? }) → opens modal
 *   window.DbSmartChart.close()                                  → closes + destroys chart
 *
 * Veri kontratı:
 *   columns: Array<string>           — kolon adları (sıralı)
 *   rows   : Array<Array<any>>       — satırlar (kolon index'lerine göre)
 *
 * Heuristic (öneri tipi seçimi):
 *   0 satır                                                  → empty (uyarı)
 *   2 kolon + ilk text + ikinci numeric + distinct≤6         → pie
 *   2 kolon + ilk date/datetime + ikinci numeric             → line
 *   2 kolon + ilk text + ikinci numeric                      → bar
 *   >2 kolon + 2..n numeric                                  → multi-series bar
 *   Hiçbiri uymazsa                                          → unsupported
 *
 * Dependency: window.Chart (Chart.js UMD bundle'a dahil — build.mjs)
 *
 * NOT: Bu modül UMD bundle'a IIFE olarak dahil edilir; ES module import yok.
 * Wizard.js'ten window.DbSmartChart.open(...) ile çağrılır.
 */
(function () {
    'use strict';

    // Tailwind-benzeri palette — kontrastlı 8 renk.
    const PALETTE = [
        '#4D99FF', // accent blue
        '#7C3AED', // purple
        '#34D399', // green
        '#FBBF24', // amber
        '#F87171', // red
        '#22D3EE', // cyan
        '#F472B6', // pink
        '#A78BFA', // violet-light
    ];
    const PALETTE_ALPHA = PALETTE.map(c => _hexToRgba(c, 0.55));

    const TYPE_LABELS = {
        bar:      'Bar',
        line:     'Çizgi',
        area:     'Alan',
        pie:      'Pasta',
        doughnut: 'Halka',
    };

    let _modalEl = null;
    let _chartInstance = null;
    let _lastData = null;        // { columns, rows } — type değişiminde re-render için
    let _lastFocusEl = null;     // return-focus

    // ============================================================
    // Public API
    // ============================================================
    function open(payload) {
        const data = _normalize(payload);
        if (!data) {
            _toast('Grafik için veri yok.', 'warning');
            return;
        }
        _lastData = data;
        _lastFocusEl = document.activeElement;

        _ensureModal();
        _modalEl.classList.remove('hidden');
        _modalEl.removeAttribute('hidden');
        document.body.style.overflow = 'hidden';

        // Type select reset → inferred type'a göre.
        const select = _modalEl.querySelector('#dswChartType');
        const inferred = (payload && payload.suggestedType) || _inferType(data.columns, data.rows);
        if (inferred === 'empty' || inferred === 'unsupported') {
            _renderFallback(inferred);
            return;
        }
        if (select) {
            select.value = inferred;
        }
        _renderChart(inferred, data.columns, data.rows);

        // Focus close button for a11y.
        setTimeout(function () {
            const closeBtn = _modalEl.querySelector('.dsw-chart-modal__close');
            if (closeBtn) closeBtn.focus();
        }, 0);
    }

    function close() {
        if (!_modalEl) return;
        if (_chartInstance) {
            try { _chartInstance.destroy(); } catch (e) { /* ignore */ }
            _chartInstance = null;
        }
        _modalEl.classList.add('hidden');
        _modalEl.setAttribute('hidden', '');
        document.body.style.overflow = '';
        if (_lastFocusEl && typeof _lastFocusEl.focus === 'function') {
            try { _lastFocusEl.focus(); } catch (e) { /* ignore */ }
        }
        _lastFocusEl = null;
    }

    // ============================================================
    // Modal scaffold (lazy mount)
    // ============================================================
    function _ensureModal() {
        if (_modalEl) return;
        const root = document.createElement('div');
        root.className = 'dsw-chart-modal hidden';
        root.setAttribute('hidden', '');
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        root.setAttribute('aria-labelledby', 'dswChartTitle');

        const typeOptions = Object.keys(TYPE_LABELS).map(function (k) {
            return '<option value="' + k + '">' + TYPE_LABELS[k] + '</option>';
        }).join('');

        root.innerHTML =
            '<div class="dsw-chart-modal__backdrop" data-action="close"></div>' +
            '<div class="dsw-chart-modal__dialog" role="document">' +
                '<header class="dsw-chart-modal__header">' +
                    '<h3 class="dsw-chart-modal__title" id="dswChartTitle">Grafik Önizleme</h3>' +
                    '<button type="button" class="dsw-chart-modal__close" aria-label="Kapat" data-action="close">×</button>' +
                '</header>' +
                '<div class="dsw-chart-modal__toolbar">' +
                    '<label for="dswChartType" class="dsw-chart-modal__type-label">Grafik tipi</label>' +
                    '<select id="dswChartType" class="dsw-chart-modal__type-select">' +
                        typeOptions +
                    '</select>' +
                '</div>' +
                '<div class="dsw-chart-modal__canvas-wrap">' +
                    '<canvas id="dswChartCanvas" aria-label="Grafik önizleme"></canvas>' +
                '</div>' +
                '<div class="dsw-chart-modal__fallback" hidden></div>' +
                '<footer class="dsw-chart-modal__footer">' +
                    '<button type="button" class="dsw-chart-modal__btn" data-action="close">Kapat</button>' +
                '</footer>' +
            '</div>';

        document.body.appendChild(root);
        _modalEl = root;

        // Event delegation: close buttons + backdrop.
        root.addEventListener('click', function (e) {
            const t = e.target;
            if (t && t.dataset && t.dataset.action === 'close') {
                close();
            }
        });
        // Esc to close.
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && _modalEl && !_modalEl.hasAttribute('hidden')) {
                e.preventDefault();
                close();
            }
        });
        // Type select → re-render same data with new type.
        const select = root.querySelector('#dswChartType');
        if (select) {
            select.addEventListener('change', function () {
                if (!_lastData) return;
                _renderChart(select.value, _lastData.columns, _lastData.rows);
            });
        }
    }

    // ============================================================
    // Data normalization
    // ============================================================
    function _normalize(payload) {
        if (!payload || !Array.isArray(payload.columns) || !Array.isArray(payload.rows)) {
            return null;
        }
        // Defensive: rows shape may be array-of-arrays OR array-of-objects.
        const cols = payload.columns.slice();
        let rows = payload.rows;
        if (rows.length && !Array.isArray(rows[0]) && typeof rows[0] === 'object') {
            // Object rows → align by column name.
            rows = rows.map(function (r) {
                return cols.map(function (c) { return r[c]; });
            });
        }
        return { columns: cols, rows: rows };
    }

    // ============================================================
    // Heuristic
    // ============================================================
    function _inferType(columns, rows) {
        if (!rows || rows.length === 0) return 'empty';
        if (!columns || columns.length < 2) return 'unsupported';

        // İlk kolon kategori, geri kalanlar numeric kontrol.
        const firstCol = rows.map(function (r) { return r[0]; });
        const firstIsDate = firstCol.every(_looksLikeDate);
        const firstIsText = firstCol.every(_looksLikeTextOrEmpty);
        const numericCols = [];
        for (let i = 1; i < columns.length; i++) {
            const colVals = rows.map(function (r) { return r[i]; });
            if (colVals.every(_looksLikeNumeric)) numericCols.push(i);
        }
        if (numericCols.length === 0) return 'unsupported';

        // 2 kolon senaryolari
        if (columns.length === 2 && numericCols.length === 1) {
            if (firstIsDate) return 'line';
            if (firstIsText) {
                const distinct = new Set(firstCol.map(String));
                if (distinct.size <= 6) return 'pie';
                return 'bar';
            }
            return 'bar';
        }
        // 3+ kolon — multi-series bar
        if (columns.length > 2 && numericCols.length >= 2) {
            return firstIsDate ? 'line' : 'bar';
        }
        // Fallback: tek numeric kolon → bar
        if (numericCols.length === 1) return 'bar';
        return 'unsupported';
    }

    function _looksLikeNumeric(v) {
        if (v === null || v === undefined || v === '') return true; // null sayılır (placeholder 0)
        if (typeof v === 'number') return isFinite(v);
        const n = parseFloat(v);
        return !isNaN(n) && isFinite(n);
    }
    function _looksLikeDate(v) {
        if (v == null || v === '') return false;
        if (v instanceof Date) return true;
        const s = String(v).trim();
        if (!s) return false;
        // v3.36.1 F11b — broadened date detection so Oracle/MSSQL/TR/US
        // default formats select 'line' chart instead of falling back to 'bar'.
        //   1) ISO 8601 / YYYY-MM-DD / YYYY/MM/DD  (e.g. 2026-05-24, 2026/05/24T12:00)
        //   2) Oracle DD-MON-YY(YY)                (e.g. 15-MAR-26, 15-MAR-2026, 15/Mar/2026)
        //   3) US MM/DD/YYYY                       (e.g. 03/15/2026)
        //   4) TR/EU DD.MM.YYYY                    (e.g. 15.03.2026)
        //   5) ISO-ish DD-MM-YYYY                  (e.g. 15-03-2026)
        if (/^\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(s)) return true;          // 1
        if (/^\d{1,2}[-/\s][A-Za-z]{3,9}[-/\s]\d{2,4}$/.test(s)) return true; // 2
        if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s)) return true;             // 3
        if (/^\d{1,2}\.\d{1,2}\.\d{4}$/.test(s)) return true;             // 4
        if (/^\d{1,2}-\d{1,2}-\d{4}$/.test(s)) return true;               // 5
        return false;
    }
    function _looksLikeTextOrEmpty(v) {
        if (v == null) return true;
        if (typeof v === 'number') return false;
        const n = parseFloat(v);
        if (!isNaN(n) && isFinite(n) && String(v).trim() !== '') return false;
        return true;
    }
    function _coerceNumber(v) {
        if (v == null || v === '') return 0;
        if (typeof v === 'number') return v;
        const n = parseFloat(v);
        return isNaN(n) ? 0 : n;
    }

    // ============================================================
    // Render
    // ============================================================
    function _renderFallback(kind) {
        const wrap = _modalEl.querySelector('.dsw-chart-modal__canvas-wrap');
        const fb = _modalEl.querySelector('.dsw-chart-modal__fallback');
        if (wrap) wrap.style.display = 'none';
        if (fb) {
            fb.hidden = false;
            fb.textContent = (kind === 'empty')
                ? 'Grafik için veri yok.'
                : 'Bu veri seti grafik gösterimi için uygun değil. Lütfen tablo görünümünü kullanın.';
        }
    }

    function _renderChart(type, columns, rows) {
        if (typeof window.Chart === 'undefined') {
            console.warn('[db_smart_chart] Chart.js yüklü değil');
            _renderFallback('unsupported');
            return;
        }
        const wrap = _modalEl.querySelector('.dsw-chart-modal__canvas-wrap');
        const fb = _modalEl.querySelector('.dsw-chart-modal__fallback');
        if (wrap) wrap.style.display = '';
        if (fb) { fb.hidden = true; fb.textContent = ''; }

        const canvas = _modalEl.querySelector('#dswChartCanvas');
        if (!canvas) return;
        if (_chartInstance) {
            try { _chartInstance.destroy(); } catch (e) { /* ignore */ }
            _chartInstance = null;
        }

        const labels = rows.map(function (r) { return String(r[0] == null ? '' : r[0]); });

        // Numeric kolonları otomatik tespit et — series.
        const numericIdx = [];
        for (let i = 1; i < columns.length; i++) {
            if (rows.every(function (r) { return _looksLikeNumeric(r[i]); })) numericIdx.push(i);
        }
        if (numericIdx.length === 0) {
            _renderFallback('unsupported');
            return;
        }

        let chartType = type;
        let isArea = false;
        if (type === 'area') {
            chartType = 'line';
            isArea = true;
        }

        let datasets;
        if (chartType === 'pie' || chartType === 'doughnut') {
            // Tek series — ilk numeric kolon. Her satır kendi rengini alır.
            const idx = numericIdx[0];
            const values = rows.map(function (r) { return _coerceNumber(r[idx]); });
            datasets = [{
                label: columns[idx],
                data: values,
                backgroundColor: values.map(function (_, i) { return PALETTE[i % PALETTE.length]; }),
                borderColor: '#0d0f14',
                borderWidth: 1,
            }];
        } else {
            datasets = numericIdx.map(function (cIdx, sIdx) {
                const color = PALETTE[sIdx % PALETTE.length];
                const alpha = PALETTE_ALPHA[sIdx % PALETTE_ALPHA.length];
                return {
                    label: columns[cIdx],
                    data: rows.map(function (r) { return _coerceNumber(r[cIdx]); }),
                    backgroundColor: (chartType === 'line' && !isArea) ? color : alpha,
                    borderColor: color,
                    borderWidth: 2,
                    fill: isArea ? true : false,
                    tension: chartType === 'line' ? 0.25 : 0,
                    pointRadius: chartType === 'line' ? 3 : 0,
                };
            });
        }

        const config = {
            type: chartType,
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: (chartType === 'pie' || chartType === 'doughnut' || datasets.length > 1),
                        labels: { color: _cssVar('--text-1', '#F1F5FF') },
                    },
                    tooltip: {
                        backgroundColor: 'rgba(13,15,20,0.92)',
                        borderColor: 'rgba(255,255,255,0.12)',
                        borderWidth: 1,
                    },
                },
                scales: (chartType === 'pie' || chartType === 'doughnut') ? {} : {
                    x: {
                        ticks: { color: _cssVar('--text-2', '#9DAAC4'), maxRotation: 45, autoSkip: true },
                        grid:  { color: 'rgba(255,255,255,0.06)' },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { color: _cssVar('--text-2', '#9DAAC4') },
                        grid:  { color: 'rgba(255,255,255,0.06)' },
                    },
                },
            },
        };

        try {
            _chartInstance = new window.Chart(canvas, config);
        } catch (e) {
            console.warn('[db_smart_chart] render fail:', e);
            _renderFallback('unsupported');
        }
    }

    // ============================================================
    // Helpers
    // ============================================================
    function _hexToRgba(hex, alpha) {
        const h = hex.replace('#', '');
        const r = parseInt(h.substring(0, 2), 16);
        const g = parseInt(h.substring(2, 4), 16);
        const b = parseInt(h.substring(4, 6), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    function _cssVar(name, fallback) {
        try {
            const v = getComputedStyle(document.documentElement).getPropertyValue(name);
            return (v && v.trim()) || fallback;
        } catch (e) {
            return fallback;
        }
    }

    function _toast(msg, kind) {
        if (window.showToast) {
            try { window.showToast(msg, kind || 'info'); return; } catch (e) { /* fallthrough */ }
        }
        // console fallback
        console.log('[db_smart_chart] ' + msg);
    }

    // ============================================================
    // Expose
    // ============================================================
    window.DbSmartChart = {
        open: open,
        close: close,
    };
})();
