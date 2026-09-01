"""Integration tests for routers/dashboard.py (/api/todos).

Computed live from today's wall-clock date (not stored), so only the
current-week timesheet case is exercised here with a real "this week"
period_start — the ld_enrollments and manager-appraisal todo branches
are covered indirectly once ld.py/performance.py get their own test files.
"""
import os
from datetime import datetime, timedelta, timezone

from conftest import _valid_employee_payload


def _this_monday():
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def _fresh_institution_hr_manager_auth(client, superadmin_headers):
    """An hr_manager account scoped to a brand-new, throwaway institution —
    NOT the shared session-wide test_institution. The hr_manager approver
    type is role-based and institution-wide (any hr_manager-role account is
    eligible for any pending hr_manager-step item in their institution, not
    just their own subordinates' — see core/approval_workflow.py), so an
    "expect zero todos" assertion against the shared test_institution is
    only true when no *other* test file in the same run has left a pending
    hr_manager-step item behind there — which, across the full suite, isn't
    reliably true. A dedicated fresh institution sidesteps that entirely."""
    code = f"ZZDASHHR{os.urandom(4).hex()}".upper()
    username = f"zzdashhr_admin_{os.urandom(4).hex()}"
    password = "ZzPytest@123"
    create = client.post("/api/institutions", headers=superadmin_headers, json={
        "name": "ZZ Dashboard HR Institution",
        "code": code,
        "contact_email": "zzdashhr@example.com",
        "admin_username": username,
        "admin_full_name": "ZZ Dashboard HR Admin",
        "admin_password": password,
    })
    assert create.status_code == 201, create.text
    inst = create.json()
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": code,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return inst, headers


def test_get_todos_requires_auth(client):
    res = client.get("/api/todos")
    assert res.status_code in (401, 403)


def test_superadmin_gets_empty_todos(client, superadmin_headers):
    res = client.get("/api/todos", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_hr_manager_with_no_employee_record_gets_empty_todos(client, superadmin_headers):
    # A fresh, dedicated institution — not the shared test_institution — so
    # this genuinely starts with zero pending items regardless of what any
    # other test file in this run has left behind there (see
    # _fresh_institution_hr_manager_auth's docstring).
    _, hr_headers = _fresh_institution_hr_manager_auth(client, superadmin_headers)
    res = client.get("/api/todos", headers=hr_headers)
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


def test_pending_leave_approval_appears_as_one_per_item_todo(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    """A pending approval-workflow request (Leave here, but the same
    _approval_row_detail branch structure in routers/dashboard.py covers
    Claims/Requisition/Timesheet/L&D Enrollment/Overtime/Resignation/PIP
    too) shows up as one real row — employee, stage, due date — not
    folded into an aggregate "N items awaiting approval" count. Regression
    coverage for the Phase 2 rollout (see docs/VISUAL_REDESIGN_ROLLOUT_PLAN.md):
    count_pending_for_approver's count-only query became
    pending_rows_for_approver, and the dashboard renders one To-Do per row."""
    emp = make_test_employee()
    username = f"zzdashleave_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Dashboard Leave Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    app = client.post("/api/leave/applications", headers=emp_headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-04-05", "end_date": "2027-04-06",
    })
    assert app.status_code == 201, app.text
    assert app.json()["status"] == "Pending Approval"
    app_id = app.json()["id"]

    # This employee has no manager set, so the default workflow's
    # direct_manager step resolves to nothing and it's immediately at the
    # hr_manager step — hr_manager_auth (no linked employee_id) is exactly
    # the "approving someone else's request" case this feature is for.
    todos = client.get("/api/todos", headers=hr_manager_auth).json()
    key = f"leave-approval-{app_id}"
    match = next((t for t in todos if t["key"] == key), None)
    assert match, f"expected a per-item leave-approval todo, got: {todos}"
    assert match["page"] == "leave-approvals"
    assert match["count"] == 1
    assert match["employee_name"] == emp["full_name"]
    assert match["stage_type"] == "Leave"
    assert match["due_date"] == "2027-04-05"
    assert lt["name"] in match["stage"]
    assert emp["full_name"] in match["label"]
    assert "awaiting your approval" in match["label"]

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_onboarding_checklist_items_appear_for_assigned_role(client, superadmin_headers):
    """A checklist item's assigned_role determines whose To-Do it shows up
    in — the new hire sees their own 'employee'-assigned items, HR sees
    the institution's 'hr_manager'-assigned items — one row per pending
    item (not an aggregate count), each labeled with the item's title so
    the To-Do card shows what the task actually is. See
    routers/dashboard.py's ob_q, which mirrors list_ob_checklists'
    (routers/onboarding.py) existing my_pending scoping.

    Uses a fresh, dedicated institution (not the shared test_institution) —
    this test doubles as the regression check for a real bug found while
    debugging it: routers/onboarding.py's start_checklist queried
    `template_set_id=?` with a bound None whenever an institution had no
    ob_template_sets row yet (only ever used the legacy templates from
    seed_ob_templates, which leave template_set_id NULL) — `x = NULL` is
    never true in SQL even when x genuinely IS NULL, so every such
    institution silently got zero checklist items on every
    POST /api/ob/checklists call. Never surfaced against the shared
    test_institution because an earlier feature (custom template sets) had
    already given it a real ob_template_sets row, masking the bug — a fresh
    institution has no such row, so it reproduces the original bug
    reliably. Now fixed with an explicit `IS NULL` branch."""
    inst, hr_headers = _fresh_institution_hr_manager_auth(client, superadmin_headers)
    inst_code = inst["code"]

    emp_res = client.post("/api/employees", headers=hr_headers,
                           json=_valid_employee_payload(full_name="ZZ Dashboard OB Employee"))
    assert emp_res.status_code == 201, emp_res.text
    emp = emp_res.json()

    username = f"zztdashob_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_headers, json={
        "username": username, "full_name": "ZZ Dashboard OB Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": inst_code,
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    started = client.post("/api/ob/checklists", headers=hr_headers,
                           json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert started.status_code == 201, started.text
    cl_id = started.json()["id"]
    item_ids = {i["id"] for i in client.get(f"/api/ob/checklists/{cl_id}", headers=hr_headers).json()["items"]}

    # The new hire sees their own 'employee'-assigned items (e.g. "Welcome
    # Acknowledgement" in the seeded default templates) as individual rows,
    # not their own name (that'd be redundant for their own to-do).
    emp_todos = client.get("/api/todos", headers=emp_headers).json()
    emp_ob_todos = [t for t in emp_todos if t["key"].startswith("ob-item-") and int(t["key"].removeprefix("ob-item-")) in item_ids]
    assert emp_ob_todos, f"expected at least one ob-item todo, got: {emp_todos}"
    assert all(t["page"] == "onboarding" and t["count"] == 1 for t in emp_ob_todos)
    assert any("Welcome Acknowledgement" in t["label"] for t in emp_ob_todos)
    assert not any(emp["full_name"] in t["label"] for t in emp_ob_todos)

    # HR sees their own 'hr_admin'/'hr_manager'-assigned items across the
    # institution (not the employee's), each labeled with the employee's
    # name since it's someone else's checklist.
    hr_todos = client.get("/api/todos", headers=hr_headers).json()
    hr_ob_todos = [t for t in hr_todos if t["key"].startswith("ob-item-") and int(t["key"].removeprefix("ob-item-")) in item_ids]
    assert hr_ob_todos
    assert all(emp["full_name"] in t["label"] for t in hr_ob_todos)
