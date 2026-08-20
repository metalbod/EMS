"""Generic approval-workflow engine, shared by every module that gates a
request behind approval: Leave, Benefits Claims, Job Requisition,
Timesheet, and L&D Enrollment. See README.md's "Approval workflow module"
section for the full mechanism. Each module used to hardcode its own
single-step role check (e.g. "role in (manager, hr_manager, hr_admin)")
with no verification that an approving "manager" was the requester's
*actual* manager — this replaces that with a per-institution configurable,
1-4 step chain of direct_manager / skip_level_manager / hr_manager /
specific_employee / project_manager approvers.
"""
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

APPROVER_TYPES = ("direct_manager", "skip_level_manager", "hr_manager", "specific_employee", "project_manager")
MAX_STEPS = 4

# project_manager only makes sense where the request either lets the
# requester pick a project (Leave, Claims — see project_id on those
# tables) or already has one via its own line items (Timesheet, via
# timesheet_entries.project_id, and Overtime — via its parent timesheet's
# entries, see project_ids_for_row). Requisition and L&D Enrollment have
# no project link at all, so the settings UI doesn't offer this type for
# them.
PROJECT_MANAGER_MODULES = ("leave", "claims", "timesheet", "overtime")

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
    "overtime": ("hr_manager", "hr_admin"),
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
    "overtime": "overtime_records",
}
MODULE_EMPLOYEE_COL = {
    "leave": "employee_id",
    "timesheet": "employee_id",
    "claims": "employee_id",
    "requisition": None,  # resolved via created_by -> users.employee_id
    "ld_enrollment": "employee_id",
    "overtime": "employee_id",
}
MODULE_PENDING_STATUSES = {
    "leave": ("Pending Approval",),
    "timesheet": ("Submitted",),
    "claims": ("Submitted", "Under Review"),
    "requisition": ("Pending Approval",),
    "ld_enrollment": ("Pending Approval",),
    "overtime": ("Pending",),
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


def _timesheet_project_ids(conn, timesheet_id: int) -> Set[int]:
    rows = conn.execute(
        "SELECT DISTINCT project_id FROM timesheet_entries WHERE timesheet_id=?", (timesheet_id,)
    ).fetchall()
    return {r["project_id"] for r in rows}


def project_ids_for_row(conn, module: str, row) -> Set[int]:
    """Which project(s) a project_manager step should resolve against for
    this specific request. Leave/Claims: the single project_id the
    requester picked at submission (or none, if the applicable workflow
    has no project_manager step and the field was left blank). Timesheet:
    the union of every project logged in that week's entries — a
    timesheet can span multiple projects, so any of their managers is
    eligible rather than requiring one specific project to be picked.
    Overtime: the same union, via its parent timesheet — an overtime
    record has no project of its own, it just follows whatever the
    timesheet it was detected on already logged."""
    if module in ("leave", "claims"):
        pid = row["project_id"] if "project_id" in row.keys() else None
        return {pid} if pid else set()
    if module == "timesheet":
        return _timesheet_project_ids(conn, row["id"])
    if module == "overtime":
        return _timesheet_project_ids(conn, row["timesheet_id"])
    return set()


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


def _project_managers_for(conn, inst_id: int, project_ids) -> FrozenSet[str]:
    if not project_ids:
        return frozenset()
    placeholders = ",".join("?" * len(project_ids))
    rows = conn.execute(
        f"SELECT DISTINCT pm.employee_id FROM project_managers pm "
        f"JOIN projects p ON p.id = pm.project_id "
        f"WHERE p.institution_id=? AND pm.project_id IN ({placeholders})",
        (inst_id, *project_ids)
    ).fetchall()
    return frozenset(r["employee_id"] for r in rows)


def _hr_pool_has_other(conn, inst_id: int, module: str, employee_id: str) -> bool:
    """Whether some HR-role user besides the requester themselves exists —
    a staff-only HR account with no linked employee record (employee_id
    IS NULL) always counts, since it can never literally *be* the
    requester; an HR account that IS linked only counts if it's not this
    request's own requester."""
    roles = MODULE_HR_ROLES[module]
    placeholders = ",".join("?" * len(roles))
    rows = conn.execute(
        f"SELECT employee_id FROM users WHERE institution_id=? AND role IN ({placeholders}) AND is_active=1",
        (inst_id, *roles)
    ).fetchall()
    return any(r["employee_id"] is None or r["employee_id"] != employee_id for r in rows)


def _type_pool_nonempty(conn, inst_id: int, module: str, employee_id: str, approver_type: Optional[str],
                        specific_employee_id: Optional[str], project_ids: Optional[Set[int]] = None) -> bool:
    """Nonempty here means "someone other than the requester themselves is
    eligible" — a step whose only possible approver would be the
    applicant is treated the same as a step with no approver at all (see
    _step_pool_nonempty), so the engine auto-skips it instead of letting
    someone approve their own request."""
    if approver_type == "direct_manager":
        mgr = _direct_manager_id(conn, inst_id, employee_id)
        return bool(mgr) and mgr != employee_id
    if approver_type == "skip_level_manager":
        mgr = _skip_level_manager_id(conn, inst_id, employee_id)
        return bool(mgr) and mgr != employee_id
    if approver_type == "hr_manager":
        return _hr_pool_has_other(conn, inst_id, module, employee_id)
    if approver_type == "specific_employee":
        if not specific_employee_id or specific_employee_id == employee_id:
            return False
        row = conn.execute(
            "SELECT status FROM employees WHERE employee_id=? AND institution_id=?",
            (specific_employee_id, inst_id)
        ).fetchone()
        return bool(row and row["status"] == "Active")
    if approver_type == "project_manager":
        return bool(_project_managers_for(conn, inst_id, project_ids) - {employee_id})
    return False


def _step_pool_nonempty(conn, inst_id: int, module: str, employee_id: str, step, project_ids: Optional[Set[int]] = None) -> bool:
    """Whether a step has anyone who could possibly approve it, for this
    specific request — a step with an empty pool (no manager exists, no
    skip-level exists, a deactivated named approver, no project manager
    for the relevant project(s), or the only possible approver would be
    the requester themselves) is auto-skipped rather than leaving the
    request stuck forever, or letting someone approve their own request.
    A step with an alternative ("OR") approver type configured is
    nonempty if either the primary or the alternative pool is nonempty."""
    if _type_pool_nonempty(conn, inst_id, module, employee_id, step["approver_type"], step["specific_employee_id"], project_ids):
        return True
    if step.get("alt_approver_type"):
        return _type_pool_nonempty(conn, inst_id, module, employee_id, step["alt_approver_type"], step.get("alt_specific_employee_id"), project_ids)
    return False


def _type_is_eligible(conn, inst_id: int, module: str, employee_id: str, approver_type: Optional[str],
                      specific_employee_id: Optional[str], acting_user: dict,
                      project_ids: Optional[Set[int]] = None) -> bool:
    if approver_type == "direct_manager":
        return bool(acting_user.get("employee_id")) and acting_user["employee_id"] == _direct_manager_id(conn, inst_id, employee_id)
    if approver_type == "skip_level_manager":
        return bool(acting_user.get("employee_id")) and acting_user["employee_id"] == _skip_level_manager_id(conn, inst_id, employee_id)
    if approver_type == "hr_manager":
        return acting_user["role"] in MODULE_HR_ROLES[module]
    if approver_type == "specific_employee":
        return bool(acting_user.get("employee_id")) and acting_user["employee_id"] == specific_employee_id
    if approver_type == "project_manager":
        return bool(acting_user.get("employee_id")) and acting_user["employee_id"] in _project_managers_for(conn, inst_id, project_ids)
    return False


def is_eligible_approver(conn, inst_id: int, module: str, employee_id: str, step, acting_user: dict,
                         project_ids: Optional[Set[int]] = None) -> bool:
    """A step with an alternative ("OR") approver type is satisfied by
    either the primary or the alternative approver. A requester can never
    be eligible to approve their own request, regardless of approver type
    (defense in depth — _step_pool_nonempty should already have
    auto-skipped any step where the requester was the only possible
    approver, but this guards decision time too)."""
    if acting_user["role"] == "superadmin":
        return True
    if acting_user.get("employee_id") and acting_user["employee_id"] == employee_id:
        return False
    if _type_is_eligible(conn, inst_id, module, employee_id, step["approver_type"], step["specific_employee_id"], acting_user, project_ids):
        return True
    if step.get("alt_approver_type"):
        return _type_is_eligible(conn, inst_id, module, employee_id, step["alt_approver_type"], step.get("alt_specific_employee_id"), acting_user, project_ids)
    return False


def _first_resolvable_step(conn, inst_id: int, module: str, employee_id: str, steps, project_ids: Optional[Set[int]] = None) -> Optional[Dict[str, Any]]:
    for step in steps:
        if _step_pool_nonempty(conn, inst_id, module, employee_id, step, project_ids):
            return step
    return None


def start_workflow(conn, inst_id: int, module: str, employee_id: str,
                   project_ids: Optional[Set[int]] = None) -> Tuple[int, Optional[int], bool]:
    """Called when a request is first submitted. Returns
    (approval_workflow_id, approval_step_order_or_None, auto_approved) —
    approval_step is None (and auto_approved True) if no step in the whole
    chain has anyone eligible (e.g. a solo employee with no manager and no
    HR steps configured), so a request never gets permanently stuck with
    nobody able to act on it. `project_ids` only matters for a workflow
    that has a project_manager step configured; pass the requester's
    selected/logged project(s) — see project_ids_for_row."""
    workflow = get_or_create_default_workflow(conn, inst_id, module)
    steps = get_steps(conn, workflow["id"])
    first = _first_resolvable_step(conn, inst_id, module, employee_id, steps, project_ids)
    if first is None:
        return workflow["id"], None, True
    return workflow["id"], first["step_order"], False


def advance_or_finalize(conn, inst_id: int, module: str, employee_id: str,
                        workflow_id: int, current_step_order: int,
                        action: str, acting_user: dict,
                        project_ids: Optional[Set[int]] = None) -> Tuple[str, Optional[int]]:
    """Validates `acting_user` can act on the request's current step, then
    returns (outcome, next_step_order): outcome is 'rejected', 'approved'
    (chain fully cleared), or 'advanced' (next_step_order is the new
    pending step). Raises PermissionError if acting_user isn't eligible —
    callers translate that to a 403."""
    steps = get_steps(conn, workflow_id)
    current = next((s for s in steps if s["step_order"] == current_step_order), None)
    if current is None:
        raise PermissionError("This request's current approval step no longer exists")
    if not is_eligible_approver(conn, inst_id, module, employee_id, current, acting_user, project_ids):
        raise PermissionError("You are not an eligible approver for this request's current step")
    if action == "reject":
        return "rejected", None
    remaining = [s for s in steps if s["step_order"] > current_step_order]
    nxt = _first_resolvable_step(conn, inst_id, module, employee_id, remaining, project_ids)
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
        project_ids = project_ids_for_row(conn, module, row)
        if is_eligible_approver(conn, inst_id, module, employee_id, current, user, project_ids):
            count += 1
    return count


def filter_actionable(conn, inst_id: int, module: str, rows: List[Dict[str, Any]], user: dict) -> List[Dict[str, Any]]:
    """For a list endpoint's already role-scoped rows (e.g. a manager sees
    only their subordinates' requests), additionally drop any row sitting
    at a pending status whose *current step* this user isn't eligible to
    act on right now.

    Without this, a request that's already cleared a manager's step and
    moved on (e.g. to HR) still showed up in that manager's "pending
    approval" list — still their subordinate, still Pending Approval — with
    live Approve/Reject buttons that 403 on click. The list query only
    ever checked "is this my subordinate," never re-checked eligibility
    against the request's current step, unlike the approve/reject action
    itself (advance_or_finalize) or the Dashboard's
    count_pending_for_approver above, whose loop this mirrors.

    A row is always kept (never hidden) if it's not at a pending status
    for this module, or has no workflow/step recorded — those carry no
    action buttons, or (a legacy pre-engine row) are gated by that
    module's own blanket role-based fallback instead of this engine, so
    hiding them here would be wrong.
    """
    pending = set(MODULE_PENDING_STATUSES[module])
    result = []
    for row in rows:
        if row["status"] not in pending or row["approval_workflow_id"] is None or row["approval_step"] is None:
            result.append(row)
            continue
        steps = get_steps(conn, row["approval_workflow_id"])
        current = next((s for s in steps if s["step_order"] == row["approval_step"]), None)
        if not current:
            result.append(row)
            continue
        employee_id = _requester_employee_id(conn, inst_id, module, row)
        if not employee_id:
            result.append(row)
            continue
        project_ids = project_ids_for_row(conn, module, row)
        if is_eligible_approver(conn, inst_id, module, employee_id, current, user, project_ids):
            result.append(row)
    return result
