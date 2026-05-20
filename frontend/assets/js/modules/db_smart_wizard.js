/**
 * VYRA Akıllı Veri Keşfi — DB Smart Wizard (v3.30.0 FAZ 1 G1.6)
 * =============================================================
 * 5-adım sihirbaz iskelet:
 *   1) Tablo Seç (eligibility hybrid search)
 *   2) İlişkiler (fk_graph subgraph)
 *   3) Metrik (library + custom)
 *   4) Filtre (column-aware)
 *   5) Önizleme (SQL + cost)
 *
 * Backend: /api/db-smart/* (12 endpoint)
 * HEBE 5c gate: feature_key 'aki_kesif' guard'ı feature_permissions_module.js'te.
 *
 * NOT: FAZ 1'de wizard sequential FSM ile yönetilir; LangGraph kullanımı FAZ 2.
 */
(function () {
    'use strict';

    const API_BASE = '/api/db-smart';
    const TOTAL_STEPS = 5;
    let _state = {
        sessionUid: null,
        currentStep: 0,
        sourceId: null,
        selectedTableId: null,
        selectedTableObjectName: null,   // P4 fix: actual SQL identifier
        selectedTableSchema: null,        // P4 fix: schema for base_table
        selectedTableLabel: null,         // display only — not used in SQL
        selectedTables: [],
        metric: null,
        filters: [],
        _lastFocusEl: null,               // HEBE Gate: return-focus target
    };

    // HEBE Gate helper: announce + toast fallback
    function _notify(msg, kind) {
        if (window.showToast) {
            try { window.showToast(msg, kind || 'info'); return; } catch (e) { /* fallthrough */ }
        }
        // aria-live fallback: write into progress text (polite region)
        const progress = document.getElementById('dswProgress');
        if (progress) progress.textContent = msg;
    }

    function _setBusy(el, busy) {
        if (!el) return;
        el.setAttribute('aria-busy', busy ? 'true' : 'false');
    }

    function _authHeaders() {
        const token = localStorage.getItem('access_token') || '';
        return {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json',
        };
    }

    async function _fetchJson(url, opts) {
        opts = opts || {};
        const headers = Object.assign({}, _authHeaders(), opts.headers || {});
        const res = await fetch(url, Object.assign({}, opts, { headers }));
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(res.status + ': ' + (text || res.statusText));
        }
        return res.json();
    }

    // ============================================
    // Step navigation
    // ============================================

    function _setStep(n) {
        if (n < 0 || n > TOTAL_STEPS - 1) return;
        _state.currentStep = n;
        // Tablist aria sync: selected step gets aria-selected=true + tabindex=0,
        // others get aria-selected=false + tabindex=-1 (roving tabindex pattern).
        document.querySelectorAll('.dsw-step').forEach(el => {
            const s = parseInt(el.dataset.step, 10);
            const active = (s === n);
            el.classList.toggle('active', active);
            el.setAttribute('aria-selected', active ? 'true' : 'false');
            el.setAttribute('tabindex', active ? '0' : '-1');
        });
        document.querySelectorAll('.dsw-step-panel').forEach(el => {
            const s = parseInt(el.dataset.step, 10);
            const hidden = (s !== n);
            el.classList.toggle('hidden', hidden);
            if (hidden) {
                el.setAttribute('hidden', '');
            } else {
                el.removeAttribute('hidden');
            }
        });
        const progress = document.getElementById('dswProgress');
        if (progress) progress.textContent = 'Adım ' + (n + 1) + ' / ' + TOTAL_STEPS;
        const prev = document.getElementById('dswPrevBtn');
        const next = document.getElementById('dswNextBtn');
        if (prev) prev.disabled = (n === 0);
        if (next) next.disabled = (n === TOTAL_STEPS - 1);
        // v3.30.0 P2: adım data fetch (lazy)
        if (typeof _onStepEnter === 'function') _onStepEnter(n);
    }

    async function _ensureSession() {
        if (_state.sessionUid) return _state.sessionUid;
        try {
            const data = await _fetchJson(API_BASE + '/sessions', {
                method: 'POST',
                body: JSON.stringify({ source_id: _state.sourceId || null }),
            });
            _state.sessionUid = data.session_uid;
            return _state.sessionUid;
        } catch (e) {
            console.warn('[db_smart_wizard] create session failed:', e);
            return null;
        }
    }

    // ============================================
    // Step 0 — Eligibility search
    // ============================================

    async function _loadSources() {
        const sel = document.getElementById('dswSourceSelect');
        if (!sel) return;
        try {
            const data = await _fetchJson(API_BASE + '/sources');
            sel.innerHTML = '';
            (data.items || []).forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = (s.name || s.host || ('source-' + s.id)) +
                                  (s.dialect ? ' (' + s.dialect + ')' : '');
                sel.appendChild(opt);
            });
            if (sel.options.length === 0) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = '(Erişilebilir veri kaynağı yok)';
                sel.appendChild(opt);
            }
        } catch (e) {
            console.warn('[db_smart_wizard] _loadSources failed:', e);
        }
    }

    async function _searchTables() {
        const q = (document.getElementById('dswSearchQ') || {}).value || '';
        const sourceId = (document.getElementById('dswSourceSelect') || {}).value || '';
        const results = document.getElementById('dswResults');
        if (!results) return;
        if (!sourceId) {
            results.innerHTML = '<div class="dsw-hint" role="status">Lütfen önce veri kaynağı seçin.</div>';
            _notify('Önce veri kaynağı seçin.', 'warning');
            return;
        }
        _state.sourceId = parseInt(sourceId, 10);
        _setBusy(results, true);
        results.innerHTML = '<div class="dsw-hint" role="status">Aranıyor...</div>';
        try {
            const url = API_BASE + '/sources/' + sourceId + '/tables?q=' +
                        encodeURIComponent(q) + '&limit=10';
            const data = await _fetchJson(url);
            const items = data.tables || data.items || [];
            if (!items.length) {
                results.innerHTML = '<div class="dsw-hint" role="status">Eşleşen tablo bulunamadı.</div>';
                return;
            }
            results.innerHTML = '';
            items.forEach(t => {
                const div = document.createElement('div');
                div.className = 'dsw-result-item';
                div.setAttribute('role', 'option');
                div.setAttribute('tabindex', '0');
                div.setAttribute('aria-selected', 'false');
                const tid = t.table_id || t.id || '';
                const objectName = t.object_name || t.table_name || '';
                const schemaName = t.schema_name || null;
                div.setAttribute('data-table-id', tid);
                div.setAttribute('data-object-name', objectName);
                if (schemaName) div.setAttribute('data-schema-name', schemaName);
                const title = (t.business_name_tr || objectName || '?');
                const meta = (schemaName ? schemaName + '.' : '') + objectName +
                             (t.row_count_estimate ? ' · ~' + t.row_count_estimate + ' satır' : '') +
                             (t.score != null ? ' · skor ' + t.score : '');
                div.setAttribute('aria-label', title + ' — ' + meta);
                div.innerHTML =
                    '<div class="dsw-r-title">' + _escape(title) + '</div>' +
                    '<div class="dsw-r-meta">' + _escape(meta) + '</div>';
                const onPick = () => _selectTable(tid, title, objectName, schemaName);
                div.addEventListener('click', onPick);
                div.addEventListener('keydown', ev => {
                    if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.preventDefault();
                        onPick();
                    }
                });
                results.appendChild(div);
            });
        } catch (e) {
            results.innerHTML = '<div class="dsw-hint" role="status">Hata: ' + _escape(e.message) + '</div>';
            _notify('Tablo araması başarısız: ' + e.message, 'error');
        } finally {
            _setBusy(results, false);
        }
    }

    function _selectTable(tableId, label, objectName, schemaName) {
        _state.selectedTableId = parseInt(tableId, 10);
        _state.selectedTables = [_state.selectedTableId];
        _state.selectedTableLabel = label;
        _state.selectedTableObjectName = objectName || null;
        _state.selectedTableSchema = schemaName || null;
        document.querySelectorAll('.dsw-result-item').forEach(el => {
            const tid = parseInt(el.getAttribute('data-table-id'), 10);
            const sel = (tid === _state.selectedTableId);
            el.style.borderColor = sel ? '#F59E0B' : '';
            el.setAttribute('aria-selected', sel ? 'true' : 'false');
        });
        // İleri butonu aktive et
        const next = document.getElementById('dswNextBtn');
        if (next) next.disabled = false;
        _notify('Seçildi: ' + label, 'success');
    }

    // ============================================
    // Step 1 — Related tables (FK graph)
    // ============================================

    async function _loadRelated() {
        const panel = document.getElementById('dswStep1');
        if (!panel) return;
        if (!_state.selectedTableId || !_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Önce Adım 1\'de bir tablo seçin.</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">FK ilişkileri yükleniyor...</p>';
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/' + _state.selectedTableId + '/related?depth=1';
            const data = await _fetchJson(url);
            const neighbors = data.neighbors || [];
            const junctions = data.junctions || [];
            let html = '<p class="dsw-hint">FK ile bağlı ' + neighbors.length +
                       ' tablo bulundu (' + junctions.length + ' bağlantı tablosu).</p>';
            if (neighbors.length) {
                html += '<div class="dsw-results">';
                neighbors.slice(0, 12).forEach(n => {
                    const label = (n.schema ? n.schema + '.' : '') + n.table;
                    const junc = n.is_junction ? ' · bağlantı tablosu' : '';
                    html += '<div class="dsw-result-item">' +
                            '<div class="dsw-r-title">' + _escape(label) + '</div>' +
                            '<div class="dsw-r-meta">' + n.via_relationship_count +
                            ' ilişki' + junc + '</div></div>';
                });
                html += '</div>';
            }
            panel.innerHTML = html;
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Hata: ' + _escape(e.message) + '</p>';
            _notify('İlişkili tablolar yüklenemedi: ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // ============================================
    // Step 2 — Metric library
    // ============================================

    async function _loadMetrics() {
        const panel = document.getElementById('dswStep2');
        if (!panel) return;
        if (!_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Önce veri kaynağı seçin.</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">Metrik kütüphanesi yükleniyor...</p>';
        try {
            // P4 fix: tablo seçildiyse table_id ekle → backend list_eligible() ile
            // applicable_when filter uygular ve user-pref/usage skor sıralaması döner.
            let url = API_BASE + '/metrics?source_id=' + _state.sourceId;
            if (_state.selectedTableId) {
                url += '&table_id=' + _state.selectedTableId;
            }
            const data = await _fetchJson(url);
            const items = data.items || [];
            if (!items.length) {
                panel.innerHTML = '<p class="dsw-hint">Metrik kütüphanesi boş ' +
                                  '(migration 033 uygulanmamış olabilir).</p>';
                return;
            }
            // Kategoriye göre grupla
            const byCategory = {};
            items.forEach(m => {
                const cat = m.category || 'other';
                (byCategory[cat] = byCategory[cat] || []).push(m);
            });
            let html = '<p class="dsw-hint">' + items.length +
                       ' hazır metrik. Bir metrik seçin veya boş bırakıp özel sorgu yazın.</p>';
            Object.keys(byCategory).sort().forEach(cat => {
                html += '<h4 style="margin:8px 0 4px;font-size:13px;color:var(--text-secondary);text-transform:uppercase">' +
                        _escape(cat) + '</h4><div class="dsw-results">';
                byCategory[cat].forEach(m => {
                    html += '<div class="dsw-result-item" data-metric-key="' +
                            _escape(m.metric_key) + '">' +
                            '<div class="dsw-r-title">' + _escape(m.name_tr || m.metric_key) + '</div>' +
                            '<div class="dsw-r-meta">' + _escape(m.description_tr || '') +
                            ' · ' + _escape(m.default_viz || 'table') + '</div></div>';
                });
                html += '</div>';
            });
            panel.innerHTML = html;
            // Click/keyboard binding + a11y attributes
            panel.querySelectorAll('[data-metric-key]').forEach(el => {
                el.setAttribute('role', 'option');
                el.setAttribute('tabindex', '0');
                el.setAttribute('aria-selected', 'false');
                const pick = () => {
                    const mk = el.getAttribute('data-metric-key');
                    _state.metric = items.find(x => x.metric_key === mk) || null;
                    panel.querySelectorAll('[data-metric-key]').forEach(e2 => {
                        const sel = (e2 === el);
                        e2.style.borderColor = sel ? '#F59E0B' : '';
                        e2.setAttribute('aria-selected', sel ? 'true' : 'false');
                    });
                    if (_state.metric) _notify('Metrik seçildi: ' + (_state.metric.name_tr || _state.metric.metric_key), 'success');
                };
                el.addEventListener('click', pick);
                el.addEventListener('keydown', ev => {
                    if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.preventDefault();
                        pick();
                    }
                });
            });
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Hata: ' + _escape(e.message) + '</p>';
            _notify('Metrik kütüphanesi yüklenemedi: ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // ============================================
    // Step 3 — Filter (columns)
    // ============================================

    async function _loadColumns() {
        const panel = document.getElementById('dswStep3');
        if (!panel) return;
        if (!_state.selectedTableId || !_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Önce tablo seçin.</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">Kolonlar yükleniyor...</p>';
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/' + _state.selectedTableId + '/columns';
            const data = await _fetchJson(url);
            const cols = data.columns || [];
            if (!cols.length) {
                panel.innerHTML = '<p class="dsw-hint">Bu tablo için kolon metadata\'sı bulunamadı.</p>';
                return;
            }
            let html = '<p class="dsw-hint">' + cols.length +
                       ' kolon. Filtre uygulamak için kolon seçin (FAZ 1 P3\'te tam UI).</p>';
            html += '<div class="dsw-results">';
            cols.slice(0, 20).forEach(c => {
                const label = c.business_name_tr || c.name;
                const meta = c.name + ' · ' + (c.data_type || '?') +
                             (c.semantic_type ? ' · ' + c.semantic_type : '');
                html += '<div class="dsw-result-item">' +
                        '<div class="dsw-r-title">' + _escape(label) + '</div>' +
                        '<div class="dsw-r-meta">' + _escape(meta) + '</div></div>';
            });
            html += '</div>';
            panel.innerHTML = html;
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Hata: ' + _escape(e.message) + '</p>';
            _notify('Kolonlar yüklenemedi: ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // ============================================
    // Step 4 — Preview (SQL + cost)
    // ============================================

    async function _loadPreview() {
        const panel = document.getElementById('dswStep4');
        if (!panel) return;
        if (!_state.sessionUid || !_state.selectedTableId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Önceki adımları tamamlayın.</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">SQL üretiliyor...</p>';
        // P4 fix: actual object_name + schema from _selectTable, not display label.
        // Display label may be a Turkish business name; SQL needs the real identifier.
        const tableName = _state.selectedTableObjectName ||
            // fallback (only if older flow set label-only): last segment of label
            (_state.selectedTableLabel || 'unknown').split('.').pop();
        const wizardState = {
            source_id: _state.sourceId,
            dialect: 'postgresql',
            base_table: {
                schema: _state.selectedTableSchema || undefined,
                table: tableName,
                alias: 't',
            },
            selected_columns: [{ expr: '*' }],
            company_scoped_aliases: ['t'],  // RLS hint — assembler injects company_id filter
            limit: 100,
        };
        if (_state.metric) {
            wizardState.metric = {
                metric_key: _state.metric.metric_key,
                sql_template: (_state.metric.sql_templates || {}).postgresql,
                placeholders: { table: tableName, limit: '100' },
            };
        }
        try {
            const url = API_BASE + '/sessions/' + _state.sessionUid + '/preview';
            const data = await _fetchJson(url, {
                method: 'POST',
                body: JSON.stringify({ wizard_state: wizardState }),
            });
            const sql = data.sql || '';
            const cost = (data.explain && data.explain.total_cost) || null;
            const strategy = data.streaming_strategy || 'direct';
            const strategyLabel = ({
                'direct': 'tek istek',
                'cursor': 'cursor akışı',
                'sse_chunk': 'SSE chunk',
            })[strategy] || strategy;
            panel.innerHTML =
                '<p class="dsw-hint" role="status">Önizleme · dialect: ' + _escape(data.dialect || 'postgresql') +
                (cost != null ? ' · maliyet: ' + cost.toFixed(2) : '') +
                ' · akış: ' + _escape(strategyLabel) + '</p>' +
                '<pre style="background:var(--bg-default);border:1px solid var(--border-default);' +
                'padding:10px;border-radius:6px;font-size:12px;overflow-x:auto;white-space:pre-wrap" ' +
                'aria-label="Üretilen SQL">' +
                _escape(sql) + '</pre>';
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint" role="status">Hata: ' + _escape(e.message) + '</p>';
            _notify('Önizleme oluşturulamadı: ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // Step değişiminde data fetch tetikle
    function _onStepEnter(n) {
        if (n === 1) _loadRelated();
        else if (n === 2) _loadMetrics();
        else if (n === 3) _loadColumns();
        else if (n === 4) _loadPreview();
    }

    // ============================================
    // Utility
    // ============================================

    function _escape(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ============================================
    // Init
    // ============================================

    // HEBE Gate: ARIA tablist keyboard navigation (Left/Right/Home/End)
    function _onStepperKeydown(e) {
        const tabs = Array.from(document.querySelectorAll('.dsw-stepper .dsw-step'));
        if (!tabs.length) return;
        const cur = _state.currentStep;
        let target = -1;
        switch (e.key) {
            case 'ArrowRight':
            case 'ArrowDown':
                target = Math.min(tabs.length - 1, cur + 1); break;
            case 'ArrowLeft':
            case 'ArrowUp':
                target = Math.max(0, cur - 1); break;
            case 'Home':
                target = 0; break;
            case 'End':
                target = tabs.length - 1; break;
            default:
                return;
        }
        e.preventDefault();
        _setStep(target);
        if (tabs[target]) tabs[target].focus();
    }

    // HEBE Gate: panel-level Esc → close wizard + return focus
    function _onPanelKeydown(e) {
        if (e.key !== 'Escape') return;
        const panel = document.getElementById('dbSmartWizardPanel');
        if (!panel || panel.classList.contains('hidden') || panel.hasAttribute('hidden')) return;
        e.preventDefault();
        _closeWizard();
    }

    function _closeWizard() {
        const panel = document.getElementById('dbSmartWizardPanel');
        if (!panel) return;
        panel.classList.add('hidden');
        panel.setAttribute('hidden', '');
        // Return focus to opener if recorded
        if (_state._lastFocusEl && typeof _state._lastFocusEl.focus === 'function') {
            try { _state._lastFocusEl.focus(); } catch (e) { /* ignore */ }
        }
    }

    function init() {
        // Record opener for return-focus (HEBE Gate)
        _state._lastFocusEl = document.activeElement;

        // Buton binding'leri (idempotent)
        const searchBtn = document.getElementById('dswSearchBtn');
        if (searchBtn && !searchBtn._bound) {
            searchBtn.addEventListener('click', _searchTables);
            searchBtn._bound = true;
        }
        const prev = document.getElementById('dswPrevBtn');
        if (prev && !prev._bound) {
            prev.addEventListener('click', () => _setStep(_state.currentStep - 1));
            prev._bound = true;
        }
        const next = document.getElementById('dswNextBtn');
        if (next && !next._bound) {
            next.addEventListener('click', () => _setStep(_state.currentStep + 1));
            next._bound = true;
        }
        const searchInput = document.getElementById('dswSearchQ');
        if (searchInput && !searchInput._bound) {
            searchInput.addEventListener('keydown', e => {
                if (e.key === 'Enter') _searchTables();
            });
            searchInput._bound = true;
        }
        // HEBE Gate: tablist keyboard nav + click activation on step buttons
        const stepper = document.getElementById('dswStepper');
        if (stepper && !stepper._bound) {
            stepper.addEventListener('keydown', _onStepperKeydown);
            stepper.querySelectorAll('.dsw-step').forEach(tab => {
                tab.addEventListener('click', () => {
                    const n = parseInt(tab.dataset.step, 10);
                    if (!isNaN(n)) {
                        _setStep(n);
                        tab.focus();
                    }
                });
            });
            stepper._bound = true;
        }
        // HEBE Gate: Esc handler on the wizard panel
        const panel = document.getElementById('dbSmartWizardPanel');
        if (panel && !panel._bound) {
            panel.addEventListener('keydown', _onPanelKeydown);
            panel._bound = true;
        }
        _setStep(0);
        _loadSources();
        _ensureSession();
    }

    window.DbSmartWizardModule = {
        init: init,
        close: _closeWizard,
        getState: function () { return Object.assign({}, _state); },
    };
})();
