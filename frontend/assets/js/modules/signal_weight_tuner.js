/* VYRA v3.29.8 L3 — Signal Weight Tuner UI
 * ------------------------------------------
 * /api/admin/signal-weights/* endpoint'lerini kullanır.
 * agentic_observability sekmesinin altında "Sinyal Ağırlıkları" tab'ı.
 *
 * HEBE Pre-Plan Gate:
 *   - Tablolar role="grid" değil, ama th[scope] ve aria-label var
 *   - Butonlar ARIA + keyboard nav default (button element)
 *   - prefers-reduced-motion → transition: none (CSS'te)
 *   - Onay modal'ı destructive aksiyonlar için (reset)
 */
(function (global) {
    'use strict';

    const SIGNAL_LABELS = {
        semantic: 'Semantik',
        name_fuzzy: 'Tablo Adı (fuzzy)',
        column_match: 'Kolon Eşleşmesi',
        fk_centrality: 'FK Merkeziliği',
        recency: 'Son Kullanım',
        usage_freq: 'Kullanım Sıklığı',
        glossary_match: 'Glossary Eşleşmesi',
    };

    const FORMAT = {
        weight: (w) => (w == null ? '—' : Number(w).toFixed(3)),
        delta: (cur, sug) => {
            if (cur == null || sug == null) return '—';
            const d = Number(sug) - Number(cur);
            const sign = d > 0 ? '+' : '';
            return sign + d.toFixed(3);
        },
        pearson: (r) => (r == null ? '—' : Number(r).toFixed(3)),
        confidence: (c) => (c == null ? '—' : (Number(c) * 100).toFixed(0) + '%'),
        date: (s) => {
            if (!s) return '—';
            try {
                return new Date(s).toLocaleString('tr-TR', {
                    dateStyle: 'short', timeStyle: 'short',
                });
            } catch (_) { return s; }
        },
    };

    let _initialized = false;

    // v3.34.0: vyraFetch delegate — Auth + JSON + friendly error helper'da.
    function _api(path, options = {}) {
        const opts = { method: options.method || 'GET' };
        if (options.body !== undefined && options.body !== null) {
            opts.body = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
        }
        return window.vyraFetch(`/admin/signal-weights${path}`, opts);
    }

    function _toast(msg, kind = 'success') {
        if (global.showToast) global.showToast(msg, kind);
        else console.log(`[swt:${kind}]`, msg);
    }

    async function _loadCurrentAndSuggestions() {
        const loading = document.getElementById('swtLoading');
        if (loading) loading.hidden = false;
        try {
            const [cur, sug, audit] = await Promise.all([
                _api('/current'),
                _api('/suggestions?only_pending=true&limit=50'),
                _api('/audit?limit=20'),
            ]);
            _renderCurrent(cur);
            _renderSuggestions(sug);
            _renderAudit(audit);
        } catch (err) {
            _toast(`Yükleme hatası: ${err.message}`, 'error');
            console.error('[swt] load error:', err);
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function _renderDeployBanner(data) {
        // v3.29.9 — FK inference recent deploy banner: fk_centrality önerileri
        // henüz olgunlaşmamış olabilir, admin'i uyar.
        const host = document.getElementById('swtDeployBanner');
        if (!host) return;
        if (data && data.fk_inference_recent_deploy === true) {
            const ageH = Number(data.fk_inference_deploy_age_hours || 0);
            const remainingH = Math.max(0, 72 - ageH);
            const remainingTxt = remainingH >= 24
                ? `${(remainingH / 24).toFixed(1)} gün`
                : `${remainingH.toFixed(0)} saat`;
            host.innerHTML = `
                <div class="swt-deploy-banner" role="status" aria-live="polite">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <span>
                        <strong>v3.29.9 FK Inference yeni devreye alındı.</strong>
                        Deploy üzerinden ${ageH.toFixed(1)} saat geçti.
                        <code class="swt-mono">fk_centrality</code> önerileri olgunlaşana kadar ~${remainingTxt} daha bekleyin.
                    </span>
                </div>
            `;
            host.hidden = false;
        } else {
            host.hidden = true;
            host.innerHTML = '';
        }
    }

    function _renderCurrent(data) {
        _renderDeployBanner(data);
        const tbody = document.querySelector('#swtCurrentTable tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        const defaults = data.defaults || {};
        const active = data.active_weights || {};
        const overrides = {};
        (data.overrides || []).forEach((o) => { overrides[o.signal_name] = o; });

        Object.keys(SIGNAL_LABELS).forEach((sig) => {
            const tr = document.createElement('tr');
            const ov = overrides[sig];
            tr.innerHTML = `
                <td>${SIGNAL_LABELS[sig]} <span class="swt-mono">(${sig})</span></td>
                <td class="swt-mono">${FORMAT.weight(defaults[sig])}</td>
                <td class="swt-mono swt-weight-cell">${FORMAT.weight(active[sig])}</td>
                <td class="swt-note">${(ov && ov.audit_note) ? _escape(ov.audit_note) : '<span class="ao-empty-inline">—</span>'}</td>
                <td>
                    <button type="button" class="btn btn-sm btn-secondary swt-manual-btn"
                            data-signal="${sig}"
                            aria-label="${SIGNAL_LABELS[sig]} sinyalini manuel ayarla">
                        <i class="fa-solid fa-pen"></i> Manuel Set
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        // Manuel set click
        tbody.querySelectorAll('.swt-manual-btn').forEach((b) => {
            b.addEventListener('click', () => _onManualOverride(b.dataset.signal));
        });
    }

    function _renderSuggestions(data) {
        const tbody = document.querySelector('#swtSuggestionsTable tbody');
        const empty = document.getElementById('swtSuggestionsEmpty');
        if (!tbody) return;
        const rows = data.suggestions || [];
        tbody.innerHTML = '';
        if (empty) empty.hidden = rows.length > 0;
        rows.forEach((s) => {
            const tr = document.createElement('tr');
            const isLowConf = (s.confidence || 0) < 0.5;
            tr.innerHTML = `
                <td>${SIGNAL_LABELS[s.signal_name] || s.signal_name}</td>
                <td class="swt-mono">${FORMAT.weight(s.current_weight)}</td>
                <td class="swt-mono">${FORMAT.weight(s.suggested_weight)}</td>
                <td class="swt-mono">${FORMAT.delta(s.current_weight, s.suggested_weight)}</td>
                <td class="swt-mono">${FORMAT.pearson(s.correlation_pearson)}</td>
                <td class="swt-mono ${isLowConf ? 'swt-conf-low' : 'swt-conf-ok'}">${FORMAT.confidence(s.confidence)}</td>
                <td class="swt-mono">${s.sample_size || 0}</td>
                <td>${FORMAT.date(s.computed_at)}</td>
                <td>
                    <button type="button" class="btn btn-sm btn-primary swt-apply-btn"
                            data-id="${s.id}" data-signal="${s.signal_name}"
                            aria-label="${SIGNAL_LABELS[s.signal_name] || s.signal_name} önerisini uygula">
                        <i class="fa-solid fa-check"></i> Uygula
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        tbody.querySelectorAll('.swt-apply-btn').forEach((b) => {
            b.addEventListener('click', () => _onApply(b.dataset.id, b.dataset.signal));
        });
    }

    function _renderAudit(data) {
        const tbody = document.querySelector('#swtAuditTable tbody');
        const empty = document.getElementById('swtAuditEmpty');
        if (!tbody) return;
        const rows = data.audit_log || [];
        tbody.innerHTML = '';
        if (empty) empty.hidden = rows.length > 0;
        rows.forEach((r) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${SIGNAL_LABELS[r.signal_name] || r.signal_name}</td>
                <td class="swt-mono">${FORMAT.weight(r.old_weight)}</td>
                <td class="swt-mono">${FORMAT.weight(r.new_weight)}</td>
                <td><span class="swt-action swt-action--${_escape(r.action || '')}">${_escape(r.action || '')}</span></td>
                <td>${FORMAT.date(r.changed_at)}</td>
                <td class="swt-note">${r.audit_note ? _escape(r.audit_note) : '<span class="ao-empty-inline">—</span>'}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function _onApply(id, signalName) {
        const sigLabel = SIGNAL_LABELS[signalName] || signalName;
        const note = prompt(`"${sigLabel}" önerisini uygula. Audit notu (opsiyonel):`, '');
        if (note === null) return; // cancel
        _api('/apply', {
            method: 'POST',
            body: JSON.stringify({ suggestion_id: Number(id), audit_note: note || null }),
        })
            .then((res) => {
                _toast(
                    `${sigLabel}: ${FORMAT.weight(res.old_weight)} → ${FORMAT.weight(res.new_weight)} uygulandı`,
                    'success',
                );
                _loadCurrentAndSuggestions();
            })
            .catch((err) => _toast(`Uygulama hatası: ${err.message}`, 'error'));
    }

    function _onManualOverride(signalName) {
        const sigLabel = SIGNAL_LABELS[signalName] || signalName;
        const raw = prompt(`"${sigLabel}" için yeni ağırlık (0.0 - 1.0):`, '');
        if (raw === null) return;
        const val = Number(raw);
        if (!Number.isFinite(val) || val < 0 || val > 1) {
            _toast('Geçersiz ağırlık (0.0 - 1.0 arası olmalı)', 'error');
            return;
        }
        const note = prompt(`Audit notu (opsiyonel):`, '');
        if (note === null) return;
        _api(`/${encodeURIComponent(signalName)}`, {
            method: 'PUT',
            body: JSON.stringify({ weight: val, audit_note: note || null }),
        })
            .then(() => {
                _toast(`${sigLabel} → ${FORMAT.weight(val)} ayarlandı`, 'success');
                _loadCurrentAndSuggestions();
            })
            .catch((err) => _toast(`Override hatası: ${err.message}`, 'error'));
    }

    function _onAnalyze() {
        const btn = document.getElementById('swtAnalyzeBtn');
        if (btn) btn.disabled = true;
        _api('/analyze', { method: 'POST', body: JSON.stringify({}) })
            .then((res) => {
                if (res.ok) {
                    _toast(`Analiz tamam: ${res.suggestions_count || 0} öneri üretildi`, 'success');
                    _loadCurrentAndSuggestions();
                } else {
                    _toast(`Analiz başarısız: ${res.error || 'unknown'}`, 'error');
                }
            })
            .catch((err) => _toast(`Analiz hatası: ${err.message}`, 'error'))
            .finally(() => { if (btn) btn.disabled = false; });
    }

    function _onReset() {
        if (!confirm('Tüm sinyal ağırlığı override\'ları silinecek. Varsayılan ağırlıklara dönülecek. Devam edilsin mi?')) {
            return;
        }
        _api('/reset', { method: 'POST', body: JSON.stringify({}) })
            .then((res) => {
                _toast(`${res.removed_count || 0} override silindi`, 'success');
                _loadCurrentAndSuggestions();
            })
            .catch((err) => _toast(`Sıfırlama hatası: ${err.message}`, 'error'));
    }

    function _escape(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function init() {
        if (_initialized) return;
        const tabBtn = document.getElementById('aoTabBtnSignals');
        if (!tabBtn) return;
        _initialized = true;

        // Tab tıklanınca ilk yüklemeyi yap (lazy)
        let loadedOnce = false;
        tabBtn.addEventListener('click', () => {
            if (!loadedOnce) {
                loadedOnce = true;
                _loadCurrentAndSuggestions();
            }
        });

        const refreshBtn = document.getElementById('swtRefreshBtn');
        if (refreshBtn) refreshBtn.addEventListener('click', _loadCurrentAndSuggestions);

        const analyzeBtn = document.getElementById('swtAnalyzeBtn');
        if (analyzeBtn) analyzeBtn.addEventListener('click', _onAnalyze);

        const resetBtn = document.getElementById('swtResetBtn');
        if (resetBtn) resetBtn.addEventListener('click', _onReset);
    }

    // DOM hazır olduğunda init
    if (document.readyState !== 'loading') init();
    else document.addEventListener('DOMContentLoaded', init);

    global.SignalWeightTuner = { init, reload: _loadCurrentAndSuggestions };
})(window);
