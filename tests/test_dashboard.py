"""Integration tests for routers/dashboard.py (/api/todos).

Computed live from today's wall-clock date (not stored), so only the
current-week timesheet case is exercised here with a real "this week"
period_start — the ld_enrollments and manager-appraisal todo branches
are covered indirectly once ld.py/performance.py get their own test files.
"""
from datetime import datetime, timedelta, timezone


def _this_monday():
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def test_get_todos_requires_auth(client):
    res = client.get("/api/todos")
    assert res.status_code in (401, 403)


def test_superadmin_gets_empty_todos(client, superadmin_headers):
    res = client.get("/api/todos", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_hr_manager_with_no_employee_record_gets_empty_todos(client, hr_manager_auth):
    res = client.get("/api/todos", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == []


def test_employee_with_draft_timesheet_this_week_gets_todo(
    client, hr_manager_auth, test_institution, make_test_employee
):
    emp = make_test_employee()
    username = f"zztdash_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Dashboard Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    monday = _this_monday()
    sunday = (datetime.fromisoformat(monday).date() + timedelta(days=6)).isoformat()
    ts = client.post("/api/timesheets", headers=emp_headers,
                      json={"employee_id": emp["employee_id"], "period_start": monday, "period_end": sunday})
    assert ts.status_code == 201, ts.text

    res = client.get("/api/todos", headers=emp_headers)
    assert res.status_code == 200
    todos = res.json()
    assert any(t["key"] == "timesheet-my" for t in todos)

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_onboarding_checklist_items_appear_for_assigned_role(client, hr_manager_auth, test_institution, make_test_employee):
    """A checklist item's assigned_role determines whose To-Do it shows up
    in — the new hire sees their own 'employee'-assigned items, HR sees
    the institution's 'hr_manager'-assigned items. See routers/dashboard.py's
    ob_q, which mirrors list_ob_checklists' (routers/onboarding.py) existing
    my_pending scoping."""
    emp = make_test_employee(full_name="ZZ Dashboard OB Employee")
    username = f"zztdashob_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Dashboard OB Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    started = client.post("/api/ob/checklists", headers=hr_manager_auth,
                           json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert started.status_code == 201, started.text
    cl_id = started.json()["id"]

    # The new hire sees their own 'employee'-assigned items (e.g. "Welcome
    # Acknowledgement" in the seeded default templates).
    emp_todos = client.get("/api/todos", headers=emp_headers).json()
    ob_todo = next((t for t in emp_todos if t["key"] == "ob-onboarding"), None)
    assert ob_todo is not None, f"expected an ob-onboarding todo, got: {emp_todos}"
    assert ob_todo["page"] == "onboarding"
    assert ob_todo["count"] > 0

    # HR sees their own 'hr_admin'/'hr_manager'-assigned items across the
    # institution, not the employee's — hr_manager_auth's role is hr_manager.
    hr_todos = client.get("/api/todos", headers=hr_manager_auth).json()
    hr_ob_todo = next((t for t in hr_todos if t["key"] == "ob-onboarding"), None)
    assert hr_ob_todo is not None
    assert hr_ob_todo["count"] > 0

    client.delete(f"/api/ob/checklists/{cl_id}", headers=hr_manager_auth)
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)
