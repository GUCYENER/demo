/**
 * VYRA — Schema Picker (Faz 5e / v3.24.0)
 * =======================================
 * Kullanıcının "şemada hangi tabloları kullanmak istediğini" drag-drop
 * (ya da klavye) ile seçtiği UI. Seçim sonucu agentic query pipeline'a
 * `forced_tables` hint olarak gönderilir.
 *
 * Exposed API: window.SchemaPicker
 *   open(sourceId, opts)   → modal aç (opts.onSelect callback)
 *   close()                → modal kapat
 *   getSelected()          → [{schema, table}]
 *   isOpen()
 *
 * HEBE (SaaS standartları):
 *   - role="dialog" + aria-labelledby + aria-modal=true
 *   - Drag/drop'a paralel klavye: Enter=ekle, Delete=kaldır, ↑↓=gezin
 *   - Empty state component (illustration + cta)
 *   - Loading skeleton (spinner değil)
 *   - Tüm renkler CSS variable
 *   - Focus trap modal içinde
 */
(function () {
    'use strict';

    const API_BASE = (window.API_BASE_URL || 'http://localhost:8002') + '/api';
    const STORAGE_KEY = 'vyra_schema_picker_selected';

    // ---- State ----
    let currentSourceId = null;
    let availableTables = [];      // [{schema, table, business_name, column_count}]
    let selectedTables = [];       // [{schema, table}]
    let onSelectCallback = null;
    let opened = false;
    let dragIndex = -1;
    let focusedSide = 'available'; // 'available' | 'selected'
    let focusedIndex = 0;

    // ---- DOM ----
    function $modal() { return document.getElementById('schemaPickerModal'); }
    function $available() { return document.getElementById('schemaPickerAvailable'); }
    function $selected() { return document.getElementById('schemaPickerSelected'); }
    function $status() { return document.getElementById('schemaPickerStatus'); }
    function $search() { return document.getElementById('schemaPickerSearch'); }

    function ensureModal() {
        if (document.getElementById('schemaPickerModal')) return;
        const html = `
        <div id="schemaPickerModal" class="schema-picker-modal" role="dialog"
             aria-modal="true" aria-labelledby="schemaPickerTitle" hidden>
          <div class="schema-picker-backdrop" data-action="close"></div>
          <div class="schema-picker-dialog" role="document">
            <header class="schema-picker-header">
              <h2 id="schemaPickerTitle">Tablo Seç</h2>
              <button type="button" class="schema-picker-close" aria-label="Kapat" data-action="close">×</button>
            </header>
            <div class="schema-picker-toolbar">
              <input id="schemaPickerSearch" type="search" placeholder="Tablo ara…"
                     aria-label="Tablo ara" autocomplete="off"/>
              <span id="schemaPickerStatus" class="schema-picker-status" aria-live="polite"></span>
            </div>
            <div class="schema-picker-body">
              <section class="schema-picker-pane" aria-labelledby="schemaPickerAvailLabel">
                <h3 id="schemaPickerAvailLabel">Mevcut</h3>
                <ul id="schemaPickerAvailable" class="schema-picker-list"
                    role="listbox" aria-label="Mevcut tablolar" tabindex="0"></ul>
              </section>
              <section class="schema-picker-pane schema-picker-pane--drop"
                       aria-labelledby="schemaPickerSelLabel">
                <h3 id="schemaPickerSelLabel">Seçilen</h3>
                <ul id="schemaPickerSelected" class="schema-picker-list schema-picker-list--drop"
                    role="listbox" aria-label="Seçilen tablolar" tabindex="0"
                    data-drop="true"></ul>
              </section>
            </div>
            <footer class="schema-picker-footer">
              <button type="button" class="btn btn--secondary" data-action="clear">Temizle</button>
              <button type="button" class="btn btn--secondary" data-action="close">İptal</button>
              <button type="button" class="btn btn--primary" data-action="confirm">Uygula</button>
            </footer>
          </div>
        </div>`;
        const wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstElementChild);
        attachEvents();
    }

    function attachEvents() {
        const modal = $modal();
        modal.addEventListener('click', (e) => {
            const action = e.target.dataset.action;
            if (action === 'close') close();
            else if (action === 'clear') clearSelection();
            else if (action === 'confirm') confirm();
        });
        $search().addEventListener('input', renderAvailable);
        document.addEventListener('keydown', onKeyDown);

        const dropZone = $selected();
        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
        dropZone.addEventListener('drop', onDrop);

        $available().addEventListener('focus', () => { focusedSide = 'available'; updateFocusVisual(); });
        $selected().addEventListener('focus', () => { focusedSide = 'selected'; updateFocusVisual(); });
    }

    function onKeyDown(e) {
        if (!opened) return;
        if (e.key === 'Escape') { close(); return; }
        if (e.key === 'Tab') return; // browser default focus trap CSS ile sağlanır

        const list = focusedSide === 'available' ? filterAvailable() : selectedTables;
        if (e.key === 'ArrowDown') { focusedIndex = Math.min(focusedIndex + 1, list.length - 1); updateFocusVisual(); e.preventDefault(); }
        else if (e.key === 'ArrowUp') { focusedIndex = Math.max(focusedIndex - 1, 0); updateFocusVisual(); e.preventDefault(); }
        else if (e.key === 'Enter' || e.key === ' ') {
            if (focusedSide === 'available' && list[focusedIndex]) {
                addTable(list[focusedIndex]);
                e.preventDefault();
            }
        }
        else if (e.key === 'Delete' || e.key === 'Backspace') {
            if (focusedSide === 'selected' && list[focusedIndex]) {
                removeAt(focusedIndex);
                e.preventDefault();
            }
        }
    }

    function updateFocusVisual() {
        document.querySelectorAll('.schema-picker-item.focused').forEach(el => el.classList.remove('focused'));
        const list = focusedSide === 'available' ? $available() : $selected();
        const items = list.querySelectorAll('.schema-picker-item');
        if (items[focusedIndex]) {
            items[focusedIndex].classList.add('focused');
            items[focusedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    // ---- Data ----
    async function loadTables(sourceId) {
        $status().textContent = 'Yükleniyor…';
        $available().innerHTML = '<li class="schema-picker-skeleton" aria-hidden="true"></li>'.repeat(5);
        try {
            // Mevcut endpoint: GET /api/data-sources/{id}/discovered-schemas (sadece schemas+counts).
            // Detay için ds_db_objects'a dayanan generic list endpoint olmadığından
            // /api/data-sources/{id}/objects (varsayılan path). Yoksa boş.
            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            const data = await window.vyraFetch(`/data-sources/${sourceId}/objects?limit=500`);
            availableTables = (data.objects || data.tables || []).map(o => ({
                schema: o.schema_name || o.schema || '',
                table: o.object_name || o.table_name || o.name,
                business_name: o.business_name_tr || '',
                column_count: o.column_count || 0,
            })).filter(o => o.table);
            $status().textContent = `${availableTables.length} tablo`;
        } catch (e) {
            availableTables = [];
            $status().textContent = 'Tablo listesi alınamadı';
            console.warn('[SchemaPicker] load:', e);
        }
        renderAvailable();
        renderSelected();
    }

    // ---- Rendering ----
    function filterAvailable() {
        const q = ($search().value || '').toLowerCase().trim();
        const sel = new Set(selectedTables.map(t => `${t.schema}.${t.table}`.toLowerCase()));
        return availableTables
            .filter(t => !sel.has(`${t.schema}.${t.table}`.toLowerCase()))
            .filter(t => !q || `${t.schema}.${t.table}`.toLowerCase().includes(q) ||
                         (t.business_name || '').toLowerCase().includes(q));
    }

    function renderAvailable() {
        const list = $available();
        const filtered = filterAvailable();
        list.innerHTML = '';
        if (!filtered.length) {
            list.innerHTML = `<li class="schema-picker-empty">
                <span class="schema-picker-empty-icon" aria-hidden="true">📋</span>
                <p>Eşleşen tablo yok</p>
            </li>`;
            return;
        }
        filtered.forEach((t, i) => {
            const li = document.createElement('li');
            li.className = 'schema-picker-item';
            li.setAttribute('role', 'option');
            li.setAttribute('draggable', 'true');
            li.dataset.index = i;
            const full = t.schema ? `${t.schema}.${t.table}` : t.table;
            li.innerHTML = `
                <span class="schema-picker-item-main">${escapeHtml(full)}</span>
                ${t.business_name ? `<span class="schema-picker-item-sub">${escapeHtml(t.business_name)}</span>` : ''}
                <button type="button" class="schema-picker-add" aria-label="Ekle: ${escapeHtml(full)}">+</button>
            `;
            li.addEventListener('dragstart', (e) => { dragIndex = i; e.dataTransfer.effectAllowed = 'copy'; });
            li.addEventListener('click', () => addTable(t));
            list.appendChild(li);
        });
    }

    function renderSelected() {
        const list = $selected();
        list.innerHTML = '';
        if (!selectedTables.length) {
            list.innerHTML = `<li class="schema-picker-empty">
                <span class="schema-picker-empty-icon" aria-hidden="true">⬅</span>
                <p>Tablo eklemek için soldan sürükle veya tıkla</p>
            </li>`;
            return;
        }
        selectedTables.forEach((t, i) => {
            const li = document.createElement('li');
            li.className = 'schema-picker-item schema-picker-item--selected';
            li.setAttribute('role', 'option');
            const full = t.schema ? `${t.schema}.${t.table}` : t.table;
            li.innerHTML = `
                <span class="schema-picker-item-main">${escapeHtml(full)}</span>
                <button type="button" class="schema-picker-remove" aria-label="Kaldır: ${escapeHtml(full)}">×</button>
            `;
            li.querySelector('.schema-picker-remove').addEventListener('click', () => removeAt(i));
            list.appendChild(li);
        });
    }

    function onDrop(e) {
        e.preventDefault();
        $selected().classList.remove('drag-over');
        const filtered = filterAvailable();
        if (dragIndex >= 0 && filtered[dragIndex]) {
            addTable(filtered[dragIndex]);
        }
        dragIndex = -1;
    }

    function addTable(t) {
        const key = `${t.schema}.${t.table}`.toLowerCase();
        if (selectedTables.some(x => `${x.schema}.${x.table}`.toLowerCase() === key)) return;
        selectedTables.push({ schema: t.schema, table: t.table });
        renderAvailable();
        renderSelected();
        $status().textContent = `${selectedTables.length} tablo seçili`;
    }

    function removeAt(i) {
        selectedTables.splice(i, 1);
        renderAvailable();
        renderSelected();
        $status().textContent = `${selectedTables.length} tablo seçili`;
    }

    function clearSelection() {
        selectedTables = [];
        renderAvailable();
        renderSelected();
        $status().textContent = '0 tablo seçili';
    }

    function confirm() {
        try {
            sessionStorage.setItem(STORAGE_KEY + '_' + currentSourceId, JSON.stringify(selectedTables));
        } catch (_) { }
        if (typeof onSelectCallback === 'function') {
            try { onSelectCallback(selectedTables.slice()); } catch (e) { console.error('[SchemaPicker]', e); }
        }
        close();
    }

    // ---- Public ----
    function open(sourceId, opts = {}) {
        ensureModal();
        currentSourceId = sourceId;
        onSelectCallback = opts.onSelect || null;
        opened = true;
        // Restore prior selection
        try {
            const raw = sessionStorage.getItem(STORAGE_KEY + '_' + sourceId);
            selectedTables = raw ? JSON.parse(raw) : (opts.initial || []);
        } catch (_) { selectedTables = opts.initial || []; }
        $modal().hidden = false;
        $modal().setAttribute('data-open', 'true');
        $search().value = '';
        focusedSide = 'available';
        focusedIndex = 0;
        loadTables(sourceId).then(() => $search().focus());
    }

    function close() {
        opened = false;
        const m = $modal();
        if (m) { m.hidden = true; m.removeAttribute('data-open'); }
    }

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    window.SchemaPicker = {
        open, close,
        getSelected: () => selectedTables.slice(),
        isOpen: () => opened,
    };
})();
