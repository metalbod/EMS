"""Shift-resolution helpers shared between the Attendance module
(routers/attendance.py) and Overtime detection (core/overtime.py) — an
employee's daily working-hours threshold for overtime is their resolved
Attendance shift, not a separate concept.
"""
from datetime import datetime
from typing import Optional


def parse_time(t) -> "datetime.time":
    if isinstance(t, str):
        return datetime.strptime(t[:5], "%H:%M").time()
    return t  # already a time object (psycopg returns datetime.time for TIME columns)


def shift_duration_hours(shift) -> float:
    """Hours between a shift's start_time and end_time, accounting for an
    overnight shift (crosses_midnight)."""
    start_t = parse_time(shift["start_time"])
    end_t = parse_time(shift["end_time"])
    start_minutes = start_t.hour * 60 + start_t.minute
    end_minutes = end_t.hour * 60 + end_t.minute
    if shift["crosses_midnight"] or end_minutes <= start_minutes:
        end_minutes += 24 * 60
    return round((end_minutes - start_minutes) / 60, 4)


def match_attendance_setting(conn, inst_id: int, employee_id: str, department: Optional[str]):
    """Employee-specific rule takes priority over a department rule.
    No matching rule = not required (opt-in only, per product decision)."""
    row = conn.execute(
        "SELECT * FROM attendance_settings WHERE institution_id=? AND employee_id=? AND is_active=1",
        (inst_id, employee_id),
    ).fetchone()
    if row:
        return row
    if department:
        row = conn.execute(
            "SELECT * FROM attendance_settings WHERE institution_id=? AND department=? AND employee_id IS NULL AND is_active=1",
            (inst_id, department),
        ).fetchone()
        if row:
            return row
    return None


def resolve_shift(conn, inst_id: int, employee_id: str, department: Optional[str], work_date: str):
    """Shift applicable to this employee on work_date: an explicit
    effective-dated assignment wins over the matching setting's
    default_shift_id. None if nothing resolves (no attendance requirement
    on file for this employee) — callers treat that as "no threshold"."""
    assignment = conn.execute(
        """
        SELECT s.* FROM employee_shift_assignments esa
        JOIN shifts s ON esa.shift_id = s.id
        WHERE esa.employee_id = ? AND esa.institution_id = ? AND esa.is_active = 1 AND s.is_active = 1
          AND esa.effective_from <= ?
          AND (esa.effective_to IS NULL OR esa.effective_to >= ?)
        ORDER BY esa.effective_from DESC LIMIT 1
        """,
        (employee_id, inst_id, work_date, work_date),
    ).fetchone()
    if assignment:
        return assignment
    setting = match_attendance_setting(conn, inst_id, employee_id, department)
    if setting and setting["default_shift_id"]:
        return conn.execute("SELECT * FROM shifts WHERE id = ? AND is_active = 1", (setting["default_shift_id"],)).fetchone()
    return None
