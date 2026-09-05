"""API endpoints for the Attendance module: shifts, shift assignments,
attendance settings, clock-in/out, HR review of late/absent days, and
device (API-key) integrations for external clock-in/out hardware."""
import logging
import math
import secrets
from datetime import datetime, timedelta, date as date_cls
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from db import get_db, set_rls_context
from core.db_session import db_session
from core.deps import get_current_user, hash_password, verify_password
from core.permission_matrix import require_permission
from core.leave_balance_ops import _consume_balance
from core.org_queries import subordinates_in_clause, is_self_or_subordinate
from core.attendance_helpers import parse_time as _parse_time, match_attendance_setting as _match_attendance_setting, resolve_shift as _resolve_shift
from core.attendance_schemas import (
    ShiftCreate, ShiftUpdate, ShiftResponse,
    ShiftAssignmentCreate, ShiftAssignmentResponse,
    AttendanceSettingCreate, AttendanceSettingUpdate, AttendanceSettingResponse,
    ClockInRequest, ClockOutRequest, AttendanceRecordResponse, AttendanceRecordWithEmployee,
    AttendanceResolve,
    DeviceCreate, DeviceResponse, DeviceCreateResponse, DeviceClockEventRequest,
)

logger = logging.getLogger("ems.attendance")
router = APIRouter(prefix="/api/attendance", tags=["attendance"])

_ABSENCE_SWEEP_WINDOW_DAYS = 30


def require_attendance_manage_role(current_user: dict):
    """Configuring shifts/settings and reviewing late/absent days is an
    HR function — same role set as timesheet approval."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "hr_admin"]:
        raise HTTPException(403, detail="HR Manager or HR Admin access required")


def _require_employee(current_user: dict) -> str:
    employee_id = current_user.get("employee_id")
    if not employee_id:
        raise HTTPException(400, detail="No employee record is linked to this account")
    return employee_id


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


# ============================================================================
# SHIFTS
# ============================================================================

def _shift_response(row) -> ShiftResponse:
    d = dict(row)
    d["crosses_midnight"] = bool(d["crosses_midnight"])
    d["is_active"] = bool(d["is_active"])
    d["start_time"] = str(d["start_time"])[:5]
    d["end_time"] = str(d["end_time"])[:5]
    return ShiftResponse(**d)


@router.post("/shifts", status_code=201)
@db_session
def create_shift(
    conn,
    payload: ShiftCreate,
    current_user: dict = Depends(get_current_user),
) -> ShiftResponse:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    now = datetime.utcnow().isoformat()
    start_t = _parse_time(payload.start_time)
    end_t = _parse_time(payload.end_time)
    crosses = end_t <= start_t

    conn.execute(
        """
        INSERT INTO shifts
        (institution_id, name, start_time, end_time, crosses_midnight, grace_period_minutes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (inst_id, payload.name, payload.start_time, payload.end_time,
         1 if crosses else 0, payload.grace_period_minutes, now, now),
    )
    conn.commit()
    shift_id = conn._last_id
    shift = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    return _shift_response(shift)


@router.get("/shifts")
@db_session
def list_shifts(
    conn,
    current_user: dict = Depends(get_current_user),
) -> List[ShiftResponse]:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    rows = conn.execute(
        "SELECT * FROM shifts WHERE institution_id = ? ORDER BY start_time",
        (inst_id,),
    ).fetchall()
    return [_shift_response(r) for r in rows]


@router.put("/shifts/{shift_id}")
@db_session
def update_shift(
    conn,
    shift_id: int,
    payload: ShiftUpdate,
    current_user: dict = Depends(get_current_user),
) -> ShiftResponse:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    shift = conn.execute("SELECT * FROM shifts WHERE id = ? AND institution_id = ?", (shift_id, inst_id)).fetchone()
    if not shift:
        raise HTTPException(404, detail="Shift not found")

    name = payload.name if payload.name is not None else shift["name"]
    start_time = payload.start_time if payload.start_time is not None else str(shift["start_time"])[:5]
    end_time = payload.end_time if payload.end_time is not None else str(shift["end_time"])[:5]
    grace = payload.grace_period_minutes if payload.grace_period_minutes is not None else shift["grace_period_minutes"]
    is_active = payload.is_active if payload.is_active is not None else bool(shift["is_active"])
    crosses = _parse_time(end_time) <= _parse_time(start_time)

    conn.execute(
        "UPDATE shifts SET name=?, start_time=?, end_time=?, crosses_midnight=?, grace_period_minutes=?, is_active=? WHERE id=?",
        (name, start_time, end_time, 1 if crosses else 0, grace, 1 if is_active else 0, shift_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    return _shift_response(updated)


@router.delete("/shifts/{shift_id}", status_code=204)
@db_session
def delete_shift(
    conn,
    shift_id: int,
    current_user: dict = Depends(get_current_user),
):
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    shift = conn.execute("SELECT * FROM shifts WHERE id = ? AND institution_id = ?", (shift_id, inst_id)).fetchone()
    if not shift:
        raise HTTPException(404, detail="Shift not found")
    conn.execute("UPDATE shifts SET is_active = 0 WHERE id = ?", (shift_id,))
    conn.commit()


# ============================================================================
# SHIFT ASSIGNMENTS
# ============================================================================

@router.post("/shift-assignments", status_code=201)
@db_session
def create_shift_assignment(
    conn,
    payload: ShiftAssignmentCreate,
    current_user: dict = Depends(get_current_user),
) -> ShiftAssignmentResponse:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    emp = conn.execute("SELECT 1 FROM employees WHERE employee_id=? AND institution_id=?", (payload.employee_id, inst_id)).fetchone()
    if not emp:
        raise HTTPException(404, detail="Employee not found")
    shift = conn.execute("SELECT 1 FROM shifts WHERE id=? AND institution_id=?", (payload.shift_id, inst_id)).fetchone()
    if not shift:
        raise HTTPException(404, detail="Shift not found")

    now = datetime.utcnow().isoformat()
    # Close out any prior open-ended assignment for this employee so
    # only one shift applies to any given date.
    conn.execute(
        "UPDATE employee_shift_assignments SET effective_to = ? WHERE employee_id = ? AND institution_id = ? AND is_active = 1 AND effective_to IS NULL",
        ((datetime.strptime(payload.effective_from, "%Y-%m-%d").date() - timedelta(days=1)).isoformat(),
         payload.employee_id, inst_id),
    )
    conn.execute(
        """
        INSERT INTO employee_shift_assignments
        (institution_id, employee_id, shift_id, effective_from, effective_to, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (inst_id, payload.employee_id, payload.shift_id, payload.effective_from, payload.effective_to, now, now),
    )
    conn.commit()
    assignment_id = conn._last_id
    row = conn.execute(
        "SELECT esa.*, s.name AS shift_name FROM employee_shift_assignments esa JOIN shifts s ON esa.shift_id = s.id WHERE esa.id = ?",
        (assignment_id,),
    ).fetchone()
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    return ShiftAssignmentResponse(**d)


@router.get("/shift-assignments")
@db_session
def list_shift_assignments(
    conn,
    employee_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[ShiftAssignmentResponse]:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    if employee_id:
        rows = conn.execute(
            """
            SELECT esa.*, s.name AS shift_name FROM employee_shift_assignments esa
            JOIN shifts s ON esa.shift_id = s.id
            WHERE esa.institution_id = ? AND esa.employee_id = ? AND esa.is_active = 1
            ORDER BY esa.effective_from DESC
            """,
            (inst_id, employee_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT esa.*, s.name AS shift_name FROM employee_shift_assignments esa
            JOIN shifts s ON esa.shift_id = s.id
            WHERE esa.institution_id = ? AND esa.is_active = 1
            ORDER BY esa.effective_from DESC
            """,
            (inst_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        out.append(ShiftAssignmentResponse(**d))
    return out


@router.delete("/shift-assignments/{assignment_id}", status_code=204)
@db_session
def delete_shift_assignment(
    conn,
    assignment_id: int,
    current_user: dict = Depends(get_current_user),
):
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    row = conn.execute("SELECT 1 FROM employee_shift_assignments WHERE id=? AND institution_id=?", (assignment_id, inst_id)).fetchone()
    if not row:
        raise HTTPException(404, detail="Assignment not found")
    conn.execute("UPDATE employee_shift_assignments SET is_active = 0 WHERE id = ?", (assignment_id,))
    conn.commit()


# ============================================================================
# ATTENDANCE SETTINGS
# ============================================================================

def _setting_response(row) -> AttendanceSettingResponse:
    d = dict(row)
    d["required"] = bool(d["required"])
    d["is_active"] = bool(d["is_active"])
    return AttendanceSettingResponse(**d)


@router.post("/settings", status_code=201)
@db_session
def create_attendance_setting(
    conn,
    payload: AttendanceSettingCreate,
    current_user: dict = Depends(get_current_user),
) -> AttendanceSettingResponse:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    if not payload.department and not payload.employee_id:
        raise HTTPException(400, detail="Specify a department or an employee to scope this rule to")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    if payload.employee_id:
        emp = conn.execute("SELECT 1 FROM employees WHERE employee_id=? AND institution_id=?", (payload.employee_id, inst_id)).fetchone()
        if not emp:
            raise HTTPException(404, detail="Employee not found")
    if payload.default_shift_id:
        shift = conn.execute("SELECT 1 FROM shifts WHERE id=? AND institution_id=?", (payload.default_shift_id, inst_id)).fetchone()
        if not shift:
            raise HTTPException(404, detail="Shift not found")

    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO attendance_settings
        (institution_id, department, employee_id, required, default_shift_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (inst_id, payload.department, payload.employee_id,
         1 if payload.required else 0, payload.default_shift_id, now, now),
    )
    conn.commit()
    setting_id = conn._last_id
    row = conn.execute(
        """
        SELECT ast.*, s.name AS default_shift_name FROM attendance_settings ast
        LEFT JOIN shifts s ON ast.default_shift_id = s.id
        WHERE ast.id = ?
        """,
        (setting_id,),
    ).fetchone()
    return _setting_response(row)


@router.get("/settings")
@db_session
def list_attendance_settings(
    conn,
    current_user: dict = Depends(get_current_user),
) -> List[AttendanceSettingResponse]:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    rows = conn.execute(
        """
        SELECT ast.*, s.name AS default_shift_name FROM attendance_settings ast
        LEFT JOIN shifts s ON ast.default_shift_id = s.id
        WHERE ast.institution_id = ? AND ast.is_active = 1
        ORDER BY ast.department, ast.employee_id
        """,
        (inst_id,),
    ).fetchall()
    return [_setting_response(r) for r in rows]


@router.put("/settings/{setting_id}")
@db_session
def update_attendance_setting(
    conn,
    setting_id: int,
    payload: AttendanceSettingUpdate,
    current_user: dict = Depends(get_current_user),
) -> AttendanceSettingResponse:
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    setting = conn.execute("SELECT * FROM attendance_settings WHERE id=? AND institution_id=?", (setting_id, inst_id)).fetchone()
    if not setting:
        raise HTTPException(404, detail="Setting not found")

    required = payload.required if payload.required is not None else bool(setting["required"])
    default_shift_id = payload.default_shift_id if payload.default_shift_id is not None else setting["default_shift_id"]
    is_active = payload.is_active if payload.is_active is not None else bool(setting["is_active"])

    conn.execute(
        "UPDATE attendance_settings SET required=?, default_shift_id=?, is_active=? WHERE id=?",
        (1 if required else 0, default_shift_id, 1 if is_active else 0, setting_id),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT ast.*, s.name AS default_shift_name FROM attendance_settings ast
        LEFT JOIN shifts s ON ast.default_shift_id = s.id
        WHERE ast.id = ?
        """,
        (setting_id,),
    ).fetchone()
    return _setting_response(row)


@router.delete("/settings/{setting_id}", status_code=204)
@db_session
def delete_attendance_setting(
    conn,
    setting_id: int,
    current_user: dict = Depends(get_current_user),
):
    require_permission(conn, current_user, "attendance.manage_shifts_assignments_settings")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    row = conn.execute("SELECT 1 FROM attendance_settings WHERE id=? AND institution_id=?", (setting_id, inst_id)).fetchone()
    if not row:
        raise HTTPException(404, detail="Setting not found")
    conn.execute("UPDATE attendance_settings SET is_active = 0 WHERE id = ?", (setting_id,))
    conn.commit()


# ============================================================================
# RESOLUTION HELPERS (shift lookup, geofence, sweep)
# ============================================================================
# _match_attendance_setting / _resolve_shift live in core/attendance_helpers.py
# (imported above) — shared with Overtime detection, which resolves the same
# per-employee shift as the daily working-hours threshold.


def _employee_location(conn, inst_id: int, employee_id: str):
    # employee_location_assignments (assignment_type='primary', is_active=1) is the
    # single source of truth for an employee's location — see _resolve_primary_locations
    # in routers/employees.py.
    return conn.execute(
        """
        SELECT l.* FROM employee_location_assignments ela
        JOIN locations l ON ela.location_id = l.id
        WHERE ela.employee_id = ? AND ela.institution_id = ? AND ela.assignment_type = 'primary' AND ela.is_active = 1
        """,
        (employee_id, inst_id),
    ).fetchone()


def _shift_deadline(work_date: str, shift) -> datetime:
    start_t = _parse_time(shift["start_time"])
    return datetime.combine(datetime.strptime(work_date, "%Y-%m-%d").date(), start_t) + timedelta(minutes=shift["grace_period_minutes"])


def _record_response(row) -> AttendanceRecordResponse:
    d = dict(row)
    d["outside_geofence"] = bool(d["outside_geofence"])
    return AttendanceRecordResponse(**d)


def _pick_assignment_shift(assignments, work_date: str):
    """In-memory equivalent of the assignment half of resolve_shift — same
    "most recent effective_from wins" tie-break, just against a
    pre-fetched list instead of a fresh query per day."""
    candidates = [
        a for a in assignments
        if a["effective_from"] <= work_date and (not a["effective_to"] or a["effective_to"] >= work_date)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a["effective_from"])


def _load_absence_sweep_context(conn, inst_id: int):
    """Batch-fetches everything _sweep_absences needs into lookup dicts —
    one query per resource up front instead of one (or several) per
    employee, which is what made the Review screen slow to load even
    after an earlier per-day-query fix. Returns None if there's nothing
    to sweep (no active settings, or no active employees) so the caller
    can bail out early without unpacking a partial context."""
    settings_rows = conn.execute(
        "SELECT * FROM attendance_settings WHERE institution_id = ? AND is_active = 1",
        (inst_id,),
    ).fetchall()
    if not settings_rows:
        return None
    settings_by_emp = {r["employee_id"]: r for r in settings_rows if r["employee_id"]}
    settings_by_dept = {r["department"]: r for r in settings_rows if r["department"] and not r["employee_id"]}

    employees = conn.execute(
        "SELECT employee_id, department, start_date FROM employees WHERE institution_id = ? AND status = 'Active'",
        (inst_id,),
    ).fetchall()
    if not employees:
        return None

    now = datetime.utcnow()
    today = now.date()
    window_start = today - timedelta(days=_ABSENCE_SWEEP_WINDOW_DAYS)
    window_start_iso = window_start.isoformat()

    existing_rows = conn.execute(
        "SELECT employee_id, work_date FROM attendance_records WHERE institution_id = ? AND work_date >= ?",
        (inst_id, window_start_iso),
    ).fetchall()
    existing = {(r["employee_id"], str(r["work_date"])[:10]) for r in existing_rows}

    assignment_rows = conn.execute(
        """
        SELECT esa.employee_id, esa.effective_from, esa.effective_to, s.*
        FROM employee_shift_assignments esa
        JOIN shifts s ON esa.shift_id = s.id
        WHERE esa.institution_id = ? AND esa.is_active = 1 AND s.is_active = 1
        """,
        (inst_id,),
    ).fetchall()
    assignments_by_emp: dict = {}
    for a in assignment_rows:
        assignments_by_emp.setdefault(a["employee_id"], []).append(a)

    shift_rows = conn.execute("SELECT * FROM shifts WHERE institution_id = ? AND is_active = 1", (inst_id,)).fetchall()
    shift_by_id = {s["id"]: s for s in shift_rows}

    return {
        "settings_by_emp": settings_by_emp,
        "settings_by_dept": settings_by_dept,
        "employees": employees,
        "now": now,
        "today": today,
        "window_start": window_start,
        "existing": existing,
        "assignments_by_emp": assignments_by_emp,
        "shift_by_id": shift_by_id,
    }


def _sweep_absences(conn, inst_id: int):
    """Lazy evaluation: run on every load of the review queue / HR
    dashboard. For each employee with an active required=true rule,
    walk back over the sweep window and materialize an
    'Absent (Pending Review)' record for any work day whose clock-in
    deadline has passed with no attendance_records row at all. Days
    that already have a row (Present/Late/etc.) are left untouched."""
    ctx = _load_absence_sweep_context(conn, inst_id)
    if ctx is None:
        return
    settings_by_emp = ctx["settings_by_emp"]
    settings_by_dept = ctx["settings_by_dept"]
    employees = ctx["employees"]
    now = ctx["now"]
    today = ctx["today"]
    window_start = ctx["window_start"]
    existing = ctx["existing"]
    assignments_by_emp = ctx["assignments_by_emp"]
    shift_by_id = ctx["shift_by_id"]

    now_iso = now.isoformat()
    for emp in employees:
        # Employee-specific rule takes priority over a department rule —
        # same precedence as _match_attendance_setting/resolve_shift.
        setting = settings_by_emp.get(emp["employee_id"]) or settings_by_dept.get(emp["department"])
        if not setting or not setting["required"]:
            continue

        rule_start = window_start
        if emp["start_date"]:
            try:
                hire = datetime.strptime(str(emp["start_date"])[:10], "%Y-%m-%d").date()
                rule_start = max(rule_start, hire)
            except ValueError:
                pass

        emp_assignments = assignments_by_emp.get(emp["employee_id"], [])
        default_shift = shift_by_id.get(setting["default_shift_id"]) if setting["default_shift_id"] else None

        d = rule_start
        while d <= today:
            work_date = d.isoformat()
            if (emp["employee_id"], work_date) not in existing:
                shift = _pick_assignment_shift(emp_assignments, work_date) or default_shift
                if shift:
                    deadline = _shift_deadline(work_date, shift)
                    if now > deadline:
                        conn.execute(
                            """
                            INSERT INTO attendance_records
                            (institution_id, employee_id, work_date, shift_id, status, suggested_action, created_at, updated_at)
                            VALUES (?, ?, ?, ?, 'Absent (Pending Review)', 'Full-Day Absence', ?, ?)
                            ON CONFLICT (employee_id, work_date) DO NOTHING
                            """,
                            (inst_id, emp["employee_id"], work_date, shift["id"], now_iso, now_iso),
                        )
            d += timedelta(days=1)
    conn.commit()


# ============================================================================
# CLOCK IN / OUT (self-service)
# ============================================================================

def _do_clock_in(conn, inst_id: int, employee_id: str, lat, lng, client_ip, source: str, device_id: Optional[int] = None, event_time: Optional[datetime] = None):
    """Shared by the self-service endpoint (source='web') and the device
    webhook (source='device') — see clock_in()/device_clock_event() below.
    event_time lets a device report a buffered/delayed timestamp instead
    of "now" (e.g. a camera that syncs events after a network gap)."""
    emp = conn.execute("SELECT department FROM employees WHERE employee_id=? AND institution_id=?", (employee_id, inst_id)).fetchone()
    if not emp:
        raise HTTPException(404, detail="Employee not found")
    department = emp["department"]

    now = event_time or datetime.utcnow()
    today = now.date().isoformat()
    shift = _resolve_shift(conn, inst_id, employee_id, department, today)

    work_date = today
    if shift and shift["crosses_midnight"]:
        end_t = _parse_time(shift["end_time"])
        if now.time() <= end_t:
            work_date = (now.date() - timedelta(days=1)).isoformat()

    existing = conn.execute(
        "SELECT * FROM attendance_records WHERE employee_id = ? AND work_date = ?",
        (employee_id, work_date),
    ).fetchone()
    if existing and existing["clock_in_at"]:
        raise HTTPException(400, detail="Already clocked in for this work day")

    distance = None
    outside = False
    if lat is not None and lng is not None:
        loc = _employee_location(conn, inst_id, employee_id)
        if loc and loc["latitude"] is not None and loc["longitude"] is not None and loc["radius_meters"]:
            distance = _haversine_meters(float(loc["latitude"]), float(loc["longitude"]), lat, lng)
            outside = distance > loc["radius_meters"]

    status = "Present"
    suggested = None
    if shift:
        deadline = _shift_deadline(work_date, shift)
        if now > deadline:
            status = "Late"
            suggested = "Half-Day Leave"

    now_iso = now.isoformat()
    if existing:
        conn.execute(
            """
            UPDATE attendance_records SET shift_id=?, clock_in_at=?, clock_in_lat=?, clock_in_lng=?, clock_in_ip=?,
            clock_in_distance_meters=?, outside_geofence=?, status=?, suggested_action=?, clock_in_source=?, clock_in_device_id=?, updated_at=? WHERE id=?
            """,
            (shift["id"] if shift else None, now_iso, lat, lng, client_ip,
             distance, 1 if outside else 0, status, suggested, source, device_id, now_iso, existing["id"]),
        )
        rec_id = existing["id"]
    else:
        conn.execute(
            """
            INSERT INTO attendance_records
            (institution_id, employee_id, work_date, shift_id, clock_in_at, clock_in_lat, clock_in_lng, clock_in_ip,
             clock_in_distance_meters, outside_geofence, status, suggested_action, clock_in_source, clock_in_device_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (inst_id, employee_id, work_date, shift["id"] if shift else None, now_iso, lat, lng, client_ip,
             distance, 1 if outside else 0, status, suggested, source, device_id, now_iso, now_iso),
        )
        rec_id = conn._last_id
    conn.commit()
    return conn.execute("SELECT * FROM attendance_records WHERE id = ?", (rec_id,)).fetchone()


def _do_clock_out(conn, inst_id: int, employee_id: str, lat, lng, client_ip, source: str, device_id: Optional[int] = None, event_time: Optional[datetime] = None):
    rec = conn.execute(
        """
        SELECT * FROM attendance_records
        WHERE employee_id = ? AND institution_id = ? AND clock_in_at IS NOT NULL AND clock_out_at IS NULL
        ORDER BY work_date DESC LIMIT 1
        """,
        (employee_id, inst_id),
    ).fetchone()
    if not rec:
        raise HTTPException(400, detail="No open clock-in found to clock out from")

    now = event_time or datetime.utcnow()
    clock_in_dt = datetime.fromisoformat(rec["clock_in_at"])
    worked = int((now - clock_in_dt).total_seconds() // 60)

    conn.execute(
        "UPDATE attendance_records SET clock_out_at=?, clock_out_lat=?, clock_out_lng=?, clock_out_ip=?, worked_minutes=?, clock_out_source=?, clock_out_device_id=?, updated_at=? WHERE id=?",
        (now.isoformat(), lat, lng, client_ip, worked, source, device_id, now.isoformat(), rec["id"]),
    )
    conn.commit()
    return conn.execute("SELECT * FROM attendance_records WHERE id = ?", (rec["id"],)).fetchone()


@router.post("/clock-in", status_code=201)
@db_session
def clock_in(
    conn,
    payload: ClockInRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> AttendanceRecordResponse:
    employee_id = _require_employee(current_user)
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    client_ip = request.client.host if request.client else None
    rec = _do_clock_in(conn, inst_id, employee_id, payload.lat, payload.lng, client_ip, "web")
    return _record_response(rec)


@router.post("/clock-out")
@db_session
def clock_out(
    conn,
    payload: ClockOutRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> AttendanceRecordResponse:
    employee_id = _require_employee(current_user)
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    client_ip = request.client.host if request.client else None
    rec = _do_clock_out(conn, inst_id, employee_id, payload.lat, payload.lng, client_ip, "web")
    return _record_response(rec)


@router.get("/mine")
@db_session
def my_attendance(
    conn,
    limit: int = 30,
    current_user: dict = Depends(get_current_user),
) -> List[AttendanceRecordResponse]:
    employee_id = current_user.get("employee_id")
    if not employee_id:
        return []
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    rows = conn.execute(
        """
        SELECT ar.*, s.name AS shift_name FROM attendance_records ar
        LEFT JOIN shifts s ON ar.shift_id = s.id
        WHERE ar.employee_id = ? AND ar.institution_id = ? ORDER BY ar.work_date DESC LIMIT ?
        """,
        (employee_id, inst_id, limit),
    ).fetchall()
    return [_record_response(r) for r in rows]


# ============================================================================
# HR REVIEW
# ============================================================================

@router.get("/review")
@db_session
def review_queue(
    conn,
    current_user: dict = Depends(get_current_user),
) -> List[AttendanceRecordWithEmployee]:
    require_permission(conn, current_user, "attendance.review_queue_resolve_attendance_record")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    _sweep_absences(conn, inst_id)
    q = """
        SELECT ar.*, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name, e.department AS department
        FROM attendance_records ar
        JOIN employees e ON ar.employee_id = e.employee_id AND ar.institution_id = e.institution_id
        WHERE ar.institution_id = ? AND ar.status IN ('Late', 'Absent (Pending Review)')
    """
    params = [inst_id]
    # A manager (the one non-HR role the permission check above admits)
    # only reviews their own downstream reporting chain — the HR tier
    # sees the whole institution. Same "manager sees subordinates, HR
    # sees all" scoping every other list endpoint in this app applies
    # (e.g. routers/employees.py's list_employees).
    if current_user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, current_user.get("employee_id") or "")
        q += f" AND ar.employee_id IN {frag}"
        params.extend(fp)
    q += " ORDER BY ar.work_date DESC"
    rows = conn.execute(q, params).fetchall()
    out = []
    for r in rows:
        base = _record_response(r).model_dump()
        out.append(AttendanceRecordWithEmployee(**base, employee_name=r["employee_name"], employee_preferred_name=r["employee_preferred_name"], department=r["department"]))
    return out


@router.put("/records/{record_id}/resolve")
@db_session
def resolve_attendance_record(
    conn,
    record_id: int,
    payload: AttendanceResolve,
    current_user: dict = Depends(get_current_user),
) -> AttendanceRecordResponse:
    require_permission(conn, current_user, "attendance.review_queue_resolve_attendance_record")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    rec = conn.execute("SELECT * FROM attendance_records WHERE id = ? AND institution_id = ?", (record_id, inst_id)).fetchone()
    if not rec:
        raise HTTPException(404, detail="Attendance record not found")
    # Same subordinate scoping as review_queue above — a manager can't
    # resolve a record outside their own reporting chain just by knowing
    # or guessing its id. 404, not 403, so as not to confirm a record's
    # existence to someone outside its scope.
    if current_user["role"] == "manager" and not is_self_or_subordinate(
        conn, inst_id, current_user.get("employee_id") or "", rec["employee_id"]
    ):
        raise HTTPException(404, detail="Attendance record not found")
    if rec["status"] not in ("Late", "Absent (Pending Review)"):
        raise HTTPException(400, detail="Only a Late or Absent (Pending Review) record can be resolved")

    now = datetime.utcnow().isoformat()
    leave_application_id = None

    if payload.action == "Excuse":
        new_status = "Excused"
    elif payload.action == "ConfirmAbsent":
        new_status = "Confirmed Absent"
    elif payload.action == "ReclassifyAsLeave":
        if not payload.leave_type_id:
            raise HTTPException(400, detail="leave_type_id is required to reclassify as leave")
        leave_type = conn.execute(
            "SELECT * FROM leave_types WHERE id = ? AND institution_id = ? AND is_active = 1",
            (payload.leave_type_id, inst_id),
        ).fetchone()
        if not leave_type:
            raise HTTPException(404, detail="Leave type not found")

        days = 0.5 if payload.half_day else 1.0
        conn.execute(
            """
            INSERT INTO leave_applications
            (institution_id, employee_id, leave_type_id, start_date, end_date, days_count, status, reason, requested_by, approved_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, 'Approved', ?, ?, ?, ?)
            """,
            (inst_id, rec["employee_id"], payload.leave_type_id, rec["work_date"], rec["work_date"], days,
             f"Reclassified from attendance record #{record_id} ({rec['status']})",
             current_user["username"], current_user["username"], payload.notes),
        )
        conn.commit()
        leave_application_id = conn._last_id

        year = datetime.strptime(rec["work_date"], "%Y-%m-%d").year
        balance = conn.execute(
            "SELECT * FROM leave_balances WHERE employee_id = ? AND leave_type_id = ? AND year = ?",
            (rec["employee_id"], payload.leave_type_id, year),
        ).fetchone()
        if balance:
            _consume_balance(conn, balance, days)

        new_status = "Reclassified as Leave"
    else:
        raise HTTPException(400, detail="Unknown action")

    conn.execute(
        """
        UPDATE attendance_records
        SET status = ?, reviewed_by_user_id = ?, review_notes = ?, reviewed_at = ?, leave_application_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_status, current_user.get("id"), payload.notes, now, leave_application_id, now, record_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM attendance_records WHERE id = ?", (record_id,)).fetchone()
    return _record_response(updated)


# ============================================================================
# DEVICES (external clock-in/out integrations, e.g. facial-recognition
# office cameras) — HR-managed API keys, verified via X-Device-Api-Key
# ============================================================================

def _generate_device_api_key():
    """adk_<12 hex chars>_<43 url-safe chars>. The prefix is stored in
    plaintext (indexed, unique) purely to locate the candidate row without
    scanning every device's bcrypt hash; the full key is then verified
    against key_hash the same way a user password is. Hex (not
    token_urlsafe) for the prefix specifically so it never contains an
    underscore, keeping the header format unambiguous to parse."""
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    return prefix, f"adk_{prefix}_{secret}"


def _parse_device_api_key(raw_key: str) -> Optional[str]:
    if not raw_key or not raw_key.startswith("adk_"):
        return None
    rest = raw_key[4:]
    if len(rest) < 14 or rest[12] != "_":
        return None
    return rest[:12]


def _device_response(row) -> DeviceResponse:
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    return DeviceResponse(**d)


@router.post("/devices", status_code=201)
@db_session
def create_device(
    conn,
    payload: DeviceCreate,
    current_user: dict = Depends(get_current_user),
) -> DeviceCreateResponse:
    require_permission(conn, current_user, "attendance.manage_attendance_devices")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    if payload.location_id and not conn.execute(
        "SELECT 1 FROM locations WHERE id=? AND institution_id=?", (payload.location_id, inst_id)
    ).fetchone():
        raise HTTPException(404, detail="Location not found")

    prefix, raw_key = _generate_device_api_key()
    key_hash = hash_password(raw_key)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO attendance_devices (institution_id, name, location_id, key_prefix, key_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (inst_id, payload.name, payload.location_id, prefix, key_hash, now, now),
    )
    conn.commit()
    device_id = conn._last_id
    row = conn.execute(
        "SELECT ad.*, l.name AS location_name FROM attendance_devices ad LEFT JOIN locations l ON ad.location_id = l.id WHERE ad.id = ?",
        (device_id,),
    ).fetchone()
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    return DeviceCreateResponse(**d, api_key=raw_key)


@router.get("/devices")
@db_session
def list_devices(
    conn,
    current_user: dict = Depends(get_current_user),
) -> List[DeviceResponse]:
    require_permission(conn, current_user, "attendance.manage_attendance_devices")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    rows = conn.execute(
        """
        SELECT ad.*, l.name AS location_name FROM attendance_devices ad
        LEFT JOIN locations l ON ad.location_id = l.id
        WHERE ad.institution_id = ? AND ad.is_active = 1
        ORDER BY ad.created_at DESC
        """,
        (inst_id,),
    ).fetchall()
    return [_device_response(r) for r in rows]


@router.delete("/devices/{device_id}", status_code=204)
@db_session
def delete_device(
    conn,
    device_id: int,
    current_user: dict = Depends(get_current_user),
):
    require_permission(conn, current_user, "attendance.manage_attendance_devices")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    if not conn.execute("SELECT 1 FROM attendance_devices WHERE id=? AND institution_id=?", (device_id, inst_id)).fetchone():
        raise HTTPException(404, detail="Device not found")
    conn.execute("UPDATE attendance_devices SET is_active = 0 WHERE id = ?", (device_id,))
    conn.commit()


async def get_device(request: Request) -> dict:
    """Device-key auth, parallel to get_current_user's JWT flow but reading
    X-Device-Api-Key instead of an Authorization bearer token. Must run
    directly on the request's own asyncio Task (not offloaded to a
    threadpool) for the same reason get_current_user must be async def —
    see its docstring in core/deps.py: set_rls_context()'s ContextVar.set()
    only propagates to later get_db() calls in THIS request if it happens
    on the live task, not a copied thread context.

    NOT converted to @db_session during the Phase 3/4 db_session rollout —
    that decorator's plain-sync wrapper would make FastAPI dispatch this to
    a threadpool like any other sync def, defeating the exact thing this
    docstring says must not happen. Left as manual get_db()/try/finally on
    purpose, matching assistant_chat's same deliberate exception in
    routers/assistant.py."""
    raw_key = request.headers.get("X-Device-Api-Key")
    if not raw_key:
        raise HTTPException(401, detail="X-Device-Api-Key header required")
    prefix = _parse_device_api_key(raw_key)
    if not prefix:
        raise HTTPException(401, detail="Malformed API key")

    conn = get_db()
    try:
        device = conn.execute(
            "SELECT * FROM attendance_devices WHERE key_prefix = ? AND is_active = 1",
            (prefix,),
        ).fetchone()
        if not device or not verify_password(raw_key, device["key_hash"]):
            raise HTTPException(401, detail="Invalid API key")
        set_rls_context(device["institution_id"], bypass_rls=False)
        conn.execute("UPDATE attendance_devices SET last_used_at = ? WHERE id = ?", (datetime.utcnow().isoformat(), device["id"]))
        conn.commit()
        return dict(device)
    finally:
        conn.close()


@router.post("/webhook/clock-event", status_code=201)
@db_session
def device_clock_event(
    conn,
    payload: DeviceClockEventRequest,
    request: Request,
    device: dict = Depends(get_device),
) -> AttendanceRecordResponse:
    """External clock-in/out hardware (e.g. a facial-recognition office
    camera) reports a punch for an employee_id it has already matched
    on-device — this endpoint trusts that match and just records the
    event; the actual face recognition/liveness check is entirely the
    vendor hardware's responsibility, not this app's.

    Converted to @db_session as part of the Phase 3/4 rollout (safe:
    get_device, the dependency that sets the RLS context, is the one that
    must stay async — see its own docstring; a sync route handler
    dispatched to FastAPI's threadpool still sees a context already
    mutated by an earlier async dependency, same reasoning core/deps.py
    documents for get_current_user) — no behavior change, this endpoint
    already worked correctly before."""
    inst_id = device["institution_id"]
    if not conn.execute(
        "SELECT 1 FROM employees WHERE employee_id = ? AND institution_id = ?",
        (payload.employee_id, inst_id),
    ).fetchone():
        raise HTTPException(404, detail="Employee not found for this institution")

    lat = lng = None
    if device.get("location_id"):
        loc = conn.execute("SELECT latitude, longitude FROM locations WHERE id = ?", (device["location_id"],)).fetchone()
        if loc and loc["latitude"] is not None and loc["longitude"] is not None:
            lat, lng = float(loc["latitude"]), float(loc["longitude"])

    event_time = None
    if payload.event_time:
        try:
            event_time = datetime.fromisoformat(payload.event_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(400, detail="event_time must be a valid ISO 8601 timestamp")

    client_ip = request.client.host if request.client else None
    if payload.event_type == "in":
        rec = _do_clock_in(conn, inst_id, payload.employee_id, lat, lng, client_ip, "device", device["id"], event_time)
    else:
        rec = _do_clock_out(conn, inst_id, payload.employee_id, lat, lng, client_ip, "device", device["id"], event_time)
    return _record_response(rec)
