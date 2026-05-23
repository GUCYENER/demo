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

    // v3.30.0 FAZ 5 P34 — i18n helper (VyraI18n yüklü değilse key passthrough)
    function _t(key, params) {
        if (window.VyraI18n && typeof window.VyraI18n.t === 'function') {
            return window.VyraI18n.t(key, params);
        }
        return key;
    }

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
        currentAst: null,                 // P20-D: server-canonical AST snapshot
        _lastFocusEl: null,               // HEBE Gate: return-focus target
    };

    // P20-D — Step 4 AST editor mount lifecycle
    const AST_EDITOR_STEP_IDX = 4;        // 0-based: 5. adım (Önizleme + AST)
    const PREVIEW_REFRESH_DEBOUNCE_MS = 300;
    let _astEditorMounted = false;
    let _previewRefreshTimer = null;

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
        // P20-D: leaving Step 4 (AST editor host) → unmount + abort in-flight fetches.
        if (_state.currentStep === AST_EDITOR_STEP_IDX && n !== AST_EDITOR_STEP_IDX) {
            _unmountAstEditor();
        }
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
        if (progress) progress.textContent = _t('wizard.step.indicator', { current: n + 1, total: TOTAL_STEPS });
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
                opt.textContent = _t('wizard.empty.sources');
                sel.appendChild(opt);
            }
        } catch (e) {
            console.warn('[db_smart_wizard] _loadSources failed:', e);
        }
    }

    // v3.34.0 — Tablo Seçici alt-modal entegrasyonu
    function _openPicker() {
        const sourceId = (document.getElementById('dswSourceSelect') || {}).value || '';
        if (!sourceId) {
            _notify(_t('wizard.toast.select_source'), 'warning');
            return;
        }
        if (!window.DbSmartPicker || typeof window.DbSmartPicker.open !== 'function') {
            console.warn('[db_smart_wizard] DbSmartPicker yüklü değil');
            return;
        }
        _state.sourceId = parseInt(sourceId, 10);
        const initialQ = (document.getElementById('dswSearchQ') || {}).value || '';
        window.DbSmartPicker.open({
            sourceId: _state.sourceId,
            initialQuery: initialQ,
            onConfirm: function (sel) { _onPickerConfirm(sel); },
        });
    }

    function _onPickerConfirm(sel) {
        if (!sel || !sel.primary) return;
        const primary = sel.primary;
        const joins = sel.joins || [];
        // Ana tablo state'i (mevcut alanlar)
        _state.selectedTableId = parseInt(primary.table_id, 10);
        _state.selectedTableObjectName = primary.name || null;
        _state.selectedTableSchema = primary.schema || null;
        _state.selectedTableLabel = primary.label || primary.name;
        _state.selectedTables = [_state.selectedTableId].concat(
            joins.map(j => (j.table_id != null && !isNaN(parseInt(j.table_id, 10)))
                              ? parseInt(j.table_id, 10) : j.table_id)
        );
        // Join adayları — step 2 (FK) için bilgilendirici
        _state.joinCandidates = joins.slice();
        // Adım 1'de seçimleri göster (kullanıcı isteği: step 1'de kal)
        _renderSelectedSummary(primary, joins);
        // İleri butonu aktive et
        const next = document.getElementById('dswNextBtn');
        if (next) next.disabled = false;
        _notify(_t('wizard.toast.table_selected', { label: primary.label || primary.name }), 'success');
    }

    function _renderSelectedSummary(primary, joins) {
        const results = document.getElementById('dswResults');
        if (!results) return;
        const escape = _escape;
        const items = [
            '<li class="is-primary" title="Ana tablo">★ ' + escape(primary.label || primary.name) +
            ' <span style="opacity:.7;font-family:ui-monospace,monospace">' +
            escape((primary.schema ? primary.schema + '.' : '') + (primary.name || '')) + '</span></li>'
        ].concat(joins.map(j =>
            '<li title="Join adayı">' + escape(j.label || j.name) +
            ' <span style="opacity:.7;font-family:ui-monospace,monospace">' +
            escape((j.schema ? j.schema + '.' : '') + (j.name || '')) + '</span></li>'
        ));
        const total = 1 + joins.length;
        results.innerHTML =
            '<div class="dsw-selected-summary">' +
              '<h4>Seçilen tablolar (' + total + ')</h4>' +
              '<ul>' + items.join('') + '</ul>' +
              '<button type="button" class="dsw-selected-edit" id="dswSelectedEdit">Seçimi düzenle…</button>' +
            '</div>';
        const editBtn = document.getElementById('dswSelectedEdit');
        if (editBtn) editBtn.addEventListener('click', _openPicker);
    }

    async function _searchTables() {
        const q = (document.getElementById('dswSearchQ') || {}).value || '';
        const sourceId = (document.getElementById('dswSourceSelect') || {}).value || '';
        const results = document.getElementById('dswResults');
        if (!results) return;
        if (!sourceId) {
            results.innerHTML = '<div class="dsw-hint" role="status">' + _escape(_t('wizard.hint.select_source_first')) + '</div>';
            _notify(_t('wizard.toast.select_source'), 'warning');
            return;
        }
        _state.sourceId = parseInt(sourceId, 10);
        _setBusy(results, true);
        results.innerHTML = '<div class="dsw-hint" role="status">' + _escape(_t('wizard.hint.searching')) + '</div>';
        try {
            const url = API_BASE + '/sources/' + sourceId + '/tables?q=' +
                        encodeURIComponent(q) + '&limit=10';
            const data = await _fetchJson(url);
            const items = data.tables || data.items || [];
            if (!items.length) {
                results.innerHTML = '<div class="dsw-hint" role="status">' + _escape(_t('wizard.empty.tables')) + '</div>';
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
            results.innerHTML = '<div class="dsw-hint" role="status">' + _escape(_t('wizard.error.generic', { message: e.message })) + '</div>';
            _notify(_t('wizard.error.search_failed', { message: e.message }), 'error');
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
        _notify(_t('wizard.toast.table_selected', { label: label }), 'success');
    }

    // ============================================
    // Step 1 — Related tables (FK graph)
    // ============================================

    async function _loadRelated() {
        const panel = document.getElementById('dswStep1');
        if (!panel) return;
        if (!_state.selectedTableId || !_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.hint.select_table_first')) + '</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.hint.loading_related')) + '</p>';
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/' + _state.selectedTableId + '/related?depth=1';
            const data = await _fetchJson(url);
            const neighbors = data.neighbors || [];
            const junctions = data.junctions || [];
            let html = '<p class="dsw-hint">' + _escape(_t('wizard.hint.related_summary', { neighbors: neighbors.length, junctions: junctions.length })) + '</p>';
            if (neighbors.length) {
                html += '<div class="dsw-results">';
                neighbors.slice(0, 12).forEach(n => {
                    const label = (n.schema ? n.schema + '.' : '') + n.table;
                    const junc = n.is_junction ? ' · ' + _t('wizard.hint.junction_table') : '';
                    html += '<div class="dsw-result-item">' +
                            '<div class="dsw-r-title">' + _escape(label) + '</div>' +
                            '<div class="dsw-r-meta">' + _escape(_t('wizard.hint.relationship_count', { count: n.via_relationship_count })) +
                            _escape(junc) + '</div></div>';
                });
                html += '</div>';
            }
            panel.innerHTML = html;
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.error.generic', { message: e.message })) + '</p>';
            _notify(_t('wizard.error.related_failed', { message: e.message }), 'error');
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
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.hint.select_source_first')) + '</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.hint.loading_metrics')) + '</p>';
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
                panel.innerHTML = '<p class="dsw-hint">' + _escape(_t('wizard.empty.metrics')) + '</p>';
                return;
            }
            // Kategoriye göre grupla
            const byCategory = {};
            items.forEach(m => {
                const cat = m.category || 'other';
                (byCategory[cat] = byCategory[cat] || []).push(m);
            });
            let html = '<p class="dsw-hint">' + _escape(_t('wizard.hint.metric_intro', { count: items.length })) + '</p>';
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
                    if (_state.metric) _notify(_t('wizard.toast.metric_selected', { label: _state.metric.name_tr || _state.metric.metric_key }), 'success');
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
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.error.generic', { message: e.message })) + '</p>';
            _notify(_t('wizard.error.metrics_failed', { message: e.message }), 'error');
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
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _t('wizard.step3.selectTableFirst') + '</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">' + _t('wizard.step3.loading') + '</p>';
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/' + _state.selectedTableId + '/columns';
            const data = await _fetchJson(url);
            const cols = data.columns || [];
            if (!cols.length) {
                panel.innerHTML = '<p class="dsw-hint">' + _t('wizard.step3.noColumns') + '</p>';
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
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _t('wizard.error.generic') + ': ' + _escape(e.message) + '</p>';
            _notify(_t('wizard.step3.loadError') + ': ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // ============================================
    // Step 4 — Preview (SQL + cost)
    // ============================================

    // P20-D: wizard_state üretimi tek bir yere alındı (preview + AST mount paylaşır).
    function _buildWizardState() {
        const tableName = _state.selectedTableObjectName ||
            (_state.selectedTableLabel || 'unknown').split('.').pop();
        const ws = {
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
            ws.metric = {
                metric_key: _state.metric.metric_key,
                sql_template: (_state.metric.sql_templates || {}).postgresql,
                placeholders: { table: tableName, limit: '100' },
            };
        }
        return ws;
    }

    async function _loadPreview() {
        const panel = document.getElementById('dswStep4');
        const hint = document.getElementById('dswStep4Hint');
        const legacy = document.getElementById('dswLegacyPreview');
        if (!panel) return;
        if (!_state.sessionUid || !_state.selectedTableId) {
            if (hint) hint.textContent = 'Önceki adımları tamamlayın.';
            if (legacy) { legacy.textContent = ''; legacy.setAttribute('hidden', ''); }
            return;
        }
        _setBusy(panel, true);
        if (hint) hint.textContent = 'SQL üretiliyor...';
        // P4 fix: actual object_name + schema from _selectTable, not display label.
        const wizardState = _buildWizardState();
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
            if (hint) {
                hint.textContent = 'Önizleme · dialect: ' + (data.dialect || 'postgresql') +
                    (cost != null ? ' · maliyet: ' + cost.toFixed(2) : '') +
                    ' · akış: ' + strategyLabel;
            }
            // P20-D: SQL legacy <pre> slot'una yazılır — AST editor mount edildiyse gizli.
            if (legacy) {
                legacy.textContent = sql;
                legacy.setAttribute('aria-label', 'Üretilen SQL');
                if (!_astEditorMounted) legacy.removeAttribute('hidden');
            }
        } catch (e) {
            if (hint) hint.textContent = 'Hata: ' + e.message;
            _notify('Önizleme oluşturulamadı: ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // P20-D: debounced preview refresh after AST onChange.
    function _refreshPreviewIfActive() {
        if (_state.currentStep !== AST_EDITOR_STEP_IDX) return;
        if (_previewRefreshTimer) clearTimeout(_previewRefreshTimer);
        _previewRefreshTimer = setTimeout(() => {
            _previewRefreshTimer = null;
            _loadPreview();
        }, PREVIEW_REFRESH_DEBOUNCE_MS);
    }

    // P20-D: build minimal starter AST from wizard_state when none exists yet.
    function _buildStarterAst() {
        const ws = _buildWizardState();
        return {
            dialect: ws.dialect,
            from: { schema: ws.base_table.schema || null, table: ws.base_table.table, alias: 't' },
            select: (ws.selected_columns || []).map(c => c.expr || '*'),
            filters: [],
            order_by: [],
            joins: [],
            limit: ws.limit || 100,
        };
    }

    // P20-D: mount AST editor into #dswAstEditor slot.
    function _mountAstEditor() {
        if (_astEditorMounted) return;
        const slot = document.getElementById('dswAstEditor');
        if (!slot) return;
        const Editor = window.DbSmartAstEditor;
        if (!Editor || typeof Editor.mount !== 'function') {
            console.warn('[db_smart_wizard] DbSmartAstEditor not loaded; legacy preview only');
            // Defansif: legacy preview görünür kalsın.
            const legacy = document.getElementById('dswLegacyPreview');
            if (legacy) legacy.removeAttribute('hidden');
            return;
        }
        const initialAst = _state.currentAst || _buildStarterAst();
        _state.currentAst = initialAst;
        // Legacy preview'ı gizle — AST editor canonical olur.
        const legacy = document.getElementById('dswLegacyPreview');
        if (legacy) legacy.setAttribute('hidden', '');
        try {
            Editor.mount(slot, {
                sessionUid: _state.sessionUid,
                dialect: 'postgresql',
                ast: initialAst,
                fetchJson: _fetchJson,
                onChange: function (newAst /*, newSql */) {
                    _state.currentAst = newAst;
                    _refreshPreviewIfActive();
                },
            });
            _astEditorMounted = true;
        } catch (e) {
            console.warn('[db_smart_wizard] AST editor mount failed:', e);
            if (legacy) legacy.removeAttribute('hidden');
        }
    }

    function _unmountAstEditor() {
        if (!_astEditorMounted) return;
        const Editor = window.DbSmartAstEditor;
        if (Editor && typeof Editor.unmount === 'function') {
            try { Editor.unmount(); } catch (e) { /* ignore */ }
        }
        _astEditorMounted = false;
        if (_previewRefreshTimer) {
            clearTimeout(_previewRefreshTimer);
            _previewRefreshTimer = null;
        }
        // Legacy preview tekrar görünür — kullanıcı 4. adıma dönerse _loadPreview yine yazar.
        const legacy = document.getElementById('dswLegacyPreview');
        if (legacy && legacy.textContent) legacy.removeAttribute('hidden');
    }

    // Step değişiminde data fetch tetikle
    function _onStepEnter(n) {
        if (n === 1) _loadRelated();
        else if (n === 2) _loadMetrics();
        else if (n === 3) _loadColumns();
        else if (n === AST_EDITOR_STEP_IDX) {
            // P20-D: preview önce — AST editor mount sırasında lastExplain için
            // sunucudan cost rozetini çağırır; sonra AST editor mount edilir.
            _loadPreview();
            _mountAstEditor();
        }
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
        // P20-D: panel kapatılırken AST editor mount edilmişse temizle.
        if (_astEditorMounted) _unmountAstEditor();
        panel.classList.add('hidden');
        panel.setAttribute('hidden', '');
        // Return focus to opener if recorded
        if (_state._lastFocusEl && typeof _state._lastFocusEl.focus === 'function') {
            try { _state._lastFocusEl.focus(); } catch (e) { /* ignore */ }
        }
    }

    // v3.33.0 — i18n bundle hazır olana kadar bekle (step.indicator vb. için)
    async function _ensureI18n() {
        if (!window.VyraI18n) return;
        try {
            if (typeof window.VyraI18n.ensureInit === 'function') {
                await window.VyraI18n.ensureInit();
            } else if (typeof window.VyraI18n.init === 'function') {
                await window.VyraI18n.init();
            }
        } catch (e) { /* graceful: passthrough fallback */ }
    }

    function init(opts) {
        opts = opts || {};
        // Record opener for return-focus (HEBE Gate)
        _state._lastFocusEl = document.activeElement;
        // i18n bundle async load (fire-and-forget; UI metinleri sonra applyTranslations)
        _ensureI18n().then(function () {
            try {
                if (window.VyraI18n && typeof window.VyraI18n.applyTranslations === 'function') {
                    const root = document.getElementById('dbSmartWizardPanel');
                    if (root) window.VyraI18n.applyTranslations(root);
                }
                // step indicator'ı yeniden bas
                _setStep(_state.currentStep);
            } catch (e) { /* ignore */ }
        });

        // Buton binding'leri (idempotent)
        // v3.34.0 — "Tablo Seç" butonu artık DbSmartPicker alt-modal'ını açar.
        // Eski inline arama fallback olarak input Enter ile hâlâ erişilebilir.
        const searchBtn = document.getElementById('dswSearchBtn');
        if (searchBtn && !searchBtn._bound) {
            searchBtn.addEventListener('click', _openPicker);
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

    // ============================================================
    // v3.33.0 — Modal wrapper (overlay + dialog)
    // ============================================================
    // Strateji: inline panel'i klonlamak yerine **taşı** (appendChild).
    //   - DOM event listener'ları + _bound flag'leri korunur (Agent A note #3).
    //   - Modal kapanınca panel orijinal parent'a iade edilir.

    let _modalState = {
        open: false,
        overlay: null,
        dialog: null,
        panelOrigParent: null,
        panelOrigNextSibling: null,
        prevBodyOverflow: null,
        resolve: null,
        opener: null,
    };

    function isOpen() { return !!_modalState.open; }

    function _trapFocus(e) {
        if (e.key !== 'Tab') return;
        const dialog = _modalState.dialog;
        if (!dialog) return;
        const focusables = dialog.querySelectorAll(
            'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'
        );
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
        }
    }

    function _onModalKeydown(e) {
        if (e.key === 'Escape') { e.stopPropagation(); closeModal({ action: 'cancelled' }); return; }
        _trapFocus(e);
    }

    function _onOverlayClick(e) {
        if (e.target === _modalState.overlay) closeModal({ action: 'cancelled' });
    }

    async function openAsModal(opts) {
        opts = opts || {};
        if (_modalState.open) return Promise.resolve(null);

        // Wizard panel DOM'unu modal'a taşı
        const panel = document.getElementById('dbSmartWizardPanel');
        if (!panel) {
            console.warn('[DbSmartWizard] panel DOM bulunamadı');
            return Promise.resolve(null);
        }

        _modalState.opener = document.activeElement;
        _state._lastFocusEl = _modalState.opener;

        // Overlay + dialog
        const overlay = document.createElement('div');
        overlay.className = 'dsw-modal-overlay';
        overlay.setAttribute('role', 'presentation');
        overlay.addEventListener('click', _onOverlayClick);

        const dialog = document.createElement('div');
        dialog.className = 'dsw-modal-dialog';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'dswTitle');

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'dsw-modal-close';
        closeBtn.setAttribute('aria-label', 'Kapat');
        closeBtn.setAttribute('data-tooltip', 'Kapat (Esc)');
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', function () { closeModal({ action: 'cancelled' }); });

        dialog.appendChild(closeBtn);

        // Panel'i taşı (klonlama yok — event binding korunur)
        _modalState.panelOrigParent = panel.parentNode;
        _modalState.panelOrigNextSibling = panel.nextSibling;
        panel.classList.remove('hidden');
        panel.hidden = false;
        panel.classList.add('dsw-in-modal');
        dialog.appendChild(panel);

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // Body scroll lock
        _modalState.prevBodyOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';

        _modalState.open = true;
        _modalState.overlay = overlay;
        _modalState.dialog = dialog;

        // ESC + focus trap
        document.addEventListener('keydown', _onModalKeydown, true);

        // Wizard init/hydrate
        init({ mode: 'modal' });

        // reportId verilmişse hydrate dene (best-effort, hatayı yutar)
        if (opts.reportId) {
            _hydrateFromSavedReport(opts.reportId).catch(function (e) {
                console.warn('[DbSmartWizard] reportId hydrate failed', e);
            });
        }

        // İlk focusable'a focus
        setTimeout(function () {
            try {
                const target = dialog.querySelector(
                    'input,select,textarea,button:not([disabled]),[tabindex]:not([tabindex="-1"])'
                );
                if (target) target.focus();
            } catch (e) { /* ignore */ }
        }, 0);

        return new Promise(function (resolve) {
            _modalState.resolve = function (payload) {
                resolve(payload);
                if (opts && typeof opts.onClose === 'function') {
                    try { opts.onClose(payload); } catch (e) { /* ignore */ }
                }
                if (payload && payload.action === 'saved' && opts && typeof opts.onSave === 'function') {
                    try { opts.onSave(payload); } catch (e) { /* ignore */ }
                }
            };
        });
    }

    async function _hydrateFromSavedReport(reportId) {
        const url = API_BASE + '/saved-reports/' + encodeURIComponent(reportId);
        const data = await _fetchJson(url);
        if (data && data.wizard_state && typeof data.wizard_state === 'object') {
            const ws = data.wizard_state;
            if (ws.sourceId) _state.sourceId = ws.sourceId;
            if (ws.selectedTableId) _state.selectedTableId = ws.selectedTableId;
            if (ws.selectedTableObjectName) _state.selectedTableObjectName = ws.selectedTableObjectName;
            if (ws.selectedTableSchema) _state.selectedTableSchema = ws.selectedTableSchema;
            if (ws.selectedTableLabel) _state.selectedTableLabel = ws.selectedTableLabel;
            if (Array.isArray(ws.selectedTables)) _state.selectedTables = ws.selectedTables;
            if (ws.metric) _state.metric = ws.metric;
            if (Array.isArray(ws.filters)) _state.filters = ws.filters;
            _setStep(0);
        }
    }

    function closeModal(payload) {
        if (!_modalState.open) return;
        const overlay = _modalState.overlay;
        const panel = document.getElementById('dbSmartWizardPanel');

        document.removeEventListener('keydown', _onModalKeydown, true);

        // Panel'i orijinal parent'a iade et + gizle
        if (panel) {
            panel.classList.remove('dsw-in-modal');
            try {
                if (_modalState.panelOrigParent) {
                    if (_modalState.panelOrigNextSibling && _modalState.panelOrigNextSibling.parentNode === _modalState.panelOrigParent) {
                        _modalState.panelOrigParent.insertBefore(panel, _modalState.panelOrigNextSibling);
                    } else {
                        _modalState.panelOrigParent.appendChild(panel);
                    }
                }
            } catch (e) { /* ignore */ }
            panel.classList.add('hidden');
            panel.setAttribute('hidden', '');
        }

        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);

        // Body scroll restore
        document.body.style.overflow = _modalState.prevBodyOverflow || '';

        // Return focus
        if (_modalState.opener && typeof _modalState.opener.focus === 'function') {
            try { _modalState.opener.focus(); } catch (e) { /* ignore */ }
        }

        const resolve = _modalState.resolve;
        _modalState = {
            open: false, overlay: null, dialog: null,
            panelOrigParent: null, panelOrigNextSibling: null,
            prevBodyOverflow: null, resolve: null, opener: null,
        };
        if (typeof resolve === 'function') {
            resolve(payload || { action: 'cancelled' });
        }
    }

    // Save sonrası dışarıdan tetiklenebilir hook (ileride wizard finish'i çağıracak)
    function _notifySaved(reportId, name) {
        if (_modalState.open) {
            closeModal({ action: 'saved', reportId: reportId, name: name });
        }
    }

    window.DbSmartWizardModule = {
        init: init,
        close: _closeWizard,
        openAsModal: openAsModal,
        closeModal: closeModal,
        isOpen: isOpen,
        _notifySaved: _notifySaved,
        getState: function () { return Object.assign({}, _state); },
    };
})();
