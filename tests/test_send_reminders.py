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
        sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, dry_run=False)
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
        first_pass = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, dry_run=False)
        second_pass = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, dry_run=False)
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
        sent = send_reminders.sweep_overdue_checklists(reminder_conn, inst_id, today_str, dry_run=False)
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
