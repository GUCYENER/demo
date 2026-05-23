/**
 * VYRA v3.32.0 — Ajan-I MVP: Error Pattern Approval UI (admin)
 * ============================================================
 *
 * self_heal_node "rewrite" kararlarını (LLM tarafından üretilen düzeltme
 * SQL'leri) admin'in tek tek onayladığı/reddettiği basit panel.
 *
 * Backend (db_learning_api.py altına eklendi):
 *   GET  /api/data-sources/admin/error-rewrites?status=pending&limit=50
 *   POST /api/data-sources/admin/error-rewrites/{id}/review
 *        body: {decision: 'approved'|'rejected', note?: string}
 *
 * HEBE UI standartları:
 *   - alert/confirm/prompt YOK — window.showToast / inline error.
 *   - Hex YOK — sınıflar design token kullanır.
 *   - Tüm butonlarda aria-label var, ikon-only butonlar dahil.
 *   - Pagination YOK (MVP: yalnız son 50).
 *
 * Kullanım:
 *   import { mountErrorReview } from "./modules/admin_error_review.js";
 *   mountErrorReview(document.querySelector("#adminErrorReviewRoot"));
 *
 * mountErrorReview idempotent — aynı root'a tekrar çağrılırsa içerik
 * yenilenir, event listener çoğalmaz.
 */

const AER_API_BASE = "/api/data-sources/admin/error-rewrites";
const MOUNT_FLAG = "__vyraErrorReviewMounted";

const STATUS_LABELS = {
  pending: "Bekliyor",
  approved: "Onaylandı",
  rejected: "Reddedildi",
  all: "Hepsi",
};

const ERROR_CLASS_LABELS = {
  syntax: "Sözdizimi",
  missing_table: "Tablo yok",
  amb_column: "Belirsiz kolon",
  timeout: "Zaman aşımı",
  empty: "Boş sonuç",
  semantic: "Anlamsal",
  permission: "Yetki",
  unknown: "Bilinmiyor",
};

/** Auth headers (localStorage access_token — projede kullanılan kalıp). */
function authHeaders() {
  const tok = (typeof localStorage !== "undefined")
    ? localStorage.getItem("access_token")
    : null;
  return tok ? { Authorization: "Bearer " + tok } : {};
}

/** XSS-safe text. */
function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Toast wrapper — proje kuralı: window.showToast varsa kullan, yoksa sessiz. */
function toast(message, type) {
  if (typeof window !== "undefined" && typeof window.showToast === "function") {
    try { window.showToast(message, type || "info"); } catch (_) { /* swallow */ }
  }
}

/** ISO timestamp → kısa Türkçe görünüm. */
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString("tr-TR", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (_) {
    return String(iso);
  }
}

/** Skeleton DOM — root içine yapı kurar. */
function buildSkeleton(root) {
  root.classList.add("admin-error-review");
  root.innerHTML = [
    '<div class="aer-toolbar" role="toolbar" aria-label="Hata düzeltme filtreleri">',
    '  <label class="aer-toolbar__label" for="aerStatusSel">Durum</label>',
    '  <select id="aerStatusSel" class="aer-select" aria-label="Durum filtresi">',
    '    <option value="pending" selected>Bekleyen</option>',
    '    <option value="approved">Onaylandı</option>',
    '    <option value="rejected">Reddedildi</option>',
    '    <option value="all">Hepsi</option>',
    '  </select>',
    '  <button type="button" id="aerRefreshBtn" class="aer-btn aer-btn--ghost" ',
    '          aria-label="Listeyi yenile">Yenile</button>',
    '  <span id="aerCount" class="aer-count" aria-live="polite"></span>',
    '</div>',
    '<div id="aerLoading" class="aer-loading" hidden role="status" aria-live="polite">',
    '  Yükleniyor…',
    '</div>',
    '<div id="aerError" class="aer-error" hidden role="alert"></div>',
    '<div id="aerEmpty" class="aer-empty" hidden>',
    '  Bu filtre için kayıt bulunamadı.',
    '</div>',
    '<ul id="aerList" class="aer-list" aria-label="Rewrite kayıtları"></ul>',
  ].join("\n");
}

/** Tek satır (li) HTML — full SQL <details> içinde collapsed. */
function renderRow(item) {
  const id = Number(item.id) || 0;
  const ec = String(item.error_class || "unknown");
  const ecLabel = ERROR_CLASS_LABELS[ec] || ec;
  const status = String(item.review_status || "pending");
  const statusLabel = STATUS_LABELS[status] || status;
  const isPending = status === "pending";

  const reviewedInfo = item.reviewed_at
    ? `<span class="aer-row__reviewed">İncelendi: ${esc(fmtDate(item.reviewed_at))}` +
      (item.reviewed_by ? ` (kullanıcı #${esc(item.reviewed_by)})` : "") +
      `</span>`
    : "";
  const noteInfo = item.review_note
    ? `<div class="aer-row__note"><strong>Not:</strong> ${esc(item.review_note)}</div>`
    : "";

  const actions = isPending
    ? [
        '<div class="aer-row__actions" role="group" aria-label="Karar">',
        `  <button type="button" class="aer-btn aer-btn--approve" `,
        `          data-action="approve" data-id="${id}" `,
        `          aria-label="Bu rewrite kaydını onayla">`,
        '    <span aria-hidden="true">✓</span> Onayla',
        '  </button>',
        `  <button type="button" class="aer-btn aer-btn--reject" `,
        `          data-action="reject-open" data-id="${id}" `,
        `          aria-label="Bu rewrite kaydını reddet">`,
        '    <span aria-hidden="true">✗</span> Reddet',
        '  </button>',
        '</div>',
        `<div class="aer-row__reject-note" data-id="${id}" hidden>`,
        `  <label class="aer-toolbar__label" for="aerNote-${id}">Reddetme notu (opsiyonel)</label>`,
        `  <textarea id="aerNote-${id}" class="aer-textarea" maxlength="2048" `,
        `            rows="2" aria-label="Reddetme notu"></textarea>`,
        '  <div class="aer-row__reject-actions">',
        `    <button type="button" class="aer-btn aer-btn--ghost" `,
        `            data-action="reject-cancel" data-id="${id}" `,
        '            aria-label="Reddetmeyi iptal et">İptal</button>',
        `    <button type="button" class="aer-btn aer-btn--reject" `,
        `            data-action="reject-confirm" data-id="${id}" `,
        '            aria-label="Reddetmeyi onayla">Reddet</button>',
        '  </div>',
        '</div>',
      ].join("\n")
    : "";

  return [
    `<li class="aer-row aer-row--${esc(status)}" data-row-id="${id}">`,
    '  <div class="aer-row__header">',
    `    <span class="aer-chip aer-chip--${esc(ec)}" aria-label="Hata sınıfı: ${esc(ecLabel)}">`,
    `      ${esc(ecLabel)}`,
    '    </span>',
    `    <span class="aer-chip aer-chip--status-${esc(status)}" aria-label="Durum: ${esc(statusLabel)}">`,
    `      ${esc(statusLabel)}`,
    '    </span>',
    `    <span class="aer-row__id">#${id}</span>`,
    `    <span class="aer-row__src">Kaynak: ${esc(item.source_id)}</span>`,
    `    <span class="aer-row__when">Oluştu: ${esc(fmtDate(item.created_at))}</span>`,
    '  </div>',
    item.question
      ? `<div class="aer-row__question"><strong>Soru:</strong> ${esc(item.question)}</div>`
      : "",
    item.error_message
      ? `<div class="aer-row__errmsg"><strong>Hata:</strong> ${esc(item.error_message)}</div>`
      : "",
    '  <details class="aer-row__sql">',
    '    <summary>Orijinal SQL</summary>',
    `    <pre class="aer-pre"><code>${esc(item.original_sql || "")}</code></pre>`,
    '  </details>',
    '  <details class="aer-row__sql">',
    '    <summary>Yeniden Üretilen SQL (LLM rewrite)</summary>',
    `    <pre class="aer-pre"><code>${esc(item.rewritten_sql || "")}</code></pre>`,
    '  </details>',
    reviewedInfo ? `<div class="aer-row__meta">${reviewedInfo}</div>` : "",
    noteInfo,
    actions,
    '</li>',
  ].filter(Boolean).join("\n");
}

/** Liste render — items boş ise empty state göster. */
function renderList(root, items) {
  const listEl = root.querySelector("#aerList");
  const emptyEl = root.querySelector("#aerEmpty");
  const countEl = root.querySelector("#aerCount");
  if (!listEl) return;
  listEl.innerHTML = "";
  const arr = Array.isArray(items) ? items : [];
  if (countEl) countEl.textContent = `${arr.length} kayıt`;
  if (!arr.length) {
    if (emptyEl) emptyEl.hidden = false;
    return;
  }
  if (emptyEl) emptyEl.hidden = true;
  listEl.insertAdjacentHTML("beforeend", arr.map(renderRow).join("\n"));
}

/** Hata gösterimi (inline + toast). */
function showError(root, message) {
  const el = root.querySelector("#aerError");
  if (el) {
    if (message) {
      el.textContent = message;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }
  if (message) toast(message, "error");
}

/** Loading toggle. */
function setLoading(root, on) {
  const el = root.querySelector("#aerLoading");
  if (el) el.hidden = !on;
}

/** GET liste. */
async function fetchList(root, statusFilter) {
  showError(root, "");
  setLoading(root, true);
  try {
    const url = `${AER_API_BASE}?status=${encodeURIComponent(statusFilter)}&limit=50`;
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const json = await res.json();
    const items = (json && json.items) || [];
    renderList(root, items);
  } catch (err) {
    renderList(root, []);
    showError(root, "Liste yüklenemedi: " + ((err && err.message) || err));
  } finally {
    setLoading(root, false);
  }
}

/** POST review (approve/reject). */
async function postReview(root, rewriteId, decision, note) {
  try {
    const res = await fetch(
      `${AER_API_BASE}/${encodeURIComponent(rewriteId)}/review`,
      {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note: note || null }),
      },
    );
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    toast(
      decision === "approved"
        ? "Rewrite onaylandı."
        : "Rewrite reddedildi.",
      "success",
    );
    // Listeyi mevcut filtre ile yeniden çek
    const sel = root.querySelector("#aerStatusSel");
    const cur = (sel && sel.value) || "pending";
    await fetchList(root, cur);
  } catch (err) {
    showError(root, "İşlem başarısız: " + ((err && err.message) || err));
  }
}

/** Reddetme bölümünü aç/kapat. */
function toggleRejectNote(root, rewriteId, open) {
  const block = root.querySelector(
    `.aer-row__reject-note[data-id="${CSS && CSS.escape ? CSS.escape(String(rewriteId)) : String(rewriteId)}"]`,
  );
  if (!block) return;
  block.hidden = !open;
  if (open) {
    const ta = block.querySelector("textarea");
    if (ta) {
      try { ta.focus(); } catch (_) { /* ignore */ }
    }
  }
}

/** Tek root için click delegation — idempotent mount sayesinde bir kere. */
function bindEvents(root) {
  // Toolbar
  const sel = root.querySelector("#aerStatusSel");
  const refreshBtn = root.querySelector("#aerRefreshBtn");
  if (sel) {
    sel.addEventListener("change", () => fetchList(root, sel.value || "pending"));
  }
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      const cur = (sel && sel.value) || "pending";
      fetchList(root, cur);
    });
  }

  // Liste click delegation
  const listEl = root.querySelector("#aerList");
  if (!listEl) return;
  listEl.addEventListener("click", (ev) => {
    const target = ev.target.closest("[data-action]");
    if (!target) return;
    const action = target.getAttribute("data-action");
    const idAttr = target.getAttribute("data-id");
    const rewriteId = Number(idAttr);
    if (!Number.isFinite(rewriteId) || rewriteId <= 0) return;

    if (action === "approve") {
      // MVP: confirm yok (HEBE kuralı). Direkt POST.
      postReview(root, rewriteId, "approved", null);
      return;
    }
    if (action === "reject-open") {
      toggleRejectNote(root, rewriteId, true);
      return;
    }
    if (action === "reject-cancel") {
      toggleRejectNote(root, rewriteId, false);
      return;
    }
    if (action === "reject-confirm") {
      const ta = root.querySelector(`#aerNote-${CSS && CSS.escape ? CSS.escape(String(rewriteId)) : String(rewriteId)}`);
      const note = ta && ta.value ? ta.value.trim() : "";
      postReview(root, rewriteId, "rejected", note);
      return;
    }
  });
}

/**
 * Public mount API.
 *
 * @param {HTMLElement} rootEl - container element (skeleton içine yazılacak).
 * @returns {Promise<void>}
 */
async function mountErrorReview(rootEl) {
  if (!rootEl || rootEl.nodeType !== 1) {
    return; // sessiz no-op — yanlış tip
  }
  // Idempotent: aynı root'a iki kere mount edilirse skeleton tek defa kurulur,
  // ama liste her çağrıda yenilenir.
  if (!rootEl[MOUNT_FLAG]) {
    buildSkeleton(rootEl);
    bindEvents(rootEl);
    Object.defineProperty(rootEl, MOUNT_FLAG, {
      value: true, enumerable: false, configurable: false, writable: false,
    });
  }
  const sel = rootEl.querySelector("#aerStatusSel");
  const statusFilter = (sel && sel.value) || "pending";
  await fetchList(rootEl, statusFilter);
}

// v3.32.0 — Bundle uyumluluğu için window'a expose et (ES export bundle'ı kırıyor).
if (typeof window !== "undefined") {
  window.mountErrorReview = mountErrorReview;
  window.AdminErrorReview = { mountErrorReview };
}
