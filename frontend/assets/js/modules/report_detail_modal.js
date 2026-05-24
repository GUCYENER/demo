/**
 * VYRA — Report Detail Modal Module
 * ==================================
 * Kayıtlı bir raporun detayını gösterir; Çalıştır / Düzenle / Kopyala / Paylaş / Sil aksiyonları.
 *
 * Public API:
 *   window.ReportDetailModal.open(reportId, {
 *     onEdit(reportId),
 *     onDuplicate(newReportId),
 *     onDeleted(reportId),
 *     onRan(result),
 *   }) -> Promise
 *   window.ReportDetailModal.close()
 *
 * HEBE: aria-modal, role=dialog, ESC, overlay click, focus trap, return-focus, body scroll lock.
 *
 * Brief: 2026-05-23_aki-kesfi-B_saved-reports-grid
 * Version: 1.0.0
 */

(function () {
    'use strict';

    const API_BASE = '/api/db-smart';

    // ─── State ───
    let _overlay = null;
    let _dialog = null;
    let _opts = {};
    let _reportId = null;
    let _report = null;
    let _returnFocusEl = null;
    let _escHandler = null;
    let _focusTrapHandler = null;
    let _resolveOpen = null;
    let _isRunning = false;

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
        try { console.log('[ReportDetailModal]', kind || 'info', msg); } catch (_) { /* noop */ }
    }

    function _clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

    function _svg(d) {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        svg.classList.add('rdm-icon');
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', d);
        svg.appendChild(path);
        return svg;
    }

    const ICONS = {
        play: 'M8 5v14l11-7z',
        edit: 'M11 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z',
        copy: 'M9 9h10v10H9zM5 5h10v4M5 5v10h4',
        share: 'M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7M16 6l-4-4-4 4M12 2v14',
        trash: 'M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14',
        close: 'M18 6L6 18M6 6l12 12',
        spinner: 'M12 2a10 10 0 1 0 10 10',
    };

    // ─── Tarih ───
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

    // ─── Focus trap ───
    function _focusableEls(container) {
        const sel = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
        return Array.from(container.querySelectorAll(sel)).filter((el) => {
            return el.offsetParent !== null || el === document.activeElement;
        });
    }

    function _installFocusTrap(container) {
        _focusTrapHandler = function (e) {
            if (e.key !== 'Tab') return;
            const els = _focusableEls(container);
            if (els.length === 0) return;
            const first = els[0];
            const last = els[els.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };
        container.addEventListener('keydown', _focusTrapHandler);
    }

    // ─── Modal shell ───
    function _createOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'rdm-overlay';
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close();
        });

        const dialog = document.createElement('div');
        dialog.className = 'rdm-dialog';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'rdm-title');
        dialog.setAttribute('tabindex', '-1');

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // body scroll lock
        document.body.style.overflow = 'hidden';

        // ESC
        _escHandler = function (e) {
            if (e.key === 'Escape') {
                // confirm modal açıksa ona bırak
                if (document.querySelector('.rdm-confirm-overlay')) return;
                close();
            }
        };
        document.addEventListener('keydown', _escHandler);

        _installFocusTrap(dialog);

        _overlay = overlay;
        _dialog = dialog;

        // mount sonrası dialog'a focus
        requestAnimationFrame(() => {
            try { dialog.focus(); } catch (_) { /* noop */ }
            overlay.classList.add('is-visible');
        });
    }

    function _renderLoading() {
        if (!_dialog) return;
        _clear(_dialog);
        const loading = document.createElement('div');
        loading.className = 'rdm-loading';
        const sp = document.createElement('div');
        sp.className = 'rdm-spinner';
        loading.appendChild(sp);
        const t = document.createElement('div');
        t.className = 'rdm-loading-text';
        t.textContent = 'Rapor yükleniyor...';
        loading.appendChild(t);
        _dialog.appendChild(loading);
    }

    function _renderError(msg) {
        if (!_dialog) return;
        _clear(_dialog);
        const wrap = document.createElement('div');
        wrap.className = 'rdm-error';
        const t = document.createElement('div');
        t.className = 'rdm-error-text';
        t.textContent = msg || 'Bir hata oluştu.';
        wrap.appendChild(t);
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'rdm-btn rdm-btn-secondary';
        closeBtn.textContent = 'Kapat';
        closeBtn.addEventListener('click', close);
        wrap.appendChild(closeBtn);
        _dialog.appendChild(wrap);
    }

    // ─── Detail render ───
    function _renderDetail() {
        if (!_dialog || !_report) return;
        _clear(_dialog);

        // header
        const header = document.createElement('header');
        header.className = 'rdm-header';

        const headerLeft = document.createElement('div');
        headerLeft.className = 'rdm-header-left';

        const title = document.createElement('h2');
        title.className = 'rdm-title';
        title.id = 'rdm-title';
        title.textContent = _report.name || 'Adsız Rapor';
        headerLeft.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'rdm-meta';

        const ts = _report.updated_at || _report.last_run_at || _report.created_at;
        if (ts) {
            const time = document.createElement('span');
            time.className = 'rdm-meta-time';
            time.textContent = _relativeTime(ts);
            const abs = _absoluteISO(ts);
            time.setAttribute('data-tooltip', abs);
            time.setAttribute('title', abs);
            meta.appendChild(time);
        }

        const metricKey = _report.metric_key || _report.metric;
        if (metricKey) {
            const metric = document.createElement('span');
            metric.className = 'rdm-metric-badge';
            metric.textContent = String(metricKey);
            meta.appendChild(metric);
        }

        const tags = Array.isArray(_report.tags) ? _report.tags : [];
        if (tags.length > 0) {
            const tagWrap = document.createElement('span');
            tagWrap.className = 'rdm-tags';
            tags.forEach((t) => {
                const c = document.createElement('span');
                c.className = 'rdm-tag';
                c.textContent = String(t);
                tagWrap.appendChild(c);
            });
            meta.appendChild(tagWrap);
        }

        headerLeft.appendChild(meta);
        header.appendChild(headerLeft);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'rdm-icon-btn rdm-close-btn';
        closeBtn.setAttribute('aria-label', 'Kapat');
        closeBtn.setAttribute('data-tooltip', 'Kapat');
        closeBtn.appendChild(_svg(ICONS.close));
        closeBtn.addEventListener('click', close);
        header.appendChild(closeBtn);

        _dialog.appendChild(header);

        // description
        if (_report.description) {
            const desc = document.createElement('p');
            desc.className = 'rdm-description';
            desc.textContent = _report.description;
            _dialog.appendChild(desc);
        }

        // body
        const body = document.createElement('div');
        body.className = 'rdm-body';

        // preview area
        const preview = document.createElement('div');
        preview.className = 'rdm-preview';
        const hint = document.createElement('div');
        hint.className = 'rdm-preview-hint';
        if (_report.last_run_at) {
            hint.textContent = 'Son çalıştırma: ' + _relativeTime(_report.last_run_at) + ' — sonucu güncellemek için Çalıştır\'a bas.';
        } else {
            hint.textContent = 'Henüz çalıştırılmadı. Çalıştır butonu ile sorguyu yürütebilirsin.';
        }
        preview.appendChild(hint);

        const resultMount = document.createElement('div');
        resultMount.className = 'rdm-result-mount';
        preview.appendChild(resultMount);

        body.appendChild(preview);

        // SQL accordion
        if (_report.last_sql) {
            const details = document.createElement('details');
            details.className = 'rdm-sql-accordion';
            const summary = document.createElement('summary');
            summary.className = 'rdm-sql-summary';
            summary.textContent = 'SQL\'i göster';
            details.appendChild(summary);
            const pre = document.createElement('pre');
            pre.className = 'rdm-sql-pre';
            pre.textContent = String(_report.last_sql);
            details.appendChild(pre);
            body.appendChild(details);
        }

        _dialog.appendChild(body);

        // footer actions
        const footer = document.createElement('footer');
        footer.className = 'rdm-footer';

        const runBtn = _makeActionBtn('Çalıştır', ICONS.play, 'rdm-btn-primary');
        runBtn.dataset.role = 'run';
        runBtn.addEventListener('click', _onRun);
        footer.appendChild(runBtn);

        const editBtn = _makeActionBtn('Düzenle', ICONS.edit, 'rdm-btn-secondary');
        editBtn.addEventListener('click', () => {
            if (typeof _opts.onEdit === 'function') {
                try { _opts.onEdit(_reportId); } catch (e) { console.error('[ReportDetailModal] onEdit error:', e); }
            }
            close();
        });
        footer.appendChild(editBtn);

        const dupBtn = _makeActionBtn('Kopyala', ICONS.copy, 'rdm-btn-secondary');
        dupBtn.addEventListener('click', _onDuplicate);
        footer.appendChild(dupBtn);

        const shareBtn = _makeActionBtn('Paylaş', ICONS.share, 'rdm-btn-secondary');
        shareBtn.addEventListener('click', _onShare);
        footer.appendChild(shareBtn);

        const delBtn = _makeActionBtn('Sil', ICONS.trash, 'rdm-btn-danger');
        delBtn.addEventListener('click', _onDelete);
        footer.appendChild(delBtn);

        _dialog.appendChild(footer);

        // initial focus → run button
        requestAnimationFrame(() => {
            try { runBtn.focus(); } catch (_) { /* noop */ }
        });
    }

    function _makeActionBtn(label, iconPath, variantClass) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'rdm-btn ' + (variantClass || '');
        b.appendChild(_svg(iconPath));
        const span = document.createElement('span');
        span.textContent = label;
        span.className = 'rdm-btn-label';
        b.appendChild(span);
        return b;
    }

    // ─── Aksiyonlar ───
    async function _onRun(e) {
        if (_isRunning) return;
        const btn = e.currentTarget;
        _isRunning = true;
        const originalLabel = btn.querySelector('.rdm-btn-label');
        const origText = originalLabel ? originalLabel.textContent : 'Çalıştır';
        btn.disabled = true;
        btn.classList.add('is-loading');
        if (originalLabel) originalLabel.textContent = 'Çalıştırılıyor...';

        const resultMount = _dialog.querySelector('.rdm-result-mount');
        if (resultMount) {
            _clear(resultMount);
            const spin = document.createElement('div');
            spin.className = 'rdm-result-loading';
            spin.textContent = 'Sorgu çalıştırılıyor...';
            resultMount.appendChild(spin);
        }

        try {
            // F21c (ARES+HERMES 2026-05-25): /sessions/{uid}/execute backend'de
            // stub (rows:[]) — bu yüzden "Sonuç boş." görünüyordu. Gerçek runner
            // /sessions/{uid}/execute/stream (SSE). Saved report'taki last_sql +
            // source_id (wizard_state'ten) + last_dialect ile direkt yeniden çalıştır.
            const ws = _report.wizard_state || {};
            const sourceId = _report.source_id || ws.source_id || ws.sourceId;
            const lastSql = _report.last_sql || '';
            // F21c+F22c (ARES 2026-05-25): dialect HER ZAMAN omit → backend
            // source.db_type'tan resolve eder. Eski raporlarda last_dialect
            // bazen yanlış literal değer ("db_type") veya wizard'ın
            // hard-coded "postgresql" default'u olarak kaydedilmiş; rerun
            // sırasında mismatch/whitelist hatası üretiyordu. FE asla
            // dialect tahmininde bulunmasın.
            const dialect = null;
            if (!sourceId) throw new Error('Veri kaynağı (source_id) yok — rapor eksik kaydedilmiş.');
            if (!lastSql) throw new Error('Saklanan SQL yok — raporu wizard ile yeniden oluşturup kaydedin.');

            // 1) Yeni session aç (source_id zorunlu — CreateSessionRequest).
            const sess = await window.vyraFetch('/db-smart/sessions', {
                method: 'POST',
                body: { source_id: Number(sourceId) },
            });
            const uid = sess.session_uid || sess.uid || sess.id;
            if (!uid) throw new Error('Session UID alınamadı');

            // 2) /execute/stream — SSE consume; columns + rows event'lerini topla.
            const token = localStorage.getItem('access_token');
            const apiBase = (window.API_BASE_URL || 'http://localhost:8002') + '/api';
            const streamRes = await fetch(
                apiBase + '/db-smart/sessions/' + encodeURIComponent(uid) + '/execute/stream',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'text/event-stream',
                        'Authorization': token ? ('Bearer ' + token) : '',
                    },
                    body: JSON.stringify(Object.assign(
                        {
                            sql: lastSql,
                            source_id: Number(sourceId),
                            batch_size: 200,
                            max_rows: 1000,
                        },
                        dialect ? { dialect: dialect } : {}
                    )),
                }
            );
            if (!streamRes.ok) {
                let detail = '';
                try { detail = await streamRes.text(); } catch (_) { /* noop */ }
                throw new Error('HTTP ' + streamRes.status + (detail ? (': ' + detail.slice(0, 200)) : ''));
            }

            const columnsAgg = [];
            const rowsAgg = [];
            let totalCount = 0;
            let truncated = false;
            let sseError = null;

            const reader = streamRes.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                // SSE event blocks separated by \n\n
                let idx;
                while ((idx = buffer.indexOf('\n\n')) !== -1) {
                    const block = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);
                    let evtName = 'message';
                    let dataStr = '';
                    block.split('\n').forEach((line) => {
                        if (line.startsWith('event:')) evtName = line.slice(6).trim();
                        else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
                    });
                    if (!dataStr) continue;
                    let payload = null;
                    try { payload = JSON.parse(dataStr); } catch (_) { continue; }
                    if (evtName === 'columns' && Array.isArray(payload.columns)) {
                        columnsAgg.length = 0;
                        payload.columns.forEach((c) => columnsAgg.push(c));
                    } else if (evtName === 'rows' && Array.isArray(payload.rows)) {
                        payload.rows.forEach((r) => rowsAgg.push(r));
                    } else if (evtName === 'end') {
                        totalCount = Number(payload.row_count || rowsAgg.length) || rowsAgg.length;
                        truncated = !!payload.truncated;
                    } else if (evtName === 'error') {
                        sseError = payload.message || 'Stream hata';
                    }
                }
            }

            if (sseError) throw new Error(sseError);

            // 3) mark-run (best-effort)
            window.vyraFetch(
                '/db-smart/saved-reports/' + encodeURIComponent(_reportId) + '/mark-run',
                { method: 'POST' }
            ).catch(() => { /* noop */ });

            const result = {
                columns: columnsAgg,
                rows: rowsAgg,
                row_count: totalCount || rowsAgg.length,
                truncated: truncated,
            };
            if (resultMount) _renderRunResult(resultMount, result);

            _toast('Sorgu çalıştırıldı (' + result.row_count + ' satır)', 'success');
            if (typeof _opts.onRan === 'function') {
                try { _opts.onRan(result); } catch (err) { console.error('[ReportDetailModal] onRan error:', err); }
            }
        } catch (err) {
            console.error('[ReportDetailModal] run error:', err);
            _toast((err && err.message) || 'Çalıştırma başarısız', 'error');
            if (resultMount) {
                _clear(resultMount);
                const errBox = document.createElement('div');
                errBox.className = 'rdm-result-error';
                errBox.textContent = (err && err.message) || 'Çalıştırma başarısız';
                resultMount.appendChild(errBox);
            }
        } finally {
            _isRunning = false;
            btn.disabled = false;
            btn.classList.remove('is-loading');
            if (originalLabel) originalLabel.textContent = origText;
        }
    }

    function _renderRunResult(mount, result) {
        _clear(mount);
        const rows = (result && (result.rows || result.data)) || [];
        const cols = (result && result.columns) || (rows.length > 0 ? Object.keys(rows[0]) : []);
        if (!cols || cols.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'rdm-result-empty';
            empty.textContent = 'Sonuç boş.';
            mount.appendChild(empty);
            return;
        }
        const wrap = document.createElement('div');
        wrap.className = 'rdm-table-wrap';
        const table = document.createElement('table');
        table.className = 'rdm-table';
        const thead = document.createElement('thead');
        const trh = document.createElement('tr');
        cols.forEach((c) => {
            const th = document.createElement('th');
            th.textContent = String(c);
            trh.appendChild(th);
        });
        thead.appendChild(trh);
        table.appendChild(thead);
        const tbody = document.createElement('tbody');
        rows.slice(0, 100).forEach((row) => {
            const tr = document.createElement('tr');
            cols.forEach((c) => {
                const td = document.createElement('td');
                const v = (row && typeof row === 'object') ? row[c] : '';
                td.textContent = (v === null || v === undefined) ? '' : String(v);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        mount.appendChild(wrap);
        if (rows.length > 100) {
            const note = document.createElement('div');
            note.className = 'rdm-result-note';
            note.textContent = 'İlk 100 satır gösteriliyor (toplam ' + rows.length + ').';
            mount.appendChild(note);
        }
    }

    // ─── Duplicate (inline rename mini-modal) ───
    function _onDuplicate() {
        _openRenameMini((newName) => {
            // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
            window.vyraFetch(
                '/db-smart/saved-reports/' + encodeURIComponent(_reportId) + '/duplicate',
                { method: 'POST', body: { name: newName } }
            )
                .then((data) => {
                    const newId = (data && (data.report_id || data.id)) || null;
                    _toast('Rapor kopyalandı', 'success');
                    if (typeof _opts.onDuplicate === 'function') {
                        try { _opts.onDuplicate(newId); } catch (e) { console.error('[ReportDetailModal] onDuplicate error:', e); }
                    }
                })
                .catch((err) => {
                    console.error('[ReportDetailModal] duplicate error:', err);
                    _toast('Kopyalama başarısız: ' + (err && err.message ? err.message : ''), 'error');
                });
        });
    }

    function _openRenameMini(onConfirm) {
        const overlay = document.createElement('div');
        overlay.className = 'rdm-mini-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'rdm-mini-dialog';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'rdm-mini-title');

        const title = document.createElement('h3');
        title.className = 'rdm-mini-title';
        title.id = 'rdm-mini-title';
        title.textContent = 'Raporu Kopyala';
        dialog.appendChild(title);

        const label = document.createElement('label');
        label.className = 'rdm-mini-label';
        label.textContent = 'Yeni rapor adı';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'rdm-mini-input';
        input.value = (_report && _report.name ? _report.name + ' (kopya)' : 'Adsız Rapor (kopya)');
        label.appendChild(input);
        dialog.appendChild(label);

        const actions = document.createElement('div');
        actions.className = 'rdm-mini-actions';

        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'rdm-btn rdm-btn-secondary';
        cancel.textContent = 'İptal';
        actions.appendChild(cancel);

        const save = document.createElement('button');
        save.type = 'button';
        save.className = 'rdm-btn rdm-btn-primary';
        save.textContent = 'Kaydet';
        actions.appendChild(save);

        dialog.appendChild(actions);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        const closeMini = () => {
            document.removeEventListener('keydown', miniEsc);
            overlay.remove();
        };
        const miniEsc = (e) => { if (e.key === 'Escape') closeMini(); };
        document.addEventListener('keydown', miniEsc);

        cancel.addEventListener('click', closeMini);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) closeMini(); });
        save.addEventListener('click', () => {
            const v = (input.value || '').trim();
            if (!v) { input.focus(); return; }
            closeMini();
            onConfirm(v);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); save.click(); }
        });

        requestAnimationFrame(() => { try { input.focus(); input.select(); } catch (_) { /* noop */ } });
    }

    // ─── Share ───
    function _onShare() {
        // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
        window.vyraFetch(
            '/db-smart/saved-reports/' + encodeURIComponent(_reportId) + '/share',
            { method: 'POST', body: { ttl_hours: 168 } }
        )
            .then((data) => {
                const token = data && data.share_token;
                if (!token) throw new Error('Share token alınamadı');
                const url = window.location.origin + '/r/' + encodeURIComponent(token);
                const writeClipboard = () => {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        return navigator.clipboard.writeText(url);
                    }
                    return Promise.reject(new Error('clipboard unavailable'));
                };
                writeClipboard()
                    .then(() => { _toast('Paylaşım linki panoya kopyalandı', 'success'); })
                    .catch(() => { _toast('Link: ' + url, 'info'); });
            })
            .catch((err) => {
                console.error('[ReportDetailModal] share error:', err);
                _toast('Paylaşım başarısız: ' + (err && err.message ? err.message : ''), 'error');
            });
    }

    // ─── Delete (custom confirm) ───
    function _onDelete() {
        _openConfirm({
            title: 'Raporu Sil',
            message: '"' + ((_report && _report.name) || 'Bu rapor') + '" kalıcı olarak silinecek. Bu işlem geri alınamaz.',
            confirmText: 'Sil',
            cancelText: 'İptal',
            danger: true,
            onConfirm: () => {
                // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
                window.vyraFetch(
                    '/db-smart/saved-reports/' + encodeURIComponent(_reportId),
                    { method: 'DELETE' }
                )
                    .then(() => {
                        _toast('Rapor silindi', 'success');
                        const deletedId = _reportId;
                        close();
                        if (typeof _opts.onDeleted === 'function') {
                            try { _opts.onDeleted(deletedId); } catch (e) { console.error('[ReportDetailModal] onDeleted error:', e); }
                        }
                    })
                    .catch((err) => {
                        console.error('[ReportDetailModal] delete error:', err);
                        _toast('Silme başarısız: ' + (err && err.message ? err.message : ''), 'error');
                    });
            },
        });
    }

    function _openConfirm(cfg) {
        const overlay = document.createElement('div');
        overlay.className = 'rdm-confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'rdm-confirm-dialog';
        dialog.setAttribute('role', 'alertdialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'rdm-confirm-title');
        dialog.setAttribute('aria-describedby', 'rdm-confirm-msg');

        const h = document.createElement('h3');
        h.className = 'rdm-confirm-title';
        h.id = 'rdm-confirm-title';
        h.textContent = cfg.title || 'Onayla';
        dialog.appendChild(h);

        const p = document.createElement('p');
        p.className = 'rdm-confirm-msg';
        p.id = 'rdm-confirm-msg';
        p.textContent = cfg.message || '';
        dialog.appendChild(p);

        const actions = document.createElement('div');
        actions.className = 'rdm-confirm-actions';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'rdm-btn rdm-btn-secondary';
        cancel.textContent = cfg.cancelText || 'İptal';
        actions.appendChild(cancel);

        const ok = document.createElement('button');
        ok.type = 'button';
        ok.className = 'rdm-btn ' + (cfg.danger ? 'rdm-btn-danger' : 'rdm-btn-primary');
        ok.textContent = cfg.confirmText || 'Onayla';
        actions.appendChild(ok);

        dialog.appendChild(actions);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        const closeConfirm = () => {
            document.removeEventListener('keydown', escCfg);
            overlay.remove();
        };
        const escCfg = (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeConfirm(); } };
        document.addEventListener('keydown', escCfg);

        cancel.addEventListener('click', closeConfirm);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) closeConfirm(); });
        ok.addEventListener('click', () => {
            closeConfirm();
            if (typeof cfg.onConfirm === 'function') cfg.onConfirm();
        });

        requestAnimationFrame(() => { try { cancel.focus(); } catch (_) { /* noop */ } });
    }

    // ─── Fetch detail ───
    async function _fetchDetail(id) {
        // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
        return await window.vyraFetch('/db-smart/saved-reports/' + encodeURIComponent(id));
    }

    // ─── Public ───
    function open(reportId, opts) {
        if (_overlay) { close(); }
        _reportId = reportId;
        _opts = Object.assign({}, opts || {});
        _returnFocusEl = document.activeElement;

        _createOverlay();
        _renderLoading();

        return new Promise((resolve) => {
            _resolveOpen = resolve;
            _fetchDetail(reportId)
                .then((data) => {
                    _report = data || {};
                    _renderDetail();
                })
                .catch((err) => {
                    console.error('[ReportDetailModal] fetch detail error:', err);
                    _renderError((err && err.message) || 'Rapor yüklenemedi');
                });
        });
    }

    function close() {
        if (!_overlay) return;
        if (_escHandler) {
            document.removeEventListener('keydown', _escHandler);
            _escHandler = null;
        }
        if (_focusTrapHandler && _dialog) {
            _dialog.removeEventListener('keydown', _focusTrapHandler);
            _focusTrapHandler = null;
        }
        _overlay.classList.remove('is-visible');
        const overlay = _overlay;
        const returnEl = _returnFocusEl;
        const resolve = _resolveOpen;

        setTimeout(() => {
            if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        }, 200);

        document.body.style.overflow = '';
        _overlay = null;
        _dialog = null;
        _report = null;
        _reportId = null;
        _opts = {};
        _isRunning = false;
        _resolveOpen = null;
        _returnFocusEl = null;

        if (returnEl && typeof returnEl.focus === 'function') {
            try { returnEl.focus(); } catch (_) { /* noop */ }
        }
        if (typeof resolve === 'function') resolve();
    }

    window.ReportDetailModal = {
        open: open,
        close: close,
    };
})();
