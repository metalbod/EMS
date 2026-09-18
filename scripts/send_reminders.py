#!/usr/bin/env python3
"""Reminder sweep — Phase 2 of the email notification engine (see
core/email_engine.py and migrations/versions/20260919_0001_email_notifications.py,
20260920_0001_email_log_dedupe_key.py).

Standalone script (same pattern as celery_worker.py/apply_migration.py at
the repo root), meant to be invoked once a day by a Fly.io scheduled
machine — provisioning that machine (a "reminders" process group in
fly.toml, `fly scale count`, and `fly machine update --schedule=daily`,
re-applied after every deploy since a redeploy can silently drop a
machine's schedule) is deliberately NOT part of this script or of
deploy.sh; that's a separate, manual infrastructure step. This script
has no HTTP endpoint or auth of its own, since only Fly's own scheduler
is expected to run it.

For every institution with notifications_email_enabled=true, sweeps:

  - Overdue onboarding/offboarding checklist items: any ob_checklist_items
    row still 'Pending' past its due_date. Recipient is whoever holds
    that item's assigned_role — the checklist's own employee's direct
    manager if assigned_role=='manager' (narrower than "every manager in
    the institution"), otherwise every active user holding that role
    institution-wide. Re-reminded at most once every REMIND_COOLDOWN_DAYS
    while it stays overdue (checked every run, any day of the week).

  - Employees with no Submitted/Approved timesheet for the week that
    just ended: only active employees who could plausibly have logged
    anything (a member of at least one project, or the institution has
    an is_open_to_all project) — reminded once per missed period, never
    re-sent once logged (checked only when this script runs on a
    Monday, regardless of what time Fly's scheduler actually wakes it —
    the schedule only controls *when* this runs, not what it decides to
    do that day).

Both categories dedupe against email_log's dedupe_key column rather than
any new tracking table.

Usage:
    python3 scripts/send_reminders.py [--dry-run]

--dry-run prints what would be sent without calling send_email or
writing to email_log — safe to run against the real database to sanity
check before pointing a real Fly schedule at this.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(env_file)

from db import get_db, set_rls_context  # noqa: E402
from core.email_engine import send_email, already_sent_recently  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ems")

REMIND_COOLDOWN_DAYS = 3
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://ems-app.fly.dev")


def _employee_contact(conn, inst_id, employee_id):
    if not employee_id:
        return None, None
    row = conn.execute(
        "SELECT full_name, work_email, personal_email FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    if not row:
        return None, None
    return row["full_name"], (row["work_email"] or row["personal_email"])


def _role_holder_contacts(conn, inst_id, role):
    rows = conn.execute(
        "SELECT email, employee_id FROM users WHERE institution_id=? AND role=? AND is_active=1",
        (inst_id, role)
    ).fetchall()
    contacts = []
    for r in rows:
        email = r["email"]
        name = None
        if r["employee_id"]:
            emp_name, emp_email = _employee_contact(conn, inst_id, r["employee_id"])
            name = emp_name
            email = email or emp_email
        if email:
            contacts.append((name, email))
    return contacts


def _dedupe_contacts(contacts):
    seen, out = set(), []
    for name, email in contacts:
        if email and email not in seen:
            seen.add(email)
            out.append((name, email))
    return out


def _enabled_institutions(conn):
    return conn.execute("SELECT id FROM institutions WHERE notifications_email_enabled=true").fetchall()


def sweep_overdue_checklists(conn, inst_id, today_str, dry_run):
    items = conn.execute(
        "SELECT i.*, c.employee_id AS checklist_employee_id FROM ob_checklist_items i "
        "JOIN ob_checklists c ON c.id = i.checklist_id "
        "WHERE i.institution_id=? AND i.status='Pending' AND i.due_date IS NOT NULL AND i.due_date < ?",
        (inst_id, today_str)
    ).fetchall()
    sent = 0
    for item in items:
        dedupe_key = f"item:{item['id']}"
        if already_sent_recently(conn, inst_id, "checklist_overdue", dedupe_key, REMIND_COOLDOWN_DAYS):
            continue

        if item["assigned_role"] == "manager":
            mgr_row = conn.execute(
                "SELECT reports_to FROM employees WHERE employee_id=? AND institution_id=?",
                (item["checklist_employee_id"], inst_id)
            ).fetchone()
            mgr_id = mgr_row["reports_to"] if mgr_row else None
            name, email = _employee_contact(conn, inst_id, mgr_id)
            contacts = [(name, email)] if email else []
        else:
            contacts = _role_holder_contacts(conn, inst_id, item["assigned_role"])
        contacts = _dedupe_contacts(contacts)
        if not contacts:
            continue

        emp_name, _ = _employee_contact(conn, inst_id, item["checklist_employee_id"])
        subject = f"Checklist item overdue: {item['title']}"
        body = (
            f"<p>Hi {{name}},</p>"
            f"<p>The checklist item <strong>{item['title']}</strong> for {emp_name or 'an employee'} "
            f"was due on {item['due_date']} and is still outstanding.</p>"
            f'<p><a href="{APP_BASE_URL}">Open EMS</a> to review it.</p>'
        )
        for name, email in contacts:
            greeting = body.format(name=name or "there")
            if dry_run:
                print(f"[DRY RUN] checklist_overdue -> {email}: {subject}")
            else:
                send_email(conn, inst_id, email, subject, greeting, "checklist_overdue", "onboarding", dedupe_key)
        if not dry_run:
            conn.commit()
        sent += len(contacts)
    return sent


def sweep_pending_timesheets(conn, inst_id, period_start, dry_run):
    has_open_project = conn.execute(
        "SELECT 1 FROM projects WHERE institution_id=? AND is_open_to_all=true AND status='Active' LIMIT 1",
        (inst_id,)
    ).fetchone() is not None

    employees = conn.execute(
        "SELECT employee_id, full_name, work_email, personal_email FROM employees "
        "WHERE institution_id=? AND status='Active'",
        (inst_id,)
    ).fetchall()

    sent = 0
    for emp in employees:
        if not has_open_project:
            is_member = conn.execute(
                "SELECT 1 FROM project_members pm JOIN projects p ON p.id = pm.project_id "
                "WHERE p.institution_id=? AND pm.employee_id=? LIMIT 1",
                (inst_id, emp["employee_id"])
            ).fetchone()
            if not is_member:
                continue

        already_submitted = conn.execute(
            "SELECT 1 FROM timesheets WHERE institution_id=? AND employee_id=? AND period_start=? "
            "AND status IN ('Submitted','Approved') LIMIT 1",
            (inst_id, emp["employee_id"], period_start)
        ).fetchone()
        if already_submitted:
            continue

        dedupe_key = f"{emp['employee_id']}:{period_start}"
        if already_sent_recently(conn, inst_id, "timesheet_reminder", dedupe_key, cooldown_days=0):
            continue  # cooldown_days=0 means "ever" — never re-send for the same missed period

        email = emp["work_email"] or emp["personal_email"]
        if not email:
            continue

        subject = "Your timesheet for last week hasn't been submitted"
        body = (
            f"<p>Hi {emp['full_name'] or 'there'},</p>"
            f"<p>Your timesheet for the week starting {period_start} hasn't been submitted yet.</p>"
            f'<p><a href="{APP_BASE_URL}">Open EMS</a> to submit it.</p>'
        )
        if dry_run:
            print(f"[DRY RUN] timesheet_reminder -> {email}: {subject}")
        else:
            send_email(conn, inst_id, email, subject, body, "timesheet_reminder", "timesheet", dedupe_key)
            conn.commit()
        sent += 1
    return sent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be sent without sending or logging anything")
    args = parser.parse_args()

    set_rls_context(None, bypass_rls=True)
    conn = get_db()
    try:
        today = datetime.now(timezone.utc).date()
        today_str = today.isoformat()
        is_monday = today.weekday() == 0
        last_period_start = (today - timedelta(days=today.weekday() + 7)).isoformat()

        institutions = _enabled_institutions(conn)
        total_checklist = total_timesheet = 0
        for inst in institutions:
            inst_id = inst["id"]
            total_checklist += sweep_overdue_checklists(conn, inst_id, today_str, args.dry_run)
            if is_monday:
                total_timesheet += sweep_pending_timesheets(conn, inst_id, last_period_start, args.dry_run)
    finally:
        conn.close()

    msg = (
        f"Reminder sweep complete ({'dry run, ' if args.dry_run else ''}"
        f"{len(institutions)} institution(s)): "
        f"{total_checklist} checklist reminder(s), {total_timesheet} timesheet reminder(s)"
        f"{' (timesheet check skipped, not Monday)' if not is_monday else ''}."
    )
    logger.info(msg)
    print(msg)


if __name__ == "__main__":
    main()
