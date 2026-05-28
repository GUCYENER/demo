/**
 * VYRA Akıllı Veri Keşfi — DB Smart Wizard (v3.35.0)
 * =============================================================
 * 4-adım sihirbaz (eski "İlişkiler" step'i kaldırıldı — FK seçimi
 * step 1'in (Tablo Seç) picker right pane'inde yapılıyor):
 *   0) Tablo Seç (eligibility hybrid search + FK picker)
 *   2) Metrik (library + custom)            ← UI: "2 · Metrik"
 *   3) Filtre (column-aware)                ← UI: "3 · Filtre"
 *   4) Önizleme (SQL + cost + AST editor)   ← UI: "4 · Önizleme"
 *
 * NOT: data-step / id değerleri korundu (panel id dswStep0, dswStep2,
 * dswStep3, dswStep4) — JS step navigation _STEPS sırası ile gezer.
 *
 * Backend: /api/db-smart/* (12 endpoint)
 * HEBE 5c gate: feature_key 'aki_kesif' guard'ı feature_permissions_module.js'te.
 */
(function () {
    'use strict';

    // v3.34.0: vyraFetch /api prefix'i kendi ekliyor — burada sadece path tutuyoruz.
    const API_BASE = '/db-smart';
    // v3.35.0: data-step indeksleri stabil tutuldu; step 1 ("İlişkiler") kaldırıldı.
    // Navigation _STEPS sırasını izler; total label'ı her zaman _STEPS.length.
    const _STEPS = [0, 2, 3, 4];
    const TOTAL_STEPS = _STEPS.length;

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
        // F14 (HEBE+HERMES+ATHENA): multi-metric akordion seçimi.
        //   - selectedMetrics: Set<metric_key> (boş geçilebilir).
        //   - _metricsIndex: Map<metric_key, item> — son _loadMetrics yanıtının düz hashi.
        //   - _metricCategories: { [cat]: items[] } — render gruplaması.
        //   - metric (tekil) geriye uyum için son seçileni tutar (F9 payload).
        selectedMetrics: new Set(),
        _metricsIndex: {},
        _metricCategories: {},
        filters: [],
        reportColumns: [],                // EDIT9 (HEBE+HERMES+ATHENA): ordered list of
                                          //   { column_name, semantic_type, table_name, label }
                                          //   shown in step-3 DnD; honoured by _buildWizardState.
        _columnCatalog: [],               // EDIT9: last fetched catalog for step-3 (for LLM payload + re-render).
        // F8 (APOLLO+HEBE+ATHENA): LLM suggestion slots, max 3 (LRU). Each:
        //   { id: "s<n>", columns: [...same shape as reportColumns...], rationale: str, appliedAt: number|null }
        suggestions: [],
        _suggestionCounter: 0,            // monotonic for unique slot id
        // F8: free-text user prompt consumed by F9 (/generate-report)
        userNote: '',
        currentAst: null,                 // P20-D: server-canonical AST snapshot
        _lastFocusEl: null,               // HEBE Gate: return-focus target
        lastGeneratedSql: null,           // v3.36.0 F10: Önizleme'den son üretilen SQL (save flow için)
        // v3.37.3 (bulgular-2 / Bulgu 7a, 8): kayıtlı bir raporu düzenleme modunda
        // açtıysak burada id tutulur. _saveCurrentReport bunu görürse POST yerine
        // PATCH (update) yapar; modal kapanışında null'a düşer.
        editingReportId: null,
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

    // FIX5 P2 (ATHENA+HEBE): API error → user-facing i18n message mapper
    // 401/403/404 ayrımı için tek helper — tüm catch blokları çağırır.
    function _mapApiError(e) {
        const raw = (e && (e.status || (e.message || ''))) || '';
        const m = String(raw).match(/(\d{3})/);
        const status = m ? m[1] : null;
        const msg = (e && e.message) || '';
        if (status === '403') return _t('wizard.error.permission_denied');
        if (status === '401') return _t('wizard.error.auth_expired');
        if (status === '404') return _t('wizard.error.not_found');
        return _t('wizard.error.generic', { message: msg });
    }

    // FIX5 P2 (ATHENA+HEBE): Body scroll-lock ref-counter — modal stacking safe.
    // Önceki: tek boolean → ikinci modal `overflow: hidden`'i prev olarak okur,
    // ilk close restore'da yanlış değere döner. Counter pattern üst üste açılışları
    // doğru yönetir.
    const _BodyScrollLock = (function () {
        let count = 0;
        let savedOverflow = null;
        return {
            lock: function () {
                if (count === 0) savedOverflow = document.body.style.overflow;
                count += 1;
                document.body.style.overflow = 'hidden';
            },
            unlock: function () {
                if (count === 0) return;
                count -= 1;
                if (count === 0) {
                    document.body.style.overflow = (savedOverflow != null) ? savedOverflow : '';
                    savedOverflow = null;
                }
            },
        };
    })();

    // v3.34.0: vyraFetch delegate — Auth + JSON + friendly error helper'da.
    // Eski caller'lar `body: JSON.stringify(...)` geçiyor; vyraFetch'in tekrar
    // stringify etmemesi için string body'i geri parse ederiz (org_utils paterni).
    async function _fetchJson(url, opts) {
        opts = opts || {};
        const method = (opts.method || 'GET').toUpperCase();
        let body = opts.body != null ? opts.body : null;
        if (typeof body === 'string') {
            try { body = JSON.parse(body); } catch (_) { /* binary/text → ignore */ }
        }
        return window.vyraFetch(url, { method, body, auth: true });
    }

    // ============================================
    // Step navigation
    // ============================================

    function _setStep(n, opts) {
        // v3.35.0: data-step indeksleri sürekli değil ([0,2,3,4]).
        // Geçerli yalnız _STEPS içindekiler — bilinmeyen indeksi reddet.
        const targetIdx = _STEPS.indexOf(n);
        if (targetIdx < 0) return;
        const currentIdx = _STEPS.indexOf(_state.currentStep);
        // F10b Fix 2 (ATHENA+HEBE): restore-path için forward-jump guard bypass.
        // _loadSavedReport step 0 → step 4 sıçraması yapıyor; jump guard'sız
        // restore tamamlanmazsa UI step 0'da kilitleniyor. force=true ile
        // validation by-pass koruma devre dışı (yalnız trusted caller).
        const force = !!(opts && opts.force);
        // FIX5 P2 (ATHENA+TYCHE): forward-skip engelle — kullanıcı ileri adıma
        // ancak bir sonraki _STEPS index'ine geçebilir (validation by-pass koruma).
        if (!force && currentIdx >= 0 && targetIdx > currentIdx + 1) return;
        // v3.37.3 (bulgular-2 / Bulgu 1 + 4a): forward-step validation.
        // Stepper-tab tıklaması doğrudan _setStep çağırdığı için "Next" disable
        // bypass edilebiliyordu. Şimdi her ileri geçişte ön-koşul kontrol edilir.
        if (!force && currentIdx >= 0 && targetIdx > currentIdx) {
            // Step 0 → 2 (Tablo Seç → Metrik): tablo seçili olmalı.
            if (n === 2 && _state.selectedTableId == null) {
                _notify(_t('wizard.toast.select_table_first'), 'warning');
                return;
            }
            // Step 3 → 4 (Filtre/Kolon → Önizleme): en az 1 kolon seçili olmalı.
            if (n === 4) {
                const cols = _state.reportColumns;
                if (!Array.isArray(cols) || cols.length === 0) {
                    _notify(_t('wizard.toast.select_columns_first'), 'warning');
                    return;
                }
            }
        }
        // FIX5 F1 (ATHENA): backward navigation → ileri adımlara ait state'i temizle
        // (preview→filter→metric→filter gezinince stale metric/filters görünmesin).
        if (currentIdx >= 0 && targetIdx < currentIdx) {
            if (n < 2) {
                _state.metric = null;
                // F14: multi-metric set'i de temizle (back-nav stale guard).
                if (_state.selectedMetrics && typeof _state.selectedMetrics.clear === 'function') {
                    _state.selectedMetrics.clear();
                } else {
                    _state.selectedMetrics = new Set();
                }
            }
            if (n < 3) {
                _state.filters = [];
                _state.reportColumns = [];
                // F8: step-3 scoped state — clear when navigating away from step-3 backwards.
                _state.suggestions = [];
                _state._suggestionCounter = 0;
                _state.userNote = '';
            }
        }
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
        if (progress) progress.textContent = _t('wizard.step.indicator', { current: targetIdx + 1, total: TOTAL_STEPS });
        const prev = document.getElementById('dswPrevBtn');
        const next = document.getElementById('dswNextBtn');
        if (prev) prev.disabled = (targetIdx === 0);
        // F22 (HEBE 2026-05-25): son adımda "İleri" butonu görsel olarak gizlenir
        // (sadece disabled değil) — kullanıcı bunu artık raporun bitti sinyali
        // olarak algılıyor; aksiyon "Çalıştır" ile sonuç modal'ında.
        if (next) {
            const isLast = (targetIdx === TOTAL_STEPS - 1);
            next.disabled = isLast;
            next.hidden = isLast;
            next.style.visibility = isLast ? 'hidden' : '';
        }
        // v3.30.0 P2: adım data fetch (lazy)
        if (typeof _onStepEnter === 'function') _onStepEnter(n);
        // v3.37.0 B5a (HEBE-FE 2026-05-25): Step 3'te kolon boşsa Next disable.
        try { _updateNextGuard(); } catch (e) { /* defansif */ }
    }

    // v3.37.0 B5a — Step 3 (Filtre / kolon seçimi) için Next butonu disable/enable.
    // Çağrı: _setStep sonrası + _addReportColumn / _removeReportColumn sonrası.
    function _updateNextGuard() {
        const next = document.getElementById('dswNextBtn');
        if (!next) return;
        // Step 4 son adımda Next zaten hidden (F22) → karışma.
        if (_state.currentStep !== 3) return;
        const empty = !Array.isArray(_state.reportColumns) || _state.reportColumns.length === 0;
        next.disabled = empty;
        next.classList.toggle('dsw-next-empty-guard', empty);
        next.setAttribute('aria-disabled', empty ? 'true' : 'false');
        if (empty) {
            next.setAttribute('title', 'En az bir kolon seçin');
        } else {
            next.removeAttribute('title');
        }
        // Hover/click handler — disabled butonda click event fire etmez (native),
        // bu yüzden ek bir mousedown listener idempotent ekliyoruz.
        if (!next._b5aBound) {
            next.addEventListener('mousedown', function (ev) {
                if (next.disabled || next.getAttribute('aria-disabled') === 'true') {
                    ev.preventDefault();
                    _notify('En az bir kolon seçin', 'warning');
                }
            });
            next._b5aBound = true;
        }
    }

    // v3.35.0: prev/next "step 1" skipliyor — _STEPS sırasını kullan.
    function _stepDelta(delta) {
        const idx = _STEPS.indexOf(_state.currentStep);
        if (idx < 0) return _STEPS[0];
        const next = Math.max(0, Math.min(_STEPS.length - 1, idx + delta));
        return _STEPS[next];
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
            // v3.34.2 — Koşullu görünürlük: >1 source varsa select göster (regresyon fix)
            // v3.34.3 — Tek source durumunda readonly badge göster (user feedback)
            const lbl = document.getElementById('dswSourceLabel');
            if (sel.options.length > 1) {
                sel.hidden = false;
                sel.removeAttribute('hidden');
                if (lbl) { lbl.hidden = true; lbl.textContent = ''; }
            } else {
                sel.hidden = true;
                if (lbl) {
                    const single = sel.options[0];
                    if (single && single.value) {
                        lbl.textContent = 'Kaynak: ' + (single.textContent || '');
                        lbl.hidden = false;
                    } else {
                        lbl.hidden = true;
                        lbl.textContent = '';
                    }
                }
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
        // v3.34.0 — Step 1 sadeleştirildi: dswSearchQ input artık DOM'da yok.
        // Picker kendi içinde arama yapıyor; initialQuery boş geçilir.
        const initialQ = '';
        // F22d (HEBE+POSEIDON 2026-05-25): "Seçimi düzenle…" tıklanınca picker
        // daha önce seçilen primary + join'leri unutuyordu — `initialSelection`
        // option'ı picker'da hazır (v3.34.5) ama wizard pas geçmiyordu.
        // Edit-mode hydrate sonrası da çalışır: _state.selectedTableId +
        // _state.selectedTables (primary dahil tüm id'ler) doludur.
        const joinIds = Array.isArray(_state.selectedTables)
            ? _state.selectedTables.filter(function (id) {
                  return id != null && id !== _state.selectedTableId;
              })
            : [];
        const initialSelection = (_state.selectedTableId != null)
            ? { primaryId: _state.selectedTableId, joinIds: joinIds }
            : null;
        window.DbSmartPicker.open({
            sourceId: _state.sourceId,
            initialQuery: initialQ,
            initialSelection: initialSelection,
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
        // v3.34.4 B1 (HEBE+ATHENA): seçim varken Ara butonunu pasifleştir
        _updateAraButtonState();
        _notify(_t('wizard.toast.table_selected', { label: primary.label || primary.name }), 'success');
    }

    function _renderSelectedSummary(primary, joins) {
        const results = document.getElementById('dswResults');
        if (!results) return;
        const escape = _escape;
        const primaryId = (primary && primary.table_id != null) ? primary.table_id : '';
        const primaryLabel = primary.label || primary.name || '';
        const items = [
            '<li class="is-primary" title="Ana tablo" data-row-id="' + escape(primaryId) + '">' +
              '<span class="dsw-chip-label">★ ANA ' + escape(primaryLabel) +
              ' <span style="opacity:.7;font-family:ui-monospace,monospace">' +
              escape((primary.schema ? primary.schema + '.' : '') + (primary.name || '')) + '</span></span>' +
              '<button type="button" class="dsw-chip-remove" aria-label="Sil: ' + escape(primaryLabel) +
              '" data-remove-id="' + escape(primaryId) + '" title="Bu tabloyu seçimden çıkar">×</button>' +
            '</li>'
        ].concat(joins.map(j => {
            const jId = (j && j.table_id != null) ? j.table_id : '';
            const jLabel = j.label || j.name || '';
            return '<li title="Join adayı" data-row-id="' + escape(jId) + '">' +
                '<span class="dsw-chip-label">' + escape(jLabel) +
                ' <span style="opacity:.7;font-family:ui-monospace,monospace">' +
                escape((j.schema ? j.schema + '.' : '') + (j.name || '')) + '</span></span>' +
                '<button type="button" class="dsw-chip-remove" aria-label="Sil: ' + escape(jLabel) +
                '" data-remove-id="' + escape(jId) + '" title="Bu tabloyu seçimden çıkar">×</button>' +
                '</li>';
        }));
        const total = 1 + joins.length;
        results.innerHTML =
            '<div class="dsw-selected-summary">' +
              '<h4>Seçilen tablolar (' + total + ')</h4>' +
              '<ul>' + items.join('') + '</ul>' +
              '<button type="button" class="dsw-selected-edit" id="dswSelectedEdit">Seçimi düzenle…</button>' +
            '</div>';
        const editBtn = document.getElementById('dswSelectedEdit');
        if (editBtn) editBtn.addEventListener('click', _openPicker);
        // v3.34.4 B1 (HERMES): chip × delegate — idempotent (innerHTML her render'da reset)
        const summaryRoot = results.querySelector('.dsw-selected-summary');
        if (summaryRoot) {
            summaryRoot.addEventListener('click', function (ev) {
                const btn = ev.target.closest('.dsw-chip-remove');
                if (!btn) return;
                ev.preventDefault();
                ev.stopPropagation();
                const rid = btn.getAttribute('data-remove-id');
                const ridInt = parseInt(rid, 10);
                if (!isNaN(ridInt)) _removeChip(ridInt);
            });
        }
    }

    // v3.34.4 B1 (HEBE+ATHENA+HERMES): chip × handler
    function _removeChip(tableId) {
        if (tableId == null) return;
        const isPrimary = (tableId === _state.selectedTableId);
        if (isPrimary) {
            // Ana tablo silinince tüm seçim temizlenir
            _state.selectedTableId = null;
            _state.selectedTableObjectName = null;
            _state.selectedTableSchema = null;
            _state.selectedTableLabel = null;
            _state.selectedTables = [];
            _state.joinCandidates = [];
            const results = document.getElementById('dswResults');
            if (results) results.innerHTML = '';
            const next = document.getElementById('dswNextBtn');
            if (next) next.disabled = true;
            _notify('Seçim temizlendi', 'info');
        } else {
            // Yalnız join chip'i kaldır
            _state.joinCandidates = (_state.joinCandidates || []).filter(j => {
                const jid = (j && j.table_id != null) ? parseInt(j.table_id, 10) : null;
                return jid !== tableId;
            });
            _state.selectedTables = (_state.selectedTables || []).filter(id => {
                const intId = (typeof id === 'number') ? id : parseInt(id, 10);
                return intId !== tableId;
            });
            // Re-render summary
            const primary = {
                table_id: _state.selectedTableId,
                label: _state.selectedTableLabel,
                name: _state.selectedTableObjectName,
                schema: _state.selectedTableSchema,
            };
            _renderSelectedSummary(primary, _state.joinCandidates);
        }
        _updateAraButtonState();
    }

    // v3.34.4 B1 (HEBE): Ara butonu state — seçim varsa pasif, yoksa aktif
    function _updateAraButtonState() {
        const btn = document.getElementById('dswSearchBtn');
        if (!btn) return;
        const hasSelection = (_state.selectedTableId != null) ||
                             (_state.selectedTables && _state.selectedTables.length > 0);
        if (hasSelection) {
            btn.disabled = true;
            btn.setAttribute('title', 'Önce mevcut seçimi temizleyin (chip × ile)');
            btn.setAttribute('aria-disabled', 'true');
        } else {
            btn.disabled = false;
            btn.setAttribute('title', 'Tablo seçici aç');
            btn.removeAttribute('aria-disabled');
        }
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
            // FIX5 P2 (ATHENA+HEBE): _mapApiError 401/403/404 ayrımı
            results.innerHTML = '<div class="dsw-hint" role="status">' + _escape(_mapApiError(e)) + '</div>';
            _notify(_t('wizard.error.search_failed', { message: (e && e.message) || '' }), 'error');
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
    // Step 2 — Metric library
    // ============================================
    // NOT: v3.35.0'da "İlişkiler" step'i (data-step="1") kaldırıldı; FK seçimi
    // step 0 picker'ın right pane'inde yapılıyor. Eski `_loadRelated` fonksiyonu
    // ve dswStep1 panel'i silindi. i18n anahtarları (wizard.hint.loading_related
    // vb.) geriye uyum için korundu.
    // ============================================

    // F14 (HEBE+HERMES+ATHENA): TR-normalize — diakritikleri sadeleştir + lower
    // case (Türkçe locale ile, "İ" → "i", "I" → "ı"). Metric arama input'unun
    // label/description match'inde kullanılır. Çağıran her iki tarafı da
    // normalize etmelidir (input + her item alanı).
    function _trNormalize(s) {
        if (s == null) return '';
        let v = String(s);
        try { v = v.toLocaleLowerCase('tr-TR'); } catch (_) { v = v.toLowerCase(); }
        // Akıllı diakritik düşürme: ş→s, ç→c, ğ→g, ü→u, ö→o, ı→i, â→a vb.
        return v
            .replace(/[şŞ]/g, 's')
            .replace(/[çÇ]/g, 'c')
            .replace(/[ğĞ]/g, 'g')
            .replace(/[üÜ]/g, 'u')
            .replace(/[öÖ]/g, 'o')
            .replace(/[ıİ]/g, 'i')
            .replace(/[âÂ]/g, 'a')
            .replace(/[îÎ]/g, 'i')
            .replace(/[ûÛ]/g, 'u');
    }

    // v3.37.3 (bulgular-2 / Bulgu 2): LLM hata sebebini kullanıcı-okur
    // büyük harfli mesaja indirgeyen helper. Kind='empty' modelin yanıt
    // verip de öneri çıkaramadığı durum; kind='error' fetch/parse istisnası.
    function _mapLlmErrorReason(err, kind) {
        if (kind === 'empty') {
            return 'YAPAY ZEKA BU TABLO İÇİN UYGUN BİR METRİK ÇIKARAMADI';
        }
        if (!err) return 'YAPAY ZEKA YANIT VERMEDİ';
        const status = (err && (err.status || err.statusCode)) || 0;
        const msg = String((err && err.message) || '').toLowerCase();
        if (err.name === 'TimeoutError' || msg.indexOf('timeout') >= 0) {
            return 'YAPAY ZEKA YANITI ZAMAN AŞIMINA UĞRADI';
        }
        if (status === 429 || msg.indexOf('rate limit') >= 0 || msg.indexOf('quota') >= 0) {
            return 'YAPAY ZEKA KOTASI DOLDU — DAHA SONRA TEKRAR DENEYİN';
        }
        if (status === 401 || status === 403) {
            return 'YAPAY ZEKA YETKİLENDİRME HATASI';
        }
        if (status === 400 || status === 422) {
            return 'YAPAY ZEKA İSTEĞİ GEÇERSİZ (TABLO VEYA KOLON BİLGİSİ EKSİK)';
        }
        if (status >= 500) {
            return 'YAPAY ZEKA SUNUCUSU YANIT VERMEDİ (' + status + ')';
        }
        if (msg.indexOf('json') >= 0 || msg.indexOf('parse') >= 0) {
            return 'YAPAY ZEKA YANITI ÇÖZÜMLENEMEDİ';
        }
        if (msg.indexOf('network') >= 0 || msg.indexOf('failed to fetch') >= 0) {
            return 'AĞ BAĞLANTI HATASI';
        }
        return 'YAPAY ZEKA SAĞLAYICISI ŞU AN ULAŞILAMIYOR';
    }

    // F14: accordion render + search + multi-checkbox. Kategori bazında
    // <details> blokları, üstte search input, her item solunda checkbox.
    // Multi-select (Set), boş geçilebilir; "İleri" validation YOK.
    //
    // v3.37.1 B (HEBE+METIS): Step 1->2 transition'da LLM auto-suggest
    // tetiklenir; statik kütüphane fallback/ek olarak merge edilir. Spinner
    // mesaji METIS imzalidir. AbortController step-out durumunda iptal eder.
    async function _loadMetrics() {
        const panel = document.getElementById('dswStep2');
        if (!panel) return;
        if (!_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_t('wizard.hint.select_source_first')) + '</p>';
            return;
        }
        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">🤖 METIS metrikleri analiz ediyor...</p>';

        // v3.37.3 (bulgular-2 / Bulgu 2): LLM önerisi başarısız olursa neden
        // göster. Reset → sonra catch dalları doldursun. _autoSuggestMetrics
        // null dönerse (kolon fetch hatası / tablo adı yok / boş yanıt) bunu
        // da fallback nedeni olarak kayıt ederiz.
        _state._lastMetricLlmError = null;

        // 1) LLM auto-suggest dene (sadece tablo seçildiyse anlamli).
        let llmSuggestions = null;
        const llmAbort = new AbortController();
        _state._metricLlmAbort = llmAbort;

        if (_state.selectedTableId) {
            try {
                const llmData = await _autoSuggestMetrics({
                    source_id: _state.sourceId,
                    table_id: _state.selectedTableId,
                    table_label: _state.selectedTableLabel,
                    joined_tables: _state.selectedTables || [],
                    signal: llmAbort.signal,
                });
                if (llmData && Array.isArray(llmData.suggestions) && llmData.suggestions.length) {
                    llmSuggestions = llmData.suggestions;
                } else {
                    // Yanıt geldi ama boş — model "çıkaramadı" durumu.
                    _state._lastMetricLlmError = _mapLlmErrorReason(null, 'empty');
                }
            } catch (e) {
                if (e && e.name === 'AbortError') {
                    // Step out — kullanici 2. adimdan ayrildi, sessizce don.
                    _setBusy(panel, false);
                    return;
                }
                _state._lastMetricLlmError = _mapLlmErrorReason(e, 'error');
                console.warn('[db_smart_wizard] auto metric-suggest failed:', e);
            }
        }

        // 2) Statik kutuphaneyi her zaman cek (LLM hata verirse fallback,
        //    basariliysa ek kategori olarak gosterilir).
        let staticItems = [];
        let staticFallback = false;
        try {
            // P4 fix: tablo seçildiyse table_id ekle → backend list_eligible() ile
            // applicable_when filter uygular ve user-pref/usage skor sıralaması döner.
            let url = API_BASE + '/metrics?source_id=' + _state.sourceId;
            if (_state.selectedTableId) {
                url += '&table_id=' + _state.selectedTableId;
            }
            const data = await _fetchJson(url);
            staticItems = data.items || [];
            staticFallback = !!(data && data.fallback);
        } catch (e) {
            console.warn('[db_smart_wizard] static metrics failed:', e);
            if (!llmSuggestions) {
                // FIX5 P2 (ATHENA+HEBE): _mapApiError 401/403/404 ayrımı
                panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_mapApiError(e)) + '</p>';
                _notify(_t('wizard.error.metrics_failed', { message: (e && e.message) || '' }), 'error');
                _setBusy(panel, false);
                _state._metricLlmAbort = null;
                return;
            }
        }

        // 3) Merge — LLM önerileri "✨ LLM Önerisi" kategorisinde, sonra statik
        //    kategoriler. metric_key cakismasinda LLM kazanir.
        //
        // Bulgular3 / Bulgu 3: LLM önerisi geldiyse standart "fallback başlıkları"
        // (Müşteri / Diğer / Masraf / Gelir ...) varsayılan olarak GİZLE — kullanıcı
        // toolbar toggle ile açabilir. _metricsIndex'e statikler yine yazılır
        // (arama + restore için), ama kategori listesinden çıkarılır. Restore
        // path'inde önceden seçili statik metric varsa o kategoriyi görünür tut
        // ki kullanıcı seçimini görsün.
        _state._metricsIndex = {};
        _state._metricCategories = {};
        _state._staticCategoriesShadow = {};
        _state._llmActive = !!(llmSuggestions && llmSuggestions.length);

        if (llmSuggestions) {
            const llmCat = '✨ LLM Önerisi';
            const llmList = llmSuggestions.map((s, i) => {
                const safeBase = (s && (s.metric_key || s.metric_name) || 'metric_' + i);
                const key = 'llm_' + String(safeBase).replace(/\W+/g, '_').toLowerCase();
                const item = {
                    metric_key: key,
                    name_tr: s.metric_name || s.name_tr || key,
                    description_tr: s.rationale || s.description_tr || '',
                    default_viz: s.default_viz || 'table',
                    category: llmCat,
                    source: 'llm',
                    confidence: s.confidence,
                    formula: s.formula,
                    agg: s.agg,
                    table_name_tr: s.table_name_tr,
                    table_object_name: s.table_object_name,
                };
                _state._metricsIndex[key] = item;
                return item;
            });
            _state._metricCategories[llmCat] = llmList;
        }

        const selectedSet = _state.selectedMetrics || new Set();
        staticItems.forEach(m => {
            if (!m || !m.metric_key) return;
            if (_state._metricsIndex[m.metric_key]) return; // LLM zaten ekledi
            _state._metricsIndex[m.metric_key] = m;
            const cat = (m.category)
                || (m.applicable_when && m.applicable_when.category)
                || 'Diğer';
            // LLM aktifse statikler shadow'a (gizli); aksi halde normal kategoriye.
            // Ancak restore'da seçili olan statik metric'ler görünür kategoriye çıkar
            // (kullanıcı seçimini kaybetmesin).
            const isSelectedStatic = selectedSet.has && selectedSet.has(m.metric_key);
            const target = (_state._llmActive && !isSelectedStatic)
                ? _state._staticCategoriesShadow
                : _state._metricCategories;
            (target[cat] = target[cat] || []).push(m);
        });

        // Stale selectedMetrics temizle (yeniden çağrılırsa).
        if (_state.selectedMetrics && typeof _state.selectedMetrics.forEach === 'function') {
            const toDrop = [];
            _state.selectedMetrics.forEach(k => {
                if (!_state._metricsIndex[k]) toDrop.push(k);
            });
            toDrop.forEach(k => _state.selectedMetrics.delete(k));
        }

        const mergedItems = Object.values(_state._metricsIndex);
        if (!mergedItems.length) {
            panel.innerHTML = '<p class="dsw-hint">' + _escape(_t('wizard.empty.metrics')) + '</p>';
            _setBusy(panel, false);
            _state._metricLlmAbort = null;
            return;
        }

        // Fallback notu SADECE LLM yokken VE statik fallback'tayken gosterilir.
        const showFallbackNote = (!llmSuggestions) && staticFallback;
        // Bulgular3 / Review fix #2: toggle re-render'ı için fallbackUsed'i state'e tut —
        // closure'dan stale değer okumayalım.
        _state._lastFallbackUsed = showFallbackNote;
        _renderStep2(mergedItems, showFallbackNote);
        _setBusy(panel, false);
        _state._metricLlmAbort = null;
    }

    // v3.37.2 (HEBE+METIS+ARES): Step 2 auto-suggest helper. Backend
    // /api/db-smart/llm/metric-suggest kontratı: { source_id, table:str,
    // columns:[{name,type}], user_intent? }. Auto-path'ta Step 2 girişinde
    // henüz _columnCatalog yok — kolonları ön-fetch ediyoruz
    // (/sources/{sid}/tables/{tid}/columns) ve {name, type} şekline indiriyoruz.
    // Kolon fetch hata verirse veya boş dönerse LLM'i atla (null), caller statik
    // kütüphaneye düşer. AbortError up'a propagate eder (step-out cleanup için).
    async function _autoSuggestMetrics(payload) {
        let columns = [];
        try {
            const colUrl = API_BASE + '/sources/' + payload.source_id +
                           '/tables/' + payload.table_id + '/columns';
            const colData = await _fetchJson(colUrl, { signal: payload.signal });
            columns = (colData && Array.isArray(colData.columns) ? colData.columns : [])
                .map(function (c) {
                    return {
                        name: c.name,
                        type: c.data_type || c.semantic_type || 'unknown',
                    };
                })
                .filter(function (c) { return c.name && c.type; });
        } catch (e) {
            if (e && e.name === 'AbortError') throw e;
            console.warn('[db_smart_wizard] metric-suggest column pre-fetch failed:', e);
            return null;
        }
        if (!columns.length) return null;

        const tableName = _state.selectedTableObjectName ||
                          (payload.table_label || '').split('.').pop() || null;
        if (!tableName) return null;

        const body = {
            source_id: payload.source_id,
            table: tableName,
            // Bulgular3 / Bulgu 4: TR ad backend'e propagate; prompt+response
            // bunu kullanir, chip "Tablo: <TR ad>" basligi olusur, tooltip SQL adi.
            table_label: payload.table_label || _state.selectedTableLabel || null,
            columns: columns,
            user_intent: _state.user_intent || '',
        };
        return await _fetchJson(API_BASE + '/llm/metric-suggest', {
            method: 'POST',
            body: JSON.stringify(body),
            signal: payload.signal,
        });
    }

    // F14: ana render fonksiyonu — accordion + search + multi-checkbox.
    function _renderStep2(items, fallbackUsed) {
        const panel = document.getElementById('dswStep2');
        if (!panel) return;
        // Bulgular3 / Bulgu 3: LLM aktif + kullanıcı toggle açtıysa shadow'daki
        // statikleri görünür kategorilere merge et. Aksi halde shadow gizli kalır.
        const baseCats = _state._metricCategories || {};
        const shadow = _state._staticCategoriesShadow || {};
        const showShadow = _state._llmActive && _state._showStaticMetrics === true;
        const cats = {};
        Object.keys(baseCats).forEach(k => { cats[k] = baseCats[k].slice(); });
        if (showShadow) {
            Object.keys(shadow).forEach(k => {
                cats[k] = (cats[k] || []).concat(shadow[k]);
            });
        }
        const catNames = Object.keys(cats).sort();
        const total = items.length;
        const selCount = (_state.selectedMetrics && _state.selectedMetrics.size) || 0;

        let html = '';
        // v3.37.3 (bulgular-2 / Bulgu 2): LLM önerisi yapılamadıysa neden'i
        // BÜYÜK HARFLERLE intro mesajının ÜSTÜNE bas. fallbackUsed alanı
        // _loadMetrics tarafından (!llmSuggestions && staticFallback) durumunda
        // true gelir — yani statik kütüphaneye düşüldü demektir.
        const llmReason = _state._lastMetricLlmError;
        if (fallbackUsed || llmReason) {
            const reasonText = llmReason || 'YAPAY ZEKA ÖNERİSİ ÜRETİLEMEDİ';
            html += '<div class="dsw-llm-fallback-banner" role="alert">' +
                    '<span class="dsw-llm-fallback-banner-reason">' +
                    _escape(reasonText) + '</span>' +
                    '<span class="dsw-llm-fallback-banner-subtitle">' +
                    _escape(_t('wizard.banner.llm_fallback_subtitle')) +
                    '</span>' +
                    '</div>';
        }
        // Intro hint
        html += '<p class="dsw-hint">' +
                _escape(_t('wizard.hint.metric_intro', { count: total })) +
                '</p>';
        // Top toolbar — search + clear + selected counter.
        // Bulgular3 / Bulgu 3: LLM aktifse "Standart kütüphaneyi göster/gizle"
        // toggle göster — varsayılan gizli, kullanıcı açabilir.
        const staticToggleHtml = (_state._llmActive)
            ? ('<button type="button" id="dswMetricStaticToggle" class="dsw-metric-static-toggle" ' +
               'title="Standart metrik kütüphanesi görünürlüğü">' +
               (_state._showStaticMetrics
                   ? '📚 Standart kütüphaneyi gizle'
                   : '📚 Standart kütüphaneyi göster') +
               '</button>')
            : '';
        html += '<div class="dsw-metric-toolbar">' +
                '<div class="dsw-metric-search-wrap">' +
                '<input type="search" id="dswMetricSearch" class="dsw-metric-search" ' +
                'placeholder="Metrik ara..." autocomplete="off" aria-label="Metrik ara">' +
                '<button type="button" id="dswMetricSearchClear" class="dsw-metric-search-clear" ' +
                'aria-label="Aramayı temizle" title="Temizle">×</button>' +
                '</div>' +
                '<button type="button" id="dswMetricClearAll" class="dsw-metric-clear-all" ' +
                'title="Tüm seçimleri kaldır">Tümünü temizle</button>' +
                staticToggleHtml +
                '<span id="dswMetricSelectedCount" class="dsw-metric-selected-count" aria-live="polite">' +
                (selCount > 0 ? (selCount + ' seçili') : '') +
                '</span>' +
                '</div>';

        // Accordion: ilk kategori open, diğerleri closed.
        // v3.37.1 B: "✨ LLM Önerisi" kategorisi her zaman acik gelir.
        html += '<div class="dsw-metric-categories" id="dswMetricCategories">';
        catNames.forEach((cat, idx) => {
            const list = cats[cat] || [];
            const isLlmCat = (cat === '✨ LLM Önerisi');
            const openAttr = (isLlmCat || idx === 0) ? ' open' : '';
            html += '<details class="dsw-metric-category"' + openAttr +
                    ' data-category="' + _escape(cat) + '">' +
                    '<summary class="dsw-metric-category-summary">' +
                    '<span class="dsw-metric-category-name">' + _escape(cat) + '</span>' +
                    '<span class="dsw-metric-category-count">' + list.length + '</span>' +
                    '</summary>' +
                    '<ul class="dsw-metric-list" role="group">';
            list.forEach(m => {
                const mk = m.metric_key;
                const isSel = !!(_state.selectedMetrics && _state.selectedMetrics.has(mk));
                const label = m.name_tr || m.metric_key;
                const desc = m.description_tr || '';
                const viz = m.default_viz || 'table';
                const selClass = isSel ? ' selected' : '';
                const searchHay = _trNormalize(label + ' ' + desc + ' ' + mk);
                html += '<li class="dsw-metric-item' + selClass + '"' +
                        ' data-metric-key="' + _escape(mk) + '"' +
                        ' data-search="' + _escape(searchHay) + '">' +
                        '<label class="dsw-metric-item-label">' +
                        '<input type="checkbox" class="dsw-metric-checkbox" ' +
                        'data-metric-key="' + _escape(mk) + '"' +
                        (isSel ? ' checked' : '') + '>' +
                        '<span class="dsw-metric-item-body">' +
                        '<strong class="dsw-metric-item-title">' + _escape(label) + '</strong>' +
                        (desc ? '<span class="dsw-metric-item-desc">' + _escape(desc) + '</span>' : '') +
                        '<span class="dsw-metric-item-meta">' + _escape(viz) + '</span>' +
                        '</span>' +
                        '</label>' +
                        '</li>';
            });
            html += '</ul></details>';
        });
        html += '</div>';
        panel.innerHTML = html;

        // Wire events.
        const searchInput = panel.querySelector('#dswMetricSearch');
        const searchClear = panel.querySelector('#dswMetricSearchClear');
        const clearAllBtn = panel.querySelector('#dswMetricClearAll');
        const countEl = panel.querySelector('#dswMetricSelectedCount');

        const updateSelectedCount = () => {
            if (!countEl) return;
            const n = (_state.selectedMetrics && _state.selectedMetrics.size) || 0;
            countEl.textContent = (n > 0) ? (n + ' seçili') : '';
        };

        // Checkbox toggle → Set + tekil metric backwards-compat.
        panel.querySelectorAll('.dsw-metric-checkbox').forEach(cb => {
            cb.addEventListener('change', ev => {
                const mk = cb.getAttribute('data-metric-key');
                const li = cb.closest('.dsw-metric-item');
                if (cb.checked) {
                    _state.selectedMetrics.add(mk);
                    if (li) li.classList.add('selected');
                } else {
                    _state.selectedMetrics.delete(mk);
                    if (li) li.classList.remove('selected');
                }
                // metric (tekil) = son seçilen (Set size > 0 ise sondaki) — F9 payload.
                const arr = Array.from(_state.selectedMetrics);
                const lastKey = arr.length ? arr[arr.length - 1] : null;
                _state.metric = lastKey ? (_state._metricsIndex[lastKey] || null) : null;
                updateSelectedCount();
            });
        });

        // Search filter — TR-normalize match.
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                const qRaw = searchInput.value || '';
                const q = _trNormalize(qRaw.trim());
                const cats = panel.querySelectorAll('.dsw-metric-category');
                cats.forEach(catEl => {
                    let visibleCount = 0;
                    const items = catEl.querySelectorAll('.dsw-metric-item');
                    items.forEach(li => {
                        const hay = li.getAttribute('data-search') || '';
                        const show = !q || hay.indexOf(q) !== -1;
                        li.style.display = show ? '' : 'none';
                        if (show) visibleCount += 1;
                    });
                    catEl.style.display = (visibleCount === 0 && q) ? 'none' : '';
                    // Aktif arama varsa eşleşen kategorileri aç.
                    if (q && visibleCount > 0) catEl.setAttribute('open', '');
                });
            });
        }
        if (searchClear) {
            searchClear.addEventListener('click', () => {
                if (!searchInput) return;
                searchInput.value = '';
                searchInput.dispatchEvent(new Event('input'));
                searchInput.focus();
            });
        }
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', () => {
                if (!_state.selectedMetrics || _state.selectedMetrics.size === 0) return;
                _state.selectedMetrics.clear();
                _state.metric = null;
                panel.querySelectorAll('.dsw-metric-checkbox').forEach(cb => { cb.checked = false; });
                panel.querySelectorAll('.dsw-metric-item.selected').forEach(li => li.classList.remove('selected'));
                updateSelectedCount();
            });
        }
        // Bulgular3 / Bulgu 3: standart kütüphane görünürlük toggle.
        const staticToggleBtn = panel.querySelector('#dswMetricStaticToggle');
        if (staticToggleBtn) {
            staticToggleBtn.addEventListener('click', () => {
                _state._showStaticMetrics = !_state._showStaticMetrics;
                // Re-render — fallbackUsed'i state'ten oku (Review fix #2: stale closure'dan değil).
                _renderStep2(
                    Object.values(_state._metricsIndex || {}),
                    !!_state._lastFallbackUsed,
                );
            });
        }
    }

    // ============================================
    // Step 3 — Filter (columns) + Report column DnD
    // ============================================
    // EDIT9 (HEBE+HERMES+ATHENA): two-panel layout — sol kolon kataloğu
    // (+ Ekle), sağ DnD "raporda görünecek kolonlar" listesi + LLM
    // öner butonu. Sıra _state.reportColumns'a yansır ve _buildWizardState
    // tarafından SELECT'e geçirilir.

    // v3.36 F7 (POSEIDON+HEBE+ATHENA): multi-table column loader.
    // Çağrı: /api/db-smart/sources/{sid}/tables/columns?table_ids=primary,join1,join2
    // Sıra: primary önce, ardından join'ler (selectedTables zaten bu sıraya sahip).
    // Kolon kataloğu flatten edilir; her kolon enrich olur → {table_id, table_name}.
    // _state._columnGroups da set edilir → _renderStep3 grupları bu sıraya göre çizer.
    async function _loadColumns() {
        const panel = document.getElementById('dswStep3');
        if (!panel) return;
        if (!_state.selectedTableId || !_state.sourceId) {
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _t('wizard.step3.selectTableFirst') + '</p>';
            return;
        }
        // Primary önce — sonra join id'ler (mükerrer eliminasyonu ile).
        const orderedIds = [_state.selectedTableId].concat(
            (_state.selectedTables || []).filter(id => {
                const n = (typeof id === 'number') ? id : parseInt(id, 10);
                return !isNaN(n) && n !== _state.selectedTableId;
            }).map(id => (typeof id === 'number') ? id : parseInt(id, 10))
        );
        const idsCsv = orderedIds.filter(x => x != null && !isNaN(x)).join(',');

        _setBusy(panel, true);
        panel.innerHTML = '<p class="dsw-hint" role="status">' + _t('wizard.step3.loading') + '</p>';
        try {
            const url = API_BASE + '/sources/' + _state.sourceId +
                        '/tables/columns?table_ids=' + encodeURIComponent(idsCsv);
            const data = await _fetchJson(url);
            const tables = (data && data.tables) || [];
            // Flatten kolonları; her kolon table_id + table_name ile zenginleşir.
            const flat = [];
            const groups = [];
            tables.forEach(t => {
                const tName = t.table_name || null;
                const tLabel = t.business_name_tr || t.table_name || ('Tablo #' + t.table_id);
                const tCols = (t.columns || []).map(c => ({
                    name: c.name,
                    label: c.business_name_tr || c.name,
                    data_type: c.data_type || null,
                    semantic_type: c.semantic_type || null,
                    table_name: tName,
                    table_id: t.table_id,
                }));
                groups.push({
                    table_id: t.table_id,
                    table_name: tName,
                    table_label: tLabel,
                    columns: tCols,
                });
                tCols.forEach(c => flat.push(c));
            });

            if (!flat.length) {
                panel.innerHTML = '<p class="dsw-hint">' + _t('wizard.step3.noColumns') + '</p>';
                return;
            }
            _state._columnCatalog = flat;
            _state._columnGroups = groups;
            _renderStep3(panel, flat.length);
        } catch (e) {
            // FIX5 P2 (ATHENA+HEBE): i18n param binding + _mapApiError 401/403/404 ayrımı
            panel.innerHTML = '<p class="dsw-hint" role="status">' + _escape(_mapApiError(e)) + '</p>';
            _notify(_t('wizard.step3.loadError', { message: (e && e.message) || '' }), 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // EDIT9 + v3.36 F7: Tam step-3 layout (sol katalog + sağ DnD).
    // F7 (HEBE): sol katalog artık tablo bazlı gruplanır — primary önce, join'ler sırada.
    // Grup başlığı = <h5 class="dsw-table-group">Tablo: SIPARISLER</h5>.
    // Aynı kolon adı farklı tablolarda olabileceğinden, "+ Ekle" data-add-col CSS
    // selector çakışmasını önlemek için data-table-id de taşır; handler her ikisini
    // birlikte kullanır.
    function _renderStep3(panel, totalCount) {
        const cols = _state._columnCatalog || [];
        const groups = (_state._columnGroups && _state._columnGroups.length)
            ? _state._columnGroups
            : [{ table_id: _state.selectedTableId,
                 table_name: _state.selectedTableObjectName,
                 table_label: _state.selectedTableLabel || _state.selectedTableObjectName || 'Tablo',
                 columns: cols }];
        const intro = '<p class="dsw-hint">' + _escape(totalCount + ' kolon · ' +
            groups.length + ' tablo. ' +
            'Soldan "+ Ekle" ile rapora dahil edin, sağ panelde sürükle-bırak ile sıralayın.') + '</p>';
        // v3.37.1 D (ATHENA+POSEIDON+HEBE): "✨ Metrik için uygun kolonlar" kategorisi.
        // Background fetch POST /llm/column-filter-suggest — render edilince doldurulur.
        // v3.37.4 Bug D fix (HEBE+ATHENA): başlığa "+ Tümünü ekle" butonu.
        // Initial state'te hidden — _loadMetricAwareColumns recommended[] dolduğunda
        // unhide edilir. Click → tüm önerilen kolonları reportColumns'a sırayla ekler.
        const metricAwareHtml =
            '<div class="dsw-metric-aware" data-category="metric-aware">' +
              '<h5 class="dsw-table-group dsw-cat-metric-aware" data-metric-aware-head>' +
                '<span class="dsw-metric-aware-title">' +
                  '✨ Metrik için uygun kolonlar ' +
                  '<span class="dsw-table-group-count" data-metric-aware-count>(...)</span>' +
                '</span>' +
                '<button type="button" class="dsw-metric-aware-add-all" ' +
                  'data-metric-aware-add-all aria-label="Önerilen tüm kolonları rapora ekle" ' +
                  'title="Önerilen tüm kolonları sırayla rapora ekle" hidden>' +
                  '+ Tümünü ekle</button>' +
              '</h5>' +
              '<ul class="dsw-col-catalog" data-metric-aware-list>' +
                '<li class="dsw-col-row dsw-metric-aware-loading">' +
                  '<div class="dsw-col-row-text">' +
                    '<div class="dsw-r-meta">Metrik analizi yapılıyor…</div>' +
                  '</div>' +
                '</li>' +
              '</ul>' +
            '</div>';

        // Sol panel: katalog (tablo bazlı grup)
        let leftHtml = '<div class="dsw-filter-catalog" role="region" aria-label="Kolon kataloğu">';
        leftHtml += metricAwareHtml;
        groups.forEach(g => {
            const headLabel = (g.table_label || g.table_name || ('Tablo #' + g.table_id));
            leftHtml += '<h5 class="dsw-table-group" data-table-id="' + _escape(g.table_id) + '">' +
                'Tablo: ' + _escape(headLabel) +
                ' <span class="dsw-table-group-count">(' + (g.columns || []).length + ')</span>' +
                '</h5>';
            leftHtml += '<ul class="dsw-col-catalog" data-table-id="' + _escape(g.table_id) + '">';
            (g.columns || []).forEach(c => {
                const meta = c.name + ' · ' + (c.data_type || '?') +
                             (c.semantic_type ? ' · ' + c.semantic_type : '');
                leftHtml += '<li class="dsw-col-row">' +
                    '<div class="dsw-col-row-text">' +
                      '<div class="dsw-r-title">' + _escape(c.label) + '</div>' +
                      '<div class="dsw-r-meta">' + _escape(meta) + '</div>' +
                    '</div>' +
                    '<button type="button" class="dsw-col-add-btn" ' +
                      'data-add-col="' + _escape(c.name) + '" ' +
                      'data-table-id="' + _escape(g.table_id) + '" ' +
                      'aria-label="Rapora ekle: ' + _escape(c.label) + '">+ Ekle</button>' +
                    '</li>';
            });
            leftHtml += '</ul>';
        });
        leftHtml += '</div>';

        // Sağ panel: DnD + LLM öneri
        const rightHtml =
            '<div class="dsw-filter-report" role="region" aria-label="Raporda görünecek kolonlar">' +
              '<div class="dsw-filter-report-head">' +
                '<h4>Raporda görünecek kolonlar</h4>' +
                '<button type="button" id="dswSuggestOrderBtn" class="dsw-suggest-btn" ' +
                  'aria-label="LLM ile sırala">✨ LLM ile öner</button>' +
              '</div>' +
              '<ul id="dswReportColumns" class="dsw-dnd-list" role="listbox" ' +
                'aria-label="Raporda görünecek kolonlar (sürükleyerek sıralayın)"></ul>' +
            '</div>';

        // F8 (APOLLO+HEBE+ATHENA): slot container above filter grid +
        // free-text yorum textarea below it. Both are rendered/bound after
        // innerHTML write so handlers attach cleanly.
        const slotsHtml = '<div id="dswSuggestSlots" class="dsw-suggest-slots" ' +
            'role="region" aria-label="LLM kolon sırası önerileri"></div>';
        const noteHtml =
            '<div class="dsw-user-note">' +
              '<label for="dswUserNote">Bu rapordan ne bekliyorsunuz?</label>' +
              '<textarea id="dswUserNote" rows="3" ' +
                'placeholder="Örn: son 3 ayın ay bazlı ürün satış artışını göster"></textarea>' +
            '</div>';

        panel.innerHTML = intro + slotsHtml +
            '<div class="dsw-filter-grid">' + leftHtml + rightHtml + '</div>' +
            noteHtml;

        // + Ekle delegate — v3.36 F7: (col_name, table_id) ile çağırarak aynı
        // ada sahip kolonların farklı tablolardan eklenmesini ayrıştır.
        panel.querySelectorAll('[data-add-col]').forEach(btn => {
            btn.addEventListener('click', function () {
                const colName = btn.getAttribute('data-add-col');
                const tidRaw = btn.getAttribute('data-table-id');
                const tid = tidRaw != null ? parseInt(tidRaw, 10) : null;
                _addReportColumn(colName, isNaN(tid) ? null : tid);
            });
        });
        // LLM öner button
        const suggestBtn = document.getElementById('dswSuggestOrderBtn');
        if (suggestBtn) suggestBtn.addEventListener('click', _suggestColumnOrder);

        // F8: free-text textarea bind (restore prior value on re-render)
        const noteEl = document.getElementById('dswUserNote');
        if (noteEl) {
            noteEl.value = _state.userNote || '';
            noteEl.addEventListener('input', function (e) {
                _state.userNote = (e.target && e.target.value) || '';
            });
        }

        _renderSuggestionSlots();
        _renderReportColumns();

        // v3.37.1 D: metric-aware kategori arka plan fetch
        try { _loadMetricAwareColumns(panel); } catch (e) { /* defansif */ }
    }

    function _renderReportColumns() {
        const list = document.getElementById('dswReportColumns');
        if (!list) return;
        const items = _state.reportColumns || [];
        if (!items.length) {
            list.innerHTML = '<li class="dsw-dnd-empty" role="presentation">' +
                _escape('Henüz kolon eklenmedi — soldan "+ Ekle" ile rapora dahil edin.') +
                '</li>';
            return;
        }
        list.innerHTML = items.map((c, idx) =>
            '<li class="dsw-dnd-item" draggable="true" role="option" tabindex="0" ' +
              'data-col-name="' + _escape(c.column_name) + '" ' +
              'data-col-idx="' + idx + '" ' +
              'aria-label="' + _escape((c.label || c.column_name) + ', sıra ' + (idx + 1) +
                '. Sürükleyerek taşıyın, Delete ile kaldırın.') + '">' +
              '<span class="dsw-dnd-handle" aria-hidden="true">⋮⋮</span>' +
              '<span class="dsw-dnd-label">' + _escape(c.label || c.column_name) +
                (c.semantic_type ? ' <span class="dsw-dnd-stype">' +
                  _escape(c.semantic_type) + '</span>' : '') +
              '</span>' +
              '<button type="button" class="dsw-dnd-remove" ' +
                'data-remove-col="' + _escape(c.column_name) + '" ' +
                'aria-label="Kaldır: ' + _escape(c.label || c.column_name) + '">×</button>' +
            '</li>'
        ).join('');
        _attachReportColumnsDnd(list);
    }

    // v3.36 F7 (POSEIDON+HEBE): tableId parametresi opsiyonel — verilirse
    // (col_name, table_id) çiftiyle catalog'da arar. Aynı ada sahip kolonlar
    // farklı tablolardan ayrı ayrı eklenebilir; duplicate kontrolü de çift
    // bazlı yapılır. SQL generation için report column satırında table_name +
    // table_id alanları korunur (qualifier ekleyebilmek için).
    function _addReportColumn(colName, tableId) {
        if (!colName) return;
        const tid = (typeof tableId === 'number' && !isNaN(tableId)) ? tableId : null;
        const exists = (_state.reportColumns || []).some(c =>
            c.column_name === colName && (tid == null || c.table_id === tid)
        );
        if (exists) {
            _notify('Bu kolon zaten ekli', 'info');
            return;
        }
        const cat = (_state._columnCatalog || []).find(x =>
            x.name === colName && (tid == null || x.table_id === tid)
        ) || (_state._columnCatalog || []).find(x => x.name === colName);
        if (!cat) return;
        // v3.37.1 D (POSEIDON): metric-aware uyumsuzluk uyarısı.
        // _metricAwareWarn array'i column-filter-suggest endpoint'inden gelir.
        // Eklemeyi engellemiyoruz — kullanıcı override edebilir, sadece uyarı veriyoruz.
        try {
            const warns = _state._metricAwareWarn || [];
            const warn = warns.find(function (w) {
                return w && w.column_name === cat.name &&
                    (w.table_id == null || w.table_id === cat.table_id);
            });
            if (warn) {
                _notify('⚠️ "' + (cat.label || cat.name) +
                    '" seçili metrik ile uyumsuz: ' + warn.reason, 'warning');
            }
        } catch (e) { /* defansif */ }

        _state.reportColumns = (_state.reportColumns || []).concat([{
            column_name: cat.name,
            label: cat.label,
            semantic_type: cat.semantic_type,
            table_name: cat.table_name,
            table_id: cat.table_id,
        }]);
        _renderReportColumns();
        // v3.37.0 B5a: kolon eklenince Next guard refresh
        try { _updateNextGuard(); } catch (e) { /* defansif */ }
    }

    // ─────────────────────────────────────────────────────────────
    // v3.37.1 D (ATHENA+POSEIDON+HEBE): Metric-Aware Column Filter
    // ─────────────────────────────────────────────────────────────
    //
    // POST /api/db-smart/llm/column-filter-suggest endpoint'i deterministik
    // POSEIDON kurallarıyla:
    //   - recommended[] : metric ile uyumlu kolonlar (relevance sıralı)
    //   - warn_columns[] : metrikle uyumsuz kolonlar (semantic_mismatch)
    //
    // Render: Step3 sol panelinin en üstündeki "✨ Metrik için uygun kolonlar"
    // kategorisi.
    // ─────────────────────────────────────────────────────────────

    async function _loadMetricAwareColumns(panelRoot) {
        const root = panelRoot || document;
        const headCount = root.querySelector('[data-metric-aware-count]');
        const list = root.querySelector('[data-metric-aware-list]');
        if (!list) return;

        const metric = _state.metric || null;
        const metricKey = metric && (metric.metric_key || metric.key || metric.name) || null;
        const candidates = (_state._columnCatalog || []).map(function (c) {
            return {
                name: c.name,
                semantic_type: c.semantic_type || c.data_type || null,
                table_id: c.table_id,
            };
        });

        if (!metricKey || !candidates.length) {
            list.innerHTML = '<li class="dsw-col-row"><div class="dsw-col-row-text">' +
                '<div class="dsw-r-meta">Metrik seçilmedi — bu kategori boş.</div>' +
                '</div></li>';
            if (headCount) headCount.textContent = '(0)';
            _state._metricAwareWarn = [];
            return;
        }

        const payload = {
            source_id: _state.sourceId,
            metric_key: metricKey,
            metric_kind: (metric && (metric.kind || metric.metric_kind || metric.type)) || null,
            candidates: candidates,
            user_intent: _state.userNote || _state.user_intent || '',
            top_n: 10,
        };

        let data = null;
        try {
            data = await _fetchJson(API_BASE + '/llm/column-filter-suggest', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
        } catch (e) {
            console.warn('[db_smart_wizard] column-filter-suggest failed:', e);
            list.innerHTML = '<li class="dsw-col-row"><div class="dsw-col-row-text">' +
                '<div class="dsw-r-meta">Metrik analizi alınamadı.</div>' +
                '</div></li>';
            if (headCount) headCount.textContent = '(0)';
            return;
        }

        const recommended = (data && Array.isArray(data.recommended)) ? data.recommended : [];
        const warns = (data && Array.isArray(data.warn_columns)) ? data.warn_columns : [];
        const cacheHit = !!(data && data.cache_hit);

        _state._metricAwareWarn = warns;
        _state._metricAwareRecommended = recommended;

        if (headCount) {
            headCount.textContent = '(' + recommended.length +
                (cacheHit ? ' · önbellek' : '') + ')';
        }

        if (!recommended.length) {
            list.innerHTML = '<li class="dsw-col-row"><div class="dsw-col-row-text">' +
                '<div class="dsw-r-meta">Bu metrik için uygun kolon bulunamadı.</div>' +
                '</div></li>';
            return;
        }

        list.innerHTML = recommended.map(function (rec) {
            const colName = rec.column_name || '';
            const cat = (_state._columnCatalog || []).find(function (x) {
                return x.name === colName &&
                    (rec.table_id == null || x.table_id === rec.table_id);
            }) || (_state._columnCatalog || []).find(function (x) {
                return x.name === colName;
            }) || { label: colName, table_id: rec.table_id, semantic_type: rec.semantic_bucket };
            const tid = (cat.table_id != null) ? cat.table_id : (rec.table_id || '');
            const relPct = Math.round((rec.relevance || 0) * 100);
            const metaParts = [];
            if (rec.semantic_bucket) metaParts.push(rec.semantic_bucket);
            metaParts.push('relevance ' + relPct + '%');
            return '<li class="dsw-col-row dsw-metric-aware-row" ' +
                  'title="' + _escape(rec.rationale || '') + '">' +
                '<div class="dsw-col-row-text">' +
                  '<div class="dsw-r-title">' + _escape(cat.label || colName) + '</div>' +
                  '<div class="dsw-r-meta">' + _escape(metaParts.join(' · ')) + '</div>' +
                '</div>' +
                '<button type="button" class="dsw-col-add-btn" ' +
                  'data-add-col="' + _escape(colName) + '" ' +
                  'data-table-id="' + _escape(tid) + '" ' +
                  'data-from-metric-aware="1" ' +
                  'aria-label="Rapora ekle: ' + _escape(cat.label || colName) + '">+ Ekle</button>' +
              '</li>';
        }).join('');

        // Bind metric-aware Add buttons (no warn — bu kategoriden eklenince
        // sessiz ekle çünkü "uygun" olarak sunuldular)
        list.querySelectorAll('[data-add-col]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const colName = btn.getAttribute('data-add-col');
                const tidRaw = btn.getAttribute('data-table-id');
                const tid = tidRaw ? parseInt(tidRaw, 10) : null;
                // metric-aware listeden eklendiği için warn'ı geçici bastır
                const prevWarn = _state._metricAwareWarn;
                _state._metricAwareWarn = [];
                try {
                    _addReportColumn(colName, isNaN(tid) ? null : tid);
                } finally {
                    _state._metricAwareWarn = prevWarn;
                }
            });
        });

        // v3.37.4 Bug D fix (HEBE+ATHENA): "+ Tümünü ekle" butonu unhide + handler.
        // Recommended list dolu (≥1) ise gözükür; click → tüm önerilenleri
        // _addReportColumn üzerinden sırayla ekler. Duplicate (zaten ekli)
        // kolonları _addReportColumn kendi içinde info-toast ile geçer.
        const addAllBtn = root.querySelector('[data-metric-aware-add-all]');
        if (addAllBtn) {
            if (recommended.length) {
                addAllBtn.hidden = false;
                addAllBtn.textContent = '+ Tümünü ekle (' + recommended.length + ')';
            } else {
                addAllBtn.hidden = true;
            }
            // Re-bind safe: önce eski handler'ı temizle (cloneNode swap).
            const fresh = addAllBtn.cloneNode(true);
            addAllBtn.parentNode.replaceChild(fresh, addAllBtn);
            fresh.addEventListener('click', function () {
                const prevWarn = _state._metricAwareWarn;
                _state._metricAwareWarn = [];
                let added = 0;
                try {
                    recommended.forEach(function (rec) {
                        const colName = rec.column_name || '';
                        if (!colName) return;
                        const tid = (rec.table_id != null) ? parseInt(rec.table_id, 10) : null;
                        const before = (_state.reportColumns || []).length;
                        _addReportColumn(colName, isNaN(tid) ? null : tid);
                        const after = (_state.reportColumns || []).length;
                        if (after > before) added += 1;
                    });
                } finally {
                    _state._metricAwareWarn = prevWarn;
                }
                if (added > 0) {
                    _notify(added + ' kolon rapora eklendi', 'success');
                } else {
                    _notify('Tüm öneriler zaten rapora ekli', 'info');
                }
            });
        }
    }

    function _removeReportColumn(colName) {
        _state.reportColumns = (_state.reportColumns || []).filter(c => c.column_name !== colName);
        _renderReportColumns();
        // v3.37.0 B5a: kolon listesi boşalırsa Next guard refresh
        try { _updateNextGuard(); } catch (e) { /* defansif */ }
    }

    function _moveReportColumn(fromIdx, toIdx) {
        const arr = (_state.reportColumns || []).slice();
        if (fromIdx < 0 || fromIdx >= arr.length) return;
        if (toIdx < 0 || toIdx >= arr.length) return;
        const [moved] = arr.splice(fromIdx, 1);
        arr.splice(toIdx, 0, moved);
        _state.reportColumns = arr;
        _renderReportColumns();
        // Re-focus the moved item at its new position (keyboard continuity).
        setTimeout(() => {
            const list = document.getElementById('dswReportColumns');
            if (!list) return;
            const target = list.querySelector('[data-col-idx="' + toIdx + '"]');
            if (target) target.focus();
        }, 0);
    }

    // EDIT9 (HERMES): HTML5 DnD + keyboard fallback.
    function _attachReportColumnsDnd(list) {
        let dragSrcIdx = -1;

        list.querySelectorAll('.dsw-dnd-item').forEach(item => {
            item.addEventListener('dragstart', function (ev) {
                dragSrcIdx = parseInt(item.getAttribute('data-col-idx'), 10);
                item.classList.add('dragging');
                if (ev.dataTransfer) {
                    ev.dataTransfer.effectAllowed = 'move';
                    try { ev.dataTransfer.setData('text/plain', String(dragSrcIdx)); } catch (e) { /* ignore */ }
                }
            });
            item.addEventListener('dragend', function () {
                item.classList.remove('dragging');
                list.querySelectorAll('.dsw-dnd-item').forEach(i => i.classList.remove('drag-over'));
                dragSrcIdx = -1;
            });
            item.addEventListener('dragover', function (ev) {
                ev.preventDefault();
                if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
                item.classList.add('drag-over');
            });
            item.addEventListener('dragleave', function () {
                item.classList.remove('drag-over');
            });
            item.addEventListener('drop', function (ev) {
                ev.preventDefault();
                item.classList.remove('drag-over');
                const tgtIdx = parseInt(item.getAttribute('data-col-idx'), 10);
                let srcIdx = dragSrcIdx;
                if ((srcIdx < 0 || isNaN(srcIdx)) && ev.dataTransfer) {
                    try { srcIdx = parseInt(ev.dataTransfer.getData('text/plain'), 10); } catch (e) { /* ignore */ }
                }
                if (isNaN(srcIdx) || srcIdx < 0 || srcIdx === tgtIdx) return;
                _moveReportColumn(srcIdx, tgtIdx);
            });
            // Keyboard: ↑/↓ swap, Delete remove
            item.addEventListener('keydown', function (ev) {
                const idx = parseInt(item.getAttribute('data-col-idx'), 10);
                if (ev.key === 'ArrowUp') {
                    ev.preventDefault();
                    if (idx > 0) _moveReportColumn(idx, idx - 1);
                } else if (ev.key === 'ArrowDown') {
                    ev.preventDefault();
                    const len = (_state.reportColumns || []).length;
                    if (idx < len - 1) _moveReportColumn(idx, idx + 1);
                } else if (ev.key === 'Delete' || ev.key === 'Backspace') {
                    ev.preventDefault();
                    _removeReportColumn(item.getAttribute('data-col-name'));
                }
            });
        });
        // Remove (×) delegate
        list.querySelectorAll('[data-remove-col]').forEach(btn => {
            btn.addEventListener('click', function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                _removeReportColumn(btn.getAttribute('data-remove-col'));
            });
        });
    }

    // EDIT9: LLM hook — POST /api/db-smart/columns/suggest-order
    async function _suggestColumnOrder() {
        const btn = document.getElementById('dswSuggestOrderBtn');
        const cat = _state._columnCatalog || [];
        if (!cat.length) {
            _notify('Önce kolon kataloğu yüklenmeli', 'warning');
            return;
        }
        if (!_state.sourceId || !_state.selectedTableId) {
            _notify('Önce kaynak ve ana tablo seçin', 'warning');
            return;
        }
        // Join tabloları (varsa) — ana tabloyu çıkar
        const joinIds = (_state.selectedTables || []).filter(id => {
            const n = (typeof id === 'number') ? id : parseInt(id, 10);
            return !isNaN(n) && n !== _state.selectedTableId;
        });
        const payload = {
            source_id: _state.sourceId,
            primary_table_id: _state.selectedTableId,
            join_table_ids: joinIds,
            // F8b (ATHENA+APOLLO+POSEIDON): table_id payload'a eklendi.
            // F7 multi-table desteğinde aynı kolon adı farklı tablolarda olabilir
            // (örn. iki tabloda `id`); backend disambiguate edebilsin diye taşıyoruz.
            available_columns: cat.map(c => ({
                name: c.name,
                semantic_type: c.semantic_type,
                table: c.table_name,
                table_id: c.table_id,
            })),
        };
        if (btn) {
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
            btn.dataset._label = btn.textContent;
            btn.textContent = '✨ Düşünüyor…';
        }
        try {
            const data = await _fetchJson(API_BASE + '/columns/suggest-order', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            // F8b: prefer `ordered_pairs` (name + table_id) over `ordered`
            // (legacy name-only list). Falls back to `ordered` if backend
            // is older than F8b.
            const orderedPairs = Array.isArray(data && data.ordered_pairs)
                ? data.ordered_pairs : null;
            const ordered = (orderedPairs && orderedPairs.length)
                ? orderedPairs
                : (Array.isArray(data && data.ordered) ? data.ordered : []);
            if (!ordered.length) {
                _notify('LLM önerisi boş döndü', 'warning');
                return;
            }
            // F8b: Stable key lookup. Catalog'daki her kolonu (table_id, name)
            // çiftiyle indeksle — aynı isimli kolonlar farklı tablolardan
            // gelirse overwrite olmasın. byName (legacy fallback) sadece
            // table_id yoksa kullanılır (eski cached state / heuristic).
            const byKey = {};
            const byName = {};
            cat.forEach(c => {
                if (c.table_id != null) byKey[c.table_id + '::' + c.name] = c;
                // first-wins for legacy lookup (deterministic but logs warn on collision use)
                if (!(c.name in byName)) byName[c.name] = c;
            });
            const newReport = [];
            const usedKeys = {};
            ordered.forEach(item => {
                // Backend may return string (legacy) or {name, table_id} (F8b).
                let name = null;
                let tid = null;
                if (typeof item === 'string') {
                    name = item;
                } else if (item && typeof item === 'object') {
                    name = item.name || item.column_name || null;
                    if (item.table_id != null) tid = item.table_id;
                }
                if (!name) return;
                let c = null;
                if (tid != null && byKey[tid + '::' + name]) {
                    c = byKey[tid + '::' + name];
                } else if (byName[name]) {
                    // Backwards-compat: no table_id in response → first-match.
                    c = byName[name];
                    if (tid == null) {
                        console.warn('[db_smart_wizard] suggest-order: response item ' +
                            'missing table_id for "' + name + '"; falling back to first-match. ' +
                            'Multi-table disambiguation may be wrong.');
                    }
                }
                if (!c) return;
                // Dedupe by (table_id, name) so the same column doesn't appear twice.
                const dedupeKey = (c.table_id != null ? c.table_id : '_') + '::' + c.name;
                if (usedKeys[dedupeKey]) return;
                usedKeys[dedupeKey] = true;
                newReport.push({
                    column_name: c.name,
                    label: c.label,
                    semantic_type: c.semantic_type,
                    table_name: c.table_name,
                    table_id: c.table_id,
                });
            });
            if (!newReport.length) {
                _notify('LLM yanıtı geçerli kolon içermiyordu', 'warning');
                return;
            }
            // F8: push as a slot (LRU max 3). DO NOT replace reportColumns
            // automatically — user opts in via "+ Bu öneriyi uygula".
            _state._suggestionCounter = (_state._suggestionCounter || 0) + 1;
            const slot = {
                id: 's' + _state._suggestionCounter,
                columns: newReport,
                rationale: (data && data.rationale) ? String(data.rationale) : '',
                appliedAt: null,
            };
            const arr = Array.isArray(_state.suggestions) ? _state.suggestions.slice() : [];
            arr.push(slot);
            while (arr.length > 3) arr.shift();
            _state.suggestions = arr;
            _renderSuggestionSlots();
            _notify('✨ Yeni öneri eklendi (Öneri ' + arr.length + '/3)', 'success');
        } catch (e) {
            console.warn('[db_smart_wizard] suggest-order failed:', e);
            _notify('LLM önerisi alınamadı: ' + ((e && e.message) || 'bilinmeyen hata'), 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.removeAttribute('aria-busy');
                if (btn.dataset._label) { btn.textContent = btn.dataset._label; delete btn.dataset._label; }
            }
        }
    }

    // F8 (APOLLO+HEBE+ATHENA): render LLM suggestion slot cards above
    // filter grid. Each card shows column preview + rationale + apply CTA.
    function _renderSuggestionSlots() {
        const host = document.getElementById('dswSuggestSlots');
        if (!host) return;
        const slots = Array.isArray(_state.suggestions) ? _state.suggestions : [];
        if (!slots.length) {
            host.innerHTML = '';
            host.hidden = true;
            return;
        }
        host.hidden = false;
        host.innerHTML = slots.map((s, idx) => {
            const isActive = !!s.appliedAt;
            const cols = Array.isArray(s.columns) ? s.columns : [];
            const colsPreview = cols.slice(0, 6).map(c =>
                '<li>' + _escape(c.label || c.column_name) + '</li>').join('');
            const more = cols.length > 6 ? '<li class="dsw-suggest-more">+' +
                (cols.length - 6) + ' daha…</li>' : '';
            const rationale = s.rationale ? _escape(s.rationale) :
                '<span class="dsw-suggest-no-rat">Açıklama yok</span>';
            return '<div class="dsw-suggest-card' + (isActive ? ' active' : '') +
                '" data-suggest-id="' + _escape(s.id) + '" role="group" ' +
                'aria-label="Öneri ' + (idx + 1) + (isActive ? ' (uygulandı)' : '') + '">' +
                  '<div class="dsw-suggest-card-head">' +
                    '<span class="dsw-suggest-card-title">Öneri ' + (idx + 1) + '</span>' +
                    (isActive ? '<span class="dsw-suggest-card-badge">✓ uygulandı</span>' : '') +
                  '</div>' +
                  '<ul class="dsw-suggest-card-cols">' + colsPreview + more + '</ul>' +
                  '<div class="dsw-suggest-card-rationale">' + rationale + '</div>' +
                  '<button type="button" class="dsw-suggest-apply-btn" ' +
                    'data-apply-suggest="' + _escape(s.id) + '" ' +
                    'aria-label="Öneri ' + (idx + 1) + ' uygula">' +
                    '+ Bu öneriyi uygula' +
                  '</button>' +
                '</div>';
        }).join('');
        // bind apply
        host.querySelectorAll('[data-apply-suggest]').forEach(btn => {
            btn.addEventListener('click', function () {
                _applySuggestionSlot(btn.getAttribute('data-apply-suggest'));
            });
        });
    }

    // F8: apply slot → REPLACE reportColumns (no append). Mark slot active,
    // clear active flag on siblings (only one applied at a time).
    function _applySuggestionSlot(slotId) {
        const slots = Array.isArray(_state.suggestions) ? _state.suggestions : [];
        const slot = slots.find(s => s.id === slotId);
        if (!slot) return;
        const cols = Array.isArray(slot.columns) ? slot.columns : [];
        if (!cols.length) {
            _notify('Bu önerideki kolon listesi boş', 'warning');
            return;
        }
        // Deep-copy columns so later DnD on reportColumns doesn't mutate slot.
        // F8b: table_id de carry edilir (F7 multi-table SQL qualifier için zorunlu).
        // Eski slot'larda table_id yoksa null kalır — _buildWizardState / SQL
        // assembler null table_id'yi tek-tablo davranışına düşürür (geriye uyum).
        _state.reportColumns = cols.map(c => {
            const mapped = {
                column_name: c.column_name,
                label: c.label,
                semantic_type: c.semantic_type,
                table_name: c.table_name,
                table_id: (c.table_id != null) ? c.table_id : null,
            };
            if (mapped.table_id == null) {
                console.warn('[db_smart_wizard] _applySuggestionSlot: legacy slot ' +
                    'column "' + c.column_name + '" missing table_id — first-match ' +
                    'semantics will apply downstream.');
            }
            return mapped;
        });
        const now = Date.now();
        _state.suggestions = slots.map(s => Object.assign({}, s, {
            appliedAt: s.id === slotId ? now : null,
        }));
        _renderSuggestionSlots();
        _renderReportColumns();
        const idx = slots.findIndex(s => s.id === slotId) + 1;
        const tail = slot.rationale ? ': ' + slot.rationale : '';
        _notify('Öneri ' + idx + ' uygulandı' + tail, 'success');
    }

    // ============================================
    // Step 4 — Preview (SQL + cost)
    // ============================================

    // P20-D: wizard_state üretimi tek bir yere alındı (preview + AST mount paylaşır).
    function _buildWizardState() {
        const tableName = _state.selectedTableObjectName ||
            (_state.selectedTableLabel || 'unknown').split('.').pop();
        // EDIT9 (ATHENA): step-3 DnD'de seçilen kolonlar varsa SELECT'i o sırayla
        // üret; aksi halde geriye dönük davranış (*).
        const rc = Array.isArray(_state.reportColumns) ? _state.reportColumns : [];
        const selectedColumns = rc.length
            ? rc.map(c => ({ expr: c.column_name, alias: c.label || c.column_name }))
            : [{ expr: '*' }];
        const ws = {
            source_id: _state.sourceId,
            dialect: 'postgresql',
            base_table: {
                schema: _state.selectedTableSchema || undefined,
                table: tableName,
                alias: 't',
            },
            selected_columns: selectedColumns,
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
        // F14 (HEBE+HERMES+ATHENA): multi-metric — UI seçimini her zaman array
        // olarak gönder. Backend prompt şu an `metric` (tekil) tüketiyor (F14b
        // TODO: F9 prompt revision). `metrics` array bilgisel; downstream
        // consumer'lar (save flow, future prompt) için forward-compat.
        if (_state.selectedMetrics && _state.selectedMetrics.size > 0) {
            ws.metrics = Array.from(_state.selectedMetrics).map(mk => {
                const m = _state._metricsIndex[mk] || {};
                return {
                    metric_key: mk,
                    sql_template: (m.sql_templates || {}).postgresql || null,
                    placeholders: { table: tableName, limit: '100' },
                };
            });
        }
        // F21b (HEBE+ATHENA 2026-05-25): picker seçimini de persistle —
        // edit-mode reopen sırasında step 1 chip'lerini ve "Çalıştır" için
        // primary_table_id + join_table_ids'i rehydrate edebilmek için.
        // (LLM SQL üretimi tableName + base_table kullanmaya devam eder.)
        ws.selectedTableId = _state.selectedTableId || null;
        ws.selectedTableObjectName = _state.selectedTableObjectName || null;
        ws.selectedTableSchema = _state.selectedTableSchema || null;
        ws.selectedTableLabel = _state.selectedTableLabel || null;
        ws.selectedTables = Array.isArray(_state.selectedTables)
            ? _state.selectedTables.slice() : [];
        ws.joinCandidates = Array.isArray(_state.joinCandidates)
            ? _state.joinCandidates.map(j => ({
                table_id: (j && j.table_id != null) ? j.table_id : null,
                name: (j && j.name) || null,
                schema: (j && j.schema) || null,
                label: (j && j.label) || null,
            }))
            : [];
        // v3.37.3 (bulgular-2 / Bulgu 6): edit-mode reopen için "Raporda
        // görünecek kolonlar" tam shape ile persist edilir. `selected_columns`
        // (expr/alias) SQL üretimi içindir; `reportColumns` UI state'ini
        // restore eden alandır — _loadSavedReport ve _hydrateFromSavedReport
        // burayı arıyor.
        ws.reportColumns = rc.slice();
        return ws;
    }

    async function _loadPreview() {
        const panel = document.getElementById('dswStep4');
        const hint = document.getElementById('dswStep4Hint');
        const legacy = document.getElementById('dswLegacyPreview');
        if (!panel) return;
        // v3.36.0 F9 (HEBE+APOLLO): Çalıştır butonu — Önizleme step yüklenince
        // mount et (idempotent). Yetersiz state durumunda dahi DOM'da kalır ama
        // _runGeneratedReport tıklamasında erken çıkar.
        // v3.37.2 B2 — LLM chips header run-btn'den ÖNCE mount
        try { _ensureLlmChipsHeader(panel); } catch (e) { /* defansif */ }
        _ensureRunButton(panel);
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
            // v3.36.0 F10 — save flow için son üretilen SQL'i state'e tut
            _state.lastGeneratedSql = sql || null;
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
            // v3.37.0 B2 (HEBE-FE 2026-05-25): SQL'i manuel pretty-print formatla.
            if (legacy) {
                legacy.textContent = _prettyPrintSql(sql);
                legacy.setAttribute('aria-label', 'Üretilen SQL');
                if (!_astEditorMounted) legacy.removeAttribute('hidden');
            }
            // v3.37.0 B7b: ORDER BY chip render
            try { _renderOrderByChips(); } catch (e) { /* defansif */ }
            // v3.37.0 B6/B7a: Çalıştır footer mount (idempotent)
            try { _ensureRunFooter(panel); } catch (e) { /* defansif */ }
        } catch (e) {
            if (hint) hint.textContent = 'Hata: ' + e.message;
            _notify('Önizleme oluşturulamadı: ' + e.message, 'error');
        } finally {
            _setBusy(panel, false);
        }
    }

    // ============================================
    // v3.36.0 F9 — Çalıştır button + Rapor Sonucu modal (HEBE+APOLLO+POSEIDON)
    // ============================================

    // Bulgular3 / Bulgu 6: "Çalıştır" butonu sticky footer'a taşındı (Format
    // Öner ile aynı eylem grubunda). Bu fonksiyon artık eski runbar/header-bar
    // DOM'unu (varsa) temizleyen idempotent bir cleanup helper'i. Footer'daki
    // gerçek mount `_ensureRunFooter` içinde.
    function _ensureRunButton(panel) {
        if (!panel) return;
        const oldBar = panel.querySelector('[data-dsw-runbar]');
        if (oldBar && oldBar.parentNode) oldBar.parentNode.removeChild(oldBar);
        const oldHeader = panel.querySelector('[data-dsw-step4-headerbar]');
        if (oldHeader && oldHeader.parentNode) {
            // hint'i geri panel'e koy, headerBar'ı kaldır
            // Review fix #3: parentNode null check (defansif — oldHeader detached path).
            const parent = oldHeader.parentNode;
            const hint = oldHeader.querySelector('#dswStep4Hint');
            if (hint && parent) parent.insertBefore(hint, oldHeader);
            if (parent) parent.removeChild(oldHeader);
        }
    }

    // v3.37.2 B2 — Step 4 önizleme panel'inde LLM-kaynaklı seçili metrikler için
    // "✨ LLM Önerileri" alt-başlık + chip listesi. Idempotent; LLM seçimi
    // yoksa block kaldırılır.
    function _ensureLlmChipsHeader(panel) {
        if (!panel) return;
        let block = panel.querySelector('[data-dsw-llm-chips]');
        const idx = _state._metricsIndex || {};
        const selected = _state.selectedMetrics;
        if (!selected || typeof selected.forEach !== 'function') {
            if (block) block.remove();
            return;
        }
        const llmItems = [];
        selected.forEach(function (key) {
            const m = idx[key];
            if (m && m.source === 'llm') llmItems.push(m);
        });
        if (!llmItems.length) {
            if (block) block.remove();
            return;
        }
        if (!block) {
            block = document.createElement('div');
            block.setAttribute('data-dsw-llm-chips', '1');
            block.className = 'dsw-llm-chips-header';
            panel.insertBefore(block, panel.firstChild);
        }
        const title = '<h5 class="dsw-llm-chips-title">✨ LLM Önerileri</h5>';
        const chips = llmItems.map(function (m) {
            const labelTxt = m.name_tr || m.metric_name || m.metric_key || '';
            const conf = m.confidence != null
                ? ' <span class="dsw-llm-chip-conf">' + Math.round(m.confidence * 100) + '%</span>'
                : '';
            // Bulgular3 / Bulgu 4: tooltip'e rationale + (TR/SQL farkliysa) orijinal tablo adi
            const tooltipParts = [];
            const rat = m.rationale || m.description_tr || '';
            if (rat) tooltipParts.push(rat);
            const tableTr = m.table_name_tr || '';
            const tableSql = m.table_object_name || '';
            if (tableTr && tableSql && tableTr.toUpperCase() !== tableSql.toUpperCase()) {
                tooltipParts.push('Tablo (orijinal): ' + tableSql);
            }
            const titleAttr = tooltipParts.length
                ? ' title="' + _escape(tooltipParts.join('\n')) + '"' : '';
            const tableInline = tableTr
                ? ' <span class="dsw-llm-chip-table-inline">· ' + _escape(tableTr) + '</span>'
                : (tableSql ? ' <span class="dsw-llm-chip-table-inline">· ' + _escape(tableSql) + '</span>' : '');
            return '<span class="dsw-llm-chip"' + titleAttr + '>' +
                _escape(labelTxt) + conf + tableInline + '</span>';
        }).join('');
        block.innerHTML = title + '<div class="dsw-llm-chips-list">' + chips + '</div>';
    }

    // Collect wizard state and POST to /generate-report → open result modal.
    async function _runGeneratedReport() {
        if (!_state.sourceId || !_state.selectedTableId) {
            _notify('Önce kaynak ve tablo seçin', 'warning');
            return;
        }
        const btn = document.getElementById('dswRunBtn');
        if (btn) {
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
            btn.textContent = '⏳ Çalıştırılıyor...';
        }
        const payload = _buildGenerateReportPayload();
        try {
            const data = await _fetchJson(API_BASE + '/generate-report', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            // v3.36.0 F10 hook: keep generated SQL for save flow.
            if (data && data.sql) _state.lastGeneratedSql = data.sql;
            _openResultModal(data || {}, payload);
        } catch (e) {
            _openResultModal({
                success: false,
                error: _mapApiError(e),
                sql: '',
                rationale: '',
                columns: [],
                rows: [],
                row_count: 0,
                elapsed_ms: 0,
            }, payload, e);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.removeAttribute('aria-busy');
                btn.textContent = '▶️ Çalıştır';
            }
        }
    }

    // Compose the /generate-report POST body from current wizard state.
    function _buildGenerateReportPayload() {
        const primaryId = _state.selectedTableId;
        // F19 (ATHENA+ARES 2026-05-25): selectedTables array of integer id
        // (picker confirm L315 `[primaryId].concat(joins.map(parseInt))`).
        // Önceki kod `t.id || t.table_id` ile object varsayıp undefined alıyordu
        // → joinIds boş → backend allowed_tables sadece primary'yi içeriyor
        // → JOIN'deki ikinci tablo "Tablo erişim yetkisi yok" reddediliyordu.
        // Defensive: primitive id, object, ya da string id hepsini destekle.
        const tables = Array.isArray(_state.selectedTables) ? _state.selectedTables : [];
        const joinIds = tables
            .map(t => {
                if (t == null) return null;
                if (typeof t === 'object') {
                    return (t.id != null) ? t.id : t.table_id;
                }
                return t;  // primitive (number/string id)
            })
            .filter(id => id != null && Number(id) !== Number(primaryId));

        const reportColumns = (Array.isArray(_state.reportColumns) ? _state.reportColumns : [])
            .map(c => ({
                name: c.column_name,
                table_name: c.table_name || null,
                semantic_type: c.semantic_type || null,
            }));

        // fk_context: best-effort — only entries with all 4 fields.
        const fkContext = (Array.isArray(_state.fkContext) ? _state.fkContext : [])
            .filter(fk => fk && fk.from_table && fk.to_table && fk.from_col && fk.to_col)
            .map(fk => ({
                from_table: fk.from_table,
                to_table: fk.to_table,
                from_col: fk.from_col,
                to_col: fk.to_col,
            }));

        // F14 (HEBE+HERMES+ATHENA): multi-metric payload.
        // `metric` tekil — backwards-compat, F9 prompt'unun mevcut tüketim noktası
        //   (son seçilen kayıt = _state.metric ile senkron).
        // `metrics` array — UI multi-select kümesi, ileride F14b kapsamında F9
        //   prompt'u multi-metric'e geçtiğinde tüketilecek (forward-compat).
        const metricsArr = (_state.selectedMetrics && _state.selectedMetrics.size > 0)
            ? Array.from(_state.selectedMetrics).map(mk => _state._metricsIndex[mk] || { metric_key: mk })
            : [];
        return {
            source_id: Number(_state.sourceId),
            primary_table_id: Number(primaryId),
            join_table_ids: joinIds.map(Number),
            report_columns: reportColumns,
            metric: _state.metric || null,
            metrics: metricsArr,
            user_note: _state.userNote || '',
            fk_context: fkContext,
            limit: 100,
        };
    }

    // ── Result modal ────────────────────────────────────────
    let _resultModalEls = null;

    function _closeResultModal() {
        if (!_resultModalEls) return;
        try { document.removeEventListener('keydown', _resultModalEls.onKey, true); } catch (_) {}
        try { _BodyScrollLock.unlock(); } catch (_) {}
        if (_resultModalEls.overlay && _resultModalEls.overlay.parentNode) {
            _resultModalEls.overlay.parentNode.removeChild(_resultModalEls.overlay);
        }
        const opener = _resultModalEls.opener;
        _resultModalEls = null;
        if (opener && typeof opener.focus === 'function') {
            try { opener.focus(); } catch (_) {}
        }
    }

    function _openResultModal(data, payload, errorObj) {
        // If one is already open, replace it.
        if (_resultModalEls) _closeResultModal();

        const overlay = document.createElement('div');
        overlay.className = 'dsw-result-modal-overlay';
        overlay.setAttribute('role', 'presentation');
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) _closeResultModal();
        });

        const modal = document.createElement('div');
        modal.className = 'dsw-result-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'dswResultModalTitle');

        // Header
        const header = document.createElement('div');
        header.className = 'dsw-result-modal-header';
        const title = document.createElement('h3');
        title.id = 'dswResultModalTitle';
        title.className = 'dsw-result-modal-title';
        title.textContent = 'Rapor Sonucu';
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'dsw-result-modal-close';
        closeBtn.setAttribute('aria-label', 'Kapat');
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', _closeResultModal);
        header.appendChild(title);
        header.appendChild(closeBtn);

        // Body
        const body = document.createElement('div');
        body.className = 'dsw-result-modal-body';

        const success = !!data.success;
        const fallback = !!data.fallback;
        const errorMsg = data.error || (errorObj ? (errorObj.message || String(errorObj)) : '');

        // SQL preview (collapsible)
        // v3.37.0 B2 (HEBE-FE 2026-05-25): SQL'i pretty-print et — kullanıcı
        // anahtar kelimeleri net görsün.
        if (data.sql) {
            const sqlWrap = document.createElement('details');
            sqlWrap.className = 'dsw-result-sql-wrap';
            const sqlSummary = document.createElement('summary');
            sqlSummary.textContent = '📝 Üretilen SQL' + (fallback ? '  (fallback)' : '');
            const sqlPre = document.createElement('pre');
            sqlPre.className = 'dsw-result-sql';
            sqlPre.textContent = _prettyPrintSql(data.sql);
            sqlWrap.appendChild(sqlSummary);
            sqlWrap.appendChild(sqlPre);
            body.appendChild(sqlWrap);
        }

        if (success) {
            // Stats line
            const stats = document.createElement('div');
            stats.className = 'dsw-result-stats';
            const parts = [
                (data.row_count || 0) + ' satır',
                (data.elapsed_ms || 0) + ' ms',
            ];
            if (data.truncated) parts.push('⚠️ kesildi');
            if (fallback) parts.push('⚠️ fallback SQL');
            stats.textContent = parts.join(' · ');
            body.appendChild(stats);

            // Result table
            const tableWrap = document.createElement('div');
            tableWrap.className = 'dsw-result-table-wrap';
            const table = document.createElement('table');
            table.className = 'dsw-result-table';
            const cols = Array.isArray(data.columns) ? data.columns : [];
            const rows = Array.isArray(data.rows) ? data.rows : [];
            const thead = document.createElement('thead');
            const trh = document.createElement('tr');
            cols.forEach(c => {
                const th = document.createElement('th');
                th.textContent = String(c);
                trh.appendChild(th);
            });
            thead.appendChild(trh);
            table.appendChild(thead);
            const tbody = document.createElement('tbody');
            rows.slice(0, 500).forEach(r => {
                const tr = document.createElement('tr');
                (Array.isArray(r) ? r : []).forEach(v => {
                    const td = document.createElement('td');
                    td.textContent = (v == null ? '' : String(v));
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
            if (!rows.length) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = Math.max(1, cols.length);
                td.className = 'dsw-result-empty';
                td.textContent = 'Sonuç yok.';
                tr.appendChild(td);
                tbody.appendChild(tr);
            }
            table.appendChild(tbody);
            tableWrap.appendChild(table);
            body.appendChild(tableWrap);

            // Rationale
            if (data.rationale) {
                const rat = document.createElement('div');
                rat.className = 'dsw-result-rationale';
                rat.textContent = '💡 LLM Yorumu: ' + data.rationale;
                body.appendChild(rat);
            }
        } else {
            // Error state
            const err = document.createElement('div');
            err.className = 'dsw-result-error';
            err.textContent = 'Rapor üretilemedi. ' +
                (errorMsg ? '' : 'Lütfen yorum alanını sadeleştirip tekrar deneyin.');
            body.appendChild(err);
            if (errorMsg) {
                const det = document.createElement('details');
                det.className = 'dsw-result-error-detail';
                const sum = document.createElement('summary');
                sum.textContent = 'Teknik detay';
                const pre = document.createElement('pre');
                pre.textContent = String(errorMsg);
                det.appendChild(sum);
                det.appendChild(pre);
                body.appendChild(det);
            }
        }

        // Footer actions
        const actions = document.createElement('div');
        actions.className = 'dsw-result-modal-actions';

        const chartBtn = document.createElement('button');
        chartBtn.type = 'button';
        chartBtn.className = 'dsw-result-action dsw-result-action-chart';
        chartBtn.textContent = '📊 Grafik';
        chartBtn.disabled = !success;
        chartBtn.addEventListener('click', function () {
            // F11 hook — DbSmartChart loaded olarak gelirse aç, değilse uyar.
            if (window.DbSmartChart && typeof window.DbSmartChart.open === 'function') {
                try {
                    window.DbSmartChart.open({
                        columns: data.columns || [],
                        rows: data.rows || [],
                    });
                } catch (e) {
                    console.warn('[db_smart_wizard] DbSmartChart.open failed:', e);
                    _notify('Grafik açılamadı', 'error');
                }
            } else {
                _notify('Grafik modülü hazırlanıyor', 'info');
            }
        });

        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.className = 'dsw-result-action dsw-result-action-save';
        saveBtn.textContent = '💾 Raporu Kaydet';
        saveBtn.disabled = !data.sql;
        saveBtn.addEventListener('click', function () {
            // F10 hook — modüle gömülü _openSaveModal varsa kullan, yoksa toast.
            // Generated SQL'i state'e tutuyoruz ki save flow alanı doldurulabilsin.
            try { _state.lastGeneratedSql = data.sql || _state.lastGeneratedSql; } catch (_) {}
            if (typeof _openSaveModal === 'function') {
                try {
                    _openSaveModal();
                } catch (e) {
                    console.warn('[db_smart_wizard] _openSaveModal failed:', e);
                    _notify('Kayıt akışı başlatılamadı', 'error');
                }
            } else {
                _notify('Kayıt akışı hazırlanıyor', 'info');
            }
        });

        const closeFooterBtn = document.createElement('button');
        closeFooterBtn.type = 'button';
        closeFooterBtn.className = 'dsw-result-action dsw-result-action-close';
        closeFooterBtn.textContent = 'Kapat';
        closeFooterBtn.addEventListener('click', _closeResultModal);

        actions.appendChild(chartBtn);
        actions.appendChild(saveBtn);
        actions.appendChild(closeFooterBtn);

        modal.appendChild(header);
        modal.appendChild(body);
        modal.appendChild(actions);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        try { _BodyScrollLock.lock(); } catch (_) {}
        const opener = document.activeElement;
        const onKey = function (e) {
            if (e.key === 'Escape') {
                e.stopPropagation();
                _closeResultModal();
            }
        };
        document.addEventListener('keydown', onKey, true);
        _resultModalEls = { overlay: overlay, modal: modal, onKey: onKey, opener: opener };

        // Focus close button for keyboard accessibility.
        try { closeBtn.focus(); } catch (_) {}
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
    // F17 (2026-05-25): `type: 'select'` defansif olarak eklendi — backend
    // ast_renderer `_require_select` ve `/explain` her ikisi de bu shape'i
    // bekliyor; eksik olduğunda eskiden 400 dönüyordu.
    function _buildStarterAst() {
        const ws = _buildWizardState();
        return {
            type: 'select',
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
        // FIX5 F2 (ATHENA): AST snapshot drop — re-mount fresh load yapsın
        // (stale snapshot UI ↔ server tutarsızlığını engelle).
        _state.currentAst = null;
        // Legacy preview tekrar görünür — kullanıcı 4. adıma dönerse _loadPreview yine yazar.
        const legacy = document.getElementById('dswLegacyPreview');
        if (legacy && legacy.textContent) legacy.removeAttribute('hidden');
    }

    // Step değişiminde data fetch tetikle
    function _onStepEnter(n) {
        // v3.37.1 B (HEBE+METIS): Adim degisirken pending LLM metric-suggest'i iptal et.
        if (_state._metricLlmAbort) {
            try { _state._metricLlmAbort.abort(); } catch (_) { /* ignore */ }
            _state._metricLlmAbort = null;
        }
        if (n === 2) _loadMetrics();
        else if (n === 3) _loadColumns();
        else if (n === AST_EDITOR_STEP_IDX) {
            // P20-D: preview önce — AST editor mount sırasında lastExplain için
            // sunucudan cost rozetini çağırır; sonra AST editor mount edilir.
            _loadPreview();
            _mountAstEditor();
        }
        // v3.37.0 (HEBE-FE): LLM/UX butonlarını ilgili step'te mount et.
        try {
            if (typeof _v337StepHook === 'function') _v337StepHook(n);
        } catch (e) { /* defansif */ }
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
    // v3.35.0: data-step indeksleri sürekli değil — _STEPS sırası ile gez.
    function _onStepperKeydown(e) {
        const tabs = Array.from(document.querySelectorAll('.dsw-stepper .dsw-step'));
        if (!tabs.length) return;
        const curIdx = Math.max(0, _STEPS.indexOf(_state.currentStep));
        let targetIdx = -1;
        switch (e.key) {
            case 'ArrowRight':
            case 'ArrowDown':
                targetIdx = Math.min(_STEPS.length - 1, curIdx + 1); break;
            case 'ArrowLeft':
            case 'ArrowUp':
                targetIdx = Math.max(0, curIdx - 1); break;
            case 'Home':
                targetIdx = 0; break;
            case 'End':
                targetIdx = _STEPS.length - 1; break;
            default:
                return;
        }
        e.preventDefault();
        const target = _STEPS[targetIdx];
        _setStep(target);
        const tab = tabs.find(t => parseInt(t.dataset.step, 10) === target);
        if (tab) tab.focus();
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
        // v3.37.3 (bulgular-2 / Bulgu 7a): sonraki açılış yeni rapor olarak başlasın.
        _state.editingReportId = null;
        // Bulgular3 / Review fix #1: oturumlar arası leak'i önle — toggle bayrakları
        // ve runtime view-state alanlarını sıfırla.
        _state._showStaticMetrics = undefined;
        _state._llmActive = undefined;
        _state._lastFallbackUsed = undefined;
        _state._lastMetricLlmError = null;
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

    // Bulgular3 / Bulgu 7: "Yeni Keşif" tıklandığında wizard state'ini fresh sıfırla.
    // _akiKesifOpenWizard(null) → openAsModal({reportId: null}) → bu helper çağrılır.
    // Saved-report edit path (_hydrateFromSavedReport) bu helper'ı KULLANMAZ.
    function _resetWizardState() {
        try { if (_astEditorMounted) _unmountAstEditor(); } catch (_) { /* defansif */ }
        _state.sessionUid = null;
        _state.currentStep = 0;
        _state.sourceId = null;
        _state.selectedTableId = null;
        _state.selectedTableObjectName = null;
        _state.selectedTableSchema = null;
        _state.selectedTableLabel = null;
        _state.selectedTables = [];
        _state.joinTableIds = [];
        _state.metric = null;
        _state.selectedMetrics = new Set();
        _state._metricsIndex = {};
        _state._metricCategories = {};
        _state._staticCategoriesShadow = {};
        _state._llmActive = undefined;
        _state._showStaticMetrics = undefined;
        _state._lastFallbackUsed = undefined;
        _state._lastMetricLlmError = null;
        _state._lastColumnSuggestion = null;
        _state._columnCatalog = [];
        _state._columnGroups = [];
        _state.filters = [];
        _state.reportColumns = [];
        _state.suggestions = [];
        _state._suggestionCounter = 0;
        _state.userNote = '';
        _state.user_intent = '';
        _state.currentAst = null;
        _state.lastGeneratedSql = null;
        _state.editingReportId = null;
        _state.format = null;
        _state.order_by = [];
        // UI input'larını da temizle (Step 0 arama kutusu, sticky-footer textarea).
        try {
            const q = document.getElementById('dswSearchQ');
            if (q) q.value = '';
            const ui = document.getElementById('user-intent');
            if (ui) ui.value = '';
            const un = document.getElementById('dswUserNote');
            if (un) un.value = '';
        } catch (_) { /* defansif */ }
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
            // v3.35.0: prev/next _STEPS sırasını izler (step 1 skipliyor).
            prev.addEventListener('click', () => _setStep(_stepDelta(-1)));
            prev._bound = true;
        }
        const next = document.getElementById('dswNextBtn');
        if (next && !next._bound) {
            next.addEventListener('click', () => _setStep(_stepDelta(+1)));
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
        // v3.34.4 B1: init'te Ara butonu doğru state'te (henüz seçim yok → aktif)
        _updateAraButtonState();
        // v3.36.0 F10 — Saved Reports section bind + initial load
        _bindSavedReportsUi();
        _loadSavedReportsList();
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

        // Bulgular3 / Bulgu 7: "Yeni Keşif" akışında tüm önceki state'i fresh sıfırla
        // — eski seçim/tablo/metrik/filter/SQL UI'da görünmesin. Saved-report edit
        // path'i (_hydrateFromSavedReport) state'i kendi şemasıyla restore edecek.
        if (!opts.reportId) {
            _resetWizardState();
        }

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

        // FIX5 P2 (ATHENA+HEBE): body scroll-lock ref-count (modal stacking safe)
        _BodyScrollLock.lock();

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
        // v3.37.3 (bulgular-2 / Bulgu 7a): modal edit-reopen edit-mode işaret.
        _state.editingReportId = parseInt(reportId, 10) || reportId;
        const url = API_BASE + '/saved-reports/' + encodeURIComponent(reportId);
        const data = await _fetchJson(url);
        if (data && data.wizard_state && typeof data.wizard_state === 'object') {
            const ws = data.wizard_state;
            // F22c (HEBE+ATHENA 2026-05-25): _buildWizardState `source_id`
            // (snake) kaydediyor ama önceki hydrate yalnız `sourceId` (camel)
            // arıyordu — sonuç: edit-mode metrik step "Lütfen önce veri
            // kaynağı seçin" diyordu. Her iki anahtarı + top-level fallback.
            if (ws.sourceId != null) _state.sourceId = ws.sourceId;
            else if (ws.source_id != null) _state.sourceId = ws.source_id;
            else if (data.source_id != null) _state.sourceId = data.source_id;
            if (ws.selectedTableId) _state.selectedTableId = ws.selectedTableId;
            if (ws.selectedTableObjectName) _state.selectedTableObjectName = ws.selectedTableObjectName;
            if (ws.selectedTableSchema) _state.selectedTableSchema = ws.selectedTableSchema;
            if (ws.selectedTableLabel) _state.selectedTableLabel = ws.selectedTableLabel;
            if (Array.isArray(ws.selectedTables)) _state.selectedTables = ws.selectedTables;
            // v3.37.3 (bulgular-2 / Bulgu 6): modal edit-reopen reportColumns restore.
            const restoredCols = _restoreReportColumns(ws);
            if (restoredCols) _state.reportColumns = restoredCols;
            if (ws.metric) _state.metric = ws.metric;
            // F14: multi-metric restore — ws.metrics array (forward-compat).
            if (Array.isArray(ws.metrics) && ws.metrics.length) {
                _state.selectedMetrics = new Set();
                _state._metricsIndex = _state._metricsIndex || {};
                ws.metrics.forEach(m => {
                    if (!m || !m.metric_key) return;
                    _state.selectedMetrics.add(m.metric_key);
                    _state._metricsIndex[m.metric_key] = m;
                });
            } else if (ws.metric && ws.metric.metric_key) {
                _state.selectedMetrics = new Set([ws.metric.metric_key]);
                _state._metricsIndex = _state._metricsIndex || {};
                _state._metricsIndex[ws.metric.metric_key] = ws.metric;
            }
            if (Array.isArray(ws.filters)) _state.filters = ws.filters;
            // F21b (HEBE+ATHENA 2026-05-25): old reports may not have these top-level
            // fields — fall back to base_table for primary identity (table_id absent
            // ise picker reopen sınırlı kalır ama chip görüntüsü tutarlı olur).
            if (!_state.selectedTableObjectName && ws.base_table && ws.base_table.table) {
                _state.selectedTableObjectName = ws.base_table.table;
            }
            if (!_state.selectedTableSchema && ws.base_table && ws.base_table.schema) {
                _state.selectedTableSchema = ws.base_table.schema;
            }
            if (!_state.selectedTableLabel) {
                _state.selectedTableLabel = _state.selectedTableObjectName ||
                    (_state.selectedTableSchema
                        ? _state.selectedTableSchema + '.' + _state.selectedTableObjectName
                        : null);
            }
            if (Array.isArray(ws.joinCandidates)) {
                _state.joinCandidates = ws.joinCandidates.slice();
            }
            _setStep(0);
            // Step 0 panel'ine seçimi yansıt (chip render + Next aktif).
            if (_state.selectedTableObjectName || _state.selectedTableLabel) {
                try {
                    const primaryObj = {
                        table_id: _state.selectedTableId,
                        label: _state.selectedTableLabel,
                        name: _state.selectedTableObjectName,
                        schema: _state.selectedTableSchema,
                    };
                    const joinsArr = Array.isArray(_state.joinCandidates)
                        ? _state.joinCandidates : [];
                    _renderSelectedSummary(primaryObj, joinsArr);
                    const next = document.getElementById('dswNextBtn');
                    if (next) next.disabled = false;
                    if (typeof _updateAraButtonState === 'function') _updateAraButtonState();
                } catch (e) {
                    console.warn('[DbSmartWizard] hydrate render failed', e);
                }
            }
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

        // FIX5 P2 (ATHENA+HEBE): body scroll-lock ref-count release
        _BodyScrollLock.unlock();

        // Return focus
        if (_modalState.opener && typeof _modalState.opener.focus === 'function') {
            try { _modalState.opener.focus(); } catch (e) { /* ignore */ }
        }

        const resolve = _modalState.resolve;
        _modalState = {
            open: false, overlay: null, dialog: null,
            panelOrigParent: null, panelOrigNextSibling: null,
            resolve: null, opener: null,
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

    // ============================================
    // v3.36.0 F10 — Saved Reports CRUD entegrasyonu
    // ============================================
    //   - Mount sırasında step-0 üstüne "Kayıtlı Raporlarım" listesi çizilir.
    //   - Önizleme (step-4) altındaki "Raporu Kaydet" butonu modal açar.
    //   - Aç → GET /saved-reports/{id} → _state restore → step-4 sıçra.
    //   - Sil → DELETE /saved-reports/{id} → liste refresh.

    function _fmtRelativeDate(iso) {
        if (!iso) return '';
        try {
            const dt = new Date(iso);
            if (isNaN(dt.getTime())) return '';
            const diffMs = Date.now() - dt.getTime();
            const m = Math.floor(diffMs / 60000);
            if (m < 1) return 'az önce';
            if (m < 60) return m + ' dk önce';
            const h = Math.floor(m / 60);
            if (h < 24) return h + ' sa önce';
            const d = Math.floor(h / 24);
            if (d < 30) return d + ' gün önce';
            return dt.toLocaleDateString('tr-TR');
        } catch (e) { return ''; }
    }

    async function _loadSavedReportsList() {
        const list = document.getElementById('dswSavedReportsList');
        const hint = document.getElementById('dswSavedReportsHint');
        if (!list) return;
        list.setAttribute('aria-busy', 'true');
        if (hint) hint.textContent = 'Yükleniyor…';
        try {
            const data = await _fetchJson(API_BASE + '/saved-reports?limit=5&offset=0');
            const items = (data && Array.isArray(data.items)) ? data.items.slice(0, 5) : [];
            _renderSavedReports(items);
            if (hint) hint.textContent = items.length ? (items.length + ' rapor') : '';
        } catch (e) {
            console.warn('[db_smart_wizard] _loadSavedReportsList failed:', e);
            list.innerHTML = '<div class="dsw-saved-reports-empty">Kayıtlı raporlar yüklenemedi.</div>';
            if (hint) hint.textContent = 'Hata';
        } finally {
            list.setAttribute('aria-busy', 'false');
        }
    }

    function _renderSavedReports(items) {
        const list = document.getElementById('dswSavedReportsList');
        if (!list) return;
        if (!items || !items.length) {
            list.innerHTML = '<div class="dsw-saved-reports-empty">Henüz kayıtlı rapor yok. Akıllı Keşif ile oluşturup kaydedebilirsiniz.</div>';
            return;
        }
        const html = items.map(function (r) {
            const id = String(r.id);
            const name = _escape(r.name || '(adsız rapor)');
            const desc = _escape((r.description || '').slice(0, 120) + ((r.description || '').length > 120 ? '…' : ''));
            const rel = _escape(_fmtRelativeDate(r.updated_at || r.created_at));
            return '<article class="dsw-saved-report-card" role="listitem" data-report-id="' + _escape(id) + '">' +
                '<div class="dsw-saved-report-main">' +
                  '<h5 class="dsw-saved-report-name" title="' + name + '">' + name + '</h5>' +
                  (desc ? '<p class="dsw-saved-report-desc">' + desc + '</p>' : '') +
                  (rel ? '<span class="dsw-saved-report-date">' + rel + '</span>' : '') +
                '</div>' +
                '<div class="dsw-saved-report-actions">' +
                  '<button type="button" class="dsw-btn-sm" data-action="open" aria-label="Raporu aç">Aç</button>' +
                  '<button type="button" class="dsw-btn-sm dsw-btn-danger" data-action="delete" aria-label="Raporu sil">Sil</button>' +
                '</div>' +
              '</article>';
        }).join('');
        list.innerHTML = html;
        // Event delegation
        if (!list._bound) {
            list.addEventListener('click', function (ev) {
                const btn = ev.target.closest('button[data-action]');
                if (!btn) return;
                const card = btn.closest('.dsw-saved-report-card');
                if (!card) return;
                const rid = parseInt(card.getAttribute('data-report-id'), 10);
                if (isNaN(rid)) return;
                const act = btn.getAttribute('data-action');
                if (act === 'open') _loadSavedReport(rid);
                else if (act === 'delete') _confirmDeleteSavedReport(rid, card);
            });
            list._bound = true;
        }
    }

    // v3.37.3 (bulgular-2 / Bulgu 6): reportColumns restore helper. Yeni
    // kayıtlarda `ws.reportColumns` tam shape; eski kayıtlarda yalnız
    // `ws.selected_columns` ({expr, alias}) var — reverse-map ile UI state'i
    // geri kazandırılır.
    //
    // PR-5/R3: backward-compat restore'da `_columnCatalog` doluysa
    // `semantic_type`/`table_id`/`table_name` alanlarını cross-reference ile
    // geri kazandırır — eski raporlarda metric-aware uyarı ve multi-table
    // chip görünümü tam çalışsın.
    function _restoreReportColumns(ws) {
        if (Array.isArray(ws.reportColumns) && ws.reportColumns.length) {
            return ws.reportColumns.slice();
        }
        if (!Array.isArray(ws.selected_columns)) return null;
        const catalog = Array.isArray(_state._columnCatalog) ? _state._columnCatalog : [];
        const byName = {};
        catalog.forEach(function (c) {
            if (c && c.name && !byName[c.name]) byName[c.name] = c;
        });
        return ws.selected_columns
            .filter(function (c) { return c && c.expr && c.expr !== '*'; })
            .map(function (c) {
                const cat = byName[c.expr] || null;
                return {
                    column_name: c.expr,
                    label: c.alias || (cat && cat.label) || c.expr,
                    semantic_type: cat ? cat.semantic_type : undefined,
                    table_name: cat ? cat.table_name : undefined,
                    table_id: cat ? cat.table_id : undefined,
                };
            });
    }

    async function _loadSavedReport(reportId) {
        try {
            const url = API_BASE + '/saved-reports/' + encodeURIComponent(reportId);
            const data = await _fetchJson(url);
            if (!data || typeof data !== 'object') {
                _notify('Rapor verisi alınamadı.', 'error');
                return;
            }
            // v3.37.3 (bulgular-2 / Bulgu 7a): edit-mode işaret.
            _state.editingReportId = parseInt(reportId, 10) || reportId;
            const ws = data.wizard_state || {};
            // _state restore — yalnız tanımlı alanları yaz, geri kalanı koru.
            if (ws.sourceId != null) _state.sourceId = ws.sourceId;
            else if (data.source_id != null) _state.sourceId = data.source_id;
            if (ws.selectedTableId != null) _state.selectedTableId = ws.selectedTableId;
            if (ws.selectedTableObjectName) _state.selectedTableObjectName = ws.selectedTableObjectName;
            if (ws.selectedTableSchema) _state.selectedTableSchema = ws.selectedTableSchema;
            if (ws.selectedTableLabel) _state.selectedTableLabel = ws.selectedTableLabel;
            if (Array.isArray(ws.selectedTables)) _state.selectedTables = ws.selectedTables.slice();
            if (Array.isArray(ws.joinTableIds)) _state.joinTableIds = ws.joinTableIds.slice();
            if (ws.metric && typeof ws.metric === 'object') _state.metric = ws.metric;
            // F14: multi-metric restore (saved-report path).
            if (Array.isArray(ws.metrics) && ws.metrics.length) {
                _state.selectedMetrics = new Set();
                _state._metricsIndex = _state._metricsIndex || {};
                ws.metrics.forEach(m => {
                    if (!m || !m.metric_key) return;
                    _state.selectedMetrics.add(m.metric_key);
                    // Saved metric'i LLM kaynaklı sayılır — restore sonrası
                    // chip header _metricsIndex'ten source==='llm' filtresi kullanır.
                    if (!m.source) m.source = 'llm';
                    _state._metricsIndex[m.metric_key] = m;
                });
            } else if (ws.metric && ws.metric.metric_key) {
                _state.selectedMetrics = new Set([ws.metric.metric_key]);
                _state._metricsIndex = _state._metricsIndex || {};
                if (!ws.metric.source) ws.metric.source = 'llm';
                _state._metricsIndex[ws.metric.metric_key] = ws.metric;
            }
            if (Array.isArray(ws.filters)) _state.filters = ws.filters.slice();
            if (typeof ws.userNote === 'string') _state.userNote = ws.userNote;
            if (data.last_sql) _state.lastGeneratedSql = data.last_sql;

            // Bulgular3 / Bulgu 1: Step 4 jump'ından ÖNCE oturum + kolon kataloğu
            // hazırla — aksi halde _onStepEnter(4) → _loadPreview "Önceki adımları
            // tamamlayın" early-exit'i veriyor, _buildStarterAst kataloğsuz çalışıp
            // AST editor mount fail → console.warn zinciri (DbSmartAstEditor not
            // loaded / mount failed).
            try {
                if (!_state.sessionUid) await _ensureSession();
                if (_state.selectedTableId != null && _state.sourceId != null) {
                    await _loadColumns();
                }
            } catch (preErr) {
                console.warn('[db_smart_wizard] saved-report pre-fetch failed:', preErr);
            }
            // Catalog dolu olduktan SONRA reportColumns restore et — bu sayede
            // eski format (ws.selected_columns) `_restoreReportColumns` cross-ref
            // ile semantic_type/table_name/table_id alanlarını geri kazanır.
            const restoredCols = _restoreReportColumns(ws);
            if (restoredCols) _state.reportColumns = restoredCols;
            // Metric library lazy-load — _metricsIndex'i saved metric'lerle
            // birleştirir (mevcut entryler korunur; backend response'u shadow merge).
            try { _loadMetrics(); } catch (_) { /* defansif, idempotent */ }

            // F10b Fix 2: restore path step 0 → step 4 jump → forward-skip guard
            // tarafından reddediliyordu (silent no-op). force:true ile bypass.
            _setStep(4, { force: true });
            _notify('Rapor yüklendi: ' + (data.name || ('#' + reportId)), 'success');
        } catch (e) {
            console.warn('[db_smart_wizard] _loadSavedReport failed:', e);
            _notify('Rapor yüklenemedi: ' + (e && e.message ? e.message : 'bilinmeyen hata'), 'error');
        }
    }

    async function _confirmDeleteSavedReport(reportId, cardEl) {
        // v3.37.0 B3 (HEBE-FE 2026-05-25): onay sonrası tüm gridi yeniden yükle —
        // tek kart DOM remove + inline empty state yerine `_loadSavedReportsList()`
        // çağrısı ile pagination/state senkron kalır.
        if (!window.confirm('Bu rapor silinsin mi? Bu işlem geri alınamaz.')) return;
        try {
            await _fetchJson(API_BASE + '/saved-reports/' + encodeURIComponent(reportId), { method: 'DELETE' });
            _notify('Rapor silindi', 'success');
            // Grid refresh — backend canlı veriyi tekrar listeler.
            await loadSavedReports();
        } catch (e) {
            console.warn('[db_smart_wizard] delete failed:', e);
            _notify('Rapor silinemedi: ' + (e && e.message ? e.message : 'bilinmeyen hata'), 'error');
        }
    }

    // v3.37.0 B3: dış aliyas — brief signature `loadSavedReports()` ile uyumlu;
    // mevcut `_loadSavedReportsList()` private helper'ı sarar.
    async function loadSavedReports() {
        return _loadSavedReportsList();
    }

    // ----- Save modal -----

    // v3.37.3 (bulgular-2 / Bulgu 5, 7a, 8): "Raporu Kaydet" butonuna tıklanınca
    //   - edit-mode (editingReportId varsa): pop-up açma, doğrudan PATCH ile
    //     üzerine kaydet ve tüm modalları kapatıp ana ekrana dön.
    //   - yeni kayıt: pop-up'ı aç → kullanıcı isim/açıklama girer → kaydet.
    function _openSaveModal() {
        if (_state.selectedTableId == null || _state.sourceId == null) {
            _notify('Önce kaynak ve tablo seçimini tamamlayın.', 'warning');
            return;
        }
        if (_state.editingReportId != null) {
            // Edit modunda doğrudan üzerine kaydet; pop-up'a gerek yok.
            _overwriteCurrentReport();
            return;
        }
        const modal = document.getElementById('dswSaveReportModal');
        if (!modal) return;
        // v3.37.2 FIX (HEBE+ATHENA): Save modal'i body'ye taşı.
        // dswSaveReportModal varsayılan olarak #dbSmartWizardPanel içinde nested;
        // openAsModal wizard'ı .dsw-modal-dialog içine taşıdığında save modal
        // yeni stacking context altında kalıyor → z-index:11100 result modal
        // overlay'inin (11000) ÜSTÜNE çıkamıyor. Body'ye taşıyarak global
        // stacking context'e koy.
        if (modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
        const nameIn = document.getElementById('dswSaveReportName');
        const descIn = document.getElementById('dswSaveReportDesc');
        const err = document.getElementById('dswSaveReportError');
        if (nameIn) { nameIn.value = ''; nameIn._userTouched = false; }
        if (descIn) { descIn.value = ''; descIn._userTouched = false; }
        if (err) { err.hidden = true; err.textContent = ''; }
        modal.classList.remove('hidden');
        modal.removeAttribute('hidden');
        setTimeout(function () { if (nameIn) nameIn.focus(); }, 0);
        // Bulgular3 / Bulgu 8: arka planda LLM'den baslik+aciklama oner.
        // Kullanici inputlara dokunduysa override etme — sadece bos kalanlari doldur.
        // Review fix #9: bekleyen LLM cagrisi varsa iptal et (modal her acilista yeni).
        if (_state._saveMetaAbort) {
            try { _state._saveMetaAbort.abort(); } catch (_) { /* ignore */ }
        }
        _state._saveMetaAbort = new AbortController();
        _suggestReportMetaIntoModal(nameIn, descIn, _state._saveMetaAbort.signal);
    }

    // Bulgular3 / Bulgu 8: save-modal acildiginda LLM ile baslik+aciklama oner.
    // Kullanici islerine dokunmayalim: input value bos VE _userTouched bayragi
    // yoksa value'yu LLM yanitiyla doldur. Tekrar oner butonu da var.
    async function _suggestReportMetaIntoModal(nameIn, descIn, abortSignal) {
        const hintEl = document.getElementById('dswSaveReportLlmHint');
        const setHint = function (txt, cls) {
            if (!hintEl) return;
            hintEl.textContent = txt || '';
            hintEl.className = 'dsw-save-llm-hint' + (cls ? ' ' + cls : '');
            hintEl.hidden = !txt;
        };
        // Kullanici input'a dokununca override koruma bayragi.
        // Review fix: her _openSaveModal'da _userTouched sifirlanir (yukarida);
        // listener once:true ile bir kez fire eder ve self-remove olur — flag
        // mantigi gerekmez. Sonraki modal acilisinda yeniden bind ederiz.
        const markTouched = function (el) {
            if (!el) return;
            el.addEventListener('input', function () { el._userTouched = true; }, { once: true });
        };
        markTouched(nameIn);
        markTouched(descIn);

        if (!_state.sourceId || !_state.selectedTableId) {
            setHint('', '');
            return;
        }
        // Payload: tablo + secili metrikler + raporda gorunen kolonlar + user_intent
        // Review fix #4: backend Pydantic max_length=20/50 — slice ile guvende kal.
        const idx = _state._metricsIndex || {};
        const metric_names = [];
        if (_state.selectedMetrics && _state.selectedMetrics.forEach) {
            _state.selectedMetrics.forEach(function (k) {
                const m = idx[k];
                if (m) {
                    const nm = (m.name_tr || m.metric_name || m.label || k || '').trim();
                    if (nm) metric_names.push(nm);
                }
            });
        }
        const columns = (Array.isArray(_state.reportColumns) ? _state.reportColumns : [])
            .map(function (c) { return c.label || c.column_name || ''; })
            .filter(function (n) { return !!n; });
        const metricNamesCapped = metric_names.slice(0, 20);
        const columnsCapped = columns.slice(0, 50);
        const payload = {
            table_label: _state.selectedTableLabel || null,
            metric_names: metricNamesCapped,
            columns: columnsCapped,
            filters_count: Array.isArray(_state.filters) ? _state.filters.length : 0,
            user_intent: _state.user_intent || _state.userNote || '',
        };
        setHint('✨ AI baslik/aciklama oneriyor...', 'is-loading');
        try {
            const data = await _fetchJson(API_BASE + '/llm/report-meta-suggest', {
                method: 'POST',
                body: JSON.stringify(payload),
                signal: abortSignal,
            });
            const suggestedTitle = (data && data.title) ? String(data.title) : '';
            const suggestedDesc = (data && data.description) ? String(data.description) : '';
            if (nameIn && !nameIn._userTouched && !nameIn.value) {
                nameIn.value = suggestedTitle;
            }
            if (descIn && !descIn._userTouched && !descIn.value) {
                descIn.value = suggestedDesc;
            }
            const cached = data && data.cache_hit ? ' (önbellek)' : '';
            setHint('✨ AI önerdi — istediğin gibi düzenleyebilirsin' + cached, 'is-ok');
        } catch (e) {
            // Review fix #9: iptal edildiyse sessizce gec (kullanici modal'i kapatti/yeniden acti)
            if (e && (e.name === 'AbortError' || (abortSignal && abortSignal.aborted))) {
                return;
            }
            console.warn('[db_smart_wizard] report-meta-suggest failed:', e);
            // Review fix #7: backend HTTPException.detail'i ekrana yansit.
            const detail = (e && (e.detail || e.message)) ? String(e.detail || e.message).slice(0, 160) : '';
            const tail = detail ? (' — ' + detail) : ' — başlığı ve açıklamayı manuel girin';
            setHint('AI öneri alınamadı' + tail, 'is-error');
        }
    }

    function _closeSaveModal() {
        const modal = document.getElementById('dswSaveReportModal');
        if (!modal) return;
        // Review fix #9: bekleyen LLM meta-suggest cagrisi varsa iptal et.
        if (_state._saveMetaAbort) {
            try { _state._saveMetaAbort.abort(); } catch (_) { /* ignore */ }
            _state._saveMetaAbort = null;
        }
        modal.classList.add('hidden');
        modal.setAttribute('hidden', '');
    }

    // v3.37.3 (bulgular-2 / Bulgu 8): Kayıt sonrası tüm wizard modallarını
    // kapat ve ana ekrana (Akıllı Keşif) dön. Saved Reports Grid'i de tazele.
    function _afterSaveCleanup(reportId, name) {
        _closeSaveModal();
        // Sonuç modal'ı (Rapor Sonucu / Çalıştır popup) açıksa kapat.
        try {
            if (typeof _closeResultModal === 'function') _closeResultModal();
        } catch (e) { /* defansif */ }
        // PR-5/R5: refresh hedefini DOM'da hangi listenin görünür olduğuna göre
        // seç — modal-mode'da wizard kapanırken ana ekran grid'i tazelenir,
        // inline-mode'da yalnız wizard içi liste tazelenir. Eskiden ikisi de
        // her zaman çağrılıyordu (gereksiz extra fetch).
        if (_modalState.open) {
            // Modal-mode: _notifySaved → closeModal → opts.onSave callback
            // (home.html'de SavedReportsGrid.refresh çağırıyor).
            try { _notifySaved(reportId, name); } catch (e) { /* ignore */ }
        } else {
            // Inline mode: önce wizard içi liste tazele (kullanıcı wizard'da
            // kalmadan kapatılır ama liste DOM'da mount edilmiş olabilir),
            // sonra panel'i kapat, ardından (varsa) ana ekran grid'ini tazele.
            try { _loadSavedReportsList(); } catch (e) { /* defansif */ }
            try { _closeWizard(); } catch (e) { /* ignore */ }
            try {
                if (window.SavedReportsGrid &&
                    typeof window.SavedReportsGrid.refresh === 'function') {
                    window.SavedReportsGrid.refresh();
                }
            } catch (e) { /* ignore */ }
        }
        // Edit-mode bayrağı sıfırla — sonraki wizard temiz başlasın.
        _state.editingReportId = null;
    }

    // v3.37.3 (bulgular-2 / Bulgu 7a): Edit-mode "üzerine kaydet" — PATCH ile
    // yalnız wizard_state + generated_sql güncellenir. İsim/açıklama korunur.
    async function _overwriteCurrentReport() {
        const id = _state.editingReportId;
        if (id == null) return;
        const wizard_state = _buildWizardState();
        const patch = {
            wizard_state: wizard_state,
            generated_sql: _state.lastGeneratedSql || null,
        };
        try {
            await _fetchJson(API_BASE + '/saved-reports/' + encodeURIComponent(id), {
                method: 'PATCH',
                body: JSON.stringify(patch),
            });
            _notify(_t('wizard.toast.report_updated'), 'success');
            _afterSaveCleanup(id, null);
        } catch (e) {
            console.warn('[db_smart_wizard] overwrite failed:', e);
            _notify('Güncellenemedi: ' + (e && e.message ? e.message : 'bilinmeyen hata'), 'error');
        }
    }

    // v3.37.3 (bulgular-2 / Bulgu 7b): Aynı isimde rapor varsa kullanıcıya sor.
    // Backend ?name_exact=X case-insensitive tam eşleşme döner (PR-5/R1) —
    // 200-rapor listesi yerine doğrudan filtreli sorgu.
    async function _findReportByName(name) {
        const needle = (name || '').trim();
        if (!needle) return null;
        try {
            const url = API_BASE + '/saved-reports?limit=1&offset=0&name_exact=' +
                        encodeURIComponent(needle);
            const data = await _fetchJson(url);
            const items = (data && Array.isArray(data.items)) ? data.items : [];
            return items.length ? items[0] : null;
        } catch (e) {
            console.warn('[db_smart_wizard] _findReportByName failed:', e);
            return null;
        }
    }

    async function _saveCurrentReport() {
        const nameIn = document.getElementById('dswSaveReportName');
        const descIn = document.getElementById('dswSaveReportDesc');
        const errEl = document.getElementById('dswSaveReportError');
        const confirmBtn = document.getElementById('dswSaveReportConfirm');
        const name = nameIn ? (nameIn.value || '').trim() : '';
        const description = descIn ? (descIn.value || '').trim() : '';
        if (!name) {
            if (errEl) { errEl.textContent = 'Rapor adı zorunlu.'; errEl.hidden = false; }
            if (nameIn) nameIn.focus();
            return;
        }
        const wizard_state = _buildWizardState();
        // F10 brief: source_id, generated_sql, metric_key, schema_version
        const body = {
            name: name,
            description: description || null,
            source_id: _state.sourceId,
            wizard_state: wizard_state,
            generated_sql: _state.lastGeneratedSql || null,
            metric_key: (_state.metric && _state.metric.metric_key) || null,
            schema_version: 'v3.36',
        };
        if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = 'Kaydediliyor…'; }
        try {
            // v3.37.3 (bulgular-2 / Bulgu 7b): duplicate-name kontrol.
            const dup = await _findReportByName(name);
            if (dup) {
                const ok = window.confirm(_t('wizard.confirm.duplicate_name', { name: dup.name }));
                if (!ok) {
                    if (errEl) {
                        errEl.textContent = _t('wizard.error.duplicate_name_field');
                        errEl.hidden = false;
                    }
                    if (nameIn) nameIn.focus();
                    return;
                }
                // Üzerine yaz: mevcut id ile PATCH.
                await _fetchJson(API_BASE + '/saved-reports/' + encodeURIComponent(dup.id), {
                    method: 'PATCH',
                    body: JSON.stringify({
                        name: name,
                        description: description || null,
                        wizard_state: wizard_state,
                        generated_sql: body.generated_sql,
                    }),
                });
                _notify(_t('wizard.toast.report_updated') + ': ' + name, 'success');
                _afterSaveCleanup(dup.id, name);
                return;
            }
            // Backend route'u (FAZ 3 P13 G3.3) /sessions/{uid}/save-report — session-bound.
            let res;
            if (_state.sessionUid) {
                // F10b Fix 3 (POSEIDON+ATHENA): session-bound path artık client
                // wizard_state'i de gönderiyor — backend body.wizard_state
                // önceliklidir (ctx.get fallback). Session context auto-sync
                // edilmiyorsa stale/empty kayıt riskini kapatır.
                res = await _fetchJson(
                    API_BASE + '/sessions/' + encodeURIComponent(_state.sessionUid) + '/save-report',
                    {
                        method: 'POST',
                        body: JSON.stringify({
                            name: name,
                            description: description || null,
                            tags: null,
                            wizard_state: wizard_state,
                            generated_sql: body.generated_sql,
                            metric_key: body.metric_key,
                            schema_version: body.schema_version,
                        }),
                    }
                );
            } else {
                // F10b Fix 1 (POSEIDON+ARES): flat /saved-reports artık backend'de
                // mevcut (post_save_report_flat) — modal-mode session drop fallback.
                res = await _fetchJson(API_BASE + '/saved-reports', {
                    method: 'POST',
                    body: JSON.stringify(body),
                });
            }
            _notify(_t('wizard.toast.report_saved'), 'success');
            _afterSaveCleanup(res && (res.report_id || res.id), name);
        } catch (e) {
            console.warn('[db_smart_wizard] save report failed:', e);
            const msg = (e && e.message) ? e.message : 'bilinmeyen hata';
            if (errEl) { errEl.textContent = 'Kaydedilemedi: ' + msg; errEl.hidden = false; }
        } finally {
            if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = 'Kaydet'; }
        }
    }

    function _bindSavedReportsUi() {
        // Save Report buton (step 4)
        const saveBtn = document.getElementById('dswSaveReportBtn');
        if (saveBtn && !saveBtn._bound) {
            saveBtn.addEventListener('click', _openSaveModal);
            saveBtn._bound = true;
        }
        // Modal aksiyonları
        const modal = document.getElementById('dswSaveReportModal');
        if (modal && !modal._bound) {
            modal.addEventListener('click', function (e) {
                const t = e.target;
                if (!t) return;
                if (t.getAttribute && t.getAttribute('data-action') === 'cancel') {
                    _closeSaveModal();
                } else if (t.getAttribute && t.getAttribute('data-role') === 'overlay') {
                    _closeSaveModal();
                }
            });
            modal.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') { e.stopPropagation(); _closeSaveModal(); }
            });
            const confirmBtn = document.getElementById('dswSaveReportConfirm');
            if (confirmBtn) confirmBtn.addEventListener('click', _saveCurrentReport);
            modal._bound = true;
        }
    }

    // =========================================================
    // v3.36.0 F11 (DIONYSOS+HEBE+HERMES) — Grafik popup hook
    // ---------------------------------------------------------
    // F9 sonuç popup'undaki "📊 Grafik" butonu bunu çağırır:
    //   DbSmartWizardModule.openChart(state.lastReportResult)
    // veya butona `data-dsw-chart-trigger="1"` ekle — delegation
    // listener tıklamayı yakalar. Defensive: data hazır değilse
    // uyarı toast, sessiz fail.
    // =========================================================
    let _lastReportResult = null;  // { columns, rows } veya null

    function setLastReportResult(result) {
        if (result && Array.isArray(result.columns) && Array.isArray(result.rows)) {
            _lastReportResult = {
                columns: result.columns,
                rows: result.rows,
                suggestedType: result.suggestedType || null,
            };
        } else {
            _lastReportResult = null;
        }
    }

    function openChart(payload) {
        const data = payload || _lastReportResult;
        if (!data || !Array.isArray(data.columns) || !Array.isArray(data.rows)) {
            _notify('Grafik için sonuç bulunamadı. Önce raporu çalıştırın.', 'warning');
            return false;
        }
        if (!window.DbSmartChart || typeof window.DbSmartChart.open !== 'function') {
            _notify('Grafik modülü yüklenemedi.', 'error');
            console.warn('[db_smart_wizard] DbSmartChart not loaded');
            return false;
        }
        try {
            window.DbSmartChart.open({
                columns: data.columns,
                rows: data.rows,
                suggestedType: data.suggestedType || null,
            });
            return true;
        } catch (e) {
            console.warn('[db_smart_wizard] chart open fail:', e);
            _notify('Grafik açılamadı: ' + e.message, 'error');
            return false;
        }
    }

    // Delegation: F9 sonuç modal'ı sonradan render edilse de
    // `[data-dsw-chart-trigger]` butonlarını otomatik yakala.
    document.addEventListener('click', function (e) {
        const t = e.target && e.target.closest && e.target.closest('[data-dsw-chart-trigger]');
        if (!t) return;
        e.preventDefault();
        openChart();
    });

    // ====================================================================
    // v3.37.0 (HEBE-FE 2026-05-25) — Smart Discovery Wizard UX bundle
    // --------------------------------------------------------------------
    //   B2  — SQL pretty-print (anahtar kelime newline + 2-space indent)
    //   B6  — "Bu rapordan ne bekliyorsunuz?" sticky footer (user_intent)
    //   B7a — "▶️ Çalıştır" butonu footer'ın sağ tarafında
    //   B7b — ORDER BY editable chip listesi (ASC/DESC toggle + remove + DnD)
    //   B4  — "✨ Metrik Öner" LLM butonu  (POST /api/db-smart/llm/metric-suggest)
    //   B5b — "✨ Kolon Öner"  LLM butonu  (POST /api/db-smart/llm/column-suggest)
    //   B8  — "✨ Hazır Format Öner" butonu (POST /api/db-smart/llm/format-suggest)
    // ====================================================================

    // ── B2: SQL pretty-print ────────────────────────────────────────────
    // Bulgular3 / Bulgu 2: yeniden yazıldı. String literal'lerini koruyan,
    // paren-depth tracking ile alt-sorgu/CTE içindeki anahtar kelimeleri
    // bozmayan, AND/OR/ON için ek indent veren manuel formatter.
    function _prettyPrintSql(sql) {
        if (sql == null) return '';
        let s = String(sql).trim();
        if (!s) return '';

        // 1) String literal'leri ('...' / "...") placeholder ile koru —
        //    içlerindeki anahtar kelime/virgül yanlış parse edilmesin.
        const strs = [];
        s = s.replace(/'(?:[^']|'')*'|"(?:[^"]|"")*"/g, function (m) {
            strs.push(m);
            return 'STR' + (strs.length - 1) + '';
        });

        // 2) Whitespace normalize.
        s = s.replace(/\s+/g, ' ').trim();

        // 3) Top-level (paren depth=0) anahtar kelimeleri ve virgülleri parçala.
        //    Uzun kelimeler önce gelir ("LEFT JOIN" > "JOIN", "UNION ALL" > "UNION").
        const KW_LIST = [
            'WITH', 'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'HAVING', 'ORDER BY',
            'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'FULL OUTER JOIN',
            'FULL JOIN', 'CROSS JOIN', 'OUTER JOIN', 'JOIN',
            'UNION ALL', 'UNION', 'INTERSECT', 'EXCEPT',
            'LIMIT', 'OFFSET', 'ON', 'AND', 'OR',
        ];
        // Boşluklu kelimeler için tek+çoğul whitespace toleransı.
        const kwPattern = KW_LIST.map(function (k) {
            return k.replace(/ /g, '\\s+');
        }).join('|');
        const kwRe = new RegExp('^(?:' + kwPattern + ')\\b', 'i');

        const parts = [];
        let depth = 0;
        let buf = '';
        for (let i = 0; i < s.length; i++) {
            const ch = s[i];
            if (ch === '(') { depth++; buf += ch; continue; }
            if (ch === ')') { depth = Math.max(0, depth - 1); buf += ch; continue; }
            if (depth === 0) {
                // Anahtar kelime başlangıcı mı?
                const rest = s.slice(i);
                const m = rest.match(kwRe);
                if (m) {
                    if (buf.trim()) parts.push(buf.trim());
                    parts.push('KW' + m[0].toUpperCase().replace(/\s+/g, ' '));
                    buf = '';
                    i += m[0].length - 1;
                    continue;
                }
                if (ch === ',') {
                    parts.push((buf + ',').trim());
                    buf = '';
                    continue;
                }
            }
            buf += ch;
        }
        if (buf.trim()) parts.push(buf.trim());

        // 4) Indent stratejisi:
        //    - Top-level keyword: ayrı satır (SELECT/FROM/WHERE/WITH/...)
        //    - SELECT listesi devamı (virgüllü parça): 2-indent
        //    - AND/OR: 2-indent (WHERE devamı)
        //    - ON: 4-indent (JOIN devamı)
        //    - FROM/WHERE/HAVING/LIMIT/OFFSET/JOIN: kelime + içerik tek satır
        //    - SELECT/WITH/GROUP BY/ORDER BY: kelime tek satır, içerik alt-indentli
        const lines = [];
        let pendingKw = null;     // Sonraki içeriğin başına eklenecek (FROM/WHERE/JOIN/AND/OR/ON)
        let curBlock = null;      // Multi-line block tracker (SELECT/GROUP BY/ORDER BY/WITH)
        const MULTI_LINE_KW = { SELECT: 1, 'GROUP BY': 1, 'ORDER BY': 1, WITH: 1 };

        parts.forEach(function (p) {
            if (p.startsWith('KW')) {
                const kw = p.slice(2);
                if (kw === 'AND' || kw === 'OR') {
                    pendingKw = '  ' + kw;
                    curBlock = null;
                    return;
                }
                if (kw === 'ON') {
                    pendingKw = '    ' + kw;
                    curBlock = null;
                    return;
                }
                if (MULTI_LINE_KW[kw]) {
                    lines.push(kw);
                    curBlock = kw;
                    pendingKw = null;
                    return;
                }
                // Inline kw (FROM/WHERE/HAVING/JOIN turleri/LIMIT/OFFSET/UNION/...)
                pendingKw = kw;
                curBlock = null;
                return;
            }
            // İçerik parçası
            if (pendingKw) {
                lines.push(pendingKw + ' ' + p);
                pendingKw = null;
            } else if (curBlock) {
                // SELECT/ORDER BY/GROUP BY/WITH listesinde devam parçası → 2-indent
                lines.push('  ' + p);
            } else if (lines.length) {
                // Hiç keyword yoksa son satıra ekle (defansif fallback)
                lines[lines.length - 1] += ' ' + p;
            } else {
                lines.push(p);
            }
        });
        // Trailing lone keyword (içerik gelmediyse)
        if (pendingKw) lines.push(pendingKw);

        // 5) Placeholder'ları geri koy.
        return lines.join('\n').replace(/STR(\d+)/g, function (_, idx) {
            return strs[parseInt(idx, 10)] || '';
        });
    }

    // ── B7b: ORDER BY editable chips ───────────────────────────────────
    // _state.order_by: [{ column_name, direction: 'ASC'|'DESC' }]
    if (!Array.isArray(_state.order_by)) _state.order_by = [];

    function _renderOrderByChips() {
        const panel = document.getElementById('dswStep4');
        if (!panel) return;
        let host = panel.querySelector('[data-dsw-orderby]');
        if (!host) {
            host = document.createElement('div');
            host.setAttribute('data-dsw-orderby', '1');
            host.className = 'dsw-orderby-bar';
            // Pre öncesine (mümkünse) yerleştir.
            const legacy = document.getElementById('dswLegacyPreview');
            if (legacy && legacy.parentNode === panel) {
                panel.insertBefore(host, legacy);
            } else {
                panel.appendChild(host);
            }
        }
        const items = Array.isArray(_state.order_by) ? _state.order_by : [];
        // Sol etiket + chip listesi + "+ ORDER BY ekle" buton.
        const cols = Array.isArray(_state.reportColumns) ? _state.reportColumns : [];
        const colOptions = cols.map(function (c) {
            return '<option value="' + _escape(c.column_name) + '">' +
                _escape(c.label || c.column_name) + '</option>';
        }).join('');
        let chipsHtml = '<span class="dsw-orderby-label">Sıralama:</span>';
        if (!items.length) {
            chipsHtml += '<span class="dsw-orderby-empty">Henüz sıralama yok.</span>';
        } else {
            chipsHtml += items.map(function (it, idx) {
                const col = it.column_name || '';
                const dir = (it.direction === 'DESC') ? 'DESC' : 'ASC';
                const arrow = (dir === 'ASC') ? '▲' : '▼';
                return '<span class="order-chip" draggable="true" data-order-idx="' + idx + '">' +
                    '<span class="order-chip-col">' + _escape(col) + '</span>' +
                    '<button type="button" class="order-chip-toggle" data-order-toggle="' + idx + '" ' +
                      'aria-label="ASC/DESC değiştir">' + arrow + ' ' + dir + '</button>' +
                    '<button type="button" class="order-chip-remove" data-order-remove="' + idx + '" ' +
                      'aria-label="Sıralamadan çıkar">×</button>' +
                    '</span>';
            }).join('');
        }
        chipsHtml += '<span class="dsw-orderby-add-wrap">' +
            '<select class="dsw-orderby-add-select" data-order-add-select' +
            (cols.length ? '' : ' disabled') + '>' +
            '<option value="">+ Kolon seç</option>' + colOptions + '</select>' +
            '</span>';
        host.innerHTML = chipsHtml;
        _bindOrderByEvents(host);
    }

    function _bindOrderByEvents(host) {
        host.querySelectorAll('[data-order-toggle]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const idx = parseInt(btn.getAttribute('data-order-toggle'), 10);
                if (isNaN(idx)) return;
                const it = _state.order_by[idx];
                if (!it) return;
                it.direction = (it.direction === 'ASC') ? 'DESC' : 'ASC';
                _renderOrderByChips();
            });
        });
        host.querySelectorAll('[data-order-remove]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const idx = parseInt(btn.getAttribute('data-order-remove'), 10);
                if (isNaN(idx)) return;
                _state.order_by.splice(idx, 1);
                _renderOrderByChips();
            });
        });
        const addSel = host.querySelector('[data-order-add-select]');
        if (addSel) {
            addSel.addEventListener('change', function () {
                const v = addSel.value;
                if (!v) return;
                const exists = _state.order_by.some(function (it) { return it.column_name === v; });
                if (!exists) {
                    _state.order_by.push({ column_name: v, direction: 'ASC' });
                }
                addSel.value = '';
                _renderOrderByChips();
            });
        }
        // HTML5 native drag-reorder
        let dragIdx = -1;
        host.querySelectorAll('[data-order-idx]').forEach(function (chip) {
            chip.addEventListener('dragstart', function (ev) {
                dragIdx = parseInt(chip.getAttribute('data-order-idx'), 10);
                if (ev.dataTransfer) {
                    ev.dataTransfer.effectAllowed = 'move';
                    try { ev.dataTransfer.setData('text/plain', String(dragIdx)); } catch (_) {}
                }
                chip.classList.add('dragging');
            });
            chip.addEventListener('dragend', function () { chip.classList.remove('dragging'); });
            chip.addEventListener('dragover', function (ev) { ev.preventDefault(); });
            chip.addEventListener('drop', function (ev) {
                ev.preventDefault();
                const target = parseInt(chip.getAttribute('data-order-idx'), 10);
                let src = dragIdx;
                if ((src < 0 || isNaN(src)) && ev.dataTransfer) {
                    try { src = parseInt(ev.dataTransfer.getData('text/plain'), 10); } catch (_) {}
                }
                if (isNaN(src) || src < 0 || src === target) return;
                const arr = _state.order_by.slice();
                const [moved] = arr.splice(src, 1);
                arr.splice(target, 0, moved);
                _state.order_by = arr;
                _renderOrderByChips();
            });
        });
    }

    // ── B6 + B7a: Sticky footer (user_intent + Çalıştır + LLM Format Öner) ─
    // user_intent state alanı (varsayılan boş)
    if (typeof _state.user_intent !== 'string') _state.user_intent = '';

    function _ensureRunFooter(panel) {
        if (!panel) return;
        let footer = panel.querySelector('.wizard-sticky-footer');
        if (footer) {
            // user_intent textarea değerini state ile senkron tut
            const ta = footer.querySelector('#user-intent');
            if (ta && ta.value !== (_state.user_intent || '')) {
                ta.value = _state.user_intent || '';
            }
            return;
        }
        footer = document.createElement('div');
        footer.className = 'wizard-sticky-footer';
        // Bulgular3 / Bulgu 6: Çalıştır butonu sticky footer içine alındı —
        // Format Öner ile yan yana, user_intent textarea ile aynı satırda.
        // ID=dswRunBtn legacy (_runGeneratedReport label override) korunur.
        footer.innerHTML =
            '<textarea id="user-intent" placeholder="Bu rapordan ne bekliyorsunuz?" maxlength="500" ' +
              'aria-label="Bu rapordan ne bekliyorsunuz?"></textarea>' +
            '<div class="wizard-sticky-footer-actions">' +
              '<button type="button" id="dswFormatSuggestBtn" class="dsw-llm-btn dsw-llm-btn-format" ' +
                'aria-label="Hazır format öner">✨ Hazır Format Öner</button>' +
              '<span id="dswFormatCacheHint" class="dsw-cache-hint" hidden></span>' +
              '<button type="button" id="dswRunBtn" class="dsw-run-btn" ' +
                'aria-label="Raporu çalıştır">▶️ Çalıştır</button>' +
            '</div>' +
            '<div id="dswFormatSuggestPanel" class="dsw-format-suggest-panel" hidden ' +
              'role="region" aria-label="LLM format önerileri"></div>';
        panel.appendChild(footer);

        const ta = footer.querySelector('#user-intent');
        if (ta) {
            ta.value = _state.user_intent || '';
            ta.addEventListener('input', function () {
                _state.user_intent = ta.value || '';
                // Geriye uyum: mevcut backend `user_note`/`userNote` kullanıyor.
                _state.userNote = ta.value || '';
            });
        }
        const fmtBtn = footer.querySelector('#dswFormatSuggestBtn');
        if (fmtBtn) {
            fmtBtn.addEventListener('click', _onFormatSuggestClick);
        }
        const runBtn = footer.querySelector('#dswRunBtn');
        if (runBtn) {
            runBtn.addEventListener('click', _runGeneratedReport);
        }
    }

    // ── B4/B5b/B8 — LLM endpoint wrappers ──────────────────────────────
    // Ortak yardımcılar: spinner state, cache hint, error toast + re-enable.
    function _llmSetBusy(btn, busy, busyLabel) {
        if (!btn) return;
        if (busy) {
            if (!btn.dataset._origLabel) btn.dataset._origLabel = btn.textContent;
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
            btn.textContent = busyLabel || '⏳ Düşünüyor…';
        } else {
            btn.disabled = false;
            btn.removeAttribute('aria-busy');
            if (btn.dataset._origLabel) {
                btn.textContent = btn.dataset._origLabel;
                delete btn.dataset._origLabel;
            }
        }
    }

    function _showCacheHint(hintEl, cacheHit) {
        if (!hintEl) return;
        if (cacheHit) {
            hintEl.textContent = '(önbellek)';
            hintEl.hidden = false;
        } else {
            hintEl.textContent = '';
            hintEl.hidden = true;
        }
    }

    function _llmError(prefix, e, btn) {
        const msg = (e && e.message) ? e.message : 'bilinmeyen hata';
        _notify(prefix + ': ' + msg, 'error');
        _llmSetBusy(btn, false);
    }

    // ── B4: Metrik Öner ────────────────────────────────────────────────
    async function _onMetricSuggestClick() {
        const btn = document.getElementById('dswMetricSuggestBtn');
        const hint = document.getElementById('dswMetricCacheHint');
        if (!_state.sourceId || !_state.selectedTableId) {
            _notify('Önce kaynak ve tablo seçin', 'warning');
            return;
        }
        const tableName = _state.selectedTableObjectName ||
            (_state.selectedTableLabel || '').split('.').pop() || null;
        // v3.37.2 (ARES+METIS): backend ColumnInfo {name, type} bekliyor.
        // _columnCatalog henüz yüklenmediyse pre-fetch et.
        let columns = (_state._columnCatalog || []).map(function (c) {
            return { name: c.name, type: c.data_type || c.semantic_type || 'unknown' };
        }).filter(function (c) { return c.name && c.type; });
        if (!columns.length && _state.selectedTableId) {
            try {
                const colData = await _fetchJson(API_BASE + '/sources/' + _state.sourceId +
                    '/tables/' + _state.selectedTableId + '/columns');
                columns = ((colData && colData.columns) || []).map(function (c) {
                    return { name: c.name, type: c.data_type || c.semantic_type || 'unknown' };
                }).filter(function (c) { return c.name && c.type; });
            } catch (e) {
                console.warn('[db_smart_wizard] column pre-fetch failed:', e);
            }
        }
        if (!columns.length) {
            _notify('Kolonlar yüklenemedi — tabloyu yeniden seçin', 'warning');
            return;
        }
        const payload = {
            source_id: _state.sourceId,
            table: tableName,
            // Bulgular3 / Bulgu 4: TR ad propagate (table_label)
            table_label: _state.selectedTableLabel || null,
            columns: columns,
            user_intent: _state.user_intent || '',
        };
        _llmSetBusy(btn, true);
        try {
            const data = await _fetchJson(API_BASE + '/llm/metric-suggest', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            _showCacheHint(hint, !!(data && data.cache_hit));
            _renderMetricSuggestions(data);
        } catch (e) {
            console.warn('[db_smart_wizard] metric-suggest failed:', e);
            _llmError('AI önerisi alınamadı', e, btn);
            return;
        }
        _llmSetBusy(btn, false);
    }

    function _renderMetricSuggestions(data) {
        const host = document.getElementById('dswMetricSuggestPanel');
        if (!host) return;
        const items = (data && Array.isArray(data.suggestions)) ? data.suggestions : [];
        if (!items.length) {
            host.innerHTML = '<p class="dsw-hint">Öneri dönmedi.</p>';
            host.hidden = false;
            return;
        }
        // Bulgular3 / Bulgu 4: TR ad chip basligi, aciklama altinda "Tablo: <TR ad>"
        // satiri. Tooltip: SQL identifier'i farkliysa "Tablo (orijinal): X" + rationale.
        host.innerHTML = items.map(function (s) {
            const key = s.metric_key || s.key || '';
            const name = s.metric_name || s.name || key;
            const conf = (typeof s.confidence === 'number')
                ? Math.round(s.confidence * 100) + '%' : '';
            const rationale = s.rationale || '';
            const tableTr = s.table_name_tr || '';
            const tableSql = s.table_object_name || '';
            const tableLine = tableTr
                ? ('<span class="dsw-llm-chip-table">Tablo: ' + _escape(tableTr) + '</span>')
                : (tableSql
                    ? ('<span class="dsw-llm-chip-table">Tablo: ' + _escape(tableSql) + '</span>')
                    : '');
            const tooltipParts = [];
            if (rationale) tooltipParts.push(rationale);
            // SQL identifier farkli ise tooltip'te goster
            if (tableTr && tableSql && tableTr.toUpperCase() !== tableSql.toUpperCase()) {
                tooltipParts.push('Tablo (orijinal): ' + tableSql);
            }
            const titleAttr = tooltipParts.length
                ? ' title="' + _escape(tooltipParts.join('\n')) + '"' : '';
            return '<button type="button" class="dsw-llm-chip dsw-llm-chip-metric" ' +
                'data-metric-key="' + _escape(key) + '"' + titleAttr + '>' +
                '<span class="dsw-llm-chip-title">' + _escape(name) +
                (conf ? ' <span class="dsw-llm-conf">(' + conf + ')</span>' : '') +
                '</span>' +
                (tableLine ? '<br>' + tableLine : '') +
                '</button>';
        }).join('');
        host.hidden = false;
        host.querySelectorAll('[data-metric-key]').forEach(function (chip) {
            chip.addEventListener('click', function () {
                const mk = chip.getAttribute('data-metric-key');
                if (!mk) return;
                _state.selectedMetrics.add(mk);
                if (!_state._metricsIndex[mk]) {
                    _state._metricsIndex[mk] = { metric_key: mk };
                }
                _state.metric = _state._metricsIndex[mk];
                // Eğer step 2'deki ilgili checkbox varsa işaretle
                const cb = document.querySelector(
                    '.dsw-metric-checkbox[data-metric-key="' + mk.replace(/"/g, '\\"') + '"]');
                if (cb) { cb.checked = true; cb.dispatchEvent(new Event('change')); }
                _notify('Metrik eklendi: ' + mk, 'success');
            });
        });
    }

    // Step 2 paneline "✨ Metrik Öner" butonunu mount et (idempotent).
    function _ensureMetricSuggestButton() {
        const panel = document.getElementById('dswStep2');
        if (!panel) return;
        if (panel.querySelector('#dswMetricSuggestBtn')) return;
        const bar = document.createElement('div');
        bar.className = 'dsw-llm-bar dsw-llm-bar-metric';
        bar.innerHTML =
            '<button type="button" id="dswMetricSuggestBtn" class="dsw-llm-btn dsw-llm-btn-metric" ' +
              'aria-label="Metrik öner">✨ Metrik Öner</button>' +
            '<span id="dswMetricCacheHint" class="dsw-cache-hint" hidden></span>' +
            '<div id="dswMetricSuggestPanel" class="dsw-llm-suggest-panel" hidden ' +
              'role="region" aria-label="LLM metrik önerileri"></div>';
        panel.insertBefore(bar, panel.firstChild);
        const btn = bar.querySelector('#dswMetricSuggestBtn');
        // Disabled mantığı: tablo seçili değilse kapalı.
        btn.disabled = !_state.selectedTableId;
        btn.addEventListener('click', _onMetricSuggestClick);
    }

    // ── B5b: Kolon Öner ────────────────────────────────────────────────
    async function _onColumnSuggestClick() {
        const btn = document.getElementById('dswColumnSuggestBtn');
        const hint = document.getElementById('dswColumnCacheHint');
        if (!_state.sourceId || !_state.selectedTableId) {
            _notify('Önce kaynak ve tablo seçin', 'warning');
            return;
        }
        if (!_state.metric || !_state.metric.metric_key) {
            _notify('Önce bir metrik seçin', 'warning');
            return;
        }
        const tableName = _state.selectedTableObjectName ||
            (_state.selectedTableLabel || '').split('.').pop() || null;
        // v3.37.2 (ARES+METIS): backend ColumnSuggestRequest kontratı:
        // { source_id, table, metric:{metric_name, agg, formula, unit},
        //   available_columns:[{name, type}] }
        const m = _state.metric || {};
        const metric = {
            metric_name: m.name_tr || m.metric_name || m.metric_key || '',
            agg: m.agg || m.aggregation || null,
            formula: m.formula || null,
            unit: m.unit || null,
        };
        const availableColumns = (_state._columnCatalog || []).map(function (c) {
            return { name: c.name, type: c.data_type || c.semantic_type || 'unknown' };
        }).filter(function (c) { return c.name; });
        if (!availableColumns.length) {
            _notify('Kolon listesi boş — adımı yeniden yükleyin', 'warning');
            return;
        }
        const payload = {
            source_id: _state.sourceId,
            table: tableName,
            metric: metric,
            available_columns: availableColumns,
        };
        _llmSetBusy(btn, true);
        try {
            const data = await _fetchJson(API_BASE + '/llm/column-suggest', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            _showCacheHint(hint, !!(data && data.cache_hit));
            _renderColumnSuggestions(data);
        } catch (e) {
            console.warn('[db_smart_wizard] column-suggest failed:', e);
            _llmError('AI önerisi alınamadı', e, btn);
            return;
        }
        _llmSetBusy(btn, false);
    }

    function _renderColumnSuggestions(data) {
        const host = document.getElementById('dswColumnSuggestPanel');
        if (!host) return;
        // v3.37.1 D: backend SuggestedColumn → { column, rationale, ... }
        // ColumnSuggestResponse → { metric_bound, related_dimensions, ... }
        const metricCols = (data && Array.isArray(data.metric_bound)) ? data.metric_bound : [];
        const dimCols = (data && Array.isArray(data.related_dimensions)) ? data.related_dimensions : [];
        // Cache last suggestion for _addReportColumn validation (Madde 5)
        _state._lastColumnSuggestion = {
            metric_key: (_state.metric && _state.metric.metric_key) || null,
            metric_bound: metricCols.map(c => (c && (c.column || c.column_name || c.name)) || ''),
            related_dimensions: dimCols.map(c => (c && (c.column || c.column_name || c.name)) || ''),
        };
        if (!metricCols.length && !dimCols.length) {
            host.innerHTML = '<p class="dsw-hint">Öneri dönmedi.</p>';
            host.hidden = false;
            return;
        }
        function chipHtml(c) {
            const name = c.column || c.column_name || c.name || '';
            const label = c.label || name;
            const rationale = c.rationale || '';
            return '<button type="button" class="dsw-llm-chip" ' +
                'data-col-name="' + _escape(name) + '" ' +
                'title="' + _escape(rationale) + '">' + _escape(label) + '</button>';
        }
        // Bulgular3 / Bulgu 5: section basligi yaninda "+ Tumunu ekle" buton +
        // panel ust kosesinde "+ Hepsini ekle" (metric_bound + dimensions birlikte).
        const bulkAllBtn = (metricCols.length || dimCols.length)
            ? '<button type="button" class="dsw-llm-bulk-add" data-bulk-add="all" ' +
              'aria-label="Tum onerilen kolonlari rapora ekle" title="Tum onerileri ekle">' +
              '+ Hepsini rapora ekle</button>'
            : '';
        const bulkMetricBtn = metricCols.length
            ? '<button type="button" class="dsw-llm-bulk-add dsw-llm-bulk-add-small" data-bulk-add="metric-cols" ' +
              'aria-label="Tum metrige bagli kolonlari rapora ekle" title="Metrige bagli kolonlari topluca ekle">' +
              '+ Tumunu ekle</button>'
            : '';
        const bulkDimBtn = dimCols.length
            ? '<button type="button" class="dsw-llm-bulk-add dsw-llm-bulk-add-small" data-bulk-add="dimensions" ' +
              'aria-label="Tum ilgili boyutlari rapora ekle" title="Boyut kolonlarini topluca ekle">' +
              '+ Tumunu ekle</button>'
            : '';
        host.innerHTML =
            (bulkAllBtn ? '<div class="dsw-llm-bulk-bar">' + bulkAllBtn + '</div>' : '') +
            '<div class="dsw-llm-section" data-section="metric-cols">' +
              '<div class="dsw-llm-section-head">' +
                '<h6>Metriğe Bağlı Kolonlar</h6>' +
                bulkMetricBtn +
              '</div>' +
              '<div class="dsw-llm-chip-row">' +
                (metricCols.length ? metricCols.map(chipHtml).join('') :
                  '<span class="dsw-hint">Yok</span>') +
              '</div>' +
            '</div>' +
            '<div class="dsw-llm-section" data-section="dimensions">' +
              '<div class="dsw-llm-section-head">' +
                '<h6>İlgili Boyutlar</h6>' +
                bulkDimBtn +
              '</div>' +
              '<div class="dsw-llm-chip-row">' +
                (dimCols.length ? dimCols.map(chipHtml).join('') :
                  '<span class="dsw-hint">Yok</span>') +
              '</div>' +
            '</div>';
        host.hidden = false;
        // Chip click → reportColumns'a ekle
        host.querySelectorAll('[data-col-name]').forEach(function (chip) {
            chip.addEventListener('click', function () {
                const name = chip.getAttribute('data-col-name');
                if (!name) return;
                _addReportColumn(name, null);
                chip.classList.add('dsw-llm-chip-added');
            });
        });
        // Bulgular3 / Bulgu 5: bulk-add handler — secime gore section veya tumu.
        host.querySelectorAll('[data-bulk-add]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const scope = btn.getAttribute('data-bulk-add');
                let targets = [];
                if (scope === 'metric-cols') {
                    targets = Array.from(host.querySelectorAll('[data-section="metric-cols"] [data-col-name]'));
                } else if (scope === 'dimensions') {
                    targets = Array.from(host.querySelectorAll('[data-section="dimensions"] [data-col-name]'));
                } else { // all
                    targets = Array.from(host.querySelectorAll('[data-col-name]'));
                }
                let added = 0;
                targets.forEach(function (chip) {
                    if (chip.classList.contains('dsw-llm-chip-added')) return;
                    const name = chip.getAttribute('data-col-name');
                    if (!name) return;
                    const before = (_state.reportColumns || []).length;
                    _addReportColumn(name, null);
                    const after = (_state.reportColumns || []).length;
                    if (after > before) {
                        added += 1;
                        chip.classList.add('dsw-llm-chip-added');
                    }
                });
                if (added > 0) {
                    _notify(added + ' kolon rapora eklendi', 'success');
                } else {
                    _notify('Tum oneriler zaten rapora ekli', 'info');
                }
            });
        });
    }

    function _ensureColumnSuggestButton() {
        const panel = document.getElementById('dswStep3');
        if (!panel) return;
        if (panel.querySelector('#dswColumnSuggestBtn')) return;
        const bar = document.createElement('div');
        bar.className = 'dsw-llm-bar dsw-llm-bar-column';
        bar.innerHTML =
            '<button type="button" id="dswColumnSuggestBtn" class="dsw-llm-btn dsw-llm-btn-column" ' +
              'aria-label="Kolon öner">✨ Kolon Öner</button>' +
            '<span id="dswColumnCacheHint" class="dsw-cache-hint" hidden></span>' +
            '<div id="dswColumnSuggestPanel" class="dsw-llm-suggest-panel" hidden ' +
              'role="region" aria-label="LLM kolon önerileri"></div>';
        panel.insertBefore(bar, panel.firstChild);
        const btn = bar.querySelector('#dswColumnSuggestBtn');
        btn.disabled = !(_state.metric && _state.metric.metric_key);
        btn.addEventListener('click', _onColumnSuggestClick);
    }

    // ── B8: Format Öner ────────────────────────────────────────────────
    async function _onFormatSuggestClick() {
        const btn = document.getElementById('dswFormatSuggestBtn');
        const hint = document.getElementById('dswFormatCacheHint');
        if (!_state.sourceId || !_state.selectedTableId) {
            _notify('Önce kaynak ve tablo seçin', 'warning');
            return;
        }
        // v3.37.3 (bulgular-2 / Bulgu 4b-ii): metric + kolon pre-flight kontrol.
        // Backend FormatSuggestRequest metric_name + en az 1 kolon zorunlu;
        // eksikse 422 dönerek "yukarıdaki" generic hata mesajını tetikliyordu.
        // Burada kullanıcıya doğrudan eksik adımı bildiriyoruz.
        const hasMetric = !!(
            (_state.metric && _state.metric.metric_key) ||
            (_state.selectedMetrics && _state.selectedMetrics.size > 0)
        );
        if (!hasMetric) {
            _notify(_t('wizard.toast.format_select_metric_first'), 'warning');
            return;
        }
        // v3.37.2 (ARES+METIS): backend FormatSuggestRequest kontratı:
        // { metric:{metric_name, agg, formula, unit}, columns:[str], user_intent? }
        const cols = (Array.isArray(_state.reportColumns) ? _state.reportColumns : [])
            .map(function (c) { return c.column_name; })
            .filter(function (n) { return !!n; });
        if (!cols.length) {
            _notify(_t('wizard.toast.format_select_columns_first'), 'warning');
            return;
        }
        // Bulgular3 / Bulgu 6: metric_name fallback zinciri — _state.metric
        // tekil pointer'i boş olabilir (multi-select ilk eklemeden sonra),
        // bu durumda selectedMetrics + _metricsIndex'ten ilk dolu adı bul.
        function _pickMetricForPayload() {
            const idx = _state._metricsIndex || {};
            const candidates = [];
            if (_state.metric && _state.metric.metric_key) candidates.push(_state.metric);
            if (_state.selectedMetrics && _state.selectedMetrics.forEach) {
                _state.selectedMetrics.forEach(function (k) {
                    if (idx[k]) candidates.push(idx[k]);
                });
            }
            for (let i = 0; i < candidates.length; i++) {
                const c = candidates[i];
                const nm = (c.name_tr || c.metric_name || c.label || c.metric_key || '').trim();
                if (nm) return { src: c, name: nm };
            }
            return null;
        }
        const picked = _pickMetricForPayload();
        if (!picked || !picked.name) {
            _notify('Metrik adı boş — önce metrik seçimini doğrulayın.', 'warning');
            return;
        }
        const m = picked.src;
        const metric = {
            metric_name: picked.name,
            agg: m.agg || m.aggregation || null,
            formula: m.formula || null,
            unit: m.unit || null,
        };
        const payload = {
            metric: metric,
            columns: cols,
            user_intent: _state.user_intent || '',
        };
        _llmSetBusy(btn, true);
        try {
            const data = await _fetchJson(API_BASE + '/llm/format-suggest', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            _showCacheHint(hint, !!(data && data.cache_hit));
            _renderFormatSuggestions(data);
        } catch (e) {
            console.warn('[db_smart_wizard] format-suggest failed:', e);
            // Bulgular3 / Bulgu 6: backend HTTP detail'ini kullanıcıya yansıt.
            const detail = (e && (e.detail || e.message)) ? String(e.detail || e.message) : '';
            _llmError('AI önerisi alınamadı' + (detail ? ': ' + detail : ''), e, btn);
            return;
        }
        _llmSetBusy(btn, false);
    }

    function _renderFormatSuggestions(data) {
        const host = document.getElementById('dswFormatSuggestPanel');
        if (!host) return;
        // v3.37.2: backend FormatSuggestResponse → { format_cards: [...] }
        // (eski `formats` alanına eski sürüm yanıtı için fallback bırakıldı)
        const items = (data && Array.isArray(data.format_cards)) ? data.format_cards :
                      (data && Array.isArray(data.formats)) ? data.formats : [];
        if (!items.length) {
            host.innerHTML = '<p class="dsw-hint">Öneri dönmedi.</p>';
            host.hidden = false;
            return;
        }
        const iconOf = function (ct) {
            const k = String(ct || '').toLowerCase();
            if (k === 'bar') return '📊';
            if (k === 'line') return '📈';
            if (k === 'pie') return '🥧';
            if (k === 'table') return '📋';
            if (k === 'scatter') return '🔵';
            return '✨';
        };
        host.innerHTML = items.map(function (f, idx) {
            const title = f.title || ('Format ' + (idx + 1));
            const ct = f.chart_type || 'table';
            const rationale = f.rationale || '';
            return '<div class="dsw-format-card" data-format-idx="' + idx + '">' +
                '<div class="dsw-format-card-head">' +
                  '<span class="dsw-format-icon" aria-hidden="true">' + iconOf(ct) + '</span>' +
                  '<strong class="dsw-format-card-title">' + _escape(title) + '</strong>' +
                  '<span class="dsw-format-card-type">' + _escape(ct) + '</span>' +
                '</div>' +
                '<p class="dsw-format-card-rationale">' + _escape(rationale) + '</p>' +
                '<button type="button" class="dsw-format-apply-btn" ' +
                  'data-format-apply="' + idx + '">Uygula</button>' +
                '</div>';
        }).join('');
        host.hidden = false;
        host.querySelectorAll('[data-format-apply]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const idx = parseInt(btn.getAttribute('data-format-apply'), 10);
                if (isNaN(idx)) return;
                const card = items[idx];
                if (!card) return;
                _state.format = card;
                _notify('Format uygulandı: ' + (card.title || card.chart_type || ''), 'success');
                // Mark active
                host.querySelectorAll('.dsw-format-card').forEach(function (el) {
                    el.classList.remove('active');
                });
                const target = host.querySelector('[data-format-idx="' + idx + '"]');
                if (target) target.classList.add('active');
                // v3.37.1 G: seçim → çalıştır (verbatim spec Madde 8)
                try { _runGeneratedReport(); } catch (err) {
                    console.error('[db_smart_wizard] format auto-run failed:', err);
                }
            });
        });
    }

    // Step enter hook'larına LLM butonlarını mount et — `_onStepEnter`
    // function declaration olduğu için reassign yerine `_setStep` sonrası
    // tetiklenen `_onStepEnter` zaten içinde lazy fetch yapıyor; biz LLM
    // butonlarını ilgili load fonksiyonları sonrası mount eden bir
    // MutationObserver yerine doğrudan _onStepEnter'a ek hook çağrısı
    // koyamadığımız için, _renderStep2/3 ve _loadPreview'ye dışarıdan
    // çağırılan helper'ları zaten ekledik. Burası rezerve no-op.
    function _v337StepHook(n) {
        if (n === 2) {
            try { _ensureMetricSuggestButton(); } catch (e) { /* defansif */ }
        } else if (n === 3) {
            try { _ensureColumnSuggestButton(); } catch (e) { /* defansif */ }
        } else if (n === 4) {
            try { _renderOrderByChips(); } catch (e) { /* defansif */ }
            const panel = document.getElementById('dswStep4');
            try { _ensureRunFooter(panel); } catch (e) { /* defansif */ }
            // v3.37.2 B2 — LLM chip header (run-btn'den ÖNCE mount edilsin diye
            // burada da çağırıyoruz; _loadPreview da ayrıca çağırır — idempotent)
            try { _ensureLlmChipsHeader(panel); } catch (e) { /* defansif */ }
        }
    }

    // ──────────────────────────────────────────────────────────────────

    window.DbSmartWizardModule = {
        init: init,
        close: _closeWizard,
        openAsModal: openAsModal,
        closeModal: closeModal,
        isOpen: isOpen,
        _notifySaved: _notifySaved,
        // v3.36.0 F11 — Grafik popup hook'ları (F9 entegrasyonu için)
        openChart: openChart,
        setLastReportResult: setLastReportResult,
        getState: function () { return Object.assign({}, _state); },
        // v3.37.0 (HEBE-FE) — testability
        loadSavedReports: loadSavedReports,
        _prettyPrintSql: _prettyPrintSql,
    };
})();
