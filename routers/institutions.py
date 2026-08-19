"""Institution CRUD routes (superadmin only)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import hash_password, require_roles

from db import get_db, IntegrityError

from core.db_session import db_session

from core.onboarding_seed import seed_ob_templates
from core.validators import validate_logo_url

router = APIRouter()


class InstitutionIn(BaseModel):
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    plan: str = "starter"
    max_employees: int = 50
    logo_url: Optional[str] = None
    admin_username: str
    admin_full_name: str
    admin_password: str
    admin_email: Optional[str] = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v):
        return validate_logo_url(v)


class InstitutionUpdate(BaseModel):
    name: str
    contact_name: Optional[str] = None
    contact_email: str
    phone: Optional[str] = None
    address: Optional[str] = None
    plan: str = "starter"
    max_employees: int = 50
    logo_url: Optional[str] = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, v):
        return validate_logo_url(v)


class InstStatusIn(BaseModel):
    status: str


@router.get("/api/institutions")
@db_session
def list_institutions(conn, user: dict = Depends(require_roles("superadmin"))) -> List[Dict[str, Any]]:
    # Correlated subqueries instead of LEFT JOIN + COUNT(DISTINCT) — the
    # join fan-out (every employee row paired with every user row per
    # institution before GROUP BY collapses it) made this take ~7s across
    # 1300+ institutions; subqueries avoid the cross product entirely.
    rows = conn.execute("""
        SELECT i.*,
               (SELECT COUNT(*) FROM employees e WHERE e.institution_id = i.id) AS employee_count,
               (SELECT COUNT(*) FROM users u WHERE u.institution_id = i.id) AS user_count
        FROM institutions i
        ORDER BY i.created_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/admin/active-users")
@db_session
def get_active_users(conn, minutes: int = 5, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    """Who currently holds a live session, approximated from last_active (refreshed
    on every authenticated request in core/deps.py, throttled to ~once/minute per
    user) since JWT auth is stateless and issued tokens aren't tracked anywhere —
    there's no way to enumerate "logged in" directly, only "active recently."
    Meant for superadmin to check before server maintenance/shutdown."""
    minutes = max(1, min(minutes, 1440))
    rows = conn.execute("""
        SELECT u.username, u.full_name, u.role, u.last_login, u.last_active,
               i.name AS institution_name, i.code AS institution_code
        FROM users u
        LEFT JOIN institutions i ON i.id = u.institution_id
        WHERE u.is_active = 1 AND u.last_active IS NOT NULL
          AND u.last_active >= to_char((NOW() AT TIME ZONE 'UTC') - make_interval(mins => ?), 'YYYY-MM-DD HH24:MI:SS')
        ORDER BY u.last_active DESC
    """, (minutes,)).fetchall()
    total_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0]
    return {
        "window_minutes": minutes,
        "active_count": len(rows),
        "total_users": total_users,
        "active_users": [dict(r) for r in rows],
    }


@router.post("/api/institutions", status_code=201)
@db_session
def create_institution(conn, body: InstitutionIn, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    try:
        code = body.code.upper()
        if conn.execute("SELECT id FROM institutions WHERE code=?", (code,)).fetchone():
            raise HTTPException(400, "Institution code already exists")
        # No admin_username pre-check here: usernames are only unique within
        # an institution (see 20260803_0001), and inst_id below is always a
        # brand-new institution, so a collision is structurally impossible.
        conn.execute("""
            INSERT INTO institutions (name, code, contact_name, contact_email, phone, address, plan, max_employees, logo_url)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (body.name, code, body.contact_name, body.contact_email,
              body.phone, body.address, body.plan, body.max_employees, body.logo_url))
        inst_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO users (institution_id, username, full_name, email, password_hash, role)
            VALUES (?,?,?,?,?,'hr_manager')
        """, (inst_id, body.admin_username, body.admin_full_name,
              body.admin_email, hash_password(body.admin_password)))
        seed_ob_templates(conn, inst_id)
        conn.commit()
        row = conn.execute("""
            SELECT i.*, 0 AS employee_count, 1 AS user_count
            FROM institutions i WHERE i.id=?
        """, (inst_id,)).fetchone()
        return dict(row)
    except IntegrityError as e:
        conn.rollback()
        raise HTTPException(400, str(e))


@router.get("/api/institutions/{inst_id}")
@db_session
def get_institution(conn, inst_id: int, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    row = conn.execute("""
        SELECT i.*,
               COUNT(DISTINCT e.id) AS employee_count,
               COUNT(DISTINCT u.id) AS user_count
        FROM institutions i
        LEFT JOIN employees e ON e.institution_id = i.id
        LEFT JOIN users     u ON u.institution_id = i.id
        WHERE i.id=? GROUP BY i.id
    """, (inst_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Institution not found")
    return dict(row)


@router.put("/api/institutions/{inst_id}")
@db_session
def update_institution(conn, inst_id: int, body: InstitutionUpdate, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    if not conn.execute("SELECT id FROM institutions WHERE id=?", (inst_id,)).fetchone():
        raise HTTPException(404, "Institution not found")
    conn.execute("""
        UPDATE institutions SET name=?,contact_name=?,contact_email=?,phone=?,address=?,plan=?,max_employees=?,logo_url=?
        WHERE id=?
    """, (body.name, body.contact_name, body.contact_email, body.phone,
          body.address, body.plan, body.max_employees, body.logo_url, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return dict(row)


@router.patch("/api/institutions/{inst_id}/status")
@db_session
def toggle_inst_status(conn, inst_id: int, body: InstStatusIn, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    if body.status not in ("Active", "Suspended"):
        raise HTTPException(400, "Status must be Active or Suspended")
    conn.execute("UPDATE institutions SET status=? WHERE id=?", (body.status, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return dict(row)
