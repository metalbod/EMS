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
# tests only cover the wrapper: each task loops enabled institutions, calls
# through, and (for reminder_sweep_timesheets) computes the right period.
# ---------------------------------------------------------------------------
def test_beat_schedule_has_expected_reminder_entries():
    schedule = celery_app.conf.beat_schedule
    daily = crontab(hour=0, minute=0)  # 08:00 Asia/Kuala_Lumpur (UTC+8, no DST)
    monday = crontab(hour=0, minute=0, day_of_week="monday")

    assert schedule["reminder-sweep-checklists"]["task"] == "core.tasks.reminder_sweep_checklists"
    assert schedule["reminder-sweep-checklists"]["schedule"] == daily
    assert schedule["reminder-sweep-holidays"]["task"] == "core.tasks.reminder_sweep_holidays"
    assert schedule["reminder-sweep-holidays"]["schedule"] == daily
    assert schedule["reminder-sweep-timesheets"]["task"] == "core.tasks.reminder_sweep_timesheets"
    assert schedule["reminder-sweep-timesheets"]["schedule"] == monday


def test_reminder_sweep_checklists_task_emails_overdue_item(
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

    with patch("core.email_engine.smtplib.SMTP"):
        result = reminder_sweep_checklists()
    assert result["sent"] >= 1

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == mgr_email and r["category"] == "checklist_overdue")
    assert row["status"] == "sent"

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_reminder_sweep_timesheets_task_emails_pending_member(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task, configured_email_settings
):
    emp_email = f"zztaskts_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Task Timesheet Employee", personal_email=emp_email)
    project = make_test_project(name="ZZ Task Reminder Project", member_ids=[emp["employee_id"]])
    make_test_project_task(project["id"])

    with patch("core.email_engine.smtplib.SMTP"):
        result = reminder_sweep_timesheets()
    assert result["sent"] >= 1

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == emp_email and r["category"] == "timesheet_reminder")
    assert row["status"] == "sent"


def test_reminder_sweep_holidays_task_emails_when_holiday_tomorrow(
    client, hr_manager_auth, make_test_employee, configured_email_settings
):
    emp_email = f"zztaskholiday_{os.urandom(4).hex()}@zzpytest.example.com"
    emp = make_test_employee(full_name="ZZ Task Holiday Employee", personal_email=emp_email)

    settings = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    original_holidays_enabled = settings["reminder_holidays_enabled"]
    settings["reminder_holidays_enabled"] = True
    assert client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings).status_code == 200

    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    holiday = client.post("/api/holidays", headers=hr_manager_auth, json={
        "name": "ZZ Task Reminder Eve Holiday", "date": tomorrow, "year": int(tomorrow[:4]),
    }).json()

    try:
        with patch("core.email_engine.smtplib.SMTP"):
            result = reminder_sweep_holidays()
        assert result["sent"] >= 1

        log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
        row = next(r for r in log if r["recipient_email"] == emp_email and r["category"] == "holiday_reminder")
        assert row["status"] == "sent"
    finally:
        client.delete(f"/api/holidays/{holiday['id']}", headers=hr_manager_auth)
        settings["reminder_holidays_enabled"] = original_holidays_enabled
        client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=settings)
