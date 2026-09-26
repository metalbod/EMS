"""Overtime: records generated from Timesheet submission (see
core/overtime.py's generate_overtime_records), their approval, and the
institution-level conversion settings (leave vs. pay — see README.md's
"Approval workflow module" section for the shared engine these steps
run through).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst

from core.roles import LEAVE_MANAGE_ROLES

from core.permission_matrix import require_permission

from core.approval_workflow import advance_or_finalize, project_ids_for_row, annotate_actionability

from core.overtime import apply_overtime_outcome, apply_overtime_project_outcome

from core.audit import diff_fields, write_entity_audit

from core.db_session import db_session

from db import get_db

router = APIRouter()

# Same role set that already manages Leave Types / Approval Workflows —
# overtime conversion settings are an HR-configuration concern. No longer
# the literal gate (update_overtime_settings below goes through
# require_permission("overtime.configure_overtime_settings") /
# core/permission_matrix.py's override system now) — kept as the
# documented default this action's matrix row represents, same pattern
# as routers/locations.py's LOCATIONS_MANAGE_ROLES.
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
                             user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "overtime.configure_overtime_settings")
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
    before = conn.execute(
        "SELECT overtime_conversion_mode, overtime_leave_type_id, overtime_pay_multiplier FROM institutions WHERE id=?",
        (inst_id,)
    ).fetchone()
    conn.execute(
        "UPDATE institutions SET overtime_conversion_mode=?,overtime_leave_type_id=?,overtime_pay_multiplier=? WHERE id=?",
        (body.overtime_conversion_mode, body.overtime_leave_type_id if body.overtime_conversion_mode == "leave" else None,
         body.overtime_pay_multiplier, inst_id)
    )
    row = conn.execute(
        "SELECT overtime_conversion_mode, overtime_leave_type_id, overtime_pay_multiplier FROM institutions WHERE id=?",
        (inst_id,)
    ).fetchone()
    changes = diff_fields(dict(before), dict(row), {
        "overtime_conversion_mode": "Conversion mode", "overtime_leave_type_id": "Overtime leave type",
        "overtime_pay_multiplier": "Pay multiplier"})
    if changes:
        write_entity_audit(conn, user, inst_id, "Overtime", "overtime_settings", inst_id, "Settings updated",
                           changes=changes, entity_label="Overtime settings")
    conn.commit()
    return dict(row)


def _visible_overtime_where(user: dict):
    """Employees see only their own records; everyone else (managers, HR,
    superadmin) sees all — the approve/reject action itself is still
    gated by is_eligible_approver via advance_or_finalize, this just
    controls list visibility."""
    if user["role"] == "employee":
        return " AND o.employee_id=?", [user.get("employee_id", "")]
    return "", []


def _expand_overtime_rows(conn, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mirrors routers/timesheets.py's _expand_timesheet_rows: one
    day-level overtime_records row -> one row per project its overtime
    was split into (see overtime_project_approvals, added 2026-09-17),
    each carrying that project's own prorated overtime_hours and
    status/approval fields — or, for a record never split (legacy,
    pre-split, or auto-approved with no attendance-detected split
    needed... actually always split when created going forward, so
    "never split" here just means legacy), a single row using the day's
    own whole-record status/overtime_hours."""
    record_ids = [r["id"] for r in records]
    if not record_ids:
        return []
    placeholders = ",".join("?" * len(record_ids))
    project_rows = conn.execute(
        f"""SELECT opa.*, p.name AS project_name FROM overtime_project_approvals opa
            JOIN projects p ON p.id = opa.project_id
            WHERE opa.overtime_record_id IN ({placeholders}) ORDER BY p.name""",
        record_ids
    ).fetchall()
    by_record: Dict[int, List[Dict[str, Any]]] = {}
    for pr in project_rows:
        by_record.setdefault(pr["overtime_record_id"], []).append(dict(pr))

    out = []
    for r in records:
        splits = by_record.get(r["id"])
        if not splits:
            row = dict(r)
            row["project_id"] = None
            row["project_name"] = None
            out.append(row)
            continue
        for pr in splits:
            row = dict(r)
            row["project_approval_id"] = pr["id"]  # the child row's own id — see PATCH .../projects/{approval_id}/status
            row["project_id"] = pr["project_id"]
            row["project_name"] = pr["project_name"]
            row["status"] = pr["status"]
            row["overtime_hours"] = pr["overtime_hours"]
            row["approval_workflow_id"] = pr["approval_workflow_id"]
            row["approval_step"] = pr["approval_step"]
            row["approved_by"] = pr["approved_by"]
            row["approved_at"] = pr["approved_at"]
            row["leave_days_credited"] = pr["leave_days_credited"]
            row["pay_amount"] = pr["pay_amount"]
            out.append(row)
    return out


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
    q += " ORDER BY o.work_date DESC, o.id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    expanded = _expand_overtime_rows(conn, rows)
    if status:
        expanded = [r for r in expanded if r["status"] == status]
    if user["role"] != "employee":
        expanded = annotate_actionability(conn, inst_id, "overtime", expanded, user)
    return expanded


@router.get("/api/timesheets/{timesheet_id}/overtime")
@db_session
def list_overtime_for_timesheet(conn, timesheet_id: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM overtime_records WHERE timesheet_id=? AND institution_id=? ORDER BY work_date",
        (timesheet_id, inst_id)
    ).fetchall()
    expanded = _expand_overtime_rows(conn, [dict(r) for r in rows])
    if user["role"] != "employee":
        expanded = annotate_actionability(conn, inst_id, "overtime", expanded, user)
    return expanded


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
    # LEGACY (pre-split) records only — a record with per-project rows
    # must be decided project by project via
    # PATCH /api/overtime/projects/{approval_id}/status instead.
    if conn.execute("SELECT 1 FROM overtime_project_approvals WHERE overtime_record_id=? LIMIT 1", (record_id,)).fetchone():
        raise HTTPException(400, "This overtime record's projects must be approved/rejected individually")
    if record["status"] != "Pending":
        raise HTTPException(400, f"Overtime record is already {record['status']}")

    action = "reject" if body.status == "Rejected" else "approve"
    timesheet = conn.execute("SELECT * FROM timesheets WHERE id=?", (record["timesheet_id"],)).fetchone()
    project_ids = project_ids_for_row(conn, "overtime", record)
    try:
        outcome, next_step = advance_or_finalize(
            conn, inst_id, "overtime", record["employee_id"],
            record["approval_workflow_id"], record["approval_step"], action, user,
            "overtime_records", record_id, project_ids
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


@router.patch("/api/overtime/projects/{approval_id}/status")
@db_session
def update_overtime_project_status(conn, approval_id: int, body: OvertimeStatusIn,
                                   user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Approve/reject one project's prorated share of a day's overtime,
    independently of any other project logged that same day — see
    migrations/versions/20260917_0001_... and core/overtime.py's module
    docstring. `approval_id` is the overtime_project_approvals row's own
    id, same direct-id convention as the legacy PATCH .../{record_id}/status
    above."""
    inst_id = need_inst(user)
    valid = ("Approved", "Rejected")
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of: {', '.join(valid)}")
    row = conn.execute(
        "SELECT * FROM overtime_project_approvals WHERE id=? AND institution_id=?", (approval_id, inst_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Overtime project approval not found")
    if row["status"] != "Pending":
        raise HTTPException(400, f"This project's overtime is already {row['status']}")

    action = "reject" if body.status == "Rejected" else "approve"
    project_ids = project_ids_for_row(conn, "overtime", row)
    try:
        outcome, next_step = advance_or_finalize(
            conn, inst_id, "overtime", row["employee_id"],
            row["approval_workflow_id"], row["approval_step"], action, user,
            "overtime_project_approvals", approval_id, project_ids
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))

    if outcome == "advanced":
        conn.execute("UPDATE overtime_project_approvals SET approval_step=? WHERE id=?", (next_step, approval_id))
        conn.commit()
        return dict(conn.execute("SELECT * FROM overtime_project_approvals WHERE id=?", (approval_id,)).fetchone())

    apply_overtime_project_outcome(conn, inst_id, row, outcome, user["username"])
    conn.commit()
    return dict(conn.execute("SELECT * FROM overtime_project_approvals WHERE id=?", (approval_id,)).fetchone())
