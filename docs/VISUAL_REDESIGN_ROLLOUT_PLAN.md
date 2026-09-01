# Visual redesign rollout plan — extending "Organic layout, Technical palette" beyond Shell + Home

**Status:** Shell + Home shipped (see the commit adopting the design brief). This
document is the plan for everything else — not started, no code changes yet.

## What shipped already

- Design tokens (`static/css/styles.css` `:root`) — surfaces, text, lines, the
  teal accent scale, status colors, Newsreader/Karla fonts, shape/shadow scale.
  Old token names (`--color-primary`, `--text-primary`, `--sidebar-*`, etc.)
  are kept as **deprecated aliases** pointing at the new tokens, specifically
  so pages outside this pass keep rendering correctly unchanged — see the
  comment block above them in `styles.css`.
- Shell: flat `--bg` canvas (gradient removed), single white content-card
  (`main.content-shell`), sidebar restyled with one neutral active/hover
  state (the old per-module "Segment Color Study" pilot — 11 pastel icon
  chips + per-group active colors — removed), new bottom-pinned account
  panel (from an earlier pass, unrelated to this redesign, left as-is).
- Home page: serif greeting header, 4 KPI tiles (Headcount / Pending
  approvals / Payroll cut-off / Open roles), pill-style dashboard tabs, and
  the To-Do queue rebuilt to the brief's row spec (avatar, title, meta line,
  one action, single accent-highlighted "most urgent" row).

**Known gap in what shipped:** the To-Do queue's richer row treatment
(avatar with real initials, employee · stage · due-date meta line) only
applies to onboarding/offboarding checklist items, which already carry
per-item employee/date data. The other 8 todo sources (leave, claims,
requisition, timesheet, ld_enrollment, overtime, resignation, pip
approvals, and the employee-document-expiry reminder) are aggregate counts
— "3 leave applications awaiting your approval" — with no single
employee/date to honestly show, so they render with the simpler
title-only + "Open" fallback the brief allows for non-urgent rows. Making
every todo source per-item (see "Phase 2" below) is what closes this gap
properly, rather than inventing a fake owner/date for an aggregate.

**Also not done:** `pay_day` is only wired into `currentUser.institution`
(the logged-in user's own institution). Superadmin viewing another
institution's Payroll cut-off KPI while inside that institution's context
still falls back to the schema default (25th) — `InstitutionResponse` /
`GET /api/institutions` doesn't carry `pay_day` today. Low-priority (a
superadmin managing an institution isn't usually the one running its
payroll), noted here rather than fixed silently.

## What's left: every other page's own hardcoded colors

Confirmed by grep, at time of writing: **27 files** (`static/js/*.js` +
`static/index.html`) use hardcoded Tailwind badge/status classes
(`bg-blue-100`, `text-emerald-700`, etc.) that don't run through the new
token system at all — the shell/Home changes don't touch them, by design,
per the scoping decision behind this pass. Two different patterns exist:

1. **Shared color-map helpers** (`static/js/core.js`'s `statusColor()` +
   per-module `*_STATUS_COLORS`/`*_BADGE_COLORS` objects — 14 files use
   this pattern: `attendance.js`, `compensation.js`, `core.js`,
   `dashboard.js`, `employees.js`, `ld.js`, `leave.js`, `notifications.js`,
   `onboarding.js`, `payroll.js`, `performance.js`, `pip.js`,
   `resignation.js`, `timesheet.js`, `users.js`). These are the easy case —
   one map object per concern, update the hex/Tailwind-class values in one
   place, everything consuming that map picks it up.
2. **Inline, one-off badge functions** not using the shared helper (e.g.
   `benefits.js`'s `claimStatusBadge()`, some of `recruitment.js`'s
   interview/offer status badges). Slightly more files to touch
   individually since there's no single map to edit.

### Recommended approach — don't try to force everything onto one accent

The brief's Section 5 ("any second accent hue... is decoration") is
written for a simpler app than this one actually is. This app's status
badges carry real semantic load across many independent lifecycles
(candidate pipeline stages, leave status, payroll run status, claim
status, appraisal status...) — collapsing all of them to teal-or-nothing
would remove information the badges exist to carry, not just decoration.
The workable interpretation, consistent with the brief's actual intent
(one brand accent, not one status color): keep semantic status colors
(success green, warning amber, danger red, etc.) as a **separate, small,
deliberately-limited palette** distinct from the teal brand accent —
teal means "this is the primary action / the app's own identity," not
"this record is in a good state." Concretely:

- Define a small `--status-*` token set (2026 palette, not the old ad hoc
  hex values scattered per file) — e.g. `--status-positive`,
  `--status-pending`, `--status-negative`, `--status-neutral` — and route
  every `*_STATUS_COLORS`/`*_BADGE_COLORS` map through those instead of
  literal Tailwind classes.
- Leave `--overdue`/`--danger` as-is (already status-only per the shipped
  tokens).
- Audit whether any of the 27 files' badges are actually acting as a
  second *brand* accent (unlikely, but check `note-type-*` in
  `styles.css` — those are still on their original hardcoded hex, never
  migrated) vs. genuinely encoding record state (the vast majority).

### Phasing

**Phase 1 — badge/status token migration (cosmetic only, no data changes).**
Introduce the `--status-*` tokens, migrate the 14 shared-helper files
first (highest leverage, one map edit reaches many call sites each), then
the smaller number of inline one-offs. Verify each module visually after
migrating it — this touches enough surface area that a single "migrate
everything then verify once" pass is a bad idea; go module by module.

**Phase 2 — make every To-Do source per-item.** Closes the gap noted
above. For each of the 8 aggregate approval types, replace the
`count_pending_for_approver` count-only query with one that returns the
underlying pending records (employee, stage/type, due or requested date),
same shape the onboarding items already use. Bigger than Phase 1 — real
backend work per approval type, not just a template change — and worth
scoping on its own rather than folding into the badge-color pass.

**Phase 3 — extend the Home-style shell treatment where it makes sense.**
The greeting-header + KPI-tile + pill-tab pattern built for Home could fit
a few other high-traffic landing pages (e.g. each module's own overview
tab) — evaluate case by case; not every page needs it, and forcing it
everywhere risks the same "simpler app than this one" mismatch noted
above.

None of these three phases is scheduled — this document exists so the
next pass has a concrete starting point instead of re-deriving scope from
scratch, matching how this project's tech-debt ledger tracks other
deferred work.
