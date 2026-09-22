"""Projects and Project Tasks (managed by HR Manager) — feeds Timesheet's project selector."""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst

from db import get_db

from core.db_session import db_session

from core.permission_matrix import require_permission

router = APIRouter()

PROJECT_MANAGE_ROLES = ("superadmin", "hr_manager")


class ProjectIn(BaseModel):
    name: str
    description: Optional[str] = None
    customer: Optional[str] = None  # free text, optional — tagged for reporting/filtering, no dedicated customers table
    status: str = "Active"  # Active | On Hold | Completed
    start_date: Optional[str] = None  # informational only — not checked against timesheet entries
    end_date: Optional[str] = None
    manager_ids: List[str] = []  # employee_ids — a project can have multiple managers
    member_ids: List[str] = []  # employee_ids — who can log time against this project
    is_open_to_all: bool = False  # any employee can log time here, no membership needed
    is_billable: bool = False  # for project-cost calculations (built separately, later)


class ProjectTaskIn(BaseModel):
    name: str
    description: Optional[str] = None
    estimated_hours: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "Not Started"  # Not Started | In Progress | Completed


_DUPLICATE_SCOPES = ("tasks_and_members", "tasks_only", "members_only")


class ProjectDuplicateIn(BaseModel):
    name: str
    duplicate_scope: str  # "tasks_and_members" | "tasks_only" | "members_only"

    @field_validator("duplicate_scope")
    @classmethod
    def _validate_scope(cls, v):
        if v not in _DUPLICATE_SCOPES:
            raise ValueError(f"duplicate_scope must be one of: {', '.join(_DUPLICATE_SCOPES)}")
        return v


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def _manager_ids_for(conn, project_id: int) -> List[str]:
    rows = conn.execute(
        "SELECT employee_id FROM project_managers WHERE project_id=? ORDER BY employee_id", (project_id,)
    ).fetchall()
    return [r["employee_id"] for r in rows]


def _set_project_managers(conn, inst_id: int, project_id: int, manager_ids: List[str]) -> None:
    ids = sorted(set(manager_ids))
    if ids:
        placeholders = ",".join("?" * len(ids))
        found = conn.execute(
            f"SELECT employee_id FROM employees WHERE institution_id=? AND employee_id IN ({placeholders})",
            (inst_id, *ids)
        ).fetchall()
        missing = set(ids) - {r["employee_id"] for r in found}
        if missing:
            raise HTTPException(404, f"Employee(s) not found: {', '.join(sorted(missing))}")
    conn.execute("DELETE FROM project_managers WHERE project_id=?", (project_id,))
    for emp_id in ids:
        conn.execute(
            "INSERT INTO project_managers (project_id,employee_id) VALUES (?,?)", (project_id, emp_id)
        )


def _member_ids_for(conn, project_id: int) -> List[str]:
    rows = conn.execute(
        "SELECT employee_id FROM project_members WHERE project_id=? ORDER BY employee_id", (project_id,)
    ).fetchall()
    return [r["employee_id"] for r in rows]


def _set_project_members(conn, inst_id: int, project_id: int, member_ids: List[str]) -> None:
    """Team members are assigned at the project level (not per task) — this
    is the roster that governs who can log timesheet hours against the
    project (see routers/timesheets.py's add_timesheet_entry)."""
    ids = sorted(set(member_ids))
    if ids:
        placeholders = ",".join("?" * len(ids))
        found = conn.execute(
            f"SELECT employee_id FROM employees WHERE institution_id=? AND employee_id IN ({placeholders})",
            (inst_id, *ids)
        ).fetchall()
        missing = set(ids) - {r["employee_id"] for r in found}
        if missing:
            raise HTTPException(404, f"Employee(s) not found: {', '.join(sorted(missing))}")
    conn.execute("DELETE FROM project_members WHERE project_id=?", (project_id,))
    for emp_id in ids:
        conn.execute(
            "INSERT INTO project_members (project_id,employee_id) VALUES (?,?)", (project_id, emp_id)
        )


@router.get("/api/projects")
@db_session
def list_projects(conn, status: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = """
        SELECT p.*,
            (SELECT COUNT(*) FROM project_members pm WHERE pm.project_id=p.id) AS member_count,
            (SELECT COUNT(*) FROM project_tasks t WHERE t.project_id=p.id) AS task_count,
            (SELECT COALESCE(SUM(t.estimated_hours),0) FROM project_tasks t WHERE t.project_id=p.id) AS total_allocated_hours,
            (SELECT COALESCE(SUM(te.hours),0) FROM timesheet_entries te WHERE te.project_id=p.id) AS total_logged_hours
        FROM projects p
        WHERE p.institution_id=?
    """
    params: list = [inst_id]
    if status: q += " AND p.status=?"; params.append(status)
    q += " GROUP BY p.id ORDER BY p.created_at DESC"
    rows = conn.execute(q, params).fetchall()
    out = [dict(r) for r in rows]
    for p in out:
        p["manager_ids"] = _manager_ids_for(conn, p["id"])
        p["member_ids"] = _member_ids_for(conn, p["id"])
    return out


@router.get("/api/projects/utilization")
@db_session
def get_project_utilization(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Hours clocked by project, broken down by task, for all Active projects."""
    require_permission(conn, user, "projects_tasks.utilization_report")
    inst_id = need_inst(user)
    projects = conn.execute(
        "SELECT * FROM projects WHERE institution_id=? AND status='Active' ORDER BY name", (inst_id,)
    ).fetchall()
    result = []
    for p in projects:
        tasks = conn.execute("""
            SELECT t.id, t.name, t.estimated_hours, t.status,
                   COALESCE(SUM(te.hours),0) AS logged_hours
            FROM project_tasks t
            LEFT JOIN timesheet_entries te ON te.task_id = t.id
            WHERE t.project_id=? AND t.institution_id=?
            GROUP BY t.id ORDER BY t.start_date NULLS LAST, t.created_at
        """, (p["id"], inst_id)).fetchall()
        task_list = [dict(t) for t in tasks]
        project_total = sum(t["logged_hours"] for t in task_list)
        # Only tasks that actually have an estimate contribute to the
        # project-level denominator — a task with no estimate can't say
        # anything about whether the project as a whole is on track, so it's
        # left out rather than silently counted as a 0-hour budget.
        estimated_task_hours = [t["estimated_hours"] for t in task_list if t["estimated_hours"]]
        project_total_estimated = sum(estimated_task_hours) if estimated_task_hours else None
        result.append({
            "id": p["id"], "name": p["name"], "status": p["status"],
            "total_hours": project_total, "total_estimated_hours": project_total_estimated, "tasks": task_list,
        })
    return result


def _month_str(d: date) -> str:
    return d.strftime("%Y-%m")


def _shift_month(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)


@router.get("/api/projects/monthly-summary")
@db_session
def get_project_monthly_summary(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Billable-project hours for the current and previous calendar month
    (grouped on timesheet_entries.date, the per-entry day field — not
    timesheets.period_start, which is the parent week's bounds), each
    project sorted by total hours logged and carrying its own top
    resources (people, ranked by hours on that project that month) plus a
    month-over-month trend against the prior month. Also a company-wide
    billable/non-billable hours split per month. Powers the Home
    dashboard's Timesheet tab (static/js/dashboard.js's loadTimesheetDash)."""
    require_permission(conn, user, "projects_tasks.utilization_report")
    inst_id = need_inst(user)

    today = date.today().replace(day=1)
    months = {"current": today, "last": _shift_month(today, -1), "before_last": _shift_month(today, -2)}
    month_keys = {k: _month_str(v) for k, v in months.items()}

    def _billable_split(month_key: str) -> Dict[str, float]:
        row = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN p.is_billable THEN te.hours ELSE 0 END),0) AS billable_hours,
                COALESCE(SUM(CASE WHEN NOT p.is_billable THEN te.hours ELSE 0 END),0) AS non_billable_hours
            FROM timesheet_entries te
            JOIN projects p ON p.id = te.project_id
            WHERE te.institution_id=? AND SUBSTR(te.date,1,7)=?
        """, (inst_id, month_key)).fetchone()
        return {"billable_hours": row["billable_hours"], "non_billable_hours": row["non_billable_hours"]}

    def _project_totals(month_key: str) -> Dict[int, float]:
        rows = conn.execute("""
            SELECT te.project_id, COALESCE(SUM(te.hours),0) AS total_hours
            FROM timesheet_entries te
            JOIN projects p ON p.id = te.project_id
            WHERE te.institution_id=? AND p.is_billable=true AND SUBSTR(te.date,1,7)=?
            GROUP BY te.project_id
        """, (inst_id, month_key)).fetchall()
        return {r["project_id"]: r["total_hours"] for r in rows}

    def _top_resources(project_id: int, month_key: str, limit: int = 5) -> List[Dict[str, Any]]:
        rows = conn.execute("""
            SELECT t.employee_id, e.full_name, e.preferred_name, COALESCE(SUM(te.hours),0) AS hours
            FROM timesheet_entries te
            JOIN timesheets t ON t.id = te.timesheet_id
            LEFT JOIN employees e ON e.employee_id = t.employee_id AND e.institution_id = te.institution_id
            WHERE te.institution_id=? AND te.project_id=? AND SUBSTR(te.date,1,7)=?
            GROUP BY t.employee_id, e.full_name, e.preferred_name
            ORDER BY hours DESC
            LIMIT ?
        """, (inst_id, project_id, month_key, limit)).fetchall()
        return [dict(r) for r in rows]

    totals = {k: _project_totals(month_keys[k]) for k in months}
    project_ids = set(totals["current"]) | set(totals["last"])
    proj_rows: Dict[int, Dict[str, Any]] = {}
    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        rows = conn.execute(
            f"SELECT id, name, (SELECT COUNT(*) FROM project_members pm WHERE pm.project_id=projects.id) AS member_count "
            f"FROM projects WHERE institution_id=? AND id IN ({placeholders})",
            [inst_id, *project_ids]
        ).fetchall()
        proj_rows = {r["id"]: dict(r) for r in rows}

    def _month_payload(key: str, baseline_key: str) -> Dict[str, Any]:
        month_totals = totals[key]
        baseline_totals = totals[baseline_key]
        projects_out = []
        for pid, hours in month_totals.items():
            if pid not in proj_rows:
                continue
            prev = baseline_totals.get(pid, 0)
            trend_pct = round((hours - prev) / prev * 100, 1) if prev else None
            projects_out.append({
                "project_id": pid, "name": proj_rows[pid]["name"], "member_count": proj_rows[pid]["member_count"],
                "total_hours": hours, "trend_pct": trend_pct,
                "top_resources": _top_resources(pid, month_keys[key]),
            })
        projects_out.sort(key=lambda p: p["total_hours"], reverse=True)
        return {"label": months[key].strftime("%B %Y"), "projects": projects_out, **_billable_split(month_keys[key])}

    return {
        "current_month": _month_payload("current", "last"),
        "last_month": _month_payload("last", "before_last"),
    }


@router.get("/api/projects/mine")
@db_session
def list_my_projects(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Projects the current employee can log time against — used to populate the timesheet project selector."""
    inst_id = need_inst(user)
    if not user.get("employee_id"):
        return []
    rows = conn.execute("""
        SELECT DISTINCT p.* FROM projects p
        WHERE p.institution_id=? AND p.status='Active' AND (
            p.is_open_to_all
            OR EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id=p.id AND pm.employee_id=?)
        )
        ORDER BY p.name
    """, (inst_id, user["employee_id"])).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/projects", status_code=201)
@db_session
def create_project(conn, body: ProjectIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    conn.execute(
        "INSERT INTO projects (institution_id,name,description,customer,status,start_date,end_date,is_open_to_all,is_billable,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (inst_id, body.name, body.description, body.customer, body.status, body.start_date, body.end_date,
         body.is_open_to_all, body.is_billable, user["username"])
    )
    project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    _set_project_managers(conn, inst_id, project_id, body.manager_ids)
    _set_project_members(conn, inst_id, project_id, body.member_ids)
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    d = dict(row)
    d["manager_ids"] = _manager_ids_for(conn, project_id)
    d["member_ids"] = _member_ids_for(conn, project_id)
    return d


@router.put("/api/projects/{project_id}")
@db_session
def update_project(conn, project_id: int, body: ProjectIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        raise HTTPException(404, "Project not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    conn.execute(
        "UPDATE projects SET name=?,description=?,customer=?,status=?,start_date=?,end_date=?,is_open_to_all=?,is_billable=? WHERE id=?",
        (body.name, body.description, body.customer, body.status, body.start_date, body.end_date,
         body.is_open_to_all, body.is_billable, project_id)
    )
    _set_project_managers(conn, inst_id, project_id, body.manager_ids)
    _set_project_members(conn, inst_id, project_id, body.member_ids)
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    d = dict(row)
    d["manager_ids"] = _manager_ids_for(conn, project_id)
    d["member_ids"] = _member_ids_for(conn, project_id)
    return d


@router.delete("/api/projects/{project_id}", status_code=204)
@db_session
def delete_project(conn, project_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    if conn.execute("SELECT id FROM timesheet_entries WHERE project_id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        raise HTTPException(400, "Cannot delete a project that already has logged timesheet hours — set it to Completed instead")
    # project_managers/project_members have a foreign key to projects, so
    # they must be deleted first.
    conn.execute("DELETE FROM project_managers WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM project_members WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id))
    conn.commit()


@router.post("/api/projects/{project_id}/duplicate", status_code=201)
@db_session
def duplicate_project(conn, project_id: int, body: ProjectDuplicateIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Clones a project under a new name — a "fresh start" clone, not a
    byte-for-byte one: the new project always starts Active regardless of
    the source's status, and copied tasks reset to Not Started with no
    dates (status/dates are execution-specific, not template data worth
    preserving). Description, customer, is_open_to_all and is_billable
    always carry over unconditionally — duplicate_scope only controls
    tasks/managers/members, per the 3 options offered in the UI. Managers
    and Team Members travel together as one "Members" unit."""
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    source = conn.execute("SELECT * FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone()
    if not source:
        raise HTTPException(404, "Project not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Project name is required")

    include_tasks = body.duplicate_scope in ("tasks_and_members", "tasks_only")
    include_members = body.duplicate_scope in ("tasks_and_members", "members_only")

    conn.execute(
        "INSERT INTO projects (institution_id,name,description,customer,status,is_open_to_all,is_billable,created_by) VALUES (?,?,?,?,?,?,?,?)",
        (inst_id, name, source["description"], source["customer"], "Active", source["is_open_to_all"], source["is_billable"], user["username"])
    )
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    if include_members:
        _set_project_managers(conn, inst_id, new_id, _manager_ids_for(conn, project_id))
        _set_project_members(conn, inst_id, new_id, _member_ids_for(conn, project_id))

    if include_tasks:
        tasks = conn.execute(
            "SELECT * FROM project_tasks WHERE project_id=? AND institution_id=?", (project_id, inst_id)
        ).fetchall()
        for t in tasks:
            conn.execute(
                "INSERT INTO project_tasks (institution_id,project_id,name,description,estimated_hours,start_date,end_date,status,created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (inst_id, new_id, t["name"], t["description"], t["estimated_hours"], None, None, "Not Started", user["username"])
            )

    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (new_id,)).fetchone()
    d = dict(row)
    d["manager_ids"] = _manager_ids_for(conn, new_id)
    d["member_ids"] = _member_ids_for(conn, new_id)
    return d


# ---------------------------------------------------------------------------
# Project Tasks
# ---------------------------------------------------------------------------
def _check_task_dates_within_project(project, body: ProjectTaskIn) -> None:
    """Each task date is checked independently against the matching project
    date, inclusive of the boundary — a task can start/end exactly on the
    project's own start/end date. Only runs where both sides of a
    comparison are actually set; the project's dates are informational-only
    otherwise and impose no constraint."""
    if project["start_date"] and body.start_date and body.start_date < project["start_date"]:
        raise HTTPException(400, "Task start date cannot be before the project's start date")
    if project["end_date"] and body.end_date and body.end_date > project["end_date"]:
        raise HTTPException(400, "Task end date cannot be after the project's end date")


@router.get("/api/projects/{project_id}/tasks")
@db_session
def list_project_tasks(conn, project_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    project = conn.execute("SELECT * FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    # Project managers and any project member see every task. An employee
    # who is neither only sees tasks at all if the whole project is marked
    # open-to-all — team membership (and the open-to-all escape hatch) now
    # lives at the project level, not per task (see add_timesheet_entry).
    is_member = bool(user.get("employee_id")) and conn.execute(
        "SELECT id FROM project_members WHERE project_id=? AND employee_id=?",
        (project_id, user.get("employee_id"))
    ).fetchone()
    if user["role"] not in PROJECT_MANAGE_ROLES and not is_member and not project["is_open_to_all"]:
        return []
    sql = """
        SELECT t.*, COALESCE(SUM(te.hours),0) AS logged_hours
        FROM project_tasks t
        LEFT JOIN timesheet_entries te ON te.task_id = t.id
        WHERE t.project_id=? AND t.institution_id=?
        GROUP BY t.id ORDER BY t.start_date NULLS LAST, t.created_at
    """
    rows = conn.execute(sql, (project_id, inst_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/projects/{project_id}/tasks", status_code=201)
@db_session
def create_project_task(conn, project_id: int, body: ProjectTaskIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    project = conn.execute("SELECT * FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    _check_task_dates_within_project(project, body)
    conn.execute(
        "INSERT INTO project_tasks (institution_id,project_id,name,description,estimated_hours,start_date,end_date,status,created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (inst_id, project_id, body.name, body.description, body.estimated_hours,
         body.start_date, body.end_date, body.status, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/projects/{project_id}/tasks/{task_id}")
@db_session
def update_project_task(conn, project_id: int, task_id: int, body: ProjectTaskIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        raise HTTPException(404, "Task not found")
    project = conn.execute("SELECT * FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone()
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    _check_task_dates_within_project(project, body)
    conn.execute(
        "UPDATE project_tasks SET name=?,description=?,estimated_hours=?,start_date=?,end_date=?,status=? WHERE id=?",
        (body.name, body.description, body.estimated_hours, body.start_date, body.end_date, body.status, task_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row)


@router.delete("/api/projects/{project_id}/tasks/{task_id}", status_code=204)
@db_session
def delete_project_task(conn, project_id: int, task_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "projects_tasks.manage_projects_tasks_assignments")
    inst_id = need_inst(user)
    if conn.execute("SELECT id FROM timesheet_entries WHERE task_id=? AND institution_id=?", (task_id, inst_id)).fetchone():
        raise HTTPException(400, "Cannot delete a task that already has logged timesheet hours — mark it Completed instead")
    conn.execute("DELETE FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id))
    conn.commit()
