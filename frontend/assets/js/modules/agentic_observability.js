/**
 * agentic_observability.js
 * ------------------------
 * /api/agentic-query/observability/stats verisini section_agentic_observability.html
 * partial'ında render eder. Admin sayfası.
 *
 * Usage:
 *   AgenticObservability.init('#agenticObservabilitySection');
 */
(function () {
    'use strict';

    const ENDPOINT = '/api/agentic-query/observability/stats';

    function _qs(parent, sel) { return parent.querySelector(sel); }
    function _qsa(parent, sel) { return parent.querySelectorAll(sel); }

    function _authHeaders() {
        const h = { 'Accept': 'application/json' };
        try {
            const t = window.localStorage && window.localStorage.getItem('access_token');
            if (t) h['Authorization'] = `Bearer ${t}`;
        } catch (_e) { /* sessiz */ }
        return h;
    }

    function _getByPath(obj, path) {
        return path.split('.').reduce((o, k) => (o == null ? null : o[k]), obj);
    }

    function _bindMetrics(root, data) {
        _qsa(root, '[data-bind]').forEach((el) => {
            const path = el.dataset.bind;
            const v = _getByPath(data, path);
            el.textContent = v == null ? '—' : String(v);
        });
    }

    function _renderNodes(root, nodes) {
        const tbody = _qs(root, '#aoNodesTable tbody');
        if (!tbody) return;
        tbody.replaceChildren();
        if (!nodes || nodes.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 6; td.className = 'ao-empty';
            td.textContent = 'Veri yok';
            tr.appendChild(td); tbody.appendChild(tr);
            return;
        }
        const frag = document.createDocumentFragment();
        for (const n of nodes) {
            const tr = document.createElement('tr');
            const cells = [n.node, n.samples, n.avg_ms, n.p50_ms, n.p95_ms, n.error_count];
            cells.forEach((v, i) => {
                const td = document.createElement('td');
                td.textContent = v == null ? '—' : String(v);
                if (i === 5 && (n.error_count || 0) > 0) td.classList.add('ao-cell--err');
                tr.appendChild(td);
            });
            frag.appendChild(tr);
        }
        tbody.appendChild(frag);
    }

    function _renderBarList(ulEl, items, labelKey, countKey) {
        if (!ulEl) return;
        ulEl.replaceChildren();
        const max = Math.max(1, ...items.map((x) => x[countKey] || 0));
        for (const it of items) {
            const li = document.createElement('li');
            li.className = 'ao-bar';
            const pct = Math.round(((it[countKey] || 0) / max) * 100);

            const lbl = document.createElement('span');
            lbl.className = 'ao-bar__label';
            lbl.textContent = it[labelKey] || 'unknown';

            const meter = document.createElement('span');
            meter.className = 'ao-bar__meter';
            meter.setAttribute('role', 'progressbar');
            meter.setAttribute('aria-valuenow', String(pct));
            meter.setAttribute('aria-valuemin', '0');
            meter.setAttribute('aria-valuemax', '100');
            const fill = document.createElement('span');
            fill.className = 'ao-bar__fill';
            fill.style.width = pct + '%';
            meter.appendChild(fill);

            const cnt = document.createElement('span');
            cnt.className = 'ao-bar__count';
            cnt.textContent = String(it[countKey] || 0);

            li.appendChild(lbl); li.appendChild(meter); li.appendChild(cnt);
            ulEl.appendChild(li);
        }
        if (items.length === 0) {
            const li = document.createElement('li');
            li.className = 'ao-empty';
            li.textContent = 'Veri yok';
            ulEl.appendChild(li);
        }
    }

    function _renderRecent(root, items) {
        const tbody = _qs(root, '#aoRecentTable tbody');
        if (!tbody) return;
        tbody.replaceChildren();
        if (!items || items.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 7; td.className = 'ao-empty';
            td.textContent = 'Veri yok';
            tr.appendChild(td); tbody.appendChild(tr);
            return;
        }
        const frag = document.createDocumentFragment();
        for (const r of items) {
            const tr = document.createElement('tr');
            const shortId = (r.run_id || '').slice(0, 8);
            const dt = r.created_at ? new Date(r.created_at).toLocaleString('tr-TR') : '—';
            const cells = [shortId, r.status || '—', `${r.duration_ms || 0} ms`,
                           r.sql_source || '—', r.size_bucket || '—',
                           r.row_count == null ? '—' : String(r.row_count), dt];
            cells.forEach((v, i) => {
                const td = document.createElement('td');
                td.textContent = v;
                if (i === 1 && r.status) td.className = `ao-status ao-status--${r.status}`;
                tr.appendChild(td);
            });
            frag.appendChild(tr);
        }
        tbody.appendChild(frag);
    }

    async function _fetchAndRender(root, hours) {
        const loading = _qs(root, '#aoLoading');
        const error = _qs(root, '#aoError');
        if (loading) loading.hidden = false;
        if (error) { error.hidden = true; error.textContent = ''; }

        try {
            const res = await fetch(`${ENDPOINT}?hours=${encodeURIComponent(hours)}`, {
                headers: _authHeaders(),
            });
            if (!res.ok) {
                const txt = await res.text().catch(() => '');
                throw new Error(`HTTP ${res.status}: ${txt.slice(0, 160)}`);
            }
            const json = await res.json();
            if (!json.success) throw new Error(json.detail || 'Veri çekilemedi');

            _bindMetrics(root, json);
            _renderNodes(root, json.nodes || []);
            _renderBarList(_qs(root, '#aoSqlSourceList'), json.sql_source || [], 'source', 'count');
            _renderBarList(_qs(root, '#aoBucketList'), json.size_buckets || [], 'bucket', 'count');
            _renderRecent(root, json.recent_runs || []);
        } catch (err) {
            if (error) {
                error.hidden = false;
                error.textContent = `Yüklenemedi: ${err.message || err}`;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function init(selector) {
        const root = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!root) return null;
        const select = _qs(root, '#aoWindow');
        const btn = _qs(root, '#aoRefresh');

        const refresh = () => _fetchAndRender(root, select ? select.value : 24);

        if (btn) btn.addEventListener('click', refresh);
        if (select) select.addEventListener('change', refresh);

        // İlk yükleme
        refresh();
        return { refresh, root };
    }

    window.AgenticObservability = { init };
})();
