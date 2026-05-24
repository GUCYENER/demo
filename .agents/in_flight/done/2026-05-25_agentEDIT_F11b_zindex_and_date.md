# Brief — F11b: Chart popup z-index regression + Oracle date detection

**Date:** 2026-05-25
**Agent:** `agentEDIT_F11b_zindex_and_date`
**Council:** HEBE (modal stacking + a11y) + DIONYSOS (chart heuristic accuracy)
**Plan:** code-review follow-up on F11 (no plan file; bug batch)
**Parent brief:** `.agents/in_flight/2026-05-25_agentEDIT_F11_chart_popup.md`

---

## Scope

Two bugs surfaced by code review on top of F11:

1. **MAJOR — Chart modal renders BEHIND the F9 result modal.**
   `.dsw-chart-modal { z-index: 9999 }` but
   `.dsw-result-modal-overlay { z-index: 11000 }`. Clicking "📊 Grafik"
   inside the F9 result modal opened the chart popup invisible to the user
   (it was under the F9 backdrop).

2. **MINOR — Oracle `DD-MON-YY` dates fail the date heuristic.**
   `_looksLikeDate` only matched `^\d{4}-\d{2}-\d{2}` / `^\d{4}/\d{2}/\d{2}`,
   so Oracle's default DATE-to-string output (`15-MAR-26`) was treated as
   text → first-col-is-date check failed → bar chart was picked instead of
   line chart for time-series data.

---

## Fix details

### 1) z-index bump

`frontend/assets/css/modules/_db_smart_wizard.css`:

```
.dsw-chart-modal {
    position: fixed;
    inset: 0;
    z-index: 11050;            /* was 9999 — must sit above result modal (11000) */
    ...
}
```

**Why 11050 (and not 11500 / 12000)?**
- The F9 result modal stack tops out at **11000**.
- The chart popup must beat it, but stay below any future toast/snackbar
  layer (project convention reserves the 12000+ band for transient
  notifications and the global command-palette / loading veil).
- A 50-unit gap leaves room for sub-elements of the chart modal
  (potential tooltip / context-menu portal) without forcing them into
  the notification band.
- The F9 modal is deliberately NOT torn down on chart open — the user
  can dismiss the chart with ✕/Esc and return to the table view, so the
  natural stack order is "result(11000) → chart(11050) on top".

### 2) Broadened date regex

`frontend/assets/js/modules/db_smart_chart.js → _looksLikeDate`:

```
// 1) ISO 8601 / YYYY-MM-DD / YYYY/MM/DD     e.g. 2026-05-24, 2026/05/24T12:00
// 2) Oracle DD-MON-YY(YY)                   e.g. 15-MAR-26, 15-MAR-2026, 15/Mar/2026
// 3) US MM/DD/YYYY                          e.g. 03/15/2026
// 4) TR/EU DD.MM.YYYY                       e.g. 15.03.2026
// 5) ISO-ish DD-MM-YYYY                     e.g. 15-03-2026
```

Patterns recognised now:
- `^\d{4}[-/]\d{1,2}[-/]\d{1,2}`
- `^\d{1,2}[-/\s][A-Za-z]{3,9}[-/\s]\d{2,4}$` — case-insensitive month
  abbreviation (JAN/FEB/MAR/...) or full name (January/...).
- `^\d{1,2}/\d{1,2}/\d{4}$`
- `^\d{1,2}\.\d{1,2}\.\d{4}$`
- `^\d{1,2}-\d{1,2}-\d{4}$`

Tradeoff: the EU `DD-MM-YYYY` and US `MM/DD/YYYY` ambiguity is accepted —
both pick "line chart" which is the correct behaviour for time-series.
Actual date *parsing* is delegated to the backend; this regex is only the
chart-type heuristic gate.

---

## Files changed

- `frontend/assets/css/modules/_db_smart_wizard.css` — z-index 9999 → 11050
  with a v3.36.1 F11b comment block.
- `frontend/assets/js/modules/db_smart_chart.js` — `_looksLikeDate` body
  rewritten; comment block lists supported formats.
- `frontend/dist/bundle.min.{js,css}{,.map}` — `npm run build` rebuild.

---

## Verification

- `cd frontend && npm run build` → green (CSS 438KB / JS 1108KB).
- `grep -o "dsw-chart-modal{[^}]*}" frontend/dist/bundle.min.css` →
  `z-index:11050` present, class name preserved (no esbuild mangle).
- `grep -n "_looksLikeDate\|MON" frontend/assets/js/modules/db_smart_chart.js`
  → matches at lines covering the helper + Oracle comment.
- Manual smoke (next browser session, hard-reload):
  - Open F9 → 📊 Grafik on a result with an Oracle DATE column → chart
    appears ABOVE the result modal AND picks `line` type automatically.
  - Close chart (Esc) → F9 modal still mounted underneath.

---

## Restart / Reload

- Backend: **no**.
- Frontend hard-reload (Ctrl+Shift+R): **YES, required** — both the
  minified CSS (`bundle.min.css`) and JS (`bundle.min.js`) changed.

---

## Known risks / follow-ups

- **Risk:** if the global notification layer ever drops below 12000,
  toasts could pop under the chart modal. Memorialise the
  "11050 chart < 12000 toast" invariant in the design tokens doc when
  HEBE next touches the stacking system.
- **Follow-up:** date regex still does not handle ISO with `T` and
  timezone suffix when the string is *not* prefixed by `YYYY-MM-DD`
  (rare; acceptable). RFC 2822 strings (`Tue, 15 Mar 2026 ...`) are
  also not detected — out of scope for BI result sets but worth a note.
- **Follow-up:** add a Jest/Vitest test for `_looksLikeDate` once the
  TYCHE+ARES test brief is dispatched (per memory rule, tests must be
  team-authored — not added inline by this fix).
- **Council approval pending** before either F11 or F11b move to
  `.agents/in_flight/done/`.
