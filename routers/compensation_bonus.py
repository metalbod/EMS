"""Compensation: Variable Pay — Bonus/Incentive Plans and Payouts. One of
six routers split out of the former single routers/compensation.py."""
import logging
from typing import List
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_helpers import require_hr_role, add_hr_note as _add_hr_note
from core.compensation_schemas import (
    BonusPlanCreate, BonusPlanUpdate, BonusPlanResponse,
    BonusPayoutCreate, BonusPayoutDecide, BonusPayoutResponse, BonusPayoutWithEmployee,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])

# ============================================================================
# VARIABLE PAY: BONUS / INCENTIVE PLAN ENDPOINTS
# ============================================================================

@router.post("/bonus-plans", status_code=201)
async def create_bonus_plan(
    payload: BonusPlanCreate,
    current_user: dict = Depends(get_current_user),
) -> BonusPlanResponse:
    """Create a bonus/incentive plan."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO bonus_plans
            (institution_id, plan_name, plan_type, plan_year, period_start, period_end,
             budget_pool_amount, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
            """,
            (inst_id, payload.plan_name, payload.plan_type, payload.plan_year,
             payload.period_start, payload.period_end, payload.budget_pool_amount,
             payload.description, now, now),
        )
        conn.commit()
        plan_id = conn._last_id

        plan = conn.execute("SELECT * FROM bonus_plans WHERE id = ?", (plan_id,)).fetchone()
        return BonusPlanResponse(**dict(plan))

    finally:
        conn.close()


@router.get("/bonus-plans")
async def list_bonus_plans(
    current_user: dict = Depends(get_current_user),
) -> List[BonusPlanResponse]:
    """List bonus/incentive plans."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plans = conn.execute(
            "SELECT * FROM bonus_plans WHERE institution_id = ? ORDER BY plan_year DESC, id DESC",
            (inst_id,),
        ).fetchall()
        return [BonusPlanResponse(**dict(p)) for p in plans]
    finally:
        conn.close()


@router.put("/bonus-plans/{plan_id}")
async def update_bonus_plan(
    plan_id: int,
    payload: BonusPlanUpdate,
    current_user: dict = Depends(get_current_user),
) -> BonusPlanResponse:
    """Update a bonus plan (name, status, budget, description)."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plan = conn.execute(
            "SELECT * FROM bonus_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Bonus plan not found")

        updates = {
            "plan_name": payload.plan_name if payload.plan_name is not None else plan["plan_name"],
            "status": payload.status if payload.status is not None else plan["status"],
            "budget_pool_amount": payload.budget_pool_amount if payload.budget_pool_amount is not None else plan["budget_pool_amount"],
            "description": payload.description if payload.description is not None else plan["description"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        conn.execute(f"UPDATE bonus_plans SET {set_clause} WHERE id = ?", (*updates.values(), plan_id))
        conn.commit()

        updated = conn.execute("SELECT * FROM bonus_plans WHERE id = ?", (plan_id,)).fetchone()
        return BonusPlanResponse(**dict(updated))

    finally:
        conn.close()


@router.get("/bonus-plans/{plan_id}/payouts")
async def list_bonus_payouts(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[BonusPayoutWithEmployee]:
    """List payouts for a bonus plan, with employee names joined in."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        plan = conn.execute(
            "SELECT * FROM bonus_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Bonus plan not found")

        # employee_id is only unique per institution, so the join must also
        # match institution_id — see the pay-equity report fix for the same
        # cross-tenant-fan-out pattern.
        rows = conn.execute(
            """
            SELECT p.*, e.full_name AS employee_name
            FROM bonus_payouts p
            JOIN employees e ON p.employee_id = e.employee_id AND p.institution_id = e.institution_id
            WHERE p.bonus_plan_id = ? AND p.institution_id = ?
            ORDER BY p.created_at DESC
            """,
            (plan_id, inst_id),
        ).fetchall()
        return [BonusPayoutWithEmployee(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/bonus-payouts", status_code=201)
async def create_bonus_payout(
    bonus_plan_id: int,
    payload: BonusPayoutCreate,
    current_user: dict = Depends(get_current_user),
) -> BonusPayoutResponse:
    """Award a bonus payout to an employee under a plan."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        plan = conn.execute(
            "SELECT * FROM bonus_plans WHERE id = ? AND institution_id = ?",
            (bonus_plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Bonus plan not found")

        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (payload.employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO bonus_payouts
            (institution_id, bonus_plan_id, employee_id, target_amount, awarded_amount,
             reason, recommended_by_user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
            """,
            (inst_id, bonus_plan_id, payload.employee_id, payload.target_amount,
             payload.awarded_amount, payload.reason, user_id, now, now),
        )
        # Capture this INSERT's id before the HR note INSERT overwrites
        # conn._last_id.
        payout_id = conn._last_id

        note_body = f"Bonus payout of RM {payload.awarded_amount:,.2f} proposed under '{plan['plan_name']}' ({plan['plan_type']})."
        if payload.reason:
            note_body += f" Reason: {payload.reason}"
        _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

        conn.commit()

        payout = conn.execute("SELECT * FROM bonus_payouts WHERE id = ?", (payout_id,)).fetchone()
        return BonusPayoutResponse(**dict(payout))

    finally:
        conn.close()


@router.put("/bonus-payouts/{payout_id}")
async def decide_bonus_payout(
    payout_id: int,
    payload: BonusPayoutDecide,
    current_user: dict = Depends(get_current_user),
) -> BonusPayoutResponse:
    """Approve or reject a bonus payout."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        payout = conn.execute(
            "SELECT * FROM bonus_payouts WHERE id = ? AND institution_id = ?",
            (payout_id, inst_id),
        ).fetchone()
        if not payout:
            raise HTTPException(404, detail="Bonus payout not found")

        plan = conn.execute("SELECT plan_name FROM bonus_plans WHERE id = ?", (payout["bonus_plan_id"],)).fetchone()
        plan_name = plan["plan_name"] if plan else "bonus plan"

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE bonus_payouts
            SET status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, user_id, now, now, payout_id),
        )

        note_body = (
            f"Bonus payout of RM {float(payout['awarded_amount']):,.2f} under '{plan_name}' "
            f"was {payload.status.lower()} by {current_user['username']}."
        )
        _add_hr_note(conn, inst_id, payout["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM bonus_payouts WHERE id = ?", (payout_id,)).fetchone()
        return BonusPayoutResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/bonus-payouts/{payout_id}/pay")
async def mark_bonus_payout_paid(
    payout_id: int,
    current_user: dict = Depends(get_current_user),
) -> BonusPayoutResponse:
    """Mark an approved bonus payout as actually paid out."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        payout = conn.execute(
            "SELECT * FROM bonus_payouts WHERE id = ? AND institution_id = ?",
            (payout_id, inst_id),
        ).fetchone()
        if not payout:
            raise HTTPException(404, detail="Bonus payout not found")
        if payout["status"] != "Approved":
            raise HTTPException(400, detail="Only an Approved payout can be marked as Paid")

        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE bonus_payouts SET status = 'Paid', payout_date = ?, updated_at = ? WHERE id = ?",
            (today, now, payout_id),
        )

        note_body = f"Bonus payout of RM {float(payout['awarded_amount']):,.2f} paid out on {today}."
        _add_hr_note(conn, inst_id, payout["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM bonus_payouts WHERE id = ?", (payout_id,)).fetchone()
        return BonusPayoutResponse(**dict(updated))

    finally:
        conn.close()


