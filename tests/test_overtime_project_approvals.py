"""Integration tests for the per-project Overtime approval split
(overtime_project_approvals, added 2026-09-17 alongside Timesheet's own
split — see migrations/versions/20260917_0001_...) and its proration
rule: a day's overtime hours are split across the projects logged that
day, proportional to each project's share of the day's total hours (see
core/overtime.py's _create_overtime_project_approvals).
"""
import pytest

PERIOD_START = "2027-06-01"
PERIOD_END = "2027-06-30"
WORK_DATE = "2027-06-10"


@pytest.fixture
def make_test_shift(client, hr_manager_auth):
    created_ids = []

    def _make(**overrides):
        payload = {"name": "ZZ OT Split Shift", "start_time": "09:00", "end_time": "17:00", "grace_period_minutes": 0}
        payload.update(overrides)
        res = client.post("/api/attendance/shifts", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create shift: {res.text}"
        shift = res.json()
        created_ids.append(shift["id"])
        return shift

    yield _make

    for sid in created_ids:
        client.delete(f"/api/attendance/shifts/{sid}", headers=hr_manager_auth)


@pytest.fixture
def emp_with_shift(client, hr_manager_auth, employee_with_login, make_test_shift):
    emp, headers = employee_with_login(full_name="ZZ OT Split Employee")
    shift = make_test_shift()
    res = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": shift["id"], "effective_from": "2027-01-01",
    })
    assert res.status_code == 201, f"failed to assign shift: {res.text}"
    return emp, headers, shift


@pytest.fixture
def two_open_tasks(hr_manager_auth, make_test_project, make_test_project_task):
    project_a = make_test_project(name="ZZ OT Split Project A", is_open_to_all=True)
    task_a = make_test_project_task(project_a["id"])
    project_b = make_test_project(name="ZZ OT Split Project B", is_open_to_all=True)
    task_b = make_test_project_task(project_b["id"])
    return (project_a, task_a), (project_b, task_b)


def test_overtime_prorated_across_two_projects_by_hours_share(
    client, hr_manager_auth, emp_with_shift, two_open_tasks
):
    """6h on Project A + 4h on Project B against an 8h shift -> 2h
    overtime total, split 60/40 by each project's share of the day's 10
    logged hours -> 1.2h / 0.8h."""
    emp, headers, shift = emp_with_shift
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    }).json()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": WORK_DATE, "hours": 6,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": WORK_DATE, "hours": 4,
    })
    submit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert submit.status_code == 200, submit.text

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    by_project = {r["project_id"]: r for r in records}
    assert set(by_project) == {project_a["id"], project_b["id"]}
    assert by_project[project_a["id"]]["overtime_hours"] == pytest.approx(1.2)
    assert by_project[project_b["id"]]["overtime_hours"] == pytest.approx(0.8)
    assert by_project[project_a["id"]]["status"] == "Pending"
    assert by_project[project_b["id"]]["status"] == "Pending"


def test_approving_one_projects_overtime_share_does_not_affect_the_other(
    client, hr_manager_auth, emp_with_shift, two_open_tasks
):
    emp, headers, shift = emp_with_shift
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "pay"})
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    }).json()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": WORK_DATE, "hours": 6,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": WORK_DATE, "hours": 4,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    by_project = {r["project_id"]: r for r in records}

    approve_a = client.patch(f"/api/overtime/projects/{by_project[project_a['id']]['project_approval_id']}/status",
                             headers=hr_manager_auth, json={"status": "Approved"})
    assert approve_a.status_code == 200, approve_a.text
    assert approve_a.json()["pay_amount"] is not None

    after = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    after_by_project = {r["project_id"]: r for r in after}
    assert after_by_project[project_a["id"]]["status"] == "Approved"
    assert after_by_project[project_b["id"]]["status"] == "Pending"  # untouched
    assert after_by_project[project_b["id"]]["pay_amount"] is None


def test_legacy_whole_record_endpoint_blocked_once_split(
    client, hr_manager_auth, emp_with_shift, two_open_tasks
):
    """PATCH /api/overtime/{record_id}/status (the day-level, pre-split
    endpoint) refuses a record that's been split into project rows —
    mirrors the equivalent Timesheet-side guard."""
    emp, headers, shift = emp_with_shift
    (project_a, task_a), (project_b, task_b) = two_open_tasks
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    }).json()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": WORK_DATE, "hours": 6,
    })
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_b["id"], "task_id": task_b["id"], "date": WORK_DATE, "hours": 4,
    })
    client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    record_id = records[0]["id"]  # the shared day-level parent id
    res = client.patch(f"/api/overtime/{record_id}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 400
    assert "individually" in res.json()["detail"]


def test_single_project_day_gets_full_overtime_unprorated(
    client, hr_manager_auth, emp_with_shift, two_open_tasks
):
    """Sanity check against the pre-split behavior: a day logged against
    only one project isn't reduced by proration — its 100% share equals
    the day's full overtime."""
    emp, headers, shift = emp_with_shift
    (project_a, task_a), _ = two_open_tasks
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    }).json()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project_a["id"], "task_id": task_a["id"], "date": WORK_DATE, "hours": 10,
    })
    submit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert submit.status_code == 200, submit.text

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    assert len(records) == 1
    assert records[0]["overtime_hours"] == 2
    assert records[0]["project_id"] == project_a["id"]
