"""Integration tests for core/overtime.py + routers/overtime.py: overtime
detection on timesheet submission, its own approval workflow (module=
'overtime' in core/approval_workflow.py), and the leave/pay conversion
outcomes. See README.md's "Approval workflow module" section for the
shared engine and test_approval_workflow.py for its general coverage —
this file only covers what's specific to Overtime.
"""
import os

import pytest

PERIOD_START = "2027-05-01"
PERIOD_END = "2027-05-31"
WORK_DATE = "2027-05-05"  # within the period


def _unique_name(prefix="ZZ Test"):
    return f"{prefix} {os.urandom(4).hex()}"


@pytest.fixture
def make_test_shift(client, hr_manager_auth):
    """Factory: creates an 09:00-17:00 (8h) shift, deletes it on teardown."""
    created_ids = []

    def _make(**overrides):
        payload = {"name": _unique_name("ZZ Shift"), "start_time": "09:00", "end_time": "17:00", "grace_period_minutes": 0}
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
    """An employee+login with an 8h shift assigned effective from well
    before WORK_DATE — the minimal fixture needed for overtime detection
    to have a threshold to compare against."""
    emp, headers = employee_with_login(full_name="ZZ Overtime Test Employee")
    shift = make_test_shift()
    res = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": shift["id"], "effective_from": "2027-01-01",
    })
    assert res.status_code == 201, f"failed to assign shift: {res.text}"
    return emp, headers, shift


@pytest.fixture
def open_task(hr_manager_auth, client, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.patch(
        f"/api/projects/{project['id']}/tasks/{task['id']}/open-to-all",
        headers=hr_manager_auth, json={"open_to_all": True},
    )
    assert res.status_code == 200
    return project, task


def _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, hours, work_date=WORK_DATE):
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": PERIOD_START, "period_end": PERIOD_END,
    }).json()
    client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": work_date, "hours": hours,
    })
    submit = client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"})
    assert submit.status_code == 200, submit.text
    return ts


def test_overtime_created_when_hours_exceed_shift(client, hr_manager_auth, emp_with_shift, open_task):
    emp, headers, shift = emp_with_shift
    project, task = open_task
    ts = _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, 10)

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    assert len(records) == 1
    assert records[0]["work_date"] == WORK_DATE
    assert records[0]["threshold_hours"] == 8
    assert records[0]["logged_hours"] == 10
    assert records[0]["overtime_hours"] == 2
    assert records[0]["status"] == "Pending"


def test_no_overtime_when_hours_within_shift(client, hr_manager_auth, emp_with_shift, open_task):
    emp, headers, shift = emp_with_shift
    project, task = open_task
    ts = _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, 8)

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    assert records == []


def test_no_overtime_detection_without_a_shift(client, hr_manager_auth, employee_with_login, open_task):
    """No shift on file at all -> nothing to compare against -> no overtime
    record, even though 10 hours would exceed most shifts' 8h."""
    emp, headers = employee_with_login(full_name="ZZ No Shift Employee")
    project, task = open_task
    ts = _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, 10)

    records = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()
    assert records == []


def test_overtime_approve_requires_manage_role_then_credits_leave(client, hr_manager_auth, emp_with_shift, open_task,
                                                                    make_test_leave_type):
    emp, headers, shift = emp_with_shift
    project, task = open_task
    lt = make_test_leave_type(name=_unique_name("ZZ OT Leave"))

    settings_res = client.put("/api/overtime/settings", headers=hr_manager_auth, json={
        "overtime_conversion_mode": "leave", "overtime_leave_type_id": lt["id"],
    })
    assert settings_res.status_code == 200, settings_res.text

    ts = _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, 12)
    record = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()[0]
    assert record["overtime_hours"] == 4

    denied = client.patch(f"/api/overtime/{record['id']}/status", headers=headers, json={"status": "Approved"})
    assert denied.status_code == 403, denied.text

    approved = client.patch(f"/api/overtime/{record['id']}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "Approved"
    assert approved.json()["leave_days_credited"] == 0.5  # 4h overtime / 8h shift

    balances = client.get(f"/api/leave/balances?employee_id={emp['employee_id']}&year=2027", headers=hr_manager_auth).json()
    bal = next(b for b in balances if b["leave_type_id"] == lt["id"])
    assert bal["entitled_days"] == lt["annual_entitlement"] + 0.5

    # Restore settings so other tests in this shared institution default to pay.
    client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "pay"})


def test_overtime_approve_pay_mode_tracks_amount(client, hr_manager_auth, emp_with_shift, open_task):
    emp, headers, shift = emp_with_shift
    project, task = open_task

    client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "pay", "overtime_pay_multiplier": 2.0})

    ts = _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, 9)
    record = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()[0]
    assert record["overtime_hours"] == 1

    approved = client.patch(f"/api/overtime/{record['id']}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["pay_amount"] is not None
    assert approved.json()["leave_days_credited"] is None


def test_overtime_reject_leaves_no_credit(client, hr_manager_auth, emp_with_shift, open_task):
    emp, headers, shift = emp_with_shift
    project, task = open_task
    ts = _submit_timesheet_with_hours(client, hr_manager_auth, emp, headers, project, task, 10)
    record = client.get(f"/api/timesheets/{ts['id']}/overtime", headers=headers).json()[0]

    res = client.patch(f"/api/overtime/{record['id']}/status", headers=hr_manager_auth, json={"status": "Rejected"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Rejected"
    assert res.json()["pay_amount"] is None
    assert res.json()["leave_days_credited"] is None


def test_overtime_settings_leave_mode_requires_leave_type(client, hr_manager_auth):
    res = client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "leave"})
    assert res.status_code == 400
    client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "pay"})


def test_overtime_settings_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.put("/api/overtime/settings", headers=headers, json={"overtime_conversion_mode": "pay"})
    assert res.status_code == 403
