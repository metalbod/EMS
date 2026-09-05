# Visual redesign rollout — "Organic layout, Technical palette"

**Status: shipped in full.** Shell + Home landed first; Phases 1-3 below
(badge/status tokens, per-item To-Do, KPI-tile shell extension) landed
together in `d9e3743` ("Execute visual redesign rollout plan Phases
1-3"). This document is now a record of what changed and why, plus the
handful of gaps that were deliberately left open — not a pending plan.

## Shell + Home (first pass)

- Design tokens (`static/css/styles.css` `:root`) — surfaces, text,
  lines, the teal accent scale, status colors, Newsreader/Karla fonts,
  shape/shadow scale. Old token names (`--color-primary`, `--text-primary`,
  `--sidebar-*`, etc.) are kept as **deprecated aliases** pointing at the
  new tokens, so any code path not touched by this redesign keeps
  rendering correctly unchanged — see the comment block above them in
  `styles.css`. Still present as of this writing; nothing has needed them
  removed.
- Shell: flat `--bg` canvas (gradient removed), single white content-card
  (`main.content-shell`), sidebar restyled with one neutral active/hover
  state (the old per-module "Segment Color Study" pilot — 11 pastel icon
  chips + per-group active colors — removed), bottom-pinned account panel
  (from an earlier, unrelated pass).
- Home page: serif greeting header, 4 KPI tiles (Headcount / Pending
  approvals / Payroll cut-off / Open roles), pill-style dashboard tabs,
  and the To-Do queue rebuilt to the brief's row spec (avatar, title,
  meta line, one action, single accent-highlighted "most urgent" row).

## Phases 1-3 (`d9e3743`)

**Phase 1 — badge/status token migration.** Introduced the `--status-*`
token set in `styles.css` (`positive` / `pending` / `negative` /
`neutral` / `info` / `special`, each with a `-soft` background pair) and
migrated every genuine status/lifecycle badge across the app onto them:
attendance, compensation, ld, leave, notifications, payroll, performance,
pip, resignation, timesheet, recruitment, benefits, dashboard, employees,
institutions, users, employee-documents, onboarding, and the shared
`core.js` helper they all route through. Categorical/identity maps
(roles, employment types, plan categories, etc.) were deliberately left
on their own values — they encode identity, not lifecycle state, so
forcing them onto the status palette would have been the wrong call, not
a migration gap.

**Phase 2 — every To-Do source is now per-item.** `count_pending_for_approver`
(`core/approval_workflow.py`) became `pending_rows_for_approver`, same
eligibility logic but returning the underlying rows instead of a count;
a new `_approval_row_detail` (`routers/dashboard.py`) resolves
employee/stage/due-date per row for all 8 approval types (leave, claims,
requisition, timesheet, ld_enrollment, overtime, resignation, pip). The
Home To-Do queue now renders one real row per pending request — same
avatar/title/meta shape the onboarding checklist items already used —
instead of an aggregate "N items awaiting approval" count. This closes
the gap the first pass had left open.

**Phase 3 — KPI-tile shell extended to more dashboard tabs.** The
Workforce, Recruitment, and Compensation & Benefits dashboard tabs'
stat-tile grids moved off the old pastel `bg-{color}-50` cards onto the
`.kpi-tile`/`.kpi-tile-accent` system built for Home's General tab,
closing the visual inconsistency between tabs sharing one tab bar. Not
every tab got this treatment — evaluated case by case, per the original
plan's own caution against forcing the Home layout everywhere.

## Known gaps (still open, not regressions)

- **`note-type-*` classes** (`static/css/styles.css`, HR notes'
  general/disciplinary/performance/warning/commendation badges) are still
  on their original hardcoded hex values, never migrated onto
  `--status-*`. Flagged during Phase 1's own audit and knowingly deferred
  — small, low-traffic surface, not worth blocking the rest of the pass.
- **`pay_day` superadmin gap**: only wired into `currentUser.institution`
  (the logged-in user's own institution). A superadmin viewing another
  institution's Payroll cut-off KPI while inside that institution's
  context still falls back to the schema default (25th) —
  `InstitutionResponse` / `GET /api/institutions` doesn't carry `pay_day`
  today. Low-priority (a superadmin managing an institution isn't usually
  the one running its payroll), noted rather than fixed silently.
- **Deprecated token aliases** (`--color-primary`, `--sidebar-*`, etc.)
  are unused as far as the migrated call sites go, but were never audited
  for removal — some other file may still reference them directly.
  Removing them is a small, separate cleanup, not attempted here.
