#!/usr/bin/env python3
"""Reminder sweep — Phase 2 of the email notification engine (see
core/email_engine.py and migrations/versions/20260919_0001_email_notifications.py,
20260920_0001_email_log_dedupe_key.py).

Standalone script (same pattern as celery_worker.py/apply_migration.py at
the repo root). In production this isn't invoked directly — its sweep
functions (sweep_overdue_checklists, sweep_pending_timesheets,
sweep_holiday_eve_emails, _enabled_institutions) are called by the
beat-scheduled tasks in core/tasks.py (reminder_sweep_checklists/
_holidays/_timesheets, see its beat_schedule and the "reminders" process
group in fly.toml — `celery -A core.tasks beat`) rather than duplicated
there, so there's exactly one implementation of each sweep. This file
stays around unchanged as the manual entry point: `python3
scripts/send_reminders.py [--dry-run]`, e.g. via `fly ssh console` to
run a real sweep on demand against production. It has no HTTP endpoint
or auth of its own — running it is an infra/ops action, not an
app-level one.

For every institution with notifications_email_enabled=true, sweeps
whichever of the following categories that institution has separately
opted into via its own reminder_<category>_enabled column (Settings ->
Notifications -> Reminders tab; migrations/versions/
20260922_0001_reminder_category_toggles.py) — each of these narrows,
never replaces, the master notifications_email_enabled toggle:

  - Overdue onboarding/offboarding checklist items (reminder_onboarding_enabled
    / reminder_offboarding_enabled — independently toggleable, swept
    separately by ob_checklists.type): any ob_checklist_items row still
    'Pending' past its due_date. Recipient is whoever holds that item's
    assigned_role — the checklist's own employee's direct manager if
    assigned_role=='manager' (narrower than "every manager in the
    institution"), otherwise every active user holding that role
    institution-wide. Re-reminded at most once every REMIND_COOLDOWN_DAYS
    while it stays overdue (checked every run, any day of the week).

  - Employees with no Submitted/Approved timesheet for the week that
    just ended (reminder_timesheet_enabled): only active employees who
    are a specific, named member of at least one currently-Active
    project. An is_open_to_all project deliberately does NOT grant
    blanket eligibility here (unlike elsewhere in the app) — that made
    nearly every employee in an institution "eligible" the moment any
    one open project existed, which meant this reminder fired for the
    whole company regardless of whether they actually had anything to
    log; a real project_members row is required instead. Membership in
    an On Hold or Completed project alone does NOT count either
    (there's nothing current to log time against there). Reminded once
    per missed period, never re-sent once logged (checked only when
    this script runs on a Monday, regardless of what time Fly's
    scheduler actually wakes it — the schedule only controls *when*
    this runs, not what it decides to do that day).

  - A public holiday falling tomorrow (reminder_holidays_enabled): every
    active employee gets an email, using the exact same "holiday is
    tomorrow, in the institution's own timezone" detection as the
    dashboard eve-banner (routers/notifications.py's
    _holiday_eve_virtual_notification) — but this is an independent
    toggle and an independent delivery channel; an institution can have
    the banner on, this email off, or both. Reminded once per employee
    per holiday, never re-sent for the same holiday.

reminder_acknowledgement_enabled is stored but not swept here — nothing
reads it yet, since the "document acknowledgement" feature it will
eventually gate doesn't exist.

All categories dedupe against email_log's dedupe_key column rather than
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
from zoneinfo import ZoneInfo

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
    """Full institution rows (not just id) — core/tasks.py's beat-scheduled
    reminder tasks need each institution's own timezone and
    reminder_<category>_hour columns to decide whether a sweep is due right
    now, not just its id."""
    return conn.execute("SELECT * FROM institutions WHERE notifications_email_enabled=true").fetchall()


_CHECKLIST_TYPE_TOGGLE_COLUMN = {"onboarding": "reminder_onboarding_enabled", "offboarding": "reminder_offboarding_enabled"}


def _category_enabled(conn, inst_id, column):
    """Reads one institutions.reminder_<category>_enabled column — each
    sweep function below checks its own toggle so it's a fully
    self-contained, independently testable unit (matches how
    already_sent_recently/send_email are called directly by each sweep
    rather than pre-filtered by the caller)."""
    row = conn.execute(f"SELECT {column} FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return bool(row and row[column])


def sweep_overdue_checklists(conn, inst_id, today_str, checklist_type, dry_run):
    """checklist_type is 'onboarding' or 'offboarding' — the two are
    swept, dedupe-tracked, and toggled independently (institutions.
    reminder_onboarding_enabled / reminder_offboarding_enabled)."""
    if not _category_enabled(conn, inst_id, _CHECKLIST_TYPE_TOGGLE_COLUMN[checklist_type]):
        return 0
    items = conn.execute(
        "SELECT i.*, c.employee_id AS checklist_employee_id FROM ob_checklist_items i "
        "JOIN ob_checklists c ON c.id = i.checklist_id "
        "WHERE i.institution_id=? AND c.type=? AND i.status='Pending' AND i.due_date IS NOT NULL AND i.due_date < ?",
        (inst_id, checklist_type, today_str)
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
                send_email(conn, inst_id, email, subject, greeting, "checklist_overdue", checklist_type, dedupe_key)
        if not dry_run:
            conn.commit()
        sent += len(contacts)
    return sent


def sweep_pending_timesheets(conn, inst_id, period_start, dry_run):
    if not _category_enabled(conn, inst_id, "reminder_timesheet_enabled"):
        return 0
    employees = conn.execute(
        "SELECT employee_id, full_name, work_email, personal_email FROM employees "
        "WHERE institution_id=? AND status='Active'",
        (inst_id,)
    ).fetchall()

    sent = 0
    for emp in employees:
        is_member = conn.execute(
            "SELECT 1 FROM project_members pm JOIN projects p ON p.id = pm.project_id "
            "WHERE p.institution_id=? AND pm.employee_id=? AND p.status='Active' LIMIT 1",
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


def sweep_holiday_eve_emails(conn, inst_id, dry_run):
    """Emails every active employee when a public holiday falls tomorrow,
    in the institution's own timezone — same "is a holiday exactly one
    calendar day away" detection as the dashboard eve-banner
    (routers/notifications.py's _holiday_eve_virtual_notification), but
    gated by its own independent toggle (reminder_holidays_enabled) and
    an independent channel (email, not a dashboard banner). Dedupe key
    is per-employee-per-holiday, not just per-holiday, so one employee's
    logged send doesn't suppress everyone else's for the same day."""
    if not _category_enabled(conn, inst_id, "reminder_holidays_enabled"):
        return 0
    row = conn.execute("SELECT timezone FROM institutions WHERE id=?", (inst_id,)).fetchone()
    try:
        tz = ZoneInfo(row["timezone"] or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    tomorrow = (datetime.now(tz).date() + timedelta(days=1)).isoformat()
    holiday = conn.execute(
        "SELECT id, name FROM holidays WHERE institution_id=? AND date=?", (inst_id, tomorrow)
    ).fetchone()
    if not holiday:
        return 0

    employees = conn.execute(
        "SELECT employee_id, full_name, work_email, personal_email FROM employees "
        "WHERE institution_id=? AND status='Active'",
        (inst_id,)
    ).fetchall()
    subject = f"Reminder: {holiday['name']} is tomorrow"
    sent = 0
    for emp in employees:
        email = emp["work_email"] or emp["personal_email"]
        if not email:
            continue
        dedupe_key = f"{emp['employee_id']}:holiday:{holiday['id']}"
        if already_sent_recently(conn, inst_id, "holiday_reminder", dedupe_key, cooldown_days=0):
            continue  # never re-send this employee for the same holiday

        body = (
            f"<p>Hi {emp['full_name'] or 'there'},</p>"
            f"<p><strong>{holiday['name']}</strong> is a public holiday tomorrow ({tomorrow}).</p>"
        )
        if dry_run:
            print(f"[DRY RUN] holiday_reminder -> {email}: {subject}")
        else:
            send_email(conn, inst_id, email, subject, body, "holiday_reminder", "holidays", dedupe_key)
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
        total_checklist = total_timesheet = total_holiday = 0
        for inst in institutions:
            inst_id = inst["id"]
            # Each sweep checks its own reminder_<category>_enabled column
            # (see _category_enabled) — no need to pre-filter here.
            total_checklist += sweep_overdue_checklists(conn, inst_id, today_str, "onboarding", args.dry_run)
            total_checklist += sweep_overdue_checklists(conn, inst_id, today_str, "offboarding", args.dry_run)
            if is_monday:
                total_timesheet += sweep_pending_timesheets(conn, inst_id, last_period_start, args.dry_run)
            total_holiday += sweep_holiday_eve_emails(conn, inst_id, args.dry_run)
    finally:
        conn.close()

    msg = (
        f"Reminder sweep complete ({'dry run, ' if args.dry_run else ''}"
        f"{len(institutions)} institution(s)): "
        f"{total_checklist} checklist reminder(s), {total_timesheet} timesheet reminder(s), "
        f"{total_holiday} holiday reminder(s)"
        f"{' (timesheet check skipped, not Monday)' if not is_monday else ''}."
    )
    logger.info(msg)
    print(msg)


if __name__ == "__main__":
    main()
