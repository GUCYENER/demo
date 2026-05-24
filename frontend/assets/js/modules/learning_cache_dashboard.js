/* -----------------------------------------------
   VYRA — Learning Cache Hit Dashboard (Ajan-G)
   v3.32.0

   learned_db_queries cache effectiveness widget'ı.
   - 3 metrik kart: Total Queries, Total Hits, Hit Rate %
   - Top-10 most-hit query tablosu (ARIA + tooltip + SQL toggle)
   - Empty / loading / error state'leri
   - ARIA: role=status, aria-busy, role=table
   - alert/confirm/prompt YASAK → window.showToast
   - Hex sabit YOK → tüm renkler design token'lar üzerinden CSS sınıflarıyla
------------------------------------------------ */

// v3.34.0: vyraFetch /api + API_BASE_URL prefix'ini kendi ekliyor — base sabiti kaldırıldı.

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function _toast(type, message) {
    if (typeof window === 'undefined') return;
    if (window.VyraToast && typeof window.VyraToast[type] === 'function') {
        window.VyraToast[type](message);
        return;
    }
    if (typeof window.showToast === 'function') {
        window.showToast(type, message);
        return;
    }
    // Son çare: console — alert/confirm/prompt YASAK
    console.log(`[learning-cache toast ${type}]`, message);
}

function _escape(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _relativeTime(iso) {
    if (!iso) return '—';
    const then = new Date(iso);
    if (Number.isNaN(then.getTime())) return '—';
    const diffMs = Date.now() - then.getTime();
    const sec = Math.floor(diffMs / 1000);
    if (sec < 60) return `${sec} sn önce`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} dk önce`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} sa önce`;
    const day = Math.floor(hr / 24);
    if (day < 30) return `${day} gün önce`;
    const mo = Math.floor(day / 30);
    if (mo < 12) return `${mo} ay önce`;
    const yr = Math.floor(mo / 12);
    return `${yr} yıl önce`;
}

function _fmtPct(rate) {
    const n = Number(rate || 0) * 100;
    return `${n.toFixed(1)}%`;
}

function _fmtNum(n) {
    const v = Number(n || 0);
    return v.toLocaleString('tr-TR');
}

async function _fetchStats(sourceId) {
    // v3.34.0: vyraFetch — Auth + JSON + friendly error helper'da.
    const path = `/data-sources/${encodeURIComponent(sourceId)}/cache-stats`;
    const data = await window.vyraFetch(path);
    if (data?.success === false) {
        throw new Error(data?.detail || data?.message || 'Sunucu hata bildirdi');
    }
    return data;
}

// ─────────────────────────────────────────────────────────────
// Render parçaları
// ─────────────────────────────────────────────────────────────

function _renderLoading() {
    return `
      <div class="lcache-loading" role="status" aria-live="polite" aria-busy="true">
        <i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i>
        <span>Cache istatistikleri yükleniyor…</span>
      </div>
    `;
}

function _renderError(message) {
    return `
      <div class="lcache-error" role="alert" aria-live="assertive">
        <i class="fa-solid fa-circle-exclamation" aria-hidden="true"></i>
        <div>
          <strong>Cache istatistikleri yüklenemedi</strong>
          <div class="lcache-error-msg">${_escape(message || 'Bilinmeyen hata')}</div>
        </div>
      </div>
    `;
}

function _renderEmpty() {
    return `
      <div class="lcache-empty" role="status">
        <i class="fa-solid fa-database" aria-hidden="true"></i>
        <h3>Henüz öğrenilmiş sorgu yok</h3>
        <p>Bu veri kaynağında <code>learned_db_queries</code> tablosu boş. Cache effectiveness ölçümü için önce kullanıcı/sentetik sorgular çalıştırılmalı.</p>
      </div>
    `;
}

function _renderMetricCards(summary) {
    const total = _fmtNum(summary.total);
    const hits = _fmtNum(summary.total_hits);
    const pct = _fmtPct(summary.hit_rate);
    const used = _fmtNum(summary.used_count);
    return `
      <div class="lcache-cards" role="group" aria-label="Cache özet metrikleri">
        <div class="lcache-card" role="status" aria-label="Toplam öğrenilmiş sorgu sayısı">
          <div class="lcache-card-icon"><i class="fa-solid fa-list" aria-hidden="true"></i></div>
          <div class="lcache-card-body">
            <div class="lcache-card-label">Toplam Sorgu</div>
            <div class="lcache-card-value">${total}</div>
            <div class="lcache-card-sub">${used} tanesi en az 1 kez kullanıldı</div>
          </div>
        </div>
        <div class="lcache-card" role="status" aria-label="Toplam cache isabet sayısı">
          <div class="lcache-card-icon"><i class="fa-solid fa-bolt" aria-hidden="true"></i></div>
          <div class="lcache-card-body">
            <div class="lcache-card-label">Toplam İsabet</div>
            <div class="lcache-card-value">${hits}</div>
            <div class="lcache-card-sub">SUM(hit_count)</div>
          </div>
        </div>
        <div class="lcache-card" role="status" aria-label="Cache isabet oranı">
          <div class="lcache-card-icon"><i class="fa-solid fa-chart-line" aria-hidden="true"></i></div>
          <div class="lcache-card-body">
            <div class="lcache-card-label">İsabet Oranı</div>
            <div class="lcache-card-value">${pct}</div>
            <div class="lcache-card-sub">kullanılan / toplam</div>
          </div>
        </div>
      </div>
    `;
}

function _renderTopRow(item, rank) {
    const id = Number(item.id) || 0;
    const q = _escape(item.question_text || '');
    const sqlEsc = _escape(item.sql_preview || '');
    const hit = _fmtNum(item.hit_count);
    const last = _relativeTime(item.last_hit_at);
    const lastTitle = item.last_hit_at ? _escape(item.last_hit_at) : 'Hiç isabet yok';
    const sqlBtnId = `lcache-sql-${id}`;
    const truncBadge = item.sql_truncated
        ? '<span class="lcache-trunc-badge" aria-label="SQL kısaltıldı (200 chr)">trunc</span>'
        : '';

    return `
      <div class="lcache-row" role="row">
        <div class="lcache-cell lcache-rank" role="cell">${rank}</div>
        <div class="lcache-cell lcache-q" role="cell"
             data-tooltip="${q}" title="${q}">
          <span class="lcache-q-text">${q || '<em>(boş)</em>'}</span>
        </div>
        <div class="lcache-cell lcache-hit" role="cell"
             aria-label="${hit} isabet">
          <i class="fa-solid fa-bolt" aria-hidden="true"></i> ${hit}
        </div>
        <div class="lcache-cell lcache-last" role="cell"
             title="${lastTitle}" data-tooltip="${lastTitle}">${last}</div>
        <div class="lcache-cell lcache-sql" role="cell">
          <button type="button" class="lcache-sql-toggle"
                  data-target="${sqlBtnId}"
                  aria-expanded="false" aria-controls="${sqlBtnId}"
                  aria-label="SQL önizlemesini göster/gizle"
                  data-tooltip="SQL önizlemesini göster/gizle">
            <i class="fa-solid fa-code" aria-hidden="true"></i>
            <span>SQL</span> ${truncBadge}
          </button>
          <pre id="${sqlBtnId}" class="lcache-sql-pre" hidden
               aria-label="SQL önizlemesi (max 200 karakter)">${sqlEsc}</pre>
        </div>
      </div>
    `;
}

function _renderTopTable(top) {
    if (!Array.isArray(top) || top.length === 0) {
        return `
          <div class="lcache-top-empty" role="status">
            <i class="fa-solid fa-circle-info" aria-hidden="true"></i>
            Henüz isabet alan bir sorgu yok.
          </div>
        `;
    }
    const rows = top.map((it, idx) => _renderTopRow(it, idx + 1)).join('');
    return `
      <div class="lcache-top" role="table" aria-label="En çok isabet alan 10 sorgu">
        <div class="lcache-row lcache-head" role="row">
          <div class="lcache-cell lcache-rank" role="columnheader">#</div>
          <div class="lcache-cell lcache-q" role="columnheader">Soru</div>
          <div class="lcache-cell lcache-hit" role="columnheader">İsabet</div>
          <div class="lcache-cell lcache-last" role="columnheader">Son İsabet</div>
          <div class="lcache-cell lcache-sql" role="columnheader">SQL</div>
        </div>
        ${rows}
      </div>
    `;
}

function _renderDashboard(data) {
    const summary = data?.summary || { total: 0, total_hits: 0, used_count: 0, hit_rate: 0 };
    const top = Array.isArray(data?.top) ? data.top : [];
    if ((summary.total | 0) === 0) {
        return _renderEmpty();
    }
    return `
      <section class="lcache-dashboard" role="region" aria-label="Cache Hit Dashboard">
        <header class="lcache-header">
          <h2><i class="fa-solid fa-bolt" aria-hidden="true"></i> Cache Hit Dashboard</h2>
          <button type="button" class="lcache-refresh"
                  aria-label="Cache istatistiklerini yenile"
                  data-tooltip="Yenile">
            <i class="fa-solid fa-rotate" aria-hidden="true"></i>
          </button>
        </header>
        ${_renderMetricCards(summary)}
        <h3 class="lcache-top-title">
          <i class="fa-solid fa-trophy" aria-hidden="true"></i>
          En çok isabet alan 10 sorgu
        </h3>
        ${_renderTopTable(top)}
      </section>
    `;
}

// ─────────────────────────────────────────────────────────────
// Event bağlama
// ─────────────────────────────────────────────────────────────

function _bindEvents(rootEl, sourceId) {
    // SQL toggle
    rootEl.querySelectorAll('.lcache-sql-toggle').forEach((btn) => {
        btn.addEventListener('click', (ev) => {
            ev.preventDefault();
            const target = btn.getAttribute('data-target');
            if (!target) return;
            const pre = rootEl.querySelector(`#${CSS.escape(target)}`);
            if (!pre) return;
            const open = pre.hasAttribute('hidden') ? true : false;
            if (open) {
                pre.removeAttribute('hidden');
                btn.setAttribute('aria-expanded', 'true');
            } else {
                pre.setAttribute('hidden', '');
                btn.setAttribute('aria-expanded', 'false');
            }
        });
    });
    // Refresh
    const refreshBtn = rootEl.querySelector('.lcache-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', (ev) => {
            ev.preventDefault();
            mountLearningCacheDashboard(rootEl, sourceId).catch(() => { /* handled inside */ });
        });
    }
}

// ─────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────

/**
 * Mount the Learning Cache Dashboard into the given root element.
 * @param {HTMLElement} rootEl - container element (yapay olarak innerHTML ile yazılır)
 * @param {number|string} sourceId - data source id
 * @returns {Promise<void>}
 */
async function mountLearningCacheDashboard(rootEl, sourceId) {
    if (!rootEl || typeof rootEl.innerHTML !== 'string') {
        throw new Error('mountLearningCacheDashboard: geçerli bir rootEl gerekli');
    }
    const sid = Number(sourceId);
    if (!Number.isFinite(sid) || sid <= 0) {
        rootEl.innerHTML = _renderError('Geçersiz source_id');
        return;
    }

    rootEl.setAttribute('aria-busy', 'true');
    rootEl.innerHTML = _renderLoading();

    try {
        const data = await _fetchStats(sid);
        rootEl.innerHTML = _renderDashboard(data);
        _bindEvents(rootEl, sid);
    } catch (err) {
        const msg = (err && err.message) ? err.message : 'Bilinmeyen hata';
        rootEl.innerHTML = _renderError(msg);
        _toast('error', `Cache istatistikleri yüklenemedi: ${msg}`);
    } finally {
        rootEl.setAttribute('aria-busy', 'false');
    }
}

// v3.32.0 — Bundle uyumluluğu için window'a expose et (ES export bundle'ı kırıyor).
if (typeof window !== "undefined") {
    window.mountLearningCacheDashboard = mountLearningCacheDashboard;
    window.LearningCacheDashboard = { mount: mountLearningCacheDashboard };
}
