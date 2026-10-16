"""Claude self-service: log today's hours and see the week's hours (the MCP server's timesheet tools).

Deliberately small, purpose-built endpoints rather than opening the general timesheet ones to a Claude token: core/oauth.py's
allow-list matches exact paths, these always act on the caller's own record, and everything is saved to the week's *Draft*
timesheet. Nothing here submits a timesheet - submitting starts approvals and overtime detection, so it stays in the web app.
They also work for a normal login (they're just the caller's own data), which keeps them easy to test.

Weeks are Monday-Sunday in the company's own timezone, like My Timesheet. "Missing hours" is My Timesheet's own figure
(routers/timesheets.py's _weekly_hours_breakdown: expected hours minus logged hours, public holidays and approved leave).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db_session import db_session
from core.deps import get_current_user, need_inst
from core.institution_time import institution_today
from routers.timesheets import (
    TimesheetEntryIn, _check_timesheet_entry_editable, _log_timesheet, _weekly_hours_breakdown,
    get_or_create_timesheet, validate_new_timesheet_entry,
)

router = APIRouter()


def _employee(user: dict) -> str:
    if not user.get("employee_id"):
        raise HTTPException(400, "No employee record is linked to this account")
    return user["employee_id"]


def _week_of(d: date):
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(400, "Dates must look like 2026-10-14")


def _people(conn, inst_id: int, table: str, project_id: int) -> List[Dict[str, Any]]:
    """Active employees in project_managers / project_members (table is one of those two, never user input)."""
    rows = conn.execute(
        f"SELECT e.full_name, e.preferred_name, e.designation, e.department FROM {table} x "
        "JOIN employees e ON e.employee_id = x.employee_id AND e.institution_id = ? "
        "WHERE x.project_id=? AND e.status='Active' ORDER BY e.full_name", (inst_id, project_id)).fetchall()
    return [{"name": r["preferred_name"] or r["full_name"], "full_name": r["full_name"],
             "designation": r["designation"], "department": r["department"]} for r in rows]


@router.get("/api/me/timesheet/projects", tags=["timesheet"])
@db_session
def my_timesheet_projects(conn, search: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Active projects the caller can log time against (open to all, or they're a member), each with its tasks, project managers and
    team members. Names only for the people (no contact details). EMS already shows every employee each project's managers and
    members (GET /api/projects), so this exposes nothing new; tasks have no individual assignee in EMS, only the project team.
    `search` narrows by project name (case-insensitive contains)."""
    inst_id = need_inst(user)
    emp = _employee(user)
    projects = conn.execute("""
        SELECT DISTINCT p.id, p.name, p.status, p.description, p.customer, p.start_date, p.end_date, p.is_open_to_all FROM projects p
        WHERE p.institution_id=? AND p.status='Active' AND (
            p.is_open_to_all OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.employee_id=?))
        ORDER BY p.name""", (inst_id, emp)).fetchall()
    if search and search.strip():
        projects = [p for p in projects if search.strip().lower() in (p["name"] or "").lower()]
    out = []
    for p in projects:
        tasks = conn.execute("SELECT id, name, status, estimated_hours, start_date, end_date FROM project_tasks "
                             "WHERE project_id=? AND institution_id=? ORDER BY start_date NULLS LAST, created_at",
                             (p["id"], inst_id)).fetchall()
        is_manager = bool(conn.execute("SELECT 1 FROM project_managers WHERE project_id=? AND employee_id=?", (p["id"], emp)).fetchone())
        is_member = bool(conn.execute("SELECT 1 FROM project_members WHERE project_id=? AND employee_id=?", (p["id"], emp)).fetchone())
        out.append({
            "project_id": p["id"], "project_name": p["name"], "status": p["status"], "customer": p["customer"],
            "description": (p["description"] or None) and p["description"][:500],
            "start_date": p["start_date"], "end_date": p["end_date"],
            "open_to_all": bool(p["is_open_to_all"]), "you_are_manager": is_manager, "you_are_member": is_member,
            "managers": _people(conn, inst_id, "project_managers", p["id"]),
            "members": _people(conn, inst_id, "project_members", p["id"]),
            "tasks": [{"task_id": t["id"], "task_name": t["name"], "status": t["status"], "estimated_hours": t["estimated_hours"],
                       "start_date": t["start_date"], "end_date": t["end_date"]} for t in tasks]})
    return out


class LogHoursIn(BaseModel):
    project_id: int
    task_id: int
    hours: float
    date: Optional[str] = None      # default: today in the company's timezone


@router.post("/api/me/timesheet/log-hours", status_code=201, tags=["timesheet"])
@db_session
def log_my_hours(conn, body: LogHoursIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Add hours for one project task on one day of the current week to the caller's Draft timesheet. If that task already
    has hours that day, the new hours are added to them."""
    inst_id = need_inst(user)
    emp = _employee(user)
    today = _parse_date(institution_today(conn, inst_id))
    day = _parse_date(body.date) if body.date else today
    monday, sunday = _week_of(today)
    if not (monday <= day <= sunday):
        raise HTTPException(400, f"Hours can only be logged for this week ({monday.isoformat()} to {sunday.isoformat()}).")
    if day > today:
        raise HTTPException(400, "You can't log hours for a future day.")
    hours = round(body.hours, 2)
    if hours <= 0 or hours > 24:
        raise HTTPException(400, "Hours must be between 0 and 24")

    ts = get_or_create_timesheet(conn, inst_id, emp, monday.isoformat(), sunday.isoformat(), user)
    ds = day.isoformat()
    day_total = conn.execute("SELECT COALESCE(SUM(hours),0) h FROM timesheet_entries WHERE timesheet_id=? AND date=?",
                             (ts["id"], ds)).fetchone()["h"]
    if day_total + hours > 24:
        raise HTTPException(400, f"That would make {round(day_total + hours, 2)} hours on {ds}; a day can't have more than 24.")

    existing = conn.execute("SELECT * FROM timesheet_entries WHERE timesheet_id=? AND project_id=? AND task_id=? AND date=?",
                            (ts["id"], body.project_id, body.task_id, ds)).fetchone()
    if existing:
        _check_timesheet_entry_editable(conn, ts, body.project_id)
        task_hours = round(existing["hours"] + hours, 2)
        conn.execute("UPDATE timesheet_entries SET hours=? WHERE id=?", (task_hours, existing["id"]))
        entry_id = existing["id"]
    else:
        validate_new_timesheet_entry(conn, inst_id, ts, TimesheetEntryIn(project_id=body.project_id, task_id=body.task_id, date=ds, hours=hours))
        conn.execute("INSERT INTO timesheet_entries (institution_id,timesheet_id,project_id,task_id,date,hours) VALUES (?,?,?,?,?,?)",
                     (inst_id, ts["id"], body.project_id, body.task_id, ds, hours))
        entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        task_hours = hours
    names = conn.execute("SELECT p.name AS project_name, t.name AS task_name FROM projects p, project_tasks t WHERE p.id=? AND t.id=?",
                         (body.project_id, body.task_id)).fetchone()
    how = "Claude" if user.get("oauth_scopes") else "API"
    _log_timesheet(conn, inst_id, ts["id"], emp, "Hours logged",
                   f"{hours}h on {names['project_name']} / {names['task_name']} for {ds} (via {how}); task total that day {task_hours}h", user)
    conn.commit()
    week_total = conn.execute("SELECT COALESCE(SUM(te.hours),0) h FROM timesheet_entries te JOIN timesheets t ON t.id=te.timesheet_id "
                              "WHERE t.institution_id=? AND t.employee_id=? AND te.date BETWEEN ? AND ?",
                              (inst_id, emp, monday.isoformat(), sunday.isoformat())).fetchone()["h"]
    return {"entry_id": entry_id, "date": ds, "project_name": names["project_name"], "task_name": names["task_name"],
            "hours_added": hours, "task_hours_that_day": task_hours, "day_total_hours": round(day_total + hours, 2),
            "week_logged_hours": round(week_total, 2), "timesheet_status": ts["status"], "added_to_existing": bool(existing)}


def _timesheet_status(conn, inst_id: int, emp: str, start: str, end: str) -> str:
    sheets = conn.execute("SELECT id, status FROM timesheets WHERE institution_id=? AND employee_id=? AND period_start<=? AND period_end>=?",
                          (inst_id, emp, end, start)).fetchall()
    if not sheets:
        return "Not started"
    states = set()
    for t in sheets:
        per_project = conn.execute("SELECT status FROM timesheet_project_approvals WHERE timesheet_id=?", (t["id"],)).fetchall()
        states.update([r["status"] for r in per_project] or [t["status"]])
    for s in ("Rejected", "Draft", "Submitted", "Approved"):     # the state that needs the person's attention first
        if s in states:
            return s if len(states) == 1 else f"Mixed ({', '.join(sorted(states))})"
    return ", ".join(sorted(states))


@router.get("/api/me/week-hours", tags=["timesheet"])
@db_session
def my_week_hours(conn, date: Optional[str] = None, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Hours clocked (attendance) and logged (timesheet) for the Monday-Sunday week containing `date` (default today), plus My
    Timesheet's expected / holiday / leave / missing figures."""
    inst_id = need_inst(user)
    emp = _employee(user)
    day = _parse_date(date) if date else _parse_date(institution_today(conn, inst_id))
    monday, sunday = _week_of(day)
    start, end = monday.isoformat(), sunday.isoformat()

    clocked: Dict[str, float] = {}
    in_progress = None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in conn.execute("SELECT work_date, clock_in_at, clock_out_at, worked_minutes FROM attendance_records "
                          "WHERE institution_id=? AND employee_id=? AND work_date BETWEEN ? AND ?", (inst_id, emp, start, end)).fetchall():
        minutes = r["worked_minutes"] or 0
        if r["clock_in_at"] and not r["clock_out_at"]:
            minutes = max(0, int((now - datetime.fromisoformat(r["clock_in_at"])).total_seconds() // 60))
            in_progress = {"since_utc": r["clock_in_at"], "work_date": r["work_date"]}
        clocked[r["work_date"]] = clocked.get(r["work_date"], 0) + minutes / 60.0
    logged: Dict[str, float] = {}
    for r in conn.execute("SELECT te.date, SUM(te.hours) h FROM timesheet_entries te JOIN timesheets t ON t.id=te.timesheet_id "
                          "WHERE t.institution_id=? AND t.employee_id=? AND te.date BETWEEN ? AND ? GROUP BY te.date",
                          (inst_id, emp, start, end)).fetchall():
        logged[r["date"]] = float(r["h"])
    total_logged = round(sum(logged.values()), 2)
    breakdown = _weekly_hours_breakdown(conn, inst_id, emp, start, end, total_logged)
    credited: Dict[str, List[str]] = {}
    for a in breakdown["auto_entries"]:
        credited.setdefault(a["date"], []).append(f"{a['label']} ({a['hours']}h)")
    days = []
    for i in range(7):
        ds = (monday + timedelta(days=i)).isoformat()
        days.append({"date": ds, "weekday": (monday + timedelta(days=i)).strftime("%a"),
                     "clocked_hours": round(clocked.get(ds, 0.0), 2), "logged_hours": round(logged.get(ds, 0.0), 2),
                     "credited": credited.get(ds, [])})
    return {"week_start": start, "week_end": end, "days": days,
            "clocked_hours": round(sum(clocked.values()), 2), "clocked_in_now": in_progress,
            "logged_hours": total_logged, "holiday_hours": breakdown["holiday_hours"], "leave_hours": breakdown["leave_hours"],
            "expected_hours": breakdown["expected_hours"], "missing_hours": breakdown["missing_hours"],
            "timesheet_status": _timesheet_status(conn, inst_id, emp, start, end)}
