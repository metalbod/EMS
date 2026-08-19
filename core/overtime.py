"""Overtime detection and approval-outcome logic.

When a timesheet is submitted (routers/timesheets.py's update_timesheet_status,
"Submitted" branch), generate_overtime_records scans its entries day by day.
An employee's daily working-hours threshold is their resolved Attendance
shift (core/attendance_helpers.resolve_shift) — an employee with no shift
on file (no assignment, no matching attendance_settings default) gets no
overtime detection at all, since there's nothing to compare against. Any
day where logged hours exceed the threshold becomes one overtime_records
row, routed through its own approval workflow (module='overtime' in
core/approval_workflow.py — see PROJECT_MANAGER_MODULES there for how a
project_manager step resolves via the parent timesheet's own projects).

On final approval (routers/overtime.py), apply_overtime_outcome either
credits the institution's configured leave type (core/leave_balance_ops.
_credit_balance) or records a tracked pay amount — see institutions.
overtime_conversion_mode. Pay is tracking-only this round, not wired into
payroll.
"""
from datetime import datetime
from typing import Any, Dict, List

from core.attendance_helpers import resolve_shift, shift_duration_hours

from core.approval_workflow import start_workflow, project_ids_for_row

from core.leave_balance_ops import _get_or_create_leave_balance, _credit_balance

# Approximates a Monthly-salary employee's hourly rate the same way
# routers/payroll.py's own overtime approximation already does — see that
# file's MONTHLY_NORMAL_HOURS disclaimer, same caveat applies here.
MONTHLY_NORMAL_HOURS = 176.0


def _hourly_rate_equivalent(emp) -> float:
    if emp["salary_type"] == "Hourly":
        return float(emp["hourly_rate"] or 0)
    return float(emp["basic_salary"] or 0) / MONTHLY_NORMAL_HOURS


def generate_overtime_records(conn, inst_id: int, timesheet: Dict[str, Any]) -> List[int]:
    """Regenerates this timesheet's not-yet-finalized overtime records
    (deletes existing Pending/Rejected ones for it first — a resubmit
    after edits/rejection shouldn't leave stale rows around; Approved
    records are untouched since they're already finalized) and recomputes
    from its current entries. Returns the new records' ids."""
    conn.execute(
        "DELETE FROM overtime_records WHERE timesheet_id=? AND status IN ('Pending','Rejected')",
        (timesheet["id"],)
    )

    emp = conn.execute(
        "SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
        (timesheet["employee_id"], inst_id)
    ).fetchone()
    if not emp:
        return []

    inst = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
    conversion_mode = inst["overtime_conversion_mode"] if inst else "pay"

    daily_totals = conn.execute(
        "SELECT date, SUM(hours) AS total_hours FROM timesheet_entries WHERE timesheet_id=? GROUP BY date",
        (timesheet["id"],)
    ).fetchall()

    created_ids = []
    for row in daily_totals:
        work_date = row["date"]
        logged_hours = float(row["total_hours"])
        shift = resolve_shift(conn, inst_id, emp["employee_id"], emp["department"], work_date)
        if not shift:
            continue  # no attendance requirement on file — nothing to compare against
        threshold_hours = shift_duration_hours(shift)
        overtime_hours = round(logged_hours - threshold_hours, 4)
        if overtime_hours <= 0:
            continue

        workflow_id, step_order, auto_approved = start_workflow(
            conn, inst_id, "overtime", emp["employee_id"], project_ids_for_row(conn, "timesheet", timesheet)
        )
        conn.execute(
            """
            INSERT INTO overtime_records
            (institution_id,employee_id,timesheet_id,work_date,shift_id,threshold_hours,logged_hours,
             overtime_hours,status,approval_workflow_id,approval_step,conversion_mode)
            VALUES (?,?,?,?,?,?,?,?,'Pending',?,?,?)
            """,
            (inst_id, emp["employee_id"], timesheet["id"], work_date, shift["id"], threshold_hours, logged_hours,
             overtime_hours, workflow_id, step_order, conversion_mode)
        )
        record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        created_ids.append(record_id)
        if auto_approved:
            _finalize_overtime(conn, inst_id, conn.execute(
                "SELECT * FROM overtime_records WHERE id=?", (record_id,)
            ).fetchone(), "approved", "system")

    conn.commit()
    return created_ids


def _finalize_overtime(conn, inst_id: int, record, outcome: str, approved_by: str) -> None:
    """Applies the terminal outcome ('approved'/'rejected') to a single
    overtime record: credits leave or records a pay amount on approval,
    just updates status on rejection. Caller commits."""
    final_status = "Approved" if outcome == "approved" else "Rejected"
    leave_days_credited, pay_amount = None, None

    if outcome == "approved":
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
            (record["employee_id"], inst_id)
        ).fetchone()
        overtime_hours = float(record["overtime_hours"])
        if record["conversion_mode"] == "leave":
            inst = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
            if inst and inst["overtime_leave_type_id"]:
                threshold_hours = float(record["threshold_hours"]) or 1.0
                leave_days_credited = round(overtime_hours / threshold_hours, 4)
                year = datetime.strptime(record["work_date"], "%Y-%m-%d").year
                bal = _get_or_create_leave_balance(conn, inst_id, record["employee_id"], inst["overtime_leave_type_id"], year)
                _credit_balance(conn, bal, leave_days_credited)
        else:
            rate = _hourly_rate_equivalent(emp) if emp else 0.0
            inst = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
            multiplier = float(inst["overtime_pay_multiplier"]) if inst else 1.5
            pay_amount = round(overtime_hours * rate * multiplier, 2)

    conn.execute(
        "UPDATE overtime_records SET status=?,approval_step=NULL,approved_by=?,approved_at=?,"
        "leave_days_credited=?,pay_amount=? WHERE id=?",
        (final_status, approved_by, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
         leave_days_credited, pay_amount, record["id"])
    )


def apply_overtime_outcome(conn, inst_id: int, record, outcome: str, approved_by: str) -> None:
    """Public entry point for routers/overtime.py's decide endpoint —
    thin wrapper so the 'advanced' (multi-step, not yet final) case is
    handled by the caller and only terminal outcomes reach here."""
    _finalize_overtime(conn, inst_id, record, outcome, approved_by)
