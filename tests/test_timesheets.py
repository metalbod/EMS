"""
Integration tests for routers/timesheets.py: the Draft -> Submitted ->
Approved/Rejected status machine, plus entry validation against project
task assignments (open-to-all vs assignment-gated).

Reuses make_test_project/make_test_project_task from conftest.py (shared
with test_projects.py) since every timesheet entry must reference a real
project + task.
"""
import pytest

PERIOD_START = "2027-04-01"
PERIOD_END = "2027-04-30"
ENTRY_DATE = "2027-04-05"  # within the period


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    """A real employee record with a linked login (role=employee)."""
    emp = make_test_employee()
    username = f"zztstest_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Timesheet Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, f"failed to create employee-linked user: {res.text}"
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    yield emp, headers

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


@pytest.fixture
def open_task(hr_manager_auth, client, make_test_project, make_test_project_task):
    """A project + task marked open_to_all, so any employee can log time
    against it without needing an explicit assignment."""
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.patch(
        f"/api/projects/{project['id']}/tasks/{task['id']}/open-to-all",
        headers=hr_manager_auth, json={"open_to_all": True},
    )
    assert res.status_code == 200
    return project, task


@pytest.fixture
def make_test_timesheet(client, employee_with_user):
    """Starts (get-or-creates) a Draft timesheet for the employee_with_user
    fixture's employee, for the fixed test period. No explicit teardown —
    timesheets have no delete endpoint; disposable data accumulates in the
    dedicated ZZPYTEST institution, consistent with employees/leave types."""
    emp, headers = employee_with_user

    def _make():
        res = client.post("/api/timesheets", headers=headers, json={
            "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
        })
        assert res.status_code == 201, f"failed to start test timesheet: {res.text}"
        return res.json()

    return _make


# ---------------------------------------------------------------------------
# List / Start / Get
# ---------------------------------------------------------------------------
def test_list_timesheets_requires_auth(client):
    res = client.get("/api/timesheets")
    assert res.status_code in (401, 403)


def test_start_timesheet_is_idempotent(client, employee_with_user, make_test_timesheet):
    emp, headers = employee_with_user
    first = make_test_timesheet()
    res = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    })
    assert res.status_code == 201
    assert res.json()["id"] == first["id"]


def test_employee_cannot_start_timesheet_for_someone_else(client, employee_with_user):
    emp, headers = employee_with_user
    res = client.post("/api/timesheets", headers=headers, json={
        "employee_id": "EMP_SOMEONE_ELSE", "period_start": PERIOD_START, "period_end": PERIOD_END,
    })
    assert res.status_code == 403


def test_get_timesheet_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/timesheets/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_employee_cannot_view_someone_elses_timesheet(client, employee_with_user, make_test_employee, hr_manager_auth):
    emp, headers = employee_with_user
    ts_res = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    })
    ts_id = ts_res.json()["id"]

    other_emp = make_test_employee()
    other_username = f"zztstest_{other_emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": other_username, "full_name": "ZZ Other Employee",
        "password": password, "role": "employee", "employee_id": other_emp["employee_id"],
    })
    other_user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": other_username, "password": password,
        "institution_code": "ZZPYTEST",
    })
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    res = client.get(f"/api/timesheets/{ts_id}", headers=other_headers)
    assert res.status_code == 403

    client.delete(f"/api/users/{other_user_id}", headers=hr_manager_auth)


def test_get_timesheet_includes_entries_and_total_hours(client, hr_manager_auth, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 8,
    })
    assert res.status_code == 201

    detail = client.get(f"/api/timesheets/{ts['id']}", headers=hr_manager_auth)
    assert detail.status_code == 200
    assert detail.json()["total_hours"] == 8
    assert len(detail.json()["entries"]) == 1


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def test_add_entry_success_when_task_open_to_all(client, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 4,
    })
    assert res.status_code == 201
    assert res.json()["hours"] == 4


def test_add_entry_without_assignment_and_not_open_returns_403(
    client, employee_with_user, make_test_timesheet, make_test_project, make_test_project_task
):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project = make_test_project()
    task = make_test_project_task(project["id"])  # not open_to_all, employee not assigned
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 4,
    })
    assert res.status_code == 403


def test_add_entry_succeeds_when_explicitly_assigned(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, make_test_project, make_test_project_task
):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project = make_test_project()
    task = make_test_project_task(project["id"])
    assign_res = client.post(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth,
        json={"employee_id": emp["employee_id"], "start_datetime": "2027-04-01T09:00", "duration_hours": 8},
    )
    assert assign_res.status_code == 201
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 4,
    })
    assert res.status_code == 201


def test_add_entry_task_not_in_project_returns_400(client, employee_with_user, make_test_timesheet, make_test_project, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    wrong_project = make_test_project()
    _, real_task = open_task
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": wrong_project["id"], "task_id": real_task["id"], "date": ENTRY_DATE, "hours": 4,
    })
    assert res.status_code == 400


def test_add_entry_hours_out_of_range_returns_400(client, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 25,
    })
    assert res.status_code == 400


def test_add_entry_date_outside_period_returns_400(client, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    res = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": "2027-05-15", "hours": 4,
    })
    assert res.status_code == 400


def test_delete_entry_success(client, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    entry = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 4,
    }).json()
    res = client.delete(f"/api/timesheets/{ts['id']}/entries/{entry['id']}", headers=headers)
    assert res.status_code == 204
    detail = client.get(f"/api/timesheets/{ts['id']}", headers=headers).json()
    assert entry["id"] not in [e["id"] for e in detail["entries"]]


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------
def test_submit_empty_timesheet_returns_400(client, employee_with_user, make_test_timesheet):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    res = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert res.status_code == 400
    assert "empty" in res.json()["detail"]


def test_submit_invalid_status_returns_400(client, employee_with_user, make_test_timesheet):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    res = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Bogus"})
    assert res.status_code == 400


def test_status_not_found_returns_404(client, hr_manager_auth):
    res = client.patch("/api/timesheets/999999999/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 404


def test_full_draft_submit_approve_lifecycle(client, hr_manager_auth, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 8,
    })

    submit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert submit.status_code == 200
    assert submit.json()["status"] == "Submitted"

    # Can no longer edit entries once submitted.
    blocked = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 1,
    })
    assert blocked.status_code == 400

    approve = client.patch(f"/api/timesheets/{ts['id']}/status", headers=hr_manager_auth, json={"status": "Approved", "notes": "ZZ looks good"})
    assert approve.status_code == 200
    assert approve.json()["status"] == "Approved"


def test_employee_cannot_approve_timesheets(client, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 8,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    res = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Approved"})
    assert res.status_code == 403


def test_cannot_approve_a_draft_timesheet(client, hr_manager_auth, employee_with_user, make_test_timesheet):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    res = client.patch(f"/api/timesheets/{ts['id']}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 400
    assert "Submitted" in res.json()["detail"]


def test_reject_timesheet(client, hr_manager_auth, employee_with_user, make_test_timesheet, open_task):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    project, task = open_task
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": ENTRY_DATE, "hours": 8,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    res = client.patch(f"/api/timesheets/{ts['id']}/status", headers=hr_manager_auth, json={"status": "Rejected", "notes": "ZZ needs revision"})
    assert res.status_code == 200
    assert res.json()["status"] == "Rejected"


def test_list_timesheets_includes_created(client, hr_manager_auth, employee_with_user, make_test_timesheet):
    emp, headers = employee_with_user
    ts = make_test_timesheet()
    res = client.get("/api/timesheets", headers=hr_manager_auth)
    assert res.status_code == 200
    assert ts["id"] in [t["id"] for t in res.json()]
