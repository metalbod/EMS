"""Manager-initiated Performance Improvement Plan (PIP): a direct (or
recursive-chain) manager proposes a PIP for a report, routed through its
own configurable approval workflow (module='pip' — see
core/approval_workflow.py, whose default chain for this module is a
single hr_manager step, not the usual direct_manager -> hr_manager, since
the manager here IS the proposer, not a requester needing their own
manager's sign-off).

Modeled as another performance_cycles row (cycle_type='pip'), reusing
the same employee-scoped-cycle + goals machinery Probation Review
established — but unlike probation, a PIP never gets an appraisals row:
its "final assessment" is a plain recorded outcome (Successful/Extended/
Failed + notes), not a numeric rating, and its check-ins are a
lightweight dated log (pip_checkins) rather than a repeated formal
review. Both PIP approval and outcome recording write an HR Note
(note_type='performance', via core/compensation_helpers.py's
add_hr_note) so there's a durable, chronological trail alongside every
other consequential Performance/Compensation event that already does
the same. No other side effect fires automatically — a Failed outcome
does not auto-trigger Offboarding or any employee-status change; HR
decides what happens next as a separate, deliberate action.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.approval_workflow import start_workflow

from core.compensation_helpers import add_hr_note

_SYSTEM_ACTOR = {"id": None, "username": "system", "role": "system"}


def propose_pip(conn, inst_id: int, employee, manager_user: dict, reason: str,
                start_date: str, end_date: str, goals: List[Dict[str, Any]]) -> int:
    """Inserts the performance_cycles row (status='PendingApproval') and
    its initial goals, then starts the approval workflow. If the
    institution's configured chain has nobody eligible to act (e.g. no
    hr_manager exists at all), it's auto-approved immediately, same as
    every other module on this engine. Returns the new cycle's id."""
    workflow_id, step_order, auto_approved = start_workflow(conn, inst_id, "pip", employee["employee_id"])
    status = "Active" if auto_approved else "PendingApproval"
    name = f"PIP — {employee['full_name']}"
    conn.execute(
        """
        INSERT INTO performance_cycles
        (institution_id,name,period_start,period_end,status,cycle_type,employee_id,reason,
         approval_workflow_id,approval_step,created_by)
        VALUES (?,?,?,?,?,'pip',?,?,?,?,?)
        """,
        (inst_id, name, start_date, end_date, status, employee["employee_id"], reason,
         workflow_id, step_order, manager_user["username"])
    )
    cycle_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for g in goals:
        conn.execute(
            """
            INSERT INTO goals (institution_id,cycle_id,employee_id,goal_type,title,description,weight,target_value,actual_value,unit,created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (inst_id, cycle_id, employee["employee_id"], g.get("goal_type", "KPI"), g["title"],
             g.get("description"), g.get("weight", 0.0), g.get("target_value"), g.get("actual_value"),
             g.get("unit"), manager_user["username"])
        )
    conn.commit()
    if auto_approved:
        _apply_pip_decision(conn, inst_id, conn.execute(
            "SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)
        ).fetchone(), "approved", _SYSTEM_ACTOR)
    return cycle_id


def _apply_pip_decision(conn, inst_id: int, cycle_row, outcome: str, actor: Dict[str, Any]) -> None:
    """Applies the terminal HR decision ('approved'/'rejected') to a
    single PIP cycle. On approval, the cycle goes Active (goals/check-ins
    can now be tracked) and an HR Note records that the PIP has started.
    On rejection, the cycle is just marked Rejected — the employee record
    is never touched by a PIP at any point, unlike Resignation."""
    if outcome == "approved":
        conn.execute("UPDATE performance_cycles SET status='Active',approval_step=NULL WHERE id=?", (cycle_row["id"],))
        add_hr_note(
            conn, inst_id, cycle_row["employee_id"],
            f"Performance Improvement Plan started ({cycle_row['period_start']} to {cycle_row['period_end']}): {cycle_row['reason']}",
            actor["username"],
        )
    else:
        conn.execute("UPDATE performance_cycles SET status='Rejected',approval_step=NULL WHERE id=?", (cycle_row["id"],))
    conn.commit()


def apply_pip_decision(conn, inst_id: int, cycle_row, outcome: str, actor: Dict[str, Any]) -> None:
    """Public entry point for routers/performance.py's decide endpoint —
    thin wrapper so the 'advanced' (not-yet-final) case is handled by the
    caller and only terminal outcomes reach here, matching
    core/resignation.py's apply_resignation_outcome shape."""
    _apply_pip_decision(conn, inst_id, cycle_row, outcome, actor)


def record_pip_outcome(conn, inst_id: int, cycle_row, outcome: str, notes: Optional[str],
                       new_end_date: Optional[str], actor: Dict[str, Any]) -> None:
    """Records a PIP's final outcome. 'Successful'/'Failed' close the
    cycle; 'Extended' keeps it Active with a pushed-out period_end and
    clears any prior outcome, rather than creating a new cycle — matches
    the manager-defined, flexible-timeline design (no fixed Month 1/2/3
    milestones like Probation Review). Every call writes an HR Note; no
    other side effect fires automatically regardless of outcome."""
    decided_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if outcome == "Extended":
        conn.execute(
            "UPDATE performance_cycles SET period_end=?,outcome=NULL,outcome_notes=NULL,"
            "outcome_decided_by=NULL,outcome_decided_at=NULL WHERE id=?",
            (new_end_date, cycle_row["id"])
        )
    else:
        conn.execute(
            "UPDATE performance_cycles SET status='Closed',outcome=?,outcome_notes=?,"
            "outcome_decided_by=?,outcome_decided_at=? WHERE id=?",
            (outcome, notes, actor["username"], decided_at, cycle_row["id"])
        )
    add_hr_note(
        conn, inst_id, cycle_row["employee_id"],
        f"Performance Improvement Plan outcome recorded: {outcome}. {notes or ''}".strip(),
        actor["username"],
    )
    conn.commit()
