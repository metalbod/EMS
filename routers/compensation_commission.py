"""Compensation: Variable Pay — Commission Structures, Plans, and Entries.
One of six routers split out of the former single routers/compensation.py."""
import logging
from typing import List
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from core.db_session import db_session
from core.deps import get_current_user
from core.compensation_helpers import add_hr_note as _add_hr_note
from core.permission_matrix import require_permission
from core.compensation_schemas import (
    CommissionPlanCreate, CommissionPlanUpdate, CommissionPlanResponse,
    CommissionEntryCreate, CommissionEntryDecide, CommissionEntryResponse, CommissionEntryWithEmployee,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])

# ============================================================================
# VARIABLE PAY: COMMISSION STRUCTURE ENDPOINTS
# ============================================================================

@router.post("/commission-plans", status_code=201)
@db_session
def create_commission_plan(
    conn,
    payload: CommissionPlanCreate,
    current_user: dict = Depends(get_current_user),
) -> CommissionPlanResponse:
    """Create a commission plan."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    now = datetime.utcnow().isoformat()

    conn.execute(
        """
        INSERT INTO commission_plans
        (institution_id, plan_name, plan_type, default_rate_percent, plan_year,
         period_start, period_end, description, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
        """,
        (inst_id, payload.plan_name, payload.plan_type, payload.default_rate_percent,
         payload.plan_year, payload.period_start, payload.period_end,
         payload.description, now, now),
    )
    conn.commit()
    plan_id = conn._last_id

    plan = conn.execute("SELECT * FROM commission_plans WHERE id = ?", (plan_id,)).fetchone()
    return CommissionPlanResponse(**dict(plan))



@router.get("/commission-plans")
@db_session
def list_commission_plans(
    conn,
    current_user: dict = Depends(get_current_user),
) -> List[CommissionPlanResponse]:
    """List commission plans."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    plans = conn.execute(
        "SELECT * FROM commission_plans WHERE institution_id = ? ORDER BY plan_year DESC, id DESC",
        (inst_id,),
    ).fetchall()
    return [CommissionPlanResponse(**dict(p)) for p in plans]


@router.put("/commission-plans/{plan_id}")
@db_session
def update_commission_plan(
    conn,
    plan_id: int,
    payload: CommissionPlanUpdate,
    current_user: dict = Depends(get_current_user),
) -> CommissionPlanResponse:
    """Update a commission plan (name, status, default rate, description)."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    plan = conn.execute(
        "SELECT * FROM commission_plans WHERE id = ? AND institution_id = ?",
        (plan_id, inst_id),
    ).fetchone()
    if not plan:
        raise HTTPException(404, detail="Commission plan not found")

    updates = {
        "plan_name": payload.plan_name if payload.plan_name is not None else plan["plan_name"],
        "status": payload.status if payload.status is not None else plan["status"],
        "default_rate_percent": payload.default_rate_percent if payload.default_rate_percent is not None else plan["default_rate_percent"],
        "description": payload.description if payload.description is not None else plan["description"],
        "updated_at": datetime.utcnow().isoformat(),
    }
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    conn.execute(f"UPDATE commission_plans SET {set_clause} WHERE id = ?", (*updates.values(), plan_id))
    conn.commit()

    updated = conn.execute("SELECT * FROM commission_plans WHERE id = ?", (plan_id,)).fetchone()
    return CommissionPlanResponse(**dict(updated))



@router.get("/commission-plans/{plan_id}/entries")
@db_session
def list_commission_entries(
    conn,
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[CommissionEntryWithEmployee]:
    """List commission entries for a plan, with employee names joined in."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

    plan = conn.execute(
        "SELECT * FROM commission_plans WHERE id = ? AND institution_id = ?",
        (plan_id, inst_id),
    ).fetchone()
    if not plan:
        raise HTTPException(404, detail="Commission plan not found")

    # employee_id is only unique per institution, so the join must also
    # match institution_id — see the pay-equity report fix for the same
    # cross-tenant-fan-out pattern.
    rows = conn.execute(
        """
        SELECT c.*, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name
        FROM commission_entries c
        JOIN employees e ON c.employee_id = e.employee_id AND c.institution_id = e.institution_id
        WHERE c.commission_plan_id = ? AND c.institution_id = ?
        ORDER BY c.created_at DESC
        """,
        (plan_id, inst_id),
    ).fetchall()
    return [CommissionEntryWithEmployee(**dict(r)) for r in rows]


@router.post("/commission-entries", status_code=201)
@db_session
def create_commission_entry(
    conn,
    commission_plan_id: int,
    payload: CommissionEntryCreate,
    current_user: dict = Depends(get_current_user),
) -> CommissionEntryResponse:
    """Record a sales/attainment entry for an employee under a commission
    plan. The commission amount is calculated server-side from
    sales_amount x commission_rate_percent and stored, so a later change
    to the plan's default rate never retroactively alters this entry."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    user_id = current_user.get("id")

    plan = conn.execute(
        "SELECT * FROM commission_plans WHERE id = ? AND institution_id = ?",
        (commission_plan_id, inst_id),
    ).fetchone()
    if not plan:
        raise HTTPException(404, detail="Commission plan not found")

    employee = conn.execute(
        "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
        (payload.employee_id, inst_id),
    ).fetchone()
    if not employee:
        raise HTTPException(404, detail="Employee not found")

    calculated_commission = round(payload.sales_amount * payload.commission_rate_percent / 100, 2)

    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO commission_entries
        (institution_id, commission_plan_id, employee_id, sales_amount, quota_target,
         commission_rate_percent, calculated_commission, notes, recommended_by_user_id,
         status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
        """,
        (inst_id, commission_plan_id, payload.employee_id, payload.sales_amount,
         payload.quota_target, payload.commission_rate_percent, calculated_commission,
         payload.notes, user_id, now, now),
    )
    # Capture this INSERT's id before the HR note INSERT overwrites
    # conn._last_id.
    entry_id = conn._last_id

    note_body = (
        f"Commission entry of RM {calculated_commission:,.2f} "
        f"(RM {payload.sales_amount:,.2f} sales @ {payload.commission_rate_percent}%) "
        f"proposed under '{plan['plan_name']}' ({plan['plan_type']})."
    )
    if payload.notes:
        note_body += f" Notes: {payload.notes}"
    _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

    conn.commit()

    entry = conn.execute("SELECT * FROM commission_entries WHERE id = ?", (entry_id,)).fetchone()
    return CommissionEntryResponse(**dict(entry))



@router.put("/commission-entries/{entry_id}")
@db_session
def decide_commission_entry(
    conn,
    entry_id: int,
    payload: CommissionEntryDecide,
    current_user: dict = Depends(get_current_user),
) -> CommissionEntryResponse:
    """Approve or reject a commission entry."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
    user_id = current_user.get("id")

    entry = conn.execute(
        "SELECT * FROM commission_entries WHERE id = ? AND institution_id = ?",
        (entry_id, inst_id),
    ).fetchone()
    if not entry:
        raise HTTPException(404, detail="Commission entry not found")

    plan = conn.execute("SELECT plan_name FROM commission_plans WHERE id = ?", (entry["commission_plan_id"],)).fetchone()
    plan_name = plan["plan_name"] if plan else "commission plan"

    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        UPDATE commission_entries
        SET status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
        WHERE id = ?
        """,
        (payload.status, user_id, now, now, entry_id),
    )

    note_body = (
        f"Commission entry of RM {float(entry['calculated_commission']):,.2f} under '{plan_name}' "
        f"was {payload.status.lower()} by {current_user['username']}."
    )
    _add_hr_note(conn, inst_id, entry["employee_id"], note_body, current_user["username"])

    conn.commit()

    updated = conn.execute("SELECT * FROM commission_entries WHERE id = ?", (entry_id,)).fetchone()
    return CommissionEntryResponse(**dict(updated))



@router.put("/commission-entries/{entry_id}/pay")
@db_session
def mark_commission_entry_paid(
    conn,
    entry_id: int,
    current_user: dict = Depends(get_current_user),
) -> CommissionEntryResponse:
    """Mark an approved commission entry as actually paid out."""
    require_permission(conn, current_user, "compensation.manage_commission_plans_entries")
    inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

    entry = conn.execute(
        "SELECT * FROM commission_entries WHERE id = ? AND institution_id = ?",
        (entry_id, inst_id),
    ).fetchone()
    if not entry:
        raise HTTPException(404, detail="Commission entry not found")
    if entry["status"] != "Approved":
        raise HTTPException(400, detail="Only an Approved commission entry can be marked as Paid")

    today = datetime.utcnow().date().isoformat()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE commission_entries SET status = 'Paid', payout_date = ?, updated_at = ? WHERE id = ?",
        (today, now, entry_id),
    )

    note_body = f"Commission payout of RM {float(entry['calculated_commission']):,.2f} paid out on {today}."
    _add_hr_note(conn, inst_id, entry["employee_id"], note_body, current_user["username"])

    conn.commit()

    updated = conn.execute("SELECT * FROM commission_entries WHERE id = ?", (entry_id,)).fetchone()
    return CommissionEntryResponse(**dict(updated))



