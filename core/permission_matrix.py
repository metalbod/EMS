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
"""
from typing import Any, Dict, List

ALL_ROLES = ["hr_manager", "hr_admin", "manager", "payroll_manager", "compensation_manager", "employee"]

ALLOW = "allow"
DENY = "deny"
OWN = "own"
SUBORDINATE = "subordinate"
CONFIGURABLE = "configurable"
NO_RESTRICTION = "no_restriction"


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
            _action("Attach / view / delete item proof file", "routers/onboarding.py attachment endpoints", _no_restriction(), note="Same assigned_role match as completing the item."),
            _action("View onboarding/offboarding history", "GET /api/ob/history", _flat(*_OB_MANAGE)),
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
            _action("View L&D history for an employee", "GET /api/ld/employees/{id}/history", _flat(*_LD_MANAGE)),
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
