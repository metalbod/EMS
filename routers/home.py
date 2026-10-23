"""
Home — the few role-shaped figures the Today tab needs that no existing endpoint already answers.

Read-only, computed live in the institution's own timezone, scoped exactly like the Directory:

* GET /api/home/team-today (managers and HR) — who is in, away or not in yet today, who is away this week, and what
  is coming up (probation / contract ends). A manager sees their reporting chain (never themself); HR sees the
  whole company. **Never the leave type**, only that someone is away — the same line the Claude colleagues-on-leave
  tool draws. People lists are capped; counts are always complete.
* GET /api/employees/{employee_id}/attention — the profile page's "Needs attention": probation / contract ending,
  a last working day, and (HR only) expiring documents and unfinished onboarding/offboarding. Same scope as opening
  the record (employee: themself, manager: their chain, HR: anyone), 404 outside it; HR-only items are never sent to
  anyone else.
* GET /api/home/glance (anyone with an employee record) — the next pay day. Pay day is a company-wide date every
  employee is paid on, not an individual figure.

"Late or missing" is only meaningful where attendance rules exist (Settings > Attendance); without any, the tile
says so instead of showing a misleading zero (`attendance_configured`).
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from core.db_session import db_session
from core.deps import get_current_user, need_inst
from core.org_queries import is_self_or_subordinate, subordinates_in_clause
from routers.attendance import _parse_time, _pick_assignment_shift
from routers.dashboard import _institution_tz, next_occurrence
from routers.employee_documents import STATUS_CASE_SQL, _HR_ROLES

router = APIRouter()

TEAM_ROLES = ("manager", "hr_manager", "hr_admin", "superadmin")
PEOPLE_CAP = 6
COMING_UP_DAYS = 30
COMING_UP_CAP = 8


def _name(r) -> str:
    return (r["preferred_name"] or r["full_name"] or r["employee_id"]).strip()


def _person(r) -> Dict[str, str]:
    return {"employee_id": r["employee_id"], "name": _name(r)}


def _capped(rows) -> Dict[str, Any]:
    return {"count": len(rows), "people": [_person(r) for r in rows[:PEOPLE_CAP]]}


@router.get("/api/home/team-today")
@db_session
def team_today(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    if user["role"] not in TEAM_ROLES:
        raise HTTPException(403, "Not available for your role")
    inst_id = need_inst(user)
    own = user.get("employee_id") or ""
    tz = _institution_tz(conn, inst_id)
    now_local = datetime.now(tz).replace(tzinfo=None)
    today = now_local.date()
    today_s = today.isoformat()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    q = ("SELECT employee_id, full_name, preferred_name, department, start_date, probation_end_date, contract_end_date "
         "FROM employees WHERE institution_id=? AND status='Active' AND employee_id != ?")
    params: List[Any] = [inst_id, own]
    scope = "company"
    if user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, own)
        q += f" AND employee_id IN {frag}"
        params.extend(fp)
        scope = "team"
    people = conn.execute(q + " ORDER BY full_name", params).fetchall()
    ids = {p["employee_id"] for p in people}
    by_id = {p["employee_id"]: p for p in people}

    holiday = conn.execute("SELECT name FROM holidays WHERE institution_id=? AND date=?", (inst_id, today_s)).fetchone()
    non_working = today.weekday() >= 5 or bool(holiday)

    # Away this week (approved leave overlapping Mon-Sun); on leave today is the subset covering today.
    leave = conn.execute(
        "SELECT employee_id, start_date, end_date FROM leave_applications "
        "WHERE institution_id=? AND status='Approved' AND start_date <= ? AND end_date >= ?",
        (inst_id, sunday.isoformat(), monday.isoformat())).fetchall()
    leave = [l for l in leave if l["employee_id"] in ids]
    away_today = {l["employee_id"] for l in leave if str(l["start_date"])[:10] <= today_s <= str(l["end_date"])[:10]}
    week: Dict[str, Dict[str, str]] = {}
    for l in sorted(leave, key=lambda x: str(x["start_date"])):
        w = week.setdefault(l["employee_id"], {"start": str(l["start_date"])[:10], "end": str(l["end_date"])[:10]})
        w["end"] = max(w["end"], str(l["end_date"])[:10])
    away_week = [{**_person(by_id[e]), "start": w["start"], "end": w["end"]} for e, w in week.items()][:12]

    records = conn.execute(
        "SELECT employee_id, clock_in_at, status FROM attendance_records WHERE institution_id=? AND work_date=?",
        (inst_id, today_s)).fetchall()
    rec_by_emp = {r["employee_id"]: r for r in records if r["employee_id"] in ids}
    clocked_in = [by_id[e] for e, r in rec_by_emp.items() if r["clock_in_at"] and e not in away_today]
    flagged = {e for e, r in rec_by_emp.items() if r["status"] in ("Late", "Absent (Pending Review)")}

    # Required-attendance people whose clock-in deadline has passed with nothing recorded (read-only: the Review
    # screen is what materialises these as records).
    settings = conn.execute("SELECT * FROM attendance_settings WHERE institution_id=? AND is_active=1", (inst_id,)).fetchall()
    configured = bool(settings)
    if configured and not non_working:
        by_emp_set = {s["employee_id"]: s for s in settings if s["employee_id"]}
        by_dept_set = {s["department"]: s for s in settings if s["department"] and not s["employee_id"]}
        shifts = {s["id"]: s for s in conn.execute("SELECT * FROM shifts WHERE institution_id=? AND is_active=1", (inst_id,)).fetchall()}
        assigns: Dict[str, list] = {}
        for a in conn.execute(
            "SELECT esa.employee_id, esa.effective_from, esa.effective_to, s.* FROM employee_shift_assignments esa "
            "JOIN shifts s ON esa.shift_id=s.id WHERE esa.institution_id=? AND esa.is_active=1 AND s.is_active=1",
                (inst_id,)).fetchall():
            assigns.setdefault(a["employee_id"], []).append(a)
        for e in people:
            eid = e["employee_id"]
            if eid in rec_by_emp or eid in away_today:
                continue
            st = by_emp_set.get(eid) or by_dept_set.get(e["department"])
            if not st or not st["required"]:
                continue
            if e["start_date"] and str(e["start_date"])[:10] > today_s:
                continue
            shift = _pick_assignment_shift(assigns.get(eid, []), today_s) or (shifts.get(st["default_shift_id"]) if st["default_shift_id"] else None)
            if not shift:
                continue
            deadline = datetime.combine(today, _parse_time(shift["start_time"])) + timedelta(minutes=shift["grace_period_minutes"])
            if now_local > deadline:
                flagged.add(eid)
    late = [by_id[e] for e in flagged if e in by_id and e not in away_today]

    up: List[Dict[str, Any]] = []
    horizon = today + timedelta(days=COMING_UP_DAYS)
    for e in people:
        for col, kind in (("probation_end_date", "Probation ends"), ("contract_end_date", "Contract ends")):
            v = e[col]
            if not v:
                continue
            try:
                d = datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if today <= d <= horizon:
                up.append({**_person(e), "kind": kind, "date": d.isoformat(), "days": (d - today).days})
    up.sort(key=lambda x: (x["date"], x["name"]))

    return {
        "scope": scope, "date": today_s, "non_working_day": non_working, "holiday": holiday["name"] if holiday else None,
        "total_people": len(people), "attendance_configured": configured,
        "clocked_in": _capped(clocked_in), "on_leave": _capped([by_id[e] for e in sorted(away_today, key=lambda x: _name(by_id[x]))]),
        "late_or_missing": _capped(sorted(late, key=_name)),
        "away_this_week": away_week, "coming_up": up[:COMING_UP_CAP], "coming_up_days": COMING_UP_DAYS,
    }


@router.get("/api/home/glance")
@db_session
def glance(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    if user["role"] == "superadmin":
        return {"next_pay_date": None, "pay_days_until": None}
    inst_id = need_inst(user)
    tz = _institution_tz(conn, inst_id)
    today = datetime.now(tz).date()
    row = conn.execute("SELECT pay_day FROM institutions WHERE id=?", (inst_id,)).fetchone()
    if not row or not row["pay_day"]:
        return {"next_pay_date": None, "pay_days_until": None}
    nxt = next_occurrence(today, row["pay_day"])
    return {"next_pay_date": nxt.isoformat(), "pay_days_until": (nxt - today).days}


ATTENTION_DAYS = 30


@router.get("/api/employees/{employee_id}/attention")
@db_session
def employee_attention(conn, employee_id: str, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    role = user["role"]
    if role == "employee":
        allowed = employee_id == user.get("employee_id")
    elif role == "manager":
        allowed = is_self_or_subordinate(conn, inst_id, user.get("employee_id") or "", employee_id)
    else:
        allowed = True
    emp = conn.execute(
        "SELECT employee_id, status, probation_end_date, contract_end_date, last_working_day FROM employees "
        "WHERE employee_id=? AND institution_id=?", (employee_id, inst_id)).fetchone() if allowed else None
    if not emp:
        raise HTTPException(404, "Employee not found")   # same answer whether it doesn't exist or isn't yours to see

    today = datetime.now(_institution_tz(conn, inst_id)).date()
    items: List[Dict[str, Any]] = []

    def _days(v):
        try:
            return (datetime.strptime(str(v)[:10], "%Y-%m-%d").date() - today).days
        except (TypeError, ValueError):
            return None

    if emp["status"] == "Active":
        for col, label, kind in (("probation_end_date", "Probation ends", "probation"), ("contract_end_date", "Contract ends", "contract"),
                                 ("last_working_day", "Last working day", "last_day")):
            n = _days(emp[col])
            if n is not None and 0 <= n <= ATTENTION_DAYS:
                items.append({"kind": kind, "text": f"{label} {'today' if n == 0 else f'in {n} day' + ('' if n == 1 else 's')}", "date": str(emp[col])[:10], "days": n})

    if role in _HR_ROLES:
        docs = conn.execute(
            f"SELECT COUNT(*) AS n FROM employee_documents ed JOIN employee_document_types edt ON edt.id = ed.document_type_id "
            f"WHERE ed.institution_id=? AND ed.employee_id=? AND ({STATUS_CASE_SQL}) != 'ok'",
            (inst_id, employee_id)).fetchone()["n"]
        if docs:
            items.append({"kind": "documents", "text": f"{docs} document{'s' if docs != 1 else ''} expiring or expired", "tab": "vt-documents"})
        for c in conn.execute("SELECT type FROM ob_checklists WHERE institution_id=? AND employee_id=? AND status != 'Completed'",
                              (inst_id, employee_id)).fetchall():
            items.append({"kind": "checklist", "text": f"{str(c['type']).capitalize()} checklist not finished"})
    return {"employee_id": employee_id, "items": items}
