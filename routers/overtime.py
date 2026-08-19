"""Overtime: records generated from Timesheet submission (see
core/overtime.py's generate_overtime_records), their approval, and the
institution-level conversion settings (leave vs. pay — see README.md's
"Approval workflow module" section for the shared engine these steps
run through).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst, require_roles

from core.roles import LEAVE_MANAGE_ROLES

from core.approval_workflow import advance_or_finalize, project_ids_for_row

from core.overtime import apply_overtime_outcome

from core.db_session import db_session

from db import get_db

router = APIRouter()

# Same role set that already manages Leave Types / Approval Workflows —
# overtime conversion settings are an HR-configuration concern.
OVERTIME_SETTINGS_ROLES = LEAVE_MANAGE_ROLES


class OvertimeStatusIn(BaseModel):
    status: str  # Approved | Rejected


class OvertimeSettingsIn(BaseModel):
    overtime_conversion_mode: str
    overtime_leave_type_id: Optional[int] = None
    overtime_pay_multiplier: float = 1.5

    @field_validator("overtime_conversion_mode")
    @classmethod
    def _validate_mode(cls, v):
        if v not in ("leave", "pay"):
            raise ValueError("overtime_conversion_mode must be 'leave' or 'pay'")
        return v


@router.get("/api/overtime/settings")
@db_session
def get_overtime_settings(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    row = conn.execute(
        "SELECT overtime_conversion_mode, overtime_leave_type_id, overtime_pay_multiplier FROM institutions WHERE id=?",
        (inst_id,)
    ).fetchone()
    return dict(row)


@router.put("/api/overtime/settings")
@db_session
def update_overtime_settings(conn, body: OvertimeSettingsIn,
                             user: dict = Depends(require_roles(*OVERTIME_SETTINGS_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.overtime_conversion_mode == "leave":
        if not body.overtime_leave_type_id:
            raise HTTPException(400, "overtime_leave_type_id is required when overtime_conversion_mode is 'leave'")
        lt = conn.execute(
            "SELECT id FROM leave_types WHERE id=? AND institution_id=? AND is_active=1",
            (body.overtime_leave_type_id, inst_id)
        ).fetchone()
        if not lt:
            raise HTTPException(404, "Leave type not found")
    conn.execute(
        "UPDATE institutions SET overtime_conversion_mode=?,overtime_leave_type_id=?,overtime_pay_multiplier=? WHERE id=?",
        (body.overtime_conversion_mode, body.overtime_leave_type_id if body.overtime_conversion_mode == "leave" else None,
         body.overtime_pay_multiplier, inst_id)
    )
    conn.commit()
    row = conn.execute(
        "SELECT overtime_conversion_mode, overtime_leave_type_id, overtime_pay_multiplier FROM institutions WHERE id=?",
        (inst_id,)
    ).fetchone()
    return dict(row)


def _visible_overtime_where(user: dict):
    """Employees see only their own records; everyone else (managers, HR,
    superadmin) sees all — the approve/reject action itself is still
    gated by is_eligible_approver via advance_or_finalize, this just
    controls list visibility."""
    if user["role"] == "employee":
        return " AND o.employee_id=?", [user.get("employee_id", "")]
    return "", []


@router.get("/api/overtime")
@db_session
def list_overtime(conn, status: Optional[str] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = """
        SELECT o.*, e.full_name AS employee_name
        FROM overtime_records o
        JOIN employees e ON e.employee_id = o.employee_id AND e.institution_id = o.institution_id
        WHERE o.institution_id=?
    """
    params: list = [inst_id]
    extra_where, extra_params = _visible_overtime_where(user)
    q += extra_where; params.extend(extra_params)
    if status:
        q += " AND o.status=?"; params.append(status)
    q += " ORDER BY o.work_date DESC, o.id DESC"
    rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/timesheets/{timesheet_id}/overtime")
@db_session
def list_overtime_for_timesheet(conn, timesheet_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM overtime_records WHERE timesheet_id=? AND institution_id=? ORDER BY work_date",
        (timesheet_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/api/overtime/{record_id}/status")
@db_session
def update_overtime_status(conn, record_id: int, body: OvertimeStatusIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    valid = ("Approved", "Rejected")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    record = conn.execute("SELECT * FROM overtime_records WHERE id=? AND institution_id=?", (record_id, inst_id)).fetchone()
    if not record:
        raise HTTPException(404, "Overtime record not found")
    if record["status"] != "Pending":
        raise HTTPException(400, f"Overtime record is already {record['status']}")

    action = "reject" if body.status == "Rejected" else "approve"
    timesheet = conn.execute("SELECT * FROM timesheets WHERE id=?", (record["timesheet_id"],)).fetchone()
    project_ids = project_ids_for_row(conn, "overtime", record)
    try:
        outcome, next_step = advance_or_finalize(
            conn, inst_id, "overtime", record["employee_id"],
            record["approval_workflow_id"], record["approval_step"], action, user, project_ids
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))

    if outcome == "advanced":
        conn.execute("UPDATE overtime_records SET approval_step=? WHERE id=?", (next_step, record_id))
        conn.commit()
        return dict(conn.execute("SELECT * FROM overtime_records WHERE id=?", (record_id,)).fetchone())

    apply_overtime_outcome(conn, inst_id, record, outcome, user["username"])
    conn.commit()
    return dict(conn.execute("SELECT * FROM overtime_records WHERE id=?", (record_id,)).fetchone())
