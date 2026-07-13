"""User management routes."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import hash_password, require_roles
except ImportError:
    from ems.core.deps import hash_password, require_roles

try:
    from core.roles import ROLES
except ImportError:
    from ems.core.roles import ROLES

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

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

    @field_validator("role")
    @classmethod
    def val(cls, v):
        if v not in ROLES: raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v


class UserUpdate(BaseModel):
    full_name: str
    email: Optional[str] = None
    password: Optional[str] = None
    role: str
    roles: Optional[List[str]] = None  # multi-role list
    employee_id: Optional[str] = None
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def val(cls, v):
        if v not in ROLES: raise ValueError(f"Role must be one of: {', '.join(ROLES)}")
        return v


@router.get("/api/users")
def list_users(user: dict = Depends(require_roles(*CAN_MANAGE_USERS))):
    conn = get_db()
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
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["roles"] = [x.strip() for x in (d.get("roles") or d["role"]).split(",") if x.strip()]
        d["must_change_password"] = bool(d["must_change_password"])
        result.append(d)
    return result


@router.post("/api/users", status_code=201)
def create_user(body: UserIn, user: dict = Depends(require_roles(*CAN_MANAGE_USERS))):
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

    roles_str = ",".join(body.roles) if body.roles else body.role
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (institution_id, username, full_name, email, password_hash, role, roles, employee_id)
            VALUES (?,?,?,?,?,?,?,?)
        """, (inst_id, body.username, body.full_name, body.email,
              hash_password(body.password), body.role, roles_str, body.employee_id))
        conn.commit()
        row = conn.execute(
            "SELECT id,institution_id,username,full_name,email,role,roles,employee_id,is_active,created_at "
            "FROM users WHERE username=?", (body.username,)
        ).fetchone()
        return dict(row)
    except IntegrityError:
        conn.rollback(); raise HTTPException(400, "Username already exists")
    finally:
        conn.close()


@router.put("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, user: dict = Depends(require_roles(*CAN_MANAGE_USERS))):
    conn = get_db()
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target: conn.close(); raise HTTPException(404, "User not found")
    if user["role"] == "hr_manager":
        if target["role"] == "superadmin": conn.close(); raise HTTPException(403, "Cannot edit Platform Admin")
        if body.role == "superadmin":      conn.close(); raise HTTPException(403, "Cannot assign Platform Admin role")
        if target["institution_id"] != user["institution_id"]:
            conn.close(); raise HTTPException(403, "Access denied to this user")
    if user_id == user["id"] and body.role != user["role"]:
        conn.close(); raise HTTPException(400, "Cannot change your own role")
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
    conn.close()
    return dict(row)


@router.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, user: dict = Depends(require_roles("superadmin", "hr_manager"))):
    if user_id == user["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    conn = get_db()
    target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target: conn.close(); raise HTTPException(404, "User not found")
    if user["role"] == "hr_manager" and target["institution_id"] != user["institution_id"]:
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
