"""User management routes."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import get_current_user, hash_password
except ImportError:
    from ems.core.deps import get_current_user, hash_password

try:
    from core.permission_matrix import require_permission
except ImportError:
    from ems.core.permission_matrix import require_permission

try:
    from core.roles import ROLES, get_valid_roles
except ImportError:
    from ems.core.roles import ROLES, get_valid_roles

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()

CAN_MANAGE_USERS = ("superadmin", "hr_manager")


class UserIn(BaseModel):
    username: str
    full_name: str
    email: Optional[str] = None
    password: str
    role: str
    roles: Optional[List[str]] = None  # multi-role list; defaults to [role]
    employee_id: Optional[str] = None
    institution_id: Optional[int] = None  # superadmin can specify

    # role is validated in create_user's body instead of a static
    # field_validator — the valid set is per-institution (built-ins plus
    # that institution's custom_roles, see core/roles.py's
    # get_valid_roles), which needs a DB connection and inst_id neither
    # of which a Pydantic validator has access to.


class UserUpdate(BaseModel):
    full_name: str
    email: Optional[str] = None
    password: Optional[str] = None
    role: str
    roles: Optional[List[str]] = None  # multi-role list
    employee_id: Optional[str] = None
    is_active: bool = True

    # role validated in update_user's body — see UserIn's note above.


@router.get("/api/users")
@db_session
def list_users(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "users.list_create_update_user")
    if user["role"] == "superadmin":
        inst_id = user.get("active_institution_id")
        if inst_id:
            rows = conn.execute(
                "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at,must_change_password "
                "FROM users WHERE institution_id=? ORDER BY created_at DESC", (inst_id,)
            ).fetchall()
        else:
            # Global view — return all non-superadmin users with institution info
            rows = conn.execute("""
                SELECT u.id, u.institution_id, u.username, u.full_name, u.email, u.role, u.roles,
                       u.employee_id, u.is_active, u.created_at, u.must_change_password,
                       i.name AS institution_name, i.code AS institution_code
                FROM users u
                LEFT JOIN institutions i ON i.id = u.institution_id
                ORDER BY u.created_at DESC
            """).fetchall()
    else:
        inst_id = user["institution_id"]
        rows = conn.execute(
            "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at,must_change_password "
            "FROM users WHERE institution_id=? ORDER BY created_at DESC", (inst_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["roles"] = [x.strip() for x in (d.get("roles") or d["role"]).split(",") if x.strip()]
        d["must_change_password"] = bool(d["must_change_password"])
        result.append(d)
    return result


@router.post("/api/users", status_code=201)
@db_session
def create_user(conn, body: UserIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "users.list_create_update_user")
    # Determine which institution this user belongs to
    if user["role"] == "superadmin":
        inst_id = body.institution_id or user.get("active_institution_id")
        if body.role != "superadmin" and inst_id is None:
            raise HTTPException(400, "institution_id is required when creating non-superadmin users")
        if body.role == "superadmin":
            inst_id = None  # platform-level
    else:
        if body.role == "superadmin":
            raise HTTPException(403, "HR Managers cannot create Platform Admin accounts")
        inst_id = user["institution_id"]

    if body.role != "superadmin":
        valid_roles = get_valid_roles(conn, inst_id)
        if body.role not in valid_roles:
            raise HTTPException(400, f"role must be one of: {', '.join(valid_roles)}")

    roles_str = ",".join(body.roles) if body.roles else body.role
    # Force a password change on first login for every role except HR
    # Manager/HR Admin — those two are trusted to pick their own password
    # at creation time (e.g. the initial institution HR Manager account).
    must_change_password = 0 if body.role in ("hr_manager", "hr_admin") else 1
    try:
        conn.execute("""
            INSERT INTO users (institution_id, username, full_name, email, password_hash, role, roles, employee_id, must_change_password)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (inst_id, body.username, body.full_name, body.email,
              hash_password(body.password), body.role, roles_str, body.employee_id, must_change_password))
        conn.commit()
        row = conn.execute(
            "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
            "FROM users WHERE id=last_insert_rowid()"
        ).fetchone()
        return dict(row)
    except IntegrityError:
        conn.rollback()
        raise HTTPException(400, "Username already exists")


@router.put("/api/users/{user_id}")
@db_session
def update_user(conn, user_id: int, body: UserUpdate, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "users.list_create_update_user")
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        raise HTTPException(404, "User not found")
    if user["role"] != "superadmin":
        # Was `if user["role"] == "hr_manager":` — only superadmin should
        # ever be exempt from these three protections (editing a Platform
        # Admin account, assigning the Platform Admin role, managing users
        # outside your own institution). Narrowing it to the literal
        # "hr_manager" string was fine while hr_manager was the only
        # non-superadmin role that could ever reach this endpoint, but the
        # permission-override system (core/permission_matrix.py) can now
        # grant manager/employee/custom-role access to this same action —
        # any of those would have bypassed all three checks entirely under
        # the old literal-role comparison.
        if target["role"] == "superadmin":
            raise HTTPException(403, "Cannot edit Platform Admin")
        if body.role == "superadmin":
            raise HTTPException(403, "Cannot assign Platform Admin role")
        if target["institution_id"] != user["institution_id"]:
            raise HTTPException(403, "Access denied to this user")
    if user_id == user["id"] and body.role != user["role"]:
        raise HTTPException(400, "Cannot change your own role")
    if body.role != "superadmin":
        valid_roles = get_valid_roles(conn, target["institution_id"])
        if body.role not in valid_roles:
            raise HTTPException(400, f"role must be one of: {', '.join(valid_roles)}")
    new_hash = hash_password(body.password) if body.password else target["password_hash"]
    # Any real password change (not just leaving it unset) clears a pending
    # forced-rotation flag — see main.py's superadmin seeding.
    must_change_password = 0 if body.password else target["must_change_password"]
    roles_str = ",".join(body.roles) if body.roles else body.role
    conn.execute("""
        UPDATE users SET full_name=?,email=?,password_hash=?,role=?,roles=?,employee_id=?,is_active=?,must_change_password=?
        WHERE id=?
    """, (body.full_name, body.email, new_hash, body.role, roles_str,
          body.employee_id, 1 if body.is_active else 0, must_change_password, user_id))
    conn.commit()
    row = conn.execute(
        "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
        "FROM users WHERE id=?", (user_id,)
    ).fetchone()
    return dict(row)


@router.delete("/api/users/{user_id}", status_code=204)
@db_session
def delete_user(conn, user_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "users.delete_user")
    if user_id == user["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        raise HTTPException(404, "User not found")
    # Was `if user["role"] == "hr_manager" and ...` — same reasoning as
    # update_user's fix above: only superadmin should be exempt from the
    # institution boundary. This incidentally also blocks any non-superadmin
    # actor from deleting a superadmin account, since superadmin's own
    # institution_id is NULL (never equal to a real institution_id).
    if user["role"] != "superadmin" and target["institution_id"] != user["institution_id"]:
        raise HTTPException(403, "Access denied")
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
