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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main as app_module
    return TestClient(app_module.app)


@pytest.fixture(scope="session")
def superadmin_token():
    """Log in as the platform superadmin seeded by init_db() (see main.py).
    Session-scoped since login is read-only and this is reused by nearly
    every DB-touching test file."""
    import main as app_module
    c = TestClient(app_module.app)
    res = c.post("/api/auth/login", json={
        "username": "superadmin", "password": "Admin@123", "institution_code": None,
    })
    assert res.status_code == 200, f"seeded superadmin login failed: {res.text}"
    return res.json()["access_token"]


@pytest.fixture(scope="session")
def test_institution(superadmin_token):
    """A dedicated institution for automated tests, separate from any real
    demo/dev data — found-or-created once per test session, never deleted
    (institutions have no delete endpoint, only status toggle) so repeated
    runs reuse the same row instead of accumulating one per run.
    Returns {"id": int, "code": str}.
    """
    import main as app_module
    c = TestClient(app_module.app)
    headers = {"Authorization": f"Bearer {superadmin_token}"}
    code = "ZZPYTEST"

    existing = c.get("/api/institutions", headers=headers).json()
    for inst in existing:
        if inst["code"] == code:
            return {"id": inst["id"], "code": code}

    res = c.post("/api/institutions", headers=headers, json={
        "name": "ZZ Pytest Institution",
        "code": code,
        "contact_email": "zzpytest@example.com",
        "admin_username": "zzpytest_admin",
        "admin_full_name": "ZZ Pytest Admin",
        "admin_password": "ZzPytest@123",
        "plan": "enterprise",
        "max_employees": 1000,
    })
    assert res.status_code == 201, f"failed to create test institution: {res.text}"
    return {"id": res.json()["id"], "code": code}


@pytest.fixture
def superadmin_headers(superadmin_token, test_institution):
    """Superadmin auth headers pre-scoped to the test institution via
    X-Institution-Id, for endpoints that need institution context."""
    return {
        "Authorization": f"Bearer {superadmin_token}",
        "X-Institution-Id": str(test_institution["id"]),
    }


@pytest.fixture
def make_test_user(test_institution, superadmin_headers):
    """Factory fixture: creates a disposable user (zz-prefixed username) in
    the test institution with the given role, returns (token, user_id), and
    deletes the user on teardown. Usage:

        def test_x(make_test_user):
            token, user_id = make_test_user(role="hr_manager")
    """
    import main as app_module
    c = TestClient(app_module.app)
    created_ids = []

    def _make(role="hr_manager", roles=None, username=None):
        username = username or f"zzpytest_{role}_{os.urandom(4).hex()}"
        password = "ZzPytest@123"
        payload = {
            "username": username,
            "full_name": f"ZZ Pytest {role}",
            "password": password,
            "role": role,
            "institution_id": test_institution["id"],
        }
        if roles:
            payload["roles"] = roles
        res = c.post("/api/users", headers=superadmin_headers, json=payload)
        assert res.status_code == 201, f"failed to create test user: {res.text}"
        user_id = res.json()["id"]
        created_ids.append(user_id)

        login = c.post("/api/auth/login", json={
            "username": username, "password": password, "institution_code": test_institution["code"],
        })
        assert login.status_code == 200, f"failed to log in as test user: {login.text}"
        return login.json()["access_token"], user_id

    yield _make

    for uid in created_ids:
        c.delete(f"/api/users/{uid}", headers=superadmin_headers)


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
