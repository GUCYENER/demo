/**
 * agentic_observability_faz6.js — v3.29.7 G5
 * ===========================================
 * Faz 6 öğrenme metrikleri sekmeleri:
 *   - Template heatmap (kind × complexity)
 *   - Failures top-10
 *   - Glossary kullanım istatistikleri
 *
 * window.AgenticObservabilityFaz6.init('#agenticObservabilitySection')
 *
 * HEBE compliance: role="tablist" / "tab" / "tabpanel", aria-selected,
 * keyboard nav (ArrowLeft/Right, Home/End), aria-live status.
 */
(function () {
    'use strict';

    const ENDPOINTS = {
        heatmap: '/api/agentic-query/observability/template-heatmap',
        failures: '/api/agentic-query/observability/failures-top',
        glossary: '/api/agentic-query/observability/glossary-usage',
    };

    const TAB_IDS = ['Templates', 'Failures', 'Glossary'];

    function _authHeaders() {
        const h = { 'Accept': 'application/json' };
        try {
            const t = window.localStorage && window.localStorage.getItem('access_token');
            if (t) h['Authorization'] = `Bearer ${t}`;
        } catch (_e) { /* sessiz */ }
        return h;
    }

    async function _fetchJson(url, signal) {
        const resp = await fetch(url, { headers: _authHeaders(), signal });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json();
    }

    function _qs(root, sel) { return root.querySelector(sel); }
    function _byId(id) { return document.getElementById(id); }

    // ───────────── tab switching ─────────────

    function _activateTab(root, name) {
        TAB_IDS.forEach((n) => {
            const btn = _qs(root, `#aoTabBtn${n}`);
            const pane = _qs(root, `#aoTab${n}`);
            if (!btn || !pane) return;
            const active = (n === name);
            btn.classList.toggle('ao-tab--active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
            btn.tabIndex = active ? 0 : -1;
            pane.classList.toggle('ao-tab-pane--active', active);
            pane.hidden = !active;
        });
    }

    function _bindTabs(root, state) {
        const buttons = TAB_IDS.map((n) => _qs(root, `#aoTabBtn${n}`)).filter(Boolean);
        buttons.forEach((btn, idx) => {
            btn.addEventListener('click', () => {
                const name = TAB_IDS[idx];
                _activateTab(root, name);
                state.activeTab = name;
                _loadTabData(root, state, name);
            });
            btn.addEventListener('keydown', (e) => {
                let nextIdx = null;
                if (e.key === 'ArrowRight') nextIdx = (idx + 1) % buttons.length;
                else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + buttons.length) % buttons.length;
                else if (e.key === 'Home') nextIdx = 0;
                else if (e.key === 'End') nextIdx = buttons.length - 1;
                if (nextIdx != null) {
                    e.preventDefault();
                    buttons[nextIdx].focus();
                    buttons[nextIdx].click();
                }
            });
        });
    }

    // ───────────── heatmap ─────────────

    async function _loadHeatmap(root, state) {
        const loading = _qs(root, '#aoHeatmapLoading');
        const empty = _qs(root, '#aoHeatmapEmpty');
        const table = _qs(root, '#aoHeatmapTable');
        if (loading) loading.hidden = false;
        if (empty) empty.hidden = true;
        try {
            const data = await _fetchJson(ENDPOINTS.heatmap + '?days=30', state.controller.signal);
            _renderHeatmap(table, data);
            if ((!data.cells || data.cells.length === 0) && empty) empty.hidden = false;
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.warn('[ao-faz6] heatmap failed:', err);
            if (empty) {
                empty.hidden = false;
                empty.textContent = `Yüklenemedi: ${err.message}`;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function _renderHeatmap(table, data) {
        if (!table) return;
        const thead = table.querySelector('thead');
        const tbody = table.querySelector('tbody');
        if (!thead || !tbody) return;
        const complexities = (data.complexities && data.complexities.length)
            ? data.complexities : [1, 2, 3, 4, 5];

        // Header
        thead.replaceChildren();
        const trH = document.createElement('tr');
        const thLabel = document.createElement('th');
        thLabel.scope = 'col';
        thLabel.textContent = 'Template';
        trH.appendChild(thLabel);
        complexities.forEach((c) => {
            const th = document.createElement('th');
            th.scope = 'col';
            th.textContent = `C${c}`;
            th.setAttribute('data-tooltip', `Karmaşıklık ${c}`);
            trH.appendChild(th);
        });
        thead.appendChild(trH);

        // Cell index
        const cellMap = {};
        (data.cells || []).forEach((c) => {
            const k = `${c.template_kind}|${c.complexity_score}`;
            cellMap[k] = c;
        });
        const maxCount = (data.cells || []).reduce((m, c) => Math.max(m, c.run_count || 0), 0) || 1;

        // Rows
        tbody.replaceChildren();
        (data.kinds || []).forEach((kind) => {
            const tr = document.createElement('tr');
            const td0 = document.createElement('td');
            td0.textContent = kind;
            td0.className = 'ao-heatmap-rowlabel';
            tr.appendChild(td0);
            complexities.forEach((c) => {
                const td = document.createElement('td');
                const cell = cellMap[`${kind}|${c}`];
                const cnt = cell ? cell.run_count : 0;
                const sr = cell ? Math.round((cell.success_rate || 0) * 100) : null;
                const ratio = maxCount > 0 ? Math.min(1, cnt / maxCount) : 0;
                const alpha = (0.10 + 0.65 * ratio).toFixed(3);
                td.className = 'ao-heatmap-cell';
                td.style.backgroundColor = `rgba(66, 133, 244, ${alpha})`;
                td.textContent = cnt > 0 ? String(cnt) : '';
                if (cell) {
                    td.setAttribute('data-tooltip',
                        `${kind} · C${c}: ${cnt} kullanım · %${sr} başarı`);
                }
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });

        // Boş kind yoksa zaten kindler boş → empty mesaj zaten gösteriliyor
    }

    // ───────────── failures ─────────────

    async function _loadFailures(root, state) {
        const loading = _qs(root, '#aoFailuresLoading');
        const empty = _qs(root, '#aoFailuresEmpty');
        if (loading) loading.hidden = false;
        if (empty) empty.hidden = true;
        try {
            const data = await _fetchJson(ENDPOINTS.failures + '?limit=10', state.controller.signal);
            _renderFailures(root, data);
            if ((!data.failures || data.failures.length === 0) && empty) empty.hidden = false;
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.warn('[ao-faz6] failures failed:', err);
            if (empty) {
                empty.hidden = false;
                empty.textContent = `Yüklenemedi: ${err.message}`;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function _renderFailures(root, data) {
        const tbody = _qs(root, '#aoFailuresTable tbody');
        if (tbody) {
            tbody.replaceChildren();
            (data.failures || []).forEach((f) => {
                const tr = document.createElement('tr');
                tr.appendChild(_td(f.error_class || '—'));
                tr.appendChild(_td(String(f.recurrence_count || 0)));
                const sqlTd = _td(f.sql_snippet || '—');
                sqlTd.className = 'ao-mono ao-truncate';
                sqlTd.title = f.sql_snippet || '';
                tr.appendChild(sqlTd);
                tr.appendChild(_td(f.hint || '—'));
                tr.appendChild(_td(f.last_seen ? new Date(f.last_seen).toLocaleString() : '—'));
                tbody.appendChild(tr);
            });
        }
        const byClass = _qs(root, '#aoFailuresByClass');
        if (byClass) {
            byClass.replaceChildren();
            const max = (data.by_class || []).reduce((m, x) => Math.max(m, x.total_recurrence || 0), 0) || 1;
            (data.by_class || []).forEach((c) => {
                byClass.appendChild(_barLi(c.error_class, c.total_recurrence, max));
            });
        }
    }

    // ───────────── glossary ─────────────

    async function _loadGlossary(root, state) {
        const loading = _qs(root, '#aoGlossaryLoading');
        const empty = _qs(root, '#aoGlossaryEmpty');
        if (loading) loading.hidden = false;
        if (empty) empty.hidden = true;
        try {
            const data = await _fetchJson(ENDPOINTS.glossary + '?limit=20', state.controller.signal);
            _renderGlossary(root, data);
            if ((!data.terms || data.terms.length === 0) && empty) empty.hidden = false;
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.warn('[ao-faz6] glossary failed:', err);
            if (empty) {
                empty.hidden = false;
                empty.textContent = `Yüklenemedi: ${err.message}`;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function _renderGlossary(root, data) {
        const tbody = _qs(root, '#aoGlossaryTable tbody');
        if (tbody) {
            tbody.replaceChildren();
            (data.terms || []).forEach((t) => {
                const tr = document.createElement('tr');
                tr.appendChild(_td(t.term || '—'));
                tr.appendChild(_td(t.term_type || '—'));
                tr.appendChild(_td(t.expansion_tr || '—'));
                tr.appendChild(_td(t.mapped_table || '—'));
                tr.appendChild(_td(String(t.usage_count || 0)));
                const v = document.createElement('td');
                v.textContent = t.admin_verified ? '✓' : '—';
                v.className = t.admin_verified ? 'ao-verified-yes' : 'ao-verified-no';
                tr.appendChild(v);
                tbody.appendChild(tr);
            });
        }
        const byType = _qs(root, '#aoGlossaryByType');
        if (byType) {
            byType.replaceChildren();
            const max = (data.by_type || []).reduce((m, x) => Math.max(m, x.total_usage || 0), 0) || 1;
            (data.by_type || []).forEach((t) => {
                byType.appendChild(_barLi(`${t.term_type} (${t.count}, ✓${t.verified})`, t.total_usage, max));
            });
        }
    }

    // ───────────── helpers ─────────────

    function _td(text) {
        const td = document.createElement('td');
        td.textContent = text;
        return td;
    }

    function _barLi(label, value, max) {
        const li = document.createElement('li');
        li.className = 'ao-bar-li';
        const lab = document.createElement('span');
        lab.className = 'ao-bar-label';
        lab.textContent = label;
        const bar = document.createElement('span');
        bar.className = 'ao-bar';
        const fill = document.createElement('span');
        fill.className = 'ao-bar-fill';
        const pct = max > 0 ? Math.round((value / max) * 100) : 0;
        fill.style.width = `${pct}%`;
        bar.appendChild(fill);
        const num = document.createElement('span');
        num.className = 'ao-bar-value';
        num.textContent = String(value);
        li.appendChild(lab);
        li.appendChild(bar);
        li.appendChild(num);
        return li;
    }

    // ───────────── load orchestrator ─────────────

    function _loadTabData(root, state, name) {
        // Yeni fetch — önceki istek abort
        if (state.controller) state.controller.abort();
        state.controller = new AbortController();
        if (name === 'Templates') _loadHeatmap(root, state);
        else if (name === 'Failures') _loadFailures(root, state);
        else if (name === 'Glossary') _loadGlossary(root, state);
    }

    function init(selector) {
        const root = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!root) return null;
        // Sekme bar yoksa (eski partial) sessiz çık
        if (!_qs(root, '#aoTabBtnTemplates')) return null;

        const state = { controller: null, activeTab: 'Templates' };
        _bindTabs(root, state);
        // İlk sekmenin verisini yükle
        _loadTabData(root, state, 'Templates');

        // Refresh butonu da Faz 6 sekmesini yenilesin
        const refreshBtn = _qs(root, '#aoRefresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => _loadTabData(root, state, state.activeTab));
        }

        return { state, refresh: () => _loadTabData(root, state, state.activeTab) };
    }

    window.AgenticObservabilityFaz6 = { init };

    // Otomatik bağlama: AgenticObservability mevcut init'i tetiklediğinde
    // bizim init'imiz de DOMContentLoaded sonrası bir kez çalışsın.
    document.addEventListener('DOMContentLoaded', () => {
        const sec = document.getElementById('agenticObservabilitySection');
        if (sec) {
            // Mevcut init zaten asenkron tetiklenebilir; biraz gecikme ile devreye al
            setTimeout(() => { try { init(sec); } catch (_e) { /* sessiz */ } }, 100);
        }
    });
})();
