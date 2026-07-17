# EMS — Employee Management System

Multi-tenant HR platform: employees, recruitment, L&D, leave, timesheets/projects,
payroll (Malaysia EPF/SOCSO/EIS/PCB), and performance management.

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
- **`ADMIN_DATABASE_URL`** — the schema-owning role, used only for DDL
  (`init_db()` on boot, Alembic migrations). Falls back to `DATABASE_URL`
  if unset, for environments that haven't split the two roles.

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

There is currently no dedicated test database — integration tests run
against whatever `DATABASE_URL` points to. Keep new DB-touching tests
read-only, or scope them to clearly-prefixed disposable data with
guaranteed teardown.

CI (`.github/workflows/tests.yml`) runs on every push/PR: the CSS build is
checked for drift, `payroll_calc` tests always run, and the DB-backed
integration tests require `DATABASE_URL`/`ADMIN_DATABASE_URL`/`JWT_SECRET`
to be configured as repo secrets (Settings → Secrets and variables →
Actions) — without `DATABASE_URL`, that step logs a warning and skips
rather than failing the build; `ADMIN_DATABASE_URL` must also be wired into
the step's `env:` block (not just added as a secret) since `init_db()`'s
schema DDL needs it — see the two-role split above.

## Database schema migrations

The schema predating this section is still owned by `main.py`'s
`init_db()`/`_init_db_body()` — idempotent `CREATE TABLE IF NOT EXISTS` /
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements that run on every app
boot. That mechanism is unchanged and still authoritative for anything that
already exists.

[Alembic](https://alembic.sqlalchemy.org/) is now set up (`migrations/`,
`alembic.ini`) for **new** schema changes going forward, so they go through
reviewable, versioned migrations instead of being appended to `init_db()`.
The current schema was stamped as a baseline (`alembic stamp head`, revision
`75b14e73962f`) without running any DDL — see that migration's docstring for
why. This app has no ORM, so autogenerate isn't available; write migrations
by hand with `op.execute("...")`, matching the raw-SQL style used everywhere
else in this codebase.

```bash
pip install -r requirements-dev.txt   # includes alembic + sqlalchemy

alembic revision -m "add foo column to bar"   # new migration
alembic upgrade head                          # apply pending migrations
alembic current                                # what's applied now
```

Alembic reads `ADMIN_DATABASE_URL` (falling back to `DATABASE_URL`) from the
same `.env` file the app uses (see `migrations/env.py`) — migrations run DDL,
so they need the schema-owning role, not the restricted `ems_app` role. Not
yet wired into deployment (the app still self-migrates via `init_db()` on
boot); running `alembic upgrade head` is a manual step for now when a
migration is added.

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

## Deployment (Fly.io)

The app is deployed to Fly.io with a rolling-update strategy. Key deployment
details:

- **Health checks:** configured in `fly.toml` with a 30-second grace period.
  This grace period is necessary because `init_db()` (line 1032 in `main.py`)
  runs synchronously at app startup during Uvicorn's import of the `main`
  module. This runs DDL/schema initialization (CREATE TABLE, CREATE POLICY,
  CREATE INDEX, etc.) that can take time, especially on the initial deployment
  or after schema changes. The 30s grace period ensures health checks don't
  timeout before initialization is complete.

- **Asset versioning:** CSS and JS static files get automatic cache-busting via
  query strings (see "Frontend asset versioning" above). No manual steps needed
  when deploying changes to `static/`.

## Known limitations

See commit history / project notes for the running tech-debt list. Notably:
payroll statutory tables are simplified approximations (see
`payroll_calc.py` docstring — verify against official tables before real
use).
