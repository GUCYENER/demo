/**
 * sample_data_preview.js — v3.28.2 G3 (Frontend)
 * ------------------------------------------------
 * SSE event'i `selected_table_for_preview` geldiğinde aday tablonun cached
 * örnek satırlarını gösteren kart render eder.
 *
 * Backend akışı:
 *   1. deep_think_service.py SQL üretildikten sonra
 *      `selected_table_for_preview` event yayar (hint: {source_id, schema, table})
 *   2. dialog_chat.js bu case'de window.renderSampleDataPreview(parentEl, hint) çağırır
 *   3. Bu modül GET /api/data-sources/{id}/samples?schema&table'tan veri çeker
 *   4. Skeleton → kart (role=region) → execute event'i geldiğinde fade out
 *
 * SaaS / HEBE checklist:
 *   - role="region" + aria-labelledby
 *   - .skel-line placeholder (fetch sırasında)
 *   - Empty state CTA ("örnek veri toplama" yönlendirmesi)
 *   - data-tooltip "Aday tablo — sorgudan önce hızlı önizleme"
 *   - prefers-reduced-motion fallback CSS modülünde
 */
(function () {
    'use strict';

    const ENDPOINT_BASE = (window.API_BASE_URL || '') + '/api/data-sources';

    function _h(html) {
        const tpl = document.createElement('template');
        tpl.innerHTML = html.trim();
        return tpl.content.firstChild;
    }

    function _esc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _renderSkeleton(parentEl, hint) {
        const id = 'samplePreview_' + Date.now();
        const tableLabel = hint.schema ? `${hint.schema}.${hint.table}` : hint.table;
        const card = _h(`
            <section class="sample-preview-card sample-preview-loading"
                     role="region"
                     aria-labelledby="${id}_title"
                     aria-busy="true"
                     data-preview-id="${id}">
                <div class="sample-preview-header">
                    <h4 class="sample-preview-title" id="${id}_title">
                        <svg class="sample-preview-icon" viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M3 5h18M3 12h18M3 19h18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>
                        </svg>
                        <span>Aday Tablo</span>
                        <code class="sample-preview-table-id">${_esc(tableLabel)}</code>
                    </h4>
                    <span class="sample-preview-badge" data-tooltip="Sorgudan önce hızlı önizleme">Önizleme</span>
                </div>
                <div class="sample-preview-body">
                    <div class="skel-line" style="width:96%"></div>
                    <div class="skel-line" style="width:82%"></div>
                    <div class="skel-line" style="width:88%"></div>
                </div>
            </section>
        `);
        parentEl.appendChild(card);
        return card;
    }

    function _renderEmpty(card, hint, reason) {
        const tableLabel = hint.schema ? `${hint.schema}.${hint.table}` : hint.table;
        const body = card.querySelector('.sample-preview-body');
        if (!body) return;
        body.innerHTML = `
            <div class="sample-preview-empty">
                <svg class="sample-preview-empty-ico" viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.8" fill="none"/>
                    <line x1="12" y1="8" x2="12" y2="13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                    <circle cx="12" cy="16.5" r="1" fill="currentColor"/>
                </svg>
                <p class="sample-preview-empty-msg">
                    <strong>${_esc(tableLabel)}</strong> için henüz örnek veri toplanmamış.
                </p>
                <p class="sample-preview-empty-hint">${_esc(reason || 'Yöneticinizden Veri Kaynakları → Örnek Veri Topla işlemini çalıştırmasını isteyin.')}</p>
            </div>
        `;
        card.classList.remove('sample-preview-loading');
        card.setAttribute('aria-busy', 'false');
    }

    function _renderData(card, hint, payload) {
        const body = card.querySelector('.sample-preview-body');
        if (!body) return;

        const columns = Array.isArray(payload.columns) ? payload.columns : [];
        const rows = Array.isArray(payload.rows) ? payload.rows : [];

        if (!rows.length) {
            _renderEmpty(card, hint, 'Cache boş döndü.');
            return;
        }

        // Türkçe etiket (varsa) başlığa ekle
        if (payload.business_name_tr) {
            const titleEl = card.querySelector('.sample-preview-title span');
            if (titleEl) {
                titleEl.textContent = 'Aday Tablo — ' + payload.business_name_tr;
            }
        }

        const colNames = columns.length ? columns.map((c) => c.name) : Object.keys(rows[0] || {});

        let html = '<div class="sample-preview-table-wrap"><table class="sample-preview-table"><thead><tr>';
        for (const c of colNames) {
            html += `<th scope="col">${_esc(c)}</th>`;
        }
        html += '</tr></thead><tbody>';
        for (const r of rows) {
            html += '<tr>';
            for (const c of colNames) {
                const v = r[c];
                const text = v == null ? '' : String(v);
                const truncated = text.length > 80 ? text.slice(0, 77) + '…' : text;
                html += `<td title="${_esc(text)}">${_esc(truncated)}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';

        const footer = `
            <div class="sample-preview-footer">
                <span class="sample-preview-meta">
                    ${rows.length} satır gösteriliyor
                    ${payload.row_count && payload.row_count > rows.length ? ` (cache: ${payload.row_count})` : ''}
                </span>
                ${payload.fetched_at ? `<span class="sample-preview-fetched" data-tooltip="Cache zamanı">⏱ ${_esc(payload.fetched_at.slice(0, 16).replace('T', ' '))}</span>` : ''}
            </div>
        `;

        body.innerHTML = html + footer;
        card.classList.remove('sample-preview-loading');
        card.setAttribute('aria-busy', 'false');
    }

    /**
     * SSE event handler — dialog_chat.js bunu çağırır.
     * @param {HTMLElement} parentEl  Mesaj container
     * @param {Object} hint  {source_id, schema, table}
     */
    function renderSampleDataPreview(parentEl, hint) {
        if (!parentEl || !hint || !hint.source_id || !hint.table) return;

        // Aynı parent'a tekrar tekrar eklenmesin
        const existing = parentEl.querySelector('.sample-preview-card');
        if (existing) {
            return;
        }

        const card = _renderSkeleton(parentEl, hint);

        const token = (typeof window !== 'undefined' && window.localStorage)
            ? window.localStorage.getItem('access_token')
            : null;

        const params = new URLSearchParams({
            table: hint.table,
            limit: '5',
        });
        if (hint.schema) params.append('schema', hint.schema);

        const url = `${ENDPOINT_BASE}/${encodeURIComponent(hint.source_id)}/samples?${params.toString()}`;

        fetch(url, {
            method: 'GET',
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        })
            .then(async (res) => {
                if (res.status === 404) {
                    const body = await res.json().catch(() => ({}));
                    _renderEmpty(card, hint, body.detail);
                    return null;
                }
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                return res.json();
            })
            .then((data) => {
                if (!data) return;
                _renderData(card, hint, data);
            })
            .catch((err) => {
                console.warn('[SampleDataPreview] fetch hatası:', err && err.message);
                _renderEmpty(card, hint, 'Örnek veri yüklenemedi.');
            });
    }

    window.renderSampleDataPreview = renderSampleDataPreview;
})();
