"""
Integration tests for routers/projects.py: Projects, Project Tasks, and
Task Assignments. Uses the shared make_test_project/make_test_project_task
fixtures from conftest.py (also reused by leave/timesheets tests, since
both need a real project+task to log time against).
"""
import os
from datetime import date, timedelta

import pytest


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def test_list_projects_requires_auth(client):
    res = client.get("/api/projects")
    assert res.status_code in (401, 403)


def test_create_project_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/projects", headers=headers, json={"name": "ZZ", "status": "Active"})
    assert res.status_code == 403


def test_create_project_success(client, make_test_project):
    project = make_test_project(name="ZZ Special Project")
    assert project["name"] == "ZZ Special Project"
    assert project["status"] == "Active"


def test_create_project_missing_name_returns_422(client, hr_manager_auth):
    res = client.post("/api/projects", headers=hr_manager_auth, json={"status": "Active"})
    assert res.status_code == 422


def test_list_projects_includes_created_project(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.get("/api/projects", headers=hr_manager_auth)
    assert res.status_code == 200
    assert project["id"] in [p["id"] for p in res.json()]


def test_list_projects_filters_by_status(client, hr_manager_auth, make_test_project):
    project = make_test_project(status="On Hold")
    active_only = client.get("/api/projects", headers=hr_manager_auth, params={"status": "Active"}).json()
    assert project["id"] not in [p["id"] for p in active_only]

    on_hold_only = client.get("/api/projects", headers=hr_manager_auth, params={"status": "On Hold"}).json()
    assert project["id"] in [p["id"] for p in on_hold_only]


def test_update_project_success(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.put(
        f"/api/projects/{project['id']}", headers=hr_manager_auth,
        json={"name": "ZZ Renamed", "status": "Completed"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "ZZ Renamed"
    assert res.json()["status"] == "Completed"


def test_update_project_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/projects/999999999", headers=hr_manager_auth, json={"name": "ZZ", "status": "Active"})
    assert res.status_code == 404


def test_create_project_with_customer(client, hr_manager_auth, make_test_project):
    project = make_test_project(name="ZZ Customer Project", customer="ZZ Customer Co")
    assert project["customer"] == "ZZ Customer Co"

    listing = client.get("/api/projects", headers=hr_manager_auth).json()
    row = next(p for p in listing if p["id"] == project["id"])
    assert row["customer"] == "ZZ Customer Co"


def test_create_project_without_customer_defaults_to_none(client, make_test_project):
    project = make_test_project(name="ZZ No Customer Project")
    assert project["customer"] is None


def test_update_project_can_set_and_clear_customer(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.put(
        f"/api/projects/{project['id']}", headers=hr_manager_auth,
        json={"name": project["name"], "status": "Active", "customer": "ZZ Updated Customer"},
    )
    assert res.status_code == 200
    assert res.json()["customer"] == "ZZ Updated Customer"

    # customer has no default in ProjectIn beyond None, so omitting it on a
    # later update (a full-replace PUT, same as every other project field)
    # clears it rather than leaving the previous value in place.
    res = client.put(
        f"/api/projects/{project['id']}", headers=hr_manager_auth,
        json={"name": project["name"], "status": "Active"},
    )
    assert res.status_code == 200
    assert res.json()["customer"] is None


def test_create_project_with_managers(client, hr_manager_auth, make_test_employee):
    mgr1 = make_test_employee(full_name="ZZ Project Manager One")
    mgr2 = make_test_employee(full_name="ZZ Project Manager Two")
    res = client.post("/api/projects", headers=hr_manager_auth, json={
        "name": "ZZ Managed Project", "status": "Active",
        "manager_ids": [mgr1["employee_id"], mgr2["employee_id"]],
    })
    assert res.status_code == 201, res.text
    assert sorted(res.json()["manager_ids"]) == sorted([mgr1["employee_id"], mgr2["employee_id"]])

    listing = client.get("/api/projects", headers=hr_manager_auth).json()
    row = next(p for p in listing if p["id"] == res.json()["id"])
    assert sorted(row["manager_ids"]) == sorted([mgr1["employee_id"], mgr2["employee_id"]])


def test_create_project_with_unknown_manager_returns_404(client, hr_manager_auth):
    res = client.post("/api/projects", headers=hr_manager_auth, json={
        "name": "ZZ Bad Manager Project", "status": "Active", "manager_ids": ["NOPE_NOT_REAL"],
    })
    assert res.status_code == 404


def test_update_project_managers_replaces_set(client, hr_manager_auth, make_test_employee, make_test_project):
    mgr1 = make_test_employee(full_name="ZZ Replace Manager One")
    mgr2 = make_test_employee(full_name="ZZ Replace Manager Two")
    project = make_test_project()

    client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth,
               json={"name": project["name"], "status": "Active", "manager_ids": [mgr1["employee_id"]]})
    res = client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth,
                      json={"name": project["name"], "status": "Active", "manager_ids": [mgr2["employee_id"]]})
    assert res.status_code == 200
    assert res.json()["manager_ids"] == [mgr2["employee_id"]]


def test_create_project_with_members(client, hr_manager_auth, make_test_employee):
    """Team members are assigned at the project level (not per task) — see
    module docstring update in routers/projects.py."""
    mem1 = make_test_employee(full_name="ZZ Project Member One")
    mem2 = make_test_employee(full_name="ZZ Project Member Two")
    res = client.post("/api/projects", headers=hr_manager_auth, json={
        "name": "ZZ Member Project", "status": "Active",
        "member_ids": [mem1["employee_id"], mem2["employee_id"]],
    })
    assert res.status_code == 201, res.text
    assert sorted(res.json()["member_ids"]) == sorted([mem1["employee_id"], mem2["employee_id"]])

    listing = client.get("/api/projects", headers=hr_manager_auth).json()
    row = next(p for p in listing if p["id"] == res.json()["id"])
    assert sorted(row["member_ids"]) == sorted([mem1["employee_id"], mem2["employee_id"]])
    assert row["member_count"] == 2


def test_create_project_with_unknown_member_returns_404(client, hr_manager_auth):
    res = client.post("/api/projects", headers=hr_manager_auth, json={
        "name": "ZZ Bad Member Project", "status": "Active", "member_ids": ["NOPE_NOT_REAL"],
    })
    assert res.status_code == 404


def test_update_project_members_replaces_set(client, hr_manager_auth, make_test_employee, make_test_project):
    mem1 = make_test_employee(full_name="ZZ Replace Member One")
    mem2 = make_test_employee(full_name="ZZ Replace Member Two")
    project = make_test_project()

    client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth,
               json={"name": project["name"], "status": "Active", "member_ids": [mem1["employee_id"]]})
    res = client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth,
                      json={"name": project["name"], "status": "Active", "member_ids": [mem2["employee_id"]]})
    assert res.status_code == 200
    assert res.json()["member_ids"] == [mem2["employee_id"]]


def test_project_is_open_to_all_and_is_billable_persist(client, hr_manager_auth, make_test_project):
    """Both default false; both persist through create and update. is_billable
    is a plain flag today — project-cost calculations on top of it are
    separate, later work."""
    project = make_test_project()
    assert project["is_open_to_all"] in (False, 0)
    assert project["is_billable"] in (False, 0)

    res = client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth, json={
        "name": project["name"], "status": "Active", "is_open_to_all": True, "is_billable": True,
    })
    assert res.status_code == 200
    assert res.json()["is_open_to_all"] in (True, 1)
    assert res.json()["is_billable"] in (True, 1)


def test_project_start_end_date_persist(client, hr_manager_auth, make_test_project):
    """Informational only — not checked against timesheet entries (see
    routers/projects.py's ProjectIn docstring comment)."""
    project = make_test_project(start_date="2027-01-01", end_date="2027-12-31")
    assert project["start_date"] == "2027-01-01"
    assert project["end_date"] == "2027-12-31"

    res = client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth, json={
        "name": project["name"], "status": "Active", "start_date": "2027-02-01", "end_date": "2027-11-30",
    })
    assert res.status_code == 200
    assert res.json()["start_date"] == "2027-02-01"
    assert res.json()["end_date"] == "2027-11-30"


def test_create_project_end_before_start_returns_400(client, hr_manager_auth):
    res = client.post("/api/projects", headers=hr_manager_auth, json={
        "name": "ZZ Bad Dates", "status": "Active", "start_date": "2027-02-01", "end_date": "2027-01-01",
    })
    assert res.status_code == 400


def test_update_project_end_before_start_returns_400(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth, json={
        "name": project["name"], "status": "Active", "start_date": "2027-02-01", "end_date": "2027-01-01",
    })
    assert res.status_code == 400


def test_delete_project_success(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.delete(f"/api/projects/{project['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/projects", headers=hr_manager_auth).json()
    assert project["id"] not in [p["id"] for p in listed]


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------
def _cleanup_duplicated_project(client, hr_manager_auth, project_id):
    """Duplicates aren't tracked by make_test_project's own teardown (they're
    created via a different endpoint) — delete child tasks first (FK), same
    defensive order make_test_project's teardown uses."""
    tasks = client.get(f"/api/projects/{project_id}/tasks", headers=hr_manager_auth)
    if tasks.status_code == 200:
        for task in tasks.json():
            client.delete(f"/api/projects/{project_id}/tasks/{task['id']}", headers=hr_manager_auth)
    client.delete(f"/api/projects/{project_id}", headers=hr_manager_auth)


def test_duplicate_project_requires_manage_role(client, make_test_user, test_institution, make_test_project):
    project = make_test_project()
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=headers,
                       json={"name": "ZZ Dup", "duplicate_scope": "tasks_only"})
    assert res.status_code == 403


def test_duplicate_project_not_found_returns_404(client, hr_manager_auth):
    res = client.post("/api/projects/999999999/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup", "duplicate_scope": "tasks_only"})
    assert res.status_code == 404


def test_duplicate_project_invalid_scope_returns_422(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup", "duplicate_scope": "everything"})
    assert res.status_code == 422


def test_duplicate_project_missing_name_returns_400(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "   ", "duplicate_scope": "tasks_only"})
    assert res.status_code == 400


def test_duplicate_project_carries_description_and_flags_and_forces_active(
    client, hr_manager_auth, make_test_project
):
    project = make_test_project(
        name="ZZ Source Project", description="ZZ desc", customer="ZZ Dup Customer Co", status="Completed",
        is_open_to_all=True, is_billable=True,
    )
    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup Flags", "duplicate_scope": "tasks_only"})
    assert res.status_code == 201, res.text
    dup = res.json()
    assert dup["name"] == "ZZ Dup Flags"
    assert dup["description"] == "ZZ desc"
    assert dup["customer"] == "ZZ Dup Customer Co"
    assert dup["is_open_to_all"] in (True, 1)
    assert dup["is_billable"] in (True, 1)
    assert dup["status"] == "Active"  # fresh-start clone, regardless of source status
    _cleanup_duplicated_project(client, hr_manager_auth, dup["id"])


def test_duplicate_project_tasks_only_copies_tasks_but_not_members(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task
):
    mgr = make_test_employee(full_name="ZZ Dup Manager")
    mem = make_test_employee(full_name="ZZ Dup Member")
    project = make_test_project(manager_ids=[mgr["employee_id"]], member_ids=[mem["employee_id"]])
    make_test_project_task(project["id"], name="ZZ Task A", estimated_hours=5,
                           start_date="2027-01-01", end_date="2027-01-05", status="In Progress")

    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup Tasks Only", "duplicate_scope": "tasks_only"})
    assert res.status_code == 201, res.text
    dup = res.json()
    assert dup["manager_ids"] == []
    assert dup["member_ids"] == []

    tasks = client.get(f"/api/projects/{dup['id']}/tasks", headers=hr_manager_auth).json()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "ZZ Task A"
    assert tasks[0]["estimated_hours"] == 5
    # Fresh-start clone: status reset, dates cleared.
    assert tasks[0]["status"] == "Not Started"
    assert tasks[0]["start_date"] is None
    assert tasks[0]["end_date"] is None
    _cleanup_duplicated_project(client, hr_manager_auth, dup["id"])


def test_duplicate_project_members_only_copies_managers_and_members_but_not_tasks(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task
):
    mgr = make_test_employee(full_name="ZZ Dup Manager2")
    mem = make_test_employee(full_name="ZZ Dup Member2")
    project = make_test_project(manager_ids=[mgr["employee_id"]], member_ids=[mem["employee_id"]])
    make_test_project_task(project["id"], name="ZZ Task B")

    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup Members Only", "duplicate_scope": "members_only"})
    assert res.status_code == 201, res.text
    dup = res.json()
    assert dup["manager_ids"] == [mgr["employee_id"]]
    assert dup["member_ids"] == [mem["employee_id"]]

    tasks = client.get(f"/api/projects/{dup['id']}/tasks", headers=hr_manager_auth).json()
    assert tasks == []
    _cleanup_duplicated_project(client, hr_manager_auth, dup["id"])


def test_duplicate_project_tasks_and_members_copies_both(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task
):
    mgr = make_test_employee(full_name="ZZ Dup Manager3")
    mem = make_test_employee(full_name="ZZ Dup Member3")
    project = make_test_project(manager_ids=[mgr["employee_id"]], member_ids=[mem["employee_id"]])
    make_test_project_task(project["id"], name="ZZ Task C")

    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup Both", "duplicate_scope": "tasks_and_members"})
    assert res.status_code == 201, res.text
    dup = res.json()
    assert dup["manager_ids"] == [mgr["employee_id"]]
    assert dup["member_ids"] == [mem["employee_id"]]

    tasks = client.get(f"/api/projects/{dup['id']}/tasks", headers=hr_manager_auth).json()
    assert len(tasks) == 1 and tasks[0]["name"] == "ZZ Task C"
    _cleanup_duplicated_project(client, hr_manager_auth, dup["id"])


def test_duplicate_project_does_not_mutate_source(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task
):
    """Duplicating is purely additive — the source project's own tasks/
    members/status must be untouched afterward."""
    mgr = make_test_employee(full_name="ZZ Dup Manager4")
    project = make_test_project(manager_ids=[mgr["employee_id"]], status="On Hold")
    task = make_test_project_task(project["id"], name="ZZ Task D")

    res = client.post(f"/api/projects/{project['id']}/duplicate", headers=hr_manager_auth,
                       json={"name": "ZZ Dup NoMutate", "duplicate_scope": "tasks_and_members"})
    assert res.status_code == 201, res.text
    dup = res.json()

    source_after = next(p for p in client.get("/api/projects", headers=hr_manager_auth).json() if p["id"] == project["id"])
    assert source_after["status"] == "On Hold"
    assert source_after["manager_ids"] == [mgr["employee_id"]]
    source_tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth).json()
    assert [t["id"] for t in source_tasks] == [task["id"]]
    _cleanup_duplicated_project(client, hr_manager_auth, dup["id"])


def test_project_utilization_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/projects/utilization", headers=headers)
    assert res.status_code == 403


def test_project_utilization_includes_active_project(client, hr_manager_auth, make_test_project):
    project = make_test_project(status="Active")
    res = client.get("/api/projects/utilization", headers=hr_manager_auth)
    assert res.status_code == 200
    assert project["id"] in [p["id"] for p in res.json()]


def test_project_utilization_total_estimated_sums_only_estimated_tasks(
    client, hr_manager_auth, make_test_project, make_test_project_task
):
    """total_estimated_hours is the sum of task-level estimates only — a
    task with no estimate at all doesn't count as a 0-hour budget, it's
    just excluded from the total (see get_project_utilization)."""
    project = make_test_project(status="Active")
    make_test_project_task(project["id"], estimated_hours=10)
    make_test_project_task(project["id"], estimated_hours=5)
    make_test_project_task(project["id"])  # no estimate

    res = client.get("/api/projects/utilization", headers=hr_manager_auth)
    assert res.status_code == 200
    body = next(p for p in res.json() if p["id"] == project["id"])
    assert body["total_estimated_hours"] == 15
    assert body["total_hours"] == 0


def test_project_utilization_total_estimated_is_none_when_no_task_has_one(
    client, hr_manager_auth, make_test_project, make_test_project_task
):
    project = make_test_project(status="Active")
    make_test_project_task(project["id"])  # no estimate

    res = client.get("/api/projects/utilization", headers=hr_manager_auth)
    body = next(p for p in res.json() if p["id"] == project["id"])
    assert body["total_estimated_hours"] is None


# ---------------------------------------------------------------------------
# Timesheet dashboard (Home dashboard's Timesheet tab —
# GET /api/projects/timesheet-dashboard)
# ---------------------------------------------------------------------------
def _monday_of_week(d):
    return d - timedelta(days=d.weekday())


def _ym(d):
    return d.strftime("%Y-%m")


def _add_months(d, delta):
    m = d.month - 1 + delta
    y = d.year + m // 12
    m = m % 12 + 1
    return d.replace(year=y, month=m, day=1)


def _log_and_approve_hours(client, headers, emp, project, task, entry_date, hours, approver_headers):
    """Starts (get-or-creates) the timesheet whose week contains
    entry_date, logs an entry, submits it, and — only when
    approver_headers is given — approves that project on it. The
    timesheet-dashboard endpoint only counts *approved* hours, so a test
    proving that must be able to log hours that stay merely Submitted."""
    period_start = _monday_of_week(entry_date)
    period_end = period_start + timedelta(days=6)
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
    })
    assert ts.status_code == 201, f"failed to start test timesheet: {ts.text}"
    ts_id = ts.json()["id"]
    entry = client.post(f"/api/timesheets/{ts_id}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": entry_date.isoformat(), "hours": hours,
    })
    assert entry.status_code == 201, f"failed to log test entry: {entry.text}"
    submit = client.patch(f"/api/timesheets/{ts_id}/status", headers=headers, json={"status": "Submitted"})
    assert submit.status_code == 200, submit.text
    if approver_headers:
        approve = client.patch(f"/api/timesheets/{ts_id}/projects/{project['id']}/status", headers=approver_headers,
                                json={"status": "Approved"})
        assert approve.status_code == 200, approve.text
    return ts_id


def test_timesheet_dashboard_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/projects/timesheet-dashboard", headers=headers)
    assert res.status_code == 403


def test_timesheet_dashboard_covers_trailing_six_months_in_order(client, hr_manager_auth):
    res = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    months = res.json()["months"]
    assert len(months) == 6
    today = date.today().replace(day=1)
    expected_keys = [_ym(_add_months(today, -i)) for i in range(5, -1, -1)]
    assert [m["year_month"] for m in months] == expected_keys
    assert months[-1]["label"] == date.today().strftime("%b %Y")
    assert all(m["total_hours"] == m["billable_hours"] + m["non_billable_hours"] for m in months)


def test_timesheet_dashboard_missing_hours_month_label_is_current_month(client, hr_manager_auth):
    res = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth)
    assert res.json()["missing_hours_month_label"] == date.today().strftime("%B %Y")


def test_timesheet_dashboard_missing_hours_top10_shape(client, hr_manager_auth):
    """Structural invariants that must hold no matter how much other test
    data has already piled up in the shared test institution (see the
    isolated-institution test below for the actual ranking behavior)."""
    res = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth)
    top10 = res.json()["missing_hours_top10"]
    assert len(top10) <= 10
    assert all(e["missing_hours"] > 0 for e in top10)
    hours = [e["missing_hours"] for e in top10]
    assert hours == sorted(hours, reverse=True)


def test_timesheet_dashboard_only_counts_approved_hours(
    client, hr_manager_auth, employee_with_login, make_test_project, make_test_project_task
):
    """The merely-Submitted employee's hours must not move the current
    month's billable total at all — only the Approved one's do. Two
    different employees on the same project (rather than one employee on
    two projects) avoids the same-timesheet's own status/lock
    interactions entirely."""
    approved_emp, approved_headers = employee_with_login(full_name="ZZ Approved Hours Employee")
    unapproved_emp, unapproved_headers = employee_with_login(full_name="ZZ Unapproved Hours Employee")
    project = make_test_project(is_billable=True, is_open_to_all=True, name="ZZ Dashboard Approval Project")
    task = make_test_project_task(project["id"])

    before = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth).json()["months"][-1]["billable_hours"]

    _log_and_approve_hours(client, approved_headers, approved_emp, project, task, date.today(), 5, hr_manager_auth)
    _log_and_approve_hours(client, unapproved_headers, unapproved_emp, project, task, date.today(), 3, None)

    after = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth).json()["months"][-1]["billable_hours"]
    assert after - before == 5


def test_timesheet_dashboard_splits_billable_and_non_billable(
    client, hr_manager_auth, employee_with_login, make_test_project, make_test_project_task
):
    billable_emp, billable_headers = employee_with_login(full_name="ZZ Billable Split Employee")
    non_billable_emp, non_billable_headers = employee_with_login(full_name="ZZ Non-billable Split Employee")
    billable_project = make_test_project(is_billable=True, is_open_to_all=True, name="ZZ Split Billable Project")
    billable_task = make_test_project_task(billable_project["id"])
    non_billable_project = make_test_project(is_billable=False, is_open_to_all=True, name="ZZ Split Non-billable Project")
    non_billable_task = make_test_project_task(non_billable_project["id"])

    before = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth).json()["months"][-1]

    _log_and_approve_hours(client, billable_headers, billable_emp, billable_project, billable_task,
                            date.today(), 5, hr_manager_auth)
    _log_and_approve_hours(client, non_billable_headers, non_billable_emp, non_billable_project, non_billable_task,
                            date.today(), 3, hr_manager_auth)

    after = client.get("/api/projects/timesheet-dashboard", headers=hr_manager_auth).json()["months"][-1]
    assert after["billable_hours"] - before["billable_hours"] == 5
    assert after["non_billable_hours"] - before["non_billable_hours"] == 3
    assert after["total_hours"] - before["total_hours"] == 8


def test_timesheet_dashboard_missing_hours_ranked_descending_isolated(client, superadmin_headers):
    """Isolated in its own throwaway institution (same technique as
    test_rls_enforcement.py's "institution B") instead of the shared
    test_institution — that one accumulates far too many employees across
    a full suite run (many of whom never log any hours at all) to assert
    a specific ranking against an unknown, unbounded set of competitors
    for a top-10-capped list."""
    from conftest import _valid_employee_payload

    payload = {
        "name": "ZZ Missing Hours Test Institution", "code": f"ZZMH{os.urandom(4).hex()}".upper(),
        "contact_email": "zzmissinghours@example.com",
        "admin_username": f"zzmissing_admin_{os.urandom(4).hex()}",
        "admin_full_name": "ZZ Missing Hours Admin", "admin_password": "ZzPytest@123",
    }
    create = client.post("/api/institutions", headers=superadmin_headers, json=payload)
    assert create.status_code == 201, create.text
    inst_b = create.json()
    login = client.post("/api/auth/login", json={
        "username": payload["admin_username"], "password": payload["admin_password"],
        "institution_code": inst_b["code"],
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    busy = client.post("/api/employees", headers=headers, json=_valid_employee_payload(full_name="ZZ Busy Employee")).json()
    idle = client.post("/api/employees", headers=headers, json=_valid_employee_payload(full_name="ZZ Idle Employee")).json()
    project = client.post("/api/projects", headers=headers, json={
        "name": "ZZ Missing Hours Project", "status": "Active", "is_open_to_all": True,
    }).json()
    task = client.post(f"/api/projects/{project['id']}/tasks", headers=headers, json={
        "name": "ZZ Missing Hours Task", "status": "Not Started",
    }).json()

    today = date.today()
    period_start = _monday_of_week(today)
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": busy["employee_id"], "period_start": period_start.isoformat(),
        "period_end": (period_start + timedelta(days=6)).isoformat(),
    }).json()
    entry = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": today.isoformat(), "hours": 8,
    })
    assert entry.status_code == 201, entry.text

    res = client.get("/api/projects/timesheet-dashboard", headers=headers)
    assert res.status_code == 200, res.text
    top10 = res.json()["missing_hours_top10"]

    idle_entry = next(e for e in top10 if e["employee_id"] == idle["employee_id"])
    busy_entry = next((e for e in top10 if e["employee_id"] == busy["employee_id"]), None)
    busy_missing = busy_entry["missing_hours"] if busy_entry else 0.0
    assert idle_entry["missing_hours"] > busy_missing, \
        "an employee who logged no hours must show more missing hours than one who logged some"
    hours = [e["missing_hours"] for e in top10]
    assert hours == sorted(hours, reverse=True)


def test_my_projects_empty_for_user_with_no_employee_record(client, hr_manager_auth):
    """The hr_manager test user has no linked employee_id."""
    res = client.get("/api/projects/mine", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == []


def test_my_projects_includes_open_to_all_project(client, hr_manager_auth, employee_with_login, make_test_project):
    """Regression test: the previous query compared is_open_to_all=1, which
    is valid against the old INTEGER 0/1 column (project_tasks.open_to_all)
    but not against this genuine Postgres BOOLEAN column — every call to
    this endpoint 500'd for a real employee with any is_open_to_all
    project in the institution (every employee's My Timesheet project
    selector), never caught because the only other coverage here
    (test_my_projects_empty_for_user_with_no_employee_record) short-
    circuits before reaching this query at all."""
    emp, emp_headers = employee_with_login()
    project = make_test_project(is_open_to_all=True)
    res = client.get("/api/projects/mine", headers=emp_headers)
    assert res.status_code == 200, res.text
    assert project["id"] in [p["id"] for p in res.json()]


def test_my_projects_includes_member_project_but_not_unrelated_one(
    client, hr_manager_auth, employee_with_login, make_test_project
):
    emp, emp_headers = employee_with_login()
    member_project = make_test_project(member_ids=[emp["employee_id"]])
    other_project = make_test_project()  # not open, not a member
    ids = [p["id"] for p in client.get("/api/projects/mine", headers=emp_headers).json()]
    assert member_project["id"] in ids
    assert other_project["id"] not in ids


# ---------------------------------------------------------------------------
# Project Tasks
# ---------------------------------------------------------------------------
def test_create_task_success(client, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"], name="ZZ Design phase", estimated_hours=10)
    assert task["name"] == "ZZ Design phase"
    assert task["estimated_hours"] == 10


def test_create_task_for_nonexistent_project_returns_404(client, hr_manager_auth):
    res = client.post("/api/projects/999999999/tasks", headers=hr_manager_auth, json={"name": "ZZ"})
    assert res.status_code == 404


def test_create_task_end_before_start_returns_400(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.post(
        f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth,
        json={"name": "ZZ", "start_date": "2026-02-01", "end_date": "2026-01-01"},
    )
    assert res.status_code == 400


def test_create_task_start_before_project_start_returns_400(client, hr_manager_auth, make_test_project):
    project = make_test_project(start_date="2027-03-01", end_date="2027-06-30")
    res = client.post(
        f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth,
        json={"name": "ZZ", "start_date": "2027-02-01"},
    )
    assert res.status_code == 400


def test_create_task_end_after_project_end_returns_400(client, hr_manager_auth, make_test_project):
    project = make_test_project(start_date="2027-03-01", end_date="2027-06-30")
    res = client.post(
        f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth,
        json={"name": "ZZ", "end_date": "2027-07-01"},
    )
    assert res.status_code == 400


def test_create_task_dates_on_project_boundary_allowed(client, hr_manager_auth, make_test_project, make_test_project_task):
    """Inclusive boundary — a task can start/end exactly on the project's
    own start/end date."""
    project = make_test_project(start_date="2027-03-01", end_date="2027-06-30")
    task = make_test_project_task(project["id"], start_date="2027-03-01", end_date="2027-06-30")
    assert task["start_date"] == "2027-03-01"
    assert task["end_date"] == "2027-06-30"


def test_create_task_dates_within_project_range_allowed(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project(start_date="2027-03-01", end_date="2027-06-30")
    task = make_test_project_task(project["id"], start_date="2027-04-01", end_date="2027-05-01")
    assert task["start_date"] == "2027-04-01"


def test_create_task_dates_allowed_when_project_has_no_dates(client, hr_manager_auth, make_test_project, make_test_project_task):
    """The project's own dates are informational-only — with none set,
    tasks impose no constraint on themselves either."""
    project = make_test_project()
    task = make_test_project_task(project["id"], start_date="2020-01-01", end_date="2099-12-31")
    assert task["start_date"] == "2020-01-01"


def test_create_task_start_allowed_with_only_project_end_set(client, hr_manager_auth, make_test_project, make_test_project_task):
    """Each side is checked independently — a task start date isn't
    constrained just because the project happens to have an end date."""
    project = make_test_project(end_date="2027-06-30")
    task = make_test_project_task(project["id"], start_date="2020-01-01")
    assert task["start_date"] == "2020-01-01"


def test_update_task_end_after_project_end_returns_400(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project(start_date="2027-03-01", end_date="2027-06-30")
    task = make_test_project_task(project["id"])
    res = client.put(
        f"/api/projects/{project['id']}/tasks/{task['id']}", headers=hr_manager_auth,
        json={"name": task["name"], "end_date": "2027-07-01"},
    )
    assert res.status_code == 400


def test_list_tasks_includes_created_task(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.get(f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth)
    assert res.status_code == 200
    assert task["id"] in [t["id"] for t in res.json()]


def test_non_member_sees_no_tasks_unless_project_is_open_to_all(
    client, hr_manager_auth, employee_with_login, make_test_project, make_test_project_task
):
    """Team membership (and its "open to all" escape hatch) lives at the
    project level now, not per task — a non-member either sees every task
    (project open) or none at all (project closed), never a per-task mix."""
    project = make_test_project()
    task = make_test_project_task(project["id"], name="ZZ Task")
    emp, emp_headers = employee_with_login()

    res = client.get(f"/api/projects/{project['id']}/tasks", headers=emp_headers)
    assert res.status_code == 200
    assert res.json() == []

    open_res = client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth,
                           json={"name": project["name"], "status": "Active", "is_open_to_all": True})
    assert open_res.status_code == 200

    res = client.get(f"/api/projects/{project['id']}/tasks", headers=emp_headers)
    assert res.status_code == 200
    assert task["id"] in [t["id"] for t in res.json()]


def test_project_member_sees_all_tasks(
    client, hr_manager_auth, employee_with_login, make_test_project, make_test_project_task
):
    emp, emp_headers = employee_with_login()
    project = make_test_project(name="ZZ Member Visibility Project", member_ids=[emp["employee_id"]])
    task = make_test_project_task(project["id"], name="ZZ Member Task")

    res = client.get(f"/api/projects/{project['id']}/tasks", headers=emp_headers)
    assert res.status_code == 200
    assert task["id"] in [t["id"] for t in res.json()]


def test_update_task_success(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.put(
        f"/api/projects/{project['id']}/tasks/{task['id']}", headers=hr_manager_auth,
        json={"name": "ZZ Updated Task", "status": "In Progress"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "ZZ Updated Task"


def test_update_task_not_found_returns_404(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.put(f"/api/projects/{project['id']}/tasks/999999999", headers=hr_manager_auth, json={"name": "ZZ"})
    assert res.status_code == 404


def test_delete_task_success(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.delete(f"/api/projects/{project['id']}/tasks/{task['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get(f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth).json()
    assert task["id"] not in [t["id"] for t in listed]

