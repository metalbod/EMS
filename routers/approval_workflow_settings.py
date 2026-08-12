"""Approval Workflow settings: institution-configurable approval chains for
Leave, Benefits Claims, Job Requisition, Timesheet, and L&D Enrollment. See
core/approval_workflow.py for the resolution/advancement engine these
configure, and README.md's "Approval workflow module" section for the
overall mechanism.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import get_current_user, need_inst
except ImportError:
    from ems.core.deps import get_current_user, need_inst

try:
    from core.permission_matrix import require_permission
except ImportError:
    from ems.core.permission_matrix import require_permission

try:
    from core.approval_workflow import APPROVER_TYPES, MAX_STEPS, MODULE_TABLE, PROJECT_MANAGER_MODULES, get_steps
except ImportError:
    from ems.core.approval_workflow import APPROVER_TYPES, MAX_STEPS, MODULE_TABLE, PROJECT_MANAGER_MODULES, get_steps

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()

MODULES = tuple(MODULE_TABLE.keys())
# Same role set that already manages Leave Types / Holidays — approval
# workflows are an HR-configuration concern, not a superadmin-only one.
WORKFLOW_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")


class WorkflowIn(BaseModel):
    module: str
    name: str

    @field_validator("module")
    @classmethod
    def _validate_module(cls, v):
        if v not in MODULES:
            raise ValueError(f"module must be one of: {', '.join(MODULES)}")
        return v


class WorkflowUpdateIn(BaseModel):
    name: str
    is_default: bool = False


class StepIn(BaseModel):
    approver_type: str
    specific_employee_id: Optional[str] = None
    # Alternative ("OR") approver for this step — the step is satisfied by
    # whichever of the two acts first. None means no alternative configured.
    alt_approver_type: Optional[str] = None
    alt_specific_employee_id: Optional[str] = None

    @field_validator("approver_type")
    @classmethod
    def _validate_approver_type(cls, v):
        if v not in APPROVER_TYPES:
            raise ValueError(f"approver_type must be one of: {', '.join(APPROVER_TYPES)}")
        return v

    @field_validator("alt_approver_type")
    @classmethod
    def _validate_alt_approver_type(cls, v):
        if v is not None and v not in APPROVER_TYPES:
            raise ValueError(f"alt_approver_type must be one of: {', '.join(APPROVER_TYPES)}")
        return v


class StepMoveIn(BaseModel):
    direction: str  # up | down


def _with_steps(conn, workflow_row) -> Dict[str, Any]:
    d = dict(workflow_row)
    d["steps"] = get_steps(conn, d["id"])
    return d


def _validate_step_body(conn, inst_id: int, module: str, body: "StepIn") -> None:
    if body.alt_approver_type and body.alt_approver_type == body.approver_type:
        raise HTTPException(400, "alt_approver_type must differ from approver_type")
    for approver_type, specific_employee_id, field_name in (
        (body.approver_type, body.specific_employee_id, "specific_employee_id"),
        (body.alt_approver_type, body.alt_specific_employee_id, "alt_specific_employee_id"),
    ):
        if approver_type == "project_manager" and module not in PROJECT_MANAGER_MODULES:
            raise HTTPException(400, f"project_manager is only available for: {', '.join(PROJECT_MANAGER_MODULES)}")
        if approver_type != "specific_employee":
            continue
        if not specific_employee_id:
            raise HTTPException(400, f"{field_name} is required when approver_type is specific_employee")
        emp = conn.execute(
            "SELECT employee_id FROM employees WHERE employee_id=? AND institution_id=?",
            (specific_employee_id, inst_id)
        ).fetchone()
        if not emp:
            raise HTTPException(404, "Employee not found")


@router.get("/api/approval-workflows")
@db_session
def list_workflows(conn, module: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = "SELECT * FROM approval_workflows WHERE institution_id=? AND is_active=1"
    p: list = [inst_id]
    if module:
        q += " AND module=?"; p.append(module)
    q += " ORDER BY module, is_default DESC, name"
    rows = conn.execute(q, p).fetchall()
    return [_with_steps(conn, r) for r in rows]


@router.post("/api/approval-workflows", status_code=201)
@db_session
def create_workflow(conn, body: WorkflowIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    existing_default = conn.execute(
        "SELECT id FROM approval_workflows WHERE institution_id=? AND module=? AND is_active=1", (inst_id, body.module)
    ).fetchone()
    conn.execute(
        "INSERT INTO approval_workflows (institution_id,module,name,is_default) VALUES (?,?,?,?)",
        (inst_id, body.module, body.name.strip(), 0 if existing_default else 1)
    )
    workflow_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return _with_steps(conn, conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone())


def _get_owned_workflow(conn, inst_id: int, workflow_id: int):
    row = conn.execute(
        "SELECT * FROM approval_workflows WHERE id=? AND institution_id=? AND is_active=1", (workflow_id, inst_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Workflow not found")
    return row


@router.put("/api/approval-workflows/{workflow_id}")
@db_session
def update_workflow(conn, workflow_id: int, body: WorkflowUpdateIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    wf = _get_owned_workflow(conn, inst_id, workflow_id)
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    if body.is_default:
        conn.execute(
            "UPDATE approval_workflows SET is_default=0 WHERE institution_id=? AND module=? AND id<>?",
            (inst_id, wf["module"], workflow_id)
        )
    conn.execute(
        "UPDATE approval_workflows SET name=?,is_default=? WHERE id=?",
        (body.name.strip(), 1 if body.is_default else 0, workflow_id)
    )
    conn.commit()
    return _with_steps(conn, conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone())


@router.delete("/api/approval-workflows/{workflow_id}", status_code=204)
@db_session
def delete_workflow(conn, workflow_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    wf = _get_owned_workflow(conn, inst_id, workflow_id)
    conn.execute("UPDATE approval_workflows SET is_active=0 WHERE id=?", (workflow_id,))
    if wf["is_default"]:
        other = conn.execute(
            "SELECT id FROM approval_workflows WHERE institution_id=? AND module=? AND is_active=1 AND id<>? ORDER BY id LIMIT 1",
            (inst_id, wf["module"], workflow_id)
        ).fetchone()
        if other:
            conn.execute("UPDATE approval_workflows SET is_default=1 WHERE id=?", (other["id"],))
        # If no other workflow exists, the next start_workflow() call for
        # this module lazily recreates a fresh 2-step default — see
        # core/approval_workflow.py's get_or_create_default_workflow.
    conn.commit()


@router.post("/api/approval-workflows/{workflow_id}/steps", status_code=201)
@db_session
def add_step(conn, workflow_id: int, body: StepIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    wf = _get_owned_workflow(conn, inst_id, workflow_id)
    _validate_step_body(conn, inst_id, wf["module"], body)
    existing = get_steps(conn, workflow_id)
    if len(existing) >= MAX_STEPS:
        raise HTTPException(400, f"A workflow can have at most {MAX_STEPS} steps")
    next_order = (max((s["step_order"] for s in existing), default=0)) + 1
    conn.execute(
        "INSERT INTO approval_workflow_steps "
        "(workflow_id,step_order,approver_type,specific_employee_id,alt_approver_type,alt_specific_employee_id) "
        "VALUES (?,?,?,?,?,?)",
        (workflow_id, next_order, body.approver_type, body.specific_employee_id,
         body.alt_approver_type, body.alt_specific_employee_id if body.alt_approver_type == "specific_employee" else None)
    )
    conn.commit()
    return _with_steps(conn, conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone())


def _get_owned_step(conn, inst_id: int, workflow_id: int, step_id: int):
    _get_owned_workflow(conn, inst_id, workflow_id)
    row = conn.execute(
        "SELECT * FROM approval_workflow_steps WHERE id=? AND workflow_id=?", (step_id, workflow_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Step not found")
    return row


@router.put("/api/approval-workflows/{workflow_id}/steps/{step_id}")
@db_session
def update_step(conn, workflow_id: int, step_id: int, body: StepIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    _get_owned_step(conn, inst_id, workflow_id, step_id)
    wf = _get_owned_workflow(conn, inst_id, workflow_id)
    _validate_step_body(conn, inst_id, wf["module"], body)
    conn.execute(
        "UPDATE approval_workflow_steps SET approver_type=?,specific_employee_id=?,alt_approver_type=?,alt_specific_employee_id=? WHERE id=?",
        (body.approver_type, body.specific_employee_id if body.approver_type == "specific_employee" else None,
         body.alt_approver_type, body.alt_specific_employee_id if body.alt_approver_type == "specific_employee" else None,
         step_id)
    )
    conn.commit()
    return _with_steps(conn, conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone())


@router.delete("/api/approval-workflows/{workflow_id}/steps/{step_id}", status_code=204)
@db_session
def delete_step(conn, workflow_id: int, step_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    _get_owned_step(conn, inst_id, workflow_id, step_id)
    conn.execute("DELETE FROM approval_workflow_steps WHERE id=?", (step_id,))
    # Re-number remaining steps to stay contiguous (1..N) so step_order
    # comparisons elsewhere (advance_or_finalize's "remaining steps after
    # current") don't have to handle gaps.
    remaining = conn.execute(
        "SELECT id FROM approval_workflow_steps WHERE workflow_id=? ORDER BY step_order", (workflow_id,)
    ).fetchall()
    for idx, r in enumerate(remaining, start=1):
        conn.execute("UPDATE approval_workflow_steps SET step_order=? WHERE id=?", (idx, r["id"]))
    conn.commit()


@router.post("/api/approval-workflows/{workflow_id}/steps/{step_id}/move")
@db_session
def move_step(conn, workflow_id: int, step_id: int, body: StepMoveIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "approval_workflows.manage_approval_workflows_steps")
    inst_id = need_inst(user)
    _get_owned_step(conn, inst_id, workflow_id, step_id)
    if body.direction not in ("up", "down"):
        raise HTTPException(400, "direction must be up or down")
    steps = get_steps(conn, workflow_id)
    idx = next((i for i, s in enumerate(steps) if s["id"] == step_id), None)
    swap_idx = idx - 1 if body.direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(steps):
        return _with_steps(conn, conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone())
    a, b = steps[idx], steps[swap_idx]
    conn.execute("UPDATE approval_workflow_steps SET step_order=? WHERE id=?", (b["step_order"], a["id"]))
    conn.execute("UPDATE approval_workflow_steps SET step_order=? WHERE id=?", (a["step_order"], b["id"]))
    conn.commit()
    return _with_steps(conn, conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone())
