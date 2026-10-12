"""Shared helpers for policy acknowledgements (routers/policies.py, onboarding links).

A policy is an `ld_courses` row with category 'policy'; its versions live in `policy_versions`
and each assigned person has one `policy_acknowledgements` row per version. See migration
20261013_0001.
"""
from typing import List, Optional

from core.org_queries import subordinates_in_clause

POLICY_CATEGORY = "policy"
AUDIENCE_TYPES = ("all", "department", "team", "people")


def current_version(conn, inst_id: int, course_id: int):
    """The latest published version of a policy (highest version number), or None."""
    return conn.execute(
        "SELECT * FROM policy_versions WHERE course_id=? AND institution_id=? ORDER BY version DESC LIMIT 1",
        (course_id, inst_id)
    ).fetchone()


def resolve_audience(conn, inst_id: int, audience_type: str, audience_ref: Optional[str],
                     employee_ids: Optional[List[str]] = None) -> List[str]:
    """Employee ids (Active only) an audience spec covers right now."""
    if audience_type == "all":
        rows = conn.execute("SELECT employee_id FROM employees WHERE institution_id=? AND status='Active'", (inst_id,)).fetchall()
    elif audience_type == "department":
        rows = conn.execute("SELECT employee_id FROM employees WHERE institution_id=? AND status='Active' AND department=?",
                            (inst_id, audience_ref)).fetchall()
    elif audience_type == "team":
        frag, fp = subordinates_in_clause(inst_id, audience_ref or "")
        rows = conn.execute(f"SELECT employee_id FROM employees WHERE institution_id=? AND status='Active' AND employee_id IN {frag}",
                            [inst_id, *fp]).fetchall()
    else:  # people
        ids = list(dict.fromkeys(employee_ids or []))
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT employee_id FROM employees WHERE institution_id=? AND status='Active' AND employee_id IN ({marks})",
                            [inst_id, *ids]).fetchall()
    return [r["employee_id"] for r in rows]


def assign_version(conn, inst_id: int, version_id: int, employee_ids: List[str]) -> int:
    """Create a pending acknowledgement row for each employee not already assigned this version.
    Returns how many were newly assigned."""
    added = 0
    for emp_id in employee_ids:
        cur = conn.execute(
            "INSERT INTO policy_acknowledgements (institution_id,version_id,employee_id) VALUES (?,?,?) "
            "ON CONFLICT (version_id, employee_id) DO NOTHING",
            (inst_id, version_id, emp_id)
        )
        added += 1 if cur.rowcount else 0
    return added


def assign_current_version(conn, inst_id: int, employee_id: str, course_id: int) -> Optional[int]:
    """Assign one employee the current version of a policy (used when an onboarding checklist
    item is linked to it). Returns the acknowledgement id, or None if the policy has no version."""
    ver = current_version(conn, inst_id, course_id)
    if not ver:
        return None
    assign_version(conn, inst_id, ver["id"], [employee_id])
    row = conn.execute("SELECT id FROM policy_acknowledgements WHERE version_id=? AND employee_id=?",
                       (ver["id"], employee_id)).fetchone()
    return row["id"] if row else None


def today_for_institution(conn, inst_id: int) -> str:
    """Today's date (YYYY-MM-DD) in the institution's own timezone — what 'overdue' is judged against."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    row = conn.execute("SELECT timezone FROM institutions WHERE id=?", (inst_id,)).fetchone()
    try:
        tz = ZoneInfo((row["timezone"] if row else None) or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def ack_status(ack, due_date: Optional[str], today: str) -> str:
    """'acknowledged' | 'overdue' | 'opened' | 'not_opened' for one acknowledgement row."""
    if ack["acknowledged_at"]:
        return "acknowledged"
    if due_date and due_date < today:
        return "overdue"
    return "opened" if ack["first_opened_at"] else "not_opened"


# ---------------------------------------------------------------------------
# Reminders (automatic sweep in scripts/send_reminders.py, manual button in routers/policies.py)
# ---------------------------------------------------------------------------
REMINDER_CATEGORY = "policy_reminder"
REMIND_BEFORE_DUE_DAYS = 3     # the automatic reminders start this many days before the due date
AUTO_REMIND_EVERY_DAYS = 7     # ...then repeat this often while it's still unacknowledged
MANUAL_REMIND_COOLDOWN_DAYS = 1


def reminder_dedupe_key(version_id: int, employee_id: str) -> str:
    """One key per person per version for every kind of reminder, so a manual nudge also holds off
    the next automatic one and the tracker can show a single 'last reminded'."""
    return f"policy:{version_id}:{employee_id}"


def reminder_email(title: str, version: int, due_date: Optional[str], today: str, name: Optional[str], app_url: str):
    """(subject, html) for a 'please acknowledge' email."""
    if due_date and due_date < today:
        when = f"It was due on {due_date}."
        subject = f"Overdue: please acknowledge {title}"
    elif due_date:
        when = f"Please do so by {due_date}."
        subject = f"Please acknowledge {title}"
    else:
        when = ""
        subject = f"Please acknowledge {title}"
    body = (
        f"<p>Hi {name or 'there'},</p>"
        f"<p><strong>{title}</strong> (version {version}) is waiting for your acknowledgement. {when}</p>"
        f'<p><a href="{app_url}">Open EMS</a> and go to L&amp;D → My Trainings to read and acknowledge it.</p>'
    )
    return subject, body


def last_reminded_map(conn, inst_id: int, version_id: int) -> dict:
    """{employee_id: last reminder time (UTC text)} for one version, from the email log."""
    prefix = f"policy:{version_id}:"
    rows = conn.execute(
        "SELECT dedupe_key, MAX(created_at) AS at FROM email_log "
        "WHERE institution_id=? AND category=? AND status='sent' AND dedupe_key LIKE ? GROUP BY dedupe_key",
        (inst_id, REMINDER_CATEGORY, prefix + "%")
    ).fetchall()
    return {r["dedupe_key"][len(prefix):]: r["at"] for r in rows}


def csv_cell(value) -> str:
    """A CSV-safe cell: quoted, and neutralised if a spreadsheet would read it as a formula."""
    s = "" if value is None else str(value)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return '"' + s.replace('"', '""') + '"'
