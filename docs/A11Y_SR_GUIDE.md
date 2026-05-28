# VYRA Accessibility — Screen Reader Smoke Test Guide

> **Scope:** vyrazeus §5c.2 — A11y Derinlik Gate. Critical user flows
> get a manual screen-reader pass before merge; automated `pa11y-ci`
> covers the static rule audit (WCAG 2.2 AA), which is the other half
> of the gate.

Manual SR testing is intentionally narrow. We don't try to certify the
whole app every PR — we run the *critical flow* the PR is touching, on
*one* screen reader appropriate for the host OS, and look for the four
failure modes most likely to bite real users.

## When this guide is required

Trigger any of:

- A new modal, panel, drawer, toast pattern, or sheet
- A new form (field group with submit)
- A change to focus management — opening, closing, returning focus
- A change to live-region announcements (toasts, loading state, error
  banners)

Skip when:

- Only static CSS values changed (colours, spacing)
- Backend-only PR with no UI diff
- Non-interactive content edit (copy fix, image swap with same alt)

## Which reader to run

| Host OS | Reader | Quick-start |
|---|---|---|
| Windows | **NVDA** (free, https://www.nvaccess.org/download/) | `Insert+Down` start reading; `Esc` stop |
| macOS | **VoiceOver** (built-in) | `Cmd+F5` to toggle; `VO+A` start reading |
| Linux | **Orca** (built-in on most distros) | `Insert+Space` start; `Alt+F4` quit |

Pick one. There's no value in running all three for a single PR —
behaviour parity across SRs is a separate concern, owned by the
quarterly a11y audit, not by the PR-gate.

## Critical-flow checklists

Each list is **what to do** plus **what should happen**. If reality
doesn't match the "should," that's a finding. File it as
`a11y: <flow> — <symptom>` in the PR review or as a REFACTOR_BACKLOG
entry depending on severity (see § Severity).

### Flow A — Login

1. Tab from page load.
   - First focus should land on the email/user input, **not** on the
     "skip to content" link or the brand wordmark.
2. Tab through the form to the submit button.
   - Every interactive element should announce a role (textbox,
     button) and an accessible name (label or aria-label).
   - Required fields should announce "required."
3. Submit with empty fields.
   - Error banner should announce via `role="alert"` or
     `aria-live="assertive"`. The reader should speak it without you
     having to navigate back to it.
4. Submit with valid creds → land on home.
   - Focus should move to the new page's primary heading, not stay
     on the now-gone submit button (which would leave the reader
     orphaned).

### Flow B — Akıllı Veri Keşfi wizard (critical, complex)

1. Open the wizard ("Yeni Keşif" button).
   - Modal should announce as dialog (`role="dialog"` `aria-modal="true"`
     `aria-labelledby` pointing at the heading).
   - Initial focus should be the close button or the first interactive
     element inside — never lost on the backdrop.
2. Tab through Step 1 (Tablo Seç).
   - Each picker tile should announce its name and "selected" state.
   - The Step indicator at the top should be a `nav` landmark (not a
     decorative div) so reader users can jump back via the landmark
     list.
3. Move to Step 3 (Filtre) and click "+ Tümünü ekle".
   - The reader should announce the toast: "N kolon rapora eklendi."
     If silence, the toast lacks `role="status"` or `aria-live`.
4. Close with Esc.
   - Focus must return to the "Yeni Keşif" button you opened from.
     Anything else is broken focus management.

### Flow C — VYRA ile Sohbet Et (chat)

1. Tab to the message input.
   - Should announce role textbox + name "Mesajınızı yazın."
2. Send a message.
   - The new message bubble should be announced. Look for
     `aria-live="polite"` on the message list container; if the
     reader stays silent, that's the bug.
3. While a long answer is streaming in, hit Esc.
   - Esc should cancel the stream and announce cancellation. If it
     doesn't, low-vision users have no way to escape a runaway
     response without finding the visual cancel button.

### Flow D — Saved Reports grid

1. Tab into the grid.
   - Each card should announce: title, table source, last-run time,
     and the available actions (Open, Edit, Delete, Share).
2. Activate "Open" with Enter on a card.
   - Report detail modal should follow Flow B's dialog rules.
3. Use the search box.
   - Filtered results count should announce live ("3 sonuç").
     A silent re-render leaves SR users guessing whether typing
     worked.

## Severity (decides where the finding lands)

- **Blocker** — keyboard-only user can't complete the flow; modal
  traps focus; an essential element has no accessible name.
  → Fix before merge; commit-blocked at KAP 5c.2.
- **Major** — user can complete the flow but with significant
  friction (missing landmark, wrong heading order, missing live
  announcement).
  → Fix in the same PR if cheap, otherwise REFACTOR_BACKLOG `P1`.
- **Minor** — cosmetic SR issue (extra punctuation announced, label
  slightly awkward).
  → REFACTOR_BACKLOG `P2`/`P3`.

## What we don't ask SR users to do

To keep the smoke fast (≤ 10 min / flow), skip these on PR review:

- Full reading-order audit of long-form content — quarterly audit owns
  this.
- Colour-contrast verification with the screen reader — pa11y-ci's
  axe runner already flags WCAG 1.4.3 violations from CSS.
- Cross-browser SR comparison (NVDA-in-Firefox vs. NVDA-in-Chrome) —
  again, quarterly audit.

## References

- WCAG 2.2 AA spec — https://www.w3.org/TR/WCAG22/
- NVDA daily-use guide — https://www.nvaccess.org/files/nvda/documentation/userGuide.html
- VoiceOver getting started — https://support.apple.com/guide/voiceover/welcome/mac
- vyrazeus §5c.2 — gate that requires this checklist.
- frontend/.pa11yci.json — automated rule audit, the other half of the
  gate.
