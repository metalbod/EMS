"""Projects, Project Tasks, and Task Assignments (managed by HR Manager) — feeds Timesheet's project selector."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()

PROJECT_MANAGE_ROLES = ("superadmin", "hr_manager")


class ProjectIn(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "Active"  # Active | On Hold | Completed


class ProjectTaskIn(BaseModel):
    name: str
    description: Optional[str] = None
    estimated_hours: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "Not Started"  # Not Started | In Progress | Completed


class TaskAssignmentIn(BaseModel):
    employee_id: str
    start_datetime: str  # ISO datetime, e.g. 2026-07-08T09:00
    duration_hours: float  # expected effort for this member on this task


class TaskOpenToAllIn(BaseModel):
    open_to_all: bool


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@router.get("/api/projects")
@db_session
def list_projects(conn, status: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    q = """
        SELECT p.*,
            (SELECT COUNT(DISTINCT ta.employee_id) FROM task_assignments ta
                JOIN project_tasks t2 ON t2.id=ta.task_id WHERE t2.project_id=p.id) AS member_count,
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
    return [dict(r) for r in rows]


@router.get("/api/projects/utilization")
@db_session
def get_project_utilization(conn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    """Hours clocked by project, broken down by task, for all Active projects."""
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
        result.append({
            "id": p["id"], "name": p["name"], "status": p["status"],
            "total_hours": project_total, "tasks": task_list,
        })
    return result


@router.get("/api/projects/mine")
@db_session
def list_my_projects(conn, user: dict = Depends(get_current_user)):
    """Projects the current employee can log time against — used to populate the timesheet project selector."""
    inst_id = need_inst(user)
    if not user.get("employee_id"):
        return []
    rows = conn.execute("""
        SELECT DISTINCT p.* FROM projects p
        WHERE p.institution_id=? AND p.status='Active' AND (
            EXISTS (
                SELECT 1 FROM task_assignments ta JOIN project_tasks t ON t.id=ta.task_id
                WHERE t.project_id=p.id AND ta.employee_id=?
            )
            OR EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id=p.id AND t.open_to_all=1)
        )
        ORDER BY p.name
    """, (inst_id, user["employee_id"])).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/projects", status_code=201)
@db_session
def create_project(conn, body: ProjectIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn.execute(
        "INSERT INTO projects (institution_id,name,description,status,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.name, body.description, body.status, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/projects/{project_id}")
@db_session
def update_project(conn, project_id: int, body: ProjectIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        raise HTTPException(404, "Project not found")
    conn.execute(
        "UPDATE projects SET name=?,description=?,status=? WHERE id=?",
        (body.name, body.description, body.status, project_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row)


@router.delete("/api/projects/{project_id}", status_code=204)
@db_session
def delete_project(conn, project_id: int, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if conn.execute("SELECT id FROM timesheet_entries WHERE project_id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        raise HTTPException(400, "Cannot delete a project that already has logged timesheet hours — set it to Completed instead")
    conn.execute("DELETE FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Project Tasks
# ---------------------------------------------------------------------------
@router.get("/api/projects/{project_id}/tasks")
@db_session
def list_project_tasks(conn, project_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        raise HTTPException(404, "Project not found")
    # Project managers and anyone already assigned to a task in this project see every
    # task. An employee with no assignment here only sees tasks marked "ALL"
    # (open_to_all) — those are the only ones they're allowed to clock hours against,
    # so anything else is irrelevant to them.
    is_assigned = bool(user.get("employee_id")) and conn.execute("""
        SELECT ta.id FROM task_assignments ta JOIN project_tasks t ON t.id=ta.task_id
        WHERE t.project_id=? AND ta.employee_id=? AND ta.institution_id=?
    """, (project_id, user.get("employee_id"), inst_id)).fetchone()
    restrict_to_open = user["role"] not in PROJECT_MANAGE_ROLES and not is_assigned
    sql = """
        SELECT t.*, COALESCE(SUM(te.hours),0) AS logged_hours
        FROM project_tasks t
        LEFT JOIN timesheet_entries te ON te.task_id = t.id
        WHERE t.project_id=? AND t.institution_id=?
    """
    if restrict_to_open:
        sql += " AND t.open_to_all=1"
    sql += " GROUP BY t.id ORDER BY t.start_date NULLS LAST, t.created_at"
    rows = conn.execute(sql, (project_id, inst_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/projects/{project_id}/tasks", status_code=201)
@db_session
def create_project_task(conn, project_id: int, body: ProjectTaskIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone():
        raise HTTPException(404, "Project not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be on or after start date")
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
def update_project_task(conn, project_id: int, task_id: int, body: ProjectTaskIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        raise HTTPException(404, "Task not found")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    conn.execute(
        "UPDATE project_tasks SET name=?,description=?,estimated_hours=?,start_date=?,end_date=?,status=? WHERE id=?",
        (body.name, body.description, body.estimated_hours, body.start_date, body.end_date, body.status, task_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row)


@router.delete("/api/projects/{project_id}/tasks/{task_id}", status_code=204)
@db_session
def delete_project_task(conn, project_id: int, task_id: int, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if conn.execute("SELECT id FROM timesheet_entries WHERE task_id=? AND institution_id=?", (task_id, inst_id)).fetchone():
        raise HTTPException(400, "Cannot delete a task that already has logged timesheet hours — mark it Completed instead")
    # task_assignments has a foreign key to project_tasks, so it must be
    # deleted first — deleting project_tasks first violates that FK whenever
    # the task has any assignments.
    conn.execute("DELETE FROM task_assignments WHERE task_id=? AND institution_id=?", (task_id, inst_id))
    conn.execute("DELETE FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Task Assignments — per-team-member expected effort (start datetime + duration)
# on a task. Purely for capturing expected effort; actual timesheet hours
# logged against the task are NOT capped by this (see add_timesheet_entry).
# ---------------------------------------------------------------------------
@router.get("/api/projects/{project_id}/tasks/{task_id}/assignments")
@db_session
def list_task_assignments(conn, project_id: int, task_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        raise HTTPException(404, "Task not found")
    rows = conn.execute("""
        SELECT ta.*, e.full_name, e.department, e.designation
        FROM task_assignments ta
        JOIN employees e ON e.employee_id = ta.employee_id AND e.institution_id = ta.institution_id
        WHERE ta.task_id=? AND ta.institution_id=?
        ORDER BY ta.start_datetime
    """, (task_id, inst_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/projects/{project_id}/tasks/{task_id}/assignments", status_code=201)
@db_session
def add_task_assignment(conn, project_id: int, task_id: int, body: TaskAssignmentIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        raise HTTPException(404, "Task not found")
    if not conn.execute("SELECT id FROM employees WHERE employee_id=? AND institution_id=?", (body.employee_id, inst_id)).fetchone():
        raise HTTPException(404, "Employee not found")
    if body.duration_hours <= 0:
        raise HTTPException(400, "Duration must be greater than 0")
    try:
        conn.execute(
            "INSERT INTO task_assignments (institution_id,task_id,employee_id,start_datetime,duration_hours,assigned_by) VALUES (?,?,?,?,?,?)",
            (inst_id, task_id, body.employee_id, body.start_datetime, body.duration_hours, user["username"])
        )
        conn.commit()
    except IntegrityError:
        raise HTTPException(400, "Employee is already assigned to this task")
    row = conn.execute("SELECT * FROM task_assignments WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.delete("/api/projects/{project_id}/tasks/{task_id}/assignments/{employee_id}", status_code=204)
@db_session
def remove_task_assignment(conn, project_id: int, task_id: int, employee_id: str, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn.execute(
        "DELETE FROM task_assignments WHERE task_id=? AND employee_id=? AND institution_id=?",
        (task_id, employee_id, inst_id)
    )
    conn.commit()


@router.patch("/api/projects/{project_id}/tasks/{task_id}/open-to-all")
@db_session
def set_task_open_to_all(conn, project_id: int, task_id: int, body: TaskOpenToAllIn, user: dict = Depends(require_roles(*PROJECT_MANAGE_ROLES))):
    """Marking a task 'ALL' lets every employee in the institution clock hours to it,
    bypassing the usual project-membership requirement (see add_timesheet_entry)."""
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (task_id, project_id, inst_id)).fetchone():
        raise HTTPException(404, "Task not found")
    conn.execute("UPDATE project_tasks SET open_to_all=? WHERE id=?", (1 if body.open_to_all else 0, task_id))
    conn.commit()
    row = conn.execute("SELECT * FROM project_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row)
