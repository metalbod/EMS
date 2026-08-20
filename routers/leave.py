"""Leave module: Types, Balances, and Applications (institution-scoped)."""
import calendar
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst, require_roles

from core.permission_matrix import require_permission

from core.org_queries import subordinates_in_clause

from core.validators import validate_logo_url

from core.leave_balance_ops import (
    _get_or_create_leave_balance, _consume_balance, _release_balance,
    _sweep_expired_carry_forward,
)

from core.approval_workflow import start_workflow, advance_or_finalize, filter_actionable

from db import get_db

from core.db_session import db_session

router = APIRouter()

# Roles that see WHAT KIND of leave someone is on in the Dashboard leave
# calendar (see get_leave_calendar below) — narrower than LEAVE_MANAGE_ROLES
# (which also includes superadmin, a platform-level role with no reason to
# see institution leave-type detail here) and specific to this one view, not
# a general "manages leave" permission.
LEAVE_CALENDAR_TYPE_VISIBLE_ROLES = ("hr_manager", "hr_admin")


class LeaveCalendarEntry(BaseModel):
    """One employee's leave span shown on the Dashboard leave calendar.
    leave_type_name is None for anyone outside LEAVE_CALENDAR_TYPE_VISIBLE_ROLES
    — set (or not) server-side in get_leave_calendar, not filtered client-side,
    so the type never reaches a non-HR browser's network response at all."""
    employee_id: str
    full_name: str
    preferred_name: Optional[str] = None
    start_date: str
    end_date: str
    days_count: float
    leave_type_name: Optional[str] = None


class LeaveTypeIn(BaseModel):
    name: str
    annual_entitlement: float = 14.0
    requires_approval: bool = True
    requires_attachment: bool = False
    is_paid: bool = True
    is_active: bool = True
    shares_entitlement_with_id: Optional[int] = None
    count_calendar_days: bool = False
    accrual_mode: str = "full_year"  # or "monthly" — see _accrued_days
    max_days_per_application: float = 0  # 0 = unlimited
    max_days_per_month: float = 0  # 0 = unlimited
    carry_forward_enabled: bool = False
    carry_forward_max_days: float = 0  # 0 = uncapped
    carry_forward_max_percent: float = 0  # 0 = uncapped, else 0-100
    carry_forward_expiry_days: int = 0  # 0 = never expires

    @field_validator("accrual_mode")
    @classmethod
    def _validate_accrual_mode(cls, v):
        if v not in ("full_year", "monthly"):
            raise ValueError("accrual_mode must be 'full_year' or 'monthly'")
        return v

    @field_validator("carry_forward_max_percent")
    @classmethod
    def _validate_carry_forward_max_percent(cls, v):
        if not (0 <= v <= 100):
            raise ValueError("carry_forward_max_percent must be between 0 and 100")
        return v

    @field_validator("carry_forward_expiry_days")
    @classmethod
    def _validate_carry_forward_expiry_days(cls, v):
        if v < 0:
            raise ValueError("carry_forward_expiry_days cannot be negative")
        return v


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
    # Which of the employee's projects a project_manager approval step (if
    # the applicable workflow has one) should route through — see
    # core/approval_workflow.py's PROJECT_MANAGER_MODULES. Ignored if the
    # workflow has no such step; a step with none picked just auto-skips.
    project_id: Optional[int] = None

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


def _compute_leave_days(conn, inst_id: int, start_date: str, end_date: str, count_calendar_days: bool = False) -> float:
    """Counts days in the inclusive range. Most leave types count only
    weekdays (Mon-Fri), excluding institution public holidays. Some types —
    Malaysian law requires this for Maternity/Paternity — count every
    calendar day instead, weekends and holidays included."""
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    if d1 < d0:
        raise HTTPException(400, "End date must be on or after start date")
    if count_calendar_days:
        return float((d1 - d0).days + 1)
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


def _accrued_days(annual_entitlement: float, join_date: Optional[str], as_of_date: str) -> float:
    """Monthly accrual: earned at the start of each calendar month, 1/12th
    of the annual entitlement per month, pro-rated in the join year from
    the employee's actual join month (a July joiner has earned 0/12 in
    January-June and starts earning from July). Evaluated as of the
    leave's own start date, not today — so booking December leave in
    January is judged against December's projected accrual. Rounded to
    the nearest half-day, matching every other day-count in this module."""
    as_of = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    join = datetime.strptime(join_date, "%Y-%m-%d").date() if join_date else date(as_of.year, 1, 1)
    if as_of.year > join.year:
        months_earned = as_of.month
    elif as_of.year == join.year:
        months_earned = max(0, as_of.month - join.month + 1)
    else:
        months_earned = 0  # as_of predates the employee's join entirely
    raw = annual_entitlement * months_earned / 12
    return round(raw * 2) / 2


def _days_in_month_range(conn, inst_id: int, start_date: str, end_date: str, count_calendar_days: bool, year: int, month: int) -> float:
    """How many of a [start_date, end_date] application's countable days
    fall within one specific calendar month — clips the range to that
    month's boundaries and reuses _compute_leave_days on the overlap."""
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    clipped_start = max(d0, month_start)
    clipped_end = min(d1, month_end)
    if clipped_start > clipped_end:
        return 0.0
    return _compute_leave_days(conn, inst_id, clipped_start.isoformat(), clipped_end.isoformat(), count_calendar_days)


def _month_buckets(conn, inst_id: int, start_date: str, end_date: str, count_calendar_days: bool) -> Dict[tuple, float]:
    """Splits an application's countable days across every calendar month
    it touches, e.g. 28 Jan - 3 Feb -> {(Y,1): 4, (Y,2): 3} — so a
    max-days-per-month cap can't be dodged by straddling a month boundary."""
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()
    buckets: Dict[tuple, float] = {}
    y, m = d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        days = _days_in_month_range(conn, inst_id, start_date, end_date, count_calendar_days, y, m)
        if days:
            buckets[(y, m)] = days
        m += 1
        if m > 12:
            m = 1
            y += 1
    return buckets


def _check_monthly_cap(conn, inst_id: int, employee_id: str, leave_type_id: int, count_calendar_days: bool,
                       start_date: str, end_date: str, max_days_per_month: float, exclude_app_id: Optional[int] = None):
    """Enforces max_days_per_month per calendar month the new application
    touches, counting Approved + Pending Approval applications of this same
    leave type (deliberately including Pending — several under-cap
    applications submitted at once shouldn't be able to collectively blow
    past the limit while they all sit awaiting approval)."""
    if not max_days_per_month:
        return
    new_buckets = _month_buckets(conn, inst_id, start_date, end_date, count_calendar_days)
    if not new_buckets:
        return
    q = "SELECT id, start_date, end_date FROM leave_applications WHERE institution_id=? AND employee_id=? AND leave_type_id=? AND status IN ('Approved', 'Pending Approval')"
    p = [inst_id, employee_id, leave_type_id]
    if exclude_app_id is not None:
        q += " AND id != ?"
        p.append(exclude_app_id)
    existing = conn.execute(q, p).fetchall()
    for (y, m), new_days in new_buckets.items():
        existing_days = sum(
            _days_in_month_range(conn, inst_id, r["start_date"], r["end_date"], count_calendar_days, y, m)
            for r in existing
        )
        total = existing_days + new_days
        if total > max_days_per_month:
            raise HTTPException(400, f"Exceeds the {max_days_per_month} day/month limit for {calendar.month_name[m]} {y} "
                                      f"({existing_days} already applied + {new_days} requested = {total})")


def _balance_leave_type_id(lt) -> int:
    """A leave type with shares_entitlement_with_id set draws from that
    other type's balance pool instead of its own — the application record
    still cites the specific type applied for, but this is the id to use
    for every balance check/deduction."""
    return lt["shares_entitlement_with_id"] or lt["id"]


def _validate_shares_entitlement(conn, inst_id: int, type_id: Optional[int], shares_with_id: Optional[int], name: str):
    """One level deep only: a type can't share with something that itself
    shares with another type, and a type that other types already share
    with can't be changed to share with something else — either direction
    would create a chain, which balance resolution doesn't walk."""
    if shares_with_id is None:
        return
    if type_id is not None and shares_with_id == type_id:
        raise HTTPException(400, "A leave type can't share entitlement with itself")
    target = conn.execute(
        "SELECT * FROM leave_types WHERE id=? AND institution_id=? AND is_active=1", (shares_with_id, inst_id)
    ).fetchone()
    if not target:
        raise HTTPException(404, "Shared leave type not found")
    if target["shares_entitlement_with_id"]:
        raise HTTPException(400, f"'{target['name']}' already shares entitlement with another leave type — can't chain shares")
    if type_id is not None:
        dependents = conn.execute(
            "SELECT 1 FROM leave_types WHERE shares_entitlement_with_id=? AND institution_id=? AND id!=?",
            (type_id, inst_id, type_id)
        ).fetchone()
        if dependents:
            raise HTTPException(400, f"'{name}' already has other leave types sharing its entitlement — can't also share with another type")




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
def create_leave_type(conn, body: LeaveTypeIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "leave.manage_leave_types")
    inst_id = need_inst(user)
    _validate_shares_entitlement(conn, inst_id, None, body.shares_entitlement_with_id, body.name)
    conn.execute(
        "INSERT INTO leave_types (institution_id,name,annual_entitlement,requires_approval,requires_attachment,is_paid,is_active,shares_entitlement_with_id,count_calendar_days,accrual_mode,max_days_per_application,max_days_per_month,carry_forward_enabled,carry_forward_max_days,carry_forward_max_percent,carry_forward_expiry_days) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (inst_id, body.name, body.annual_entitlement, 1 if body.requires_approval else 0,
         1 if body.requires_attachment else 0, 1 if body.is_paid else 0, 1 if body.is_active else 0,
         body.shares_entitlement_with_id, 1 if body.count_calendar_days else 0,
         body.accrual_mode, body.max_days_per_application, body.max_days_per_month,
         1 if body.carry_forward_enabled else 0, body.carry_forward_max_days,
         body.carry_forward_max_percent, body.carry_forward_expiry_days)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leave_types WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/leave/types/{type_id}")
@db_session
def update_leave_type(conn, type_id: int, body: LeaveTypeIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "leave.manage_leave_types")
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM leave_types WHERE id=? AND institution_id=?", (type_id, inst_id)).fetchone():
        raise HTTPException(404, "Leave type not found")
    _validate_shares_entitlement(conn, inst_id, type_id, body.shares_entitlement_with_id, body.name)
    conn.execute(
        "UPDATE leave_types SET name=?,annual_entitlement=?,requires_approval=?,requires_attachment=?,is_paid=?,is_active=?,shares_entitlement_with_id=?,count_calendar_days=?,accrual_mode=?,max_days_per_application=?,max_days_per_month=?,carry_forward_enabled=?,carry_forward_max_days=?,carry_forward_max_percent=?,carry_forward_expiry_days=? WHERE id=?",
        (body.name, body.annual_entitlement, 1 if body.requires_approval else 0,
         1 if body.requires_attachment else 0, 1 if body.is_paid else 0, 1 if body.is_active else 0,
         body.shares_entitlement_with_id, 1 if body.count_calendar_days else 0,
         body.accrual_mode, body.max_days_per_application, body.max_days_per_month,
         1 if body.carry_forward_enabled else 0, body.carry_forward_max_days,
         body.carry_forward_max_percent, body.carry_forward_expiry_days, type_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM leave_types WHERE id=?", (type_id,)).fetchone()
    return dict(row)


@router.delete("/api/leave/types/{type_id}", status_code=204)
@db_session
def delete_leave_type(conn, type_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "leave.manage_leave_types")
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
        SELECT b.*, lt.name AS leave_type_name, lt.accrual_mode, e.full_name AS employee_name,
               e.preferred_name AS employee_preferred_name, e.department, e.start_date AS employee_start_date
        FROM leave_balances b
        JOIN leave_types lt ON lt.id = b.leave_type_id
        JOIN employees e ON e.employee_id = b.employee_id AND e.institution_id = b.institution_id
        WHERE b.institution_id=? AND b.year=?
    """
    p: list = [inst_id, year]
    if user["role"] == "employee":
        q += " AND b.employee_id=?"; p.append(user.get("employee_id", ""))
    elif user["role"] == "manager":
        # Default to the manager's own balances — this is what "My Leave"
        # wants, not blended-in rows from every subordinate. An explicit
        # employee_id (e.g. previewing balance before applying leave on
        # someone's behalf) is honored as given, unrestricted — matching
        # create_leave_application below, which already lets a manager
        # submit for any active employee, not just their own reports.
        q += " AND b.employee_id=?"; p.append(employee_id or user.get("employee_id", ""))
    elif employee_id:
        q += " AND b.employee_id=?"; p.append(employee_id)
    q += " ORDER BY e.full_name, lt.name"
    rows = conn.execute(q, p).fetchall()
    # Ensure every active leave type has a balance row for the employees being viewed, so
    # a type created after an employee joined still shows up with its default entitlement.
    if user["role"] in ("employee",) and user.get("employee_id"):
        # Types that share entitlement with another type never get their own
        # balance row — their pool is the shared type's row, which is already
        # covered by that type's own entry in this loop.
        types = conn.execute(
            "SELECT id FROM leave_types WHERE institution_id=? AND is_active=1 AND shares_entitlement_with_id IS NULL",
            (inst_id,)
        ).fetchall()
        existing_type_ids = {r["leave_type_id"] for r in rows}
        missing = [t["id"] for t in types if t["id"] not in existing_type_ids]
        if missing:
            for tid in missing:
                _get_or_create_leave_balance(conn, inst_id, user["employee_id"], tid, year)
            conn.commit()
            rows = conn.execute(q, p).fetchall()
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for r in rows:
        d = dict(r)
        # Forfeit any carry-forward that's past its expiry before reporting
        # the balance — otherwise this list could show a carried-forward
        # amount that's already lapsed until something else (an application)
        # happens to touch that row and trigger the sweep. Updated in-memory
        # directly (rather than using _sweep_expired_carry_forward's own
        # re-fetched row) since that row is leave_balances columns only and
        # would drop this query's joined employee_name/leave_type_name.
        expires_on = d["carried_forward_expires_on"]
        remaining = d["carried_forward_days"] - d["carried_forward_used_days"]
        if expires_on and expires_on <= today and remaining > 0:
            _sweep_expired_carry_forward(conn, r)
            d["carried_forward_forfeited_days"] += remaining
            d["carried_forward_days"] = d["carried_forward_used_days"]
        d["accrued_days"] = (
            _accrued_days(d["entitled_days"], d["employee_start_date"], today)
            if d["accrual_mode"] == "monthly" else d["entitled_days"]
        )
        out.append(d)
    return out


@router.patch("/api/leave/balances/{balance_id}")
@db_session
def adjust_leave_balance(conn, balance_id: int, body: LeaveBalanceAdjustIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "leave.adjust_leave_balance")
    inst_id = need_inst(user)
    bal = conn.execute("SELECT * FROM leave_balances WHERE id=? AND institution_id=?", (balance_id, inst_id)).fetchone()
    if not bal:
        raise HTTPException(404, "Balance not found")
    entitled = body.entitled_days if body.entitled_days is not None else bal["entitled_days"]
    carried = body.carried_forward_days if body.carried_forward_days is not None else bal["carried_forward_days"]
    # A manual reduction of carried_forward_days below what's already been
    # consumed from it would otherwise leave carried_forward_used_days >
    # carried_forward_days — clamp the used-tracker down to match so
    # "remaining carry-forward" can never go negative.
    carried_used = min(bal["carried_forward_used_days"], carried)
    conn.execute(
        "UPDATE leave_balances SET entitled_days=?,carried_forward_days=?,carried_forward_used_days=? WHERE id=?",
        (entitled, carried, carried_used, balance_id)
    )
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
        SELECT a.*, lt.name AS leave_type_name, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name, e.department, e.designation
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
    result = [dict(r) for r in rows]
    if user["role"] != "employee":
        result = filter_actionable(conn, inst_id, "leave", result, user)
    return result


@router.get("/api/leave/calendar", response_model=List[LeaveCalendarEntry])
@db_session
def get_leave_calendar(conn, year: int, month: int, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Institution-wide Approved leave for a given month, for the Dashboard's
    leave calendar. Unlike list_leave_applications above (scoped to a
    manager's own reporting chain, or an employee's own applications), this
    is deliberately institution-wide for every caller — HR Manager/HR Admin
    and everyone else with Leave-tab access alike see who's out; only
    LEAVE_CALENDAR_TYPE_VISIBLE_ROLES also see what kind of leave (see
    LeaveCalendarEntry's docstring).

    Access mirrors the Dashboard Leave tab's own visibility rule (see
    static/js/dashboard.js's canViewLeaveDash/hasEmployeeRecord toggle):
    anyone with a linked employee record, plus HR Manager/HR Admin even
    without one.
    """
    inst_id = need_inst(user)
    if not (user.get("employee_id") or user["role"] in LEAVE_CALENDAR_TYPE_VISIBLE_ROLES):
        raise HTTPException(403, "Access denied")
    if not (1 <= month <= 12):
        raise HTTPException(400, "month must be between 1 and 12")

    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1).isoformat()
    month_end = date(year, month, last_day).isoformat()

    rows = conn.execute("""
        SELECT a.employee_id, e.full_name, e.preferred_name, a.start_date, a.end_date, a.days_count, lt.name AS leave_type_name
        FROM leave_applications a
        JOIN employees e ON e.employee_id = a.employee_id AND e.institution_id = a.institution_id
        JOIN leave_types lt ON lt.id = a.leave_type_id
        WHERE a.institution_id=? AND a.status='Approved'
          AND a.start_date <= ? AND a.end_date >= ?
        ORDER BY a.start_date
    """, (inst_id, month_end, month_start)).fetchall()

    can_see_type = user["role"] in LEAVE_CALENDAR_TYPE_VISIBLE_ROLES
    result = []
    for r in rows:
        entry = dict(r)
        if not can_see_type:
            entry["leave_type_name"] = None
        result.append(entry)
    return result


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

    days = _compute_leave_days(conn, inst_id, body.start_date, body.end_date, bool(lt["count_calendar_days"]))
    if days <= 0:
        raise HTTPException(400, "Selected date range has no working days to apply (all weekends/public holidays)")

    if lt["max_days_per_application"] and days > lt["max_days_per_application"]:
        raise HTTPException(400, f"'{lt['name']}' allows at most {lt['max_days_per_application']} day(s) per application — requested {days}")

    _check_monthly_cap(conn, inst_id, body.employee_id, body.leave_type_id, bool(lt["count_calendar_days"]),
                       body.start_date, body.end_date, lt["max_days_per_month"])

    year = datetime.strptime(body.start_date, "%Y-%m-%d").year
    balance = _get_or_create_leave_balance(conn, inst_id, body.employee_id, _balance_leave_type_id(lt), year)
    if lt["accrual_mode"] == "monthly":
        entitled_for_check = _accrued_days(balance["entitled_days"], emp["start_date"], body.start_date)
    else:
        entitled_for_check = balance["entitled_days"]
    available = entitled_for_check + balance["carried_forward_days"] - balance["used_days"]
    if days > available:
        raise HTTPException(400, f"Insufficient balance: requesting {days} day(s), only {available} available")

    status = "Pending Approval" if lt["requires_approval"] else "Approved"
    workflow_id, step_order = None, None
    if status == "Pending Approval":
        project_ids = {body.project_id} if body.project_id else set()
        workflow_id, step_order, auto_approved = start_workflow(conn, inst_id, "leave", body.employee_id, project_ids)
        if auto_approved:
            status = "Approved"
    conn.execute(
        "INSERT INTO leave_applications (institution_id,employee_id,leave_type_id,start_date,end_date,days_count,status,reason,attachment,requested_by,approval_workflow_id,approval_step,project_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (inst_id, body.employee_id, body.leave_type_id, body.start_date, body.end_date, days, status,
         body.reason, body.attachment, user["username"], workflow_id, step_order, body.project_id)
    )
    app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    if status == "Approved":
        _consume_balance(conn, balance, days)

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
        if application["status"] != "Pending Approval":
            raise HTTPException(400, f"Application is already {application['status']}")
        action = "reject" if body.status == "Rejected" else "approve"
        if application["approval_workflow_id"] and application["approval_step"] is not None:
            try:
                project_ids = {application["project_id"]} if application["project_id"] else set()
                outcome, next_step = advance_or_finalize(
                    conn, inst_id, "leave", application["employee_id"],
                    application["approval_workflow_id"], application["approval_step"], action, user, project_ids
                )
            except PermissionError as e:
                raise HTTPException(403, str(e))
        else:
            # Legacy row with no workflow assigned (predates this engine) —
            # fall back to the old blanket role check rather than getting stuck.
            if user["role"] not in ("superadmin", "hr_manager", "hr_admin", "manager"):
                raise HTTPException(403, "Only a manager or HR can approve/reject leave")
            outcome = "rejected" if action == "reject" else "approved"
            next_step = None

        if outcome == "advanced":
            conn.execute("UPDATE leave_applications SET approval_step=?,notes=? WHERE id=?",
                         (next_step, body.notes, app_id))
            _log_leave(conn, inst_id, app_id, application["employee_id"], "Approval Advanced",
                       f"Step {application['approval_step']} cleared by {user['username']} — now awaiting step {next_step}", user)
            conn.commit()
            return dict(conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone())

        final_status = "Approved" if outcome == "approved" else "Rejected"
        if final_status == "Approved":
            year = datetime.strptime(application["start_date"], "%Y-%m-%d").year
            lt = conn.execute("SELECT * FROM leave_types WHERE id=?", (application["leave_type_id"],)).fetchone()
            balance = _get_or_create_leave_balance(conn, inst_id, application["employee_id"], _balance_leave_type_id(lt), year)
            _consume_balance(conn, balance, application["days_count"])
        approved_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") if final_status == "Approved" else None
        conn.execute("UPDATE leave_applications SET status=?,approved_by=?,approved_at=?,notes=?,approval_step=NULL WHERE id=?",
                     (final_status, user["username"], approved_at, body.notes, app_id))
    elif body.status == "Cancelled":
        if user["role"] == "employee" and user.get("employee_id") != application["employee_id"]:
            raise HTTPException(403, "Access denied")
        if application["status"] not in ("Pending Approval", "Approved"):
            raise HTTPException(400, f"Application is already {application['status']}")
        if application["status"] == "Approved":
            year = datetime.strptime(application["start_date"], "%Y-%m-%d").year
            lt = conn.execute("SELECT * FROM leave_types WHERE id=?", (application["leave_type_id"],)).fetchone()
            balance = _get_or_create_leave_balance(conn, inst_id, application["employee_id"], _balance_leave_type_id(lt), year)
            _release_balance(conn, balance, application["days_count"])
        conn.execute("UPDATE leave_applications SET status='Cancelled',notes=? WHERE id=?", (body.notes, app_id))

    _log_leave(conn, inst_id, app_id, application["employee_id"], f"Status changed to {body.status}",
               body.notes or "", user)
    conn.commit()
    row = conn.execute("SELECT * FROM leave_applications WHERE id=?", (app_id,)).fetchone()
    return dict(row)


@router.get("/api/leave/dashboard/utilization")
@db_session
def get_leave_utilization_dashboard(conn, year: Optional[int] = None,
                                    user: dict = Depends(require_roles("hr_manager", "hr_admin"))) -> Dict[str, Any]:
    # NOT retrofitted onto require_permission() — a dedicated test
    # (test_leave_utilization_dashboard_superadmin_denied) confirms
    # excluding superadmin here is deliberate, not an oversight, and
    # require_permission()'s standard "superadmin always passes" rule
    # would silently break that. Leave this on its own explicit
    # require_roles(...) gate instead of adding it to the pilot.
    """Institution-wide leave utilization for the HR dashboard's Leave tab:
    usage by leave type, and the 10 employees with the highest and lowest
    overall utilization (their leave_balances rows summed across every
    type they have a balance for). A leave type that shares entitlement
    with another never has its own balance row (see _balance_leave_type_id),
    so this naturally aggregates shared usage under the pool's own type —
    there's no double-counting to guard against."""
    inst_id = need_inst(user)
    year = year or datetime.now().year

    by_type = conn.execute("""
        SELECT lt.id AS leave_type_id, lt.name AS leave_type_name,
               SUM(b.entitled_days + b.carried_forward_days) AS total_entitled,
               SUM(b.used_days) AS total_used
        FROM leave_balances b
        JOIN leave_types lt ON lt.id = b.leave_type_id
        WHERE b.institution_id=? AND b.year=?
        GROUP BY lt.id, lt.name
        ORDER BY lt.name
    """, (inst_id, year)).fetchall()
    by_type_out = [{
        "leave_type_id": r["leave_type_id"], "leave_type_name": r["leave_type_name"],
        "total_entitled": r["total_entitled"], "total_used": r["total_used"],
        "utilization_percent": round(r["total_used"] / r["total_entitled"] * 100, 1) if r["total_entitled"] else 0.0,
    } for r in by_type]

    emp_rows = conn.execute("""
        SELECT b.employee_id, e.full_name, e.preferred_name, e.department,
               SUM(b.entitled_days + b.carried_forward_days) AS total_entitled,
               SUM(b.used_days) AS total_used
        FROM leave_balances b
        JOIN employees e ON e.employee_id = b.employee_id AND e.institution_id = b.institution_id
        WHERE b.institution_id=? AND b.year=? AND e.status='Active'
        GROUP BY b.employee_id, e.full_name, e.preferred_name, e.department
        HAVING SUM(b.entitled_days + b.carried_forward_days) > 0
    """, (inst_id, year)).fetchall()

    def _breakdown(employee_id: str):
        rows = conn.execute("""
            SELECT lt.name AS leave_type_name, b.entitled_days, b.carried_forward_days, b.used_days
            FROM leave_balances b
            JOIN leave_types lt ON lt.id = b.leave_type_id
            WHERE b.employee_id=? AND b.institution_id=? AND b.year=?
            ORDER BY lt.name
        """, (employee_id, inst_id, year)).fetchall()
        out = []
        for r in rows:
            entitled = r["entitled_days"] + r["carried_forward_days"]
            out.append({
                "leave_type_name": r["leave_type_name"], "entitled_days": entitled, "used_days": r["used_days"],
                "utilization_percent": round(r["used_days"] / entitled * 100, 1) if entitled else 0.0,
            })
        return out

    ranked = [{
        "employee_id": r["employee_id"], "full_name": r["full_name"], "preferred_name": r["preferred_name"], "department": r["department"],
        "total_entitled": r["total_entitled"], "total_used": r["total_used"],
        "utilization_percent": round(r["total_used"] / r["total_entitled"] * 100, 1),
    } for r in emp_rows]
    ranked.sort(key=lambda e: e["utilization_percent"], reverse=True)

    top_highest = ranked[:10]
    top_lowest = sorted(ranked, key=lambda e: e["utilization_percent"])[:10]
    for e in top_highest + top_lowest:
        e["breakdown"] = _breakdown(e["employee_id"])

    return {"year": year, "by_type": by_type_out, "top_highest": top_highest, "top_lowest": top_lowest}


@router.get("/api/employees/{employee_id}/leave-history")
@db_session
def get_employee_leave_history(conn, employee_id: str, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    require_permission(conn, user, "leave.view_leave_audit_history")
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM leave_audit_log WHERE employee_id=? AND institution_id=? ORDER BY created_at ASC",
        (employee_id, inst_id)
    ).fetchall()
    return [dict(r) for r in rows]
