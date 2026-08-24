"""Employee document compliance reminders: HR-configurable document types
(e.g. Work Permit, Passport — each with its own reminder-window-in-days)
and per-employee tracked instances (e.g. this employee's Work Permit
expires on this date). HR-only end to end.

No cron job computes "expiring soon" — status is computed fresh on every
read via SQL CURRENT_DATE comparisons (STATUS_CASE_SQL below), reused
verbatim by the per-employee documents list, the Dashboard To-Do count
(routers/dashboard.py), and the Dashboard monthly Leave Calendar's
document-expiry chips (GET /api/employee-documents/calendar) — matching
this project's "no cron jobs, compute lazily on read" rule.
"""
import calendar
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst, require_roles

from core.audit import write_audit

from core.validators import validate_document_data_url

from db import get_db, IntegrityError

from core.db_session import db_session

router = APIRouter()

# This feature is HR-only end to end, including the Dashboard aggregate —
# every endpoint here uses this same gate, deliberately narrower than
# employees.py's CAN_WRITE (which also allows superadmin).
_HR_ROLES = ("hr_manager", "hr_admin")

# Boundary semantics: 'overdue' = strictly past; 'expiring_soon' = today
# through exactly the type's reminder_window_days out, inclusive; 'ok' =
# beyond that. CURRENT_DATE + edt.reminder_window_days relies on Postgres'
# date + integer = date (adds days) — no string concat/interval cast
# needed. Reused verbatim wherever "is this expiring" is asked, so the
# boundary can't drift between call sites.
STATUS_CASE_SQL = """
    CASE
        WHEN ed.expiry_date::date < CURRENT_DATE THEN 'overdue'
        WHEN ed.expiry_date::date <= CURRENT_DATE + edt.reminder_window_days THEN 'expiring_soon'
        ELSE 'ok'
    END
"""
DAYS_UNTIL_SQL = "(ed.expiry_date::date - CURRENT_DATE)"


class EmployeeDocumentTypeIn(BaseModel):
    name: str
    reminder_window_days: int = 30
    is_active: bool = True

    @field_validator("reminder_window_days")
    @classmethod
    def _validate_window(cls, v):
        if v < 1:
            raise ValueError("reminder_window_days must be at least 1")
        return v


class EmployeeDocumentIn(BaseModel):
    document_type_id: int
    document_number: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: str
    notes: Optional[str] = None
    attachment_file_name: Optional[str] = None
    attachment_mime_type: Optional[str] = None
    attachment_data_url: Optional[str] = None

    @field_validator("attachment_data_url")
    @classmethod
    def _validate_attachment(cls, v):
        return validate_document_data_url(v)


# ---------------------------------------------------------------------------
# Document Types (institution-configurable, like leave_types)
# ---------------------------------------------------------------------------
@router.get("/api/employee-document-types")
@db_session
def list_document_types(conn, user: dict = Depends(require_roles(*_HR_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM employee_document_types WHERE institution_id=? AND is_active=1 ORDER BY name", (inst_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/employee-document-types", status_code=201)
@db_session
def create_document_type(conn, body: EmployeeDocumentTypeIn, user: dict = Depends(require_roles(*_HR_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    conn.execute(
        "INSERT INTO employee_document_types (institution_id,name,reminder_window_days,is_active) VALUES (?,?,?,?)",
        (inst_id, body.name, body.reminder_window_days, 1 if body.is_active else 0)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM employee_document_types WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/employee-document-types/{type_id}")
@db_session
def update_document_type(conn, type_id: int, body: EmployeeDocumentTypeIn, user: dict = Depends(require_roles(*_HR_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM employee_document_types WHERE id=? AND institution_id=?", (type_id, inst_id)).fetchone():
        raise HTTPException(404, "Document type not found")
    conn.execute(
        "UPDATE employee_document_types SET name=?,reminder_window_days=?,is_active=? WHERE id=?",
        (body.name, body.reminder_window_days, 1 if body.is_active else 0, type_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM employee_document_types WHERE id=?", (type_id,)).fetchone()
    return dict(row)


@router.delete("/api/employee-document-types/{type_id}", status_code=204)
@db_session
def delete_document_type(conn, type_id: int, user: dict = Depends(require_roles(*_HR_ROLES))) -> None:
    inst_id = need_inst(user)
    conn.execute("UPDATE employee_document_types SET is_active=0 WHERE id=? AND institution_id=?", (type_id, inst_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Per-employee tracked documents
# ---------------------------------------------------------------------------
def _get_employee_or_404(conn, inst_id: int, employee_id: str):
    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                        (employee_id, inst_id)).fetchone()
    if not emp:
        raise HTTPException(404, "Employee not found")
    return emp


@router.get("/api/employees/{employee_id}/documents")
@db_session
def list_employee_documents(conn, employee_id: str, user: dict = Depends(require_roles(*_HR_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    _get_employee_or_404(conn, inst_id, employee_id)
    rows = conn.execute(f"""
        SELECT ed.*, edt.name AS document_type_name, edt.reminder_window_days,
               {STATUS_CASE_SQL} AS status, {DAYS_UNTIL_SQL} AS days_until_expiry
        FROM employee_documents ed
        JOIN employee_document_types edt ON edt.id = ed.document_type_id
        WHERE ed.institution_id=? AND ed.employee_id=?
        ORDER BY ed.expiry_date ASC
    """, (inst_id, employee_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/employees/{employee_id}/documents", status_code=201)
@db_session
def add_employee_document(conn, employee_id: str, body: EmployeeDocumentIn, user: dict = Depends(require_roles(*_HR_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    emp = _get_employee_or_404(conn, inst_id, employee_id)
    doc_type = conn.execute("SELECT * FROM employee_document_types WHERE id=? AND institution_id=? AND is_active=1",
                             (body.document_type_id, inst_id)).fetchone()
    if not doc_type:
        raise HTTPException(404, "Document type not found")
    try:
        conn.execute(
            "INSERT INTO employee_documents (institution_id,employee_id,document_type_id,document_number,issue_date,"
            "expiry_date,notes,attachment_file_name,attachment_mime_type,attachment_data_url,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (inst_id, employee_id, body.document_type_id, body.document_number, body.issue_date,
             body.expiry_date, body.notes, body.attachment_file_name, body.attachment_mime_type,
             body.attachment_data_url, user["username"])
        )
        conn.commit()
    except IntegrityError:
        raise HTTPException(400, f"'{doc_type['name']}' is already tracked for this employee — edit the existing record to renew it")
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    write_audit(conn, user, inst_id, employee_id, emp["full_name"], "DOCUMENT_ADDED",
                {"document_type": doc_type["name"], "expiry_date": body.expiry_date})
    conn.commit()
    row = conn.execute(f"""
        SELECT ed.*, edt.name AS document_type_name, edt.reminder_window_days,
               {STATUS_CASE_SQL} AS status, {DAYS_UNTIL_SQL} AS days_until_expiry
        FROM employee_documents ed JOIN employee_document_types edt ON edt.id = ed.document_type_id
        WHERE ed.id=?
    """, (doc_id,)).fetchone()
    return dict(row)


@router.put("/api/employees/{employee_id}/documents/{doc_id}")
@db_session
def update_employee_document(conn, employee_id: str, doc_id: int, body: EmployeeDocumentIn, user: dict = Depends(require_roles(*_HR_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    emp = _get_employee_or_404(conn, inst_id, employee_id)
    existing = conn.execute("SELECT * FROM employee_documents WHERE id=? AND institution_id=? AND employee_id=?",
                             (doc_id, inst_id, employee_id)).fetchone()
    if not existing:
        raise HTTPException(404, "Document not found")
    doc_type = conn.execute("SELECT * FROM employee_document_types WHERE id=? AND institution_id=?",
                             (body.document_type_id, inst_id)).fetchone()
    if not doc_type:
        raise HTTPException(404, "Document type not found")
    try:
        conn.execute(
            "UPDATE employee_documents SET document_type_id=?,document_number=?,issue_date=?,expiry_date=?,notes=?,"
            "attachment_file_name=?,attachment_mime_type=?,attachment_data_url=?,updated_by=? WHERE id=?",
            (body.document_type_id, body.document_number, body.issue_date, body.expiry_date, body.notes,
             body.attachment_file_name, body.attachment_mime_type, body.attachment_data_url, user["username"], doc_id)
        )
        conn.commit()
    except IntegrityError:
        raise HTTPException(400, f"'{doc_type['name']}' is already tracked for this employee")
    write_audit(conn, user, inst_id, employee_id, emp["full_name"], "DOCUMENT_UPDATED",
                {"document_type": doc_type["name"], "expiry_date": body.expiry_date})
    conn.commit()
    row = conn.execute(f"""
        SELECT ed.*, edt.name AS document_type_name, edt.reminder_window_days,
               {STATUS_CASE_SQL} AS status, {DAYS_UNTIL_SQL} AS days_until_expiry
        FROM employee_documents ed JOIN employee_document_types edt ON edt.id = ed.document_type_id
        WHERE ed.id=?
    """, (doc_id,)).fetchone()
    return dict(row)


@router.delete("/api/employees/{employee_id}/documents/{doc_id}", status_code=204)
@db_session
def delete_employee_document(conn, employee_id: str, doc_id: int, user: dict = Depends(require_roles(*_HR_ROLES))) -> None:
    inst_id = need_inst(user)
    emp = _get_employee_or_404(conn, inst_id, employee_id)
    existing = conn.execute("SELECT * FROM employee_documents WHERE id=? AND institution_id=? AND employee_id=?",
                             (doc_id, inst_id, employee_id)).fetchone()
    if not existing:
        raise HTTPException(404, "Document not found")
    doc_type = conn.execute("SELECT name FROM employee_document_types WHERE id=?", (existing["document_type_id"],)).fetchone()
    conn.execute("DELETE FROM employee_documents WHERE id=?", (doc_id,))
    write_audit(conn, user, inst_id, employee_id, emp["full_name"], "DOCUMENT_REMOVED",
                {"document_type": doc_type["name"] if doc_type else None})
    conn.commit()


# ---------------------------------------------------------------------------
# Dashboard monthly Leave Calendar integration
# ---------------------------------------------------------------------------
@router.get("/api/employee-documents/calendar")
@db_session
def get_document_expiry_calendar(conn, year: int, month: int, user: dict = Depends(require_roles(*_HR_ROLES))) -> List[Dict[str, Any]]:
    """Every tracked document whose expiry_date falls within the given
    month, institution-wide — mirrors routers/leave.py's get_leave_calendar
    shape for the Dashboard monthly calendar to merge in alongside leave/
    holidays/onboarding items. Not filtered by status/window — shows the
    raw dated event like leave/holidays do; urgency is conveyed by the
    frontend coloring the chip from each row's own `status`."""
    inst_id = need_inst(user)
    if not (1 <= month <= 12):
        raise HTTPException(400, "month must be between 1 and 12")
    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1).isoformat()
    month_end = date(year, month, last_day).isoformat()

    rows = conn.execute(f"""
        SELECT ed.employee_id, e.full_name, e.preferred_name, ed.expiry_date,
               edt.name AS document_type_name, {STATUS_CASE_SQL} AS status
        FROM employee_documents ed
        JOIN employee_document_types edt ON edt.id = ed.document_type_id
        JOIN employees e ON e.employee_id = ed.employee_id AND e.institution_id = ed.institution_id
        WHERE ed.institution_id=? AND ed.expiry_date BETWEEN ? AND ?
        ORDER BY ed.expiry_date
    """, (inst_id, month_start, month_end)).fetchall()
    return [dict(r) for r in rows]
