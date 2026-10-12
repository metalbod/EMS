"""API surface for the FR (facial-recognition attendance kiosk) system —
see docs/FR_INTEGRATION.md for the full contract. Two device-key-authed
endpoints: a roster pull FR mirrors locally, and a batch attendance push.

Reuses the existing attendance_devices/get_device() machinery
(routers/attendance.py) wholesale — an FR kiosk is provisioned exactly
like any other external clock-in/out device (Settings > Attendance >
Devices), no new device concept or auth mechanism. Not user-role gated
at all, same as routers/attendance.py's own device webhook — see its
comment at core/permission_matrix.py's Attendance module entry."""
from datetime import datetime, date as date_cls
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from core.db_session import db_session
from core.institution_time import institution_today
from core.fr_integration_schemas import (
    FrEmployeeOut, FrEmployeeLookupOut, FrAttendanceRow, FrAttendancePushResult,
)
from routers.attendance import get_device

router = APIRouter(prefix="/api/integrations/fr", tags=["fr-integration"])

_MAX_PAGE_SIZE = 1000
_MAX_BATCH = 500
# Attendance-record statuses HR has already made a determination on — a
# late-arriving/re-synced FR push for that work_date must not silently
# clobber an HR review decision. Present/Late/Absent (Pending Review) are
# all still "the machine's own read of the day" and remain overwritable.
_HR_FINALIZED_STATUSES = {"Excused", "Reclassified as Leave", "Confirmed Absent"}


def _parse_iso(ts: str) -> datetime:
    """Same relaxed ISO-8601 parsing as device_clock_event
    (routers/attendance.py) — accepts a trailing 'Z', strips tzinfo since
    this app stores naive-UTC timestamps throughout."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)


def is_birthday(dob: Optional[str], today: str) -> bool:
    """Whether `dob` (YYYY-MM-DD) falls on `today` (YYYY-MM-DD) by month and day. A 29 February birthday is
    celebrated on 28 February in years that are not leap years."""
    try:
        _, m, d = (int(x) for x in (dob or "")[:10].split("-"))
        ty, tm, td = (int(x) for x in today[:10].split("-"))
    except ValueError:
        return False
    if (m, d) == (2, 29) and not (ty % 4 == 0 and (ty % 100 != 0 or ty % 400 == 0)):
        d = 28
    return (m, d) == (tm, td)


def _to_fr_employee(row, today: str) -> Dict[str, Any]:
    """Maps an `employees` row onto FR's own field names/casing — a
    deliberately narrow, stable external contract, not just EmployeeOut
    reused. display_name falls back to full_name, matching the
    preferred_name-or-full_name convention static/js/core.js's
    displayName() already uses everywhere else in this app."""
    d = dict(row)
    return {
        "ems_employee_id": d["employee_id"],
        "full_name": d["full_name"],
        "display_name": d.get("preferred_name") or d["full_name"],
        "department": d.get("department"),
        "email": d.get("work_email") or d.get("personal_email"),
        "start_date": d["start_date"],
        # The date of birth is only released when the employee consented to the birthday greeting; without
        # consent there is no reason for the external system to hold it.
        "date_of_birth": d.get("date_of_birth") if d.get("consent_dob") else None,
        "status": "active" if d["status"] == "Active" else "inactive",
        "consent_recognition": bool(d.get("consent_recognition")),
        "consent_display_name": bool(d.get("consent_display_name")),
        "consent_dob": bool(d.get("consent_dob")),
        "birthday": bool(d.get("consent_dob")) and is_birthday(d.get("date_of_birth"), today),
    }


@router.get("/employees", response_model=List[FrEmployeeOut])
@db_session
def fr_list_employees(
    conn,
    response: Response,
    changed_since: Optional[str] = None,
    cursor: Optional[str] = None,
    page_size: Optional[int] = None,
    device: dict = Depends(get_device),
) -> List[Dict[str, Any]]:
    """Roster pull — FR upserts its local mirror keyed on ems_employee_id.
    `changed_since` filters on employees.updated_at (already trigger-
    maintained, no new column needed). Response is a bare JSON array per
    the agreed contract; when page_size limits the result, the id of the
    last row returned is echoed back in an X-Next-Cursor response header
    (not a JSON envelope, to keep the body's shape exactly "array of
    employee") — pass it back as `cursor` to continue. Omitting page_size
    returns the full matching roster in one call, which the contract
    doc's own FR-side mock already treats as acceptable."""
    inst_id = device["institution_id"]
    q = "SELECT * FROM employees WHERE institution_id=?"
    params: List[Any] = [inst_id]
    if changed_since:
        q += " AND updated_at >= ?"
        params.append(changed_since)
    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError:
            raise HTTPException(400, detail="cursor must be an opaque id from a previous X-Next-Cursor")
        q += " AND id > ?"
        params.append(cursor_id)
    q += " ORDER BY id"

    limit = None
    if page_size:
        limit = max(1, min(page_size, _MAX_PAGE_SIZE))
        q += " LIMIT ?"
        params.append(limit + 1)  # one extra row to detect "more remain"

    rows = conn.execute(q, params).fetchall()
    if limit and len(rows) > limit:
        rows = rows[:limit]
        response.headers["X-Next-Cursor"] = str(rows[-1]["id"])
    today = institution_today(conn, inst_id)
    return [_to_fr_employee(r, today) for r in rows]


@router.get("/employees/{ems_employee_id}", response_model=FrEmployeeLookupOut)
@db_session
def fr_get_employee(conn, ems_employee_id: str, device: dict = Depends(get_device)) -> Dict[str, Any]:
    """Look up one employee by ID for a greeting: just `display_name` (only if they consented to a name
    greeting, else null) and `birthday` (true only if it is their birthday today in the company's timezone
    AND they consented to a birthday greeting). No other field is returned. An unknown ID, an ID that only
    exists in another company, or an employee who is no longer active is a 404."""
    inst_id = device["institution_id"]
    row = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=? AND status='Active'",
                       (inst_id, ems_employee_id)).fetchone()
    if not row:
        raise HTTPException(404, detail="Employee not found")
    e = _to_fr_employee(row, institution_today(conn, inst_id))
    return {"display_name": e["display_name"] if e["consent_display_name"] else None, "birthday": e["birthday"]}


@router.post("/attendance", response_model=FrAttendancePushResult, status_code=201)
@db_session
def fr_push_attendance(
    conn,
    payload: List[FrAttendanceRow],
    device: dict = Depends(get_device),
) -> Dict[str, Any]:
    """Idempotent batch upsert keyed on (employee_id, work_date) — unlike
    the live single-event webhook (device_clock_event), which rejects a
    repeat clock-in with a 400, this endpoint SETS both timestamps
    directly on every call, so FR re-sending a corrected or previously-
    failed day is always safe and never double-counts. Deliberately a
    separate code path from _do_clock_in/_do_clock_out (routers/
    attendance.py) rather than a reuse of either — those compute a live
    "is this late" status against the employee's shift and geofence,
    which doesn't apply to a batch of already-finalized punches with no
    shift/location context in the payload."""
    inst_id = device["institution_id"]
    if len(payload) > _MAX_BATCH:
        raise HTTPException(400, detail=f"Batch too large — max {_MAX_BATCH} rows per call")

    accepted = 0
    rejected: List[Dict[str, str]] = []
    now_iso = datetime.utcnow().isoformat()

    for row in payload:
        def reject(reason: str):
            rejected.append({"ems_employee_id": row.ems_employee_id, "work_date": row.work_date, "reason": reason})

        if not conn.execute(
            "SELECT 1 FROM employees WHERE employee_id=? AND institution_id=?",
            (row.ems_employee_id, inst_id),
        ).fetchone():
            reject("unknown_employee")
            continue

        try:
            date_cls.fromisoformat(row.work_date)
        except ValueError:
            reject("invalid_work_date")
            continue

        try:
            clock_in_dt = _parse_iso(row.clock_in_ts)
        except ValueError:
            reject("invalid_clock_in_ts")
            continue

        clock_out_dt = None
        if row.clock_out_ts:
            try:
                clock_out_dt = _parse_iso(row.clock_out_ts)
            except ValueError:
                reject("invalid_clock_out_ts")
                continue
            if clock_out_dt < clock_in_dt:
                reject("clock_out_before_clock_in")
                continue

        existing = conn.execute(
            "SELECT * FROM attendance_records WHERE employee_id=? AND institution_id=? AND work_date=?",
            (row.ems_employee_id, inst_id, row.work_date),
        ).fetchone()
        if existing and existing["status"] in _HR_FINALIZED_STATUSES:
            reject("day_already_finalized_by_hr")
            continue

        worked_minutes = int((clock_out_dt - clock_in_dt).total_seconds() // 60) if clock_out_dt else None
        clock_out_at = clock_out_dt.isoformat() if clock_out_dt else None
        clock_out_source = "device" if clock_out_dt else None
        clock_out_device_id = device["id"] if clock_out_dt else None

        try:
            if existing:
                conn.execute(
                    """
                    UPDATE attendance_records SET clock_in_at=?, clock_out_at=?, worked_minutes=?,
                    clock_in_source='device', clock_in_device_id=?, clock_out_source=?, clock_out_device_id=?,
                    status='Present', updated_at=? WHERE id=?
                    """,
                    (clock_in_dt.isoformat(), clock_out_at, worked_minutes, device["id"],
                     clock_out_source, clock_out_device_id, now_iso, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO attendance_records
                    (institution_id, employee_id, work_date, clock_in_at, clock_out_at, worked_minutes,
                     status, clock_in_source, clock_in_device_id, clock_out_source, clock_out_device_id,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'Present', 'device', ?, ?, ?, ?, ?)
                    """,
                    (inst_id, row.ems_employee_id, row.work_date, clock_in_dt.isoformat(), clock_out_at,
                     worked_minutes, device["id"], clock_out_source, clock_out_device_id, now_iso, now_iso),
                )
        except Exception:
            reject("db_error")
            continue
        accepted += 1

    conn.commit()
    return {
        "ok": True,
        "accepted": accepted,
        "rejected": rejected,
        "detail": f"{len(rejected)} row(s) rejected — see reasons" if rejected else None,
    }
