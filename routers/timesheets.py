"""Timesheets (institution-scoped)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst

from core.org_queries import subordinates_in_clause

from core.approval_workflow import start_workflow, advance_or_finalize, project_ids_for_row, annotate_actionability

from core.overtime import generate_overtime_records

from db import get_db

from core.db_session import db_session

router = APIRouter()


class TimesheetEntryIn(BaseModel):
    project_id: int
    task_id: int
    date: str  # YYYY-MM-DD
    hours: float
    description: Optional[str] = None  # legacy per-entry field — the weekly grid no longer sets this, see TimesheetDescriptionIn


class TimesheetEntryHoursIn(BaseModel):
    hours: float  # a cell's identity (project/task/date) doesn't change on edit — move it by deleting and re-creating in a different row/column instead


class TimesheetDescriptionIn(BaseModel):
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


def _check_timesheet_entry_editable(conn, ts, project_id: int) -> None:
    """Whether an entry for `project_id` on this timesheet can currently be
    added/deleted. A timesheet with no timesheet_project_approvals rows at
    all is either genuinely Draft (fine) or a LEGACY pre-2026-09-17
    timesheet that was never split per-project — for those, fall back to
    the old whole-record gate exactly as before. Once at least one
    per-project row exists (this timesheet has been through Submit at
    least once under the new model), the gate becomes per-project: a
    project still Submitted/Approved is locked, a Rejected one has
    reopened for just that project, and a project with no row at all yet
    (never submitted) is open like Draft."""
    has_split = conn.execute(
        "SELECT 1 FROM timesheet_project_approvals WHERE timesheet_id=? LIMIT 1", (ts["id"],)
    ).fetchone()
    if not has_split:
        if ts["status"] != "Draft":
            raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
        return
    row = conn.execute(
        "SELECT status FROM timesheet_project_approvals WHERE timesheet_id=? AND project_id=?",
        (ts["id"], project_id)
    ).fetchone()
    if row and row["status"] != "Rejected":
        raise HTTPException(400, f"This project's hours are already {row['status']} — cannot edit")


def _reconcile_timesheet_project_approvals(conn, inst_id: int, ts) -> None:
    """Called on Submit (including a resubmit after a partial rejection):
    for every distinct project currently logged on this timesheet, ensures
    a timesheet_project_approvals row exists and is actively running its
    own workflow instance. A project with no row yet (first submission, or
    a project added after other projects were already decided) gets one
    started; a Rejected row gets reset and restarted (the employee has
    presumably fixed that project's hours); a Submitted or Approved row is
    left completely untouched — this call must never disturb a decision
    that's already been made or is already in flight on another project."""
    project_ids = [r["project_id"] for r in conn.execute(
        "SELECT DISTINCT project_id FROM timesheet_entries WHERE timesheet_id=?", (ts["id"],)
    ).fetchall()]
    for project_id in project_ids:
        existing = conn.execute(
            "SELECT * FROM timesheet_project_approvals WHERE timesheet_id=? AND project_id=?",
            (ts["id"], project_id)
        ).fetchone()
        if existing and existing["status"] != "Rejected":
            continue
        workflow_id, step_order, auto_approved = start_workflow(
            conn, inst_id, "timesheet", ts["employee_id"], {project_id}
        )
        new_status = "Approved" if auto_approved else "Submitted"
        if existing:
            conn.execute(
                "UPDATE timesheet_project_approvals SET status=?,approval_workflow_id=?,approval_step=?,"
                "approved_by=NULL,approved_at=NULL,notes=NULL WHERE id=?",
                (new_status, workflow_id, step_order, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO timesheet_project_approvals "
                "(institution_id,timesheet_id,employee_id,project_id,period_start,period_end,"
                "status,approval_workflow_id,approval_step) VALUES (?,?,?,?,?,?,?,?,?)",
                (inst_id, ts["id"], ts["employee_id"], project_id, ts["period_start"], ts["period_end"],
                 new_status, workflow_id, step_order)
            )


# list_timesheets sorts/paginates in Python (see _expand_timesheet_rows)
# rather than in SQL, since a timesheet's row count isn't knowable until
# its per-project split is checked — this is the key the frontend's
# sort_by picks, not a raw SQL column.
_TIMESHEET_SORT_KEYS = {
    "employee_name": lambda r: (r.get("employee_name") or "").lower(),
    "period_start": lambda r: r["period_start"],
    "total_hours": lambda r: r["total_hours"],
    "status": lambda r: r["status"],
    "project": lambda r: (r.get("project_names") or "").lower(),
}


def _expand_timesheet_rows(conn, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One timesheet -> one row per project it's been split into (see
    timesheet_project_approvals, added 2026-09-17), each carrying that
    project's OWN status/approval_workflow_id/approval_step (so
    annotate_actionability below judges actionability per project, not
    per timesheet) — or, for a timesheet never split (legacy, pre-split,
    or simply never submitted), a single row using its own whole-record
    status and every project it touches as one comma-separated string.
    `row["id"]` always stays the parent timesheet's id either way (the
    Timesheet Detail modal opens by timesheet id, not by this table's own
    child-row id); a split row additionally carries `project_id` for the
    per-project approve/reject endpoint and `project_approval_id` (the
    child row's own id) for anything that needs to identify that specific
    approval instance, e.g. flat-mode decision tracking — see
    core/approval_workflow.py's _request_identity_for_row."""
    ts_ids = [c["id"] for c in candidates]
    if not ts_ids:
        return []
    placeholders = ",".join("?" * len(ts_ids))
    project_rows = conn.execute(
        f"""SELECT tpa.*, p.name AS project_name FROM timesheet_project_approvals tpa
            JOIN projects p ON p.id = tpa.project_id
            WHERE tpa.timesheet_id IN ({placeholders}) ORDER BY p.name""",
        ts_ids
    ).fetchall()
    by_ts: Dict[int, List[Dict[str, Any]]] = {}
    for pr in project_rows:
        by_ts.setdefault(pr["timesheet_id"], []).append(dict(pr))

    hours_rows = conn.execute(
        f"""SELECT timesheet_id, project_id, SUM(hours) AS hours FROM timesheet_entries
            WHERE timesheet_id IN ({placeholders}) GROUP BY timesheet_id, project_id""",
        ts_ids
    ).fetchall()
    hours_by = {(h["timesheet_id"], h["project_id"]): float(h["hours"]) for h in hours_rows}

    legacy_names_rows = conn.execute(
        f"""SELECT te.timesheet_id, STRING_AGG(DISTINCT p.name, ', ' ORDER BY p.name) AS names
            FROM timesheet_entries te JOIN projects p ON p.id = te.project_id
            WHERE te.timesheet_id IN ({placeholders}) GROUP BY te.timesheet_id""",
        ts_ids
    ).fetchall()
    legacy_names = {r["timesheet_id"]: r["names"] for r in legacy_names_rows}

    out = []
    for t in candidates:
        splits = by_ts.get(t["id"])
        if not splits:
            row = dict(t)
            row["total_hours"] = sum(v for (tid, _pid), v in hours_by.items() if tid == t["id"])
            row["project_names"] = legacy_names.get(t["id"])
            row["project_id"] = None
            out.append(row)
            continue
        for pr in splits:
            row = dict(t)
            row["project_approval_id"] = pr["id"]  # the child row's own id — see PATCH .../projects/{project_id}/status
            row["project_id"] = pr["project_id"]
            row["project_names"] = pr["project_name"]
            row["status"] = pr["status"]
            row["approval_workflow_id"] = pr["approval_workflow_id"]
            row["approval_step"] = pr["approval_step"]
            row["approved_by"] = pr["approved_by"]
            row["approved_at"] = pr["approved_at"]
            row["notes"] = pr["notes"]
            row["total_hours"] = hours_by.get((t["id"], pr["project_id"]), 0.0)
            out.append(row)
    return out


@router.get("/api/timesheets")
@db_session
def list_timesheets(
    conn, response: Response,
    status: Optional[str] = None, employee_id: Optional[str] = None,
    period_from: Optional[str] = None, period_to: Optional[str] = None,
    project_id: Optional[int] = None,
    sort_by: str = "period_start", sort_dir: str = "desc",
    limit: int = 50, offset: int = 0,
    user: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    where = "t.institution_id=?"
    params: list = [inst_id]
    if employee_id: where += " AND t.employee_id=?"; params.append(employee_id)
    # Matches on the period's start date — a period is always a fixed 7-day
    # week (see static/js/timesheet.js's tsGetMonday), so "period starting
    # within this range" is the intuitive reading of a "period" filter (e.g.
    # picking a month's date range surfaces every week that starts in it).
    if period_from: where += " AND t.period_start>=?"; params.append(period_from)
    if period_to: where += " AND t.period_start<=?"; params.append(period_to)
    if user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        where += f" AND e.employee_id IN {frag}"; params.extend(fp)
    elif user["role"] == "employee":
        where += " AND t.employee_id=?"; params.append(user.get("employee_id", ""))

    # status/project_id filter AFTER expansion below, not here — see
    # _expand_timesheet_rows: a split (new-style) timesheet's own t.status
    # stays a vestigial "Submitted" forever once split, so filtering has
    # to look at each expanded row's own effective status/project, not
    # the parent timesheet's.
    candidates = conn.execute(
        f"""SELECT t.*, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name,
                   e.department, e.designation
            FROM timesheets t
            JOIN employees e ON e.employee_id = t.employee_id AND e.institution_id = t.institution_id
            WHERE {where}""",
        params
    ).fetchall()
    expanded = _expand_timesheet_rows(conn, [dict(c) for c in candidates])

    if status:
        expanded = [r for r in expanded if r["status"] == status]
    if project_id:
        expanded = [r for r in expanded if r.get("project_id") == project_id]

    key_fn = _TIMESHEET_SORT_KEYS.get(sort_by, _TIMESHEET_SORT_KEYS["period_start"])
    expanded.sort(key=key_fn, reverse=(str(sort_dir).lower() != "asc"))

    response.headers["X-Total-Count"] = str(len(expanded))
    page = expanded[offset:offset + limit]
    if user["role"] != "employee":
        page = annotate_actionability(conn, inst_id, "timesheet", page, user)
    return page


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


TIMESHEET_SETTINGS_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")


class TimesheetSettingsIn(BaseModel):
    standard_weekly_hours: float

    @field_validator("standard_weekly_hours")
    @classmethod
    def _positive_and_reasonable(cls, v):
        if not (0 < v <= 168):  # 168 = every hour of every day of the week
            raise ValueError("standard_weekly_hours must be greater than 0 and at most 168")
        return v


class TimesheetSettingsOut(TimesheetSettingsIn):
    pass


@router.get("/api/timesheets/settings")
@db_session
def get_timesheet_settings(conn, user: dict = Depends(get_current_user)) -> TimesheetSettingsOut:
    """Institution-wide "Missing hours" baseline (My Timesheet) — see
    _weekly_hours_breakdown below. Settings -> Attendance page, next to
    Shifts/Rules (a related work-time policy, not its own nav item for
    one field)."""
    if user["role"] not in TIMESHEET_SETTINGS_MANAGE_ROLES:
        raise HTTPException(403, "Not authorized")
    inst_id = need_inst(user)
    row = conn.execute("SELECT standard_weekly_hours FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return TimesheetSettingsOut(standard_weekly_hours=float(row["standard_weekly_hours"]))


@router.put("/api/timesheets/settings")
@db_session
def update_timesheet_settings(conn, body: TimesheetSettingsIn, user: dict = Depends(get_current_user)) -> TimesheetSettingsOut:
    if user["role"] not in TIMESHEET_SETTINGS_MANAGE_ROLES:
        raise HTTPException(403, "Not authorized")
    inst_id = need_inst(user)
    conn.execute("UPDATE institutions SET standard_weekly_hours=? WHERE id=?", (body.standard_weekly_hours, inst_id))
    conn.commit()
    return TimesheetSettingsOut(standard_weekly_hours=body.standard_weekly_hours)


def _weekly_hours_breakdown(conn, inst_id: int, employee_id: str, period_start: str, period_end: str, total_hours: float) -> Dict[str, Any]:
    """Powers My Timesheet's "Missing hours" line and its auto-populated
    public-holiday/approved-leave rows. Mon-Fri are the only days counted
    as "expected" (matches routers/leave.py's _compute_leave_days, which
    treats weekends the same way for leave-balance purposes) — a
    standard_weekly_hours of 40 means 8h/working day. Generalizes to any
    period length, not just a 7-day week, so it stays correct for a
    monthly/custom-range timesheet too (e.g. institutions.
    standard_weekly_hours=40 over a full month works out to roughly
    core/overtime.py's own MONTHLY_NORMAL_HOURS=176 approximation — same
    8h x ~22 working-day reasoning, arrived at independently here).

    A day that's both a public holiday and inside an approved leave range
    is credited once, as a holiday — never double-counted."""
    inst = conn.execute("SELECT standard_weekly_hours FROM institutions WHERE id=?", (inst_id,)).fetchone()
    weekly_hours = float(inst["standard_weekly_hours"]) if inst and inst["standard_weekly_hours"] is not None else 40.0
    daily_rate = weekly_hours / 5.0

    d0 = datetime.strptime(period_start, "%Y-%m-%d").date()
    d1 = datetime.strptime(period_end, "%Y-%m-%d").date()

    holiday_rows = conn.execute(
        "SELECT date, name FROM holidays WHERE institution_id=? AND date BETWEEN ? AND ?",
        (inst_id, period_start, period_end)
    ).fetchall()
    holiday_by_date = {r["date"]: r["name"] for r in holiday_rows}

    leave_apps = conn.execute("""
        SELECT la.start_date, la.end_date, la.start_day_period, la.end_day_period, lt.name AS leave_type_name
        FROM leave_applications la
        JOIN leave_types lt ON lt.id = la.leave_type_id
        WHERE la.institution_id=? AND la.employee_id=? AND la.status='Approved'
          AND la.start_date<=? AND la.end_date>=?
    """, (inst_id, employee_id, period_end, period_start)).fetchall()

    working_days = 0
    holiday_hours = 0.0
    leave_hours = 0.0
    auto_entries = []
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            working_days += 1
            ds = d.isoformat()
            if ds in holiday_by_date:
                holiday_hours += daily_rate
                auto_entries.append({"date": ds, "type": "holiday", "label": holiday_by_date[ds], "hours": round(daily_rate, 2)})
            else:
                for app in leave_apps:
                    if app["start_date"] <= ds <= app["end_date"]:
                        fraction = 1.0
                        if ds == app["start_date"] and app["start_day_period"]:
                            fraction = 0.5
                        elif ds == app["end_date"] and app["end_date"] != app["start_date"] and app["end_day_period"]:
                            fraction = 0.5
                        hrs = round(daily_rate * fraction, 2)
                        leave_hours += hrs
                        label = app["leave_type_name"] + (" (Half day)" if fraction == 0.5 else "")
                        auto_entries.append({"date": ds, "type": "leave", "label": label, "hours": hrs})
                        break  # first matching approved application wins this date
        d += timedelta(days=1)

    expected_hours = round(working_days * daily_rate, 2)
    accounted_hours = round(total_hours + holiday_hours + leave_hours, 2)
    return {
        "expected_hours": expected_hours,
        "holiday_hours": round(holiday_hours, 2),
        "leave_hours": round(leave_hours, 2),
        "accounted_hours": accounted_hours,
        "missing_hours": max(0.0, round(expected_hours - accounted_hours, 2)),
        "auto_entries": auto_entries,
    }


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
    # Per-project approval rows, if this timesheet has been split (see
    # timesheet_project_approvals) — empty for a Draft timesheet or a
    # legacy pre-split one, in which case the caller falls back to this
    # timesheet's own whole-record status/approved_by/notes.
    project_approvals = conn.execute("""
        SELECT tpa.*, p.name AS project_name,
               COALESCE(SUM(te.hours),0) AS total_hours
        FROM timesheet_project_approvals tpa
        JOIN projects p ON p.id = tpa.project_id
        LEFT JOIN timesheet_entries te ON te.timesheet_id = tpa.timesheet_id AND te.project_id = tpa.project_id
        WHERE tpa.timesheet_id=?
        GROUP BY tpa.id, p.name
        ORDER BY p.name
    """, (ts_id,)).fetchall()
    result = dict(ts)
    result["entries"] = [dict(e) for e in entries]
    result["total_hours"] = sum(e["hours"] for e in result["entries"])
    result.update(_weekly_hours_breakdown(conn, inst_id, ts["employee_id"], ts["period_start"], ts["period_end"], result["total_hours"]))
    approvals = [dict(r) for r in project_approvals]
    if user["role"] != "employee":
        approvals = annotate_actionability(conn, inst_id, "timesheet", approvals, user)
    result["project_approvals"] = approvals
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
    _check_timesheet_entry_editable(conn, ts, body.project_id)
    task = conn.execute(
        "SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?",
        (body.task_id, body.project_id, inst_id)
    ).fetchone()
    if not task:
        raise HTTPException(400, "Selected task does not belong to this project")
    # Team membership (and its "open to all" escape hatch) lives at the
    # project level, not per task — anyone on the project's member list
    # can log time against any of its tasks (see routers/projects.py's
    # list_project_tasks for the same project-level gate).
    project = conn.execute(
        "SELECT is_open_to_all FROM projects WHERE id=? AND institution_id=?",
        (body.project_id, inst_id)
    ).fetchone()
    if not project["is_open_to_all"] and not conn.execute(
        "SELECT id FROM project_members WHERE project_id=? AND employee_id=?",
        (body.project_id, ts["employee_id"])
    ).fetchone():
        raise HTTPException(403, "This employee is not a member of the selected project")
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


@router.put("/api/timesheets/{ts_id}/entries/{entry_id}")
@db_session
def update_timesheet_entry_hours(conn, ts_id: int, entry_id: int, body: TimesheetEntryHoursIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Edits an already-saved cell's hours in place — the weekly grid's
    "Save Week" batch calls this for any cell whose value changed from
    what was loaded, POST /entries for a newly-filled cell, and DELETE
    for one cleared back to empty (see static/js/timesheet.js)."""
    inst_id = need_inst(user)
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        raise HTTPException(403, "Access denied")
    entry = conn.execute("SELECT * FROM timesheet_entries WHERE id=? AND timesheet_id=?", (entry_id, ts_id)).fetchone()
    if not entry:
        raise HTTPException(404, "Entry not found")
    _check_timesheet_entry_editable(conn, ts, entry["project_id"])
    if body.hours <= 0 or body.hours > 24:
        raise HTTPException(400, "Hours must be between 0 and 24")
    conn.execute("UPDATE timesheet_entries SET hours=? WHERE id=? AND timesheet_id=?", (body.hours, entry_id, ts_id))
    conn.commit()
    row = conn.execute("SELECT * FROM timesheet_entries WHERE id=?", (entry_id,)).fetchone()
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
    entry = conn.execute("SELECT * FROM timesheet_entries WHERE id=? AND timesheet_id=?", (entry_id, ts_id)).fetchone()
    if not entry:
        raise HTTPException(404, "Entry not found")
    _check_timesheet_entry_editable(conn, ts, entry["project_id"])
    conn.execute("DELETE FROM timesheet_entries WHERE id=? AND timesheet_id=?", (entry_id, ts_id))
    conn.commit()


@router.put("/api/timesheets/{ts_id}/description")
@db_session
def update_timesheet_description(conn, ts_id: int, body: TimesheetDescriptionIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """One free-text description for the whole week (not per entry — see
    migrations/versions/20260924_0001_add_timesheet_weekly_description.py).
    Self-service only, same ownership rule as every other timesheet
    action; editable whenever at least one project on this timesheet
    still is (has_split-aware, same as _check_timesheet_entry_editable,
    but not tied to any one project since this field isn't either)."""
    inst_id = need_inst(user)
    ts = conn.execute("SELECT * FROM timesheets WHERE id=? AND institution_id=?", (ts_id, inst_id)).fetchone()
    if not ts:
        raise HTTPException(404, "Timesheet not found")
    if user["role"] == "employee" and user.get("employee_id") != ts["employee_id"]:
        raise HTTPException(403, "Access denied")
    project_ids_on_ts = [r["project_id"] for r in conn.execute(
        "SELECT DISTINCT project_id FROM timesheet_entries WHERE timesheet_id=?", (ts_id,)
    ).fetchall()]
    if not project_ids_on_ts:
        # A fresh, empty timesheet — nothing to be locked by yet.
        if ts["status"] != "Draft":
            raise HTTPException(400, f"Cannot edit a {ts['status']} timesheet")
    else:
        # Reuses _check_timesheet_entry_editable's own per-project rule
        # (rather than re-deriving it here) — scoped to the projects
        # actually logged on THIS timesheet, not every project the
        # employee happens to be eligible for institution-wide (an
        # open-to-all project untouched by this week's timesheet says
        # nothing about whether this week is still open to edit).
        still_open = False
        for pid in project_ids_on_ts:
            try:
                _check_timesheet_entry_editable(conn, ts, pid)
                still_open = True
                break
            except HTTPException:
                continue
        if not still_open:
            raise HTTPException(400, "This timesheet has no open projects left to edit")
    conn.execute("UPDATE timesheets SET description=? WHERE id=?", (body.description, ts_id))
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    return dict(row)


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
        # A Submitted timesheet with per-project rows already (new-style)
        # can be resubmitted — that's how a rejected or newly-added
        # project's hours get (re)started; see
        # _reconcile_timesheet_project_approvals, which is a no-op for any
        # project already Submitted/Approved. A Submitted timesheet with
        # NO per-project rows is a legacy, pre-split one still on its
        # single whole-record workflow instance — not resubmittable here,
        # same restriction as before this feature existed.
        has_split = ts["status"] != "Draft" and conn.execute(
            "SELECT 1 FROM timesheet_project_approvals WHERE timesheet_id=? LIMIT 1", (ts_id,)
        ).fetchone()
        if ts["status"] != "Draft" and not has_split:
            raise HTTPException(400, f"Only a Draft timesheet can be submitted (current status: {ts['status']})")
        entry_count = conn.execute("SELECT COUNT(*) FROM timesheet_entries WHERE timesheet_id=?", (ts_id,)).fetchone()[0]
        if entry_count == 0:
            raise HTTPException(400, "Cannot submit an empty timesheet")
        if ts["status"] == "Draft":
            conn.execute(
                "UPDATE timesheets SET status='Submitted',"
                "submitted_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
                (ts_id,)
            )
        _reconcile_timesheet_project_approvals(conn, inst_id, ts)
        generate_overtime_records(conn, inst_id, ts)
    else:  # Approved | Rejected — legacy whole-timesheet review only. A
           # timesheet with per-project rows must be decided project by
           # project via PATCH /api/timesheets/{id}/projects/{project_id}/status
           # instead — approving/rejecting it as one unit here would apply
           # to every project at once, exactly the blanket behavior this
           # feature was built to stop.
        if conn.execute("SELECT 1 FROM timesheet_project_approvals WHERE timesheet_id=? LIMIT 1", (ts_id,)).fetchone():
            raise HTTPException(400, "This timesheet's projects must be approved/rejected individually")
        if ts["status"] != "Submitted":
            raise HTTPException(400, f"Only a Submitted timesheet can be reviewed (current status: {ts['status']})")
        action = "reject" if body.status == "Rejected" else "approve"
        if ts["approval_workflow_id"] and ts["approval_step"] is not None:
            try:
                project_ids = project_ids_for_row(conn, "timesheet", ts)
                outcome, next_step = advance_or_finalize(
                    conn, inst_id, "timesheet", ts["employee_id"],
                    ts["approval_workflow_id"], ts["approval_step"], action, user,
                    "timesheets", ts_id, project_ids
                )
            except PermissionError as e:
                raise HTTPException(403, str(e))
        else:
            if user["role"] not in ("superadmin", "hr_manager", "hr_admin", "manager"):
                raise HTTPException(403, "Only a manager or HR can approve/reject timesheets")
            outcome, next_step = ("rejected" if action == "reject" else "approved"), None

        if outcome == "advanced":
            conn.execute("UPDATE timesheets SET approval_step=?,notes=? WHERE id=?", (next_step, body.notes, ts_id))
            _log_timesheet(conn, inst_id, ts_id, ts["employee_id"], "Approval Advanced",
                           f"Step {ts['approval_step']} cleared by {user['username']} — now awaiting step {next_step}", user)
            conn.commit()
            return dict(conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone())

        final_status = "Approved" if outcome == "approved" else "Rejected"
        conn.execute("UPDATE timesheets SET status=?,approved_by=?,notes=?,approval_step=NULL WHERE id=?",
                     (final_status, user["username"], body.notes, ts_id))

    _log_timesheet(conn, inst_id, ts_id, ts["employee_id"], f"Status changed to {body.status}", body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM timesheets WHERE id=?", (ts_id,)).fetchone()
    return dict(row)


@router.patch("/api/timesheets/{ts_id}/projects/{project_id}/status")
@db_session
def update_timesheet_project_status(conn, ts_id: int, project_id: int, body: TimesheetStatusIn,
                                    user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Approve/reject one project's slice of a timesheet, independently of
    its other projects — see migrations/versions/20260917_0001_... for why
    this exists alongside (not instead of) the whole-timesheet PATCH
    .../status above, which stays as the legacy path for pre-split rows."""
    inst_id = need_inst(user)
    valid = ("Approved", "Rejected")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    row = conn.execute(
        "SELECT * FROM timesheet_project_approvals WHERE timesheet_id=? AND project_id=? AND institution_id=?",
        (ts_id, project_id, inst_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "This project has no approval record on this timesheet")
    if row["status"] != "Submitted":
        raise HTTPException(400, f"This project's hours are already {row['status']}")

    action = "reject" if body.status == "Rejected" else "approve"
    project_ids = project_ids_for_row(conn, "timesheet", row)
    try:
        outcome, next_step = advance_or_finalize(
            conn, inst_id, "timesheet", row["employee_id"],
            row["approval_workflow_id"], row["approval_step"], action, user,
            "timesheet_project_approvals", row["id"], project_ids
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))

    if outcome == "advanced":
        conn.execute("UPDATE timesheet_project_approvals SET approval_step=?,notes=? WHERE id=?",
                     (next_step, body.notes, row["id"]))
        _log_timesheet(conn, inst_id, ts_id, row["employee_id"], "Approval Advanced",
                       f"Project #{project_id}: step {row['approval_step']} cleared by {user['username']} — now awaiting step {next_step}", user)
        conn.commit()
        return dict(conn.execute("SELECT * FROM timesheet_project_approvals WHERE id=?", (row["id"],)).fetchone())

    final_status = "Approved" if outcome == "approved" else "Rejected"
    approved_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") if final_status == "Approved" else None
    conn.execute(
        "UPDATE timesheet_project_approvals SET status=?,approved_by=?,approved_at=?,notes=?,approval_step=NULL WHERE id=?",
        (final_status, user["username"], approved_at, body.notes, row["id"])
    )
    _log_timesheet(conn, inst_id, ts_id, row["employee_id"], f"Project status changed to {final_status}",
                   body.notes or "", user)
    conn.commit()
    return dict(conn.execute("SELECT * FROM timesheet_project_approvals WHERE id=?", (row["id"],)).fetchone())
