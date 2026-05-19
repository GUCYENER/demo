/**
 * VYRA v3.29.7 G2 — Disambiguation Card v2
 * =========================================
 * SSE event `clarification_v2` için zengin "Bunu mu kastettiniz?" kartları.
 *
 * Backend payload (her kart):
 *   {
 *     schema, table, label_tr, score, matched_terms,
 *     row_count_estimate, preview_sql,
 *     sample_rows: [{col1:val, col2:val, ...}],
 *     masked_columns: [str], join_paths_to_target: [[node, node, ...]],
 *     truncated: bool
 *   }
 *
 * Public API:
 *   window.DisambiguationCardV2.render(cards, query, message, onSelect, container)
 *
 * HEBE compliance:
 *   - data-tooltip + aria-label ikon-only buton zorunluluğu
 *   - keyboard erişim (Tab/Enter/Space/Esc)
 *   - role="radiogroup" / role="radio" semantic
 *   - CSS değişkenler (no hex), FontAwesome 6 (fa-solid)
 *   - Türkçe label_tr defaultu + admin_verified rozeti
 */
(function () {
    'use strict';

    /** XSS-safe text → DOM */
    function _escape(s) {
        const div = document.createElement('div');
        div.textContent = String(s == null ? '' : s);
        return div.innerHTML;
    }

    function _formatRowCount(n) {
        if (n == null || isNaN(n)) return '';
        if (n < 1000) return String(n);
        if (n < 1_000_000) return (n / 1000).toFixed(1).replace('.0', '') + 'K';
        return (n / 1_000_000).toFixed(1).replace('.0', '') + 'M';
    }

    /** Sample rows mini-table */
    function _renderSampleTable(rows, maskedCols) {
        if (!Array.isArray(rows) || rows.length === 0) {
            return `<div class="disambig-sample-empty">
                <i class="fa-solid fa-circle-info"></i>
                <span>Örnek satır yok</span>
            </div>`;
        }
        const cols = Object.keys(rows[0]);
        const maskedSet = new Set(maskedCols || []);
        const head = cols.map(c => {
            const masked = maskedSet.has(c);
            const icon = masked ? '<i class="fa-solid fa-eye-slash" aria-hidden="true"></i> ' : '';
            const tt = masked ? 'PII maskelenmiş kolon' : 'Kolon adı';
            return `<th data-tooltip="${_escape(tt)}">${icon}${_escape(c)}</th>`;
        }).join('');
        const body = rows.slice(0, 3).map(row => {
            const cells = cols.map(c => {
                const v = row[c];
                const str = v == null ? '<span class="disambig-null">∅</span>' : _escape(String(v).slice(0, 40));
                return `<td>${str}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
        }).join('');
        return `<table class="disambig-sample-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }

    /** Join path chips: ["public.problem","public.party"] → 'problem → party' */
    function _renderJoinPaths(paths) {
        if (!Array.isArray(paths) || paths.length === 0) return '';
        const chips = paths.slice(0, 3).map(path => {
            if (!Array.isArray(path) || path.length === 0) return '';
            const nodes = path.map(n => {
                const parts = String(n).split('.');
                const short = parts[parts.length - 1] || n;
                return `<span class="disambig-path-node">${_escape(short)}</span>`;
            }).join('<i class="fa-solid fa-arrow-right disambig-path-arrow" aria-hidden="true"></i>');
            return `<div class="disambig-path-chip" data-tooltip="JOIN yolu (${_escape(path.join(' → '))})">
                <i class="fa-solid fa-diagram-project" aria-hidden="true"></i>
                ${nodes}
            </div>`;
        }).join('');
        return `<div class="disambig-paths">
            <span class="disambig-section-label">
                <i class="fa-solid fa-route" aria-hidden="true"></i> Bağlantılı tablolar
            </span>
            ${chips}
        </div>`;
    }

    function _renderCard(card, index, total) {
        const full = card.schema && card.schema !== 'public'
            ? `${card.schema}.${card.table}`
            : card.table;
        const label = card.label_tr || full;
        const rowCount = _formatRowCount(card.row_count_estimate);
        const score = (card.score || 0).toFixed(2);
        const truncated = card.truncated
            ? `<span class="disambig-badge disambig-badge-warn" data-tooltip="Bazı kolonlar PII gizliliği için maskelendi">
                 <i class="fa-solid fa-shield-halved" aria-hidden="true"></i> PII maskeli
               </span>`
            : '';
        const matchedTerms = (card.matched_terms || []).slice(0, 4).map(t =>
            `<span class="disambig-term">${_escape(t)}</span>`).join('');

        return `<div class="disambig-card-v2"
                     role="radio"
                     tabindex="0"
                     aria-checked="false"
                     aria-labelledby="disambig-title-${index}"
                     data-schema="${_escape(card.schema || '')}"
                     data-table="${_escape(card.table || '')}"
                     data-full="${_escape(full)}">

            <div class="disambig-card-header">
                <div class="disambig-card-title-wrap">
                    <i class="fa-solid fa-table disambig-card-icon" aria-hidden="true"></i>
                    <div>
                        <h4 class="disambig-card-title" id="disambig-title-${index}">
                            ${_escape(label)}
                        </h4>
                        <div class="disambig-card-meta">
                            <code class="disambig-card-fqn">${_escape(full)}</code>
                            ${rowCount ? `<span class="disambig-meta-sep">•</span>
                                <span class="disambig-row-count" data-tooltip="Tahmini satır sayısı">
                                    <i class="fa-solid fa-database" aria-hidden="true"></i> ${rowCount} satır
                                </span>` : ''}
                            <span class="disambig-meta-sep">•</span>
                            <span class="disambig-score" data-tooltip="Sıralama puanı (0-1)">
                                <i class="fa-solid fa-chart-simple" aria-hidden="true"></i> ${score}
                            </span>
                        </div>
                    </div>
                </div>
                ${truncated}
            </div>

            ${matchedTerms ? `<div class="disambig-terms">${matchedTerms}</div>` : ''}

            <div class="disambig-sample">
                <span class="disambig-section-label">
                    <i class="fa-solid fa-eye" aria-hidden="true"></i> Örnek veri
                </span>
                ${_renderSampleTable(card.sample_rows, card.masked_columns)}
            </div>

            ${_renderJoinPaths(card.join_paths_to_target)}

            <div class="disambig-card-actions">
                <button type="button" class="disambig-select-btn"
                        aria-label="Bu tabloyu seç ve sorguyu yeniden gönder"
                        data-tooltip="Bu tabloyu seçip sorguyu yeniden çalıştır">
                    <i class="fa-solid fa-check" aria-hidden="true"></i>
                    <span>Bunu seç</span>
                </button>
            </div>
        </div>`;
    }

    /**
     * Render zengin disambiguation kartları.
     *
     * @param {Array} cards - SSE clarification_v2 cards
     * @param {string} query - Original kullanıcı sorgusu
     * @param {string} message - Üst mesaj
     * @param {Function} onSelect - (selectedFull, card) => void
     * @param {HTMLElement} container - Hedef container (yoksa string döner)
     * @returns {HTMLElement | string} container veya HTML string
     */
    function render(cards, query, message, onSelect, container) {
        if (!Array.isArray(cards) || cards.length === 0) {
            const msg = `<div class="vyra-empty-state">
                <i class="fa-solid fa-circle-question" aria-hidden="true"></i>
                <h3>Eşleşen tablo bulunamadı</h3>
                <p>Soruyu farklı kelimelerle yeniden deneyin.</p>
            </div>`;
            if (container) { container.innerHTML = msg; return container; }
            return msg;
        }

        const html = `<div class="disambig-v2-wrap"
                           role="radiogroup"
                           aria-label="Tablo seçimi"
                           data-query="${_escape(query || '')}">
            <div class="disambig-v2-header">
                <i class="fa-solid fa-circle-question disambig-v2-icon" aria-hidden="true"></i>
                <div>
                    <h3 class="disambig-v2-title">${_escape(message || 'Hangi tabloyu kastettiniz?')}</h3>
                    ${query ? `<p class="disambig-v2-query"><em>"${_escape(query)}"</em></p>` : ''}
                </div>
            </div>
            <div class="disambig-v2-cards">
                ${cards.map((c, i) => _renderCard(c, i, cards.length)).join('')}
            </div>
        </div>`;

        if (!container) return html;

        container.innerHTML = html;
        const wrap = container.querySelector('.disambig-v2-wrap');
        if (!wrap) return container;

        const cardEls = wrap.querySelectorAll('.disambig-card-v2');

        function _select(cardEl) {
            // ARIA güncelleme
            cardEls.forEach(el => el.setAttribute('aria-checked', 'false'));
            cardEl.setAttribute('aria-checked', 'true');
            cardEl.classList.add('disambig-selected');
            // Diğer butonları devre dışı bırak
            wrap.querySelectorAll('.disambig-select-btn').forEach(b => {
                b.disabled = true;
                b.classList.add('disambig-btn-disabled');
            });
            const full = cardEl.dataset.full || '';
            const schema = cardEl.dataset.schema || '';
            const table = cardEl.dataset.table || '';
            // Toast bilgi (proje API'si window.showToast)
            if (typeof window.showToast === 'function') {
                window.showToast(`✓ ${full} seçildi`, 'success');
            }
            const matched = cards.find(c => (c.table === table && (c.schema || '') === schema));
            if (typeof onSelect === 'function') {
                onSelect(full, matched);
            }
        }

        // Click + Keyboard (Enter/Space)
        cardEls.forEach(cardEl => {
            const btn = cardEl.querySelector('.disambig-select-btn');
            if (btn) {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _select(cardEl);
                });
            }
            cardEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    _select(cardEl);
                }
            });
            // Card body click (button hariç)
            cardEl.addEventListener('click', (e) => {
                if (e.target.closest('.disambig-select-btn')) return;
                cardEl.focus();
            });
        });

        // İlk karta odaklan (klavye akışı)
        if (cardEls.length > 0) {
            setTimeout(() => cardEls[0].focus(), 80);
        }

        return container;
    }

    window.DisambiguationCardV2 = { render };
})();
