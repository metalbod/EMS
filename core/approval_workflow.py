"""Generic approval-workflow engine, shared by every module that gates a
request behind approval: Leave, Benefits Claims, Job Requisition,
Timesheet, L&D Enrollment, Overtime, Resignation, and PIP. See README.md's
"Approval workflow module" section for the full mechanism. Each module
used to hardcode its own single-step role check (e.g. "role in (manager,
hr_manager, hr_admin)") with no verification that an approving "manager"
was the requester's *actual* manager — this replaces that with a
per-institution configurable, 1-4 step chain of direct_manager /
skip_level_manager / hr_manager / specific_employee / project_manager
approvers.

Each workflow also has a `mode` (see WORKFLOW_MODES): 'sequential' (the
default, and how every workflow behaved before this existed) requires
step 1 to clear before step 2 becomes actionable, and so on; 'flat' lets
every step with a nonempty approver pool act at once, finalizing once all
of them have approved (a reject at any one is still immediately
terminal, same as sequential). Flat mode's per-step decisions are
recorded in approval_step_decisions, since a request row's own single
`approval_step` column can't represent "several steps open at once."
"""
import logging
import os
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from core.email_engine import send_email

logger = logging.getLogger("ems")

APPROVER_TYPES = ("direct_manager", "skip_level_manager", "hr_manager", "specific_employee", "project_manager")
MAX_STEPS = 4
WORKFLOW_MODES = ("sequential", "flat")

APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://ems-app.fly.dev")

# Human-readable module names for email subjects/bodies — separate from
# _STEP_TYPE_LABELS (which labels an approver *type*, not a module).
MODULE_DISPLAY_NAME = {
    "leave": "Leave Application",
    "timesheet": "Timesheet",
    "claims": "Benefit Claim",
    "requisition": "Job Requisition",
    "ld_enrollment": "L&D Enrollment",
    "overtime": "Overtime",
    "resignation": "Resignation Request",
    "pip": "Performance Improvement Plan",
}

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
    "resignation": ("hr_manager", "hr_admin"),
    "pip": ("hr_manager",),  # matches PERFORMANCE_MANAGE_ROLES — every other
                              # Performance consequence (calibrate, merit,
                              # bonus) is hr_manager-only, not hr_admin too.
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
    "resignation": "resignation_requests",
    # Reuses performance_cycles rather than a dedicated table — standard/
    # probation cycles never populate approval_workflow_id/approval_step
    # (NULL for both) and never use the 'PendingApproval' status below, so
    # sharing the table is safe: every engine query here also filters on
    # those two columns being NOT NULL.
    "pip": "performance_cycles",
}
MODULE_EMPLOYEE_COL = {
    "leave": "employee_id",
    "timesheet": "employee_id",
    "claims": "employee_id",
    "requisition": None,  # resolved via created_by -> users.employee_id
    "ld_enrollment": "employee_id",
    "overtime": "employee_id",
    "resignation": "employee_id",
    "pip": "employee_id",
}
MODULE_PENDING_STATUSES = {
    "leave": ("Pending Approval",),
    "timesheet": ("Submitted",),
    "claims": ("Submitted", "Under Review"),
    "requisition": ("Pending Approval",),
    "ld_enrollment": ("Pending Approval",),
    "overtime": ("Pending",),
    "resignation": ("Pending",),
    "pip": ("PendingApproval",),
}

# timesheet/overtime rows submitted since 2026-09-17 track approval per
# project instead of on the parent row (see timesheet_project_approvals/
# overtime_project_approvals) — pending_rows_for_approver below reads BOTH
# this table (new-style) and MODULE_TABLE (legacy, pre-split rows that are
# never backfilled) rather than replacing one with the other, since a
# legacy row's own workflow instance is still live and actionable forever.
# Same pending-status strings as MODULE_PENDING_STATUSES: a fresh child row
# starts life carrying its module's own "just submitted" status.
MODULE_PROJECT_TABLE = {
    "timesheet": "timesheet_project_approvals",
    "overtime": "overtime_project_approvals",
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


def _request_identity_for_row(module: str, row) -> Tuple[str, int]:
    """(request_table, request_id) for approval_step_decisions lookups —
    the table+row a flat workflow's per-step decisions are recorded
    against, mirroring project_ids_for_row's own legacy-vs-split
    disambiguation (same "genuinely non-None project_id" signal). A
    per-project split row's true id is its own project-table row id: for
    a row read straight off that table (e.g. get_timesheet's
    project_approvals, or a raw fetch from MODULE_PROJECT_TABLE) that's
    just row['id']; for a row that's been through
    _expand_timesheet_rows/_expand_overtime_rows (which keep row['id']
    pointing at the PARENT record so the Timesheet Detail modal still
    opens by timesheet id) it's the project_approval_id key those
    functions overlay instead. Uses `"key" in row.keys()` throughout
    rather than `row.get(...)` since db.py's Row type (unlike a plain
    dict) has no .get()."""
    project_table = MODULE_PROJECT_TABLE.get(module)
    if project_table and "project_id" in row.keys() and row["project_id"] is not None:
        if "project_approval_id" in row.keys() and row["project_approval_id"] is not None:
            return project_table, row["project_approval_id"]
        return project_table, row["id"]
    return MODULE_TABLE[module], row["id"]


def _get_workflow_mode(conn, workflow_id: int) -> str:
    row = conn.execute("SELECT mode FROM approval_workflows WHERE id=?", (workflow_id,)).fetchone()
    return row["mode"] if row else "sequential"


def _decided_step_orders(conn, request_table: str, request_id: int) -> Set[int]:
    """Which step_orders already have a recorded decision (approve or
    reject) for this specific flat-mode request — sequential workflows
    never write here, so this is only ever consulted on the flat path."""
    rows = conn.execute(
        "SELECT step_order FROM approval_step_decisions WHERE request_table=? AND request_id=?",
        (request_table, request_id)
    ).fetchall()
    return {r["step_order"] for r in rows}


def _record_decision(conn, inst_id: int, module: str, request_table: str, request_id: int,
                     step_order: int, action: str, decided_by: str) -> None:
    conn.execute(
        "INSERT INTO approval_step_decisions "
        "(institution_id,module,request_table,request_id,step_order,action,decided_by) "
        "VALUES (?,?,?,?,?,?,?)",
        (inst_id, module, request_table, request_id, step_order, action, decided_by)
    )


def project_ids_for_row(conn, module: str, row) -> Set[int]:
    """Which project(s) a project_manager step should resolve against for
    this specific request. Leave/Claims: the single project_id the
    requester picked at submission (or none, if the applicable workflow
    has no project_manager step and the field was left blank).

    Timesheet/Overtime have two row shapes now (see
    timesheet_project_approvals/overtime_project_approvals, added
    2026-09-17 to split approval to the project level): a NEW-style
    per-project row already carries its own single project_id — disambiguated
    by its presence, since legacy rows never have that column — so it
    resolves to just that one project, not a union. A LEGACY row (a plain
    `timesheets`/`overtime_records` row that predates the split, or one
    read via this module's old whole-record path) still resolves to the
    union of every project logged in that week/day — kept forever, since
    those rows are never backfilled onto the new shape."""
    if module in ("leave", "claims"):
        pid = row["project_id"] if "project_id" in row.keys() else None
        return {pid} if pid else set()
    # A row that's been through routers/timesheets.py's _expand_timesheet_rows
    # (or overtime's equivalent) always has a project_id KEY, even for a
    # legacy/unsplit row (explicitly set to None there) — so disambiguating
    # by mere key presence would wrongly treat every legacy row as split.
    # Check for a genuinely non-None value instead.
    if module == "timesheet":
        if "project_id" in row.keys() and row["project_id"] is not None:
            return {row["project_id"]}
        return _timesheet_project_ids(conn, row["id"])
    if module == "overtime":
        if "project_id" in row.keys() and row["project_id"] is not None:
            return {row["project_id"]}
        return _timesheet_project_ids(conn, row["timesheet_id"])
    return set()


def get_or_create_default_workflow(conn, inst_id: int, module: str) -> Dict[str, Any]:
    """The active default workflow for this institution+module — created
    lazily (2 steps: Direct Manager, then this module's HR roles) the
    first time it's needed, rather than seeded for every institution up
    front. Mirrors the ob_template_sets "resolve or create default"
    pattern from the onboarding-templates module.

    "pip" is a deliberate exception: a 'direct_manager' first step would
    resolve to the PIP subject's direct manager — who, in the ordinary
    case, IS the manager who just proposed the PIP in the first place, so
    that step would trivially clear itself rather than add real scrutiny.
    Its default is a single hr_manager step instead. Institutions can
    still reconfigure either module's chain afterward via Settings ->
    Approval Workflows, same as any other module — this only controls
    what's seeded the first time."""
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
    if module == "pip":
        conn.execute(
            "INSERT INTO approval_workflow_steps (workflow_id,step_order,approver_type) VALUES (?,1,'hr_manager')",
            (workflow_id,)
        )
    else:
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


# ---------------------------------------------------------------------------
# Email notifications (Phase 1 — see migrations/versions/20260919_0001_*).
# Best-effort only: every function here is wrapped by _safe_notify at its
# call site in start_workflow/advance_or_finalize, so a bug or SMTP
# failure here can never break the underlying approval action. Resolves
# a step's approver *type* into concrete (name, email) contacts — a
# separate concern from is_eligible_approver, which only checks whether
# one specific acting_user matches, not who all the candidates are.
# ---------------------------------------------------------------------------
def _employee_contact(conn, inst_id: int, employee_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not employee_id:
        return None, None
    row = conn.execute(
        "SELECT full_name, work_email, personal_email FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    if not row:
        return None, None
    return row["full_name"], (row["work_email"] or row["personal_email"])


def _hr_pool_contacts(conn, inst_id: int, module: str, exclude_employee_id: Optional[str]) -> List[Tuple[Optional[str], str]]:
    """Every active user in this module's HR role set — same pool
    _hr_pool_has_other checks non-emptiness of, but resolved to actual
    contacts. A user account's own `email` wins over their linked
    employee record's, since that's the address they actually log in
    with; falls back to the employee record only if the user has none."""
    roles = MODULE_HR_ROLES[module]
    placeholders = ",".join("?" * len(roles))
    rows = conn.execute(
        f"SELECT username, email, employee_id FROM users WHERE institution_id=? AND role IN ({placeholders}) AND is_active=1",
        (inst_id, *roles)
    ).fetchall()
    contacts = []
    for r in rows:
        if exclude_employee_id and r["employee_id"] == exclude_employee_id:
            continue
        email = r["email"]
        name = None
        if r["employee_id"]:
            emp_name, emp_email = _employee_contact(conn, inst_id, r["employee_id"])
            name = emp_name
            email = email or emp_email
        if email:
            contacts.append((name, email))
    return contacts


def _recipient_contacts_for_type(conn, inst_id: int, module: str, employee_id: str, approver_type: Optional[str],
                                 specific_employee_id: Optional[str],
                                 project_ids: Optional[Set[int]]) -> List[Tuple[Optional[str], str]]:
    if approver_type == "direct_manager":
        name, email = _employee_contact(conn, inst_id, _direct_manager_id(conn, inst_id, employee_id))
        return [(name, email)] if email else []
    if approver_type == "skip_level_manager":
        name, email = _employee_contact(conn, inst_id, _skip_level_manager_id(conn, inst_id, employee_id))
        return [(name, email)] if email else []
    if approver_type == "hr_manager":
        return _hr_pool_contacts(conn, inst_id, module, employee_id)
    if approver_type == "specific_employee":
        name, email = _employee_contact(conn, inst_id, specific_employee_id)
        return [(name, email)] if email else []
    if approver_type == "project_manager":
        contacts = []
        for eid in _project_managers_for(conn, inst_id, project_ids) - {employee_id}:
            name, email = _employee_contact(conn, inst_id, eid)
            if email:
                contacts.append((name, email))
        return contacts
    return []


def _recipient_contacts_for_step(conn, inst_id: int, module: str, employee_id: str, step,
                                 project_ids: Optional[Set[int]]) -> List[Tuple[Optional[str], str]]:
    contacts = _recipient_contacts_for_type(conn, inst_id, module, employee_id, step["approver_type"],
                                            step["specific_employee_id"], project_ids)
    if step.get("alt_approver_type"):
        contacts += _recipient_contacts_for_type(conn, inst_id, module, employee_id, step["alt_approver_type"],
                                                 step.get("alt_specific_employee_id"), project_ids)
    seen: Set[str] = set()
    out = []
    for name, email in contacts:
        if email and email not in seen:
            seen.add(email)
            out.append((name, email))
    return out


def _notify_step_recipients(conn, inst_id: int, module: str, employee_id: str, step,
                            project_ids: Optional[Set[int]]) -> None:
    contacts = _recipient_contacts_for_step(conn, inst_id, module, employee_id, step, project_ids)
    if not contacts:
        return
    requester_name, _ = _employee_contact(conn, inst_id, employee_id)
    label = MODULE_DISPLAY_NAME.get(module, module)
    subject = f"{label} awaiting your approval"
    for name, email in contacts:
        body = (
            f"<p>Hi {name or 'there'},</p>"
            f"<p>A {label} from {requester_name or 'an employee'} is awaiting your approval.</p>"
            f'<p><a href="{APP_BASE_URL}">Open EMS</a> to review it.</p>'
        )
        send_email(conn, inst_id, email, subject, body, "approval_needed", module)


def _notify_requester_outcome(conn, inst_id: int, module: str, employee_id: str, outcome: str) -> None:
    name, email = _employee_contact(conn, inst_id, employee_id)
    if not email:
        return
    label = MODULE_DISPLAY_NAME.get(module, module)
    decision = "Approved" if outcome == "approved" else "Rejected"
    subject = f"Your {label} has been {decision}"
    body = (
        f"<p>Hi {name or 'there'},</p>"
        f"<p>Your {label} has been <strong>{decision}</strong>.</p>"
        f'<p><a href="{APP_BASE_URL}">Open EMS</a> to view details.</p>'
    )
    send_email(conn, inst_id, email, subject, body, "approval_decided", module)


def _safe_notify(fn, *args, **kwargs) -> None:
    """Runs a notification function, logging (never raising) on failure —
    the one guard point every call site below relies on so a bug in
    recipient resolution/email composition can never surface as a 500 on
    the underlying approve/reject/submit action."""
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("approval_workflow: notification failed")


# Human-readable labels for APPROVER_TYPES, matching
# static/js/approval-workflow.js's AW_STEP_LABELS — kept as a separate
# copy since that one labels a step *type* in the Settings screen, while
# describe_current_step below resolves a type to an actual person for one
# specific request.
_STEP_TYPE_LABELS = {
    "direct_manager": "Direct Manager",
    "skip_level_manager": "Skip-Level Manager",
    "hr_manager": "HR Manager",
    "specific_employee": "Specific Employee",
    "project_manager": "Project Manager",
}


def _employee_display_name(conn, inst_id: int, employee_id: Optional[str]) -> Optional[str]:
    if not employee_id:
        return None
    row = conn.execute(
        "SELECT full_name FROM employees WHERE employee_id=? AND institution_id=?",
        (employee_id, inst_id)
    ).fetchone()
    return row["full_name"] if row else None


def _describe_approver_type(conn, inst_id: int, employee_id: str, approver_type: Optional[str],
                            specific_employee_id: Optional[str], project_ids: Optional[Set[int]]) -> str:
    label = _STEP_TYPE_LABELS.get(approver_type, approver_type or "")
    name = None
    if approver_type == "direct_manager":
        name = _employee_display_name(conn, inst_id, _direct_manager_id(conn, inst_id, employee_id))
    elif approver_type == "skip_level_manager":
        name = _employee_display_name(conn, inst_id, _skip_level_manager_id(conn, inst_id, employee_id))
    elif approver_type == "specific_employee":
        name = _employee_display_name(conn, inst_id, specific_employee_id)
    elif approver_type == "project_manager":
        names = sorted(n for n in (
            _employee_display_name(conn, inst_id, eid) for eid in _project_managers_for(conn, inst_id, project_ids)
        ) if n)
        name = " / ".join(names) if names else None
    return f"{name} ({label})" if name else label


def describe_current_step(conn, inst_id: int, employee_id: str, step,
                          project_ids: Optional[Set[int]] = None) -> str:
    """Human-readable "who's holding this up right now" for a request
    sitting at this step — e.g. "Suwarto (Direct Manager)" or "HR
    Manager", joined with " or " when the step has an OR alternative.
    Used by annotate_actionability so a list screen has something to show
    in place of the Approve/Reject buttons once a viewer isn't (or isn't
    yet) the eligible approver."""
    primary = _describe_approver_type(conn, inst_id, employee_id, step["approver_type"],
                                      step["specific_employee_id"], project_ids)
    if step.get("alt_approver_type"):
        alt = _describe_approver_type(conn, inst_id, employee_id, step["alt_approver_type"],
                                      step.get("alt_specific_employee_id"), project_ids)
        return f"{primary} or {alt}"
    return primary


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
    if workflow.get("mode") == "flat":
        # Every resolvable step is open at once in flat mode — each of
        # their approvers needs telling now, not just the first one.
        for step in steps:
            if _step_pool_nonempty(conn, inst_id, module, employee_id, step, project_ids):
                _safe_notify(_notify_step_recipients, conn, inst_id, module, employee_id, step, project_ids)
    else:
        _safe_notify(_notify_step_recipients, conn, inst_id, module, employee_id, first, project_ids)
    return workflow["id"], first["step_order"], False


def advance_or_finalize(conn, inst_id: int, module: str, employee_id: str,
                        workflow_id: int, current_step_order: int,
                        action: str, acting_user: dict,
                        request_table: str, request_id: int,
                        project_ids: Optional[Set[int]] = None) -> Tuple[str, Optional[int]]:
    """Validates `acting_user` can act on the request right now, then
    returns (outcome, next_step_order): outcome is 'rejected', 'approved'
    (chain fully cleared), or 'advanced'. Raises PermissionError if
    acting_user isn't eligible for anything actionable right now —
    callers translate that to a 403.

    Sequential workflows (the default, and every pre-existing one — see
    approval_workflows.mode) behave exactly as before: only the row's own
    current_step_order is checked, and 'advanced' means "move to this new
    single step".

    Flat workflows let every step with a nonempty approver pool act at
    once instead of one at a time: current_step_order is ignored for
    eligibility (any still-undecided resolvable step qualifies, not just
    one), a single Approve clears every open step `acting_user` happens
    to be eligible for in one shot (see approval_step_decisions), reject
    is immediately terminal exactly as in sequential mode, and 'advanced'
    means "at least one other step is still undecided" — its
    next_step_order is only the lowest-numbered one of those, kept purely
    as a non-null "still pending" signal on the request row; nothing
    re-reads it as *the* current step for a flat row the way sequential
    mode does. `request_table`/`request_id` identify this specific row
    for recording each step's decision — required on every call (even
    sequential ones, which never read/write it) so a workflow could be
    switched from sequential to flat later without a gap in history."""
    steps = get_steps(conn, workflow_id)
    mode = _get_workflow_mode(conn, workflow_id)

    if mode != "flat":
        current = next((s for s in steps if s["step_order"] == current_step_order), None)
        if current is None:
            raise PermissionError("This request's current approval step no longer exists")
        if not is_eligible_approver(conn, inst_id, module, employee_id, current, acting_user, project_ids):
            raise PermissionError("You are not an eligible approver for this request's current step")
        if action == "reject":
            _safe_notify(_notify_requester_outcome, conn, inst_id, module, employee_id, "rejected")
            return "rejected", None
        remaining = [s for s in steps if s["step_order"] > current_step_order]
        nxt = _first_resolvable_step(conn, inst_id, module, employee_id, remaining, project_ids)
        if nxt is None:
            _safe_notify(_notify_requester_outcome, conn, inst_id, module, employee_id, "approved")
            return "approved", None
        _safe_notify(_notify_step_recipients, conn, inst_id, module, employee_id, nxt, project_ids)
        return "advanced", nxt["step_order"]

    # Flat: every step with a non-empty pool is open simultaneously,
    # regardless of step_order, until each is individually decided.
    decided = _decided_step_orders(conn, request_table, request_id)
    open_steps = [s for s in steps if s["step_order"] not in decided
                  and _step_pool_nonempty(conn, inst_id, module, employee_id, s, project_ids)]
    my_steps = [s for s in open_steps
                if is_eligible_approver(conn, inst_id, module, employee_id, s, acting_user, project_ids)]
    if not my_steps:
        raise PermissionError("You are not an eligible approver for any of this request's open steps")
    decision = "rejected" if action == "reject" else "approved"
    for s in my_steps:
        _record_decision(conn, inst_id, module, request_table, request_id, s["step_order"], decision, acting_user["username"])
    if action == "reject":
        _safe_notify(_notify_requester_outcome, conn, inst_id, module, employee_id, "rejected")
        return "rejected", None
    my_orders = {s["step_order"] for s in my_steps}
    still_open = [s for s in open_steps if s["step_order"] not in my_orders]
    if not still_open:
        _safe_notify(_notify_requester_outcome, conn, inst_id, module, employee_id, "approved")
        return "approved", None
    # No notification here — every still-open step's approver was already
    # told at submission time (flat mode notifies everyone up front), so
    # a partial approve/reject among several open steps has nobody new to
    # tell.
    return "advanced", min(s["step_order"] for s in still_open)


def pending_rows_for_approver(conn, inst_id: int, user: dict, module: str) -> List[Dict[str, Any]]:
    """Which of this module's pending requests are sitting at a step `user`
    is eligible to act on right now — powers the Dashboard To-Do
    integration (see routers/dashboard.py), both the aggregate count
    (count_pending_for_approver below) and the per-item rows it renders
    one To-Do row per (employee, stage, date) rather than just an "N
    pending" count."""
    table = MODULE_TABLE[module]
    statuses = MODULE_PENDING_STATUSES[module]
    placeholders = ",".join("?" * len(statuses))
    rows = list(conn.execute(
        f"SELECT * FROM {table} WHERE institution_id=? AND status IN ({placeholders}) "
        f"AND approval_workflow_id IS NOT NULL AND approval_step IS NOT NULL",
        (inst_id, *statuses)
    ).fetchall())
    project_table = MODULE_PROJECT_TABLE.get(module)
    if project_table:
        rows += list(conn.execute(
            f"SELECT * FROM {project_table} WHERE institution_id=? AND status IN ({placeholders}) "
            f"AND approval_workflow_id IS NOT NULL AND approval_step IS NOT NULL",
            (inst_id, *statuses)
        ).fetchall())
    result = []
    for row in rows:
        workflow_id = row["approval_workflow_id"]
        steps = get_steps(conn, workflow_id)
        employee_id = _requester_employee_id(conn, inst_id, module, row)
        if not employee_id:
            continue
        project_ids = project_ids_for_row(conn, module, row)
        mode = _get_workflow_mode(conn, workflow_id)

        if mode != "flat":
            current = next((s for s in steps if s["step_order"] == row["approval_step"]), None)
            if not current:
                continue
            if is_eligible_approver(conn, inst_id, module, employee_id, current, user, project_ids):
                result.append(row)
            continue

        request_table, request_id = _request_identity_for_row(module, row)
        resolvable = [s for s in steps if _step_pool_nonempty(conn, inst_id, module, employee_id, s, project_ids)]
        decided = _decided_step_orders(conn, request_table, request_id)
        open_steps = [s for s in resolvable if s["step_order"] not in decided]
        if any(is_eligible_approver(conn, inst_id, module, employee_id, s, user, project_ids) for s in open_steps):
            result.append(row)
    return result


def count_pending_for_approver(conn, inst_id: int, user: dict, module: str) -> int:
    """How many of this module's pending requests are sitting at a step
    `user` is eligible to act on right now."""
    return len(pending_rows_for_approver(conn, inst_id, user, module))


def annotate_actionability(conn, inst_id: int, module: str, rows: List[Dict[str, Any]], user: dict) -> List[Dict[str, Any]]:
    """For a list endpoint's already role-scoped rows (e.g. a manager sees
    only their subordinates' requests), tag each row with whether THIS
    user can act on it right now (`is_actionable`) and, if not, who
    currently holds it (`pending_with`) — so a list screen can show every
    in-scope request for visibility/escalation while only offering
    Approve/Reject on the ones actually actionable.

    Was `filter_actionable` (dropped non-actionable rows outright) until a
    request that's already cleared a manager's step and moved on (e.g. to
    HR) — or one sitting at a step the viewer never reaches, like HR
    viewing a request still with the direct manager — simply vanished
    from that viewer's screen instead of showing who it's actually
    waiting on. The eligibility check itself (`is_eligible_approver`) is
    unchanged and still the source of truth the actual approve/reject
    action (`advance_or_finalize`) and the Dashboard's
    `count_pending_for_approver` both rely on — this only changes what a
    list screen does with a "not eligible" result: label it, don't hide
    it.

    A row always gets `is_actionable=True`, `pending_with=None`,
    `approval_progress=None` if it's not at a pending status for this
    module, or has no workflow/step recorded — those carry no action
    buttons anyway, or (a legacy pre-engine row) are gated by that
    module's own blanket role-based fallback instead of this engine, so
    labeling them here would be wrong.

    A flat-mode row (see approval_workflows.mode) additionally gets
    `approval_progress={"decided": N, "total": M}` — how many of its
    resolvable steps have already been individually decided — and
    `pending_with` becomes a comma-joined list of every still-open step's
    description rather than just one, since more than one can be
    actionable at once.
    """
    pending = set(MODULE_PENDING_STATUSES[module])
    for row in rows:
        row["is_actionable"] = True
        row["pending_with"] = None
        row["approval_progress"] = None
        if row["status"] not in pending or row["approval_workflow_id"] is None or row["approval_step"] is None:
            continue
        workflow_id = row["approval_workflow_id"]
        steps = get_steps(conn, workflow_id)
        employee_id = _requester_employee_id(conn, inst_id, module, row)
        if not employee_id:
            continue
        project_ids = project_ids_for_row(conn, module, row)
        mode = _get_workflow_mode(conn, workflow_id)

        if mode != "flat":
            current = next((s for s in steps if s["step_order"] == row["approval_step"]), None)
            if not current:
                continue
            row["is_actionable"] = is_eligible_approver(conn, inst_id, module, employee_id, current, user, project_ids)
            if not row["is_actionable"]:
                row["pending_with"] = describe_current_step(conn, inst_id, employee_id, current, project_ids)
            continue

        request_table, request_id = _request_identity_for_row(module, row)
        resolvable = [s for s in steps if _step_pool_nonempty(conn, inst_id, module, employee_id, s, project_ids)]
        decided = _decided_step_orders(conn, request_table, request_id)
        open_steps = [s for s in resolvable if s["step_order"] not in decided]
        row["approval_progress"] = {"decided": len(resolvable) - len(open_steps), "total": len(resolvable)}
        row["is_actionable"] = any(
            is_eligible_approver(conn, inst_id, module, employee_id, s, user, project_ids) for s in open_steps
        )
        if not row["is_actionable"] and open_steps:
            row["pending_with"] = ", ".join(
                describe_current_step(conn, inst_id, employee_id, s, project_ids) for s in open_steps
            )
    return rows
