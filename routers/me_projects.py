"""Claude self-service: a project's own managers add, edit and delete its tasks (the MCP server's project-task tools).

The rule is narrower here than in the EMS web app on purpose. In the web app, anyone holding the 'Manage projects, tasks,
assignments' permission (HR Manager) OR listed as a manager of the project may change tasks (routers/projects.py's
require_task_manage). Through Claude only the latter: you must be listed as a manager of THAT project. An HR Manager who isn't
one of the project's managers uses the web screen. Writes go through the same create/update/delete functions as the web screen
(date rules, "can't delete a task with logged hours", audit trail), recorded "via Claude".

Paths carry no ids (core/oauth.py's allow-list matches exact paths), so the ids travel in the body.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db_session import db_session
from core.deps import get_current_user, need_inst
from routers.projects import (
    TASK_STATUSES, ProjectTaskIn, create_task_record, delete_task_record, is_project_manager_of, update_task_record,
)

router = APIRouter()
VIA = "Claude"


def _employee(user: dict) -> str:
    if not user.get("employee_id"):
        raise HTTPException(400, "No employee record is linked to this account")
    return user["employee_id"]


def _my_project(conn, user: dict, project_id: int):
    """The project, if the caller is one of its managers; otherwise the same 403 whether it exists or not."""
    inst_id = need_inst(user)
    if not is_project_manager_of(conn, inst_id, _employee(user), project_id):
        raise HTTPException(403, "Only a project's own managers can change its tasks through Claude.")
    return conn.execute("SELECT * FROM projects WHERE id=? AND institution_id=?", (project_id, inst_id)).fetchone()


def _date(value: Optional[str], label: str) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, f"{label} must look like 2026-11-30")
    return value


def _clean(name: Optional[str], description: Optional[str], hours: Optional[float], status: Optional[str]):
    name = (name or "").strip()
    if not name or len(name) > 200:
        raise HTTPException(400, "A task needs a name of up to 200 characters.")
    if hours is not None and not (0 <= hours <= 10000):
        raise HTTPException(400, "Estimated hours must be between 0 and 10000.")
    if status not in TASK_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(TASK_STATUSES)}.")
    description = (description or "").strip()[:2000] or None
    return name, description, (hours or None), status


def _no_duplicate(conn, project_id: int, name: str, except_task_id: Optional[int] = None) -> None:
    for r in conn.execute("SELECT id, name FROM project_tasks WHERE project_id=?", (project_id,)).fetchall():
        if r["id"] != except_task_id and (r["name"] or "").strip().lower() == name.lower():
            raise HTTPException(400, f"This project already has a task called '{r['name']}'.")


@router.get("/api/me/managed-projects", tags=["projects"])
@db_session
def my_managed_projects(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Projects the caller is a listed manager of, with every task (and the hours already logged on it, which decides whether a task
    can be deleted). Includes projects that are On Hold or Completed."""
    inst_id = need_inst(user)
    emp = _employee(user)
    projects = conn.execute(
        "SELECT p.id, p.name, p.status, p.start_date, p.end_date FROM projects p JOIN project_managers pm ON pm.project_id = p.id "
        "WHERE p.institution_id=? AND pm.employee_id=? ORDER BY p.name", (inst_id, emp)).fetchall()
    out = []
    for p in projects:
        tasks = conn.execute(
            "SELECT t.id, t.name, t.description, t.estimated_hours, t.start_date, t.end_date, t.status, COALESCE(SUM(te.hours),0) AS logged_hours "
            "FROM project_tasks t LEFT JOIN timesheet_entries te ON te.task_id = t.id WHERE t.project_id=? AND t.institution_id=? "
            "GROUP BY t.id ORDER BY t.start_date NULLS LAST, t.created_at", (p["id"], inst_id)).fetchall()
        out.append({"project_id": p["id"], "project_name": p["name"], "status": p["status"], "start_date": p["start_date"], "end_date": p["end_date"],
                    "tasks": [{"task_id": t["id"], "task_name": t["name"], "description": t["description"], "status": t["status"],
                               "estimated_hours": t["estimated_hours"], "start_date": t["start_date"], "end_date": t["end_date"],
                               "logged_hours": round(float(t["logged_hours"]), 2), "can_delete": float(t["logged_hours"]) == 0} for t in tasks]})
    return out


class TaskAddIn(BaseModel):
    project_id: int
    name: str
    description: Optional[str] = None
    estimated_hours: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "Not Started"


@router.post("/api/me/project-tasks/add", status_code=201, tags=["projects"])
@db_session
def add_my_project_task(conn, body: TaskAddIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    project = _my_project(conn, user, body.project_id)
    name, description, hours, status = _clean(body.name, body.description, body.estimated_hours, body.status)
    _no_duplicate(conn, project["id"], name)
    task = create_task_record(conn, user, need_inst(user), project, ProjectTaskIn(
        name=name, description=description, estimated_hours=hours, start_date=_date(body.start_date, "Start date"),
        end_date=_date(body.end_date, "End date"), status=status), via=VIA)
    return {"task_id": task["id"], "task_name": task["name"], "project_id": project["id"], "project_name": project["name"],
            "status": task["status"], "estimated_hours": task["estimated_hours"], "start_date": task["start_date"], "end_date": task["end_date"]}


class TaskUpdateIn(BaseModel):
    project_id: int
    task_id: int
    name: Optional[str] = None
    description: Optional[str] = None
    estimated_hours: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None


@router.post("/api/me/project-tasks/update", tags=["projects"])
@db_session
def update_my_project_task(conn, body: TaskUpdateIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Partial update: only the fields that were sent change (send null to clear a description, hours or date)."""
    project = _my_project(conn, user, body.project_id)
    inst_id = need_inst(user)
    old = conn.execute("SELECT * FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (body.task_id, project["id"], inst_id)).fetchone()
    if not old:
        raise HTTPException(404, "Task not found")
    sent = body.model_fields_set - {"project_id", "task_id"}
    if not sent:
        raise HTTPException(400, "Nothing to change: say what should be different about the task.")
    merged = {"name": old["name"], "description": old["description"], "estimated_hours": old["estimated_hours"],
              "start_date": old["start_date"], "end_date": old["end_date"], "status": old["status"]}
    for field in sent:
        merged[field] = getattr(body, field)
    name, description, hours, status = _clean(merged["name"], merged["description"], merged["estimated_hours"], merged["status"])
    if name.lower() != (old["name"] or "").strip().lower():
        _no_duplicate(conn, project["id"], name, except_task_id=old["id"])
    task = update_task_record(conn, user, inst_id, project, old, ProjectTaskIn(
        name=name, description=description, estimated_hours=hours, start_date=_date(merged["start_date"], "Start date"),
        end_date=_date(merged["end_date"], "End date"), status=status), via=VIA)
    return {"task_id": task["id"], "task_name": task["name"], "project_id": project["id"], "project_name": project["name"],
            "changed": sorted(sent), "status": task["status"], "estimated_hours": task["estimated_hours"],
            "start_date": task["start_date"], "end_date": task["end_date"], "previous_name": old["name"]}


class TaskDeleteIn(BaseModel):
    project_id: int
    task_id: int


@router.post("/api/me/project-tasks/delete", tags=["projects"])
@db_session
def delete_my_project_task(conn, body: TaskDeleteIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    project = _my_project(conn, user, body.project_id)
    inst_id = need_inst(user)
    task = conn.execute("SELECT name FROM project_tasks WHERE id=? AND project_id=? AND institution_id=?", (body.task_id, project["id"], inst_id)).fetchone()
    if not task:
        raise HTTPException(404, "Task not found")
    delete_task_record(conn, user, inst_id, project["id"], body.task_id, via=VIA)
    return {"deleted": True, "task_name": task["name"], "project_id": project["id"], "project_name": project["name"]}
