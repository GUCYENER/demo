/**
 * VYRA — DB Source Selector (v3.20.0 / Faz 1f)
 * =============================================
 * "Veritabanında Ara" modunda kullanıcının yetkili olduğu veri kaynaklarını
 * chip-tabanlı tek-seçimli (radio group) UI'da gösterir. Seçim aktif olduğunda
 * dialog gönderiminde `source_id` payload'a eklenir.
 *
 * Exposed API: window.DbSourceSelector
 *   load(force?)             → /api/data-sources/ çağırır, chip'leri render eder
 *   show() / hide()          → DB modu/diğer modlar arası geçişlerde
 *   getSelectedSourceId()    → seçili kaynak ID (null olabilir)
 *   getSelectedSourceName()  → seçili kaynak adı (label için)
 *   setSelectedSourceId(id)  → programatik seçim (örn. localStorage restore)
 *   isReady()                → en az bir kaynak yüklendi mi
 *   onChange(cb)             → seçim değişikliğinde dispatch
 *
 * HEBE:
 *   - role="radiogroup", her chip role="radio" + aria-checked
 *   - Klavye: Arrow / Home / End / Enter|Space
 *   - Empty state ve loading state ayrı görsel
 *   - Tüm renkler CSS variable (no hard-coded hex)
 */
(function () {
    'use strict';

    const STORAGE_KEY = 'vyra_selected_source_id';
    const API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api';

    // ---- State ----
    let sources = [];           // [{id, name, db_type, company_name, ...}]
    let selectedId = null;
    let loadPromise = null;     // in-flight load (dedup)
    let lastError = null;
    const changeListeners = new Set();

    // ---- Helpers ----
    function $bar() { return document.getElementById('dbSourceBar'); }
    function $chips() { return document.getElementById('dbSourceChips'); }
    function $status() { return document.getElementById('dbSourceStatus'); }

    function dispatch() {
        for (const cb of changeListeners) {
            try { cb(selectedId, getSelectedSourceName()); } catch (e) { console.error('[DbSourceSelector] listener error:', e); }
        }
    }

    function getSelectedSourceName() {
        const s = sources.find(x => x.id === selectedId);
        return s ? (s.name || `#${s.id}`) : null;
    }

    function persist() {
        try {
            if (selectedId != null) localStorage.setItem(STORAGE_KEY, String(selectedId));
            else localStorage.removeItem(STORAGE_KEY);
        } catch (_) { /* private mode vb. — yok say */ }
    }

    function restorePersisted() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (raw) {
                const n = parseInt(raw, 10);
                if (!Number.isNaN(n)) return n;
            }
        } catch (_) {}
        return null;
    }

    // ---- Render ----
    function renderLoading() {
        const chips = $chips(); if (!chips) return;
        chips.innerHTML = '<span class="dsb-skeleton" aria-hidden="true"></span><span class="dsb-skeleton" aria-hidden="true"></span>';
        const st = $status(); if (st) { st.textContent = 'Yükleniyor…'; st.dataset.state = 'loading'; }
    }

    function renderError(msg) {
        const chips = $chips(); if (!chips) return;
        chips.innerHTML = '';
        const st = $status(); if (st) { st.textContent = msg; st.dataset.state = 'error'; }
    }

    function renderEmpty() {
        const chips = $chips(); if (!chips) return;
        chips.innerHTML = '';
        const st = $status();
        if (st) {
            st.textContent = 'Yetkili olduğunuz bir veri kaynağı yok. Yöneticinizden erişim talep edin.';
            st.dataset.state = 'empty';
        }
    }

    function renderChips() {
        const chips = $chips(); if (!chips) return;
        const st = $status(); if (st) { st.textContent = ''; st.dataset.state = 'ok'; }

        chips.innerHTML = '';
        for (const s of sources) {
            const isSel = (s.id === selectedId);
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'dsb-chip' + (isSel ? ' selected' : '');
            btn.dataset.sourceId = String(s.id);
            btn.setAttribute('role', 'radio');
            btn.setAttribute('aria-checked', isSel ? 'true' : 'false');
            btn.setAttribute('tabindex', isSel || (selectedId == null && s === sources[0]) ? '0' : '-1');
            btn.setAttribute('aria-label', `Veri kaynağı: ${s.name}${s.company_name ? ' / ' + s.company_name : ''}`);

            const dot = document.createElement('span');
            dot.className = 'dsb-chip-dot';
            dot.setAttribute('aria-hidden', 'true');

            const lbl = document.createElement('span');
            lbl.className = 'dsb-chip-label';
            lbl.textContent = s.name || `#${s.id}`;

            btn.appendChild(dot);
            btn.appendChild(lbl);
            btn.addEventListener('click', () => selectById(s.id));
            btn.addEventListener('keydown', onChipKeydown);
            chips.appendChild(btn);
        }
    }

    function onChipKeydown(ev) {
        const list = Array.from($chips()?.querySelectorAll('.dsb-chip') || []);
        if (list.length === 0) return;
        const i = list.indexOf(ev.currentTarget);
        if (i < 0) return;

        let nextIdx = -1;
        switch (ev.key) {
            case 'ArrowRight': case 'ArrowDown':
                nextIdx = (i + 1) % list.length; break;
            case 'ArrowLeft': case 'ArrowUp':
                nextIdx = (i - 1 + list.length) % list.length; break;
            case 'Home': nextIdx = 0; break;
            case 'End': nextIdx = list.length - 1; break;
            case 'Enter': case ' ':
                ev.preventDefault();
                const sid = parseInt(ev.currentTarget.dataset.sourceId, 10);
                if (!Number.isNaN(sid)) selectById(sid);
                return;
            default: return;
        }
        if (nextIdx >= 0) {
            ev.preventDefault();
            list[nextIdx].focus();
        }
    }

    function selectById(id) {
        if (id === selectedId) return;
        const exists = sources.some(s => s.id === id);
        if (!exists) return;
        selectedId = id;
        persist();
        renderChips();
        dispatch();
    }

    // ---- Load ----
    async function load(force) {
        if (loadPromise && !force) return loadPromise;
        const bar = $bar();
        if (bar) renderLoading();

        loadPromise = (async () => {
            try {
                // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
                const data = await window.vyraFetch('/data-sources/');
                sources = Array.isArray(data) ? data : [];
                lastError = null;

                // Persisted selection geçerli mi?
                const persisted = restorePersisted();
                if (persisted != null && sources.some(s => s.id === persisted)) {
                    selectedId = persisted;
                } else if (sources.length === 1) {
                    // Tek kaynak varsa otomatik seç (UX)
                    selectedId = sources[0].id;
                    persist();
                } else {
                    selectedId = null;
                    persist();
                }

                if (sources.length === 0) renderEmpty();
                else renderChips();
                dispatch();
            } catch (e) {
                lastError = String(e && e.message ? e.message : e);
                console.error('[DbSourceSelector] load hatası:', e);
                renderError('Veri kaynakları yüklenemedi. Tekrar deneyin.');
                dispatch();
            } finally {
                loadPromise = null;
            }
        })();
        return loadPromise;
    }

    // ---- Visibility ----
    function show() {
        const bar = $bar();
        if (bar) bar.removeAttribute('hidden');
        if (sources.length === 0 && !loadPromise) load();
    }

    function hide() {
        const bar = $bar();
        if (bar) bar.setAttribute('hidden', '');
    }

    function isReady() {
        return sources.length > 0;
    }

    function onChange(cb) {
        if (typeof cb === 'function') changeListeners.add(cb);
        return () => changeListeners.delete(cb);
    }

    // ---- Public API ----
    window.DbSourceSelector = {
        load,
        show,
        hide,
        isReady,
        onChange,
        getSelectedSourceId: () => selectedId,
        getSelectedSourceName,
        setSelectedSourceId: selectById,
        // Debug/test
        _state: () => ({ sources: sources.slice(), selectedId, lastError }),
    };
})();
