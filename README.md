# EMS — Employee Management System

Multi-tenant HR platform: employees, recruitment, onboarding/offboarding
checklists, L&D, leave, timesheets/projects/overtime, payroll (Malaysia
EPF/SOCSO/EIS/PCB), performance management, compensation (pay grades,
bonus/commission plans, equity grants), benefits (enrollment, dependents,
claims, compliance reporting), attendance (shifts, clock-in/out,
geofencing, device integrations), and per-institution custom roles.

New to this codebase? Read `CLAUDE.md` first — it's a map of every
module and the gotchas that have bitten this project more than once.

FastAPI + Postgres (Supabase) backend, vanilla JS frontend, deployed to Fly.io.

## Setup

Use the exact Python version pinned in `.python-version` (matches CI and
the Docker deployment's `python:3.11-slim`) — `psycopg2-binary`'s exact
pinned version has no prebuilt wheel for older/unusual Python builds
(e.g. macOS system Python 3.9), which silently masks dependency-version
drift between local runs and what's actually deployed if you skip this.

```bash
pyenv install   # reads .python-version automatically, if using pyenv
python3 -m venv .venv
source .venv/bin/activate

cp .env.example .env   # fill in DATABASE_URL, ADMIN_DATABASE_URL, and JWT_SECRET
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

### Two database roles: `DATABASE_URL` vs `ADMIN_DATABASE_URL`

The app connects with two separate Postgres roles, split across two
connection pools (`db.py`):

- **`DATABASE_URL`** — a low-privilege `ems_app` role (`NOBYPASSRLS`,
  `NOSUPERUSER`, DML-only grants, not table owner) used for all regular
  request-serving queries. Row-level security tenant-isolation policies
  actually apply to this connection.
- **`ADMIN_DATABASE_URL`** — the schema-owning role, used for DDL (Alembic
  migrations) and for `core/seed.py`'s startup seed data (superadmin user,
  onboarding templates — INSERT/UPDATE only, no DDL). Falls back to
  `DATABASE_URL` if unset, for environments that haven't split the two
  roles.

This split exists because Postgres roles with `BYPASSRLS` (including
`postgres` on some managed providers) silently skip RLS policy checks
regardless of `FORCE ROW LEVEL SECURITY` — using a genuinely restricted
role for `DATABASE_URL` is what makes the tenant-isolation policies below
actually enforced rather than a no-op.

## Frontend structure

The frontend is vanilla JavaScript (no framework) with HTML templates in
`static/index.html` and separate logic files:

- `static/js/core.js` — global auth, boot, page navigation, role switching
- `static/js/app-init.js` — menu and navigation UI interactions
- `static/js/payroll.js`, `static/js/leave.js`, etc. — feature-specific logic
- `static/js/employee-picker.js` — `initEmployeeSearchSelect(selectId,
  placeholder)`, a shared helper turning any plain employee `<select>`
  into a type-to-search picker (institutions can have 100+ employees).
  Non-invasive by design: it hides the real `<select>` behind a text
  input + dropdown but keeps it as the actual source of truth (same
  `id`/`.value`, dispatches a real `change` event on pick), so every one
  of the 8 call sites across the app needed only a single added line —
  no changes to how each site already builds its `<option>`s or reads
  the value back out on submit.

### UI Design (Navigation & Menu)

The top navigation includes:

- **Burger menu** (top-left): off-canvas drawer that slides down from the
  header (not from the left side). Opens/closes via `openBurgerMenu()` /
  `closeBurgerMenu()` / `toggleBurgerMenu()` in `app-init.js`, with overlay
  click-to-close. Uses CSS transforms (`invisible opacity-0 -translate-y-2`)
  for smooth animations and z-index stacking to keep the header clickable
  while the overlay is open.

- **Company branding** (top-center): logo (custom or default icon) and
  institution name. Updated by `updateBrandHeader()` in `core.js` when
  superadmin switches institutions.

- **User profile menu** (top-right): avatar with user initials, dropdown
  containing logout and role-switching controls (if user has multiple roles).
  Opens/closes via `toggleUserMenu()` with click-outside handling.

### Frontend CSS (Tailwind)

Tailwind is compiled ahead of time rather than loaded from the CDN at
runtime (the CDN build is explicitly documented by Tailwind as unsuitable
for production — no purging, external runtime dependency, unpinned
version). The compiled, purged `static/css/tailwind.css` is committed to
the repo, so no build step is required to run or deploy the app.

On Tailwind v4: there's no `tailwind.config.js` — config lives directly
in `static/css/tailwind-input.css` (`@import "tailwindcss";` plus a
`@layer base` block that pins the pre-v4 default border color, so
existing markup didn't need updating for v4's `currentcolor` default).
Content detection is automatic (v4 scans the project respecting
`.gitignore`); the build itself needs the separate `@tailwindcss/cli`
package (v4 split the CLI out of the main `tailwindcss` package).

If you add new Tailwind utility classes to `static/index.html` or any
`static/js/*.js` file, rebuild the compiled CSS before committing:

```bash
npm install
npm run build:css
```

`npm run watch:css` rebuilds on save while iterating on styles.

## Frontend asset versioning

`index.html`'s `?v=...` cache-busting query strings are rewritten
automatically at request time (`_static_asset_version()` in `main.py`),
derived from a hash of every static file's path + mtime. Editing any file
under `static/` automatically changes the served version — there is
nothing to bump by hand. The literal `?v=...` values committed in
`static/index.html` are just inert placeholders.

## API Documentation (OpenAPI/Swagger)

The API is documented via OpenAPI 3.0 schemas generated from Pydantic response models. Access the interactive docs while the app is running:

- **Swagger UI**: http://localhost:8000/api/docs — full interactive API explorer
- **ReDoc**: http://localhost:8000/api/redoc — alternative docs view
- **OpenAPI JSON**: http://localhost:8000/api/openapi.json — raw schema (for code generation)

Response models are defined in `core/schemas.py` and added incrementally to endpoints via `response_model=` parameter. This enables:
- Automatic request/response validation
- Clear API contracts for frontend integration
- Generated client SDKs in any language via tools like `openapi-generator`
- Swagger UI "Try it out" feature for testing endpoints

To add response models to new endpoints:
```python
from core.schemas import UserResponse

@router.get("/api/users", response_model=List[UserResponse], tags=["users"])
def list_users(...):
    ...
```

## Async Operations (Celery + Redis)

Long-running operations (e.g. payroll run generation, bulk uploads) are executed
asynchronously via Celery, returning `202 Accepted` with a task ID immediately
while the work runs in the background.

### Architecture

- **Celery App** (`core/tasks.py`): defines async tasks, talks to Redis broker/backend
- **Redis**: message queue (broker) and result storage (backend) for task status
- **Task Tracking** (`task_tracking` table): optional database record linking tasks to users/institutions
- **Task Status Endpoint** (`GET /api/tasks/{task_id}`): poll for completion and results

### Local Development

Start Redis and the Celery worker in separate terminals:

```bash
# Terminal 1: Redis (requires `brew install redis` or Docker)
redis-server

# Terminal 2: Celery worker
python celery_worker.py
```

The FastAPI app runs normally: `uvicorn main:app --reload`

### Production Deployment

Production (`ems-app` on Fly.io) does **not** run a separate Redis instance or
Celery worker — there's a single Fly machine running only `uvicorn main:app`
(see `fly.toml`/`Dockerfile`, no `[processes]` worker entry). Instead, the
`CELERY_TASK_ALWAYS_EAGER` Fly secret is set to `true`, which makes
`core/tasks.py` configure Celery with `task_always_eager=True`: `.apply_async()`
calls execute the task **synchronously, inline, in the same request** that
queued it, using an in-memory broker/backend (`broker="memory://"`) instead of
Redis — no separate worker process is needed or running.

This is a deliberate choice for this app's current scale, not a stopgap left
over from local dev — but it has one real consequence worth knowing:
**the `202 Accepted` / poll-`GET /api/tasks/{task_id}` contract described below
doesn't reflect what actually happens in production.** The HTTP response for
`POST /api/payroll/runs` or `POST /api/employees/bulk-upload` isn't sent until
the *entire* task has finished running inline — there's no real "pending" state
to poll for. As institution size grows, a large payroll run generating payslips
for hundreds of employees synchronously inside one request is a real
request-timeout risk (see "Known limitations" below). If that ever becomes a
problem in practice, the fix is to actually provision Redis + a Fly worker
process and unset `CELERY_TASK_ALWAYS_EAGER` in production — the code path
already supports it, it's just not deployed that way today.

### Async Endpoint Pattern

```python
from core.tasks import generate_payroll_run
from celery.result import AsyncResult

@router.post("/api/payroll/runs", status_code=202)
def create_payroll_run(body: PayrollRunIn, user: dict = Depends(require_roles("payroll_manager"))):
    # 1. Create the resource (e.g. payroll run) with status 'pending'
    run = create_run_in_db(...)

    # 2. Queue the async task
    task = generate_payroll_run.apply_async(
        args=[inst_id, run["id"], body.period_start, body.period_end]
    )

    # 3. Track the task (optional, for audit/permissions)
    track_task_in_db(task.id, user["id"], inst_id, "payroll_run")

    # 4. Return 202 with task ID for polling
    return {"task_id": task.id, "run_id": run["id"], "status": "pending"}
```

The client polls `GET /api/tasks/{task_id}` to check progress:

```json
{
  "id": "celery-uuid-here",
  "status": "SUCCESS",
  "result": {"run_id": 1, "employee_count": 42, ...},
  "error": null
}
```

Possible statuses: `PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, `RETRY`.

### Implemented Async Endpoints

- **POST /api/payroll/runs** (202 Accepted): Generate payslips for a payroll run
  - Long-running operation: processes all active employees in the institution
  - Task result: `{"run_id": int, "employee_count": int, ...}`

- **POST /api/employees/bulk-upload** (202 Accepted): Bulk import employees from CSV
  - Long-running operation: validates and inserts many rows with retry logic
  - Task result: `{"created": [...], "errors": [...], "summary": "..."}`

Both endpoints follow the same 202 Accepted pattern: queue work, return task_id, and client polls status.

## Testing

### Backend (Python/pytest)

```bash
pytest                            # run all tests
pytest tests/test_payroll_calc.py # payroll unit tests only (no DB needed)
```

- `tests/test_payroll_calc.py` — pure unit tests, no external dependencies
  (doesn't import `main.py`, so no DB connection needed).
- `tests/test_auth.py`, `tests/test_frontend.py`, `tests/test_currency.py`,
  `tests/test_rls_enforcement.py` — integration tests against the real app;
  require `DATABASE_URL`/`ADMIN_DATABASE_URL`/`JWT_SECRET` in `.env`. Note
  this applies even to tests that look unrelated to the database (e.g.
  `test_frontend.py`, which only tests static file serving) — they import
  `main.py`, which connects to and migrates the DB at module import time.
  These tests are strictly read-only and never create, mutate, or delete
  data (see `tests/conftest.py`).

**Concurrency & deadlock handling:** `tests/conftest.py`'s `make_test_user()`
fixture includes exponential-backoff retry logic for transient `DeadlockDetected`
errors. Under xdist 2-worker parallelization, concurrent test files both call
`make_test_user()` simultaneously, hitting concurrent INSERTs on the users table
with lock conflicts. The retry wrapper (up to 3 attempts, 0.1s–0.2s backoff)
transparently handles these race conditions without requiring architectural
changes to the DB layer.

### Frontend (JavaScript/Vitest)

```bash
npm test              # run all JS tests once
npm run test:ui       # interactive test UI
npm run test:coverage # test coverage report
```

Frontend tests cover vanilla-JS navigation and menu logic (burger menu toggle,
user dropdown, page navigation, nav accordion groups). Tests use Vitest + jsdom
and are located in `static/js/__tests__/`. All 15 tests passing validates the
burger-menu redesign and ensures menu interactions remain correct as the
codebase evolves.

Integration tests run against a dedicated test Supabase project, configured
via `TEST_DATABASE_URL`/`TEST_ADMIN_DATABASE_URL` in `.env`
(`tests/conftest.py` swaps them in for `DATABASE_URL`/`ADMIN_DATABASE_URL`
before anything else imports the DB layer — falls back to running against
prod if the `TEST_*` vars aren't set). Keep new DB-touching tests read-only,
or scope them to clearly-prefixed disposable data with guaranteed teardown,
regardless — the fallback path is still real prod data. See CLAUDE.md for
how the test project was provisioned (a schema dump/restore from prod, not
`alembic upgrade head` from empty — the historical migration chain isn't
currently replayable from a truly empty database).

CI (`.github/workflows/tests.yml`) runs on every push/PR: the CSS build is
checked for drift, `payroll_calc` tests always run, and the DB-backed
integration tests need `TEST_DATABASE_URL`/`TEST_ADMIN_DATABASE_URL`/
`JWT_SECRET` configured as repo secrets (Settings → Secrets and variables →
Actions) — falls back to `DATABASE_URL`/`ADMIN_DATABASE_URL` (i.e. prod) if
the `TEST_*` secrets aren't set, and skips DB-backed steps entirely if
neither is configured.

## Database schema migrations

[Alembic](https://alembic.sqlalchemy.org/) (`migrations/`, `alembic.ini`)
owns the schema. `main.py` no longer has any DDL of its own — the
`init_db()`/`_init_db_body()` function this section used to describe was
removed as part of restructuring `main.py` into routers; the schema that
function used to own is now `20260717_0001_full_schema_ddl.py`. The
pre-Alembic schema was stamped as a baseline (`alembic stamp head`,
revision `75b14e73962f`, an empty no-op migration) rather than run as
real DDL — see that migration's docstring for why. This app has no ORM,
so autogenerate isn't available; write migrations by hand with
`op.execute("...")`, matching the raw-SQL style used everywhere
else in this codebase.

```bash
pip install -r requirements-dev.txt   # includes alembic + sqlalchemy

alembic revision -m "add foo column to bar"   # new migration
alembic upgrade head                          # apply pending migrations
alembic current                                # what's applied now
```

Alembic reads `ADMIN_DATABASE_URL` (falling back to `DATABASE_URL`) from the
same `.env` file the app uses (see `migrations/env.py`) — migrations run DDL,
so they need the schema-owning role, not the restricted `ems_app` role.
Deploys go through `./deploy.sh` (repo root), which runs `alembic upgrade
head` before `fly deploy` so a migration can never ship un-applied — don't
call `fly deploy` directly.

## Currency storage

All money columns are `NUMERIC(12,2)` (exact fixed-point decimal), not
`REAL`/float — storage and SQL-side aggregation (e.g. `SUM(net_pay)`) are
exact. `db.py` registers a psycopg2 adapter so these still come back as
plain Python `float` in application code (existing arithmetic in
`payroll_calc.py` and elsewhere is unchanged); the fixed-point guarantee
applies to the database layer, where float drift previously accumulated
silently across storage/retrieval and aggregation. See `tests/test_currency.py`.

## Row-level security (multi-tenancy)

Tenant isolation is enforced at the database layer via Postgres RLS
(`migrations/versions/eb95a484c74a_*.py`), not just application-code
filtering — every standard table has a `tenant_isolation` policy scoped to
`app.current_institution_id`, set per-request via `set_config(...)` in
`db.py`. This only actually restricts access because `DATABASE_URL` is a
non-`BYPASSRLS` role (see the two-role split above); superadmin access
across institutions works by setting `bypass_rls=true` in the RLS context
(`core/deps.py`), not by relying on role-level bypass. See
`tests/test_rls_enforcement.py` for the enforcement tests.

**Institution ID indexing:** All RLS-filtered tables have indexes on
`institution_id` to avoid full-table scans when the RLS policy filters by
tenant. These were added in `migrations/versions/8fc32f58e44f_*.py` and cover
38 tables. Without these indexes, every RLS-scoped query would perform
sequential scans even when `institution_id` is highly selective (e.g. a single
institution rarely has >100k rows of any single entity type across millions of
rows in the large shared tables).

## Benefits module

`routers/benefits.py` / `core/benefits_schemas.py` / `static/js/benefits.js`.
Plan catalog → eligibility rules (by job level/pay grade, "no rule = open to
everyone") → enrollment periods & life-event triggered enrollment → dependents/
beneficiaries → carrier/claims tracking (modeled internally, no live external
carrier API) → compliance/cost reporting. HR-side access is gated to
`hr_manager`/`payroll_manager`/`compensation_manager` (`require_benefits_role`)
except dependent editing, which is narrower (`hr_manager`/`hr_admin`/
`superadmin`, matching Edit Employee's own access) since dependents now live in
the Edit Employee modal's Dependents tab rather than a standalone page.
Self-service dependent editing (an employee maintaining their own roster) is
authorized in the same shared `PUT /dependents/{id}` endpoint by comparing the
dependent's `employee_id` against the caller's own, not via a separate
self-service endpoint.

Reimbursement-cap plans enforce the cap at claim-approval time (not just
display) — see `decide_claim`'s cap-check block in `routers/benefits.py`, which
sums the employee's already-approved/paid claims for the year against the
enrollment's cost-snapshot cap before allowing an approval through.

## Attendance module

`routers/attendance.py` / `core/attendance_schemas.py` / `static/js/attendance.js`.

- **Shifts** support overnight/cross-midnight schedules. A shift's
  `crosses_midnight` flag is computed and stored at creation
  (`end_time <= start_time`); an `attendance_records` row is keyed by
  `work_date` anchored to the day the shift *starts*, so an overnight punch
  produces one record, not two fragments split across the calendar boundary.
  Clock-out doesn't recompute any of this — it just finds the employee's
  currently-open record (`clock_in_at` set, `clock_out_at` null) and closes it,
  which sidesteps the midnight-crossing ambiguity entirely.
- **Clock-in requirement** is opt-in: `attendance_settings` rows scope
  "required" to a department or a specific employee; no matching rule means
  not required. An employee-specific rule takes priority over a department
  rule.
- **Geofencing** is advisory only, never blocking: a clock-in outside a
  location's configured radius is flagged (`outside_geofence`, with the
  computed distance) but still succeeds, since remote/field employees may have
  no location rule at all.
- **Absence detection** is lazy — there is no background job/cron in this
  stack. Late/absent status is computed and materialized the moment the
  Attendance Review page or HR dashboard loads, by walking back over a rolling
  window per employee and checking each work day's clock-in deadline
  (`scheduled_start + grace_period`) against the current time.
- **HR review** resolves a Late/Absent record as Excused, Confirmed Absent, or
  Reclassified as Leave — the last option creates a real `leave_applications`
  row (optionally half-day) linked back to the attendance record, reusing the
  existing Leave module rather than a parallel approval flow.
- **Device webhook** (`POST /api/attendance/webhook/clock-event`): external
  clock-in/out hardware (e.g. a facial-recognition office camera) authenticates
  with its own API key via the `X-Device-Api-Key` header — a separate auth path
  from the JWT bearer-token flow every other endpoint uses. A device's key is
  generated once as `adk_<prefix>_<secret>`; only the `key_prefix` (plaintext,
  indexed, for fast lookup) and a bcrypt hash of the full key are ever
  persisted (`attendance_devices` table) — the raw key is shown to HR exactly
  once at creation and is never retrievable again. The actual face
  recognition/liveness check is entirely the vendor hardware's responsibility;
  this endpoint just trusts the `employee_id` the device reports and records
  the event through the same shift-resolution/geofence logic as self-service
  clock-in.

## Leave module

`routers/leave.py` / `core/leave_balance_ops.py` / `static/js/leave.js`.

A `leave_balances` row is one employee+leave_type+year, holding
`entitled_days`, `carried_forward_days`, and `used_days` (all `REAL`).
Available balance is always `entitled_days + carried_forward_days -
used_days` — carry-forward is additive to the pool, not a separate
allowance you have to apply for.

Rows are created lazily, not by a batch job: `_get_or_create_leave_balance`
(`core/leave_balance_ops.py`) is called from every code path that needs a
balance (applying, approving, cancelling, the balances list, and
`routers/attendance.py`'s "reclassify as leave" action), and inserts the row
the first time any of them touches that employee+type+year combination.
There is no scheduled job anywhere in this stack (see the Attendance
module's absence detection above for the same pattern) — carry-forward and
expiry are both computed lazily, at read/use time, not on a year-boundary
cron.

### Carry-forward mechanism

Two `leave_types` fields gate it per type — `carry_forward_enabled` (off by
default; most types like Medical or Maternity shouldn't carry forward at
all), plus `carry_forward_max_days` and `carry_forward_max_percent` (both
`0` = uncapped, matching how `max_days_per_application`/`max_days_per_month`
already treat `0` as "unconfigured" on this table). A fourth field,
`carry_forward_expiry_days`, controls how long the carried amount stays
spendable into the new year (`0` = never expires).

**Computing how much carries forward** (`_compute_carry_forward`, called
only when a new year's balance row is being created): the prior year's
unused balance is `entitled_days + carried_forward_days - used_days` from
*its* row (already net of anything that expired out of it during that
year — see below), and the amount actually carried is

```
min(unused, max_days if set, unused * max_percent / 100 if set)
```

— i.e. whichever cap bites hardest, rounded to the nearest half-day. Leaving
both caps at `0` carries the full unused balance forward uncapped. This is a
one-year grace period, not compounding: a carried-forward amount that goes
unused doesn't roll into a third year, because carry-forward is only ever
computed from the immediately preceding year's row when *that* year's row
is first created — a two-year-old unused amount has either already been
spent, or already expired and been forfeited.

**Expiry date**: computed once, at the new row's creation, as `Jan 1 of
that year + carry_forward_expiry_days`, stored on the row itself
(`carried_forward_expires_on`) rather than recomputed on the fly — so
changing a leave type's policy later doesn't retroactively change the
deadline on balances that already rolled over under the old policy.

### Deduction order: carry-forward is drawn down first

`carried_forward_used_days` is a second counter alongside `used_days`,
tracking just the carry-forward portion of what's been used.
`_consume_balance`/`_release_balance` (`core/leave_balance_ops.py`) are the
only places `used_days` changes, and both keep the two counters in step:

- **Consuming** `days` (an application gets approved) takes
  `min(days, carried_forward_days - carried_forward_used_days)` from the
  carry-forward bucket first, incrementing `carried_forward_used_days` by
  that amount; `used_days` always increases by the full `days` regardless
  of which bucket it logically came from — the combined total is what every
  other part of the system (balance display, utilization dashboard) already
  reads.
- **Releasing** `days` (cancellation, or an approval reversed) gives back
  to the carry-forward bucket first — `min(days,
  carried_forward_used_days)` — the same-direction mirror of consumption.
  This is bucket-level bookkeeping, not a per-application ledger: it keeps
  `carried_forward_used_days` always between `0` and `carried_forward_days`,
  but doesn't guarantee restoring the *exact* split a specific application
  originally consumed if several applications interleaved.

This ordering exists entirely to make the expiry sweep below correct — the
top-level available-balance number is the same simple sum either way; only
"how much carry-forward is left to expire" depends on drawing it down
first.

### Expiry sweep (forfeiture)

There's no cron job to sweep expired carry-forward on the new year — instead
`_sweep_expired_carry_forward` runs lazily, called every time a balance row
is read or used (`_get_or_create_leave_balance`'s existing-row path, and the
`GET /api/leave/balances` listing). If `carried_forward_expires_on` has
passed and there's still unused carry-forward
(`carried_forward_days - carried_forward_used_days > 0`), that remainder is
moved into `carried_forward_forfeited_days` (an audit trail — "why did this
employee's balance drop with no application against it") and
`carried_forward_days` is capped down to `carried_forward_used_days`, so it
stops counting toward the available-balance total. Because this only runs
on access, `_get_or_create_leave_balance` explicitly sweeps the *prior*
year's row before computing what rolls into a new one — otherwise an
already-lapsed carry-forward that nothing happened to read all year could
incorrectly roll forward again.

A manual balance adjustment (`PATCH /api/leave/balances/{id}`, HR-only)
that lowers `carried_forward_days` below the row's own
`carried_forward_used_days` clamps the used-counter down to match, so
"remaining carry-forward" can never go negative from an admin edit.

### Half-day (AM/PM) applications

The start and/or end date of a leave application can each independently
be marked as a half-day (`start_day_period`/`end_day_period` on
`leave_applications`, `'AM'`/`'PM'`/`NULL`) — e.g. PM on the first day,
full days between, AM on the last day. A single-day application only
ever uses `start_day_period` (`end_day_period` is DB-constrained to
`NULL` whenever `start_date = end_date`). Deduction is computed once at
submission (`_half_day_deduction` in `routers/leave.py`, reused by
`_check_monthly_cap` so a half-day application can't be miscounted as a
full day against a monthly cap) and stored on `days_count` — the rest of
the lifecycle (approve/reject/cancel) just reuses that stored figure,
same as every other leave amount.

Availability is governed by a single per-leave-type flag,
`leave_types.allow_half_day` (default on) — **not** inferred from
`count_calendar_days`, so a calendar-day-counting type (e.g.
Maternity/Paternity) can still offer half-day if HR leaves it on, or a
normal type can have it turned off. The frontend shows the Start
Day/End Day selectors as soon as an eligible type is picked (not
gated on both dates being filled in first — `updateLeaveApplyDayPeriodVisibility`
in `static/js/leave.js`).

## Approval workflow module

`core/approval_workflow.py` / `routers/approval_workflow_settings.py` /
`static/js/approval-workflow.js`.

Originally five modules — Leave, Benefits Claims, Job Requisition,
Timesheet, and L&D Enrollment — used to each hardcode their own
single-step role check (e.g. `role in (manager, hr_manager, hr_admin)`),
with no verification that an approving "manager" was the requester's
*actual* manager. This replaced all five with one shared,
per-institution-configurable engine, since extended to **Overtime** and
**Resignation** too (7 modules total — see `MODULE_TABLE` in
`core/approval_workflow.py` for the current list): an ordered chain of
1-4 steps, each step being `direct_manager`, `skip_level_manager`,
`hr_manager` (a fixed, module-specific role set — see `MODULE_HR_ROLES`,
since these weren't identical before: Claims never included `hr_admin`,
Requisition approval was `hr_manager`-only), `project_manager` (resolved
via the request's own project(s) — direct on Leave/Claims/Timesheet, via
the parent timesheet's projects on Overtime, since an overtime record has
no project of its own — see `PROJECT_MANAGER_MODULES`), or
`specific_employee` (a named override, e.g. routing one leave type
straight to a named compliance officer regardless of org chart).

Each step may also configure an *alternative* ("OR") approver type —
`alt_approver_type` (plus `alt_specific_employee_id` when that's
`specific_employee`) — so the step is satisfied by whichever of the two
acts first, e.g. `direct_manager` OR `hr_manager` lets HR approve
directly without waiting on the line manager. `alt_approver_type` must
differ from the step's primary `approver_type`; both `is_eligible_approver`
and `_step_pool_nonempty` in `core/approval_workflow.py` check the
primary type first and fall back to the alt type via the shared
`_type_is_eligible`/`_type_pool_nonempty` helpers.

**Data model**: `approval_workflows` (one named, orderable chain per
institution+module) and `approval_workflow_steps`. Each of the 5 request
tables gets `approval_workflow_id` (snapshotted at submission — editing
the workflow later doesn't reshuffle in-flight requests) and
`approval_step` (which step is currently pending; `NULL` once the request
leaves its pending state).

**Defaults**: lazily created per institution+module on first use (2
steps: Direct Manager, then that module's HR roles), the same
resolve-or-create-default pattern as `ob_template_sets`
(routers/onboarding.py) and leave's own carry-forward default — not
seeded up front for every institution.

**Resolution and auto-skip**: `start_workflow` (submission time) and
`advance_or_finalize` (each approve/reject) both walk the step list via
`_first_resolvable_step`, which skips any step whose pool is empty for
that specific request — no manager on file skips `direct_manager`, no
manager's-manager skips `skip_level_manager`, a deactivated named
approver skips `specific_employee`. If the *entire* chain is
unresolvable (e.g. a solo employee with no manager and no HR steps
configured), the request auto-approves rather than getting permanently
stuck. `job_requisitions` has no requester-employee column of its own
(it's always created by an HR/recruiter user, not a line manager) — its
Direct/Skip-Level Manager steps resolve via whichever employee record is
linked to the *creating user's own account* (`_requisition_requester_employee_id`).

**Approve/reject flow**: each endpoint now checks `is_eligible_approver`
for the request's current step instead of a blanket role check. Approving
a non-final step returns `"advanced"` (status stays e.g. `Pending
Approval`, `approval_step` moves to the next resolvable step); approving
the final step finalizes as before (balance deduction, reimbursement-cap
check, etc. — the existing side effects are unchanged, just gated
differently). Rejecting is terminal from any step. A legacy row with no
`approval_workflow_id` (predates this engine) falls back to each module's
original blanket role check rather than getting stuck.

**Dashboard integration**: `count_pending_for_approver`
(`core/approval_workflow.py`) powers new items in the Dashboard To-Do
list (`routers/dashboard.py`) — "N leave applications awaiting your
approval" etc. — generalizing the one precedent that already existed
there (the ManagerReview appraisal item) rather than introducing a new
exception to that endpoint's "personal items only" design.

## Timesheet & Overtime modules

`routers/timesheets.py` / `routers/overtime.py` / `core/overtime.py` /
`core/attendance_helpers.py`.

Timesheets are weekly: one `timesheets` header row (`Draft` →
`Submitted` → `Approved`/`Rejected`) with `timesheet_entries` logging
hours per day against a project+task. `Submitted` triggers the shared
approval-workflow engine (module `"timesheet"`, see below).

**Overtime is detected automatically**, not user-submitted: on
submission, `core/overtime.py`'s `generate_overtime_records` groups that
week's entries by date and compares each day's total hours against the
employee's resolved Attendance shift (`core/attendance_helpers.py`'s
`resolve_shift` — the same function `routers/attendance.py` uses, shared
so both modules agree on "an employee's normal working hours"). No shift
on file for that employee means no overtime detection at all — there's
nothing to compare against. Any day over threshold becomes one
`overtime_records` row, routed through its own approval-workflow chain
(module `"overtime"`), including project-manager eligibility resolved
via the union of projects the parent timesheet actually logged that
week (a timesheet has no single project of its own).

On approval, an overtime record converts per an institution-level
setting (`institutions.overtime_conversion_mode`, `GET/PUT
/api/overtime/settings`): either **credited as leave** (proportional to
that employee's own shift length, onto an HR-configured leave type) or
**tracked as a pay amount** (`hours × hourly-rate-equivalent ×
overtime_pay_multiplier` — Monthly-salary employees get an approximated
hourly rate of `basic_salary / 176`, matching `payroll.py`'s existing
approximation). Pay conversion is tracking-only this round — not yet
summed into an actual payslip.

## Onboarding & Offboarding module

`routers/onboarding.py` / `core/ob_ld_shared.py` / `static/js/onboarding.js`.

`ob_template_sets` → `ob_templates` (reusable, per institution+type,
each with an `assigned_role` and up to 4-ish ordering via
`order_index`) get snapshotted into a real `ob_checklists` +
`ob_checklist_items` row pair when HR starts a checklist for a specific
employee (`POST /api/ob/checklists`) — editing a template afterward
never reshuffles an in-flight checklist, same "snapshot at start"
principle the Approval Workflow module uses. A template can optionally
link an L&D course (`linked_ld_course_id`); its checklist item then
auto-completes when the employee finishes that course rather than
needing manual completion.

**Item completion permission**: `item["assigned_role"] == user["role"]`,
or HR (`superadmin`/`hr_manager`/`hr_admin`) can always override — this
same rule gates the optional proof-of-completion **attachments**
(`ob_item_attachments`, `POST/GET/DELETE
/api/ob/checklists/{cl_id}/items/{item_id}/attachments`): a photo or
document (~6MB cap, same `data:...;base64` URI pattern as
`candidate_documents`), never required to mark an item Done, just
supporting evidence attachable any time. A checklist auto-completes
(`status='Completed'`) the moment every item reaches `Done`/`N/A`.

`assigned_role` (on both templates and items) accepts any of the 6
built-in roles plus this institution's custom roles (see below) —
validated dynamically via `core/roles.py`'s `get_valid_roles`, not a
fixed list.

### Probation Review (Month 1/2/3)

HR can opt a specific employee's onboarding checklist into "Probation
Review" — a checkbox at Start Onboarding, or added later from an
in-progress checklist — rather than it being automatic for every
employee, since not everyone goes through probation. Enabling it creates
three Performance cycles up front (`core/performance_probation.py`), one
each for Month 1/2/3 of employment, fully reusing the existing Goals/
Appraisal engine via a new employee-scoped cycle mode
(`performance_cycles.cycle_type='probation'` + `employee_id` set)
instead of the org-wide batch cycles HR creates manually (which stay
`cycle_type='standard'`, `employee_id` `NULL`). Each probation cycle gets
exactly one appraisal (not the org-wide fan-out standard cycles get) and
a fixed 6-criterion rubric (Job Knowledge, Quality of Work, Productivity,
Attendance & Punctuality, Communication, Cultural Fit), then goes through
the same Self → Manager → Calibration → Final flow as any other
appraisal. Only HR (`superadmin`/`hr_manager`/`hr_admin`) can see whether
a given employee is on probation — a plain `manager` or `employee`
viewer never sees this status on someone else's record, even
indirectly through the Performance cycle list.

## Resignation workflow

`core/resignation.py` / `routers/resignation.py`.

Employees can self-file a resignation from the Home dashboard ("Resign"
button); HR can also file one on an employee's behalf from the Employee
detail view. A request captures a reason, effective date (defaults to
today), and a required last working day (distinct from the effective
date, to account for a notice period), plus an optional resignation
letter attachment.

Routed through a `"resignation"` module on the same generic
approval-workflow engine as Leave/Claims/Timesheet/etc. (default Direct
Manager → HR Manager chain, configurable per institution in Settings →
Approval Workflows — see "Approval workflow module" above). On final
approval, `employees.resign_date`/`last_working_day` are stamped and an
Offboarding checklist is auto-started from the institution's default
Offboarding template, reusing `routers/onboarding.py`'s checklist-creation
logic (factored out of `start_ob_checklist` for this). Employee `status`
is left untouched by this flow — HR still deactivates the record
manually once the last working day has passed, matching how Offboarding
already works for exits filed the old way.

## Custom roles

`core/roles.py` / `routers/roles.py` / Settings → Roles UI.

6 built-in roles (`hr_manager`, `hr_admin`, `manager`,
`payroll_manager`, `compensation_manager`, `employee`) are fixed and
always available; `superadmin` is platform-level and never shown here.
HR can add more per institution (`custom_roles` table) — e.g. "IT
Infra" — usable both as a user's `role` (`routers/users.py`) and as an
onboarding/offboarding item's `assigned_role`. Deleting a custom role is
blocked while it's still assigned to any user, template, or in-progress
checklist item (`DELETE /api/roles/{id}` reports exactly how many of
each).

Role validity checks moved out of `UserIn`/`UserUpdate`'s Pydantic
`field_validator`s (which can't see the DB or the institution) into the
endpoint bodies, once `inst_id` is known — an invalid role on user
create/update now returns `400`, not Pydantic's `422`.

## Employee document compliance reminders

`routers/employee_documents.py` / `static/js/employee-documents.js`.

HR-configurable reminders for time-sensitive employee documents — e.g. a
foreign employee's work permit renewal, or a passport nearing expiry.
`employee_document_types` is an institution-defined list (HR adds
whatever categories it needs — Work Permit, Passport, anything else — via
Settings → Document Types), each with its own `reminder_window_days`.
`employee_documents` is one row per (employee, document type) —
`UNIQUE(employee_id, document_type_id)`, so renewing a document means
`PUT`-ing the existing row's `expiry_date` in place rather than creating
a new one; there's no renewal-history table. Any employee can have any
number of tracked documents regardless of nationality — there's no
"foreigner" flag gating this, since `employees.nationality` is free text
with no reliable way to validate it.

Expiry status (`overdue` / `expiring_soon` / `ok`) is computed lazily in
SQL from `CURRENT_DATE` on every read (`STATUS_CASE_SQL` in
`routers/employee_documents.py`, reused verbatim by every endpoint that
needs it) — matching this project's no-cron-jobs rule, same as the Leave
module's carry-forward expiry sweep above. `expiring_soon` covers today
through exactly the type's `reminder_window_days` out, inclusive.

This feature is HR-only end to end (`require_roles("hr_manager",
"hr_admin")` on every endpoint, deliberately narrower than most
employee-record writes, which also allow `superadmin`). Reminders surface
in two places: an aggregate line in the Dashboard To-Do widget
(`routers/dashboard.py`'s `get_todos`, gated the same way as its
onboarding-checklist block — institution-wide for HR roles, no
per-employee narrowing), and color-coded chips (red = overdue, amber =
expiring soon) on the existing Dashboard monthly Leave Calendar rather
than a separate list page — `GET /api/employee-documents/calendar`
mirrors `get_leave_calendar`'s shape so `static/js/dashboard.js`'s
`renderLeaveCalendarGrid` can merge it in alongside leave/holiday/
onboarding entries, one more source in the same day-bucketing pattern.
Since the calendar view lives inside a page other roles can also open,
the frontend only fetches this data at all when the logged-in role is
`hr_manager`/`hr_admin` — the endpoint enforces the same restriction
server-side as defense in depth.

## AI assistant

`routers/assistant.py` / `core/assistant_tools.py` / `core/anthropic_client.py`
/ `static/js/assistant.js`.

A self-service chatbot (`POST /api/assistant/chat`, Claude Haiku via the
Anthropic API) that answers questions about the logged-in user's own
leave balance, payslips, benefits, and timesheet/overtime status — and,
for managers using the team-scoped tools, their direct team's data for
those same areas. Read-only end to end: no tool can mutate data, and
chat history is ephemeral (the client resends recent turns each request;
nothing is persisted server-side).

Every tool Claude can call is zero-argument — the model never supplies
an `employee_id`, so there's no code path for it to ask for someone
else's data even if asked to. The actual scoping happens server-side in
`core/assistant_tools.py`, keyed off the authenticated `current_user`
only (see that module's docstring for the self-scoped vs. team-scoped
split). A Redis-backed rate limit (`CHAT_RATE_LIMIT_PER_HOUR`, currently
30) applies per user per rolling hour.

### Bring-your-own-key (BYOK)

An institution can supply its own Anthropic API key instead of relying
on the platform's shared `ANTHROPIC_API_KEY` — useful for isolating
billing/usage per tenant. `core/anthropic_client.py`'s
`get_client_for_institution()` resolves, per request: the institution's
own key if configured, else the platform default (`ANTHROPIC_API_KEY`,
now optional rather than fail-fast), else `None` — in which case
`/api/assistant/chat` returns a plain "not set up yet" reply instead of
erroring, and the frontend hides the chat widget entirely.

Managed via `GET`/`PUT`/`DELETE /api/assistant/settings`, gated to
**`hr_manager` only** (`ASSISTANT_SETTINGS_ROLES` in
`routers/assistant.py`) — deliberately narrower than this app's usual
Settings-page HR tier, since it's a real billing-relevant credential.
`PUT` validates the key against the real Anthropic API (a free
`models.list()` call) before saving, so a typo is caught immediately.
The key is encrypted at rest with Fernet
(`core/secrets_encryption.py`, `TENANT_SECRETS_ENCRYPTION_KEY` env var —
see `.env.example`) and never round-trips back out of the API in any
form; only `configured` (bool), `key_last4`, and `added_at` are exposed.

Superadmin gets read-only visibility into which institutions are on
BYOK vs. the platform default vs. neither (`ai_key_status`:
`"byok"`/`"platform"`/`"none"`, computed in
`routers/institutions.py`'s `_with_ai_key_status()`) — never the key
itself.

## Deployment (Fly.io)

The app is deployed to Fly.io with a rolling-update strategy. Key deployment
details:

- **Health checks:** configured in `fly.toml` with a 45-second grace period.
  This grace period is for `core/seed.py`'s `init_db_seed()`, called from
  `main.py`'s `lifespan` startup handler — it runs synchronously before the
  app starts accepting traffic. It does **not** run any DDL (schema is
  managed entirely by Alembic migrations, applied separately before
  deploy — see "Database schema migrations" below); it only seeds/upserts
  the platform superadmin user and default onboarding templates, which is
  normally fast, but the grace period gives it — plus DB connection
  startup — headroom before a health check would time it out.

- **Asset versioning:** CSS and JS static files get automatic cache-busting via
  query strings (see "Frontend asset versioning" above). No manual steps needed
  when deploying changes to `static/`.

- **Automatic rollback on a failed health check:** `deploy.sh` captures the
  current live image before deploying; if the post-deploy `curl` check
  doesn't return `200`, it redeploys that captured image (no rebuild, so
  it's fast) rather than leaving prod on a broken release. This rolls back
  the **app only** — the Alembic migration that already ran at the start
  of `deploy.sh` is not undone (requires `jq`, already on the deploy
  machine). If a migration isn't backward-compatible with the previous
  app code, a rolled-back app can still misbehave against the new schema;
  the script's own warning output calls this out rather than implying the
  rollback is a complete fix.

## Known limitations

See commit history / project notes for the running tech-debt list. Notably:
payroll statutory tables are simplified approximations (see
`payroll_calc.py` docstring — verify against official tables before real
use).

- **Payroll run / bulk upload block synchronously in production**, despite
  their `202 Accepted` response. Production runs Celery in eager mode (see
  "Production Deployment" under "Async Operations" above) with no separate
  worker, so `POST /api/payroll/runs` and `POST /api/employees/bulk-upload`
  don't return until all the work is done — a large institution's payroll run
  is a real request-timeout risk as headcount grows. No incident yet, but
  worth watching; the fix is provisioning a real Redis + worker deployment.
