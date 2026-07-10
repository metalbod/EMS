# EMS — Employee Management System

Multi-tenant HR platform: employees, recruitment, L&D, leave, timesheets/projects,
payroll (Malaysia EPF/SOCSO/EIS/PCB), and performance management.

FastAPI + Postgres (Supabase) backend, vanilla JS frontend, deployed to Fly.io.

## Setup

```bash
cp .env.example .env   # fill in DATABASE_URL and JWT_SECRET
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

## Testing

```bash
pytest
```

- `tests/test_payroll_calc.py` — pure unit tests, no external dependencies.
- `tests/test_auth.py` — integration tests against the real app; requires
  `DATABASE_URL`/`JWT_SECRET` in `.env`. These tests are strictly read-only
  and never create, mutate, or delete data (see `tests/conftest.py`).

There is currently no dedicated test database — integration tests run
against whatever `DATABASE_URL` points to. Keep new DB-touching tests
read-only, or scope them to clearly-prefixed disposable data with
guaranteed teardown.

CI (`.github/workflows/tests.yml`) runs on every push/PR. The auth
integration tests require `DATABASE_URL` and `JWT_SECRET` to be configured
as repo secrets (Settings → Secrets and variables → Actions) — without
them, that step logs a warning and skips rather than failing the build.

## Known limitations

See commit history / project notes for the running tech-debt list. Notably:
multi-tenancy isolation is enforced in application code only (no DB-level
RLS), payroll statutory tables are simplified approximations (see
`payroll_calc.py` docstring — verify against official tables before real
use), and currency is stored as floating point rather than fixed-point.
