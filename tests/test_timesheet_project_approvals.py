"""Integration tests for the per-project Timesheet approval split
(timesheet_project_approvals, added 2026-09-17 — see
migrations/versions/20260917_0001_per_project_timesheet_overtime_approval.py
and routers/timesheets.py's _reconcile_timesheet_project_approvals/
_check_timesheet_entry_editable/_expand_timesheet_rows).

Covers what test_timesheets.py's existing single-project lifecycle tests
don't: a timesheet spanning multiple projects gets one independent
approval row per project, approving/rejecting one never touches another,
a rejected project's entries (only) reopen for editing, and resubmitting
reconciles just what changed.
"""
import pytest

PERIOD_START = "2027-05-01"
PERIOD_END = "2027-05-31"
ENTRY_DATE = "2027-05-10"


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    emp = make_test_employee()
    username = f"zztppatest_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Timesheet Project Approval Test Employee",
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
def two_open_tasks(hr_manager_auth, make_test_project, make_test_project_task):
    """Two separate is_open_to_all projects, each with one task — for
    testing a single timesheet that spans multiple projects."""
    project_a = make_test_project(name="ZZ TPA Project A", is_open_to_all=True)
    task_a = make_test_project_task(project_a["id"])
    project_b = make_test_project(name="ZZ TPA Project B", is_open_to_all=True)
    task_b = make_test_project_task(project_b["id"])
    return (project_a, task_a), (project_b, task_b)


@pytest.fixture
def make_test_timesheet(client, employee_with_user):
    emp, headers = employee_with_user

    def _make():
        res = client.post("/api/timesheets", headers=headers, json={
            "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
        })
        assert res.status_code == 201, f"failed to start test timesheet: {res.text}"
        return res.json()

    return _make


def test_submit_creates_one_approval_row_per_project(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    emp, headers = employee_with_user
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 3,
    })
    submit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert submit.status_code == 200

    detail = client.get(f"/api/timesheets/{ts['id']}", headers=hr_manager_auth).json()
    approvals = {a["project_id"]: a for a in detail["project_approvals"]}
    assert set(approvals) == {project_a["id"], project_b["id"]}
    assert approvals[project_a["id"]]["status"] == "Submitted"
    assert approvals[project_a["id"]]["total_hours"] == 5
    assert approvals[project_b["id"]]["status"] == "Submitted"
    assert approvals[project_b["id"]]["total_hours"] == 3


def test_approving_one_project_does_not_affect_the_other(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    emp, headers = employee_with_user
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 3,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})

    approve_a = client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                             headers=hr_manager_auth, json={"status": "Approved"})
    assert approve_a.status_code == 200
    assert approve_a.json()["status"] == "Approved"

    detail = client.get(f"/api/timesheets/{ts['id']}", headers=hr_manager_auth).json()
    approvals = {a["project_id"]: a for a in detail["project_approvals"]}
    assert approvals[project_a["id"]]["status"] == "Approved"
    assert approvals[project_b["id"]]["status"] == "Submitted"  # untouched


def test_rejecting_one_project_reopens_only_its_own_entries(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    emp, headers = employee_with_user
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 3,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})

    reject_a = client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                            headers=hr_manager_auth, json={"status": "Rejected", "notes": "ZZ fix hours"})
    assert reject_a.status_code == 200

    # Project A reopened for editing...
    edit_a = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 1,
    })
    assert edit_a.status_code == 201, edit_a.text

    # ...but Project B (still Submitted) stays locked.
    edit_b = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 1,
    })
    assert edit_b.status_code == 400
    assert "already Submitted" in edit_b.json()["detail"]


def test_resubmit_after_rejection_restarts_only_that_projects_workflow(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    emp, headers = employee_with_user
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 3,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                headers=hr_manager_auth, json={"status": "Rejected"})
    client.patch(f"/api/timesheets/{ts['id']}/projects/{project_b['id']}/status",
                headers=hr_manager_auth, json={"status": "Approved"})

    resubmit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert resubmit.status_code == 200

    detail = client.get(f"/api/timesheets/{ts['id']}", headers=hr_manager_auth).json()
    approvals = {a["project_id"]: a for a in detail["project_approvals"]}
    assert approvals[project_a["id"]]["status"] == "Submitted"  # back in flight
    assert approvals[project_b["id"]]["status"] == "Approved"  # untouched by the resubmit


def test_new_project_added_after_first_submission_can_be_submitted_independently(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    """Adding hours to a project never touched before, on a week that's
    already Submitted overall, is allowed (see
    _check_timesheet_entry_editable) — and submitting again starts that
    project's own workflow without disturbing the first project's."""
    emp, headers = employee_with_user
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                headers=hr_manager_auth, json={"status": "Approved"})

    add_new = client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 2,
    })
    assert add_new.status_code == 201, add_new.text

    resubmit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert resubmit.status_code == 200

    detail = client.get(f"/api/timesheets/{ts['id']}", headers=hr_manager_auth).json()
    approvals = {a["project_id"]: a for a in detail["project_approvals"]}
    assert approvals[project_a["id"]]["status"] == "Approved"  # untouched
    assert approvals[project_b["id"]]["status"] == "Submitted"  # newly started


def test_approve_project_never_submitted_returns_404(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    (project_a, _), _ = two_open_tasks
    ts = make_test_timesheet()
    res = client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                       headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 404  # never submitted -> no approval row for that project yet


def test_approve_already_decided_project_returns_400(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    emp, headers = employee_with_user
    (project_a, task_a), _ = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                headers=hr_manager_auth, json={"status": "Approved"})

    res = client.patch(f"/api/timesheets/{ts['id']}/projects/{project_a['id']}/status",
                       headers=hr_manager_auth, json={"status": "Rejected"})
    assert res.status_code == 400
    assert "already Approved" in res.json()["detail"]


def test_list_timesheets_project_filter_and_sort(
    client, hr_manager_auth, employee_with_user, make_test_timesheet, two_open_tasks
):
    emp, headers = employee_with_user
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = make_test_timesheet()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": ENTRY_DATE, "hours": 5,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": ENTRY_DATE, "hours": 3,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})

    # Filtering by employee_id (since the shared test institution
    # accumulates rows) — filtering by project_id then narrows to just
    # that project's own row for this timesheet.
    both = client.get("/api/timesheets", headers=hr_manager_auth,
                      params={"employee_id": emp["employee_id"], "status": "Submitted"}).json()
    assert len(both) == 2
    assert {r["project_id"] for r in both} == {project_a["id"], project_b["id"]}

    only_a = client.get("/api/timesheets", headers=hr_manager_auth,
                        params={"employee_id": emp["employee_id"], "status": "Submitted",
                                "project_id": project_a["id"]}).json()
    assert len(only_a) == 1
    assert only_a[0]["project_id"] == project_a["id"]

    sorted_desc = client.get("/api/timesheets", headers=hr_manager_auth, params={
        "employee_id": emp["employee_id"], "status": "Submitted", "sort_by": "project", "sort_dir": "desc",
    }).json()
    assert [r["project_names"] for r in sorted_desc] == sorted(
        [r["project_names"] for r in sorted_desc], reverse=True
    )
