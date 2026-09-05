"""Integration tests for routers/attendance.py: shifts, shift assignments,
attendance settings, self-service clock-in/out (including geofencing), HR
review (absence sweep + resolve), and device (API-key) webhook
integrations. Existing coverage before this file only had one sweep test.

A handful of clock-in tests (Present vs Late) depend on where "now" falls
relative to a shift deadline computed from datetime.utcnow() at test-setup
time. Offsets are kept to +/-10 minutes so this is robust except within a
narrow (~20 minute) window either side of UTC midnight, where the shift's
computed start_time can wrap to the next calendar day and throw off the
deadline math against the actual work_date. Same class of accepted,
documented time-window flakiness as test_rls_enforcement.py's known-flaky
test elsewhere in this suite — not worth mocking the clock for.
"""
import os
from datetime import datetime, timedelta

import pytest


def _unique_name(prefix="ZZ Attendance Test"):
    return f"{prefix} {os.urandom(4).hex()}"


def _hhmm(offset_minutes):
    return (datetime.utcnow() + timedelta(minutes=offset_minutes)).strftime("%H:%M")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_test_shift(client, hr_manager_auth):
    """Factory: creates a disposable 09:00-17:00 shift, deletes (soft) on teardown."""
    created_ids = []

    def _make(**overrides):
        payload = {"name": _unique_name("ZZ Shift"), "start_time": "09:00", "end_time": "17:00", "grace_period_minutes": 15}
        payload.update(overrides)
        res = client.post("/api/attendance/shifts", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create shift: {res.text}"
        shift = res.json()
        created_ids.append(shift["id"])
        return shift

    yield _make

    for sid in created_ids:
        client.delete(f"/api/attendance/shifts/{sid}", headers=hr_manager_auth)


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

def test_create_shift(client, hr_manager_auth, make_test_shift):
    shift = make_test_shift(name="ZZ Day Shift", start_time="09:00", end_time="17:00", grace_period_minutes=15)
    assert shift["name"] == "ZZ Day Shift"
    assert shift["start_time"] == "09:00"
    assert shift["end_time"] == "17:00"
    assert shift["grace_period_minutes"] == 15
    assert shift["crosses_midnight"] is False
    assert shift["is_active"] is True


def test_create_shift_crosses_midnight_when_end_before_start(client, hr_manager_auth, make_test_shift):
    shift = make_test_shift(name="ZZ Night Shift", start_time="22:00", end_time="06:00")
    assert shift["crosses_midnight"] is True


def test_list_shifts(client, hr_manager_auth, make_test_shift):
    shift = make_test_shift()
    res = client.get("/api/attendance/shifts", headers=hr_manager_auth)
    assert res.status_code == 200
    ids = [s["id"] for s in res.json()]
    assert shift["id"] in ids


def test_update_shift(client, hr_manager_auth, make_test_shift):
    shift = make_test_shift()
    res = client.put(f"/api/attendance/shifts/{shift['id']}", headers=hr_manager_auth, json={
        "name": "ZZ Renamed Shift", "grace_period_minutes": 30,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "ZZ Renamed Shift"
    assert body["grace_period_minutes"] == 30
    assert body["start_time"] == shift["start_time"]  # unchanged fields preserved


def test_update_shift_404_unknown(client, hr_manager_auth):
    res = client.put("/api/attendance/shifts/999999999", headers=hr_manager_auth, json={"name": "X"})
    assert res.status_code == 404


def test_delete_shift_soft_deletes(client, hr_manager_auth):
    res = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Shift"), "start_time": "09:00", "end_time": "17:00",
    })
    shift = res.json()
    del_res = client.delete(f"/api/attendance/shifts/{shift['id']}", headers=hr_manager_auth)
    assert del_res.status_code == 204

    listed = client.get("/api/attendance/shifts", headers=hr_manager_auth).json()
    match = next((s for s in listed if s["id"] == shift["id"]), None)
    assert match is not None
    assert match["is_active"] is False


def test_shift_endpoints_require_hr_role(client, employee_with_login, make_test_shift):
    shift = make_test_shift()
    _, headers = employee_with_login(full_name="ZZ Attendance Non-HR")
    assert client.get("/api/attendance/shifts", headers=headers).status_code == 403
    assert client.post("/api/attendance/shifts", headers=headers, json={
        "name": "X", "start_time": "09:00", "end_time": "17:00",
    }).status_code == 403
    assert client.put(f"/api/attendance/shifts/{shift['id']}", headers=headers, json={"name": "X"}).status_code == 403
    assert client.delete(f"/api/attendance/shifts/{shift['id']}", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# Shift assignments
# ---------------------------------------------------------------------------

def test_create_shift_assignment(client, hr_manager_auth, make_test_employee, make_test_shift):
    emp = make_test_employee()
    shift = make_test_shift()
    res = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": shift["id"], "effective_from": "2027-01-01",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["employee_id"] == emp["employee_id"]
    assert body["shift_id"] == shift["id"]
    assert body["shift_name"] == shift["name"]
    assert body["is_active"] is True


def test_create_shift_assignment_closes_prior_open_ended_assignment(client, hr_manager_auth, make_test_employee, make_test_shift):
    emp = make_test_employee()
    shift_a = make_test_shift()
    shift_b = make_test_shift()

    first = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": shift_a["id"], "effective_from": "2027-01-01",
    }).json()
    assert first["effective_to"] is None

    client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": shift_b["id"], "effective_from": "2027-06-01",
    })

    listed = client.get(f"/api/attendance/shift-assignments?employee_id={emp['employee_id']}", headers=hr_manager_auth).json()
    prior = next(a for a in listed if a["id"] == first["id"])
    assert prior["effective_to"] == "2027-05-31"  # day before the new assignment starts


def test_create_shift_assignment_404_unknown_employee(client, hr_manager_auth, make_test_shift):
    shift = make_test_shift()
    res = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": "NONEXISTENT", "shift_id": shift["id"], "effective_from": "2027-01-01",
    })
    assert res.status_code == 404


def test_create_shift_assignment_404_unknown_shift(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": 999999999, "effective_from": "2027-01-01",
    })
    assert res.status_code == 404


def test_list_shift_assignments_filtered_by_employee(client, hr_manager_auth, make_test_employee, make_test_shift):
    emp1 = make_test_employee()
    emp2 = make_test_employee()
    shift = make_test_shift()
    client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp1["employee_id"], "shift_id": shift["id"], "effective_from": "2027-01-01",
    })
    client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp2["employee_id"], "shift_id": shift["id"], "effective_from": "2027-01-01",
    })
    res = client.get(f"/api/attendance/shift-assignments?employee_id={emp1['employee_id']}", headers=hr_manager_auth)
    ids = [a["employee_id"] for a in res.json()]
    assert ids == [emp1["employee_id"]]


def test_delete_shift_assignment(client, hr_manager_auth, make_test_employee, make_test_shift):
    emp = make_test_employee()
    shift = make_test_shift()
    created = client.post("/api/attendance/shift-assignments", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "shift_id": shift["id"], "effective_from": "2027-01-01",
    }).json()
    res = client.delete(f"/api/attendance/shift-assignments/{created['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get(f"/api/attendance/shift-assignments?employee_id={emp['employee_id']}", headers=hr_manager_auth).json()
    assert created["id"] not in [a["id"] for a in listed]


# ---------------------------------------------------------------------------
# Attendance settings
# ---------------------------------------------------------------------------

def test_create_setting_requires_department_or_employee(client, hr_manager_auth):
    res = client.post("/api/attendance/settings", headers=hr_manager_auth, json={"required": True})
    assert res.status_code == 400


def test_create_setting_employee_scoped(client, hr_manager_auth, make_test_employee, make_test_shift):
    emp = make_test_employee()
    shift = make_test_shift()
    res = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["employee_id"] == emp["employee_id"]
    assert body["required"] is True
    assert body["default_shift_name"] == shift["name"]


def test_create_setting_department_scoped(client, hr_manager_auth):
    dept = _unique_name("ZZ Dept")
    res = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "department": dept, "required": True,
    })
    assert res.status_code == 201, res.text
    assert res.json()["department"] == dept


def test_create_setting_404_unknown_employee(client, hr_manager_auth):
    res = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": "NONEXISTENT", "required": True,
    })
    assert res.status_code == 404


def test_create_setting_404_unknown_shift(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": 999999999,
    })
    assert res.status_code == 404


def test_list_settings(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    created = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True,
    }).json()
    listed = client.get("/api/attendance/settings", headers=hr_manager_auth).json()
    assert created["id"] in [s["id"] for s in listed]


def test_update_setting(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    created = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True,
    }).json()
    res = client.put(f"/api/attendance/settings/{created['id']}", headers=hr_manager_auth, json={"required": False})
    assert res.status_code == 200
    assert res.json()["required"] is False


def test_update_setting_404_unknown(client, hr_manager_auth):
    res = client.put("/api/attendance/settings/999999999", headers=hr_manager_auth, json={"required": False})
    assert res.status_code == 404


def test_delete_setting_soft_deletes(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    created = client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True,
    }).json()
    res = client.delete(f"/api/attendance/settings/{created['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/attendance/settings", headers=hr_manager_auth).json()
    assert created["id"] not in [s["id"] for s in listed]  # list only returns is_active=1


def test_settings_endpoints_require_hr_role(client, employee_with_login, make_test_employee):
    emp = make_test_employee()
    _, headers = employee_with_login(full_name="ZZ Attendance Settings Non-HR")
    assert client.get("/api/attendance/settings", headers=headers).status_code == 403
    assert client.post("/api/attendance/settings", headers=headers, json={
        "employee_id": emp["employee_id"], "required": True,
    }).status_code == 403


# ---------------------------------------------------------------------------
# Clock in / out (self-service)
# ---------------------------------------------------------------------------

def test_clock_in_present_when_before_deadline(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ Clock Present")
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True,
        "default_shift_id": client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
            "name": _unique_name("ZZ Present Shift"), "start_time": _hhmm(10), "end_time": _hhmm(600), "grace_period_minutes": 0,
        }).json()["id"],
    })
    res = client.post("/api/attendance/clock-in", headers=headers, json={})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Present"
    assert body["clock_in_at"] is not None
    assert body["employee_id"] == emp["employee_id"]


def test_clock_in_late_when_after_deadline(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ Clock Late")
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True,
        "default_shift_id": client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
            "name": _unique_name("ZZ Late Shift"), "start_time": _hhmm(-10), "end_time": _hhmm(600), "grace_period_minutes": 0,
        }).json()["id"],
    })
    res = client.post("/api/attendance/clock-in", headers=headers, json={})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Late"
    assert body["suggested_action"] == "Half-Day Leave"


def test_clock_in_twice_same_day_rejected(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Clock Twice")
    first = client.post("/api/attendance/clock-in", headers=headers, json={})
    assert first.status_code == 201
    second = client.post("/api/attendance/clock-in", headers=headers, json={})
    assert second.status_code == 400
    assert "already clocked in" in second.text.lower()


def test_clock_in_without_linked_employee_record_400(client, hr_manager_auth):
    # hr_manager_auth's user has no employee_id linked.
    res = client.post("/api/attendance/clock-in", headers=hr_manager_auth, json={})
    assert res.status_code == 400


def test_clock_out_requires_open_clock_in(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Clock Out No Open")
    res = client.post("/api/attendance/clock-out", headers=headers, json={})
    assert res.status_code == 400
    assert "no open clock-in" in res.text.lower()


def test_clock_out_computes_worked_minutes(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Clock Out Worked")
    client.post("/api/attendance/clock-in", headers=headers, json={})
    res = client.post("/api/attendance/clock-out", headers=headers, json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["clock_out_at"] is not None
    assert body["worked_minutes"] is not None
    assert body["worked_minutes"] >= 0


def test_clock_in_geofencing_inside_radius(client, hr_manager_auth, employee_with_login, make_test_location):
    emp, headers = employee_with_login(full_name="ZZ Geofence Inside")
    loc = make_test_location(latitude=3.1390, longitude=101.6869, radius_meters=100)
    assign = client.post(f"/api/employees/{emp['employee_id']}/locations", headers=hr_manager_auth, json={
        "location_id": loc["id"], "assignment_type": "primary", "start_date": "2026-08-01",
    })
    assert assign.status_code == 201, assign.text

    res = client.post("/api/attendance/clock-in", headers=headers, json={"lat": 3.1390, "lng": 101.6869})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["outside_geofence"] is False
    assert body["clock_in_distance_meters"] is not None
    assert body["clock_in_distance_meters"] < 100


def test_clock_in_geofencing_outside_radius(client, hr_manager_auth, employee_with_login, make_test_location):
    emp, headers = employee_with_login(full_name="ZZ Geofence Outside")
    loc = make_test_location(latitude=3.1390, longitude=101.6869, radius_meters=100)
    assign = client.post(f"/api/employees/{emp['employee_id']}/locations", headers=hr_manager_auth, json={
        "location_id": loc["id"], "assignment_type": "primary", "start_date": "2026-08-01",
    })
    assert assign.status_code == 201, assign.text

    res = client.post("/api/attendance/clock-in", headers=headers, json={"lat": 3.1500, "lng": 101.7000})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["outside_geofence"] is True
    assert body["clock_in_distance_meters"] > 100


def test_my_attendance_lists_own_records(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ My Attendance")
    client.post("/api/attendance/clock-in", headers=headers, json={})
    res = client.get("/api/attendance/mine", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) >= 1


def test_my_attendance_empty_for_no_linked_employee(client, hr_manager_auth):
    res = client.get("/api/attendance/mine", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# HR review (absence sweep + resolve)
# ---------------------------------------------------------------------------

def test_review_sweep_creates_absent_record_for_required_employee(client, hr_manager_auth, make_test_employee):
    """Original coverage this file started with — kept as-is. See
    routers/attendance.py's _sweep_absences docstring: run lazily on every
    /api/attendance/review load, batched instead of per-employee queries."""
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


def test_review_sweep_result_includes_employee_name(client, hr_manager_auth, make_test_employee):
    shift = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Shift"), "start_time": "09:00", "end_time": "17:00", "grace_period_minutes": 0,
    }).json()
    emp = make_test_employee(full_name="ZZ Sweep Name Employee")
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    res = client.get("/api/attendance/review", headers=hr_manager_auth)
    mine = [r for r in res.json() if r["employee_id"] == emp["employee_id"]]
    assert mine
    assert mine[0]["employee_name"] == "ZZ Sweep Name Employee"


def test_review_queue_requires_hr_role(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Review Non-HR")
    res = client.get("/api/attendance/review", headers=headers)
    assert res.status_code == 403


def _make_late_record(client, hr_manager_auth, employee_with_login):
    """Clocks an employee in late (guaranteed via a deadline already in the
    past) and returns (emp, attendance_record)."""
    emp, headers = employee_with_login(full_name=_unique_name("ZZ Resolve Employee"))
    shift = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Resolve Shift"), "start_time": _hhmm(-10), "end_time": _hhmm(600), "grace_period_minutes": 0,
    }).json()
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    rec = client.post("/api/attendance/clock-in", headers=headers, json={}).json()
    assert rec["status"] == "Late"
    return emp, rec


def test_resolve_excuse(client, hr_manager_auth, employee_with_login):
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={
        "action": "Excuse", "notes": "ZZ traffic jam",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Excused"
    assert body["review_notes"] == "ZZ traffic jam"
    assert body["reviewed_at"] is not None


def test_resolve_confirm_absent(client, hr_manager_auth, employee_with_login):
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={
        "action": "ConfirmAbsent",
    })
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Confirmed Absent"


def test_resolve_reclassify_as_leave_consumes_balance(client, hr_manager_auth, employee_with_login, make_test_leave_type):
    emp, headers = employee_with_login(full_name=_unique_name("ZZ Reclassify Employee"))
    shift = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Reclassify Shift"), "start_time": _hhmm(-10), "end_time": _hhmm(600), "grace_period_minutes": 0,
    }).json()
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    rec = client.post("/api/attendance/clock-in", headers=headers, json={}).json()
    assert rec["status"] == "Late"

    lt = make_test_leave_type(name=_unique_name("ZZ Reclassify Leave Type"), annual_entitlement=10.0)
    # role="employee" auto-creates a missing balance row on read — see
    # list_leave_balances in routers/leave.py.
    before = client.get("/api/leave/balances", headers=headers).json()
    before_bal = next(b for b in before if b["leave_type_id"] == lt["id"])
    assert before_bal["used_days"] == 0

    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={
        "action": "ReclassifyAsLeave", "leave_type_id": lt["id"], "half_day": True, "notes": "ZZ half day",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Reclassified as Leave"
    assert body["leave_application_id"] is not None

    after = client.get("/api/leave/balances", headers=headers).json()
    after_bal = next(b for b in after if b["leave_type_id"] == lt["id"])
    assert after_bal["used_days"] == 0.5


def test_resolve_reclassify_requires_leave_type_id(client, hr_manager_auth, employee_with_login):
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={
        "action": "ReclassifyAsLeave",
    })
    assert res.status_code == 400


def test_resolve_already_resolved_record_rejected(client, hr_manager_auth, employee_with_login):
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    first = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={"action": "Excuse"})
    assert first.status_code == 200
    second = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={"action": "ConfirmAbsent"})
    assert second.status_code == 400


def test_resolve_unknown_action_rejected_by_schema(client, hr_manager_auth, employee_with_login):
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={"action": "NotARealAction"})
    assert res.status_code == 422  # Literal[...] rejects it at the schema level


def test_resolve_404_unknown_record(client, hr_manager_auth):
    res = client.put("/api/attendance/records/999999999/resolve", headers=hr_manager_auth, json={"action": "Excuse"})
    assert res.status_code == 404


def test_resolve_requires_hr_role(client, hr_manager_auth, employee_with_login):
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    _, non_hr_headers = employee_with_login(full_name=_unique_name("ZZ Resolve Non-HR"))
    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=non_hr_headers, json={"action": "Excuse"})
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Review queue / resolve — manager access (subordinate-scoped, unlike HR's
# institution-wide view)
# ---------------------------------------------------------------------------

@pytest.fixture
def manager_with_login(client, hr_manager_auth, make_test_employee, test_institution):
    """A manager employee + linked login, no subordinate pre-attached
    (unlike test_approval_workflow.py's manager_with_report fixture) —
    each test here attaches its own subordinate(s) via
    employee_with_login(reports_to=...). Returns (manager_employee, headers)."""
    mgr_emp = make_test_employee(full_name=_unique_name("ZZ Review Manager"))
    username = f"zzattmgr_{mgr_emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Attendance Manager", "password": password,
        "role": "manager", "employee_id": mgr_emp["employee_id"],
    })
    assert res.status_code == 201, f"failed to create manager user: {res.text}"
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    yield mgr_emp, headers

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def _make_late_record_reporting_to(client, hr_manager_auth, employee_with_login, manager_employee_id):
    """Same as _make_late_record, but the employee's reports_to is set —
    for subordinate-scoping checks on the manager-accessible endpoints."""
    emp, headers = employee_with_login(full_name=_unique_name("ZZ Report Late"), reports_to=manager_employee_id)
    shift = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Report Shift"), "start_time": _hhmm(-10), "end_time": _hhmm(600), "grace_period_minutes": 0,
    }).json()
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    rec = client.post("/api/attendance/clock-in", headers=headers, json={}).json()
    assert rec["status"] == "Late"
    return emp, rec


def test_review_queue_allows_manager_for_own_subordinate(client, hr_manager_auth, employee_with_login, manager_with_login):
    mgr_emp, mgr_headers = manager_with_login
    report_emp, rec = _make_late_record_reporting_to(client, hr_manager_auth, employee_with_login, mgr_emp["employee_id"])
    res = client.get("/api/attendance/review", headers=mgr_headers)
    assert res.status_code == 200, res.text
    assert rec["id"] in [r["id"] for r in res.json()]


def test_review_queue_manager_excludes_non_subordinates(client, hr_manager_auth, employee_with_login, manager_with_login):
    """A late/absent record for an employee who does NOT report to this
    manager must not leak into their review queue — the whole point of
    scoping this endpoint by subordinates_in_clause rather than just
    institution_id once 'manager' was added to its allowed roles."""
    mgr_emp, mgr_headers = manager_with_login
    other_emp, other_rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    res = client.get("/api/attendance/review", headers=mgr_headers)
    assert res.status_code == 200
    assert other_rec["id"] not in [r["id"] for r in res.json()]


def test_resolve_allows_manager_for_own_subordinate(client, hr_manager_auth, employee_with_login, manager_with_login):
    mgr_emp, mgr_headers = manager_with_login
    report_emp, rec = _make_late_record_reporting_to(client, hr_manager_auth, employee_with_login, mgr_emp["employee_id"])
    res = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=mgr_headers, json={"action": "Excuse"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Excused"


def test_resolve_rejects_manager_for_non_subordinate(client, hr_manager_auth, employee_with_login, manager_with_login):
    mgr_emp, mgr_headers = manager_with_login
    other_emp, other_rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    res = client.put(f"/api/attendance/records/{other_rec['id']}/resolve", headers=mgr_headers, json={"action": "Excuse"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def test_create_device_returns_api_key_once(client, hr_manager_auth):
    res = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Device")})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["api_key"].startswith("adk_")
    assert body["key_prefix"] in body["api_key"]
    assert body["is_active"] is True


def test_create_device_with_location(client, hr_manager_auth, make_test_location):
    loc = make_test_location()
    res = client.post("/api/attendance/devices", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Device"), "location_id": loc["id"],
    })
    assert res.status_code == 201, res.text
    assert res.json()["location_name"] == loc["name"]


def test_create_device_404_unknown_location(client, hr_manager_auth):
    res = client.post("/api/attendance/devices", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ Device"), "location_id": 999999999,
    })
    assert res.status_code == 404


def test_list_devices_excludes_api_key(client, hr_manager_auth):
    created = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Device")}).json()
    listed = client.get("/api/attendance/devices", headers=hr_manager_auth).json()
    match = next(d for d in listed if d["id"] == created["id"])
    assert "api_key" not in match


def test_delete_device_soft_deletes(client, hr_manager_auth):
    created = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Device")}).json()
    res = client.delete(f"/api/attendance/devices/{created['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/attendance/devices", headers=hr_manager_auth).json()
    assert created["id"] not in [d["id"] for d in listed]


def test_device_endpoints_require_hr_role(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Device Non-HR")
    assert client.get("/api/attendance/devices", headers=headers).status_code == 403
    assert client.post("/api/attendance/devices", headers=headers, json={"name": "X"}).status_code == 403


def test_webhook_clock_in_with_valid_key(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    device = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Webhook Device")}).json()
    res = client.post("/api/attendance/webhook/clock-event", headers={"X-Device-Api-Key": device["api_key"]}, json={
        "employee_id": emp["employee_id"], "event_type": "in",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["clock_in_source"] == "device"
    assert body["clock_in_at"] is not None


def test_webhook_clock_out_with_valid_key(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    device = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Webhook Device")}).json()
    headers = {"X-Device-Api-Key": device["api_key"]}
    client.post("/api/attendance/webhook/clock-event", headers=headers, json={
        "employee_id": emp["employee_id"], "event_type": "in",
    })
    res = client.post("/api/attendance/webhook/clock-event", headers=headers, json={
        "employee_id": emp["employee_id"], "event_type": "out",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["clock_out_source"] == "device"
    assert body["worked_minutes"] is not None


def test_webhook_missing_header_rejected(client, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/attendance/webhook/clock-event", json={
        "employee_id": emp["employee_id"], "event_type": "in",
    })
    assert res.status_code == 401


def test_webhook_malformed_key_rejected(client, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/attendance/webhook/clock-event", headers={"X-Device-Api-Key": "not-a-real-key"}, json={
        "employee_id": emp["employee_id"], "event_type": "in",
    })
    assert res.status_code == 401


def test_webhook_invalid_key_rejected(client, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/attendance/webhook/clock-event", headers={"X-Device-Api-Key": f"adk_{'a' * 12}_{'b' * 43}"}, json={
        "employee_id": emp["employee_id"], "event_type": "in",
    })
    assert res.status_code == 401


def test_webhook_unknown_employee_404(client, hr_manager_auth):
    device = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Webhook Device")}).json()
    res = client.post("/api/attendance/webhook/clock-event", headers={"X-Device-Api-Key": device["api_key"]}, json={
        "employee_id": "NONEXISTENT", "event_type": "in",
    })
    assert res.status_code == 404


def test_webhook_event_time_must_be_valid_iso(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    device = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ Webhook Device")}).json()
    res = client.post("/api/attendance/webhook/clock-event", headers={"X-Device-Api-Key": device["api_key"]}, json={
        "employee_id": emp["employee_id"], "event_type": "in", "event_time": "not-a-timestamp",
    })
    assert res.status_code == 400
