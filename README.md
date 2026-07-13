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

cp .env.example .env   # fill in DATABASE_URL and JWT_SECRET
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

## Frontend CSS (Tailwind)

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

## Testing

```bash
pytest
```

- `tests/test_payroll_calc.py` — pure unit tests, no external dependencies
  (doesn't import `main.py`, so no DB connection needed).
- `tests/test_auth.py`, `tests/test_frontend.py`, `tests/test_currency.py`
  — integration tests against the real app; require `DATABASE_URL`/
  `JWT_SECRET` in `.env`. Note this applies even to tests that look
  unrelated to the database (e.g. `test_frontend.py`, which only tests
  static file serving) — they import `main.py`, which connects to and
  migrates the DB at module import time. These tests are strictly
  read-only and never create, mutate, or delete data (see
  `tests/conftest.py`).

There is currently no dedicated test database — integration tests run
against whatever `DATABASE_URL` points to. Keep new DB-touching tests
read-only, or scope them to clearly-prefixed disposable data with
guaranteed teardown.

CI (`.github/workflows/tests.yml`) runs on every push/PR: the CSS build is
checked for drift, `payroll_calc` tests always run, and the DB-backed
integration tests require `DATABASE_URL`/`JWT_SECRET` to be configured as
repo secrets (Settings → Secrets and variables → Actions) — without them,
that step logs a warning and skips rather than failing the build.

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

Alembic reads `DATABASE_URL` from the same `.env` file the app uses (see
`migrations/env.py`) — no separate configuration needed. Not yet wired into
deployment (the app still self-migrates via `init_db()` on boot); running
`alembic upgrade head` is a manual step for now when a migration is added.

## Currency storage

All money columns are `NUMERIC(12,2)` (exact fixed-point decimal), not
`REAL`/float — storage and SQL-side aggregation (e.g. `SUM(net_pay)`) are
exact. `db.py` registers a psycopg2 adapter so these still come back as
plain Python `float` in application code (existing arithmetic in
`payroll_calc.py` and elsewhere is unchanged); the fixed-point guarantee
applies to the database layer, where float drift previously accumulated
silently across storage/retrieval and aggregation. See `tests/test_currency.py`.

## Known limitations

See commit history / project notes for the running tech-debt list. Notably:
multi-tenancy isolation is enforced in application code only (no DB-level
RLS), and payroll statutory tables are simplified approximations (see
`payroll_calc.py` docstring — verify against official tables before real
use).
