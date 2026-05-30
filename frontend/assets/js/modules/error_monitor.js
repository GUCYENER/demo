/* -------------------------------
   VYRA - Error Monitor Module (v3.38.3)
   Sistem Parametreleri → "Hata İzleme" sekmesi.
   GET /api/system/errors (+ /errors/stats) — tam traceback + request_id, admin-only.
   vyraFetch /api prefix'i kendi ekler → burada '/system/...' path tutulur.
-------------------------------- */
window.ErrorMonitorModule = (function () {
    'use strict';

    const ENDPOINT = '/system/errors';
    const PAGE = 100;
    const state = { level: '', since: '24', q: '', expanded: new Set(), items: [], total: 0 };
    let _seq = 0;        // race guard — eski yanıtları yok say
    let _searchTimer = null;

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

    function _sinceParam() {
        // liste ve stats AYNI pencereyi kullanır (boş = tüm zamanlar)
        return state.since ? `&since_hours=${encodeURIComponent(state.since)}` : '';
    }

    async function _loadStats() {
        const wrap = document.getElementById('errorMonitorStats');
        if (!wrap) return;
        try {
            const res = await window.vyraFetch(`/system/errors/stats?_=1${_sinceParam()}`);
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

    function _rowHtml(it) {
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
        return `<div class="em-row ${open ? 'is-open' : ''}" data-rowid="${id}">${head}${body}</div>`;
    }

    function _renderAll() {
        const list = document.getElementById('errorMonitorList');
        if (!list) return;
        if (!state.items.length) {
            list.innerHTML = '<div class="em-empty"><i class="fa-solid fa-circle-check"></i> Bu filtrede hata kaydı yok.</div>';
            return;
        }
        const shown = state.items.length;
        const more = state.total > shown
            ? `<button id="errMonMore" class="btn-secondary em-more" type="button">Daha fazla yükle (${shown}/${state.total})</button>`
            : '';
        list.innerHTML = `<div class="em-count">${state.total} kayıt${state.total > shown ? ` · ${shown} gösteriliyor` : ''}</div>`
            + state.items.map(_rowHtml).join('')
            + (more ? `<div class="em-more-wrap">${more}</div>` : '');
        const moreBtn = document.getElementById('errMonMore');
        if (moreBtn) moreBtn.addEventListener('click', () => _load(true));
    }

    async function _load(append) {
        const list = document.getElementById('errorMonitorList');
        if (!list) return;
        const mySeq = ++_seq;            // race guard
        const offset = append ? state.items.length : 0;
        if (!append) list.innerHTML = '<div class="em-empty">Yükleniyor…</div>';
        const params = new URLSearchParams();
        if (state.level) params.set('level', state.level);
        if (state.since) params.set('since_hours', state.since);
        if (state.q) params.set('q', state.q);
        params.set('limit', String(PAGE));
        params.set('offset', String(offset));
        try {
            const res = await window.vyraFetch(`${ENDPOINT}?${params.toString()}`);
            if (mySeq !== _seq) return;   // daha yeni bir istek başladı → bu yanıtı yok say
            const items = (res && res.items) || [];
            state.total = (res && res.total) || items.length;
            state.items = append ? state.items.concat(items) : items;
            // sadece mevcut id'ler için expanded tut
            const present = new Set(state.items.map(i => i.id));
            Array.from(state.expanded).forEach(id => { if (!present.has(id)) state.expanded.delete(id); });
            _renderAll();
            if (!append) _loadStats();
        } catch (e) {
            if (mySeq !== _seq) return;
            list.innerHTML = `<div class="em-empty em-error">Hatalar yüklenemedi: ${_esc((e && e.message) || 'bilinmeyen hata')}</div>`;
        }
    }

    function _toggle(idStr) {
        // IN-PLACE: yeniden fetch YOK, scroll kaybı YOK — sadece o satırı güncelle
        const id = parseInt(idStr, 10);
        if (state.expanded.has(id)) state.expanded.delete(id); else state.expanded.add(id);
        const it = state.items.find(x => x.id === id);
        const node = document.querySelector(`.em-row[data-rowid="${id}"]`);
        if (it && node) node.outerHTML = _rowHtml(it);
    }

    function _copyRid(id) {
        const it = state.items.find(x => x.id === parseInt(id, 10));
        const text = it && it.request_id;
        const ok = () => { if (typeof window.showToast === 'function') window.showToast('request_id kopyalandı', 'success'); };
        const fail = () => { if (typeof window.showToast === 'function') window.showToast('Kopyalanamadı — metni elle seçin', 'warning'); };
        if (!text) { if (typeof window.showToast === 'function') window.showToast('Bu kayıtta request_id yok', 'warning'); return; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(ok).catch(fail);
        } else {
            try {
                const ta = document.createElement('textarea');
                ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
                document.body.appendChild(ta); ta.select();
                const done = document.execCommand && document.execCommand('copy');
                document.body.removeChild(ta);
                done ? ok() : fail();
            } catch (e) { fail(); }
        }
    }

    function _bind() {
        const list = document.getElementById('errorMonitorList');
        if (list && !list._emBound) {
            list._emBound = true;
            list.addEventListener('click', (e) => {
                const copyBtn = e.target.closest('[data-emcopy]');
                if (copyBtn) { e.stopPropagation(); _copyRid(copyBtn.dataset.emcopy); return; }
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
        bindOnce('errMonRefresh', 'click', () => _load(false));
        bindOnce('errMonLevel', 'change', () => { state.level = document.getElementById('errMonLevel').value; _load(false); });
        bindOnce('errMonSince', 'change', () => { state.since = document.getElementById('errMonSince').value; _load(false); });
        const search = document.getElementById('errMonSearch');
        if (search && !search._emBound) {
            search._emBound = true;
            search.addEventListener('input', () => {
                state.q = search.value.trim();
                clearTimeout(_searchTimer);
                _searchTimer = setTimeout(() => _load(false), 350);
            });
        }
        bindOnce('errMonSearchClear', 'click', () => {
            const s = document.getElementById('errMonSearch');
            if (s) s.value = '';
            state.q = '';
            _load(false);
        });
    }

    function load() {
        _bind();
        _load(false);
    }

    return { load };
})();
