"""Timesheets (institution-scoped)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import get_current_user, need_inst
except ImportError:
    from ems.core.deps import get_current_user, need_inst

try:
    from core.org_queries import subordinates_in_clause
except ImportError:
    from ems.core.org_queries import subordinates_in_clause

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()


class TimesheetEntryIn(BaseModel):
    project_id: int
    task_id: int
    date: str  # YYYY-MM-DD
    hours: float
    description: Optional[str] = None


class TimesheetStartIn(BaseModel):
    employee_id: str
    period_start: str
    period_end: str


class TimesheetStatusIn(BaseModel):
    status: str  # Submitted | Approved | Rejected
    notes: Optional[str] = None


def _log_timesheet(conn, inst_id: int, ts_id: int, emp_id: str,
                    action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO timesheet_audit_log
           (institution_id,timesheet_id,employee_id,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?)""",
        (inst_id, ts_id, emp_id, action, detail, user["username"], user["role"])
    )


@router.get("/api/timesheets")
@db_session
def list_timesheets(conn, status: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = """
        SELECT t.*, e.full_name AS employee_name, e.department, e.designation,
               COALESCE(SUM(te.hours),0) AS total_hours
        FROM timesheets t
        JOIN employees e ON e.employee_id = t.employee_id AND e.institution_id = t.institution_id
        LEFT JOIN timesheet_entries te ON te.timesheet_id = t.id
        WHERE t.institution_id=?
    """
    params: list = [inst_id]
    if status: q += " AND t.status=?"; params.append(status)
    if user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; params.extend(fp)
    elif user["role"] == "employee":
        q += " AND t.employee_id=?"; params.append(user.get("employee_id", ""))
    q += " GROUP BY t.id, e.full_name, e.department, e.designation ORDER BY t.period_start DESC"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/timesheets", status_code=201)
@db_session
def start_timesheet(conn, body: TimesheetStartIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Get-or-create the Draft timesheet for an employee's period (idempotent)."""
    inst_id = need_inst(user)
    if user["role"] == "employee" and user.get("employee_id") != body.employee_id:
        raise HTTPException(403, "You can only manage your own timesheet")
    existing = conn.execute(
        "SELECT * FROM timesheets WHERE employee_id=? AND period_start=? AND period_end=? AND institution_id=?",
        (body.employee_id, body.period_start, body.period_end, inst_id)
    ).fetchone()
    if existing:
        return dict(existing)
    conn.execute(
        "INSERT INTO timesheets (institution_id,employee_id,period_start,period_end) VALUES (?,?,?,?)",
        (inst_id, body.employee_id, body.period_start, body.period_end)
    )
    ts_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _log_timesheet(conn, inst_id, ts_id, body.employee_id, "Created",
                    f"Timesheet created for {body.period_start} to {body.period_end}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    return dict(row)


@router.get("/api/timesheets/{ts_id}")
@db_session
def get_timesheet(conn, ts_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        raise HTTPException(403, "Access denied")
    entries = conn.execute("""
        SELECT te.*, p.name AS project_name, t.name AS task_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN project_tasks t ON t.id = te.task_id
        WHERE te.timesheet_id=? ORDER BY te.date, p.name
    """, (ts_id,)).fetchall()
    result = dict(ts)
    result["entries"] = [dict(e) for e in entries]
    result["total_hours"] = sum(e["hours"] for e in result["entries"])
    return result


@router.post("/api/timesheets/{ts_id}/entries", status_code=201)
@db_session
def add_timesheet_entry(conn, ts_id: int, body: TimesheetEntryIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        raise HTTPException(403, "Access denied")
    if ts["status"] != "Draft":
        raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    task = conn.execute(
        "SELECT id, open_to_all FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?",
        (body.task_id, body.project_id, inst_id)
    ).fetchone()
    if not task:
        raise HTTPException(400, "Selected task does not belong to this project")
    if not task["open_to_all"] and not conn.execute(
        "SELECT id FROM task_assignments WHERE task_id=? AND employee_id=? AND institution_id=?",
        (body.task_id, ts["employee_id"], inst_id)
    ).fetchone():
        raise HTTPException(403, "This employee is not assigned to the selected task")
    if body.hours <= 0 or body.hours > 24:
        raise HTTPException(400, "Hours must be between 0 and 24")
    if not (ts["period_start"] <= body.date <= ts["period_end"]):
        raise HTTPException(400, "Entry date must fall within the timesheet's period")

    conn.execute(
        "INSERT INTO timesheet_entries (institution_id,timesheet_id,project_id,task_id,date,hours,description) VALUES (?,?,?,?,?,?,?)",
        (inst_id, ts_id, body.project_id, body.task_id, body.date, body.hours, body.description)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM timesheet_entries WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.delete("/api/timesheets/{ts_id}/entries/{entry_id}", status_code=204)
@db_session
def delete_timesheet_entry(conn, ts_id: int, entry_id: int, user: dict = Depends(get_current_user)) -> None:
    inst_id = need_inst(user)
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        raise HTTPException(403, "Access denied")
    if ts["status"] != "Draft":
        raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    conn.execute("DELETE FROM timesheet_entries WHERE id=? AND timesheet_id=?", (entry_id, ts_id))
    conn.commit()


@router.patch("/api/timesheets/{ts_id}/status")
@db_session
def update_timesheet_status(conn, ts_id: int, body: TimesheetStatusIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    valid = ("Submitted", "Approved", "Rejected")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        raise HTTPException(404, "Timesheet not found")

    if body.status == "Submitted":
        if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
            raise HTTPException(403, "Access denied")
        if ts["status"] != "Draft":
            raise HTTPException(400, f"Only a Draft timesheet can be submitted (current status: {ts['status']})")
        entry_count = conn.execute("SELECT COUNT(*) FROM timesheet_entries WHERE timesheet_id=?", (ts_id,)).fetchone()[0]
        if entry_count == 0:
            raise HTTPException(400, "Cannot submit an empty timesheet")
        conn.execute(
            "UPDATE timesheets SET status='Submitted',submitted_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
            (ts_id,)
        )
    else:  # Approved | Rejected
        can_approve = user["role"] in ("superadmin", "hr_manager", "hr_admin", "manager")
        if not can_approve:
            raise HTTPException(403, "Only a manager or HR can approve/reject timesheets")
        if ts["status"] != "Submitted":
            raise HTTPException(400, f"Only a Submitted timesheet can be reviewed (current status: {ts['status']})")
        conn.execute("UPDATE timesheets SET status=?,approved_by=?,notes=? WHERE id=?",
                     (body.status, user["username"], body.notes, ts_id))

    _log_timesheet(conn, inst_id, ts_id, ts["employee_id"], f"Status changed to {body.status}", body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    return dict(row)
