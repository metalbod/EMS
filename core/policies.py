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
