"""
Shared pytest fixtures.

These tests import the real `main.app` and, for the auth tests, hit the real
database configured via .env (DATABASE_URL) — there is no local test DB yet
(see tech-debt notes). Keep DB-touching tests strictly read-only or scoped to
disposable, clearly-prefixed data with guaranteed teardown; never assume it's
safe to mutate arbitrary rows.

IMPORTANT: `main` must NOT be imported at module level here. main.py raises
at import time if DATABASE_URL/JWT_SECRET aren't set (by design — see
main.py), and conftest.py is loaded by pytest for every test file in this
directory, including tests/test_payroll_calc.py, which is pure Python with
no DB dependency. A module-level `import main` here broke CI's "always run,
no secrets needed" payroll_calc step entirely — pytest can't even collect
test_payroll_calc.py if conftest.py itself fails to import. Every fixture
below imports main lazily, inside the function body, so only tests that
actually request these fixtures pay that cost.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main as app_module
    return TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """The login rate limiter is process-local in-memory state (see
    routers/auth.py). Clear it before and after every test so one test's
    failed-login attempts can't trip the 429 lockout in an unrelated test.
    Skips entirely for test files that never touch `main` (e.g.
    test_payroll_calc.py), so importing it isn't forced on tests that don't
    need it."""
    if "main" not in sys.modules:
        yield
        return
    from routers.auth import _login_failures
    _login_failures.clear()
    yield
    _login_failures.clear()
