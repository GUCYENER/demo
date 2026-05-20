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
    let _state = {
        sessionUid: null,
        currentStep: 0,
        sourceId: null,
        selectedTableId: null,
        selectedTables: [],
        metric: null,
        filters: [],
    };

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
        if (n < 0 || n > 4) return;
        _state.currentStep = n;
        document.querySelectorAll('.dsw-step').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.step, 10) === n);
        });
        document.querySelectorAll('.dsw-step-panel').forEach(el => {
            el.classList.toggle('hidden', parseInt(el.dataset.step, 10) !== n);
        });
        const progress = document.getElementById('dswProgress');
        if (progress) progress.textContent = 'Adım ' + (n + 1) + ' / 5';
        const prev = document.getElementById('dswPrevBtn');
        const next = document.getElementById('dswNextBtn');
        if (prev) prev.disabled = (n === 0);
        if (next) next.disabled = (n === 4);
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
            results.innerHTML = '<div class="dsw-hint">Lütfen önce veri kaynağı seçin.</div>';
            return;
        }
        _state.sourceId = parseInt(sourceId, 10);
        results.innerHTML = '<div class="dsw-hint">Aranıyor...</div>';
        try {
            const url = API_BASE + '/sources/' + sourceId + '/tables?q=' +
                        encodeURIComponent(q) + '&limit=10';
            const data = await _fetchJson(url);
            const items = data.tables || data.items || [];
            if (!items.length) {
                results.innerHTML = '<div class="dsw-hint">Eşleşen tablo bulunamadı.</div>';
                return;
            }
            results.innerHTML = '';
            items.forEach(t => {
                const div = document.createElement('div');
                div.className = 'dsw-result-item';
                div.setAttribute('data-table-id', t.table_id || t.id || '');
                const title = (t.business_name_tr || t.object_name || t.table_name || '?');
                const meta = (t.schema_name ? t.schema_name + '.' : '') +
                             (t.object_name || t.table_name || '') +
                             (t.row_count_estimate ? ' · ~' + t.row_count_estimate + ' satır' : '') +
                             (t.score != null ? ' · skor ' + t.score : '');
                div.innerHTML =
                    '<div class="dsw-r-title">' + _escape(title) + '</div>' +
                    '<div class="dsw-r-meta">' + _escape(meta) + '</div>';
                div.addEventListener('click', () => _selectTable(t.table_id || t.id, title));
                results.appendChild(div);
            });
        } catch (e) {
            results.innerHTML = '<div class="dsw-hint">Hata: ' + _escape(e.message) + '</div>';
        }
    }

    function _selectTable(tableId, label) {
        _state.selectedTableId = parseInt(tableId, 10);
        _state.selectedTables = [_state.selectedTableId];
        _state.selectedTableLabel = label;
        document.querySelectorAll('.dsw-result-item').forEach(el => {
            const tid = parseInt(el.getAttribute('data-table-id'), 10);
            el.style.borderColor = (tid === _state.selectedTableId) ? '#F59E0B' : '';
        });
        // İleri butonu aktive et
        const next = document.getElementById('dswNextBtn');
        if (next) next.disabled = false;
    }

    // ============================================
    // Step 1 — Related tables (FK graph)
    // ============================================

    async function _loadRelated() {
        const panel = document.getElementById('dswStep1');
        if (!panel) return;
        if (!_state.selectedTableId || !_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint">Önce Adım 1\'de bir tablo seçin.</p>';
            return;
        }
        panel.innerHTML = '<p class="dsw-hint">FK ilişkileri yükleniyor...</p>';
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
            panel.innerHTML = '<p class="dsw-hint">Hata: ' + _escape(e.message) + '</p>';
        }
    }

    // ============================================
    // Step 2 — Metric library
    // ============================================

    async function _loadMetrics() {
        const panel = document.getElementById('dswStep2');
        if (!panel) return;
        if (!_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint">Önce veri kaynağı seçin.</p>';
            return;
        }
        panel.innerHTML = '<p class="dsw-hint">Metrik kütüphanesi yükleniyor...</p>';
        try {
            const url = API_BASE + '/metrics?source_id=' + _state.sourceId;
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
            // Click binding
            panel.querySelectorAll('[data-metric-key]').forEach(el => {
                el.addEventListener('click', () => {
                    const mk = el.getAttribute('data-metric-key');
                    _state.metric = items.find(x => x.metric_key === mk) || null;
                    panel.querySelectorAll('[data-metric-key]').forEach(e2 => {
                        e2.style.borderColor = (e2 === el) ? '#F59E0B' : '';
                    });
                });
            });
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint">Hata: ' + _escape(e.message) + '</p>';
        }
    }

    // ============================================
    // Step 3 — Filter (columns)
    // ============================================

    async function _loadColumns() {
        const panel = document.getElementById('dswStep3');
        if (!panel) return;
        if (!_state.selectedTableId || !_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint">Önce tablo seçin.</p>';
            return;
        }
        panel.innerHTML = '<p class="dsw-hint">Kolonlar yükleniyor...</p>';
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
            panel.innerHTML = '<p class="dsw-hint">Hata: ' + _escape(e.message) + '</p>';
        }
    }

    // ============================================
    // Step 4 — Preview (SQL + cost)
    // ============================================

    async function _loadPreview() {
        const panel = document.getElementById('dswStep4');
        if (!panel) return;
        if (!_state.sessionUid || !_state.selectedTableId) {
            panel.innerHTML = '<p class="dsw-hint">Önceki adımları tamamlayın.</p>';
            return;
        }
        panel.innerHTML = '<p class="dsw-hint">SQL üretiliyor...</p>';
        // Transient mod: wizard_state'i request body'de gönder (G1.7 öncesi)
        const wizardState = {
            source_id: _state.sourceId,
            dialect: 'postgresql',
            base_table: { table: (_state.selectedTableLabel || 'unknown').split('.').pop() },
            selected_columns: [{ expr: '*' }],
            limit: 100,
        };
        if (_state.metric) {
            wizardState.metric = {
                metric_key: _state.metric.metric_key,
                sql_template: (_state.metric.sql_templates || {}).postgresql,
                placeholders: { table: wizardState.base_table.table, limit: '100' },
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
            panel.innerHTML =
                '<p class="dsw-hint">Önizleme · dialect: ' + _escape(data.dialect || 'postgresql') +
                (cost != null ? ' · maliyet: ' + cost.toFixed(2) : '') + '</p>' +
                '<pre style="background:var(--bg-default);border:1px solid var(--border-default);' +
                'padding:10px;border-radius:6px;font-size:12px;overflow-x:auto;white-space:pre-wrap">' +
                _escape(sql) + '</pre>';
        } catch (e) {
            panel.innerHTML = '<p class="dsw-hint">Hata: ' + _escape(e.message) + '</p>';
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

    function init() {
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
        _setStep(0);
        _loadSources();
        _ensureSession();
    }

    window.DbSmartWizardModule = {
        init: init,
        getState: function () { return Object.assign({}, _state); },
    };
})();
