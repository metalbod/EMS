"""Overtime detection and approval-outcome logic.

When a timesheet is submitted (routers/timesheets.py's update_timesheet_status,
"Submitted" branch), generate_overtime_records scans its entries day by day.
An employee's daily working-hours threshold is their resolved Attendance
shift (core/attendance_helpers.resolve_shift) — an employee with no shift
on file (no assignment, no matching attendance_settings default) gets no
overtime detection at all, since there's nothing to compare against. Any
day where logged hours exceed the threshold becomes one overtime_records
row (the day-level container: threshold/logged/overtime hours for that
date).

As of 2026-09-17, that day's overtime_hours is further split across
overtime_project_approvals — one row per project logged that day,
prorated by each project's share of the day's hours (a day's overtime
isn't tied to one project any more than a timesheet's approval is; see
migrations/versions/20260917_0001 for the reasoning and the equivalent
Timesheet-side split). Each project row runs its own approval workflow
instance (module='overtime' in core/approval_workflow.py, project_manager
resolving against just that one project) and its own leave/pay
conversion on approval. overtime_records.status/approval_workflow_id/
approval_step are left NULL/unused for these split records — real state
lives on the children — and kept exactly as before for legacy
(pre-split) records, which are never backfilled.

On final approval, apply_overtime_project_outcome (new-style, per
project) or apply_overtime_outcome (legacy, per day) either credits the
institution's configured leave type (core/leave_balance_ops.
_credit_balance) or records a tracked pay amount — see institutions.
overtime_conversion_mode. Pay is tracking-only this round, not wired into
payroll.
"""
from datetime import datetime
from typing import Any, Dict, List

from core.attendance_helpers import resolve_shift, shift_duration_hours

from core.approval_workflow import start_workflow, project_ids_for_row

from core.leave_balance_ops import _get_or_create_leave_balance, _credit_balance

# Simplified monthly normal-hours threshold (8hrs x 22 working days), shared
# with routers/payroll.py's own overtime-pay split (which imports this
# constant rather than redeclaring it). This is an approximation —
# Malaysia's Employment Act overtime rules are based on daily/weekly
# limits, not a flat monthly figure; verify before relying on it.
MONTHLY_NORMAL_HOURS = 176.0


def _hourly_rate_equivalent(emp) -> float:
    if emp["salary_type"] == "Hourly":
        return float(emp["hourly_rate"] or 0)
    return float(emp["basic_salary"] or 0) / MONTHLY_NORMAL_HOURS


def generate_overtime_records(conn, inst_id: int, timesheet: Dict[str, Any]) -> List[int]:
    """Regenerates this timesheet's not-yet-finalized overtime records
    (deletes existing Pending/Rejected ones for it first, and their
    per-project children — a resubmit after edits/rejection shouldn't
    leave stale rows around; Approved records/children are untouched
    since they're already finalized) and recomputes from its current
    entries. Returns the new day-level records' ids."""
    stale_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM overtime_records WHERE timesheet_id=? AND status IN ('Pending','Rejected')",
        (timesheet["id"],)
    ).fetchall()]
    if stale_ids:
        placeholders = ",".join("?" * len(stale_ids))
        conn.execute(f"DELETE FROM overtime_project_approvals WHERE overtime_record_id IN ({placeholders})", stale_ids)
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

        conn.execute(
            """
            INSERT INTO overtime_records
            (institution_id,employee_id,timesheet_id,work_date,shift_id,threshold_hours,logged_hours,
             overtime_hours,status,conversion_mode)
            VALUES (?,?,?,?,?,?,?,?,'Pending',?)
            """,
            (inst_id, emp["employee_id"], timesheet["id"], work_date, shift["id"], threshold_hours, logged_hours,
             overtime_hours, conversion_mode)
        )
        record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        created_ids.append(record_id)

        day_project_hours = conn.execute(
            "SELECT project_id, SUM(hours) AS hours FROM timesheet_entries WHERE timesheet_id=? AND date=? GROUP BY project_id",
            (timesheet["id"], work_date)
        ).fetchall()
        _create_overtime_project_approvals(
            conn, inst_id, record_id, emp["employee_id"], work_date,
            conversion_mode, overtime_hours, logged_hours, day_project_hours
        )

    conn.commit()
    return created_ids


def _create_overtime_project_approvals(conn, inst_id: int, overtime_record_id: int, employee_id: str,
                                       work_date: str, conversion_mode: str, overtime_hours: float,
                                       logged_hours: float, day_project_hours) -> None:
    """Splits one day's overtime_hours across the projects logged that
    day, prorated by each project's share of the day's total hours — e.g.
    6h on Project A + 4h on Project B against an 8h threshold -> 2h
    overtime, split 1.2h/0.8h by share. The day's total isn't owned by
    one project any more than a timesheet's approval is, so this is the
    fairest simple default (see migrations/versions/20260917_0001 for the
    design discussion). Each share runs its own workflow instance,
    project_manager resolving against just that one project."""
    for row in day_project_hours:
        project_id = row["project_id"]
        share = float(row["hours"]) / logged_hours if logged_hours else 0.0
        project_overtime_hours = round(overtime_hours * share, 4)
        if project_overtime_hours <= 0:
            continue
        workflow_id, step_order, auto_approved = start_workflow(
            conn, inst_id, "overtime", employee_id, {project_id}
        )
        new_status = "Approved" if auto_approved else "Pending"
        conn.execute(
            """
            INSERT INTO overtime_project_approvals
            (institution_id,overtime_record_id,employee_id,project_id,work_date,overtime_hours,
             conversion_mode,status,approval_workflow_id,approval_step)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (inst_id, overtime_record_id, employee_id, project_id, work_date, project_overtime_hours,
             conversion_mode, new_status, workflow_id, step_order)
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if auto_approved:
            _finalize_overtime_project(conn, inst_id, conn.execute(
                "SELECT * FROM overtime_project_approvals WHERE id=?", (row_id,)
            ).fetchone(), "approved", "system")


def _finalize_overtime(conn, inst_id: int, record, outcome: str, approved_by: str) -> None:
    """LEGACY (pre-2026-09-17, whole-day) terminal outcome ('approved'/
    'rejected') for a single overtime_records row: credits leave or
    records a pay amount on approval, just updates status on rejection.
    Caller commits. Kept unchanged for records that predate the
    per-project split — see _finalize_overtime_project for new records."""
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


def _finalize_overtime_project(conn, inst_id: int, row, outcome: str, approved_by: str) -> None:
    """Applies the terminal outcome to one project's share of a day's
    overtime (overtime_project_approvals row) — same conversion math as
    _finalize_overtime, just scoped to this row's own prorated
    overtime_hours instead of the whole day's. The leave-day-equivalent
    conversion still needs the day's own threshold_hours (a per-project
    threshold has no meaning — the shift is the employee's for the whole
    day), so it's read from the parent overtime_records row."""
    final_status = "Approved" if outcome == "approved" else "Rejected"
    leave_days_credited, pay_amount = None, None

    if outcome == "approved":
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
            (row["employee_id"], inst_id)
        ).fetchone()
        overtime_hours = float(row["overtime_hours"])
        if row["conversion_mode"] == "leave":
            inst = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
            if inst and inst["overtime_leave_type_id"]:
                parent = conn.execute(
                    "SELECT threshold_hours FROM overtime_records WHERE id=?", (row["overtime_record_id"],)
                ).fetchone()
                threshold_hours = (float(parent["threshold_hours"]) if parent and parent["threshold_hours"] else 0.0) or 1.0
                leave_days_credited = round(overtime_hours / threshold_hours, 4)
                year = datetime.strptime(row["work_date"], "%Y-%m-%d").year
                bal = _get_or_create_leave_balance(conn, inst_id, row["employee_id"], inst["overtime_leave_type_id"], year)
                _credit_balance(conn, bal, leave_days_credited)
        else:
            rate = _hourly_rate_equivalent(emp) if emp else 0.0
            inst = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
            multiplier = float(inst["overtime_pay_multiplier"]) if inst else 1.5
            pay_amount = round(overtime_hours * rate * multiplier, 2)

    conn.execute(
        "UPDATE overtime_project_approvals SET status=?,approval_step=NULL,approved_by=?,approved_at=?,"
        "leave_days_credited=?,pay_amount=? WHERE id=?",
        (final_status, approved_by, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") if outcome == "approved" else None,
         leave_days_credited, pay_amount, row["id"])
    )


def apply_overtime_outcome(conn, inst_id: int, record, outcome: str, approved_by: str) -> None:
    """Public entry point for routers/overtime.py's LEGACY decide endpoint
    — thin wrapper so the 'advanced' (multi-step, not yet final) case is
    handled by the caller and only terminal outcomes reach here."""
    _finalize_overtime(conn, inst_id, record, outcome, approved_by)


def apply_overtime_project_outcome(conn, inst_id: int, row, outcome: str, approved_by: str) -> None:
    """Public entry point for routers/overtime.py's per-project decide
    endpoint — same 'advanced' contract as apply_overtime_outcome."""
    _finalize_overtime_project(conn, inst_id, row, outcome, approved_by)
