"""Timesheets (institution-scoped)."""
from typing import Optional

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
def list_timesheets(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
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
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/timesheets", status_code=201)
def start_timesheet(body: TimesheetStartIn, user: dict = Depends(get_current_user)):
    """Get-or-create the Draft timesheet for an employee's period (idempotent)."""
    inst_id = need_inst(user)
    if user["role"] == "employee" and user.get("employee_id") != body.employee_id:
        raise HTTPException(403, "You can only manage your own timesheet")
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM timesheets WHERE employee_id=? AND period_start=? AND period_end=? AND institution_id=?",
        (body.employee_id, body.period_start, body.period_end, inst_id)
    ).fetchone()
    if existing:
        conn.close()
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
    conn.close()
    return dict(row)


@router.get("/api/timesheets/{ts_id}")
def get_timesheet(ts_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    entries = conn.execute("""
        SELECT te.*, p.name AS project_name, t.name AS task_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN project_tasks t ON t.id = te.task_id
        WHERE te.timesheet_id=? ORDER BY te.date, p.name
    """, (ts_id,)).fetchall()
    conn.close()
    result = dict(ts)
    result["entries"] = [dict(e) for e in entries]
    result["total_hours"] = sum(e["hours"] for e in result["entries"])
    return result


@router.post("/api/timesheets/{ts_id}/entries", status_code=201)
def add_timesheet_entry(ts_id: int, body: TimesheetEntryIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    if ts["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    task = conn.execute(
        "SELECT id, open_to_all FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?",
        (body.task_id, body.project_id, inst_id)
    ).fetchone()
    if not task:
        conn.close(); raise HTTPException(400, "Selected task does not belong to this project")
    if not task["open_to_all"] and not conn.execute(
        "SELECT id FROM task_assignments WHERE task_id=? AND employee_id=? AND institution_id=?",
        (body.task_id, ts["employee_id"], inst_id)
    ).fetchone():
        conn.close(); raise HTTPException(403, "This employee is not assigned to the selected task")
    if body.hours <= 0 or body.hours > 24:
        conn.close(); raise HTTPException(400, "Hours must be between 0 and 24")
    if not (ts["period_start"] <= body.date <= ts["period_end"]):
        conn.close(); raise HTTPException(400, "Entry date must fall within the timesheet's period")

    conn.execute(
        "INSERT INTO timesheet_entries (institution_id,timesheet_id,project_id,task_id,date,hours,description) VALUES (?,?,?,?,?,?,?)",
        (inst_id, ts_id, body.project_id, body.task_id, body.date, body.hours, body.description)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM timesheet_entries WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/timesheets/{ts_id}/entries/{entry_id}", status_code=204)
def delete_timesheet_entry(ts_id: int, entry_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    if ts["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    conn.execute("DELETE FROM timesheet_entries WHERE id=? AND timesheet_id=?", (entry_id, ts_id))
    conn.commit(); conn.close()


@router.patch("/api/timesheets/{ts_id}/status")
def update_timesheet_status(ts_id: int, body: TimesheetStatusIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    valid = ("Submitted", "Approved", "Rejected")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    conn = get_db()
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        conn.close(); raise HTTPException(404, "Timesheet not found")

    if body.status == "Submitted":
        if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
            conn.close(); raise HTTPException(403, "Access denied")
        if ts["status"] != "Draft":
            conn.close(); raise HTTPException(400, f"Only a Draft timesheet can be submitted (current status: {ts['status']})")
        entry_count = conn.execute("SELECT COUNT(*) FROM timesheet_entries WHERE timesheet_id=?", (ts_id,)).fetchone()[0]
        if entry_count == 0:
            conn.close(); raise HTTPException(400, "Cannot submit an empty timesheet")
        conn.execute(
            "UPDATE timesheets SET status='Submitted',submitted_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
            (ts_id,)
        )
    else:  # Approved | Rejected
        can_approve = user["role"] in ("superadmin", "hr_manager", "hr_admin", "manager")
        if not can_approve:
            conn.close(); raise HTTPException(403, "Only a manager or HR can approve/reject timesheets")
        if ts["status"] != "Submitted":
            conn.close(); raise HTTPException(400, f"Only a Submitted timesheet can be reviewed (current status: {ts['status']})")
        conn.execute("UPDATE timesheets SET status=?,approved_by=?,notes=? WHERE id=?",
                     (body.status, user["username"], body.notes, ts_id))

    _log_timesheet(conn, inst_id, ts_id, ts["employee_id"], f"Status changed to {body.status}", body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    conn.close()
    return dict(row)
