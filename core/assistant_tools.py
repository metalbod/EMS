"""Tool implementations for the AI assistant chatbot (routers/assistant.py).

Each function is a thin wrapper around the SAME logic the existing
self-service REST endpoints already use — never a reimplementation. This
means the assistant automatically stays correct as leave/payroll/benefits/
timesheet logic evolves elsewhere, with zero duplicated SQL.

Security model: every wrapper takes only `user: dict` — never anything a
Claude tool-call could supply — and the *tool dispatch table* in
routers/assistant.py only ever reads `block.name`, never `block.input`. So
there is no code path, anywhere, for the model to ask for another
employee's data.

Two families:
  - Self-scoped (get_*): force role="employee" on a copy of the caller's
    user dict before delegating, so the underlying self-filter branches in
    list_leave_balances/list_timesheets/list_overtime fire regardless of
    the caller's real role. Without this, a manager/HR/superadmin asking
    "my" question would fall through to those functions' non-employee
    branches, which return institution-wide or team-wide data.
  - Team-scoped (get_team_*): pass the REAL user through unmodified, so
    the callee's own manager-scoping (subordinates_in_clause, already
    used by these same functions for their normal HR-facing callers)
    resolves "team" from the manager's own employee_id. Still no
    model-supplied employee_id anywhere.
"""
import asyncio

from fastapi import HTTPException

try:
    from routers.leave import list_leave_balances
    from routers.payroll import my_payslips
    from routers.benefits import list_my_enrollments, list_my_claims, list_claims
    from routers.timesheets import list_timesheets
    from routers.overtime import list_overtime
except ImportError:
    from ems.routers.leave import list_leave_balances
    from ems.routers.payroll import my_payslips
    from ems.routers.benefits import list_my_enrollments, list_my_claims, list_claims
    from ems.routers.timesheets import list_timesheets
    from ems.routers.overtime import list_overtime


def _self_scoped_user(user: dict) -> dict:
    return {**user, "role": "employee"}


def _err(e: HTTPException) -> dict:
    return {"error": e.detail}


# ---------------------------------------------------------------------------
# Self-scoped
# ---------------------------------------------------------------------------

async def get_leave_balance(user: dict) -> dict:
    try:
        rows = await asyncio.to_thread(list_leave_balances, employee_id=None, year=None, user=_self_scoped_user(user))
    except HTTPException as e:
        return _err(e)
    return {"leave_balances": [
        {
            "leave_type": r["leave_type_name"],
            "entitled_days": r["entitled_days"],
            "accrued_days": r["accrued_days"],
            "used_days": r["used_days"],
            "carried_forward_days_remaining": r["carried_forward_days"] - r["carried_forward_used_days"],
            "carried_forward_expires_on": r["carried_forward_expires_on"],
        }
        for r in rows
    ]}


async def get_payslips(user: dict) -> dict:
    try:
        rows = await asyncio.to_thread(my_payslips, user=_self_scoped_user(user))
    except HTTPException as e:
        return _err(e)
    return {"payslips": [
        {
            "period_start": r["period_start"],
            "period_end": r["period_end"],
            "salary_type": r["salary_type"],
            "gross_pay": r["gross_pay"],
            "net_pay": r["net_pay"],
            "epf_employee": r["epf_employee"],
            "socso_employee": r["socso_employee"],
            "eis_employee": r["eis_employee"],
            "pcb": r["pcb"],
        }
        for r in rows
    ]}


async def get_benefits_enrollments(user: dict) -> dict:
    try:
        rows = await list_my_enrollments(current_user=_self_scoped_user(user))
    except HTTPException as e:
        return _err(e)
    return {"enrollments": [
        {"plan_name": r.plan_name, "plan_category": r.plan_category, "status": r.status}
        for r in rows
    ]}


async def get_benefits_claims(user: dict) -> dict:
    try:
        rows = await list_my_claims(current_user=_self_scoped_user(user))
    except HTTPException as e:
        return _err(e)
    return {"claims": [
        {
            "plan_name": r.plan_name, "plan_category": r.plan_category,
            "claim_date": r.claim_date, "amount_claimed": r.amount_claimed,
            "amount_approved": r.amount_approved, "status": r.status,
        }
        for r in rows
    ]}


async def get_timesheets(user: dict) -> dict:
    try:
        rows = await asyncio.to_thread(list_timesheets, status=None, user=_self_scoped_user(user))
    except HTTPException as e:
        return _err(e)
    return {"timesheets": [
        {
            "period_start": r["period_start"], "period_end": r["period_end"],
            "status": r["status"], "total_hours": r["total_hours"],
        }
        for r in rows
    ]}


async def get_overtime(user: dict) -> dict:
    try:
        rows = await asyncio.to_thread(list_overtime, status=None, user=_self_scoped_user(user))
    except HTTPException as e:
        return _err(e)
    return {"overtime_records": [
        {
            "work_date": r["work_date"], "overtime_hours": r["overtime_hours"],
            "status": r["status"], "conversion_mode": r["conversion_mode"],
            "leave_days_credited": r["leave_days_credited"], "pay_amount": r["pay_amount"],
        }
        for r in rows
    ]}


# ---------------------------------------------------------------------------
# Team-scoped (manager only — dispatch table only offers these when
# user["role"] == "manager"; the real, unmodified user is passed through so
# these functions' own existing manager-scoping resolves "team" server-side)
# ---------------------------------------------------------------------------

async def get_team_leave_balance(user: dict) -> dict:
    try:
        rows = await asyncio.to_thread(list_leave_balances, employee_id=None, year=None, user=user)
    except HTTPException as e:
        return _err(e)
    return {"team_leave_balances": [
        {
            "employee_name": r["employee_name"],
            "leave_type": r["leave_type_name"],
            "entitled_days": r["entitled_days"],
            "accrued_days": r["accrued_days"],
            "used_days": r["used_days"],
            "carried_forward_days_remaining": r["carried_forward_days"] - r["carried_forward_used_days"],
        }
        for r in rows
    ]}


async def get_team_timesheets(user: dict) -> dict:
    try:
        rows = await asyncio.to_thread(list_timesheets, status=None, user=user)
    except HTTPException as e:
        return _err(e)
    return {"team_timesheets": [
        {
            "employee_name": r["employee_name"], "period_start": r["period_start"],
            "period_end": r["period_end"], "status": r["status"], "total_hours": r["total_hours"],
        }
        for r in rows
    ]}


async def get_team_benefits_claims(user: dict) -> dict:
    try:
        rows = await list_claims(status=None, current_user=user)
    except HTTPException as e:
        return _err(e)
    return {"team_claims": [
        {
            "employee_name": r.employee_name, "plan_name": r.plan_name,
            "claim_date": r.claim_date, "amount_claimed": r.amount_claimed,
            "status": r.status,
        }
        for r in rows
    ]}
