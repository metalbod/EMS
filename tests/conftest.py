"""
Shared pytest fixtures.

These tests import the real `main.app` and, for the auth tests, hit a real
database — a dedicated Supabase test project (TEST_DATABASE_URL /
TEST_ADMIN_DATABASE_URL in .env), NOT prod, as of the test-DB-isolation
tech-debt fix. Falls back to DATABASE_URL/ADMIN_DATABASE_URL if the TEST_*
vars aren't set, for any environment that hasn't provisioned a test project
yet — so this still runs against prod in that case. Keep DB-touching tests
strictly read-only or scoped to disposable, clearly-prefixed data with
guaranteed teardown regardless; never assume it's safe to mutate arbitrary
rows, since the fallback path is still real prod data.

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
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must happen before anything below (or any test module) imports db.py/main.py
# — db.py reads DATABASE_URL/ADMIN_DATABASE_URL as module-level constants at
# import time, not lazily, so this has to win the race and run first. Since
# pytest always loads conftest.py before collecting any test file in this
# directory, this is early enough. load_dotenv()'s default override=False
# means it won't clobber a DATABASE_URL the environment already set (e.g. in
# CI), matching main.py's own load_dotenv() call later in the process.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
if os.environ.get("TEST_ADMIN_DATABASE_URL"):
    os.environ["ADMIN_DATABASE_URL"] = os.environ["TEST_ADMIN_DATABASE_URL"]

# Configure Celery to execute tasks synchronously during tests (no Redis/worker needed)
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("CELERY_TASK_EAGER_PROPAGATES", "true")

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
        "username": "superadmin", "password": "admin123", "institution_code": None,
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

    # Employees have no hard-delete endpoint (only a status toggle — see
    # make_test_employee's teardown), so every test run permanently adds to
    # this institution's employee count. max_employees is a billing guard for
    # real customer institutions, not meant to cap a permanently-disposable
    # test tenant, so keep it very high here to avoid hitting "Employee limit
    # reached" as more router test files accumulate employees over time.
    MAX_EMPLOYEES = 1_000_000

    existing = c.get("/api/institutions", headers=headers).json()
    for inst in existing:
        if inst["code"] == code:
            if inst["max_employees"] < MAX_EMPLOYEES:
                update_res = c.put(f"/api/institutions/{inst['id']}", headers=headers, json={
                    "name": inst["name"], "contact_email": inst["contact_email"],
                    "plan": inst["plan"], "max_employees": MAX_EMPLOYEES,
                })
                assert update_res.status_code == 200, f"failed to raise test institution employee limit: {update_res.text}"
            return {"id": inst["id"], "code": code}

    res = c.post("/api/institutions", headers=headers, json={
        "name": "ZZ Pytest Institution",
        "code": code,
        "contact_email": "zzpytest@example.com",
        "admin_username": "zzpytest_admin",
        "admin_full_name": "ZZ Pytest Admin",
        "admin_password": "ZzPytest@123",
        "plan": "enterprise",
        "max_employees": MAX_EMPLOYEES,
    })
    if res.status_code == 400 and "already exists" in res.text:
        # The find-or-create check above isn't atomic — under pytest-xdist,
        # every parallel worker runs this fixture in its own session, and on
        # a genuinely empty DB (e.g. right after a test-DB reset) they can
        # all race to create ZZPYTEST simultaneously. Only the first INSERT
        # wins; everyone else loses the race here instead of at the earlier
        # SELECT. Whoever lost just needs to look the row up now that it
        # exists — normally invisible once the institution exists for good
        # after the first-ever run, but surfaces every time the test DB
        # starts from empty.
        existing = c.get("/api/institutions", headers=headers).json()
        for inst in existing:
            if inst["code"] == code:
                return {"id": inst["id"], "code": code}
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

        # Retry on transient deadlock errors (xdist concurrent INSERTs with lock conflicts)
        res = None
        for attempt in range(3):
            try:
                res = c.post("/api/users", headers=superadmin_headers, json=payload)
                if res.status_code == 201:
                    break
                if res.status_code == 500 and "deadlock" in res.text.lower():
                    if attempt < 2:
                        time.sleep(0.1 * (2 ** attempt))  # Exponential backoff: 0.1s, 0.2s, then fail
                        continue
            except Exception as e:
                if attempt < 2 and "deadlock" in str(e).lower():
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise

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


# Salted with a cryptographically random per-process value plus a per-call
# counter, so IC numbers are unique both within a run and across separate
# pytest invocations — a prior run's leftover test employees (e.g. from an
# interrupted run) must never collide with a fresh run's.
#
# This used to be salted with os.getpid() % 1000 and time.time_ns() % 1000
# instead of secrets.randbelow() — deliberately redesigned away from that
# (see the Debt Ledger's "Redesign the test-data uniqueness scheme" item).
# PID and wall-clock time are not independent sources of entropy across
# concurrent process starts: CI matrix jobs and local `-n auto` xdist
# workers are launched close together in time (correlated time_ns() low
# digits) and OS PID allocation is sequential within a short window
# (correlated getpid() values), so two workers/runs starting near-
# simultaneously were more likely to land on the same 1000x1000 salt combo
# than the raw 1,000,000-combo space suggested. That's exactly the failure
# mode this already hit once (test_related_contracts_empty_for_unique_ic:
# a fresh employee's IC collided with a different run's leftover "ZZ Test
# Employee") even after a first attempt to fix it by widening the salt
# range. secrets.randbelow() draws are independent between processes by
# construction, so simultaneous starts no longer correlate.
# IC numbers must be exactly 12 digits (see validate_ic in
# routers/employees.py), so this can't just add more digits freely —
# it keeps the same 1000x1000-combo, 4-digit-counter shape as before,
# only the entropy source changed.
_ic_counter = itertools.count(1)
_ic_pid_salt = secrets.randbelow(1000)
_ic_time_salt = secrets.randbelow(1000)


def _unique_ic():
    """A syntactically valid, per-call-unique 12-digit IC number, so tests
    that check IC-based matching (e.g. employees' related-contracts) don't
    collide with other employees created by other tests or other runs in the
    same shared institution."""
    n = next(_ic_counter)
    return f"90{_ic_pid_salt:03d}{_ic_time_salt:03d}{n:04d}"


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


_code_counter = itertools.count(1)
# Same redesign as _ic_pid_salt/_ic_time_salt above: a genuinely random
# per-process salt instead of PID+timestamp, which correlated across
# rapid-fire/concurrent process starts. No fixed-width format constraint
# here (unlike IC numbers), so there's no reason to skimp on entropy —
# 10 random digits, drawn once per process.
_code_run_salt = f"{secrets.randbelow(10**10):010d}"


def _unique_code(prefix="ZZ"):
    """A short per-call-unique code (e.g. for grade_code/level_code/role_code
    in compensation tests, or location codes), so re-running the suite
    against the same persistent shared test institution never collides
    with a previous run's leftover rows — same rationale as _unique_ic."""
    n = next(_code_counter)
    return f"{prefix}{_code_run_salt}{n:04d}"


def _valid_location_payload(institution_id, **overrides):
    """Generate valid location payload for testing. Uses the same salted
    counter as _unique_code/_unique_ic (not random.randint, which only had
    9000 possible values and collided with leftover rows from earlier CI
    runs against the same persistent shared test institution)."""
    random_suffix = _unique_code("")
    payload = {
        "name": f"Test Location {random_suffix}",
        "code": f"LOC_{random_suffix}",
        "address": f"{random_suffix} Test Street",
        "city": "Kuala Lumpur",
        "state": "KL",
        "postal_code": "50050",
        "phone": "+60312345678",
        "location_type": "branch",
        "capacity": 50,
        "capacity_warning_threshold": 75,
        "capacity_critical_threshold": 95,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def make_test_location(client, hr_manager_auth, test_institution):
    """Factory fixture: creates a disposable location, soft-deletes it on
    teardown (DELETE /api/locations/{id} only sets is_active=0 — there's
    no hard-delete endpoint). tests/test_locations.py used to create
    locations with no cleanup at all, which had accumulated 7,000+
    leftover rows in the shared ZZPYTEST institution and measurably slowed
    down routers/location_phase2.py's payroll-by-location summary query
    (see migrations/versions/20260806_0004_payslips_employee_id_index.py's
    commit message). Usage:

        location = make_test_location()
        location = make_test_location(name="Branch A", capacity=20)
    """
    created_ids = []

    def _make(**overrides):
        payload = _valid_location_payload(test_institution["id"], **overrides)
        res = client.post("/api/locations", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test location: {res.text}"
        location = res.json()
        created_ids.append(location["id"])
        return location

    yield _make

    for loc_id in created_ids:
        client.delete(f"/api/locations/{loc_id}", headers=hr_manager_auth)


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

    # Collected rather than asserted inline, so one failed deactivation
    # doesn't abort teardown for the remaining ids — every created employee
    # still gets a deactivation attempt. The final assert still fails the
    # test run loudly if any of them didn't take: a silent failure here
    # leaves the employee permanently Active on the shared test institution
    # — this kind of unnoticed leak, multiplied across many test files over
    # a long project history, is what made auto-enroll-all in
    # test_benefits.py process 1300+ Active employees and effectively hang.
    failures = []
    for emp_id in created_ids:
        res = client.patch(f"/api/employees/{emp_id}/status", headers=hr_manager_auth, json={"status": "Inactive"})
        if res.status_code != 200:
            failures.append(f"{emp_id}: {res.status_code} {res.text}")
    assert not failures, f"teardown failed to deactivate {len(failures)} test employee(s): {failures}"


@pytest.fixture
def employee_with_login(client, hr_manager_auth, make_test_employee, test_institution):
    """Factory: creates a real employee with a linked login account. Shared
    by test_approval_workflow.py and test_overtime.py, both of which need
    a real user session to exercise eligibility (not just an employee
    record). Returns (employee, auth_headers). Usage:

        emp, headers = employee_with_login(full_name="ZZ Someone")
    """
    created_user_ids = []

    def _make(**overrides):
        emp = make_test_employee(**overrides)
        username = f"zzawuser_{emp['employee_id'].lower()}"
        password = "ZzPytest@123"
        res = client.post("/api/users", headers=hr_manager_auth, json={
            "username": username, "full_name": emp["full_name"], "password": password,
            "role": "employee", "employee_id": emp["employee_id"],
        })
        assert res.status_code == 201, f"failed to create user: {res.text}"
        created_user_ids.append(res.json()["id"])
        login = client.post("/api/auth/login", json={
            "username": username, "password": password, "institution_code": test_institution["code"],
        })
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        return emp, headers

    yield _make

    for uid in created_user_ids:
        client.delete(f"/api/users/{uid}", headers=hr_manager_auth)


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
