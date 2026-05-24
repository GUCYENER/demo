# Brief — F11: Akıllı Keşfi Grafik Popup (DbSmartChart)

**Date:** 2026-05-25 (retroactively authored 2026-05-25 evening after F11b code review caught the missing brief)
**Agent:** `agentEDIT_F11_chart_popup`
**Council:** HEBE (modal/a11y gate) + HERMES (i18n surface) + DIONYSOS (chart UX + heuristic)
**Plan:** `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md` — Deliverable F11

> **Retroactive note:** F11 was initially dispatched without a written brief. Per
> the memory rule "Brief done/ move requires council approval", this file is
> authored after-the-fact to capture the actual delivered surface. The
> z-index regression fix and the date-regex broadening that landed in F11b are
> consolidated into the "Files changed" and "Verification" sections below so
> the combined feature has a single auditable brief.

---

## Scope

Add a self-contained chart popup module (`DbSmartChart`) that the F9 result
modal can launch via the "📊 Grafik" button. The popup picks an appropriate
Chart.js visualization (bar / line / pie / multi-series) from a heuristic over
the columns/rows payload, lets the user switch chart type, and closes cleanly
without unmounting the F9 result modal underneath (so the user can pop back to
the table view).

**Out of scope:**
- Server-side chart rendering or export — client-only Chart.js.
- Persisted chart configuration on saved reports (F10 owns saved-report
  metadata; chart type selection is session-local).
- Internationalisation beyond Turkish labels (HERMES follow-up).

---

## Deliverable summary

1. **New JS module:** `frontend/assets/js/modules/db_smart_chart.js`
   - Exposes `window.DbSmartChart.open({columns, rows, suggestedType?})`
     and `window.DbSmartChart.close()`.
   - Owns its own modal DOM (lazily mounted at first `open()` call,
     reused thereafter; chart instance destroyed on close).
   - Heuristic for `suggestedType`:
     - 0 rows → `empty` (friendly fallback message).
     - 2 cols, first text + second numeric + distinct ≤ 6 → `pie`.
     - 2 cols, first date/datetime + second numeric → `line`.
     - 2 cols, first text + second numeric → `bar`.
     - > 2 cols with ≥ 2 numeric columns → multi-series `bar` (or `line` if
       first column is a date).
     - Otherwise → `unsupported` (table-only message).
   - Helpers `_looksLikeNumeric`, `_looksLikeDate`, `_looksLikeTextOrEmpty`,
     `_coerceNumber`. The date helper recognises ISO 8601 / `YYYY-MM-DD`
     / `YYYY/MM/DD` and, after F11b, also Oracle `DD-MON-YY(YY)`, US
     `MM/DD/YYYY`, TR/EU `DD.MM.YYYY`, and `DD-MM-YYYY`.
   - 8-colour palette with alpha variant for fills.
   - Focus capture + return-focus; Esc closes; overlay click closes.

2. **Bundle integration:** `frontend/build.mjs` was already wiring the
   module into the IIFE umbrella; Chart.js UMD is included alongside.
   No new dependency added at this step (Chart.js was bundled earlier).

3. **F9 hook:** `frontend/assets/js/modules/db_smart_wizard.js` —
   "📊 Grafik" action of `_openResultModal` calls
   `window.DbSmartChart.open({columns, rows})` when present; otherwise
   it emits a Turkish "modül hazırlanıyor" toast.

4. **CSS:** `frontend/assets/css/modules/_db_smart_wizard.css` — block
   beginning at `/* v3.36.0 F11 — Akıllı Keşfi Grafik Popup */`. After
   F11b, `.dsw-chart-modal` carries `z-index: 11050` so it renders above
   `.dsw-result-modal-overlay` (z-index 11000); F9 modal is *not* torn
   down on chart open.

---

## Files changed (F11 + F11b consolidated)

- `frontend/assets/js/modules/db_smart_chart.js` — new module (~430 LOC),
  including the broadened `_looksLikeDate` regex from F11b.
- `frontend/assets/js/modules/db_smart_wizard.js` — invoke
  `window.DbSmartChart.open(...)` from the result modal's chart button.
- `frontend/assets/css/modules/_db_smart_wizard.css` — `.dsw-chart-modal`,
  `.dsw-chart-modal__backdrop`, `.dsw-chart-modal__dialog`,
  `.dsw-chart-modal__header`, `.dsw-chart-modal__title`,
  `.dsw-chart-modal__close`, `.dsw-chart-modal__toolbar`,
  `.dsw-chart-modal__canvas-wrap`, `.dsw-chart-modal__fallback`.
  z-index updated from 9999 → 11050 in F11b.
- `frontend/build.mjs` — Chart.js UMD already declared; no change.
- `frontend/dist/bundle.min.{js,css}{,.map}` — rebuild artefacts.

---

## Verification

- `cd frontend && npm run build` — green, CSS 438KB / JS 1108KB.
- `grep -o "dsw-chart-modal{[^}]*}" frontend/dist/bundle.min.css` →
  contains `z-index:11050`.
- `grep -n "_looksLikeDate\|MON" frontend/assets/js/modules/db_smart_chart.js`
  → confirms the broadened regex block (Oracle, US, TR variants).
- Manual smoke (deferred to next browser session, hard-reload required):
  open F9 result modal, click 📊 Grafik on an Oracle DATE column → expects
  line chart with x-axis dates rendered above the result modal, ✕/Esc
  returns to the result modal intact.

---

## Restart / Reload

- Backend: **no** (pure frontend module).
- Frontend hard-reload (Ctrl+Shift+R): **yes** — required to drop the
  cached `bundle.min.js` / `bundle.min.css`.

---

## Known follow-ups

- **TR i18n:** all user-facing strings hard-coded Turkish. Move to HERMES'
  i18n table when the dictionary layer lands.
- **Large dataset warning:** no row-cap toast yet; > 5k row payloads will
  hammer Chart.js. DIONYSOS to add a "veri seti büyük, ilk N satır
  gösterildi" banner.
- **Retroactive brief:** this file documents a feature that shipped without
  a pre-implementation brief. Going forward F-tier dispatches must author
  the brief BEFORE landing code; council to confirm.
- **F11b open items:** see sibling brief `2026-05-25_agentEDIT_F11b_zindex_and_date.md`.
