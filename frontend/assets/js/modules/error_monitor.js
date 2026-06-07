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
    const state = { level: '', since: '24', q: '', expanded: new Set(), selected: new Set(), allFiltered: false, items: [], total: 0 };
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
        if (level === 'INFO') return 'em-lvl-info';
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
            const crit = bl.CRITICAL || 0, err = bl.ERROR || 0, warn = bl.WARNING || 0, info = bl.INFO || 0;
            const top = (res && res.top_paths) || [];
            let html = `<div class="em-stat em-lvl-critical"><span class="em-stat-n">${crit}</span> CRITICAL</div>`
                + `<div class="em-stat em-lvl-error"><span class="em-stat-n">${err}</span> ERROR</div>`
                + `<div class="em-stat em-lvl-warning"><span class="em-stat-n">${warn}</span> WARNING</div>`
                + `<div class="em-stat em-lvl-info"><span class="em-stat-n">${info}</span> INFO</div>`;
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
                <input type="checkbox" class="em-check" data-rowid="${id}" ${(state.allFiltered || state.selected.has(id)) ? 'checked' : ''} aria-label="Bu kaydı dışa aktarım için seç">
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
            _updateExportBar();
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
        _updateExportBar();
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
            Array.from(state.selected).forEach(id => { if (!present.has(id)) state.selected.delete(id); });
            if (!append) { state.selected.clear(); state.allFiltered = false; }  // v3.76.5: yeni filtre/yenile → seçim sıfır
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

    function _updateExportBar() {
        const btn = document.getElementById('errMonExport');
        if (btn) {
            if (state.allFiltered) {
                // "filtreli tümü" — yüklü 100 değil, DB'deki TÜM filtreli kayıt sayısı (state.total)
                btn.disabled = !state.total;
                btn.innerHTML = `<i class="fa-solid fa-file-excel"></i> Tümünü İndir (${state.total})`;
            } else {
                const n = state.selected.size;
                btn.disabled = n === 0;
                btn.innerHTML = `<i class="fa-solid fa-file-excel"></i> Seçilenleri İndir${n ? ` (${n})` : ''}`;
            }
        }
        const all = document.getElementById('errMonSelectAll');
        if (all) {
            all.checked = state.allFiltered;
            all.indeterminate = !state.allFiltered && state.selected.size > 0;
        }
    }

    // v3.76.5: Hata İzleme export → backend POST /api/system/errors/export (FİLTREYE UYAN TÜM kayıtlar +
    // TAM detay/full traceback). allFiltered → filtre gönder (backend DB'den tümünü çeker, yüklü 100 değil);
    // değilse seçili id'ler. Eski client-satır + /api/db/export/excel (500-cap, kısmi) yaklaşımı kaldırıldı.
    async function _exportSelected() {
        let body, count;
        if (state.allFiltered) {
            body = {
                level: state.level || null,
                q: state.q || null,
                since_hours: state.since ? parseInt(state.since, 10) : null,
            };
            count = state.total;
        } else {
            const ids = Array.from(state.selected);
            if (!ids.length) {
                if (typeof window.showToast === 'function') window.showToast('Önce kayıt seçin ya da "Tümünü seç"', 'info');
                return;
            }
            body = { ids };
            count = ids.length;
        }
        const token = localStorage.getItem('access_token')
            || localStorage.getItem('vyra_access_token')
            || localStorage.getItem('token') || '';
        const btn = document.getElementById('errMonExport');
        try {
            if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Hazırlanıyor…'; }
            const resp = await fetch('/api/system/errors/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                let detail = 'HTTP ' + resp.status;
                try { const j = await resp.json(); detail = (j && (j.detail || j.message)) || detail; } catch (_) { /* blob yanıtı */ }
                throw new Error(detail);
            }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'hata_izleme_' + Date.now() + '.xlsx';
            document.body.appendChild(a); a.click();
            setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 2000);
            if (typeof window.showToast === 'function') window.showToast((count || '') + ' kayıt Excel olarak indirildi', 'success');
        } catch (e) {
            if (typeof window.showToast === 'function') window.showToast('Dışa aktarma başarısız: ' + ((e && e.message) || ''), 'error');
        } finally {
            if (btn) _updateExportBar();   // label + disabled durumunu seçime göre geri yükle
        }
    }

    function _bind() {
        const list = document.getElementById('errorMonitorList');
        if (list && !list._emBound) {
            list._emBound = true;
            list.addEventListener('click', (e) => {
                if (e.target.closest('.em-check')) return;   // seçim kutusu: 'change'te işlenir, satır toggle YOK
                const copyBtn = e.target.closest('[data-emcopy]');
                if (copyBtn) { e.stopPropagation(); _copyRid(copyBtn.dataset.emcopy); return; }
                const head = e.target.closest('.em-row-head');
                if (head && head.dataset.emid) _toggle(head.dataset.emid);
            });
            list.addEventListener('change', (e) => {
                const chk = e.target.closest('.em-check');
                if (!chk) return;
                if (state.allFiltered) {
                    // v3.76.5: "filtreli tümü" modundan çık → görünür kutuların güncel haline geç (tek satır oynanınca)
                    state.allFiltered = false;
                    state.selected = new Set(
                        Array.from(list.querySelectorAll('.em-check'))
                            .filter(c => c.checked).map(c => parseInt(c.dataset.rowid, 10))
                    );
                } else {
                    const id = parseInt(chk.dataset.rowid, 10);
                    if (chk.checked) state.selected.add(id); else state.selected.delete(id);
                }
                _updateExportBar();
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
        bindOnce('errMonSelectAll', 'change', () => {
            const all = document.getElementById('errMonSelectAll');
            // v3.76.5: "Tümünü seç" = FİLTREYE UYAN TÜM kayıtlar (yalnız yüklü 100 değil) → indirme DB'den tümünü çeker
            state.allFiltered = !!(all && all.checked);
            state.selected.clear();
            _renderAll();   // satır kutularını + export bar'ı tazele
        });
        bindOnce('errMonExport', 'click', _exportSelected);
    }

    function load() {
        _bind();
        _load(false);
    }

    return { load };
})();
