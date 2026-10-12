"""Integration tests for routers/fr_integration.py — the FR (facial-
recognition attendance kiosk) roster-pull and attendance-push endpoints.
See docs/FR_INTEGRATION.md for the contract these implement.

Reuses the existing attendance_devices API-key auth wholesale (an FR
kiosk is provisioned exactly like any other clock-in/out device), so the
auth-rejection checklist mirrors tests/test_attendance.py's own device/
webhook tests almost verbatim.
"""
import os
from datetime import datetime, timedelta

import pytest

from conftest import _valid_employee_payload


def _unique_name(prefix="ZZ FR Test"):
    return f"{prefix} {os.urandom(4).hex()}"


def _hhmm(offset_minutes):
    return (datetime.utcnow() + timedelta(minutes=offset_minutes)).strftime("%H:%M")


@pytest.fixture
def fr_device(client, hr_manager_auth):
    """A disposable attendance_devices row standing in for an FR kiosk —
    same provisioning path Settings > Attendance > Devices uses. Returns
    the raw api_key (X-Device-Api-Key header value)."""
    res = client.post("/api/attendance/devices", headers=hr_manager_auth, json={"name": _unique_name("ZZ FR Kiosk")})
    assert res.status_code == 201, res.text
    return res.json()["api_key"]


def _fresh_institution_employee(client, superadmin_headers):
    """An employee in a brand-new, throwaway institution — for the
    cross-tenant isolation check, so a device keyed to the shared
    test_institution genuinely cannot see this employee regardless of
    what else the full suite has left behind there."""
    code = f"ZZFRINT{os.urandom(4).hex()}".upper()
    username = f"zzfrint_admin_{os.urandom(4).hex()}"
    password = "ZzPytest@123"
    create = client.post("/api/institutions", headers=superadmin_headers, json={
        "name": "ZZ FR Integration Other Institution",
        "code": code,
        "contact_email": "zzfrint@example.com",
        "admin_username": username,
        "admin_full_name": "ZZ FR Integration Admin",
        "admin_password": password,
    })
    assert create.status_code == 201, create.text
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": code,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    emp = client.post("/api/employees", headers=headers,
                       json=_valid_employee_payload(full_name="ZZ Other Institution Employee"))
    assert emp.status_code == 201, emp.text
    return emp.json()


def _make_late_record(client, hr_manager_auth, employee_with_login):
    """Same helper as tests/test_attendance.py's own — clocks an employee
    in late (deadline already in the past) so it can be resolved by HR."""
    emp, headers = employee_with_login(full_name=_unique_name("ZZ FR Finalized Day Employee"))
    shift = client.post("/api/attendance/shifts", headers=hr_manager_auth, json={
        "name": _unique_name("ZZ FR Shift"), "start_time": _hhmm(-10), "end_time": _hhmm(600), "grace_period_minutes": 0,
    }).json()
    client.post("/api/attendance/settings", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "required": True, "default_shift_id": shift["id"],
    })
    rec = client.post("/api/attendance/clock-in", headers=headers, json={}).json()
    assert rec["status"] == "Late"
    return emp, rec


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_roster_missing_header_rejected(client):
    res = client.get("/api/integrations/fr/employees")
    assert res.status_code == 401


def test_roster_malformed_key_rejected(client):
    res = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": "not-a-real-key"})
    assert res.status_code == 401


def test_roster_invalid_key_rejected(client):
    res = client.get("/api/integrations/fr/employees",
                      headers={"X-Device-Api-Key": f"adk_{'a' * 12}_{'b' * 43}"})
    assert res.status_code == 401


def test_attendance_push_missing_header_rejected(client):
    res = client.post("/api/integrations/fr/attendance", json=[])
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Roster pull
# ---------------------------------------------------------------------------

def test_roster_includes_employee_with_default_consent_false(client, fr_device, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Roster Employee")
    rows = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device}).json()
    match = next(r for r in rows if r["ems_employee_id"] == emp["employee_id"])
    assert match["full_name"] == "ZZ FR Roster Employee"
    assert match["display_name"] == "ZZ FR Roster Employee"  # no preferred_name set -> falls back
    assert match["status"] == "active"
    assert match["consent_recognition"] is False
    assert match["consent_display_name"] is False
    assert match["consent_dob"] is False


def test_roster_display_name_prefers_preferred_name(client, fr_device, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Full Name", preferred_name="Zed")
    rows = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device}).json()
    match = next(r for r in rows if r["ems_employee_id"] == emp["employee_id"])
    assert match["display_name"] == "Zed"


def test_roster_reflects_consent_after_patch(client, fr_device, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Consent Employee")
    patch = client.patch(f"/api/employees/{emp['employee_id']}/consent", headers=hr_manager_auth, json={
        "consent_recognition": True, "consent_dob": True,
    })
    assert patch.status_code == 200, patch.text
    assert patch.json()["consent_recognition"] is True
    assert patch.json()["consent_display_name"] is False  # untouched field stays false
    assert patch.json()["consent_dob"] is True

    rows = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device}).json()
    match = next(r for r in rows if r["ems_employee_id"] == emp["employee_id"])
    assert match["consent_recognition"] is True
    assert match["consent_display_name"] is False
    assert match["consent_dob"] is True


def test_roster_inactive_status_lowercased(client, fr_device, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Inactive Employee")
    client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})
    rows = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device}).json()
    match = next(r for r in rows if r["ems_employee_id"] == emp["employee_id"])
    assert match["status"] == "inactive"


def test_roster_changed_since_excludes_untouched_employees(client, fr_device, make_test_employee):
    make_test_employee(full_name="ZZ FR Old Employee")
    future = (datetime.utcnow() + timedelta(days=1)).isoformat()
    rows = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device},
                       params={"changed_since": future}).json()
    assert rows == []


def test_roster_scoped_to_device_institution(client, fr_device, superadmin_headers):
    # Asserts on full_name, not employee_id: gen_employee_id() (routers/
    # employees.py) is a per-institution sequential counter ("EMP0001",
    # "EMP0002", ...), not globally unique, so a fresh institution's first
    # employee routinely collides on the id string with the shared
    # test_institution's own first employee — a real different person,
    # not a leak. full_name is the value this test actually controls.
    other_emp = _fresh_institution_employee(client, superadmin_headers)
    rows = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device}).json()
    assert other_emp["full_name"] not in [r["full_name"] for r in rows]


def test_roster_pagination_next_cursor_header(client, fr_device, make_test_employee):
    make_test_employee(full_name="ZZ FR Page Employee 1")
    make_test_employee(full_name="ZZ FR Page Employee 2")
    res = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device},
                      params={"page_size": 1})
    assert res.status_code == 200
    assert len(res.json()) == 1
    cursor = res.headers.get("X-Next-Cursor")
    assert cursor is not None

    res2 = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device},
                       params={"page_size": 1, "cursor": cursor})
    assert res2.status_code == 200
    assert len(res2.json()) == 1
    assert res2.json()[0]["ems_employee_id"] != res.json()[0]["ems_employee_id"]


def test_roster_bad_cursor_rejected(client, fr_device):
    res = client.get("/api/integrations/fr/employees", headers={"X-Device-Api-Key": fr_device},
                      params={"cursor": "not-an-id"})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Attendance push
# ---------------------------------------------------------------------------

def test_push_creates_new_attendance_record(client, fr_device, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Push Employee")
    res = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[
        {"ems_employee_id": emp["employee_id"], "work_date": "2026-08-29",
         "clock_in_ts": "2026-08-29T01:03:11Z", "clock_out_ts": "2026-08-29T10:30:44Z"},
    ])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body == {"ok": True, "accepted": 1, "rejected": [], "detail": None}

    rec = client.get("/api/attendance/review", headers=hr_manager_auth)  # sanity: doesn't error
    assert rec.status_code == 200


def test_push_is_idempotent_upsert(client, fr_device, make_test_employee):
    """Re-sending the same row (a retry, or a corrected clock-out) must
    upsert cleanly, not double-count or reject."""
    emp = make_test_employee(full_name="ZZ FR Idempotent Employee")
    row = {"ems_employee_id": emp["employee_id"], "work_date": "2026-08-30",
           "clock_in_ts": "2026-08-30T01:00:00Z", "clock_out_ts": None}
    first = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[row])
    assert first.json()["accepted"] == 1

    row["clock_out_ts"] = "2026-08-30T09:00:00Z"  # FR later reports the clock-out for the same day
    second = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[row])
    assert second.status_code == 201
    assert second.json() == {"ok": True, "accepted": 1, "rejected": [], "detail": None}

    third = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[row])
    assert third.json()["accepted"] == 1  # exact repeat — still a clean accept, no error


def test_push_unknown_employee_rejected(client, fr_device):
    res = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[
        {"ems_employee_id": "NONEXISTENT", "work_date": "2026-08-29", "clock_in_ts": "2026-08-29T01:00:00Z"},
    ])
    assert res.status_code == 201
    body = res.json()
    assert body["accepted"] == 0
    assert body["rejected"] == [{"ems_employee_id": "NONEXISTENT", "work_date": "2026-08-29", "reason": "unknown_employee"}]


def test_push_invalid_clock_in_ts_rejected(client, fr_device, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Bad Timestamp Employee")
    res = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[
        {"ems_employee_id": emp["employee_id"], "work_date": "2026-08-29", "clock_in_ts": "not-a-timestamp"},
    ])
    body = res.json()
    assert body["accepted"] == 0
    assert body["rejected"][0]["reason"] == "invalid_clock_in_ts"


def test_push_clock_out_before_clock_in_rejected(client, fr_device, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Backwards Employee")
    res = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[
        {"ems_employee_id": emp["employee_id"], "work_date": "2026-08-29",
         "clock_in_ts": "2026-08-29T10:00:00Z", "clock_out_ts": "2026-08-29T01:00:00Z"},
    ])
    assert res.json()["rejected"][0]["reason"] == "clock_out_before_clock_in"


def test_push_batch_too_large_rejected(client, fr_device, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Big Batch Employee")
    rows = [{"ems_employee_id": emp["employee_id"], "work_date": "2026-08-29", "clock_in_ts": "2026-08-29T01:00:00Z"}] * 501
    res = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=rows)
    assert res.status_code == 400


def test_push_does_not_clobber_hr_finalized_day(client, fr_device, hr_manager_auth, employee_with_login):
    """An HR-reviewed/reclassified day must not be silently overwritten by
    a later or re-synced kiosk batch for the same (employee, work_date)."""
    emp, rec = _make_late_record(client, hr_manager_auth, employee_with_login)
    resolve = client.put(f"/api/attendance/records/{rec['id']}/resolve", headers=hr_manager_auth, json={
        "action": "Excuse", "notes": "ZZ FR test — traffic jam",
    })
    assert resolve.status_code == 200, resolve.text
    assert resolve.json()["status"] == "Excused"

    work_date = rec["work_date"]
    res = client.post("/api/integrations/fr/attendance", headers={"X-Device-Api-Key": fr_device}, json=[
        {"ems_employee_id": emp["employee_id"], "work_date": work_date,
         "clock_in_ts": f"{work_date}T01:00:00Z", "clock_out_ts": f"{work_date}T09:00:00Z"},
    ])
    body = res.json()
    assert body["accepted"] == 0
    assert body["rejected"][0]["reason"] == "day_already_finalized_by_hr"

    still = client.get("/api/attendance/review", headers=hr_manager_auth)
    assert still.status_code == 200  # the resolved record wasn't touched (indirect sanity check)


# ---------------------------------------------------------------------------
# Consent endpoint (routers/employees.py) — role gating
# ---------------------------------------------------------------------------

def test_consent_defaults_false_for_new_employee(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Fresh Consent Employee")
    got = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth).json()
    assert got["consent_recognition"] is False
    assert got["consent_display_name"] is False
    assert got["consent_dob"] is False


def test_consent_update_requires_hr_manager_role(client, make_test_user, test_institution, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Consent Role Employee")
    token, _ = make_test_user(role="hr_admin")  # CAN_TOGGLE is superadmin/hr_manager only — hr_admin excluded
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.patch(f"/api/employees/{emp['employee_id']}/consent", headers=headers, json={"consent_recognition": True})
    assert res.status_code == 403


def test_consent_update_404_unknown_employee(client, hr_manager_auth):
    res = client.patch("/api/employees/NONEXISTENT/consent", headers=hr_manager_auth, json={"consent_recognition": True})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Single employee lookup, the `birthday` flag, and date-of-birth consent
# ---------------------------------------------------------------------------
from zoneinfo import ZoneInfo
from routers.fr_integration import is_birthday


def _today_in_company_tz(client, hr_manager_auth):
    tz = client.get("/api/notifications/general-settings", headers=hr_manager_auth).json()["timezone"] or "UTC"
    return datetime.now(ZoneInfo(tz)).date()


def _grant(client, hr_manager_auth, emp, **consents):
    res = client.patch(f"/api/employees/{emp['employee_id']}/consent", headers=hr_manager_auth, json=consents)
    assert res.status_code == 200, res.text


def test_is_birthday_matches_month_and_day_and_handles_29_february():
    assert is_birthday("1992-10-12", "2026-10-12") is True
    assert is_birthday("1992-10-12", "2026-10-13") is False
    assert is_birthday("1992-10-12", "2026-11-12") is False
    assert is_birthday("1992-02-29", "2027-02-28") is True      # not a leap year: celebrated on 28 Feb
    assert is_birthday("1992-02-29", "2027-03-01") is False
    assert is_birthday("1992-02-29", "2028-02-29") is True      # leap year: the real day
    assert is_birthday("1992-02-29", "2028-02-28") is False
    assert is_birthday("1992-02-29", "2100-02-28") is True      # 2100 is not a leap year
    assert is_birthday(None, "2026-10-12") is False
    assert is_birthday("not a date", "2026-10-12") is False


def test_single_employee_lookup_returns_only_display_name_and_birthday(client, fr_device, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR Single Employee", preferred_name="Zee")
    headers = {"X-Device-Api-Key": fr_device}
    url = f"/api/integrations/fr/employees/{emp['employee_id']}"

    # no consent yet: no name, no birthday
    res = client.get(url, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"display_name": None, "birthday": False}

    _grant(client, hr_manager_auth, emp, consent_display_name=True)
    assert client.get(url, headers=headers).json() == {"display_name": "Zee", "birthday": False}
    # nothing else is ever released — no full name, date of birth, email, status or consent flags
    assert set(client.get(url, headers=headers).json()) == {"display_name", "birthday"}


def test_single_employee_lookup_falls_back_to_the_full_name_when_no_preferred_name(client, fr_device, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR No Preferred")
    _grant(client, hr_manager_auth, emp, consent_display_name=True)
    res = client.get(f"/api/integrations/fr/employees/{emp['employee_id']}", headers={"X-Device-Api-Key": fr_device})
    assert res.json()["display_name"] == "ZZ FR No Preferred"


def test_single_employee_lookup_needs_a_key_and_hides_unknown_inactive_and_other_companies(
    client, fr_device, hr_manager_auth, superadmin_headers, make_test_employee
):
    assert client.get("/api/integrations/fr/employees/EMP-1").status_code == 401
    headers = {"X-Device-Api-Key": fr_device}
    assert client.get("/api/integrations/fr/employees/ZZ-NO-SUCH", headers=headers).status_code == 404

    gone = make_test_employee(full_name="ZZ FR Left The Company")
    _grant(client, hr_manager_auth, gone, consent_display_name=True)
    assert client.get(f"/api/integrations/fr/employees/{gone['employee_id']}", headers=headers).status_code == 200
    assert client.patch(f"/api/employees/{gone['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"}).status_code == 200
    assert client.get(f"/api/integrations/fr/employees/{gone['employee_id']}", headers=headers).status_code == 404

    other = _fresh_institution_employee(client, superadmin_headers)
    res = client.get(f"/api/integrations/fr/employees/{other['employee_id']}", headers=headers)
    # Employee IDs are numbered per company, so the same ID may exist in OUR company (a 200 for a different
    # person); what must never happen is returning the other company's person.
    assert res.status_code == 404 or res.json().get("display_name") != "ZZ Other Institution Employee"


def test_date_of_birth_is_withheld_from_the_roster_unless_the_employee_consented(client, fr_device, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ FR DOB Employee", date_of_birth="1990-03-04")
    headers = {"X-Device-Api-Key": fr_device}
    roster = lambda: next(r for r in client.get("/api/integrations/fr/employees", headers=headers).json()
                          if r["ems_employee_id"] == emp["employee_id"])
    assert roster()["date_of_birth"] is None
    _grant(client, hr_manager_auth, emp, consent_dob=True)
    assert roster()["date_of_birth"] == "1990-03-04"


def test_birthday_flag_needs_consent_and_todays_date_in_the_company_timezone(client, fr_device, hr_manager_auth, make_test_employee):
    today = _today_in_company_tz(client, hr_manager_auth)
    birthday = make_test_employee(full_name="ZZ FR Birthday Today", date_of_birth=today.replace(year=1990, day=today.day).isoformat()
                                  if not (today.month == 2 and today.day == 29) else "1992-02-29")
    other_day = make_test_employee(full_name="ZZ FR Not Today", date_of_birth="1990-01-01" if (today.month, today.day) != (1, 1) else "1990-01-02")
    headers = {"X-Device-Api-Key": fr_device}
    get = lambda e: client.get(f"/api/integrations/fr/employees/{e['employee_id']}", headers=headers).json()

    assert get(birthday)["birthday"] is False                    # it is their birthday, but no consent
    _grant(client, hr_manager_auth, birthday, consent_dob=True)
    _grant(client, hr_manager_auth, other_day, consent_dob=True)
    assert get(birthday)["birthday"] is True
    assert get(other_day)["birthday"] is False
    roster = {r["ems_employee_id"]: r for r in client.get("/api/integrations/fr/employees", headers=headers).json()}
    assert roster[birthday["employee_id"]]["birthday"] is True
    assert roster[other_day["employee_id"]]["birthday"] is False
    _grant(client, hr_manager_auth, birthday, consent_dob=False)
    assert get(birthday)["birthday"] is False
