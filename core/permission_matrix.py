"""Curated documentation of "who can do what" across the app, powering
Settings -> Roles -> Permission Matrix (routers/roles.py's
GET /api/roles/permission-matrix).

This is hand-maintained, not derived from the routers at runtime — most
role gates in this codebase are inline `if user["role"] not in (...)`
checks in a function body, not a single uniform decorator, so reliable
generic introspection isn't practical. That means this file can drift
from the actual code if a router's role gate changes and this file isn't
updated alongside it — keep it in sync when you touch a require_roles(...)
call, a *_MANAGE_ROLES constant, or an inline role check in routers/.

Cell values (ACCESS.*) are deliberately richer than a plain allow/deny
boolean, because a lot of real gates in this app aren't flat role lists:

- ALLOW / DENY        — a flat require_roles(...)-style check.
- OWN                 — only the record's own employee (e.g. an employee
                         viewing their own payslip, own timesheet).
- SUBORDINATE         — a manager acting on their reporting chain, via
                         subordinates_in_clause (core/org_queries.py).
- CONFIGURABLE        — resolved at runtime by the approval-workflow
                         engine (core/approval_workflow.py): the actual
                         approver depends on this institution's configured
                         steps (direct/skip-level manager, Project
                         Manager, or a fallback HR role), not a fixed
                         role. The roles shown here are that engine's
                         built-in HR-role fallback only.
- NO_RESTRICTION      — any authenticated user in the institution, no
                         role check at all (flagged deliberately where
                         this is the case, e.g. locations today).

Per-institution custom roles (e.g. "IT Infra" — see routers/roles.py) are
NOT in this file at all, since they don't exist until an institution
creates one. GET /api/roles/permission-matrix expands them into their own
columns at request time, each one a straight copy of the Employee column
— custom roles never unlock a require_roles(...) gate, they only ever
function as an assignable `role`/`assigned_role` value, so they behave
like `employee` for every action in this table.

---
Overridable access (role_permission_overrides table, see routers/roles.py)
---
hr_manager/hr_admin/payroll_manager/compensation_manager are permanently
locked (LOCKED_ROLES) — an institution can never loosen or tighten what
those roles can do from the UI, only manager/employee/custom roles.
Within that, only a row whose default access for the target role is
ALLOW or DENY is override-eligible at all — OWN/SUBORDINATE/CONFIGURABLE/
NO_RESTRICTION rows stay fixed, since "allow" doesn't mean anything for a
relationship-based or approval-workflow-resolved check without also
rewriting that check's own logic, not just a flag.

Even within "override-eligible", an override only actually changes
behavior for actions whose endpoint has been retrofitted to call
has_permission() below instead of its old hardcoded require_roles(...) —
see ENFORCED_ACTION_KEYS. Rows outside that set still show as
theoretically overridable in the data model (so the UI/API don't need a
second, separate notion of "editable"), but routers/roles.py's override
endpoint rejects writes to a non-enforced action_key, and the frontend is
expected to only offer editing controls where enforced=True comes back
from the API — this is a deliberately incremental rollout (see
ENFORCED_ACTION_KEYS's own comment), not a one-shot rewrite of every
router's access control.
"""
from typing import Any, Dict, List

ALL_ROLES = ["hr_manager", "hr_admin", "manager", "payroll_manager", "compensation_manager", "employee"]

ALLOW = "allow"
DENY = "deny"
OWN = "own"
SUBORDINATE = "subordinate"
CONFIGURABLE = "configurable"
NO_RESTRICTION = "no_restriction"

# Never overridable, regardless of action — see module docstring.
LOCKED_ROLES = frozenset({"hr_manager", "hr_admin", "payroll_manager", "compensation_manager"})


def _flat(*allowed: str) -> Dict[str, str]:
    """Every role not listed gets DENY — the common case, matching a
    plain require_roles(*allowed) / *_MANAGE_ROLES gate."""
    return {r: (ALLOW if r in allowed else DENY) for r in ALL_ROLES}


def _with(base: Dict[str, str], **overrides: str) -> Dict[str, str]:
    """A flat base with one or two roles overridden to OWN/SUBORDINATE/etc
    — for the OR-of-relationship-and-role gates (e.g. payslip: own record
    OR PAYROLL_VIEW_ROLES)."""
    out = dict(base)
    out.update(overrides)
    return out


def _no_restriction() -> Dict[str, str]:
    return {r: NO_RESTRICTION for r in ALL_ROLES}


def _action(action: str, path: str, access: Dict[str, str], note: str = None) -> Dict[str, Any]:
    return {
        "action": action,
        "path": path,
        "access": access,
        "note": note,
    }


# Reused flat sets, named after the constants they mirror in the code —
# see each router's own module docstring/comment for the reasoning behind
# exactly which roles are in each.
_LEAVE_MANAGE = ("superadmin", "hr_manager", "hr_admin")          # core/roles.py LEAVE_MANAGE_ROLES
_PAYROLL_VIEW = ("payroll_manager", "hr_manager")                  # core/roles.py PAYROLL_VIEW_ROLES
_PAYROLL_MANAGE = ("payroll_manager",)                              # routers/payroll.py PAYROLL_MANAGE_ROLES
_EMPLOYEE_WRITE = ("superadmin", "hr_manager", "hr_admin")          # routers/employees.py CAN_WRITE
_EMPLOYEE_TOGGLE = ("superadmin", "hr_manager")                     # routers/employees.py CAN_TOGGLE
_BULK_UPLOAD = ("hr_manager",)                                      # routers/employees.py BULK_UPLOAD_ROLES
_OB_MANAGE = ("superadmin", "hr_manager", "hr_admin")               # routers/onboarding.py OB_MANAGE_ROLES
_RECRUIT_WRITE = ("superadmin", "hr_manager", "hr_admin")           # routers/recruitment.py RECRUIT_WRITE
_BENEFITS = ("superadmin", "hr_manager", "payroll_manager", "compensation_manager")  # require_benefits_role — no hr_admin
_BENEFITS_DEPENDENTS = ("superadmin", "hr_manager", "hr_admin")     # require_dependents_manage_role
_BENEFITS_DASHBOARD = ("superadmin", "hr_manager", "compensation_manager", "manager")  # require_benefits_dashboard_role
_COMP_HR = ("superadmin", "hr_manager", "payroll_manager", "compensation_manager")  # compensation_helpers.require_hr_role — no hr_admin
_ATTENDANCE_MANAGE = ("superadmin", "hr_manager", "hr_admin")       # require_attendance_manage_role
_PERFORMANCE_MANAGE = ("hr_manager",)                                # PERFORMANCE_MANAGE_ROLES — no superadmin, no hr_admin
_LD_MANAGE = ("superadmin", "hr_manager", "hr_admin")                # LD_MANAGE_ROLES
_PROJECT_MANAGE = ("superadmin", "hr_manager")                       # PROJECT_MANAGE_ROLES — no hr_admin
_ROLE_MANAGE = ("superadmin", "hr_manager", "hr_admin")              # routers/roles.py ROLE_MANAGE_ROLES
_USER_MANAGE = ("superadmin", "hr_manager")                          # CAN_MANAGE_USERS
_NOTIFICATION_MANAGE = ("hr_manager", "hr_admin")                    # NOTIFICATION_MANAGE_ROLES — no superadmin
_HR_NOTE_READ = ("superadmin", "hr_manager", "hr_admin")             # HR_NOTE_ROLES
_HR_NOTE_DELETE = ("superadmin", "hr_manager")                       # narrower than read/create


MATRIX: List[Dict[str, Any]] = [
    {
        "module": "Employees",
        "actions": [
            _action("List employees", "GET /api/employees", _with(_flat(*ALL_ROLES), manager=SUBORDINATE, employee=OWN),
                     note="Manager sees their reporting chain only; employee sees only themselves."),
            _action("View employee record", "GET /api/employees/{id}", _with(_flat(*_EMPLOYEE_WRITE, "manager", "payroll_manager", "compensation_manager"), manager=SUBORDINATE, employee=OWN)),
            _action("Create employee", "POST /api/employees", _flat(*_EMPLOYEE_WRITE)),
            _action("Edit employee", "PUT /api/employees/{id}", _flat(*_EMPLOYEE_WRITE),
                     note="Some sensitive fields are further restricted to hr_manager only."),
            _action("Activate / deactivate employee", "PATCH /api/employees/{id}/status", _flat(*_EMPLOYEE_TOGGLE)),
            _action("Download bulk-upload template", "GET /api/employees/bulk-template", _flat(*_BULK_UPLOAD)),
            _action("Bulk-upload employees", "POST /api/employees/bulk-upload", _flat(*_BULK_UPLOAD)),
            _action("Rehire prefill", "GET /api/employees/{id}/rehire-prefill", _flat(*_EMPLOYEE_WRITE)),
        ],
    },
    {
        "module": "Org Chart",
        "actions": [
            _action("View org chart", "GET /api/org-chart", _no_restriction(), note="Any authenticated user in the institution; scoped by RLS to their own tenant only."),
        ],
    },
    {
        "module": "Leave",
        "actions": [
            _action("View leave types", "GET /api/leave/types", _no_restriction()),
            _action("Manage leave types", "POST/PUT/DELETE /api/leave/types", _flat(*_LEAVE_MANAGE)),
            _action("View leave balances", "GET /api/leave/balances", _no_restriction(), note="Scoped inline: self / subordinates / all, by role."),
            _action("Adjust leave balance", "PATCH /api/leave/balances/{id}", _flat(*_LEAVE_MANAGE)),
            _action("Apply for leave", "POST /api/leave/applications", _no_restriction(), note="Self-serve; any authenticated employee applies for their own leave."),
            _action("View leave applications", "GET /api/leave/applications", _with(_flat(*ALL_ROLES), manager=SUBORDINATE, employee=OWN)),
            _action("Approve / reject leave application", "PATCH /api/leave/applications/{id}/status", _flat("hr_manager", "hr_admin"),
                     note=CONFIGURABLE + " — actual approver resolved by this institution's configured approval-workflow steps (direct/skip-level manager, Project Manager, or the HR fallback shown here). See Settings > Approval Workflows."),
            _action("Leave utilization dashboard", "GET /api/leave/dashboard/utilization", _flat("hr_manager", "hr_admin")),
            _action("View leave audit history", "GET /api/employees/{id}/leave-history", _flat(*_LEAVE_MANAGE)),
            _action("Manage public holidays", "POST/DELETE /api/holidays", _flat(*_LEAVE_MANAGE)),
        ],
    },
    {
        "module": "Timesheets",
        "actions": [
            _action("View timesheets", "GET /api/timesheets", _with(_flat(*ALL_ROLES), manager=SUBORDINATE, employee=OWN)),
            _action("Start / edit own timesheet", "POST /api/timesheets, POST .../entries", _no_restriction(), note="Self-serve; employee acts on their own timesheet only."),
            _action("Submit timesheet", "PATCH /api/timesheets/{id}/status (submit)", _no_restriction(), note="Self-serve submission by the timesheet's own employee."),
            _action("Approve / reject timesheet", "PATCH /api/timesheets/{id}/status (approve/reject)", _flat("hr_manager", "hr_admin"),
                     note=CONFIGURABLE + " — resolved by the approval-workflow engine, same mechanism as Leave."),
        ],
    },
    {
        "module": "Overtime",
        "actions": [
            _action("View overtime settings", "GET /api/overtime/settings", _no_restriction()),
            _action("Configure overtime settings", "PUT /api/overtime/settings", _flat(*_LEAVE_MANAGE)),
            _action("View overtime records", "GET /api/overtime", _no_restriction(), note="Scoped inline by role."),
            _action("Approve / reject overtime", "PATCH /api/overtime/{id}/status", _flat("hr_manager", "hr_admin"),
                     note=CONFIGURABLE + " — resolved by the approval-workflow engine."),
        ],
    },
    {
        "module": "Approval Workflows",
        "actions": [
            _action("Manage approval workflows & steps", "routers/approval_workflow_settings.py (all)", _flat(*_LEAVE_MANAGE),
                     note="Configures the per-institution approver chain that every CONFIGURABLE row in this table refers to."),
        ],
    },
    {
        "module": "Onboarding / Offboarding",
        "actions": [
            _action("Manage template sets & templates", "routers/onboarding.py template/set CRUD", _flat(*_OB_MANAGE)),
            _action("Start / delete checklist", "POST/DELETE /api/ob/checklists", _flat(*_OB_MANAGE)),
            _action("View checklist", "GET /api/ob/checklists/{id}", _no_restriction(), note="Visible to the assigned employee and anyone whose role matches an item's assigned_role."),
            _action("Complete / update checklist item", "PATCH /api/ob/checklists/{id}/items/{item_id}", _no_restriction(),
                     note="Allowed only if the acting user's role matches that item's assigned_role (can be a custom role) — not a fixed list."),
            _action("Add / edit / delete checklist item (HR)", "POST/PUT/DELETE /api/ob/checklists/{id}/items[/{item_id}]", _flat(*_OB_MANAGE),
                     note="HR editing a live checklist's items directly — distinct from completing an assigned item, and from editing a template."),
            _action("Attach / view / delete item proof file", "routers/onboarding.py attachment endpoints", _no_restriction(), note="Same assigned_role match as completing the item."),
            _action("View onboarding/offboarding history", "GET /api/employees/{id}/ob-history", _flat(*_OB_MANAGE)),
        ],
    },
    {
        "module": "Recruitment",
        "actions": [
            _action("View requisitions / candidates / interviews / offers", "GET endpoints", _no_restriction()),
            _action("Create / edit requisition, candidate, interview, offer", "POST/PUT endpoints", _flat(*_RECRUIT_WRITE)),
            _action("Approve requisition", "POST /api/recruitment/requisitions/{id}/approve", _flat("hr_manager"),
                     note=CONFIGURABLE + " — approval-workflow engine; HR fallback here is hr_manager only (narrower than most other modules, no hr_admin)."),
            _action("View candidate audit log", "GET /api/recruitment/candidates/{id}/audit", _flat(*_RECRUIT_WRITE)),
            _action("View candidate stage timing", "GET /api/recruitment/candidates/{id}/stage-history", _flat(*_RECRUIT_WRITE, "manager"),
                     note="Deliberately broader than the audit log above — manager included so a hiring manager can see how long their own candidates have sat in each stage."),
        ],
    },
    {
        "module": "Benefits",
        "actions": [
            _action("Manage benefit plans, eligibility, enrollment periods", "routers/benefits.py plan/eligibility CRUD", _flat(*_BENEFITS),
                     note="No hr_admin — deliberately narrower than most other 'manage' sets."),
            _action("Decide life events, auto-enroll, view compliance report", "routers/benefits.py", _flat(*_BENEFITS)),
            _action("View / elect own enrollment", "GET/POST .../enrollments/mine", _no_restriction(), note="Self-serve."),
            _action("Manage employee dependents (HR side)", "routers/benefits.py dependents CRUD", _flat(*_BENEFITS_DEPENDENTS)),
            _action("Attach / detach dependent to enrollment", "routers/benefits.py", _with(_flat(*_BENEFITS), employee=OWN),
                     note="OR gate: the enrollment's own employee, or a Benefits-role user."),
            _action("List / decide claims", "GET/PATCH /api/benefits/claims", _with(_flat(*_BENEFITS), manager=SUBORDINATE),
                     note="Manager sees/decides subordinates' claims via the approval-workflow engine; Benefits-role users see all."),
            _action("View reports dashboard", "GET /api/benefits/reports/dashboard", _flat(*_BENEFITS_DASHBOARD),
                     note="Widest of the Benefits gates — includes plain manager, read-only."),
        ],
    },
    {
        "module": "Payroll",
        "actions": [
            _action("View payroll runs", "GET /api/payroll/runs", _flat(*_PAYROLL_VIEW)),
            _action("Create / finalize / delete payroll run", "POST/PATCH/DELETE /api/payroll/runs", _flat(*_PAYROLL_MANAGE),
                     note="payroll_manager only — hr_manager can view runs but not manage them."),
            _action("Adjust / recompute payslip", "PUT/PATCH /api/payroll/payslips/{id}", _flat(*_PAYROLL_MANAGE)),
            _action("Export bank CSV", "GET /api/payroll/runs/{id}/bank-csv", _flat(*_PAYROLL_MANAGE)),
            _action("View own payslips", "GET /api/payroll/payslips/mine", _no_restriction()),
            _action("View a specific payslip", "GET /api/payroll/payslips/{id}", _with(_flat(*_PAYROLL_VIEW), employee=OWN),
                     note="OR gate: the payslip's own employee, or payroll_manager/hr_manager."),
        ],
    },
    {
        "module": "Compensation",
        "actions": [
            _action("Manage pay grades, job levels/roles", "compensation_pay_structure.py", _flat(*_COMP_HR), note="No hr_admin."),
            _action("Set employee compensation, record salary changes", "compensation_pay_structure.py", _flat(*_COMP_HR)),
            _action("Manage bonus plans & payouts", "compensation_bonus.py", _flat(*_COMP_HR)),
            _action("Manage commission plans & entries", "compensation_commission.py", _flat(*_COMP_HR)),
            _action("Manage equity grants & vesting", "compensation_equity.py", _flat(*_COMP_HR)),
            _action("Manage merit cycles & recommendations", "compensation_merit.py", _flat(*_COMP_HR)),
            _action("View own total rewards", "GET /api/compensation/total-rewards/mine", _no_restriction()),
            _action("View someone's total rewards / pay equity report", "compensation_rewards.py", _flat(*_COMP_HR),
                     note="Verify against source before relying on this row — not fully confirmed during research."),
        ],
    },
    {
        "module": "Attendance",
        "actions": [
            _action("Clock in / out, view own attendance", "POST /api/attendance/clock-in|out, GET .../mine", _no_restriction()),
            _action("Manage shifts, assignments, settings", "routers/attendance.py", _flat(*_ATTENDANCE_MANAGE)),
            _action("Review queue / resolve attendance record", "routers/attendance.py", _flat(*_ATTENDANCE_MANAGE)),
            _action("Manage attendance devices", "routers/attendance.py", _flat(*_ATTENDANCE_MANAGE)),
            _action("Device webhook (clock event)", "POST /api/attendance/webhook/clock-event", _no_restriction(),
                     note="Not user-role gated at all — authenticated via a per-device API key, not a user session."),
        ],
    },
    {
        "module": "Performance",
        "actions": [
            _action("Manage performance cycles (create/activate/calibrate)", "routers/performance.py", _flat(*_PERFORMANCE_MANAGE),
                     note="hr_manager only — no superadmin, no hr_admin. Confirm this is intentional; inconsistent with every other 'manage' set in the app."),
            _action("Set goals / self-review / manager-review", "routers/performance.py", _no_restriction(), note="Inline self/manager checks in the endpoint body."),
            _action("Merit increment, queue/cancel bonus payout", "routers/performance.py", _flat(*_PERFORMANCE_MANAGE)),
            _action("List bonus payouts", "GET /api/performance/payouts", _flat("hr_manager", "payroll_manager")),
        ],
    },
    {
        "module": "Learning & Development",
        "actions": [
            _action("Manage courses & quizzes", "routers/ld.py", _flat(*_LD_MANAGE)),
            _action("View L&D history for an employee", "GET /api/employees/{id}/ld-history", _flat(*_LD_MANAGE)),
            _action("Enroll / take quiz / view own progress", "routers/ld.py", _no_restriction(), note="Self-serve."),
            _action("Approve / reject enrollment", "PATCH /api/ld/enrollments/{id}/status", _flat("hr_manager", "hr_admin"),
                     note=CONFIGURABLE + " — approval-workflow engine."),
        ],
    },
    {
        "module": "Projects & Tasks",
        "actions": [
            _action("Manage projects, tasks, assignments", "routers/projects.py", _flat(*_PROJECT_MANAGE), note="No hr_admin."),
            _action("Utilization report", "GET /api/projects/utilization", _flat(*_PROJECT_MANAGE)),
            _action("View my projects / project tasks / assignments", "GET endpoints", _no_restriction(), note="Scoped to the caller's own assignments."),
            _action("Get task by id", "GET /api/tasks/{id}", _flat("employee", "hr_manager", "hr_admin", "payroll_manager", "superadmin"),
                     note="Unusually broad allow-list, missing only manager and compensation_manager — confirm intentional."),
        ],
    },
    {
        "module": "Locations",
        "actions": [
            _action("Create / edit / delete locations, assignments, budgets, transfers", "locations.py, location_features.py, location_phase2.py", _no_restriction(),
                     note="No role gate at all today — any authenticated in-tenant user, including plain employee, can write here. Worth a separate decision on whether to restrict this."),
        ],
    },
    {
        "module": "Custom Roles",
        "actions": [
            _action("List roles", "GET /api/roles", _no_restriction()),
            _action("Create / delete custom role", "POST/DELETE /api/roles", _flat(*_ROLE_MANAGE)),
        ],
    },
    {
        "module": "Users",
        "actions": [
            _action("List / create / update user", "routers/users.py", _flat(*_USER_MANAGE),
                     note="hr_manager is also blocked from assigning the superadmin role, and from managing users outside their own institution — extra checks beyond this flat gate."),
            _action("Delete user", "DELETE /api/users/{id}", _flat(*_USER_MANAGE)),
        ],
    },
    {
        "module": "Institutions (platform)",
        "actions": [
            _action("List / create / update / toggle institutions", "routers/institutions.py", _flat("superadmin")),
        ],
    },
    {
        "module": "Notifications",
        "actions": [
            _action("Manage institution notification banners", "routers/notifications.py", _flat(*_NOTIFICATION_MANAGE), note="No superadmin in this gate."),
            _action("Manage system-wide (platform) notifications", "routers/notifications.py /system-notifications*", _flat("superadmin")),
            _action("View active notifications", "GET .../active", _no_restriction()),
        ],
    },
    {
        "module": "Audit Log",
        "actions": [
            _action("View institution audit log", "GET /api/audit-logs", _flat("superadmin", "hr_manager")),
        ],
    },
    {
        "module": "HR Notes",
        "actions": [
            _action("View / create HR note", "routers/hr_notes.py", _flat(*_HR_NOTE_READ)),
            _action("Delete HR note", "DELETE /api/hr-notes/{id}", _flat(*_HR_NOTE_DELETE), note="Narrower than view/create — excludes hr_admin."),
        ],
    },
    {
        "module": "Dashboard",
        "actions": [
            _action("View personal To-Do dashboard", "GET /api/todos", _no_restriction(),
                     note="Every role sees a different, personally-scoped set of items (own/subordinates'/institution-wide, plus assigned_role matches for onboarding items) — not a flat allow/deny."),
        ],
    },
]


# ---------------------------------------------------------------------------
# Stable per-action keys + lookup, assigned here (not hand-written per
# _action() call) so adding/reordering a row can never silently collide or
# renumber an existing key that role_permission_overrides rows reference.
# ---------------------------------------------------------------------------
def _slugify(text: str) -> str:
    import re
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


ACTION_BY_KEY: Dict[str, Dict[str, Any]] = {}
for _mod in MATRIX:
    _mod_slug = _slugify(_mod["module"])
    for _a in _mod["actions"]:
        _key = f"{_mod_slug}.{_slugify(_a['action'])}"
        assert _key not in ACTION_BY_KEY, f"duplicate permission_matrix key: {_key}"
        _a["key"] = _key
        _a["module"] = _mod["module"]
        ACTION_BY_KEY[_key] = _a


# Action keys actually retrofitted to call has_permission() below instead
# of their old hardcoded require_roles(...) — i.e. where a
# role_permission_overrides row genuinely changes behavior, not just the
# matrix's own display. Deliberately starts as a small pilot (Employees
# module's flat-gated actions — see routers/employees.py) rather than
# every override-eligible row in the file; expand this set only as each
# router is actually retrofitted, in a follow-up change, not by adding
# keys here speculatively ahead of the code.
ENFORCED_ACTION_KEYS = frozenset({
    "employees.create_employee",
    "employees.edit_employee",
    "employees.activate_deactivate_employee",
    "employees.download_bulk_upload_template",
    "employees.bulk_upload_employees",
    "employees.rehire_prefill",
    "leave.manage_leave_types",
    "leave.adjust_leave_balance",
    "leave.view_leave_audit_history",
    "leave.manage_public_holidays",
    # NOT leave.leave_utilization_dashboard — its default access dict
    # (built with _flat("hr_manager","hr_admin")) looks override-eligible
    # structurally, but a dedicated test
    # (test_leave_utilization_dashboard_superadmin_denied) confirms
    # excluding superadmin from it is deliberate, not an oversight. Every
    # other row in this set is safe to feed through require_permission()'s
    # standard "superadmin always passes" rule; this one specifically
    # is not, so it stays on its own explicit require_roles(...) gate in
    # routers/leave.py instead of being retrofitted.
    #
    # NOT leave.approve_reject_leave_application — despite having a flat
    # ALLOW/DENY access dict like the rows above (is_override_eligible
    # would say yes), that row's real gate is the approval-workflow
    # engine (core/approval_workflow.py), not require_roles(...). Adding
    # it here would let someone "grant" a role approval rights that the
    # engine would still ignore — never add a CONFIGURABLE-noted action
    # to this set no matter what its access dict looks like structurally.
    "onboarding_offboarding.manage_template_sets_templates",
    "onboarding_offboarding.start_delete_checklist",
    "onboarding_offboarding.add_edit_delete_checklist_item_hr",
    "onboarding_offboarding.view_onboarding_offboarding_history",
    # NOT onboarding_offboarding.view_checklist,
    # complete_update_checklist_item, or attach_view_delete_item_proof_file
    # — all three are assigned_role-matched (NO_RESTRICTION at the role
    # level; the real gate is per-item, checked in the endpoint body via
    # _can_act_on_item), not a flat role list at all.
    "learning_development.manage_courses_quizzes",
    "learning_development.view_l_d_history_for_an_employee",
    # NOT learning_development.approve_reject_enrollment — approval-workflow
    # engine, same reasoning as every other *.approve_reject_* key.
    "attendance.manage_shifts_assignments_settings",
    "attendance.review_queue_resolve_attendance_record",
    "attendance.manage_attendance_devices",
    # NOT attendance.clock_in_out_view_own_attendance or
    # attendance.device_webhook_clock_event — both NO_RESTRICTION (self-serve
    # / device-API-key auth respectively), not a flat role list.
    "hr_notes.view_create_hr_note",
    "hr_notes.delete_hr_note",
    "approval_workflows.manage_approval_workflows_steps",
    "custom_roles.create_delete_custom_role",
    # NOT any Settings > Roles > Permission Matrix management action itself
    # (viewing the matrix, setting/resetting an override) — those stay
    # permanently hardcoded to ROLE_MANAGE_ROLES in routers/roles.py,
    # completely outside this override system. If they were overridable,
    # granting a role "manage custom roles" would also hand it the power
    # to grant itself anything else in the app — a real escalation chain.
    "audit_log.view_institution_audit_log",
    "users.list_create_update_user",
    "users.delete_user",
    # Retrofitting these required first fixing a real bug in
    # routers/users.py: update_user's and delete_user's extra protections
    # (can't edit/assign the Platform Admin role, can't touch a user
    # outside your own institution) were gated on the literal string
    # user["role"] == "hr_manager", not "any non-superadmin actor" — a
    # role newly granted this action via an override would have bypassed
    # all of them. Generalized to `!= "superadmin"` before adding these keys.
    "projects_tasks.manage_projects_tasks_assignments",
    "projects_tasks.utilization_report",
    # NOT projects_tasks.view_my_projects_project_tasks_assignments —
    # NO_RESTRICTION, self-scoped, nothing to enforce.
    # NOT projects_tasks.get_task_by_id — pre-existing note flags this row's
    # access dict as suspiciously broad ("missing only manager and
    # compensation_manager, confirm intentional") and it doesn't correspond
    # to any route in routers/projects.py; leaving untouched rather than
    # enforcing a gate nobody has verified is correct.
    "recruitment.create_edit_requisition_candidate_interview_offer",
    "recruitment.view_candidate_audit_log",
    # NOT recruitment.view_requisitions_candidates_interviews_offers —
    # NO_RESTRICTION at the matrix level (though several of the underlying
    # GET endpoints, e.g. list_offers/get_offer, are actually gated the
    # same as the write action today — a pre-existing doc/reality mismatch,
    # not something introduced or fixed by this retrofit).
    # NOT recruitment.approve_requisition — approval-workflow engine, same
    # reasoning as every other *.approve_reject_*/approve_* key; its inline
    # fallback (`if user["role"] not in ("superadmin","hr_manager")`) stays
    # hardcoded in routers/recruitment.py's approve_requisition, untouched.
    #
    # NOT any Payroll action (routers/payroll.py) — PAYROLL_MANAGE_ROLES is
    # ("payroll_manager",) and PAYROLL_VIEW_ROLES is ("payroll_manager",
    # "hr_manager"): both deliberately exclude superadmin (same pattern
    # confirmed intentional for leave.leave_utilization_dashboard above).
    # has_permission()/require_permission() always grant superadmin first,
    # by design, so every other retrofitted module works correctly for it —
    # but that means retrofitting Payroll would silently hand superadmin
    # payroll management/view access it doesn't have today, a real
    # escalation rather than just "making the matrix editable". Deliberately
    # left permanently out of scope for this override system, like
    # Institutions and system-wide Notifications — routers/payroll.py keeps
    # its own hardcoded require_roles(...) gates untouched.
    "compensation.manage_pay_grades_job_levels_roles",
    "compensation.set_employee_compensation_record_salary_changes",
    "compensation.manage_bonus_plans_payouts",
    "compensation.manage_commission_plans_entries",
    "compensation.manage_equity_grants_vesting",
    "compensation.manage_merit_cycles_recommendations",
    "compensation.view_someone_s_total_rewards_pay_equity_report",
    # NOT compensation.view_own_total_rewards — NO_RESTRICTION, self-scoped.
    # _COMP_HR (core/compensation_helpers.py's require_hr_role) includes
    # superadmin, unlike Payroll's role tuples above, so this module doesn't
    # have that same escalation problem.
    "benefits.manage_benefit_plans_eligibility_enrollment_periods",
    "benefits.decide_life_events_auto_enroll_view_compliance_report",
    "benefits.manage_employee_dependents_hr_side",
    "benefits.view_reports_dashboard",
    # NOT benefits.view_elect_own_enrollment — NO_RESTRICTION, self-scoped.
    # NOT benefits.attach_detach_dependent_to_enrollment — true OR gate at
    # runtime (an inline `is_hr = role in [...]` literal-list check ORed
    # with "is this the caller's own enrollment"), not a 1:1 flat-role swap
    # like the other rows here. has_permission()/require_permission() only
    # model flat per-role allow/deny, not an OR against a hardcoded
    # is_hr check — retrofitting would require restructuring that check to
    # also consult the override table, which is a bigger change than this
    # pass is scoped for. update_dependent (PUT /api/benefits/dependents/
    # {id}, the same is_self-OR-HR pattern) has the same issue and is
    # likewise left on its current hardcoded gate.
    # NOT benefits.list_decide_claims — same reasoning as leave/recruitment/
    # L&D's approve_reject_* keys: a manager's path here is the
    # approval-workflow engine (SUBORDINATE scoping in list_claims,
    # advance_or_finalize in decide_claim), and the HR fallback branch in
    # each stays on its hardcoded require_benefits_role call. Two adjacent,
    # matrix-undocumented endpoints in this same claims lifecycle
    # (submit_employee_claim, mark_claim_paid) are left untouched for
    # consistency, rather than making some claims actions overridable and
    # others not.
    #
    # Also left untouched, pre-existing gaps in this matrix's Benefits rows
    # rather than something this pass introduced: list_employee_enrollments
    # and elect_employee_enrollment (GET/POST /api/benefits/employees/{id}/
    # enrollments, HR acting on an employee's enrollment — no matching row;
    # "View/elect own enrollment" only covers the self-service /mine
    # endpoints). Not retrofitted rather than guessed onto a mismatched key.
    #
    # NOT institution-level Notifications (routers/notifications.py's
    # "Manage institution notification banners", NOTIFICATION_MANAGE_ROLES =
    # ("hr_manager", "hr_admin")) — same escalation problem as Payroll
    # above: this gate deliberately excludes superadmin (matrix row already
    # carries the note "No superadmin in this gate"), and
    # has_permission()/require_permission() always grant superadmin first.
    # Retrofitting would silently hand superadmin banner-management access
    # it doesn't have today. Confirmed with the project owner to leave this
    # permanently out of scope, same as Payroll, Institutions, and
    # system-wide (platform) Notifications.
})


# Every module named in MATRIX with zero keys in ENFORCED_ACTION_KEYS, and
# why — kept as data, not prose, so test_permission_matrix_consistency can
# actually verify the claim "every module has either been retrofitted or
# has a documented reason for staying on its own hardcoded gate" instead of
# it just being an assertion in a comment nobody re-checks. That's exactly
# how this went stale before: an earlier version of this file claimed
# retrofit-or-documented coverage was complete while Performance, Overtime,
# and Timesheets were silently neither — caught 2026-08-18 by an
# architecture review, not by anything that would have failed a test.
#
# The reasons below are NOT interchangeable — some are permanent
# (retrofitting would change who has access), others are just "not reached
# yet" (retrofitting is behavior-neutral whenever it happens). Keep that
# distinction when adding an entry here.
NOT_YET_ENFORCED_MODULES: Dict[str, str] = {
    "Payroll": (
        "PAYROLL_MANAGE_ROLES/PAYROLL_VIEW_ROLES deliberately exclude "
        "superadmin; has_permission()/require_permission() always grant "
        "superadmin first, so retrofitting would silently escalate "
        "superadmin's access. Confirmed with the project owner to leave "
        "permanently out of scope."
    ),
    "Institutions (platform)": (
        "Cross-tenant, superadmin-only by design — not part of the "
        "per-institution override system at all."
    ),
    "Notifications": (
        "Institution-level notification management (NOTIFICATION_MANAGE_ROLES "
        "= (\"hr_manager\", \"hr_admin\")) excludes superadmin, same "
        "escalation risk as Payroll; platform-wide notifications are "
        "superadmin-only like Institutions. Confirmed with the project "
        "owner to leave permanently out of scope."
    ),
    "Performance": (
        "PERFORMANCE_MANAGE_ROLES = (\"hr_manager\",) excludes superadmin — "
        "same escalation risk as Payroll (retrofitting would silently grant "
        "superadmin merit-increment/bonus-payout access it doesn't have "
        "today). Flagged and confirmed with the project owner (2026-08-18) "
        "to leave out of scope for now — unlike Payroll this isn't "
        "necessarily permanent, revisit if there's a reason to reconsider."
    ),
    "Overtime": (
        "Not yet retrofitted — no escalation risk if/when it is: "
        "OVERTIME_SETTINGS_ROLES already includes superadmin, so this one "
        "just hasn't been reached yet, unlike Payroll/Performance above."
    ),
    "Timesheets": (
        "Not yet retrofitted — no escalation risk if/when it is: its "
        "inline role checks already include superadmin, so this one just "
        "hasn't been reached yet, unlike Payroll/Performance above."
    ),
}


def is_override_eligible(action: Dict[str, Any], role: str) -> bool:
    if role in LOCKED_ROLES:
        return False
    return action["access"].get(role) in (ALLOW, DENY)


def has_permission(conn, inst_id: int, user: dict, action_key: str) -> bool:
    """The enforcement half of the override system — call this from a
    retrofitted endpoint instead of checking user["role"] against a fixed
    tuple. Superadmin always passes, matching every existing require_roles(...)
    call in this codebase that lists it explicitly. Falls back to this
    file's hardcoded default the moment anything is ambiguous (unknown
    action_key, locked role, non-flat access type, no override row) —
    never fails open."""
    role = user["role"]
    if role == "superadmin":
        return True
    action = ACTION_BY_KEY.get(action_key)
    if not action:
        return False
    default = action["access"].get(role, DENY)
    if not is_override_eligible(action, role):
        return default == ALLOW
    row = conn.execute(
        "SELECT access_value FROM role_permission_overrides WHERE institution_id=? AND action_key=? AND role=?",
        (inst_id, action_key, role)
    ).fetchone()
    return (row["access_value"] if row else default) == ALLOW


def require_permission(conn, user: dict, action_key: str) -> None:
    """403-raising convenience wrapper around has_permission() for
    retrofitted endpoints — needs need_inst/HTTPException imported lazily
    to avoid this core/ module depending on FastAPI or core/deps for
    every caller that only wants the plain boolean check.

    Checks the superadmin bypass BEFORE calling need_inst(), not after —
    some endpoints (e.g. routers/users.py's list_users) have a legitimate
    superadmin-with-no-institution-selected code path (a global,
    cross-institution view). Calling need_inst() unconditionally would
    401/400 that case even though has_permission() would have granted it
    anyway, since superadmin always passes regardless of institution
    context."""
    if user["role"] == "superadmin":
        return
    from fastapi import HTTPException
    from core.deps import need_inst
    inst_id = need_inst(user)
    if not has_permission(conn, inst_id, user, action_key):
        raise HTTPException(403, "Insufficient permissions")
