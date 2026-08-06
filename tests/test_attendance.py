"""Integration test for routers/attendance.py's absence sweep
(_sweep_absences, run lazily on every /api/attendance/review load) — added
alongside the perf fix that batches its lookups instead of querying once
per employee per day in the sweep window. No delete endpoint exists for
attendance_records, so disposable rows accumulate in the shared test
institution, same pattern as timesheets/leave types elsewhere in this
suite.
"""
import os


def _unique_name(prefix="ZZ Attendance Test"):
    return f"{prefix} {os.urandom(4).hex()}"


def test_review_sweep_creates_absent_record_for_required_employee(client, hr_manager_auth, make_test_employee):
    shift = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Shift"), "start_time": "09:00", "end_time": "17:00", "grace_period_minutes": 0,
    }).json()
    emp = make_test_employee(full_name="ZZ Attendance Sweep Employee")
    setting = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    assert setting.status_code == 201, setting.text

    res = client.get("/api/attendance/review", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    records = res.json()
    mine = [r for r in records if r["employee_id"] == emp["employee_id"]]
    assert mine, "expected at least one swept Absent (Pending Review) record for a required employee with no clock-ins"
    assert all(r["status"] == "Absent (Pending Review)" for r in mine)

    # Re-running the sweep must not duplicate rows for days already materialized.
    res2 = client.get("/api/attendance/review", headers=hr_manager_auth)
    mine2 = [r for r in res2.json() if r["employee_id"] == emp["employee_id"]]
    assert len(mine2) == len(mine)
