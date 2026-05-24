/**
 * VYRA — Saved Reports Grid Module
 * =================================
 * Kullanıcının kayıtlı (tasarladığı) raporlarını kart grid olarak listeler.
 *
 * Public API:
 *   window.SavedReportsGrid.mount(rootEl, { onOpenReport, onNewReport })
 *   window.SavedReportsGrid.refresh()
 *   window.SavedReportsGrid.unmount()
 *
 * Brief: 2026-05-23_aki-kesfi-B_saved-reports-grid
 * Version: 1.0.0
 */

(function () {
    'use strict';

    // ─── State ───
    const API_BASE = '/api/db-smart';
    let _root = null;
    let _opts = { onOpenReport: null, onNewReport: null };
    let _searchTimer = null;
    let _currentChip = 'all'; // all | last7 | mostRun
    let _lastItems = [];

    // ─── Utils ───
    function _authHeaders() {
        const token = localStorage.getItem('access_token');
        const h = { 'Content-Type': 'application/json' };
        if (token) h['Authorization'] = 'Bearer ' + token;
        return h;
    }

    function _toast(msg, kind) {
        if (window.showToast) {
            try { window.showToast(msg, kind || 'info'); return; } catch (_) { /* noop */ }
        }
        // sessiz fallback (console)
        try { console.log('[SavedReportsGrid]', kind || 'info', msg); } catch (_) { /* noop */ }
    }

    function _qs(sel, root) { return (root || _root).querySelector(sel); }
    function _qsa(sel, root) { return Array.from((root || _root).querySelectorAll(sel)); }

    function _clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

    function _icon(name) {
        // basit inline SVG ikon havuzu (fa olmadığı kabulü için)
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        svg.classList.add('srg-icon');
        const path = document.createElementNS(ns, 'path');
        const paths = {
            plus: 'M12 5v14M5 12h14',
            search: 'M21 21l-4.35-4.35M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16z',
            empty: 'M3 7h18M3 12h18M3 17h18',
            chart: 'M3 3v18h18M7 14l4-4 4 4 5-5',
        };
        path.setAttribute('d', paths[name] || paths.empty);
        svg.appendChild(path);
        return svg;
    }

    // ─── Tarih formatı ───
    const MONTH_TR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];

    function _relativeTime(isoStr) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        if (isNaN(d.getTime())) return '';
        const now = new Date();
        const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
        if (diffSec < 60) return '<1dk önce';
        if (diffSec < 3600) return Math.floor(diffSec / 60) + 'dk önce';
        if (diffSec < 86400) return Math.floor(diffSec / 3600) + 'sa önce';
        // gün hesabı (takvim günü farkı)
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
        const startOfThat = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
        const diffDays = Math.round((startOfToday - startOfThat) / 86400000);
        if (diffDays === 1) return 'dün';
        if (diffDays > 1 && diffDays < 7) return diffDays + 'gün önce';
        return d.getDate() + ' ' + MONTH_TR[d.getMonth()];
    }

    function _absoluteISO(isoStr) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        if (isNaN(d.getTime())) return String(isoStr);
        try { return d.toISOString(); } catch (_) { return String(isoStr); }
    }

    // ─── DOM iskelet ───
    function _buildShell() {
        _clear(_root);

        const wrap = document.createElement('div');
        wrap.className = 'srg-root';

        // header
        const header = document.createElement('header');
        header.className = 'srg-header';
        const title = document.createElement('h2');
        title.className = 'srg-title';
        title.textContent = 'Tasarladığım Raporlar';
        header.appendChild(title);

        const tools = document.createElement('div');
        tools.className = 'srg-tools';

        const searchWrap = document.createElement('div');
        searchWrap.className = 'srg-search-wrap';

        const search = document.createElement('input');
        search.type = 'search';
        search.className = 'srg-search';
        search.placeholder = 'Rapor ara...';
        search.setAttribute('aria-label', 'Rapor arama');
        searchWrap.appendChild(search);

        const searchClear = document.createElement('button');
        searchClear.type = 'button';
        searchClear.className = 'srg-search-clear';
        searchClear.setAttribute('aria-label', 'Aramayı temizle');
        searchClear.setAttribute('tabindex', '-1');
        searchClear.hidden = true;
        searchClear.textContent = '\u00D7'; // ×
        searchWrap.appendChild(searchClear);

        tools.appendChild(searchWrap);

        const newBtn = document.createElement('button');
        newBtn.type = 'button';
        newBtn.className = 'srg-new-btn';
        newBtn.setAttribute('data-tooltip', 'Yeni keşif başlat');
        newBtn.setAttribute('aria-label', 'Yeni keşif başlat');
        newBtn.appendChild(_icon('plus'));
        const newLabel = document.createElement('span');
        newLabel.textContent = 'Yeni Keşif';
        newBtn.appendChild(newLabel);
        tools.appendChild(newBtn);

        header.appendChild(tools);
        wrap.appendChild(header);

        // chips
        const chipsRow = document.createElement('div');
        chipsRow.className = 'srg-chips';
        chipsRow.setAttribute('role', 'tablist');
        chipsRow.setAttribute('aria-label', 'Kategori filtresi');
        const chipDefs = [
            { id: 'all', label: 'Tümü' },
            { id: 'last7', label: 'Son 7 gün' },
            { id: 'mostRun', label: 'En çok çalıştırılan' },
        ];
        chipDefs.forEach((c) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'srg-chip' + (c.id === _currentChip ? ' is-active' : '');
            b.setAttribute('role', 'tab');
            b.setAttribute('aria-selected', c.id === _currentChip ? 'true' : 'false');
            b.dataset.chip = c.id;
            b.textContent = c.label;
            chipsRow.appendChild(b);
        });
        wrap.appendChild(chipsRow);

        // grid
        const grid = document.createElement('div');
        grid.className = 'srg-grid';
        grid.setAttribute('role', 'list');
        grid.setAttribute('aria-live', 'polite');
        grid.setAttribute('aria-busy', 'false');
        wrap.appendChild(grid);

        // empty placeholder
        const empty = document.createElement('div');
        empty.className = 'srg-empty hidden';
        wrap.appendChild(empty);

        _root.appendChild(wrap);

        // events
        const _syncClearVisibility = () => {
            const hasValue = !!(search.value && search.value.length > 0);
            searchClear.hidden = !hasValue;
            searchWrap.classList.toggle('is-filled', hasValue);
        };

        search.addEventListener('input', () => {
            _syncClearVisibility();
            if (_searchTimer) clearTimeout(_searchTimer);
            _searchTimer = setTimeout(() => { refresh(); }, 300);
        });

        search.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && search.value) {
                e.preventDefault();
                search.value = '';
                _syncClearVisibility();
                if (_searchTimer) clearTimeout(_searchTimer);
                refresh();
                search.focus();
            }
        });

        searchClear.addEventListener('click', (e) => {
            e.preventDefault();
            if (!search.value) return;
            search.value = '';
            _syncClearVisibility();
            if (_searchTimer) clearTimeout(_searchTimer);
            refresh();
            search.focus();
        });

        // initial state (input başlangıçta boş)
        _syncClearVisibility();

        newBtn.addEventListener('click', () => {
            if (typeof _opts.onNewReport === 'function') {
                try { _opts.onNewReport(); } catch (e) { console.error('[SavedReportsGrid] onNewReport error:', e); }
            }
        });

        chipsRow.addEventListener('click', (e) => {
            const t = e.target.closest('.srg-chip');
            if (!t) return;
            _currentChip = t.dataset.chip || 'all';
            _qsa('.srg-chip').forEach((c) => {
                const on = c.dataset.chip === _currentChip;
                c.classList.toggle('is-active', on);
                c.setAttribute('aria-selected', on ? 'true' : 'false');
            });
            _renderItems(_applyChipFilter(_lastItems));
        });
    }

    // ─── Skeleton ───
    function _renderSkeleton() {
        const grid = _qs('.srg-grid');
        const empty = _qs('.srg-empty');
        if (!grid) return;
        empty.classList.add('hidden');
        grid.setAttribute('aria-busy', 'true');
        _clear(grid);
        for (let i = 0; i < 6; i++) {
            const sk = document.createElement('div');
            sk.className = 'srg-skel-card';
            sk.setAttribute('aria-hidden', 'true');
            const sh1 = document.createElement('div'); sh1.className = 'srg-skel-line srg-skel-line--title'; sk.appendChild(sh1);
            const sh2 = document.createElement('div'); sh2.className = 'srg-skel-line'; sk.appendChild(sh2);
            const sh3 = document.createElement('div'); sh3.className = 'srg-skel-line srg-skel-line--short'; sk.appendChild(sh3);
            grid.appendChild(sk);
        }
    }

    // ─── Empty state ───
    function _renderEmpty() {
        const grid = _qs('.srg-grid');
        const empty = _qs('.srg-empty');
        if (!grid || !empty) return;
        _clear(grid);
        _clear(empty);

        const wrap = document.createElement('div');
        wrap.className = 'vyra-empty-state';

        const iconWrap = document.createElement('div');
        iconWrap.className = 'vyra-empty-state__icon';
        iconWrap.appendChild(_icon('chart'));
        wrap.appendChild(iconWrap);

        const h3 = document.createElement('h3');
        h3.className = 'vyra-empty-state__title';
        h3.textContent = 'Henüz kayıtlı raporun yok';
        wrap.appendChild(h3);

        const p = document.createElement('p');
        p.className = 'vyra-empty-state__desc';
        p.textContent = 'Yeni bir keşif başlatarak ilk raporunu oluştur. Tüm raporların burada görünecek.';
        wrap.appendChild(p);

        const cta = document.createElement('button');
        cta.type = 'button';
        cta.className = 'vyra-empty-state__cta srg-new-btn';
        cta.setAttribute('aria-label', 'Yeni keşif başlat');
        cta.appendChild(_icon('plus'));
        const ctaLabel = document.createElement('span');
        ctaLabel.textContent = 'Yeni Keşif';
        cta.appendChild(ctaLabel);
        cta.addEventListener('click', () => {
            if (typeof _opts.onNewReport === 'function') {
                try { _opts.onNewReport(); } catch (e) { console.error('[SavedReportsGrid] onNewReport error:', e); }
            }
        });
        wrap.appendChild(cta);

        empty.appendChild(wrap);
        empty.classList.remove('hidden');
    }

    // ─── Kart ───
    function _renderCard(report) {
        const card = document.createElement('article');
        card.className = 'srg-card';
        card.setAttribute('role', 'listitem');
        card.setAttribute('tabindex', '0');
        card.dataset.reportId = String(report.id);

        // head
        const head = document.createElement('header');
        head.className = 'srg-card-head';

        const metric = document.createElement('span');
        metric.className = 'srg-card-metric-badge';
        const metricKey = report.metric_key || report.metric || '';
        if (metricKey) {
            metric.textContent = String(metricKey);
        } else {
            metric.textContent = '—';
            metric.classList.add('srg-card-metric-badge--muted');
        }
        head.appendChild(metric);

        const title = document.createElement('h3');
        title.className = 'srg-card-title';
        title.textContent = report.name || 'Adsız Rapor';
        head.appendChild(title);

        card.appendChild(head);

        // desc
        const desc = document.createElement('p');
        desc.className = 'srg-card-desc';
        desc.textContent = report.description || '';
        card.appendChild(desc);

        // foot
        const foot = document.createElement('footer');
        foot.className = 'srg-card-foot';

        const time = document.createElement('span');
        time.className = 'srg-card-time';
        const ts = report.updated_at || report.last_run_at || report.created_at;
        time.textContent = _relativeTime(ts);
        const absIso = _absoluteISO(ts);
        if (absIso) {
            time.setAttribute('data-tooltip', absIso);
            time.setAttribute('title', absIso);
        }
        foot.appendChild(time);

        const tagsWrap = document.createElement('span');
        tagsWrap.className = 'srg-card-tags';
        const tags = Array.isArray(report.tags) ? report.tags : [];
        tags.slice(0, 3).forEach((t) => {
            const chip = document.createElement('span');
            chip.className = 'srg-tag';
            chip.textContent = String(t);
            tagsWrap.appendChild(chip);
        });
        if (tags.length > 3) {
            const more = document.createElement('span');
            more.className = 'srg-tag srg-tag--more';
            more.textContent = '+' + (tags.length - 3);
            tagsWrap.appendChild(more);
        }
        foot.appendChild(tagsWrap);

        card.appendChild(foot);

        // events
        const openHandler = () => {
            if (typeof _opts.onOpenReport === 'function') {
                try { _opts.onOpenReport(report.id); } catch (e) { console.error('[SavedReportsGrid] onOpenReport error:', e); }
            }
        };
        card.addEventListener('click', openHandler);
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openHandler();
            }
        });

        return card;
    }

    // ─── Liste filtresi (chip) ───
    function _applyChipFilter(items) {
        if (!Array.isArray(items)) return [];
        if (_currentChip === 'last7') {
            const cutoff = Date.now() - 7 * 86400000;
            return items.filter((r) => {
                const t = r.updated_at || r.last_run_at || r.created_at;
                if (!t) return false;
                const d = new Date(t);
                return !isNaN(d.getTime()) && d.getTime() >= cutoff;
            });
        }
        if (_currentChip === 'mostRun') {
            const sorted = items.slice().sort((a, b) => (b.run_count || 0) - (a.run_count || 0));
            return sorted;
        }
        return items;
    }

    function _renderItems(items) {
        const grid = _qs('.srg-grid');
        const empty = _qs('.srg-empty');
        if (!grid) return;
        grid.setAttribute('aria-busy', 'false');
        _clear(grid);

        if (!items || items.length === 0) {
            _renderEmpty();
            return;
        }
        empty.classList.add('hidden');
        items.forEach((r) => grid.appendChild(_renderCard(r)));
    }

    // ─── Fetch ───
    async function _fetchList() {
        const search = _qs('.srg-search');
        const q = (search && search.value ? search.value.trim() : '');
        const params = new URLSearchParams();
        params.set('limit', '24');
        if (q) params.set('q', q);
        // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
        // v3.34.1 BUG-4.2: Endpoint backend'de `/api/db-smart/saved-reports`
        // altında mount edildi (db_smart_api router prefix). vyraFetch zaten
        // `/api` ekliyor → burada `/db-smart/saved-reports` kullanılmalı.
        // Önceki `/saved-reports` 404 dönüyordu.
        const data = await window.vyraFetch('/db-smart/saved-reports?' + params.toString());
        return Array.isArray(data && data.items) ? data.items : [];
    }

    // ─── Public ───
    function mount(rootEl, opts) {
        if (!rootEl) {
            console.error('[SavedReportsGrid] mount: rootEl gerekli');
            return;
        }
        _root = rootEl;
        _opts = Object.assign({ onOpenReport: null, onNewReport: null }, opts || {});
        _buildShell();
        refresh();
        SavedReportsGrid._instance = { rootEl: _root };
    }

    function refresh() {
        if (!_root) return;
        _renderSkeleton();
        _fetchList()
            .then((items) => {
                _lastItems = items || [];
                _renderItems(_applyChipFilter(_lastItems));
            })
            .catch((err) => {
                console.error('[SavedReportsGrid] fetch error:', err);
                const grid = _qs('.srg-grid');
                if (grid) {
                    grid.setAttribute('aria-busy', 'false');
                    _clear(grid);
                }
                _renderEmpty();
                _toast('Raporlar yüklenemedi: ' + (err && err.message ? err.message : 'bilinmeyen hata'), 'error');
            });
    }

    function unmount() {
        if (_searchTimer) { clearTimeout(_searchTimer); _searchTimer = null; }
        if (_root) { _clear(_root); }
        _root = null;
        _opts = { onOpenReport: null, onNewReport: null };
        _lastItems = [];
        SavedReportsGrid._instance = null;
    }

    const SavedReportsGrid = {
        mount: mount,
        refresh: refresh,
        unmount: unmount,
        _instance: null,
    };

    window.SavedReportsGrid = SavedReportsGrid;
})();
