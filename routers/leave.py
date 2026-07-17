"""Leave module: Types, Balances, and Applications (institution-scoped)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.roles import LEAVE_MANAGE_ROLES
except ImportError:
    from ems.core.roles import LEAVE_MANAGE_ROLES

try:
    from core.org_queries import subordinates_in_clause
except ImportError:
    from ems.core.org_queries import subordinates_in_clause

try:
    from core.validators import validate_logo_url
except ImportError:
    from ems.core.validators import validate_logo_url

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()


class LeaveTypeIn(BaseModel):
    name: str
    annual_entitlement: float = 14.0
    requires_approval: bool = True
    requires_attachment: bool = False
    is_paid: bool = True
    is_active: bool = True


class LeaveBalanceAdjustIn(BaseModel):
    entitled_days: Optional[float] = None
    carried_forward_days: Optional[float] = None


class LeaveApplicationIn(BaseModel):
    employee_id: str
    leave_type_id: int
    start_date: str
    end_date: str
    reason: Optional[str] = None
    attachment: Optional[str] = None  # data:... URI, same pattern as institution logo

    @field_validator("attachment")
    @classmethod
    def validate_attachment(cls, v):
        return validate_logo_url(v)  # reuses the data:-URI + size-cap validator


class LeaveStatusIn(BaseModel):
    status: str  # Approved | Rejected | Cancelled
    notes: Optional[str] = None


def _log_leave(conn, inst_id: int, app_id: int, emp_id: str,
               action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO leave_audit_log
           (institution_id,application_id,employee_id,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?)""",
        (inst_id, app_id, emp_id, action, detail, user["username"], user["role"])
    )


def _compute_leave_days(conn, inst_id: int, start_date: str, end_date: str) -> float:
    """Counts weekdays (Mon-Fri) in the inclusive range, excluding institution public holidays."""
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    if d1 < d0:
        raise HTTPException(400, "End date must be on or after start date")
    holiday_rows = conn.execute(
        "SELECT date FROM holidays WHERE institution_id=? AND date BETWEEN ? AND ?",
        (inst_id, start_date, end_date)
    ).fetchall()
    holiday_dates = {r["date"] for r in holiday_rows}
    count = 0
    d = d0
    while d <= d1:
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and ds not in holiday_dates:
            count += 1
        d += timedelta(days=1)
    return float(count)


def _get_or_create_leave_balance(conn, inst_id: int, employee_id: str, leave_type_id: int, year: int):
    row = conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()
    if row:
        return row
    lt = conn.execute("SELECT * FROM leave_types WHERE id=? AND institution_id=?", (leave_type_id, inst_id)).fetchone()
    entitled = lt["annual_entitlement"] if lt else 0
    conn.execute(
        "INSERT INTO leave_balances (institution_id,employee_id,leave_type_id,year,entitled_days,carried_forward_days,used_days) VALUES (?,?,?,?,?,0,0)",
        (inst_id, employee_id, leave_type_id, year, entitled)
    )
    return conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()


# ---------------------------------------------------------------------------
# Leave — Types
# ---------------------------------------------------------------------------
@router.get("/api/leave/types")
@db_session
def list_leave_types(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM leave_types WHERE institution_id=? AND is_active=1 ORDER BY name", (inst_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/leave/types", status_code=201)
@db_session
def create_leave_type(conn, body: LeaveTypeIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    conn.execute(
        "INSERT INTO leave_types (institution_id,name,annual_entitlement,requires_approval,requires_attachment,is_paid,is_active) VALUES (?,?,?,?,?,?,?)",
        (inst_id, body.name, body.annual_entitlement, 1 if body.requires_approval else 0,
         1 if body.requires_attachment else 0, 1 if body.is_paid else 0, 1 if body.is_active else 0)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leave_types WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/leave/types/{type_id}")
@db_session
def update_leave_type(conn, type_id: int, body: LeaveTypeIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM leave_types WHERE id=? AND institution_id=?", (type_id, inst_id)).fetchone():
        raise HTTPException(404, "Leave type not found")
    conn.execute(
        "UPDATE leave_types SET name=?,annual_entitlement=?,requires_approval=?,requires_attachment=?,is_paid=?,is_active=? WHERE id=?",
        (body.name, body.annual_entitlement, 1 if body.requires_approval else 0,
         1 if body.requires_attachment else 0, 1 if body.is_paid else 0, 1 if body.is_active else 0, type_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leave_types WHERE id=?", (type_id,)).fetchone()
    return dict(row)


@router.delete("/api/leave/types/{type_id}", status_code=204)
@db_session
def delete_leave_type(conn, type_id: int, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))) -> None:
    inst_id = need_inst(user)
    conn.execute("UPDATE leave_types SET is_active=0 WHERE id=? AND institution_id=?", (type_id, inst_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Leave — Balances
# ---------------------------------------------------------------------------
@router.get("/api/leave/balances")
@db_session
def list_leave_balances(conn, employee_id: Optional[str] = None, year: Optional[int] = None,
                        user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    year = year or datetime.now().year
    q = """
        SELECT b.*, lt.name AS leave_type_name, e.full_name AS employee_name, e.department
        FROM leave_balances b
        JOIN leave_types lt ON lt.id = b.leave_type_id
        JOIN employees e ON e.employee_id = b.employee_id AND e.institution_id = b.institution_id
        WHERE b.institution_id=? AND b.year=?
    """
    p: list = [inst_id, year]
    if user["role"] == "employee":
        q += " AND b.employee_id=?"; p.append(user.get("employee_id", ""))
    elif user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif employee_id:
        q += " AND b.employee_id=?"; p.append(employee_id)
    q += " ORDER BY e.full_name, lt.name"
    rows = conn.execute(q, p).fetchall()
    # Ensure every active leave type has a balance row for the employees being viewed, so
    # a type created after an employee joined still shows up with its default entitlement.
    if user["role"] in ("employee",) and user.get("employee_id"):
        types = conn.execute("SELECT id FROM leave_types WHERE institution_id=? AND is_active=1", (inst_id,)).fetchall()
        existing_type_ids = {r["leave_type_id"] for r in rows}
        missing = [t["id"] for t in types if t["id"] not in existing_type_ids]
        if missing:
            for tid in missing:
                _get_or_create_leave_balance(conn, inst_id, user["employee_id"], tid, year)
            conn.commit()
            rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.patch("/api/leave/balances/{balance_id}")
@db_session
def adjust_leave_balance(conn, balance_id: int, body: LeaveBalanceAdjustIn, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    bal = conn.execute("SELECT * FROM leave_balances WHERE id=? AND institution_id=?", (balance_id, inst_id)).fetchone()
    if not bal:
        raise HTTPException(404, "Balance not found")
    entitled = body.entitled_days if body.entitled_days is not None else bal["entitled_days"]
    carried = body.carried_forward_days if body.carried_forward_days is not None else bal["carried_forward_days"]
    conn.execute("UPDATE leave_balances SET entitled_days=?,carried_forward_days=? WHERE id=?", (entitled, carried, balance_id))
    conn.commit()
    row = conn.execute("SELECT * FROM leave_balances WHERE id=?", (balance_id,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------------------
# Leave — Applications
# ---------------------------------------------------------------------------
@router.get("/api/leave/applications")
@db_session
def list_leave_applications(conn, status: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = """
        SELECT a.*, lt.name AS leave_type_name, e.full_name AS employee_name, e.department, e.designation
        FROM leave_applications a
        JOIN leave_types lt ON lt.id = a.leave_type_id
        JOIN employees e ON e.employee_id = a.employee_id AND e.institution_id = a.institution_id
        WHERE a.institution_id=?
    """
    p: list = [inst_id]
    if status: q += " AND a.status=?"; p.append(status)
    if user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        q += f" AND e.employee_id IN {frag}"; p.extend(fp)
    elif user["role"] == "employee":
        q += " AND a.employee_id=?"; p.append(user.get("employee_id", ""))
    q += " ORDER BY a.created_at DESC"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/leave/applications", status_code=201)
@db_session
def create_leave_application(conn, body: LeaveApplicationIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if user["role"] == "employee" and user.get("employee_id") != body.employee_id:
        raise HTTPException(403, "You can only apply leave for yourself")
    emp = conn.execute("SELECT * FROM employees WHERE employee_id=? AND institution_id=?",
                        (body.employee_id, inst_id)).fetchone()
    if not emp:
        raise HTTPException(404, "Employee not found")
    lt = conn.execute("SELECT * FROM leave_types WHERE id=? AND institution_id=? AND is_active=1",
                       (body.leave_type_id, inst_id)).fetchone()
    if not lt:
        raise HTTPException(404, "Leave type not found")
    if lt["requires_attachment"] and not body.attachment:
        raise HTTPException(400, f"'{lt['name']}' requires a supporting document to be attached")

    days = _compute_leave_days(conn, inst_id, body.start_date, body.end_date)
    if days <= 0:
        raise HTTPException(400, "Selected date range has no working days to apply (all weekends/public holidays)")

    year = datetime.strptime(body.start_date, "%Y-%m-%d").year
    balance = _get_or_create_leave_balance(conn, inst_id, body.employee_id, body.leave_type_id, year)
    available = balance["entitled_days"] + balance["carried_forward_days"] - balance["used_days"]
    if days > available:
        raise HTTPException(400, f"Insufficient balance: requesting {days} day(s), only {available} available")

    status = "Pending Approval" if lt["requires_approval"] else "Approved"
    conn.execute(
        "INSERT INTO leave_applications (institution_id,employee_id,leave_type_id,start_date,end_date,days_count,status,reason,attachment,requested_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (inst_id, body.employee_id, body.leave_type_id, body.start_date, body.end_date, days, status,
         body.reason, body.attachment, user["username"])
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    if status == "Approved":
        conn.execute("UPDATE leave_balances SET used_days=used_days+? WHERE id=?", (days, balance["id"]))

    _log_leave(conn, inst_id, app_id, body.employee_id, "Applied",
               f"Applied for {lt['name']}: {body.start_date} to {body.end_date} ({days} working day(s)) — status: {status}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone()
    return dict(row)


@router.patch("/api/leave/applications/{app_id}/status")
@db_session
def update_leave_status(conn, app_id: int, body: LeaveStatusIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    valid = ("Approved", "Rejected", "Cancelled")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    application = conn.execute("SELECT * FROM leave_applications WHERE id=? AND institution_id=?", (app_id, inst_id)).fetchone()
    if not application:
        raise HTTPException(404, "Application not found")

    if body.status in ("Approved", "Rejected"):
        can_approve = user["role"] in ("superadmin", "hr_manager", "hr_admin", "manager")
        if not can_approve:
            raise HTTPException(403, "Only a manager or HR can approve/reject leave")
        if application["status"] != "Pending Approval":
            raise HTTPException(400, f"Application is already {application['status']}")
        if body.status == "Approved":
            year = datetime.strptime(application["start_date"], "%Y-%m-%d").year
            balance = _get_or_create_leave_balance(conn, inst_id, application["employee_id"], application["leave_type_id"], year)
            conn.execute("UPDATE leave_balances SET used_days=used_days+? WHERE id=?", (application["days_count"], balance["id"]))
        conn.execute("UPDATE leave_applications SET status=?,approved_by=?,notes=? WHERE id=?",
                     (body.status, user["username"], body.notes, app_id))
    elif body.status == "Cancelled":
        if user["role"] == "employee" and user.get("employee_id") != application["employee_id"]:
            raise HTTPException(403, "Access denied")
        if application["status"] not in ("Pending Approval", "Approved"):
            raise HTTPException(400, f"Application is already {application['status']}")
        if application["status"] == "Approved":
            year = datetime.strptime(application["start_date"], "%Y-%m-%d").year
            balance = _get_or_create_leave_balance(conn, inst_id, application["employee_id"], application["leave_type_id"], year)
            conn.execute("UPDATE leave_balances SET used_days=used_days-? WHERE id=?", (application["days_count"], balance["id"]))
        conn.execute("UPDATE leave_applications SET status='Cancelled',notes=? WHERE id=?", (body.notes, app_id))

    _log_leave(conn, inst_id, app_id, application["employee_id"], f"Status changed to {body.status}",
               body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone()
    return dict(row)


@router.get("/api/employees/{employee_id}/leave-history")
@db_session
def get_employee_leave_history(conn, employee_id: str, user: dict = Depends(require_roles(*LEAVE_MANAGE_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM leave_audit_log WHERE employee_id=? AND institution_id=? ORDER BY created_at ASC",
        (employee_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]
