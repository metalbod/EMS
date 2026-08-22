"""Employee Resignation: filed by the employee (self-service, Home
dashboard "Resign" button) or by HR on the employee's behalf (Employee
detail, "File Resignation"), routed through its own configurable
approval workflow (module='resignation' in core/approval_workflow.py).

On final approval, employees.resign_date/last_working_day are set and an
Offboarding checklist is auto-started from the institution's default
Offboarding template (routers/onboarding.py's _create_ob_checklist,
factored out of start_ob_checklist for exactly this reuse). Employee
status is left untouched — no cron job in this codebase to act on a
future last_working_day automatically, so HR deactivates manually,
on/after that date, same as they do today.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from core.approval_workflow import start_workflow

from core.audit import write_audit

from routers.onboarding import _create_ob_checklist

from routers.employees import write_employee_change_note

_SYSTEM_ACTOR = {"id": None, "username": "system", "role": "system"}


def file_resignation(conn, inst_id: int, emp, reason: str, effective_date: str, last_working_day: str,
                     attachment: Optional[Dict[str, str]], submitted_by: str) -> int:
    """Inserts the request row and starts its approval workflow — if the
    institution's configured chain has nobody eligible to act on it (e.g.
    a solo employee with no manager and no HR steps configured), it's
    auto-approved immediately, same as every other module on this engine.
    Returns the new request's id."""
    workflow_id, step_order, auto_approved = start_workflow(conn, inst_id, "resignation", emp["employee_id"])
    status = "Approved" if auto_approved else "Pending"
    conn.execute(
        """
        INSERT INTO resignation_requests
        (institution_id,employee_id,reason,effective_date,last_working_day,status,
         attachment_file_name,attachment_mime_type,attachment_data_url,submitted_by,
         approval_workflow_id,approval_step)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (inst_id, emp["employee_id"], reason, effective_date, last_working_day, status,
         attachment.get("file_name") if attachment else None,
         attachment.get("mime_type") if attachment else None,
         attachment.get("data_url") if attachment else None,
         submitted_by, workflow_id, step_order)
    )
    request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    if auto_approved:
        _finalize_resignation(conn, inst_id, conn.execute(
            "SELECT * FROM resignation_requests WHERE id=?", (request_id,)
        ).fetchone(), "approved", _SYSTEM_ACTOR)
    return request_id


def _finalize_resignation(conn, inst_id: int, request_row, outcome: str, actor: Dict[str, Any]) -> None:
    """Applies the terminal outcome ('approved'/'rejected') to a single
    resignation request: on approval, stamps the employee's resign_date/
    last_working_day (logged to the Audit Log and the employee's HR Notes,
    same as every other path that touches those fields — see
    routers/employees.py's write_employee_change_note) and auto-starts an
    Offboarding checklist (default template) — recorded on ob_checklist_id
    so this never double-triggers. On rejection, just updates status;
    employee record untouched. Caller commits (matches
    core/overtime.py's _finalize_overtime shape)."""
    final_status = "Approved" if outcome == "approved" else "Rejected"
    decided_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ob_checklist_id = None

    if outcome == "approved":
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
            (request_row["employee_id"], inst_id)
        ).fetchone()
        old_resign_date = emp["resign_date"] if emp else None
        old_last_working_day = emp["last_working_day"] if emp else None
        conn.execute(
            "UPDATE employees SET resign_date=?,last_working_day=? WHERE employee_id=? AND institution_id=?",
            (request_row["effective_date"], request_row["last_working_day"], request_row["employee_id"], inst_id)
        )
        changes = [
            {"field": "resign_date", "label": "Resign Date", "old": old_resign_date or "", "new": request_row["effective_date"] or ""},
            {"field": "last_working_day", "label": "Last Working Day", "old": old_last_working_day or "", "new": request_row["last_working_day"] or ""},
        ]
        write_audit(conn, actor, inst_id, request_row["employee_id"], emp["full_name"] if emp else request_row["employee_id"],
                    "Resignation Approved", changes)
        write_employee_change_note(conn, inst_id, request_row["employee_id"], actor, changes)
        existing_ob = conn.execute(
            "SELECT id FROM ob_checklists WHERE employee_id=? AND institution_id=? AND type='offboarding' AND status='In Progress'",
            (request_row["employee_id"], inst_id)
        ).fetchone()
        if existing_ob:
            ob_checklist_id = existing_ob["id"]
        elif emp:
            ob_checklist_id = _create_ob_checklist(
                conn, inst_id, emp, "offboarding", None,
                f"Auto-started from resignation request #{request_row['id']}", "system",
                _SYSTEM_ACTOR
            )

    conn.execute(
        "UPDATE resignation_requests SET status=?,approval_step=NULL,decided_by=?,decided_at=?,ob_checklist_id=? WHERE id=?",
        (final_status, actor["username"], decided_at, ob_checklist_id, request_row["id"])
    )
    conn.commit()


def apply_resignation_outcome(conn, inst_id: int, request_row, outcome: str, actor: Dict[str, Any]) -> None:
    """Public entry point for routers/resignation.py's decide endpoint —
    thin wrapper so the 'advanced' (multi-step, not yet final) case is
    handled by the caller and only terminal outcomes reach here."""
    _finalize_resignation(conn, inst_id, request_row, outcome, actor)
