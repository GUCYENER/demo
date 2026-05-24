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

    function _renderPendingTable(rows) {
        const tbody = document.querySelector('#aoFkiPendingTable tbody');
        const empty = document.getElementById('aoFkiEmpty');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (!rows || rows.length === 0) {
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        rows.forEach((r) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${_escape(r.source_table || r.from_table || '')}</td>
                <td class="swt-mono">${_escape(r.source_column || r.from_column || '')}</td>
                <td>${_escape(r.target_table || r.to_table || '')}</td>
                <td class="swt-mono">${_escape(r.target_column || r.to_column || '')}</td>
                <td class="swt-mono">${_formatConfidence(r.confidence_score)}</td>
                <td class="swt-mono">${_escape(r.inference_method || '—')}</td>
                <td>${_formatDate(r.created_at || r.discovered_at)}</td>
            `;
            tbody.appendChild(tr);
        });
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
    }

    if (document.readyState !== 'loading') init();
    else document.addEventListener('DOMContentLoaded', init);

    global.FkInferenceObservability = { init, reload: _loadStats };
})(window);
