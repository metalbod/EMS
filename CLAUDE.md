# CLAUDE.md — EMS project guide

This file is read automatically at the start of every Claude Code session
in this repo. It's the map — deep-dive details already live in `README.md`
and inline code comments; this file exists so a **fresh session with no
prior context** can get oriented fast and avoid re-discovering the same
gotchas.

## What this is

Multi-tenant HR platform (EMS = Employee Management System) for
Malaysian companies: employees, recruitment (ATS), onboarding/offboarding
checklists, L&D, leave, timesheets/projects, overtime, payroll (EPF/
SOCSO/EIS/PCB), performance management, compensation (pay grades, bonus/
commission plans, equity), benefits (enrollment, dependents, claims),
attendance (shifts, clock-in/out, geofencing, device webhooks), and
per-institution custom roles.

**Stack**: FastAPI + Postgres (Supabase) backend, vanilla JS frontend (no
framework), deployed to Fly.io. No ORM — raw SQL via a thin `db.py`
wrapper everywhere.

## Read README.md first for these (already documented in depth)

- Two-database-role RLS setup (`DATABASE_URL` vs `ADMIN_DATABASE_URL`)
- Frontend structure, Tailwind build step, asset versioning
- Async ops via Celery (payroll runs, bulk upload)
- Testing (pytest, Vitest, xdist deadlock retries)
- Alembic migration workflow
- Currency storage (`NUMERIC(12,2)`, not float)
- Row-level security / tenant isolation mechanics
- Benefits, Attendance, Leave, and Approval Workflow module internals

## Module map (routers/*.py — what exists, even if not in README yet)

| Router | Covers |
|---|---|
| `employees.py` | Employee CRUD, bulk upload, rehire, org data |
| `orgchart.py` | Org chart tree/reporting-line queries |
| `recruitment.py` | Requisitions, candidates/ATS, interviews, offers |
| `onboarding.py` | Onboarding/offboarding templates + checklists, item attachments |
| `ld.py` | Learning & Development courses/enrollments |
| `leave.py` | Leave types, applications, balances, carry-forward |
| `timesheets.py` | Timesheet entries against projects/tasks |
| `overtime.py` | Auto-detected overtime (vs. Attendance shift), leave/pay conversion |
| `projects.py` | Projects, tasks, task assignments, project managers |
| `attendance.py` | Shifts, clock-in/out, geofencing, device webhooks |
| `payroll.py` | Payroll runs, payslips, statutory calculations |
| `performance.py` | Appraisal cycles, calibration, manager review |
| `compensation_*.py` | Pay grades/bands, bonus, commission, equity, merit cycles, total rewards |
| `benefits.py` | Plan catalog, enrollment, dependents, claims, compliance |
| `locations.py`, `location_features.py`, `location_phase2.py` | Multi-location: assignments, transfers, budgets, capacity alerts |
| `approval_workflow_settings.py` | Configurable approval chains (see README) |
| `roles.py` | Per-institution custom roles (built-ins + additions like "IT Infra") |
| `assistant.py` | AI self-service chatbot (Claude Haiku) over the caller's own/team's leave, payroll, benefits, timesheet data — read-only, server-side-scoped tools, Redis-backed hourly rate limit |
| `users.py` | User accounts, role assignment |
| `institutions.py` | Tenant (company) CRUD, superadmin-only |
| `dashboard.py` | Personal To-Do widget (aggregates pending items across modules) |
| `holidays.py`, `notifications.py`, `hr_notes.py`, `audit.py`, `meta.py`, `auth.py`, `tasks.py`, `health.py`, `frontend.py` | Supporting/cross-cutting |

## Recently added (not yet in README's prose — check git log for detail)

- **Approval workflow** now also covers **Timesheet** and **Overtime**,
  supports a **Project Manager** approver type (resolved via the
  request's own project(s) — direct on Leave/Claims/Timesheet, via the
  parent timesheet on Overtime), and a per-step **alternative ("OR")
  approver** (`alt_approver_type`).
- **Overtime module** (`core/overtime.py`, `routers/overtime.py`):
  detected automatically at timesheet submission by comparing logged
  hours against the employee's resolved Attendance shift
  (`core/attendance_helpers.py`, shared with `routers/attendance.py`).
  Goes through its own approval-workflow chain; on approval, converts to
  either credited leave or a tracked pay amount per an institution-level
  setting (`institutions.overtime_conversion_mode`) — pay is
  tracking-only, not yet wired into payroll.
- **Per-institution custom roles** (`core/roles.py`'s
  `get_valid_roles`, `routers/roles.py`, Settings → Roles UI): 6 built-in
  roles are fixed; HR can add more, usable as a user's `role` and as an
  onboarding/offboarding item's `assigned_role`. Role validation lives in
  the endpoint body (needs a DB connection + inst_id), not a static
  Pydantic `field_validator`.
- **Onboarding/offboarding checklist item attachments**
  (`ob_item_attachments` table): optional proof-of-completion file
  upload per item (photo/document, ~6MB cap, base64 data URI — same
  pattern as `candidate_documents`), never required to mark an item Done.
- **Dashboard To-Do** now also surfaces pending onboarding/offboarding
  checklist items (one row per item, not an aggregate count) alongside
  the approval-workflow items.
- **Settings → Roles → Permission Matrix** (`core/permission_matrix.py`,
  `routers/roles.py`): a hand-curated, read-only reference of role access
  across ~90 actions/24 modules — not derived from the routers at
  runtime, since most gates are inline checks, not a uniform decorator.
  On top of that, `manager`/`employee`/custom-role access is now actually
  **editable per institution** via `role_permission_overrides`
  (`PUT`/`DELETE /api/roles/permission-matrix/override`) —
  `hr_manager`/`hr_admin`/`payroll_manager`/`compensation_manager` are
  permanently locked and can never be overridden. This is a deliberate
  **pilot**, wired into only 6 of `routers/employees.py`'s actions so far
  (`ENFORCED_ACTION_KEYS`) — retrofitting the other ~23 modules to call
  `has_permission()` instead of their existing `require_roles(...)`/inline
  checks is intentionally left as separate, incremental follow-up work,
  not a one-shot rewrite of the app's access control. See
  `permission_matrix.py`'s module docstring before touching either file.

## Recurring gotchas (hit more than once this project's history)

- **RLS fails closed, not open.** A table gets RLS auto-enabled by an
  `ensure_rls` event trigger the moment it's created, but with **zero**
  policies that means every query returns nothing / every insert is
  denied — not "RLS off". Every new tenant-scoped table needs an
  explicit `tenant_isolation` policy in its migration. A table with no
  `institution_id` of its own (e.g. a child table like
  `approval_workflow_steps`, `ob_item_attachments`) needs an
  EXISTS-based policy scoped through its parent.
- **`db.py`'s `Conn` wrapper translates `?` placeholders to psycopg2's
  `%s`.** Never use a raw `%` wildcard directly in a `LIKE`/`ILIKE`
  pattern string passed through `.execute()` — it breaks the
  translation (`IndexError: tuple index out of range`). Fetch rows and
  filter in Python instead, or pass the wildcard pre-built into the bind
  parameter, not the SQL string.
- **Imports are flat (`from core.deps import ...`), not `ems.`-prefixed.**
  Every router used to carry a `try: from core.X import Y / except
  ImportError: from ems.X import Y` fallback, for a second invocation mode
  (running from the *parent* of this repo, so `ems/` resolves as a
  package) that turned out to be unused by anything real — production
  (`Dockerfile`/`deploy.sh`), local preview (`.claude/launch.json`, via
  `--app-dir`), and `celery_worker.py`'s own documented usage all already
  ran the flat path. Removed in full across 34 files (139 blocks) after
  confirming this; the root `__init__.py` that made the `ems.` package
  mode possible was removed too. Don't reintroduce the dual-import
  pattern in new files — if a second invocation mode is ever genuinely
  needed again, resolve it once at process start (e.g. `sys.path`/
  `sys.modules` aliasing in `main.py`), not per-file.
- **No cron/scheduled jobs anywhere in this stack.** Anything that looks
  like it needs one (leave carry-forward expiry, attendance absence
  detection, overtime detection) is instead computed **lazily on
  read/use** or triggered by an adjacent action (timesheet submission
  triggers overtime detection, not a nightly job).
- **Tests run against a dedicated test Supabase project, not prod** —
  `TEST_DATABASE_URL`/`TEST_ADMIN_DATABASE_URL` in `.env`,
  `tests/conftest.py` swaps them in for `DATABASE_URL`/`ADMIN_DATABASE_URL`
  before anything else imports `db.py`/`main.py`. Falls back to running
  against prod if the `TEST_*` vars aren't set. When a new Alembic
  migration is added, apply it to the test project too (`alembic upgrade
  head` with `ADMIN_DATABASE_URL` env-overridden to
  `TEST_ADMIN_DATABASE_URL`) — it does **not** happen automatically,
  `deploy.sh` only migrates prod.
  - Provisioning note: the historical Alembic chain assumes the schema
    already exists (it grew out of the pre-Alembic `main.py init_db()`
    era) and is **not** currently replayable from a truly empty database —
    `20260717_0001_full_schema_ddl.py` itself contains ALTER statements
    against tables added by later migrations. The test project was
    bootstrapped by dumping prod's schema (`pg_dump --schema-only
    --no-owner --no-privileges -n public`), restoring it into the empty
    project, granting `ems_app` the same DML privileges as prod, then
    `alembic stamp head` (schema already matches head; this just writes
    the bookkeeping row). Re-provisioning a fresh test project should
    follow the same recipe, not `alembic upgrade head` from empty — that
    still fails partway through today. (`eb95a484c74a`'s `depends_on` was
    fixed to require `20260717_0001` first, which was a real, separate
    ordering bug, but doesn't make the chain fully bootstrap-clean on its
    own — a from-scratch-safe migration chain is a larger, separate
    project.)
- **`tests/conftest.py`'s `test_institution` fixture is
  session-scoped** — created once, shared by every test in one pytest
  invocation, and never cleaned up. Data your test creates (workflows,
  checklists, projects, locations) can silently become "the first/
  default one" for later tests in the same run if you don't tear it down
  explicitly. This has caused real cross-test pollution more than once
  (thousands of leftover rows, measurable query slowdowns) — always add
  teardown (a factory fixture with `yield` + cleanup, matching
  `make_test_project`/`make_test_ob_checklist`/`make_test_location`).
  Now that tests hit an isolated test project rather than prod, a leak is
  much lower-stakes, but still adds noise/slowdown to future test runs —
  keep adding teardown.
- **`get_db()`/`get_admin_db()` (`db.py`) validate a pooled connection
  before handing it out** (`_get_live_raw`, a `SELECT 1`, discarding and
  retrying on a dead one) — Supabase's pooler can silently close an
  idle-in-pool connection, which used to surface as a random
  `psycopg2.OperationalError: server closed the connection unexpectedly`
  at an unrelated call site. Genuinely transient DB flakiness (network
  blips, not stale connections) can still happen occasionally — retry the
  specific failing test in isolation before concluding something broke;
  only real `AssertionError`s indicate an actual regression.
- **`tests/test_rls_enforcement.py::test_rls_blocks_cross_institution_row_even_without_a_where_filter`
  is a known-flaky test under the full suite** (tracked, not root-caused as
  of 2026-08-10) — passes reliably alone or in a small `-n 2` subset, but
  has intermittently failed only during a full 400+ test CI run. See its
  docstring for the leading theory (possible PgBouncer transaction-pooler
  interaction) and why the obvious next diagnostic step (a direct,
  non-pooled connection) isn't practical in CI. A real regression here
  would show up as this test failing *reliably*, not just occasionally
  under full-suite load.
- **Bash tool's cwd resets between calls** — always use absolute paths
  or prefix `cd /path/to/ems &&`.
- **`fly deploy` does not run migrations on its own** — use `./deploy.sh`
  (repo root) instead of calling `fly deploy` directly; it runs `alembic
  upgrade head` against the shared DB first, then deploys, then curl-
  verifies `/` returns 200. This exists so a migration can never ship
  silently un-applied.
- **VACUUM requires the admin DB connection**, not the app's normal
  `DATABASE_URL` role (`permission denied to vacuum ..., skipping it`).
  Use `ADMIN_DATABASE_URL` via a direct `psycopg2.connect(...)` for any
  one-off `VACUUM FULL` after a large `DELETE` (a `DELETE` doesn't
  reclaim disk space on its own — a bulk cleanup can leave a table
  physically huge despite few live rows, which shows up as inflated
  query-planner costs / real slow scans until vacuumed).

## Workflow expectations for this project

- **Never commit, push, or deploy without being explicitly told to.**
  Implement → verify (tests and/or browser) → wait for an explicit
  instruction like "commit and push and deploy".
- Deploys are `./deploy.sh` (runs pending migrations, then
  `fly deploy --app ems-app`, then verifies `https://ems-app.fly.dev/`
  returns `200`).
- For any non-trivial feature request, research the current
  implementation and present a plan (and ask clarifying questions where
  the request is ambiguous) before writing code — this project's owner
  consistently prefers that over guessing.
