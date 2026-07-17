"""HR Notes (confidential, institution-scoped)."""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from core.deps import need_inst, require_roles
except ImportError:
    from ems.core.deps import need_inst, require_roles

try:
    from db import get_db
except ImportError:
    from ems.db import get_db
try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()

HR_NOTE_ROLES = ["superadmin", "hr_manager", "hr_admin"]


class NoteIn(BaseModel):
    note_type: str = "general"
    body: str


@router.get("/api/employees/{employee_id}/notes")
@db_session
def get_notes(conn, employee_id: str, user: dict = Depends(require_roles(*HR_NOTE_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT id,note_type,body,created_by,created_at FROM hr_notes "
        "WHERE institution_id=? AND employee_id=? AND deleted=0 ORDER BY created_at DESC",
        (inst_id, employee_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/employees/{employee_id}/notes", status_code=201)
@db_session
def create_note(conn, employee_id: str, note: NoteIn, user: dict = Depends(require_roles(*HR_NOTE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute(
        "SELECT id FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, employee_id)
    ).fetchone():
        raise HTTPException(404, "Employee not found")
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?,?,?,?,?)",
        (inst_id, employee_id, note.note_type, note.body.strip(), user["username"])
    )
    conn.commit()
    return {"ok": True}


@router.delete("/api/employees/{employee_id}/notes/{note_id}", status_code=204)
@db_session
def delete_note(conn, employee_id: str, note_id: int,
                user: dict = Depends(require_roles("superadmin", "hr_manager"))) -> None:
    inst_id = need_inst(user)
    conn.execute(
        "UPDATE hr_notes SET deleted=1 WHERE id=? AND institution_id=? AND employee_id=?",
        (note_id, inst_id, employee_id)
    )
    conn.commit()
