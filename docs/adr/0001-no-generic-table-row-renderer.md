# 0001 — No generic table/row-rendering module

## Status

Accepted (2026-08-19)

## Context

An architecture review (`/improve-codebase-architecture`) flagged that every
page in `static/js/*.js` hand-builds its own HTML for table rows and list
cards via template-literal `.map(...).join('')` calls — 112 occurrences
across 21 files. The review's original framing (Candidate E, "every page
hand-builds its own HTML") suggested this might be a shallow-module problem
worth deepening into one shared row/table-rendering interface.

Before designing anything, we surveyed real call sites (employees table,
payroll payslip table, compensation's merit/bonus/commission tables,
projects table) and found the codebase already contains a directly relevant
prior deepening: `static/js/list-state.js`'s `createListState()`. Its own
docstring is explicit about where it drew the line:

> "It owns sort/page state and the render-time work (sorting, clamping the
> page, updating sort arrows) but NOT the DOM row markup or data fetching —
> callers still own `renderEmpTable()`/`renderInstTable()` as the seam where
> their own row template lives."

That decision was made narrowly and deliberately: the sort/paginate
bookkeeping *is* uniform enough to share (same shape everywhere — a sort
key, a direction, a page, a page size), but the row markup is not. Looking
at real examples confirms this:

- `employees.js`'s table renders an avatar-initials badge, responsive
  hidden columns per breakpoint, and a status badge.
- `payroll.js`'s payslip table has an `hourly ? ... : ...` conditional cell
  shape depending on salary type.
- `compensation.js`'s tables embed inline `onclick` handlers that open
  different modals per row, with per-row conditional action buttons based
  on approval status.
- `timesheet.js`'s project table has a fixed, JS-array-driven column set
  with click-to-sort headers built from that same array.

The variation is real, not incidental — it reflects genuine per-module
differences in what a row needs to show and do, not copy-paste drift that
happened to diverge. A generic `renderTable(rows, columns)` interface would
need enough escape hatches (custom cell renderers, conditional columns,
per-row event handlers, nested sub-content) to cover these cases, at which
point the interface becomes nearly as complex as what it replaces — a
shallow module, not a deep one. See `.claude/skills/codebase-design/` for
the deep-vs-shallow vocabulary this review used throughout.

## Decision

Do not build a generic table/row-rendering module. Each page keeps owning
its own row template as the seam where its formatting, conditionals, and
event wiring live — this was already the codebase's own conclusion via
`list-state.js`, and nothing found in this review contradicts it.

Instead, we closed the one real, narrow gap this review did surface:
`list-state.js`'s own rollout was incomplete. `createListState()` existed
but only 2 of the ~20 list-rendering modules (`employees.js`,
`institutions.js`) used it. Of the other candidates surveyed
(`timesheet.js`'s project list, `recruitment.js`'s candidate list), only
`timesheet.js`'s was a genuine fit — an in-memory array with client-side
sort, the exact shape `createListState()` already models. `recruitment.js`'s
candidate sort is server-driven (`sort_by`/`sort_dir` query params against
the API), a different shape entirely; forcing it onto `createListState()`
would be new scope, not adoption, so it was left alone.

`timesheet.js`'s `projectSortKey`/`projectSortDir` module-level variables
and hand-rolled comparator were replaced with
`createListState({ sortKey: 'name', pageSize: 10000 })` — used sort-only
(no pagination UI exists on that page) by setting `pageSize` above any
realistic project count.

## Consequences

- A future architecture review should not re-propose a generic
  table/row-rendering module without new evidence — e.g., a *new* class of
  duplication that's actually uniform in shape, not just frequent in count.
  Frequency alone (112 call sites) is not sufficient; the deletion test
  here shows the complexity would resurface as configuration complexity in
  the generic renderer's parameters, not disappear.
- If a genuinely uniform sub-pattern is found later (e.g., a specific kind
  of status-badge rendering, already identified separately as its own
  candidate in this review but not yet acted on), it should be evaluated
  and scoped on its own — this ADR only closes the door on a *generic*
  row/table renderer, not on every future rendering-related deepening.
- `recruitment.js`'s candidate list remains on its own hand-rolled,
  server-driven sort. If it's ever worth sharing, it would need
  `createListState()` (or a sibling module) to grow support for
  server-driven sort dispatch — a real design change, not a drop-in
  adoption, and out of scope here.
