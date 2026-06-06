/**
 * fk_inference_observability.js — v3.29.9
 * =======================================
 * "FK Inference" sekmesi: kaynak başına FK çıkarım istatistikleri ve
 * onay bekleyen ilişkilerin listesi. Lazy load — sekme tıklanınca devreye girer.
 *
 * Bağımlı endpoint'ler (db_learning_api.py):
 *   - GET /api/admin/data-sources                      → kaynak listesi
 *   - GET /api/admin/db-learning/{src}/fk-inference-stats
 *   - GET /api/admin/db-learning/{src}/inferred-relationships?status=pending
 *
 * HEBE compliance: <select> label binding, <button> default keyboard, aria-live
 * loading, prefers-reduced-motion CSS'te.
 */
(function (global) {
    'use strict';

    let _initialized = false;
    let _sourcesLoaded = false;
    let _currentSourceId = null;

    // v3.34.0: vyraFetch delegate — Auth + JSON + friendly error helper'da.
    async function _fetchJson(path) {
        // vyraFetch otomatik /api prefix ekler — '/api/...' geçilirse strip et
        const p = path.startsWith('/api/') ? path.slice(4) : path;
        return window.vyraFetch(p);
    }

    function _escape(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _formatDate(s) {
        if (!s) return '—';
        try {
            return new Date(s).toLocaleString('tr-TR', {
                dateStyle: 'short', timeStyle: 'short',
            });
        } catch (_e) { return s; }
    }

    function _formatConfidence(c) {
        if (c == null) return '—';
        return (Number(c) * 100).toFixed(0) + '%';
    }

    function _toast(msg, kind = 'info') {
        if (global.showToast) global.showToast(msg, kind);
        else console.log(`[fki:${kind}]`, msg);
    }

    async function _loadSources() {
        if (_sourcesLoaded) return;
        const sel = document.getElementById('aoFkiSourceSelect');
        if (!sel) return;
        try {
            const data = await _fetchJson('/api/admin/data-sources');
            const items = data.items || data.sources || data || [];
            // Önce mevcut seçenekleri (placeholder hariç) temizle
            for (let i = sel.options.length - 1; i >= 1; i--) sel.remove(i);
            items.forEach((s) => {
                const opt = document.createElement('option');
                opt.value = String(s.id);
                opt.textContent = `#${s.id} — ${s.name || s.connection_name || '?'}`;
                sel.appendChild(opt);
            });
            _sourcesLoaded = true;
        } catch (err) {
            console.warn('[fki] sources load failed:', err);
            _toast(`Kaynak listesi yüklenemedi: ${err.message}`, 'error');
        }
    }

    function _renderStatsCards(stats) {
        const host = document.getElementById('aoFkiStatsCards');
        if (!host) return;
        const total = stats.total_relationships || 0;
        const declared = stats.declared_count || 0;
        const inferred = stats.inferred_count || 0;
        const verified = stats.verified_count || 0;
        const pending = stats.pending_count || 0;
        const rejected = stats.rejected_count || 0;
        const avgConf = stats.avg_inferred_confidence;

        host.innerHTML = `
            <div class="fki-stat-card">
                <div class="fki-stat-card__value">${total}</div>
                <div class="fki-stat-card__label">Toplam ilişki</div>
            </div>
            <div class="fki-stat-card">
                <div class="fki-stat-card__value">${declared}</div>
                <div class="fki-stat-card__label">Declared (DB FK)</div>
            </div>
            <div class="fki-stat-card fki-stat-card--inferred">
                <div class="fki-stat-card__value">${inferred}</div>
                <div class="fki-stat-card__label">Inferred (çıkarım)</div>
            </div>
            <div class="fki-stat-card fki-stat-card--verified">
                <div class="fki-stat-card__value">${verified}</div>
                <div class="fki-stat-card__label">Admin onaylı</div>
            </div>
            <div class="fki-stat-card fki-stat-card--pending">
                <div class="fki-stat-card__value">${pending}</div>
                <div class="fki-stat-card__label">Onay bekleyen</div>
            </div>
            <div class="fki-stat-card fki-stat-card--rejected">
                <div class="fki-stat-card__value">${rejected}</div>
                <div class="fki-stat-card__label">Reddedilen</div>
            </div>
            <div class="fki-stat-card">
                <div class="fki-stat-card__value">${_formatConfidence(avgConf)}</div>
                <div class="fki-stat-card__label">Ort. çıkarım güveni</div>
            </div>
        `;
    }

    function _splitRef(ref) {
        const parts = String(ref || '').split('.').filter(Boolean);
        if (parts.length >= 2) return { table: parts.slice(0, -1).join('.'), col: parts[parts.length - 1] };
        return { table: parts[0] || '—', col: '' };
    }

    function _renderPendingTable(rows) {
        const tbody = document.querySelector('#aoFkiPendingTable tbody');
        const empty = document.getElementById('aoFkiEmpty');
        const bulkBtn = document.getElementById('aoFkiBulkVerifyBtn');
        if (!tbody) return;
        tbody.innerHTML = '';
        const has = !!(rows && rows.length);
        if (empty) empty.hidden = has;
        if (bulkBtn) bulkBtn.hidden = !has;
        if (!has) return;
        rows.forEach((r) => {
            // endpoint 'from'/'to' (s.t.c) döndürür; eski from_table/.. fallback'i de tut
            const f = _splitRef(r.from || `${r.from_table || ''}.${r.from_column || ''}`);
            const t = _splitRef(r.to || `${r.to_table || ''}.${r.to_column || ''}`);
            const conf = r.confidence != null ? r.confidence : r.confidence_score;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${_escape(f.table)}</td>
                <td class="swt-mono">${_escape(f.col)}</td>
                <td>${_escape(t.table)}</td>
                <td class="swt-mono">${_escape(t.col)}</td>
                <td class="swt-mono">${_formatConfidence(conf)}</td>
                <td class="swt-mono">${_escape(r.method || r.inference_method || '—')}</td>
                <td class="ao-fki-row-actions">
                    <button type="button" class="btn btn-xs ao-fki-verify" data-id="${_escape(r.id)}"
                            data-tooltip="Onayla — RAG'de kullanılsın" aria-label="Onayla"><i class="fa-solid fa-check"></i></button>
                    <button type="button" class="btn btn-xs ao-fki-reject" data-id="${_escape(r.id)}"
                            data-tooltip="Reddet" aria-label="Reddet"><i class="fa-solid fa-xmark"></i></button>
                </td>`;
            tbody.appendChild(tr);
        });
    }

    const _REASON_TR = {
        no_pattern_match: 'Kalıba uymadı',
        no_target_table: 'Hedef tablo yok',
        target_pk_not_found: 'Hedef PK yok',
    };

    function _renderDiagnostics(data) {
        const reasonsHost = document.getElementById('aoFkiDiagReasons');
        const tbody = document.querySelector('#aoFkiDiagTable tbody');
        const empty = document.getElementById('aoFkiDiagEmpty');
        const byReason = (data && data.by_reason) || [];
        const items = (data && data.items) || [];
        if (reasonsHost) {
            reasonsHost.innerHTML = byReason.map((b) =>
                `<span class="ao-fki-diag-chip" data-reason="${_escape(b.reason)}">`
                + `${_escape(_REASON_TR[b.reason] || b.reason)}: <strong>${_escape(b.count)}</strong></span>`
            ).join('');
        }
        if (tbody) {
            tbody.innerHTML = '';
            items.forEach((it) => {
                const rh = [it.root, it.head].filter(Boolean).join(' / ') || '—';
                const hint = (it.evidence && it.evidence.hint) || '';
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="swt-mono">${_escape(it.column)}</td>
                    <td>${_escape(_REASON_TR[it.reason] || it.reason)}</td>
                    <td class="swt-mono">${_escape(rh)}</td>
                    <td class="ao-fki-diag-hint">${_escape(hint)}</td>`;
                tbody.appendChild(tr);
            });
        }
        if (empty) empty.hidden = items.length > 0;
    }

    async function _loadDiagnostics() {
        if (!_currentSourceId) return;
        try {
            const sid = encodeURIComponent(_currentSourceId);
            const data = await _fetchJson(`/api/admin/db-learning/${sid}/fk-diagnostics?only_open=true&limit=300`);
            _renderDiagnostics(data || {});
        } catch (err) {
            console.warn('[fki] diagnostics load failed:', err);
        }
    }

    async function _verifyReject(id, action) {
        if (!_currentSourceId || !id) return;
        const sid = encodeURIComponent(_currentSourceId);
        try {
            await window.vyraFetch(`/admin/db-learning/${sid}/relationships/${id}/${action}`, { method: 'POST' });
            _toast(action === 'verify' ? 'FK onaylandı' : 'FK reddedildi', 'success');
            _loadStats();
        } catch (err) {
            _toast(`İşlem başarısız: ${(err && err.message) || ''}`, 'error');
        }
    }

    async function _bulkVerify() {
        if (!_currentSourceId) return;
        const ids = Array.from(document.querySelectorAll('#aoFkiPendingTable .ao-fki-verify'))
            .map((b) => parseInt(b.dataset.id, 10)).filter((x) => !isNaN(x));
        if (!ids.length) return;
        if (global.confirm && !global.confirm(`${ids.length} öneriyi onaylamak istediğine emin misin?`)) return;
        const sid = encodeURIComponent(_currentSourceId);
        try {
            await window.vyraFetch(`/admin/db-learning/${sid}/relationships/bulk-verify`,
                { method: 'POST', body: { relationship_ids: ids } });
            _toast(`${ids.length} FK onaylandı`, 'success');
            _loadStats();
        } catch (err) {
            _toast(`Toplu onay başarısız: ${(err && err.message) || ''}`, 'error');
        }
    }

    async function _loadStats() {
        if (!_currentSourceId) {
            const empty = document.getElementById('aoFkiEmpty');
            if (empty) { empty.hidden = false; empty.textContent = 'Bir kaynak seçin'; }
            return;
        }
        const loading = document.getElementById('aoFkiLoading');
        const empty = document.getElementById('aoFkiEmpty');
        if (loading) loading.hidden = false;
        if (empty) empty.hidden = true;
        try {
            const sid = encodeURIComponent(_currentSourceId);
            const [stats, pending] = await Promise.all([
                _fetchJson(`/api/admin/db-learning/${sid}/fk-inference-stats`),
                _fetchJson(`/api/admin/db-learning/${sid}/inferred-relationships?status=pending&limit=100`),
            ]);
            _renderStatsCards(stats || {});
            const rows = (pending && (pending.items || pending.relationships || pending)) || [];
            _renderPendingTable(Array.isArray(rows) ? rows : []);
            _loadDiagnostics();
        } catch (err) {
            console.warn('[fki] stats load failed:', err);
            if (empty) {
                empty.hidden = false;
                empty.textContent = `Yüklenemedi: ${err.message}`;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    async function _onTabActivate() {
        await _loadSources();
        if (!_currentSourceId) {
            const sel = document.getElementById('aoFkiSourceSelect');
            if (sel && sel.options.length > 1) {
                sel.selectedIndex = 1;
                _currentSourceId = sel.value || null;
            }
        }
        await _loadStats();
    }

    function init() {
        if (_initialized) return;
        const tabBtn = document.getElementById('aoTabBtnFkInference');
        if (!tabBtn) return;
        _initialized = true;

        let loadedOnce = false;
        tabBtn.addEventListener('click', () => {
            if (!loadedOnce) {
                loadedOnce = true;
                _onTabActivate();
            }
        });

        const sel = document.getElementById('aoFkiSourceSelect');
        if (sel) {
            sel.addEventListener('change', () => {
                _currentSourceId = sel.value || null;
                _loadStats();
            });
        }
        const refreshBtn = document.getElementById('aoFkiRefreshBtn');
        if (refreshBtn) refreshBtn.addEventListener('click', _loadStats);

        // Tema-1: pending tablo delegated verify/reject + toplu onay
        const pendingTable = document.getElementById('aoFkiPendingTable');
        if (pendingTable && !pendingTable._fkiBound) {
            pendingTable._fkiBound = true;
            pendingTable.addEventListener('click', (e) => {
                const v = e.target.closest('.ao-fki-verify');
                if (v) { _verifyReject(parseInt(v.dataset.id, 10), 'verify'); return; }
                const rj = e.target.closest('.ao-fki-reject');
                if (rj) { _verifyReject(parseInt(rj.dataset.id, 10), 'reject'); }
            });
        }
        const bulkBtn = document.getElementById('aoFkiBulkVerifyBtn');
        if (bulkBtn && !bulkBtn._fkiBound) { bulkBtn._fkiBound = true; bulkBtn.addEventListener('click', _bulkVerify); }
    }

    if (document.readyState !== 'loading') init();
    else document.addEventListener('DOMContentLoaded', init);

    global.FkInferenceObservability = { init, reload: _loadStats };
})(window);
