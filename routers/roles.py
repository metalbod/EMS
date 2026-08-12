"""Per-institution custom roles — the 6 built-in roles (see
core/roles.py's BUILTIN_ROLES) are fixed; this lets HR add more on top
(e.g. "IT Infra"), usable both as a user's role (routers/users.py) and as
an onboarding/offboarding checklist item's assigned_role
(routers/onboarding.py).
"""
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.roles import BUILTIN_ROLES, LEAVE_MANAGE_ROLES
except ImportError:
    from ems.core.roles import BUILTIN_ROLES, LEAVE_MANAGE_ROLES

try:
    from core.constants import ROLE_LABELS
except ImportError:
    from ems.core.constants import ROLE_LABELS

try:
    from core.permission_matrix import ALL_ROLES, MATRIX, LOCKED_ROLES, ENFORCED_ACTION_KEYS, ACTION_BY_KEY, is_override_eligible, require_permission
except ImportError:
    from ems.core.permission_matrix import ALL_ROLES, MATRIX, LOCKED_ROLES, ENFORCED_ACTION_KEYS, ACTION_BY_KEY, is_override_eligible, require_permission

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

router = APIRouter()

# Same role set that already manages Leave Types / Approval Workflows —
# role management is an HR-configuration concern, not a superadmin-only one.
ROLE_MANAGE_ROLES = LEAVE_MANAGE_ROLES


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug


class RoleIn(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, v):
        if not v.strip():
            raise ValueError("display_name is required")
        return v.strip()


@router.get("/api/roles")
@db_session
def list_roles(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    builtin = [{"id": None, "role_key": r, "display_name": ROLE_LABELS.get(r, r), "is_builtin": True} for r in BUILTIN_ROLES]
    custom_rows = conn.execute(
        "SELECT * FROM custom_roles WHERE institution_id=? ORDER BY display_name", (inst_id,)
    ).fetchall()
    custom = [{"id": r["id"], "role_key": r["role_key"], "display_name": r["display_name"], "is_builtin": False} for r in custom_rows]
    return builtin + custom


def _eligibility_proxy_role(role: str) -> str:
    """Custom roles have no row of their own in MATRIX's static access
    dicts (see permission_matrix.py) — they're synthesized as a copy of
    Employee at request time, so eligibility for a custom role is
    whatever Employee's eligibility is for that action."""
    return role if role in ALL_ROLES else "employee"


@router.get("/api/roles/permission-matrix")
@db_session
def get_permission_matrix(conn, user: dict = Depends(require_roles(*ROLE_MANAGE_ROLES))) -> Dict[str, Any]:
    """Hand-curated "who can do what" reference for the 6 built-in roles
    (see core/permission_matrix.py's module docstring for why this isn't
    derived from the routers at runtime), plus this institution's actual
    custom roles (see create_role below) expanded as their own columns —
    a custom role never unlocks a require_roles(...) gate, so each one's
    default access is just a copy of the Employee column for every
    action, same as before.

    On top of that default, this institution's saved
    role_permission_overrides are applied for whichever (action, role)
    cells are actually enforced (ENFORCED_ACTION_KEYS) — manager/employee/
    custom roles only, never the locked HR/payroll/compensation roles.
    Each action also carries an `editable` map so the frontend knows
    exactly which cells to render as an edit control rather than plain
    text, without re-deriving the eligibility rules itself."""
    inst_id = need_inst(user)
    custom_rows = conn.execute(
        "SELECT role_key, display_name FROM custom_roles WHERE institution_id=? ORDER BY display_name", (inst_id,)
    ).fetchall()
    custom_roles = [{"role_key": r["role_key"], "display_name": r["display_name"]} for r in custom_rows]
    custom_role_keys = [cr["role_key"] for cr in custom_roles]
    all_columns = list(ALL_ROLES) + custom_role_keys

    override_rows = conn.execute(
        "SELECT action_key, role, access_value FROM role_permission_overrides WHERE institution_id=?", (inst_id,)
    ).fetchall()
    overrides = {(r["action_key"], r["role"]): r["access_value"] for r in override_rows}

    modules = []
    for mod in MATRIX:
        actions = []
        for a in mod["actions"]:
            access_default = dict(a["access"])
            for role_key in custom_role_keys:
                access_default[role_key] = access_default.get("employee", "deny")
            access = dict(access_default)
            enforced = a["key"] in ENFORCED_ACTION_KEYS
            editable = {}
            for role in all_columns:
                elig = enforced and role not in LOCKED_ROLES and is_override_eligible(a, _eligibility_proxy_role(role))
                editable[role] = elig
                if elig:
                    override_val = overrides.get((a["key"], role))
                    if override_val:
                        access[role] = override_val
            actions.append({**a, "access": access, "access_default": access_default, "enforced": enforced, "editable": editable})
        modules.append({"module": mod["module"], "actions": actions})

    role_labels = dict(ROLE_LABELS)
    for cr in custom_roles:
        role_labels[cr["role_key"]] = cr["display_name"]

    return {
        "roles": ALL_ROLES,
        "custom_roles": custom_role_keys,
        "role_labels": role_labels,
        "modules": modules,
    }


class PermissionOverrideIn(BaseModel):
    action_key: str
    role: str
    access_value: str

    @field_validator("access_value")
    @classmethod
    def _validate_access_value(cls, v):
        if v not in ("allow", "deny"):
            raise ValueError("access_value must be 'allow' or 'deny'")
        return v


def _validate_overridable(conn, inst_id: int, action_key: str, role: str) -> Dict[str, Any]:
    if role in LOCKED_ROLES:
        raise HTTPException(400, f"'{ROLE_LABELS.get(role, role)}' access is locked and can't be overridden")
    action = ACTION_BY_KEY.get(action_key)
    if not action:
        raise HTTPException(404, "Unknown action")
    if action_key not in ENFORCED_ACTION_KEYS:
        raise HTTPException(400, "This action isn't wired up for overrides yet")
    if role not in ALL_ROLES:
        exists = conn.execute(
            "SELECT 1 FROM custom_roles WHERE institution_id=? AND role_key=?", (inst_id, role)
        ).fetchone()
        if not exists:
            raise HTTPException(400, f"Unknown role '{role}'")
    if not is_override_eligible(action, _eligibility_proxy_role(role)):
        raise HTTPException(400, "This action's default access for this role can't be overridden")
    return action


@router.put("/api/roles/permission-matrix/override")
@db_session
def set_permission_override(conn, body: PermissionOverrideIn, user: dict = Depends(require_roles(*ROLE_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    _validate_overridable(conn, inst_id, body.action_key, body.role)
    conn.execute(
        """INSERT INTO role_permission_overrides (institution_id, action_key, role, access_value, updated_by)
           VALUES (?,?,?,?,?)
           ON CONFLICT (institution_id, action_key, role)
           DO UPDATE SET access_value=EXCLUDED.access_value, updated_by=EXCLUDED.updated_by,
                         updated_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS')""",
        (inst_id, body.action_key, body.role, body.access_value, user["username"])
    )
    conn.commit()
    return {"ok": True}


@router.delete("/api/roles/permission-matrix/override", status_code=204)
@db_session
def reset_permission_override(conn, action_key: str, role: str, user: dict = Depends(require_roles(*ROLE_MANAGE_ROLES))) -> None:
    """Removes the override, reverting that cell to permission_matrix.py's
    hardcoded default — not a way to explicitly set a cell to Deny (use
    the PUT endpoint with access_value='deny' for that)."""
    inst_id = need_inst(user)
    conn.execute(
        "DELETE FROM role_permission_overrides WHERE institution_id=? AND action_key=? AND role=?",
        (inst_id, action_key, role)
    )
    conn.commit()


@router.post("/api/roles", status_code=201)
@db_session
def create_role(conn, body: RoleIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    # Only create/delete are retrofitted here — get_permission_matrix,
    # set_permission_override, and reset_permission_override above stay on
    # their own permanently-hardcoded require_roles(*ROLE_MANAGE_ROLES)
    # gate, never require_permission(). If those three were overridable
    # too, granting a role "manage custom roles" access would also hand
    # it the ability to view/edit the permission matrix and create
    # further overrides — a real escalation chain (grant yourself the
    # power to grant yourself anything). Don't change that.
    require_permission(conn, user, "custom_roles.create_delete_custom_role")
    inst_id = need_inst(user)
    role_key = _slugify(body.display_name)
    if not role_key:
        raise HTTPException(400, "display_name must contain at least one letter or number")
    if role_key in BUILTIN_ROLES or role_key == "superadmin":
        raise HTTPException(400, f"'{role_key}' is a built-in role and can't be added again")
    existing = conn.execute(
        "SELECT id FROM custom_roles WHERE institution_id=? AND role_key=?", (inst_id, role_key)
    ).fetchone()
    if existing:
        raise HTTPException(400, f"A role with key '{role_key}' already exists")
    conn.execute(
        "INSERT INTO custom_roles (institution_id,role_key,display_name) VALUES (?,?,?)",
        (inst_id, role_key, body.display_name)
    )
    role_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    row = conn.execute("SELECT * FROM custom_roles WHERE id=?", (role_id,)).fetchone()
    return {"id": row["id"], "role_key": row["role_key"], "display_name": row["display_name"], "is_builtin": False}


@router.delete("/api/roles/{role_id}", status_code=204)
@db_session
def delete_role(conn, role_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "custom_roles.create_delete_custom_role")
    inst_id = need_inst(user)
    row = conn.execute(
        "SELECT * FROM custom_roles WHERE id=? AND institution_id=?", (role_id, inst_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Role not found")
    role_key = row["role_key"]

    user_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE institution_id=? AND role=?", (inst_id, role_key)
    ).fetchone()[0]
    template_count = conn.execute(
        "SELECT COUNT(*) FROM ob_templates WHERE institution_id=? AND assigned_role=?", (inst_id, role_key)
    ).fetchone()[0]
    item_count = conn.execute(
        "SELECT COUNT(*) FROM ob_checklist_items WHERE institution_id=? AND assigned_role=?", (inst_id, role_key)
    ).fetchone()[0]
    in_use = user_count + template_count + item_count
    if in_use:
        parts = []
        if user_count: parts.append(f"{user_count} user{'s' if user_count != 1 else ''}")
        if template_count: parts.append(f"{template_count} checklist template item{'s' if template_count != 1 else ''}")
        if item_count: parts.append(f"{item_count} in-progress checklist item{'s' if item_count != 1 else ''}")
        raise HTTPException(400, f"Can't delete '{row['display_name']}' — still assigned to {', '.join(parts)}. Reassign them first.")

    conn.execute("DELETE FROM custom_roles WHERE id=?", (role_id,))
    conn.commit()
