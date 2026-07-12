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
import itertools
import os
import random
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


@pytest.fixture
def hr_manager_auth(make_test_user, test_institution):
    """A disposable hr_manager user's auth headers, pre-scoped to the test
    institution. Used by any router test that needs write access without
    superadmin's extra privileges (e.g. exercising CAN_WRITE-style guards)."""
    token, _ = make_test_user(role="hr_manager")
    return {
        "Authorization": f"Bearer {token}",
        "X-Institution-Id": str(test_institution["id"]),
    }


@pytest.fixture
def payroll_manager_auth(make_test_user, test_institution):
    """A disposable payroll_manager user's auth headers, pre-scoped to the
    test institution — the only role in PAYROLL_MANAGE_ROLES (see
    routers/payroll.py)."""
    token, _ = make_test_user(role="payroll_manager")
    return {
        "Authorization": f"Bearer {token}",
        "X-Institution-Id": str(test_institution["id"]),
    }


# Salted with a fresh random value per process (not the PID, which can
# recycle across separate CI runs) plus a per-process counter, so IC numbers
# are unique both within a run and across separate pytest invocations — a
# prior run's leftover test employees (e.g. from an interrupted run) must
# never collide with a fresh run's.
_ic_counter = itertools.count(1)
_ic_run_salt = random.randint(0, 9999)


def _unique_ic():
    """A syntactically valid, per-call-unique 12-digit IC number, so tests
    that check IC-based matching (e.g. employees' related-contracts) don't
    collide with other employees created by other tests or other runs in the
    same shared institution."""
    n = next(_ic_counter)
    return f"9001{_ic_run_salt:04d}{n:04d}"


def _valid_employee_payload(**overrides):
    payload = {
        "full_name": "ZZ Test Employee",
        "ic_number": _unique_ic(),
        "race": "Malay",
        "religion": "Islam",
        "gender": "Male",
        "date_of_birth": "1990-01-01",
        "marital_status": "Single",
        "phone": "+60123456789",
        "department": "IT",
        "designation": "Tester",
        "employment_type": "Permanent",
        "start_date": "2026-01-01",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def make_test_employee(client, hr_manager_auth):
    """Factory fixture: creates a disposable employee (via the hr_manager_auth
    user), deactivates it on teardown (employees have no delete endpoint,
    only status toggle). Shared across any test file that needs a real
    employee record to exercise (leave, timesheets, projects, org chart,
    etc.), not just test_employees.py itself. Usage:

        def test_x(make_test_employee):
            emp = make_test_employee()
            emp = make_test_employee(department="Sales")
    """
    created_ids = []

    def _make(**overrides):
        res = client.post("/api/employees", headers=hr_manager_auth, json=_valid_employee_payload(**overrides))
        assert res.status_code == 201, f"failed to create test employee: {res.text}"
        emp = res.json()
        created_ids.append(emp["employee_id"])
        return emp

    yield _make

    for emp_id in created_ids:
        client.patch(f"/api/employees/{emp_id}/status", headers=hr_manager_auth, json={"status": "Inactive"})


@pytest.fixture
def make_test_project(client, hr_manager_auth):
    """Factory fixture: creates a disposable project, deletes it on teardown.
    Shared by test_projects.py and (later) test_leave.py/test_timesheets.py,
    which both need a real project+task to log time against. Usage:

        def test_x(make_test_project):
            project = make_test_project()
            project = make_test_project(name="ZZ Special Project")
    """
    created_ids = []

    def _make(**overrides):
        payload = {"name": "ZZ Test Project", "status": "Active"}
        payload.update(overrides)
        res = client.post("/api/projects", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test project: {res.text}"
        project = res.json()
        created_ids.append(project["id"])
        return project

    yield _make

    for pid in created_ids:
        # Defensive: delete any child tasks first regardless of whether
        # make_test_project_task's own teardown already ran — pytest doesn't
        # guarantee this fixture tears down after make_test_project_task
        # just because a test happens to use both (project_id is passed as a
        # plain value, not a fixture dependency, so there's no ordering edge
        # between them). Deleting a project that still has project_tasks
        # rows violates a foreign key, so this must run first every time.
        tasks = client.get(f"/api/projects/{pid}/tasks", headers=hr_manager_auth)
        if tasks.status_code == 200:
            for task in tasks.json():
                client.delete(f"/api/projects/{pid}/tasks/{task['id']}", headers=hr_manager_auth)
        client.delete(f"/api/projects/{pid}", headers=hr_manager_auth)


@pytest.fixture
def make_test_project_task(client, hr_manager_auth):
    """Factory fixture: creates a disposable task on the given project,
    deletes it on teardown. Usage:

        def test_x(make_test_project, make_test_project_task):
            project = make_test_project()
            task = make_test_project_task(project["id"])
    """
    created = []  # (project_id, task_id)

    def _make(project_id, **overrides):
        payload = {"name": "ZZ Test Task", "status": "Not Started"}
        payload.update(overrides)
        res = client.post(f"/api/projects/{project_id}/tasks", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test task: {res.text}"
        task = res.json()
        created.append((project_id, task["id"]))
        return task

    yield _make

    for project_id, task_id in created:
        client.delete(f"/api/projects/{project_id}/tasks/{task_id}", headers=hr_manager_auth)


@pytest.fixture
def make_test_leave_type(client, hr_manager_auth):
    """Factory fixture: creates a disposable leave type, soft-deletes it on
    teardown (leave types have no hard-delete endpoint, only
    is_active=0 via DELETE). Usage:

        def test_x(make_test_leave_type):
            lt = make_test_leave_type()
            lt = make_test_leave_type(requires_approval=False, annual_entitlement=5)
    """
    created_ids = []

    def _make(**overrides):
        payload = {"name": "ZZ Test Leave Type", "annual_entitlement": 14.0}
        payload.update(overrides)
        res = client.post("/api/leave/types", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test leave type: {res.text}"
        lt = res.json()
        created_ids.append(lt["id"])
        return lt

    yield _make

    for tid in created_ids:
        client.delete(f"/api/leave/types/{tid}", headers=hr_manager_auth)


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
