"""Generic approval-workflow engine, shared by every module that gates a
request behind approval: Leave, Benefits Claims, Job Requisition,
Timesheet, and L&D Enrollment. See README.md's "Approval workflow module"
section for the full mechanism. Each module used to hardcode its own
single-step role check (e.g. "role in (manager, hr_manager, hr_admin)")
with no verification that an approving "manager" was the requester's
*actual* manager — this replaces that with a per-institution configurable,
1-4 step chain of direct_manager / skip_level_manager / hr_manager /
specific_employee approvers.
"""
from typing import Any, Dict, List, Optional, Tuple

APPROVER_TYPES = ("direct_manager", "skip_level_manager", "hr_manager", "specific_employee")
MAX_STEPS = 4

# Each module's own "HR-ish" role set, preserved from what that module's
# hardcoded check allowed before this engine existed (they're not
# identical — e.g. Claims never included hr_admin, Requisition approval
# was hr_manager-only) — superadmin is always an implicit override on top,
# matching every pre-existing check in this codebase.
MODULE_HR_ROLES = {
    "leave": ("hr_manager", "hr_admin"),
    "timesheet": ("hr_manager", "hr_admin"),
    "claims": ("hr_manager", "payroll_manager", "compensation_manager"),
    "requisition": ("hr_manager",),
    "ld_enrollment": ("hr_manager", "hr_admin"),
}

# table + the employee column identifying who the request is *for* (the
# requester whose reporting chain direct_manager/skip_level_manager
# resolve from). job_requisitions has no such column — see
# _requester_employee_id below, which resolves it via the creating user's
# own linked employee record instead.
MODULE_TABLE = {
    "leave": "leave_applications",
    "timesheet": "timesheets",
    "claims": "benefit_claims",
    "requisition": "job_requisitions",
    "ld_enrollment": "ld_enrollments",
}
MODULE_EMPLOYEE_COL = {
    "leave": "employee_id",
    "timesheet": "employee_id",
    "claims": "employee_id",
    "requisition": None,  # resolved via created_by -> users.employee_id
    "ld_enrollment": "employee_id",
}
MODULE_PENDING_STATUSES = {
    "leave": ("Pending Approval",),
    "timesheet": ("Submitted",),
    "claims": ("Submitted", "Under Review"),
    "requisition": ("Pending Approval",),
    "ld_enrollment": ("Pending Approval",),
}


def _requester_employee_id(conn, inst_id: int, module: str, row) -> Optional[str]:
    col = MODULE_EMPLOYEE_COL[module]
    if col:
        return row[col]
    # requisition: whoever created it, resolved to their own employee record.
    u = conn.execute(
        "SELECT employee_id FROM users WHERE username=? AND institution_id=?",
        (row["created_by"], inst_id)
    ).fetchone()
    return u["employee_id"] if u else None


def get_or_create_default_workflow(conn, inst_id: int, module: str) -> Dict[str, Any]:
    """The active default workflow for this institution+module — created
    lazily (2 steps: Direct Manager, then this module's HR roles) the
    first time it's needed, rather than seeded for every institution up
    front. Mirrors the ob_template_sets "resolve or create default"
    pattern from the onboarding-templates module."""
    row = conn.execute(
        "SELECT * FROM approval_workflows WHERE institution_id=? AND module=? AND is_active=1 "
        "ORDER BY is_default DESC, id LIMIT 1",
        (inst_id, module)
    ).fetchone()
    if row:
        return dict(row)
    conn.execute(
        "INSERT INTO approval_workflows (institution_id,module,name,is_default,is_active) VALUES (?,?,?,1,1)",
        (inst_id, module, "Default")
    )
    workflow_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO approval_workflow_steps (workflow_id,step_order,approver_type) VALUES (?,1,'direct_manager')",
        (workflow_id,)
    )
    conn.execute(
        "INSERT INTO approval_workflow_steps (workflow_id,step_order,approver_type) VALUES (?,2,'hr_manager')",
        (workflow_id,)
    )
    conn.commit()
    return conn.execute("SELECT * FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone()


def get_steps(conn, workflow_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM approval_workflow_steps WHERE workflow_id=? ORDER BY step_order", (workflow_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _direct_manager_id(conn, inst_id: int, employee_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT reports_to FROM employees WHERE employee_id=? AND institution_id=?", (employee_id, inst_id)
    ).fetchone()
    return row["reports_to"] if row else None


def _skip_level_manager_id(conn, inst_id: int, employee_id: str) -> Optional[str]:
    mgr = _direct_manager_id(conn, inst_id, employee_id)
    return _direct_manager_id(conn, inst_id, mgr) if mgr else None


def _step_pool_nonempty(conn, inst_id: int, employee_id: str, step) -> bool:
    """Whether a step has anyone who could possibly approve it, for this
    specific request — a step with an empty pool (no manager exists, no
    skip-level exists, or the designated specific employee is inactive)
    is auto-skipped rather than leaving the request stuck forever."""
    t = step["approver_type"]
    if t == "direct_manager":
        return bool(_direct_manager_id(conn, inst_id, employee_id))
    if t == "skip_level_manager":
        return bool(_skip_level_manager_id(conn, inst_id, employee_id))
    if t == "hr_manager":
        return True  # role-based; assume every institution has at least one HR user
    if t == "specific_employee":
        if not step["specific_employee_id"]:
            return False
        row = conn.execute(
            "SELECT status FROM employees WHERE employee_id=? AND institution_id=?",
            (step["specific_employee_id"], inst_id)
        ).fetchone()
        return bool(row and row["status"] == "Active")
    return False


def is_eligible_approver(conn, inst_id: int, module: str, employee_id: str, step, acting_user: dict) -> bool:
    if acting_user["role"] == "superadmin":
        return True
    t = step["approver_type"]
    if t == "direct_manager":
        return acting_user.get("employee_id") and acting_user["employee_id"] == _direct_manager_id(conn, inst_id, employee_id)
    if t == "skip_level_manager":
        return acting_user.get("employee_id") and acting_user["employee_id"] == _skip_level_manager_id(conn, inst_id, employee_id)
    if t == "hr_manager":
        return acting_user["role"] in MODULE_HR_ROLES[module]
    if t == "specific_employee":
        return acting_user.get("employee_id") and acting_user["employee_id"] == step["specific_employee_id"]
    return False


def _first_resolvable_step(conn, inst_id: int, employee_id: str, steps) -> Optional[Dict[str, Any]]:
    for step in steps:
        if _step_pool_nonempty(conn, inst_id, employee_id, step):
            return step
    return None


def start_workflow(conn, inst_id: int, module: str, employee_id: str) -> Tuple[int, Optional[int], bool]:
    """Called when a request is first submitted. Returns
    (approval_workflow_id, approval_step_order_or_None, auto_approved) —
    approval_step is None (and auto_approved True) if no step in the whole
    chain has anyone eligible (e.g. a solo employee with no manager and no
    HR steps configured), so a request never gets permanently stuck with
    nobody able to act on it."""
    workflow = get_or_create_default_workflow(conn, inst_id, module)
    steps = get_steps(conn, workflow["id"])
    first = _first_resolvable_step(conn, inst_id, employee_id, steps)
    if first is None:
        return workflow["id"], None, True
    return workflow["id"], first["step_order"], False


def advance_or_finalize(conn, inst_id: int, module: str, employee_id: str,
                        workflow_id: int, current_step_order: int,
                        action: str, acting_user: dict) -> Tuple[str, Optional[int]]:
    """Validates `acting_user` can act on the request's current step, then
    returns (outcome, next_step_order): outcome is 'rejected', 'approved'
    (chain fully cleared), or 'advanced' (next_step_order is the new
    pending step). Raises PermissionError if acting_user isn't eligible —
    callers translate that to a 403."""
    steps = get_steps(conn, workflow_id)
    current = next((s for s in steps if s["step_order"] == current_step_order), None)
    if current is None:
        raise PermissionError("This request's current approval step no longer exists")
    if not is_eligible_approver(conn, inst_id, module, employee_id, current, acting_user):
        raise PermissionError("You are not an eligible approver for this request's current step")
    if action == "reject":
        return "rejected", None
    remaining = [s for s in steps if s["step_order"] > current_step_order]
    nxt = _first_resolvable_step(conn, inst_id, employee_id, remaining)
    if nxt is None:
        return "approved", None
    return "advanced", nxt["step_order"]


def count_pending_for_approver(conn, inst_id: int, user: dict, module: str) -> int:
    """How many of this module's pending requests are sitting at a step
    `user` is eligible to act on right now — powers the Dashboard To-Do
    integration (see routers/dashboard.py)."""
    table = MODULE_TABLE[module]
    statuses = MODULE_PENDING_STATUSES[module]
    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE institution_id=? AND status IN ({placeholders}) "
        f"AND approval_workflow_id IS NOT NULL AND approval_step IS NOT NULL",
        (inst_id, *statuses)
    ).fetchall()
    count = 0
    for row in rows:
        steps = get_steps(conn, row["approval_workflow_id"])
        current = next((s for s in steps if s["step_order"] == row["approval_step"]), None)
        if not current:
            continue
        employee_id = _requester_employee_id(conn, inst_id, module, row)
        if not employee_id:
            continue
        if is_eligible_approver(conn, inst_id, module, employee_id, current, user):
            count += 1
    return count
