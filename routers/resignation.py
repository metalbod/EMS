"""Employee Resignation: filed by the employee (self-service) or by HR on
the employee's behalf, routed through its own configurable approval
workflow (module='resignation' — see core/approval_workflow.py). On
final approval, core/resignation.py's _finalize_resignation stamps the
employee's resign_date/last_working_day and auto-starts an Offboarding
checklist from the institution's default template.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst

from core.org_queries import subordinates_in_clause

from core.validators import validate_document_data_url

from core.approval_workflow import advance_or_finalize, filter_actionable

from core.resignation import file_resignation, apply_resignation_outcome

from db import get_db

from core.db_session import db_session

router = APIRouter()

RESIGNATION_ON_BEHALF_ROLES = ("superadmin", "hr_manager", "hr_admin")


class ResignationAttachmentIn(BaseModel):
    file_name: str
    mime_type: str
    data_url: str  # data:...;base64 URI — same pattern as ob_item_attachments/candidate_documents

    @field_validator("data_url")
    @classmethod
    def _validate_data_url(cls, v):
        v = validate_document_data_url(v)
        if not v:
            raise ValueError("data_url is required")
        return v


class ResignationIn(BaseModel):
    employee_id: Optional[str] = None  # omitted = self-service (the caller's own record)
    reason: str
    effective_date: str
    last_working_day: str
    attachment: Optional[ResignationAttachmentIn] = None

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, v):
        if not v or not v.strip():
            raise ValueError("reason is required")
        return v.strip()


class ResignationDecisionIn(BaseModel):
    status: str  # Approved | Rejected | Withdrawn
    notes: Optional[str] = None


@router.post("/api/resignations", status_code=201)
@db_session
def create_resignation(conn, body: ResignationIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.employee_id:
        if user["role"] not in RESIGNATION_ON_BEHALF_ROLES:
            raise HTTPException(403, "Only HR can file a resignation on someone else's behalf")
        employee_id = body.employee_id
    else:
        employee_id = user.get("employee_id")
        if not employee_id:
            raise HTTPException(400, "No employee record linked to your account")

    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                       (employee_id, inst_id)).fetchone()
    if not emp:
        raise HTTPException(404, "Employee not found")
    if body.last_working_day < body.effective_date:
        raise HTTPException(400, "Last working day cannot be before the effective date")

    existing = conn.execute(
        "SELECT id FROM resignation_requests WHERE employee_id=? AND institution_id=? AND status='Pending'",
        (employee_id, inst_id)
    ).fetchone()
    if existing:
        raise HTTPException(400, "This employee already has a pending resignation request")

    attachment = body.attachment.model_dump() if body.attachment else None
    request_id = file_resignation(conn, inst_id, emp, body.reason, body.effective_date, body.last_working_day,
                                  attachment, user["username"])
    row = conn.execute("SELECT * FROM resignation_requests WHERE id=?", (request_id,)).fetchone()
    return dict(row)


@router.get("/api/resignations")
@db_session
def list_resignations(conn, status: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = """
        SELECT r.*, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name,
               e.department, e.designation
        FROM resignation_requests r
        JOIN employees e ON e.employee_id = r.employee_id AND e.institution_id = r.institution_id
        WHERE r.institution_id=?
    """
    p: list = [inst_id]
    if status: q += " AND r.status=?"; p.append(status)
    if user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND r.employee_id=?"; p.append(user.get("employee_id", ""))
    q += " ORDER BY r.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    result = [dict(r) for r in rows]
    if user["role"] != "employee":
        result = filter_actionable(conn, inst_id, "resignation", result, user)
    return result


@router.patch("/api/resignations/{request_id}")
@db_session
def update_resignation_status(conn, request_id: int, body: ResignationDecisionIn,
                              user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    valid = ("Approved", "Rejected", "Withdrawn")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    request_row = conn.execute("SELECT * FROM resignation_requests WHERE id=? AND institution_id=?",
                               (request_id, inst_id)).fetchone()
    if not request_row:
        raise HTTPException(404, "Resignation request not found")

    if body.status in ("Approved", "Rejected"):
        if request_row["status"] != "Pending":
            raise HTTPException(400, f"Request is already {request_row['status']}")
        action = "reject" if body.status == "Rejected" else "approve"
        try:
            outcome, next_step = advance_or_finalize(
                conn, inst_id, "resignation", request_row["employee_id"],
                request_row["approval_workflow_id"], request_row["approval_step"], action, user
            )
        except PermissionError as e:
            raise HTTPException(403, str(e))

        if outcome == "advanced":
            conn.execute("UPDATE resignation_requests SET approval_step=?,notes=? WHERE id=?",
                         (next_step, body.notes, request_id))
            conn.commit()
            return dict(conn.execute("SELECT * FROM resignation_requests WHERE id=?", (request_id,)).fetchone())

        if body.notes:
            conn.execute("UPDATE resignation_requests SET notes=? WHERE id=?", (body.notes, request_id))
        apply_resignation_outcome(conn, inst_id, request_row, outcome, user)
    elif body.status == "Withdrawn":
        if user["role"] == "employee" and user.get("employee_id") != request_row["employee_id"]:
            raise HTTPException(403, "Access denied")
        if request_row["status"] != "Pending":
            raise HTTPException(400, f"Request is already {request_row['status']}")
        conn.execute(
            "UPDATE resignation_requests SET status='Withdrawn',approval_step=NULL,decided_by=?,decided_at=?,notes=? WHERE id=?",
            (user["username"], datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), body.notes, request_id)
        )
        conn.commit()

    return dict(conn.execute("SELECT * FROM resignation_requests WHERE id=?", (request_id,)).fetchone())
