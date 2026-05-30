/* -------------------------------
   VYRA - Error Monitor Module (v3.38.3)
   Sistem Parametreleri → "Hata İzleme" sekmesi.
   GET /api/system/errors (+ /errors/stats) — tam traceback + request_id, admin-only.
   vyraFetch /api prefix'i kendi ekler → burada '/system/...' path tutulur.
-------------------------------- */
window.ErrorMonitorModule = (function () {
    'use strict';

    const ENDPOINT = '/system/errors';
    const state = { level: '', since: '24', q: '', expanded: new Set() };

    function _esc(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function _fmtTime(ts) {
        if (!ts) return '-';
        try {
            const d = new Date(ts);
            if (isNaN(d.getTime())) return ts;
            return d.toLocaleString('tr-TR', { hour12: false });
        } catch (e) { return ts; }
    }

    function _lvlClass(level) {
        if (level === 'CRITICAL') return 'em-lvl-critical';
        if (level === 'WARNING') return 'em-lvl-warning';
        return 'em-lvl-error';
    }

    async function _loadStats() {
        const wrap = document.getElementById('errorMonitorStats');
        if (!wrap) return;
        try {
            const since = state.since || 720;
            const res = await window.vyraFetch(`/system/errors/stats?since_hours=${encodeURIComponent(since)}`);
            const bl = (res && res.by_level) || {};
            const crit = bl.CRITICAL || 0, err = bl.ERROR || 0, warn = bl.WARNING || 0;
            const top = (res && res.top_paths) || [];
            let html = `<div class="em-stat em-lvl-critical"><span class="em-stat-n">${crit}</span> CRITICAL</div>`
                + `<div class="em-stat em-lvl-error"><span class="em-stat-n">${err}</span> ERROR</div>`
                + `<div class="em-stat em-lvl-warning"><span class="em-stat-n">${warn}</span> WARNING</div>`;
            if (top.length) {
                html += `<div class="em-stat-top">En çok hata: `
                    + top.slice(0, 3).map(t => `<code>${_esc(t.path)}</code> (${t.count})`).join(' · ')
                    + `</div>`;
            }
            wrap.innerHTML = html;
        } catch (e) {
            wrap.innerHTML = '';
        }
    }

    function _renderRow(it) {
        const id = it.id;
        const open = state.expanded.has(id);
        const lvlCls = _lvlClass(it.level);
        const head = `
            <div class="em-row-head" data-emid="${id}" role="button" tabindex="0" aria-expanded="${open}">
                <span class="em-badge ${lvlCls}">${_esc(it.level)}</span>
                <span class="em-time">${_esc(_fmtTime(it.ts))}</span>
                <span class="em-method">${_esc(it.request_method || '')}</span>
                <span class="em-path" title="${_esc(it.request_path || '')}">${_esc(it.request_path || '—')}</span>
                <span class="em-status">${it.response_status != null ? _esc(it.response_status) : ''}</span>
                <span class="em-msg" title="${_esc(it.message || '')}">${_esc(it.message || '')}</span>
                <i class="fa-solid fa-chevron-${open ? 'down' : 'right'} em-caret"></i>
            </div>`;
        const body = open ? `
            <div class="em-row-body">
                <div class="em-meta">
                    <span>request_id: <code class="em-rid">${_esc(it.request_id || '-')}</code></span>
                    <span>modül: ${_esc(it.module || '-')}</span>
                    <span>user_id: ${_esc(it.user_id != null ? it.user_id : '-')}</span>
                    <button class="em-copy" type="button" data-emcopy="${id}"><i class="fa-solid fa-copy"></i> request_id kopyala</button>
                </div>
                <pre class="em-traceback">${_esc(it.traceback || '(traceback kaydı yok)')}</pre>
            </div>` : '';
        return `<div class="em-row ${open ? 'is-open' : ''}">${head}${body}</div>`;
    }

    async function _load() {
        const list = document.getElementById('errorMonitorList');
        if (!list) return;
        list.innerHTML = '<div class="em-empty">Yükleniyor…</div>';
        const params = new URLSearchParams();
        if (state.level) params.set('level', state.level);
        if (state.since) params.set('since_hours', state.since);
        if (state.q) params.set('q', state.q);
        params.set('limit', '100');
        try {
            const res = await window.vyraFetch(`${ENDPOINT}?${params.toString()}`);
            const items = (res && res.items) || [];
            const present = new Set(items.map(i => i.id));
            Array.from(state.expanded).forEach(id => { if (!present.has(id)) state.expanded.delete(id); });
            if (!items.length) {
                list.innerHTML = '<div class="em-empty"><i class="fa-solid fa-circle-check"></i> Bu filtrede hata kaydı yok.</div>';
            } else {
                const more = res.total > items.length ? ` (son ${items.length} gösteriliyor)` : '';
                list.innerHTML = `<div class="em-count">${res.total} kayıt${more}</div>` + items.map(_renderRow).join('');
            }
            _loadStats();
        } catch (e) {
            list.innerHTML = `<div class="em-empty em-error">Hatalar yüklenemedi: ${_esc((e && e.message) || 'bilinmeyen hata')}</div>`;
        }
    }

    function _toggle(idStr) {
        const id = parseInt(idStr, 10);
        if (state.expanded.has(id)) state.expanded.delete(id); else state.expanded.add(id);
        _load();
    }

    function _bind() {
        const list = document.getElementById('errorMonitorList');
        if (list && !list._emBound) {
            list._emBound = true;
            list.addEventListener('click', (e) => {
                const copyBtn = e.target.closest('[data-emcopy]');
                if (copyBtn) {
                    e.stopPropagation();
                    const row = copyBtn.closest('.em-row');
                    const rid = row && row.querySelector('.em-rid');
                    if (rid && navigator.clipboard) navigator.clipboard.writeText(rid.textContent || '');
                    if (typeof window.showToast === 'function') window.showToast('request_id kopyalandı', 'success');
                    return;
                }
                const head = e.target.closest('.em-row-head');
                if (head && head.dataset.emid) _toggle(head.dataset.emid);
            });
            list.addEventListener('keydown', (e) => {
                const head = e.target.closest && e.target.closest('.em-row-head');
                if (head && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    if (head.dataset.emid) _toggle(head.dataset.emid);
                }
            });
        }
        const bindOnce = (elId, evt, fn) => {
            const el = document.getElementById(elId);
            if (el && !el._emBound) { el._emBound = true; el.addEventListener(evt, fn); }
        };
        bindOnce('errMonRefresh', 'click', _load);
        bindOnce('errMonLevel', 'change', () => { state.level = document.getElementById('errMonLevel').value; _load(); });
        bindOnce('errMonSince', 'change', () => { state.since = document.getElementById('errMonSince').value; _load(); });
        const search = document.getElementById('errMonSearch');
        if (search && !search._emBound) {
            search._emBound = true;
            let t = null;
            search.addEventListener('input', () => {
                state.q = search.value.trim();
                clearTimeout(t);
                t = setTimeout(_load, 350);
            });
        }
        bindOnce('errMonSearchClear', 'click', () => {
            const s = document.getElementById('errMonSearch');
            if (s) s.value = '';
            state.q = '';
            _load();
        });
    }

    function load() {
        _bind();
        _load();
    }

    return { load };
})();
