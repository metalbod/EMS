"""Role-group constants shared across multiple routers/modules that main.py hasn't split out yet."""
ROLES = ["superadmin", "hr_manager", "hr_admin", "manager", "payroll_manager", "compensation_manager", "employee"]
LEAVE_MANAGE_ROLES = ("superadmin", "hr_manager", "hr_admin")
PAYROLL_VIEW_ROLES = ("payroll_manager", "hr_manager")

# The 6 must-have roles every institution has, fixed and non-deletable —
# see routers/roles.py for the per-institution custom_roles an institution
# can add on top (e.g. "IT Infra"), which get_valid_roles below folds in.
# Kept separate from ROLES above (which also includes the platform-only
# "superadmin", never assignable via an institution's own role management).
BUILTIN_ROLES = ["hr_manager", "hr_admin", "manager", "payroll_manager", "compensation_manager", "employee"]


def get_valid_roles(conn, inst_id) -> list:
    """BUILTIN_ROLES plus this institution's custom_roles — the full set of
    role values assignable to a user's primary role or an onboarding/
    offboarding item's assigned_role. Role validation for both moved out
    of static Pydantic field_validators (which can't see the DB) into the
    endpoint bodies that call this, once inst_id is known."""
    if not inst_id:
        return list(BUILTIN_ROLES)
    rows = conn.execute(
        "SELECT role_key FROM custom_roles WHERE institution_id=? ORDER BY role_key", (inst_id,)
    ).fetchall()
    return list(BUILTIN_ROLES) + [r["role_key"] for r in rows]
