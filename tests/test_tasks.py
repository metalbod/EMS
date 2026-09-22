"""Tests for the async task status endpoint's per-task ownership authorization,
plus the Celery beat reminder-sweep tasks/schedule (core/tasks.py).

Previously GET /api/tasks/{task_id} had no authorization at all — any
authenticated user of any role could look up any task ID.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from celery.schedules import crontab

from db import get_db
from core.tasks import app as celery_app, reminder_sweep_checklists, reminder_sweep_holidays, reminder_sweep_timesheets


def _insert_tracking_row(user_id, inst_id, task_id=None):
    task_id = task_id or str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO task_tracking (id, user_id, institution_id, task_type, status) VALUES (?, ?, ?, ?, ?)",
            (task_id, user_id, inst_id, "bulk_upload", "pending"),
        )
        conn.commit()
    finally:
        conn.close()
    return task_id


def _employee_headers(make_test_user, test_institution, role="employee"):
    token, user_id = make_test_user(role=role)
    return {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}, user_id


def test_owner_can_view_own_task(client, make_test_user, test_institution):
    headers, user_id = _employee_headers(make_test_user, test_institution)
    task_id = _insert_tracking_row(user_id, test_institution["id"])

    res = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == task_id


def test_non_owner_non_hr_cannot_view_others_task(client, make_test_user, test_institution):
    owner_headers, owner_id = _employee_headers(make_test_user, test_institution)
    task_id = _insert_tracking_row(owner_id, test_institution["id"])

    other_headers, _ = _employee_headers(make_test_user, test_institution)
    res = client.get(f"/api/tasks/{task_id}", headers=other_headers)
    assert res.status_code == 403


def test_hr_tier_can_view_any_tracked_task(client, make_test_user, hr_manager_auth, test_institution):
    owner_headers, owner_id = _employee_headers(make_test_user, test_institution)
    task_id = _insert_tracking_row(owner_id, test_institution["id"])

    res = client.get(f"/api/tasks/{task_id}", headers=hr_manager_auth)
    assert res.status_code == 200


def test_untracked_task_id_is_hr_tier_only(client, make_test_user, hr_manager_auth, test_institution):
    untracked_task_id = str(uuid.uuid4())

    employee_headers, _ = _employee_headers(make_test_user, test_institution)
    res = client.get(f"/api/tasks/{untracked_task_id}", headers=employee_headers)
    assert res.status_code == 403

    res = client.get(f"/api/tasks/{untracked_task_id}", headers=hr_manager_auth)
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Celery beat schedule — reminder sweeps (core/tasks.py's beat_schedule,
# fired by the "reminders" Fly process group: `celery -A core.tasks beat`).
# The sweep logic itself (who gets emailed, dedupe, per-category toggles) is
# exhaustively covered by tests/test_send_reminders.py against the same
# underlying scripts/send_reminders.py functions these tasks call — these
# tests only cover the wrapper: each task loops enabled institutions, checks
# each institution's own reminder_<category>_hour (Settings -> Notifications
# -> Reminders tab) against the current local time there, and calls through
# when due. Real wall-clock time is never relied on for "is it due" — every
# test below pins core.tasks._reminder_local_now to a fixed Monday morning
# instead, so these pass regardless of what day/hour they actually run.
# ---------------------------------------------------------------------------
_FIXED_MONDAY = datetime(2026, 9, 21, tzinfo=timezone.utc)  # a real Monday
_DEFAULT_HOUR = 8  # institutions.reminder_<category>_hour's migration default


def test_beat_schedule_has_expected_reminder_entries():
    schedule = celery_app.conf.beat_schedule
    every_30_min = crontab(minute="*/30")

    for name, task_name in (
        ("reminder-sweep-checklists", "core.tasks.reminder_sweep_checklists"),
        ("reminder-sweep-holidays", "core.tasks.reminder_sweep_holidays"),
        ("reminder-sweep-timesheets", "core.tasks.reminder_sweep_timesheets"),
    ):
        assert schedule[name]["task"] == task_name
        assert schedule[name]["schedule"] == every_30_min


def test_reminder_sweep_checklists_task_emails_overdue_item_when_hour_matches(
    client, hr_manager_auth, make_test_employee, configured_email_settings
):
    mgr_email = f"zztaskckmgr_{os.urandom(4).hex()}@zzpytest.example.com"
    mgr = make_test_employee(full_name="ZZ Task Checklist Manager", personal_email=mgr_email)
    report = make_test_employee(full_name="ZZ Task Checklist Report", reports_to=mgr["employee_id"])
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report["employee_id"], "type": "onboarding",
    }).json()
    client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Task Overdue Item", "assigned_role": "manager", "due_date": "2020-01-01 00:00:00",
    })

    due_now = _FIXED_MONDAY.replace(hour=_DEFAULT_HOUR)
    with patch("core.email_engine.smtplib.SMTP"), patch("core.tasks._reminder_local_now", return_value=due_now):
        result = reminder_sweep_checklists()
    assert result["sent"] >= 1

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == mgr_email and r["category"] == "checklist_overdue")
    assert row["status"] == "sent"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_reminder_sweep_checklists_task_skips_institution_when_hour_does_not_match(
    client, hr_manager_auth, make_test_employee, configured_email_settings
):
    mgr_email = f"zztaskckmgroff_{os.urandom(4).hex()}@zzpytest.example.com"
    mgr = make_test_employee(full_name="ZZ Task Checklist Off-Hour Manager", personal_email=mgr_email)
    report = make_test_employee(full_name="ZZ Task Checklist Off-Hour Report", reports_to=mgr["employee_id"])
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": report["employee_id"], "type": "onboarding",
    }).json()
    client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth, json={
        "title": "ZZ Off-Hour Overdue Item", "assigned_role": "manager", "due_date": "2020-01-01 00:00:00",
    })

    not_due = _FIXED_MONDAY.replace(hour=(_DEFAULT_HOUR + 12) % 24)  # 12h away from the configured hour
    with patch("core.email_engine.smtplib.SMTP"), patch("core.tasks._reminder_local_now", return_value=not_due):
        reminder_sweep_checklists()

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    assert not any(r["recipient_email"] == mgr_email for r in log), \
        "an institution whose configured hour doesn't match the current one must not be swept"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_reminder_sweep_timesheets_task_emails_pending_member_on_monday(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task, configured_email_settings
):
    emp_email = f"zztaskts_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Task Timesheet Employee", personal_email=emp_email)
    project = make_test_project(name="ZZ Task Reminder Project", member_ids=[emp["employee_id"]])
    make_test_project_task(project["id"])

    due_now = _FIXED_MONDAY.replace(hour=_DEFAULT_HOUR)
    assert due_now.weekday() == 0
    with patch("core.email_engine.smtplib.SMTP"), patch("core.tasks._reminder_local_now", return_value=due_now):
        result = reminder_sweep_timesheets()
    assert result["sent"] >= 1

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == emp_email and r["category"] == "timesheet_reminder")
    assert row["status"] == "sent"


def test_reminder_sweep_timesheets_task_skips_when_hour_matches_but_not_monday(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task, configured_email_settings
):
    emp_email = f"zztasktstue_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Task Timesheet Tuesday Employee", personal_email=emp_email)
    project = make_test_project(name="ZZ Task Reminder Tuesday Project", member_ids=[emp["employee_id"]])
    make_test_project_task(project["id"])

    a_tuesday = (_FIXED_MONDAY + timedelta(days=1)).replace(hour=_DEFAULT_HOUR)
    assert a_tuesday.weekday() == 1
    with patch("core.email_engine.smtplib.SMTP"), patch("core.tasks._reminder_local_now", return_value=a_tuesday):
        reminder_sweep_timesheets()

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    assert not any(r["recipient_email"] == emp_email for r in log), \
        "the timesheet sweep must only run on a Monday in the institution's own timezone, even if the hour matches"


def test_reminder_sweep_timesheets_task_uses_institution_configured_day_of_week(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task, configured_email_settings
):
    """reminder_timesheet_day_of_week (Settings -> Notifications -> Reminders,
    default 0=Monday) lets an institution move the sweep to any weekday — and
    "the week that just ended" must still mean the most recently *completed*
    Monday-Sunday week regardless of which day the sweep itself runs on, not
    the week ending on that configured day. Verified via the dedupe_key
    (f"{employee_id}:{period_start}") email_log actually stores, since the
    date only otherwise appears in the email body, which isn't logged."""
    emp_email = f"zztaskwed_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Task Timesheet Wednesday Employee", personal_email=emp_email)
    project = make_test_project(name="ZZ Task Reminder Wednesday Project", member_ids=[emp["employee_id"]])
    make_test_project_task(project["id"])

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    original_day = settings["reminder_timesheet_day_of_week"]
    settings["reminder_timesheet_day_of_week"] = 2  # Wednesday
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    a_wednesday = (_FIXED_MONDAY + timedelta(days=2)).replace(hour=_DEFAULT_HOUR)
    assert a_wednesday.weekday() == 2
    expected_last_period_start = (_FIXED_MONDAY.date() - timedelta(days=7)).isoformat()  # the Monday before _FIXED_MONDAY

    try:
        with patch("core.email_engine.smtplib.SMTP"), patch("core.tasks._reminder_local_now", return_value=a_wednesday):
            result = reminder_sweep_timesheets()
        assert result["sent"] >= 1

        log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
        row = next(r for r in log if r["recipient_email"] == emp_email and r["category"] == "timesheet_reminder")
        assert row["status"] == "sent"
        assert row["dedupe_key"] == f"{emp['employee_id']}:{expected_last_period_start}"
    finally:
        settings["reminder_timesheet_day_of_week"] = original_day
        client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings)


def test_reminder_sweep_holidays_task_emails_when_holiday_tomorrow(
    client, hr_manager_auth, make_test_employee, configured_email_settings
):
    emp_email = f"zztaskholiday_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Task Holiday Employee", personal_email=emp_email)

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    original_holidays_enabled = settings["reminder_holidays_enabled"]
    settings["reminder_holidays_enabled"] = True
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    # sweep_holiday_eve_emails (scripts/send_reminders.py) computes "tomorrow"
    # from the real clock in the institution's own timezone — unaffected by
    # the core.tasks._reminder_local_now patch below, which only gates
    # whether this task considers the sweep due right now.
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    holiday = client.post("/api/holidays", headers=hr_manager_auth, json={
        "name": "ZZ Task Reminder Eve Holiday", "date": tomorrow, "year": int(tomorrow[:4]),
    }).json()

    due_now = _FIXED_MONDAY.replace(hour=_DEFAULT_HOUR)
    try:
        with patch("core.email_engine.smtplib.SMTP"), patch("core.tasks._reminder_local_now", return_value=due_now):
            result = reminder_sweep_holidays()
        assert result["sent"] >= 1

        log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
        row = next(r for r in log if r["recipient_email"] == emp_email and r["category"] == "holiday_reminder")
        assert row["status"] == "sent"
    finally:
        client.delete(f"/api/holidays/{holiday['id']}", headers=hr_manager_auth)
        settings["reminder_holidays_enabled"] = original_holidays_enabled
        client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings)
