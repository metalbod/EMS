"""Claude self-service: who else is on leave on a given day (the MCP server's colleagues_on_leave tool).

Mirrors what EMS already shows every employee on the Home leave calendar (routers/leave.py's get_leave_calendar): colleagues'
names and dates of APPROVED leave, company-wide. It is deliberately narrower in one respect: it NEVER returns the leave type
(medical, maternity, ...), not even for HR, because what Claude says can be pasted into chats and notes. Pending or rejected
requests are never included. Public holidays and weekends are reported as non-working days with nobody listed (an approved range
that spans a weekend isn't "away" on the Saturday). The caller is left out of the list ("who *else*").
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.db_session import db_session
from core.deps import get_current_user, need_inst
from core.institution_time import institution_today

router = APIRouter()
MAX_DAYS = 31


def _parse(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(400, "Dates must look like 2026-10-14")


def _half_day(app, day: str) -> Optional[str]:
    """'morning' / 'afternoon' when the colleague is only off for half of this particular day."""
    if app["start_date"] == app["end_date"]:
        period = app["start_day_period"]
    elif day == app["start_date"]:
        period = app["start_day_period"]
    elif day == app["end_date"]:
        period = app["end_day_period"]
    else:
        period = None
    return {"AM": "morning", "PM": "afternoon"}.get(period)


@router.get("/api/me/leave-colleagues", tags=["leave"])
@db_session
def colleagues_on_leave(conn, date: Optional[str] = None, end_date: Optional[str] = None, department: Optional[str] = None,
                        user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    me = user.get("employee_id")
    if not me:
        raise HTTPException(400, "No employee record is linked to this account")
    start = _parse(date) if date else _parse(institution_today(conn, inst_id))
    end = _parse(end_date) if end_date else start
    if end < start:
        raise HTTPException(400, "end_date can't be before date")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(400, f"Ask for at most {MAX_DAYS} days at a time.")
    s, e = start.isoformat(), end.isoformat()

    sql = """
        SELECT a.employee_id, a.start_date, a.end_date, a.start_day_period, a.end_day_period,
               emp.full_name, emp.preferred_name, emp.department
        FROM leave_applications a
        JOIN employees emp ON emp.employee_id = a.employee_id AND emp.institution_id = a.institution_id
        WHERE a.institution_id=? AND a.status='Approved' AND a.start_date<=? AND a.end_date>=?
          AND emp.status='Active' AND a.employee_id<>?"""
    params: list = [inst_id, e, s, me]
    apps = conn.execute(sql, params).fetchall()
    if department:
        apps = [a for a in apps if (a["department"] or "").strip().lower() == department.strip().lower()]
    holidays = {r["date"]: r["name"] for r in conn.execute(
        "SELECT date, name FROM holidays WHERE institution_id=? AND date BETWEEN ? AND ?", (inst_id, s, e)).fetchall()}

    days: List[Dict[str, Any]] = []
    d = start
    while d <= end:
        ds = d.isoformat()
        entry: Dict[str, Any] = {"date": ds, "weekday": d.strftime("%a"), "non_working_day": None, "on_leave": []}
        if d.weekday() >= 5:
            entry["non_working_day"] = "Weekend"
        elif ds in holidays:
            entry["non_working_day"] = f"Public holiday: {holidays[ds]}"
        else:
            for a in sorted(apps, key=lambda x: (x["full_name"] or "").lower()):
                if a["start_date"] <= ds <= a["end_date"]:
                    entry["on_leave"].append({"name": a["preferred_name"] or a["full_name"], "full_name": a["full_name"],
                                              "department": a["department"], "half_day": _half_day(a, ds)})
        days.append(entry)
        d += timedelta(days=1)
    return {"from": s, "to": e, "department": department, "days": days}


@router.get("/api/me/public-holidays", tags=["leave"])
@db_session
def my_public_holidays(conn, date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 5,
                       user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """The company's public holidays from `date` (default today) onward: everything up to `end_date` if given, otherwise the next
    `limit` (1-50). The same list every employee already sees under Settings -> Holidays (GET /api/holidays), so there's nothing
    here that isn't company-wide knowledge. `date` and `end_date` the same day = "is that day a public holiday?"."""
    inst_id = need_inst(user)
    start = _parse(date) if date else _parse(institution_today(conn, inst_id))
    if end_date:
        end = _parse(end_date)
        if end < start:
            raise HTTPException(400, "end_date can't be before date")
        rows = conn.execute("SELECT date, name FROM holidays WHERE institution_id=? AND date BETWEEN ? AND ? ORDER BY date",
                            (inst_id, start.isoformat(), end.isoformat())).fetchall()
    else:
        rows = conn.execute("SELECT date, name FROM holidays WHERE institution_id=? AND date>=? ORDER BY date LIMIT ?",
                            (inst_id, start.isoformat(), min(max(1, limit), 50))).fetchall()
    out = []
    for r in rows:
        d0 = _parse(r["date"])
        out.append({"date": r["date"], "weekday": d0.strftime("%a"), "name": r["name"], "days_from_start": (d0 - start).days})
    return {"from": start.isoformat(), "to": end_date or None, "holidays": out}
