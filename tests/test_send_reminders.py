"""Integration tests for scripts/send_reminders.py — Phase 2 of the email
notification engine (overdue onboarding/offboarding checklist items and
pending-timesheet reminders). See core/email_engine.py and
migrations/versions/20260920_0001_email_log_dedupe_key.py for the
dedupe_key mechanism these rely on.

Unlike every other test file in this repo, this one calls the sweep
functions directly against a raw DB connection (via db.get_db(), same
as the real script) rather than exclusively through the HTTP client —
scripts/send_reminders.py is a standalone script with no HTTP endpoint
of its own, so there's nothing to hit via `client` for the sweep logic
itself. Test *data* setup and *verification* still go through the
normal HTTP API/fixtures wherever possible (make_test_employee, the
onboarding endpoints, GET /api/notifications/email-log) — only the
actual sweep call bypasses HTTP, matching how the real script runs.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import send_reminders  # noqa: E402

from db import get_db, set_rls_context  # noqa: E402

PAST_DUE_DATE = "2020-01-01 00:00:00"


@pytest.fixture
def restore_reminder_settings(client, hr_manager_auth):
    """test_institution is session-scoped, so a test that flips one of the
    reminder_<category>_enabled toggles off has to put it back — otherwise
    it leaks into whatever test runs next in the same session (same
    pattern as tests/test_notifications.py's restore_general_settings)."""
    original = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    yield
    client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=original)


@pytest.fixture
def reminder_conn():
    """A raw bypass-RLS connection, same as the real script's main()
    obtains — needed because the sweep functions take a `conn`, not an
    HTTP client."""
    set_rls_context(None, bypass_rls=True)
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture
def manager_with_report_and_emails_for_reminders(client, hr_manager_auth, make_test_employee):
    """Same shape as test_approval_workflow.py's manager_with_report_and_emails,
    duplicated locally rather than imported cross-file (matches this
    repo's convention of per-file local fixtures) — a manager and their
    direct report, each with a real (fake-domain) email."""
    mgr_email = f"zzremindmgr_{os.urandom(4).hex()}@zzpytest.example.com"
    report_email = f"zzremindrep_{os.urandom(4).hex()}@zzpytest.example.com"
    mgr_emp = make_test_employee(full_name="ZZ Reminder Manager", personal_email=mgr_email)
    report_emp = make_test_employee(full_name="ZZ Reminder Report", reports_to=mgr_emp["employee_id"],
                                    personal_email=report_email)
    return report_emp, mgr_emp, mgr_email, report_email


def test_overdue_checklist_item_notifies_direct_manager(
    client, hr_manager_auth, manager_with_report_and_emails_for_reminders,
    configured_email_settings, reminder_conn
):
    report_emp, mgr_emp, mgr_email, report_email = manager_with_report_and_emails_for_reminders
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report_emp["employee_id"], "type": "onboarding",
    }).json()
    item = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Overdue Manager Item", "assigned_role": "manager", "due_date": PAST_DUE_DATE,
    }).json()
    assert item["status"] == "Pending"

    inst_id = report_emp["institution_id"]
    today_str = datetime.now(timezone.utc).date().isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "onboarding", dry_run=False)
    assert sent >= 1

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == mgr_email and r["category"] == "checklist_overdue")
    assert row["status"] == "sent"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_overdue_checklist_item_not_re_reminded_within_cooldown(
    client, hr_manager_auth, manager_with_report_and_emails_for_reminders,
    configured_email_settings, reminder_conn
):
    report_emp, mgr_emp, mgr_email, report_email = manager_with_report_and_emails_for_reminders
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report_emp["employee_id"], "type": "onboarding",
    }).json()
    client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Cooldown Item", "assigned_role": "manager", "due_date": PAST_DUE_DATE,
    })

    inst_id = report_emp["institution_id"]
    today_str = datetime.now(timezone.utc).date().isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        first_pass = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "onboarding", dry_run=False)
        second_pass = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "onboarding", dry_run=False)
    assert first_pass >= 1
    assert second_pass == 0, "running the sweep again immediately must not re-send within the cooldown window"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_checklist_item_not_yet_due_is_not_reminded(
    client, hr_manager_auth, manager_with_report_and_emails_for_reminders,
    configured_email_settings, reminder_conn
):
    report_emp, mgr_emp, mgr_email, report_email = manager_with_report_and_emails_for_reminders
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report_emp["employee_id"], "type": "onboarding",
    }).json()
    future_due = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Not Due Yet Item", "assigned_role": "manager", "due_date": future_due,
    })

    inst_id = report_emp["institution_id"]
    today_str = datetime.now(timezone.utc).date().isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "onboarding", dry_run=False)
    assert sent == 0

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_pending_timesheet_reminder_sent_and_not_duplicated(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task,
    configured_email_settings, reminder_conn
):
    emp_email = f"zzremindts_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Reminder Timesheet Employee", personal_email=emp_email)
    project = make_test_project(name="ZZ Reminder Project", member_ids=[emp["employee_id"]])
    make_test_project_task(project["id"])

    inst_id = emp["institution_id"]
    last_monday = (datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).date().weekday() + 7)).isoformat()

    with patch("core.email_engine.smtplib.SMTP"):
        first_pass = send_reminders.sweep_pending_timesheets(reminder_conn, inst_id, last_monday, dry_run=False)
        second_pass = send_reminders.sweep_pending_timesheets(reminder_conn, inst_id, last_monday, dry_run=False)

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == emp_email and r["category"] == "timesheet_reminder")
    assert row["status"] == "sent"
    assert second_pass == 0, "the same missed period must never be re-reminded once already logged"


def test_employee_with_no_project_access_is_not_reminded(
    client, hr_manager_auth, make_test_employee, configured_email_settings, reminder_conn
):
    """An employee who isn't a specific member of any project has
    nothing to log — reminding them would be a false positive. An
    is_open_to_all project elsewhere in the institution must NOT grant
    them blanket eligibility (that's the whole point of the fix this
    test guards — see sweep_pending_timesheets' docstring)."""
    emp_email = f"zznoproj_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ No Project Employee", personal_email=emp_email)
    inst_id = emp["institution_id"]

    last_monday = (datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).date().weekday() + 7)).isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_pending_timesheets(reminder_conn, inst_id, last_monday, dry_run=False)

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    assert not any(r["recipient_email"] == emp_email for r in log)


def test_employee_member_of_open_to_all_project_only_is_not_reminded(
    client, hr_manager_auth, make_test_employee, make_test_project,
    configured_email_settings, reminder_conn
):
    """is_open_to_all no longer grants blanket eligibility to everyone in
    the institution — a specific project_members row is required, so an
    employee who is NOT a named member of the open-to-all project still
    isn't reminded even though they could technically log time there."""
    emp_email = f"zzopentoall_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Open To All Non-Member Employee", personal_email=emp_email)
    inst_id = emp["institution_id"]
    make_test_project(name="ZZ Open To All Reminder Test", is_open_to_all=True)

    last_monday = (datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).date().weekday() + 7)).isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_pending_timesheets(reminder_conn, inst_id, last_monday, dry_run=False)

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    assert not any(r["recipient_email"] == emp_email for r in log)


def test_employee_member_of_only_a_non_active_project_is_not_reminded(
    client, hr_manager_auth, make_test_employee, make_test_project,
    configured_email_settings, reminder_conn
):
    """Membership in a Completed or On Hold project doesn't count towards
    eligibility either — there's nothing currently open to log time
    against, so reminding them would be a false positive."""
    emp_email = f"zznonactive_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Non-Active Project Employee", personal_email=emp_email)
    inst_id = emp["institution_id"]

    make_test_project(name="ZZ Completed Project For Reminder Test", status="Completed", member_ids=[emp["employee_id"]])

    last_monday = (datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).date().weekday() + 7)).isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_pending_timesheets(reminder_conn, inst_id, last_monday, dry_run=False)

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    assert not any(r["recipient_email"] == emp_email for r in log)


# ---------------------------------------------------------------------------
# Per-category reminder toggles (institutions.reminder_<category>_enabled —
# see migrations/versions/20260922_0001_reminder_category_toggles.py). Each
# sweep function checks its own toggle (send_reminders._category_enabled),
# so these are testable directly without going through main()'s loop.
# ---------------------------------------------------------------------------
def test_onboarding_reminder_toggle_off_suppresses_sweep(
    client, hr_manager_auth, manager_with_report_and_emails_for_reminders,
    configured_email_settings, restore_reminder_settings, reminder_conn
):
    report_emp, mgr_emp, mgr_email, report_email = manager_with_report_and_emails_for_reminders
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report_emp["employee_id"], "type": "onboarding",
    }).json()
    client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Toggle Off Item", "assigned_role": "manager", "due_date": PAST_DUE_DATE,
    })

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    settings["reminder_onboarding_enabled"] = False
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    inst_id = report_emp["institution_id"]
    today_str = datetime.now(timezone.utc).date().isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "onboarding", dry_run=False)
    assert sent == 0, "reminder_onboarding_enabled=false must suppress the onboarding sweep entirely"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_offboarding_checklist_item_notified_independently_of_onboarding_type(
    client, hr_manager_auth, manager_with_report_and_emails_for_reminders,
    configured_email_settings, reminder_conn
):
    """The checklist sweep is split by ob_checklists.type — an offboarding
    item must not be picked up by an 'onboarding'-typed sweep call, and
    vice versa, since the two are independently toggleable."""
    report_emp, mgr_emp, mgr_email, report_email = manager_with_report_and_emails_for_reminders
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report_emp["employee_id"], "type": "offboarding",
    }).json()
    client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Offboarding Overdue Item", "assigned_role": "manager", "due_date": PAST_DUE_DATE,
    })

    inst_id = report_emp["institution_id"]
    today_str = datetime.now(timezone.utc).date().isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        onboarding_sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "onboarding", dry_run=False)
        offboarding_sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, "offboarding", dry_run=False)
    assert onboarding_sent == 0, "an offboarding item must not be swept by the onboarding-typed call"
    assert offboarding_sent >= 1

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == mgr_email and r["category"] == "checklist_overdue" and r["module"] == "offboarding")
    assert row["status"] == "sent"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_timesheet_reminder_toggle_off_suppresses_sweep(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task,
    configured_email_settings, restore_reminder_settings, reminder_conn
):
    emp_email = f"zztoggletimesheet_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Toggle Timesheet Employee", personal_email=emp_email)
    project = make_test_project(name="ZZ Toggle Timesheet Project", member_ids=[emp["employee_id"]])
    make_test_project_task(project["id"])

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    settings["reminder_timesheet_enabled"] = False
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    inst_id = emp["institution_id"]
    last_monday = (datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).date().weekday() + 7)).isoformat()
    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_pending_timesheets(reminder_conn, inst_id, last_monday, dry_run=False)
    assert sent == 0, "reminder_timesheet_enabled=false must suppress the timesheet sweep entirely"


# ---------------------------------------------------------------------------
# Holiday-eve email reminder (reminder_holidays_enabled) — independent of
# the pre-existing dashboard "announce on the eve" banner toggle.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_test_holiday_tomorrow(client, hr_manager_auth):
    """Creates a real holiday dated "tomorrow" in the institution's own
    (already-configured) timezone, deletes it on teardown."""
    from zoneinfo import ZoneInfo
    created_ids = []

    def _make():
        tz_name = client.get("/api/notifications/general-settings", headers=hr_manager_auth).json()["timezone"]
        try:
            tz = ZoneInfo(tz_name or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        tomorrow = (datetime.now(tz).date() + timedelta(days=1)).isoformat()
        year = int(tomorrow[:4])
        res = client.post(
            "/api/holidays", headers=hr_manager_auth,
            json={"name": "ZZ Reminder Eve Holiday", "date": tomorrow, "year": year},
        )
        assert res.status_code == 201, f"failed to create test holiday: {res.text}"
        holiday = res.json()
        created_ids.append(holiday["id"])
        return holiday

    yield _make

    for hid in created_ids:
        client.delete(f"/api/holidays/{hid}", headers=hr_manager_auth)


def test_holiday_reminder_sent_when_enabled_and_holiday_tomorrow(
    client, hr_manager_auth, make_test_employee, configured_email_settings,
    restore_reminder_settings, make_test_holiday_tomorrow, reminder_conn
):
    emp_email = f"zzholidayreminder_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Holiday Reminder Employee", personal_email=emp_email)
    inst_id = emp["institution_id"]
    make_test_holiday_tomorrow()

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    settings["reminder_holidays_enabled"] = True
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    with patch("core.email_engine.smtplib.SMTP"):
        first_pass = send_reminders.sweep_holiday_eve_emails(reminder_conn, inst_id, dry_run=False)
        send_reminders.sweep_holiday_eve_emails(reminder_conn, inst_id, dry_run=False)
    assert first_pass >= 1

    # The sweep is institution-wide by design (every active employee gets
    # reminded), so a second pass's aggregate return value isn't a safe
    # thing to assert on here — under a parallel test run, another test in
    # this same shared institution can create a brand-new employee between
    # the two passes, who would then legitimately be swept for the first
    # time on the "second" pass without that being a duplicate-send bug.
    # What must never happen is *our* employee getting a second 'sent' row
    # for this same holiday.
    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    matches = [r for r in log if r["recipient_email"] == emp_email and r["category"] == "holiday_reminder"]
    assert len(matches) == 1, "the same employee must never be re-reminded for the same holiday"
    assert matches[0]["status"] == "sent"


def test_holiday_reminder_not_sent_when_disabled(
    client, hr_manager_auth, make_test_employee, configured_email_settings,
    restore_reminder_settings, make_test_holiday_tomorrow, reminder_conn
):
    emp_email = f"zzholidaydisabled_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Holiday Disabled Employee", personal_email=emp_email)
    inst_id = emp["institution_id"]
    make_test_holiday_tomorrow()

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    settings["reminder_holidays_enabled"] = False
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_holiday_eve_emails(reminder_conn, inst_id, dry_run=False)
    assert sent == 0


def test_holiday_reminder_not_sent_when_no_holiday_tomorrow(
    client, hr_manager_auth, make_test_employee, configured_email_settings,
    restore_reminder_settings, reminder_conn
):
    emp_email = f"zznoholiday_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ No Holiday Employee", personal_email=emp_email)
    inst_id = emp["institution_id"]

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    settings["reminder_holidays_enabled"] = True
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    with patch("core.email_engine.smtplib.SMTP"):
        sent = send_reminders.sweep_holiday_eve_emails(reminder_conn, inst_id, dry_run=False)
    assert sent == 0
