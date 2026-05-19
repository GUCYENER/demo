/**
 * VYRA v3.29.6 — Learned Query Failure Queue (Admin)
 *
 * Backend (admin onaylı):
 *   GET    /api/data-sources/{source_id}/failure-queue?min_recurrence=3&limit=50
 *   POST   /api/data-sources/{source_id}/failures/{id}/approve  body: {pattern_hint?}
 *   DELETE /api/data-sources/{source_id}/failures/{id}
 *
 * Kullanım:
 *   window.FailureQueue.init('#failureQueueSection');
 */
(function () {
  "use strict";

  const state = {
    rootSel: null,
    sourceId: null,
    minRecur: 3,
    rows: [],
  };

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function authHeaders() {
    const t = localStorage.getItem("access_token");
    return t ? { Authorization: "Bearer " + t } : {};
  }

  function setLoading(on) {
    const root = $(state.rootSel);
    if (!root) return;
    const el = root.querySelector("#fqLoading");
    if (el) el.hidden = !on;
  }

  function setError(msg) {
    const root = $(state.rootSel);
    if (!root) return;
    const el = root.querySelector("#fqError");
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = "";
    } else {
      el.textContent = msg;
      el.hidden = false;
    }
  }

  async function loadSources() {
    try {
      const res = await fetch("/api/data-sources", { headers: authHeaders() });
      if (!res.ok) throw new Error("data-sources HTTP " + res.status);
      const j = await res.json();
      const list = (j && j.items) || j || [];
      const sel = $(state.rootSel).querySelector("#fqSourceSel");
      sel.innerHTML = "";
      list.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `${s.name || s.id} (#${s.id})`;
        sel.appendChild(opt);
      });
      if (list.length > 0) {
        state.sourceId = list[0].id;
        sel.value = state.sourceId;
      }
    } catch (e) {
      setError("Veri kaynakları yüklenemedi: " + (e.message || e));
    }
  }

  async function loadFailures() {
    if (!state.sourceId) return;
    setError("");
    setLoading(true);
    try {
      const url =
        `/api/data-sources/${state.sourceId}/failure-queue` +
        `?min_recurrence=${state.minRecur}&limit=50`;
      const res = await fetch(url, { headers: authHeaders() });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const j = await res.json();
      state.rows = (j && j.items) || j.failures || [];
      renderTable();
    } catch (e) {
      setError("Liste yüklenemedi: " + (e.message || e));
      state.rows = [];
      renderTable();
    } finally {
      setLoading(false);
    }
  }

  function renderTable() {
    const root = $(state.rootSel);
    if (!root) return;
    const tbody = root.querySelector("#fqTable tbody");
    const empty = root.querySelector("#fqEmpty");
    tbody.innerHTML = "";
    if (!state.rows.length) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    state.rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.dataset.fid = r.id;
      const q = r.question || "";
      const ec = r.error_class || "";
      const rc = r.recurrence_count || 0;
      const corrected = r.corrected_sql || r.pattern_hint || "";
      tr.innerHTML =
        `<td>${esc(q)}</td>` +
        `<td><span class="fq-tag fq-tag--${ec}">${esc(ec)}</span></td>` +
        `<td>${rc}</td>` +
        `<td><code class="fq-corrected">${esc((corrected || "").slice(0, 200))}</code></td>` +
        `<td>` +
        `<button class="btn btn-primary fq-btn-approve" type="button" aria-label="Onayla">Onayla</button> ` +
        `<button class="btn btn-secondary fq-btn-dismiss" type="button" aria-label="Reddet">Reddet</button>` +
        `</td>`;
      tbody.appendChild(tr);
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function approveFailure(failureId) {
    try {
      const res = await fetch(
        `/api/data-sources/${state.sourceId}/failures/${failureId}/approve`,
        {
          method: "POST",
          headers: { ...authHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
      if (!res.ok) throw new Error("HTTP " + res.status);
      await loadFailures();
    } catch (e) {
      setError("Onay başarısız: " + (e.message || e));
    }
  }

  async function dismissFailure(failureId) {
    try {
      const res = await fetch(
        `/api/data-sources/${state.sourceId}/failures/${failureId}`,
        { method: "DELETE", headers: authHeaders() },
      );
      if (!res.ok) throw new Error("HTTP " + res.status);
      await loadFailures();
    } catch (e) {
      setError("Reddetme başarısız: " + (e.message || e));
    }
  }

  function bindEvents() {
    const root = $(state.rootSel);
    if (!root) return;
    const sel = root.querySelector("#fqSourceSel");
    const minInp = root.querySelector("#fqMinRecur");
    const btn = root.querySelector("#fqRefresh");

    if (sel) {
      sel.addEventListener("change", () => {
        state.sourceId = parseInt(sel.value, 10);
        loadFailures();
      });
    }
    if (minInp) {
      minInp.addEventListener("change", () => {
        const v = parseInt(minInp.value, 10);
        state.minRecur = Number.isFinite(v) && v > 0 ? v : 3;
        loadFailures();
      });
    }
    if (btn) btn.addEventListener("click", loadFailures);

    // Event delegation for approve/dismiss buttons
    const tbody = root.querySelector("#fqTable tbody");
    if (tbody) {
      tbody.addEventListener("click", (ev) => {
        const tr = ev.target.closest("tr[data-fid]");
        if (!tr) return;
        const fid = parseInt(tr.dataset.fid, 10);
        if (ev.target.classList.contains("fq-btn-approve")) {
          approveFailure(fid);
        } else if (ev.target.classList.contains("fq-btn-dismiss")) {
          dismissFailure(fid);
        }
      });
    }
  }

  let _inited = false;
  async function init(rootSel) {
    state.rootSel = rootSel || "#failureQueueSection";
    const root = $(state.rootSel);
    if (!root) return;
    root.removeAttribute("hidden");
    if (!_inited) {
      bindEvents();
      _inited = true;
    }
    await loadSources();
    await loadFailures();
  }

  window.FailureQueue = { init };
})();
