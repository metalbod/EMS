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


@router.post("/api/roles", status_code=201)
@db_session
def create_role(conn, body: RoleIn, user: dict = Depends(require_roles(*ROLE_MANAGE_ROLES))) -> Dict[str, Any]:
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
def delete_role(conn, role_id: int, user: dict = Depends(require_roles(*ROLE_MANAGE_ROLES))) -> None:
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
