"""Institution CRUD routes (superadmin only)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import hash_password, require_roles
except ImportError:
    from ems.core.deps import hash_password, require_roles

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

try:
    from core.onboarding_seed import seed_ob_templates
    from core.validators import validate_logo_url
except ImportError:
    from ems.core.onboarding_seed import seed_ob_templates
    from ems.core.validators import validate_logo_url

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
def list_institutions(conn, user: dict = Depends(require_roles("superadmin"))):
    rows = conn.execute("""
        SELECT i.*,
               COUNT(DISTINCT e.id)  AS employee_count,
               COUNT(DISTINCT u.id)  AS user_count
        FROM   institutions i
        LEFT JOIN employees e ON e.institution_id = i.id
        LEFT JOIN users     u ON u.institution_id = i.id
        GROUP BY i.id
        ORDER BY i.created_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/institutions", status_code=201)
@db_session
def create_institution(conn, body: InstitutionIn, user: dict = Depends(require_roles("superadmin"))):
    try:
        code = body.code.upper()
        if conn.execute("SELECT id FROM institutions WHERE code=?", (code,)).fetchone():
            raise HTTPException(400, "Institution code already exists")
        if conn.execute("SELECT id FROM users WHERE username=?", (body.admin_username,)).fetchone():
            raise HTTPException(400, "Admin username already taken")
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
def get_institution(conn, inst_id: int, user: dict = Depends(require_roles("superadmin"))):
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
def update_institution(conn, inst_id: int, body: InstitutionUpdate, user: dict = Depends(require_roles("superadmin"))):
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
def toggle_inst_status(conn, inst_id: int, body: InstStatusIn, user: dict = Depends(require_roles("superadmin"))):
    if body.status not in ("Active", "Suspended"):
        raise HTTPException(400, "Status must be Active or Suspended")
    conn.execute("UPDATE institutions SET status=? WHERE id=?", (body.status, inst_id))
    conn.commit()
    row = conn.execute("SELECT * FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return dict(row)
