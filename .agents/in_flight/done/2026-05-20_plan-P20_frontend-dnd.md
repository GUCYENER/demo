---
task_id: aa814c85d351c0958
status: completed
agent_type: Plan
target_files:
  - frontend/assets/js/modules/db_smart_wizard.js (READ ONLY for planning)
  - frontend/assets/js/modules/schema_picker.js (READ ONLY — DnD reference pattern)
started_at: 2026-05-20
completed_at: 2026-05-20
---

## Brief — design implementation plan for P20 (G3.4 frontend DnD + undo/redo + live preview)

You are a **planning** subagent. Do not write code — produce a step-by-step
implementation plan that another agent (or the main agent) will execute.

### Context

VYRA DB Smart Wizard, v3.30.0, branch `hira`. Backend for AST drag-drop is
already complete:
- `POST /api/db-smart/sessions/{uid}/ast/patch` — accepts op + args + render_preview flag
  - whitelisted ops: `add_column`, `remove_column`, `add_filter`, `remove_filter`,
    `modify_join`, `reorder_by`, `set_limit`, `reorder_columns`
- `POST /api/db-smart/ast/diff` — pure compute diff between two ASTs (DB-less, <10ms)
- `POST /api/db-smart/sessions/{uid}/explain` — render + EXPLAIN with 5sn TTL cache
  (cost/cardinality feedback in sub-100ms for repeat queries)
- F-021 fix: `render_preview=true` path now auto-injects RLS — preview SQL is safe.

### Goal

Wire these backend endpoints to a drag-drop frontend UX in `db_smart_wizard.js`
(Step 6 — "AST düzenle / canlı önizleme"). HEBE-Gate compliance required (a11y,
keyboard support, micro-interactions).

### Required features in the plan

1. **DnD library choice**: SortableJS or native HTML5 DnD? Justify based on
   existing project patterns (check `schema_picker.js` for prior choice).
2. **Reorderable lists**: SELECT columns (uses `reorder_columns`), ORDER BY
   (uses `reorder_by`).
3. **Add/remove filter**: chip-style UI for filters; +Add launches a small modal
   to pick column + op + value.
4. **Live preview**: after each DnD event, debounce 250ms, then call `/ast/patch
   render_preview=true`, render returned SQL in a syntax-highlighted box.
5. **Cost rozeti (badge)**: after each AST mutation, call `/explain` and show
   estimated rows + cost as a colored badge (green <10k, yellow <1M, red >=1M).
   Cache hit indicator (small ⚡ icon) when `cached:true`.
6. **Undo/redo**: keep a stack of AST snapshots (max 20). Ctrl+Z / Ctrl+Y key
   bindings. Use `/ast/diff` to display "you changed N columns / M filters"
   between snapshots (toast).
7. **A11y**: every DnD list must have ARIA-grabbed/ARIA-dropped announcements,
   keyboard alternatives (arrow keys + Space to grab/drop), focus-visible
   indicators, escape-to-cancel.

### Deliverables (your output)

Write a detailed plan to `d:\demo_vyra\.agents\in_flight\2026-05-20_plan-P20_frontend-dnd.md`
(this file — append a `## Plan` section at the bottom). Plan must include:

- Files to create/edit (paths + rough line budget)
- Module/function structure (function names, responsibilities)
- API contract details (request/response shapes for each endpoint call)
- DnD library decision + justification
- HEBE-Gate checklist mapping (a11y items)
- Test plan: at minimum, manual smoke checklist for keyboard nav + screen reader
- Suggested split into parallel sub-tasks (which parts can be done by separate agents
  in parallel without conflict?)

### Rules
- Do NOT write JS code. Only the plan.
- Do NOT touch any file other than this brief md.
- Read `db_smart_wizard.js` and `schema_picker.js` to understand patterns.
- When you finish, update this md's `status` field to `completed`.

---

## Plan

> Plan ajanı strict read-only harness'tan dolayı Edit/Write yapamadı; içerik
> ZEUS tarafından buraya işlendi.

### 0. Repository reconnaissance summary

- `frontend/assets/js/modules/schema_picker.js` — native HTML5 DnD (`draggable="true"`, `dragstart`/`dragover`/`drop`); paralel klavye alt (ArrowUp/Down + Enter + Delete + Escape); `role="listbox"` + `role="option"`; `aria-live="polite"` status region; CSS variables; focus visual via class. Harici DnD kütüphanesi YOK.
- `frontend/assets/js/modules/query_builder.js` — yine native HTML5 DnD; `aria-grabbed`/`aria-pressed` chip'leri, Space-to-grab/drop, ArrowUp/Down to reorder, Enter to add, Escape to cancel grab; `aria-live` polite via `.qb-live` span. P20'nin ihtiyaçlarına en yakın analog.
- `frontend/assets/js/modules/db_smart_wizard.js` — mevcut 5-step wizard (Step 4 = preview). Mevcut yardımcılar: `_fetchJson` (Bearer auth), `_notify` toast w/ aria-live fallback, `_escape`, `_setBusy`, `_setStep` (tablist a11y), `_onPanelKeydown` Esc handler, return-focus pattern, idempotent `_bound` flags. Step 4 şu an `POST /sessions/{uid}/preview` çağırıp SQL'i `<pre>` içine yazıyor. P20 Step 4'ü interaktif AST editör ile değiştirir/genişletir.
- `frontend/home.html` 811–841 mevcut wizard markup'ı içerir.
- Grep doğrulaması: **`Sortable` / `sortablejs` import YOK**. 6 modül native HTML5 DnD kullanıyor.
- Backend API'ler (`app/api/routes/db_smart_api.py`) doğrulandı: `/ast/patch`, `/ast/diff`, `/sessions/{uid}/explain` (5s TTL cache, F-021 RLS inject `render_preview=true` ile).

### 1. DnD library decision

**Native HTML5 Drag-and-Drop API + klavye alternatifleri. SortableJS EKLENMEZ.**

Gerekçe:
1. **Proje tutarlılığı** — 6 modül zaten native DnD. SortableJS HEBE tutarlılığını bozar.
2. **Sıfır bundle ağırlığı** — yeni `<script>`/CDN/SBOM/CSP yok.
3. **A11y zaten elle çözülmüş** — `aria-grabbed`/`aria-pressed` + Space/Arrow/Enter/Escape pattern mevcut, SortableJS stock klavye desteğinden iyi.
4. **Touch kapsam dışı** — VYRA masaüstü L1 console.
5. **Performans** — ≤20 SELECT col, ≤10 ORDER BY, ≤10 filter chip; küçük listeler.

Trade-off: native DnD'de insert-between manuel `dragover.clientY` + `getBoundingClientRect()` ile yapılır — `query_builder.js` zaten gösteriyor.

### 2. Files to create / edit (paths + line budget)

| Path | Action | Approx LOC |
|---|---|---|
| `frontend/assets/js/modules/db_smart_wizard.js` | edit — Step 4 entry hook + state.lastAst | +280 / -10 |
| `frontend/assets/js/modules/db_smart_ast_editor.js` | new — AST editör controller (mount/unmount, DnD, a11y) | ~520 |
| `frontend/assets/js/modules/db_smart_ast_history.js` | new — undo/redo stack + `/ast/diff` toast (Agent B için bağımsız dosya) | ~180 |
| `frontend/assets/js/modules/db_smart_filter_modal.js` | new — küçük modal (column/op/value) | ~220 |
| `frontend/assets/css/modules/_db_smart_wizard.css` | new — `.dsw-ast-*` chip/drop-indicator/badge/modal/focus | ~260 |
| `frontend/home.html` | edit — CSS link + 3 script tag + `#dswStep4` slot id'leri | +60 / -3 |
| `tests/manual/p20_smoke.md` | new — klavye + SR smoke checklist | ~80 |

Toplam: ~980 JS LOC + ~260 CSS + 60 HTML. HEBE per-file 600 LOC soft cap'i aşılmıyor.

### 3. Module / function structure

#### 3.1 `db_smart_ast_editor.js` — `window.DbSmartAstEditor`

State (closure-scoped):
```
{
  sessionUid, dialect, ast,
  history: [],           // [{ast, label, ts}]
  cursor: -1,
  HISTORY_MAX: 20,
  debounceTimer, explainAbort, patchAbort,
  rootEl, grabbed,       // {list,index}
  filterModalOpen: false,
}
```

Public API:
| Function | Sorumluluk |
|---|---|
| `mount(rootEl, {sessionUid, dialect, ast})` | Step 4 entry; DOM wire + global Ctrl+Z/Y bind + history seed + ilk preview/explain |
| `unmount()` | In-flight fetch abort + global key unbind + DOM temizle |
| `getAst()` / `getHistory()` | Test hook |

Internal:
- `_render()` — idempotent tam re-render
- `_renderSelectList()` — `<ul role="list">` + `<li role="listitem" draggable="true" tabindex="0" aria-grabbed="false">`
- `_renderOrderList()` — aynı şema + ASC/DESC toggle
- `_renderFilterChips()` — `<button class="dsw-ast-chip" aria-label="…">` + `×` remove_filter; `+Ekle` modal aç
- `_attachDnd(listEl, listKey)` — native pattern (dragstart/over/leave/drop/end), `clientY` ile target index, `.dsw-drop-indicator`
- `_attachKeyboardReorder(listEl, listKey)` — Space=grab toggle, Arrow=move (grabbed), Enter=drop, Escape=cancel
- `_announce(msg)` — `#dswAstLive` aria-live polite
- `_applyPatch(op, args, {optimistic})` — snapshot push → optimistic mutate → debounced `/ast/patch render_preview=true` → server AST ile değiştir → `_refreshExplain()`. Hata: rollback + red toast.
- `_debouncedPatch(op, args)` — 250ms trailing, per-op coalescing
- `_refreshExplain()` — `POST /sessions/{uid}/explain` → badge (green <1e4 / yellow <1e6 / red ≥1e6) + ⚡ cached, AbortController
- `_pushHistory(prevAst, label)` — cursor truncate → push (max 20)
- `undo()` / `redo()` — client-side AST mirror; whitelist'te ters op varsa (add_column/remove_column) onu kullan, reorder gibi non-trivial için target AST'i yeniden replay. **Önemli not**: server state ancak bir sonraki gerçek patch'te sync olur — kullanıcı undone state'te kalırken navigate ederse divergence. Mitigation belgelenmeli.
- `_diffToast(fromAst, toAst)` — `POST /ast/diff` → `summary.changed_sections` → Türkçe toast
- `_onGlobalKey(e)` — `#dbSmartWizardPanel`'da Ctrl/Meta+Z=undo, Ctrl/Meta+Y or Shift+Z=redo; input/textarea içindeyken hijack yok
- `_openFilterModal()` — `await window.DbSmartFilterModal.open({columns})` → `add_filter` patch

#### 3.2 `db_smart_ast_history.js` — `window.DbSmartAstHistory`

Bağımsız dosya (Agent A/B merge çakışmasını engellemek için). Public: `push(ast, label)`, `undo()→{ast, label}`, `redo()→{ast, label}`, `canUndo()`, `canRedo()`, `clear()`. State internal — A modülü dependency injection ile alır.

#### 3.3 `db_smart_filter_modal.js` — `window.DbSmartFilterModal`

| Function | Sorumluluk |
|---|---|
| `open({columns, dialect}) → Promise<spec\|null>` | Lazy mount, focus first field, Esc cancel, focus return |
| `_ensureModal()` | `schema_picker.js`'in `ensureModal()` pattern'i — `role="dialog" aria-modal="true" aria-labelledby"` + backdrop + focus trap |
| `_validate(spec)` | Op whitelist (`=, !=, <, <=, >, >=, LIKE, ILIKE, IS NULL, IS NOT NULL, IN`), value empty check unless IS [NOT] NULL |
| `close(result)` | Promise resolve + caller'a focus return |

#### 3.4 `db_smart_wizard.js` — diffs

- Top: `let _astEditor = null;`
- `_state.lastAst` getter/setter
- `_onStepEnter(4)`: AST varsa `_astEditor.mount(...)`, yoksa legacy `_loadPreview()` fallback
- `_setStep` / `_closeWizard`: step 4'ten çıkarken `_astEditor.unmount()`

### 4. API contract details

#### 4.1 `/sessions/{uid}/ast/patch`

Request: `{op, args, render_preview, dialect?}`

Per-op args:
| op | args |
|---|---|
| add_column | `{expr, alias?}` |
| remove_column | `{index}` veya `{alias}` |
| add_filter | `{expr, op, value}` |
| remove_filter | `{index}` |
| modify_join | `{alias, kind}` |
| reorder_by | `{from, to}` |
| reorder_columns | `{from, to}` |
| set_limit | `{limit}` (server clamps 10M) |

Response: `{ast, sql?, binds?, dialect?}`

Errors:
- 400 → unknown op / arg / whitelist reject → kırmızı toast + rollback
- 404 → session/RLS → wizard kapat + re-open prompt
- 409 → AST init edilmemiş → inline "Önce Adım 3'ü tamamlayın"

#### 4.2 `/ast/diff`

Request: `{from_ast, to_ast}`

Response (toast için): `{columns:{added,removed,reordered}, filters:{added,removed}, joins:{added,removed,modified}, order_by, limit, offset, from, summary:{total_changes, changed_sections:[…]}}`

Toast formatı (TR): `"N kolon eklendi, M filtre kaldırıldı, sıralama değişti"` — non-empty section'lardan parça parça. Fallback `${total_changes} değişiklik geri alındı`.

#### 4.3 `/sessions/{uid}/explain`

Request: `{ast, dialect}`

Response: `{sql, dialect, explain:{total_cost?}, streaming_strategy, cached}`

Badge mapping: `explain.total_cost` proxy olarak — green <1e4 / yellow <1e6 / red ≥1e6. `explain` boş → gri "?" title `"EXPLAIN unavailable"`. `cached:true` → ⚡ glyph aria-label `"önbellekten (5sn TTL)"`. Streaming strategy ikincil etiket (TR: tek istek / cursor akışı / SSE chunk).

### 5. HEBE-Gate a11y checklist mapping

| HEBE item | Implementation hook |
|---|---|
| Outer region | `#dswStep4` retains `role="tabpanel"`, inner `role="region" aria-label="AST düzenleyici"` |
| List/Item rolleri | `role="list"` + `role="listitem" tabindex="0"` |
| `aria-grabbed` | dragstart/end + Space-grab; ARIA 1.1'de deprecated ama `query_builder.js` ile parity — ek olarak `aria-pressed` toggleable handle'da |
| Keyboard | Space=grab/drop, Arrow=move (grabbed) / focus-move (else), Enter=add, Delete=remove, Escape=cancel grab |
| Focus-visible | `:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px }` |
| Escape | Önce: aktif grab → cancel only; açık modal → close only; else wizard kapat. `stopPropagation()` |
| `aria-live` polite | `#dswAstLive` `<span class="sr-only">` — `_announce` ile |
| Badge `aria-label` | `"Tahmini maliyet 1.2 milyon, yüksek, önbellekten"` |
| Undo/Redo butonları | `aria-keyshortcuts="Control+Z"`, `disabled` + `aria-disabled` |
| Toast | `window.showToast` zaten polite |
| Modal focus trap | `schema_picker.js` pattern: first focus, Tab cycle, Esc, return |
| Return-focus | Unmount'ta önceki focused element'e |
| Reduced motion | `@media (prefers-reduced-motion: no-preference)` ile sarılı |
| Contrast | `--color-success/warning/danger` zaten AA |
| Touch | Kapsam dışı (modül header'da belgelendi) |

### 6. Manual smoke test plan

`tests/manual/p20_smoke.md` — Chrome+Firefox, NVDA (Win) / VoiceOver (Mac).

**Pre-cond:** logged in, Step 4'te AST var (Step 1-3 tamamlanmış).

#### Klavye-only (fare yasak)
1. Tab → Step 4 region; ilk SELECT item; SR: "Müşteri adı, sıra 1, seçenek 1/4, listede tutulabilir"
2. Space → `aria-grabbed=true`; SR "tutuldu"; visual highlight
3. ArrowDown ×2 → item move; SR "Müşteri adı 3. sıraya taşındı"
4. Enter → drop confirm; 250ms debounce; SR "kolon sırası güncellendi"; badge ~200ms içinde
5. Mid-grab Escape → cancel; original restore; SR "geri alındı"
6. Tab → ORDER BY list, 2-5 tekrar
7. Tab → filter chip; Delete → kaldır; toast "1 filtre kaldırıldı"
8. Tab → +Ekle; Enter → modal; first field focus; SR "Filtre ekle, kolon seç"; fill + Enter → chip; focus +Ekle'ye döner
9. Ctrl+Z → toast "1 filtre geri alındı"; chip restore
10. Ctrl+Y → toast "1 filtre yeniden eklendi"
11. Grab/modal dışında Escape → wizard kapat; focus opener'a

#### Screen reader specifics
- Drop indicator SR focus çalmaz (`aria-hidden="true"`)
- Cost badge tek labelled element
- Live region burst'ler son-yazma (last-write-wins polite)

#### Network/error
- `/ast/patch` block (devtools offline) → optimistic move → rollback animasyonu + red toast "Sunucu hatası — değişiklik geri alındı"
- 5 hızlı reorder → tek `/ast/patch` (debounce verify)
- Aynı AST iki kez patch → ikinci `/explain` ⚡ (`cached:true`)

#### Acceptance gates
- Lighthouse a11y ≥95
- axe-core devtools → 0 violations (editor mounted, modal open, mid-grab)
- Keyboard-only Step 1→4→submit hatasız

### 7. Suggested parallel sub-task split (4 ajan)

Dosya sahipliği disjoint:

| Sub-task | Owner | Touches |
|---|---|---|
| **A. Core editor + DnD + a11y** | Agent-A | `db_smart_ast_editor.js` (new ~520 LOC) — `mount`, `_render*`, `_attachDnd`, `_attachKeyboardReorder`, `_announce` |
| **B. History + diff toast + cost badge** | Agent-B | `db_smart_ast_history.js` (new ~180 LOC) + editor'a `_applyPatch/_debouncedPatch/_refreshExplain/undo/redo/_diffToast/_onGlobalKey` ekler — **DİKKAT**: B'nin editor edit'i A ile çakışır; bunu önlemek için B yalnızca history modülünü yazar, A ise B'yi import edip kullanır. Contract: A define `_applyPatch` SHELL, B export `Window.DbSmartAstHistory` (push/undo/redo) |
| **C. Filter modal + CSS + HTML** | Agent-C | `db_smart_filter_modal.js` (new), `_db_smart_wizard.css` (new), `home.html` (#dswStep4 + link/script tag'ler) |
| **D. Wizard integration + smoke doc** | Agent-D | `db_smart_wizard.js` (small surgical edit — _onStepEnter/_setStep mount/unmount) + `tests/manual/p20_smoke.md` (new). En son merge — A/B/C API yüzeyleri stabilize olduktan sonra |

2 ajana sıkıştırılırsa: **A+C** (UI surface) ve **B+D** (state + integration).

### 8. Critical Files for Implementation

- `d:\demo_vyra\frontend\assets\js\modules\db_smart_wizard.js`
- `d:\demo_vyra\frontend\assets\js\modules\schema_picker.js` (modal/DnD reference)
- `d:\demo_vyra\frontend\assets\js\modules\query_builder.js` (chip + klavye a11y reference)
- `d:\demo_vyra\app\api\routes\db_smart_api.py` (API contract source of truth)
- `d:\demo_vyra\frontend\home.html` (markup mount points lines 811-841)

---

## Özet (ZEUS)

- **DnD kararı**: Native HTML5, SortableJS YOK (6 modül zaten native, HEBE tutarlılığı, sıfır bundle, klavye a11y elle çözülmüş, touch kapsam dışı)
- **4 paralel ajan**: A (core editor) · B (history bağımsız dosya) · C (modal+CSS+HTML) · D (wizard entegrasyon + smoke doc, en son merge)
- **Çakışma riski**: B history'yi ayrı dosyada yazarak A ile çakışmayı sıfırladık

