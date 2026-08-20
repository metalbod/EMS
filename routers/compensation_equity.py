"""Compensation: Equity Grants and Vesting Events (long-term incentives).
One of six routers split out of the former single routers/compensation.py."""
import calendar
import logging
from typing import List
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_helpers import add_hr_note as _add_hr_note
from core.permission_matrix import require_permission
from core.compensation_schemas import (
    EquityGrantCreate, EquityGrantDecide, EquityGrantResponse, EquityGrantWithEmployee,
    EquityGrantDetail, VestingEventResponse, VestingEventSettle,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])

# ============================================================================
# EQUITY & LONG-TERM INCENTIVES
# ============================================================================

def _add_months(date_str: str, months: int) -> str:
    """Add whole calendar months to a YYYY-MM-DD string, clamping the day to
    the target month's length (e.g. Jan 31 + 1 month -> Feb 28/29, not an
    invalid Feb 31). No dateutil dependency in this project, so this is the
    plain-stdlib equivalent of relativedelta(months=+months)."""
    y, m, d = (int(p) for p in date_str.split('-'))
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    last_day = calendar.monthrange(ny, nm)[1]
    return date(ny, nm, min(d, last_day)).isoformat()


def _generate_vesting_schedule(quantity: int, vesting_start_date: str, vesting_years: int, cliff_months: int):
    """Standard cliff + quarterly vesting: cliff_months worth of shares vest
    in one tranche at the cliff date (proportional to time elapsed), then
    the remainder vests in equal quarterly tranches for the rest of the
    schedule. The final quarter absorbs any rounding remainder so the
    tranches always sum to exactly `quantity`. Returns a list of
    (vest_date, quantity) tuples."""
    total_months = vesting_years * 12
    events = []

    cliff_qty = 0
    if cliff_months > 0:
        cliff_qty = round(quantity * cliff_months / total_months)
        if cliff_qty > 0:
            events.append((_add_months(vesting_start_date, cliff_months), cliff_qty))

    remaining_qty = quantity - cliff_qty
    remaining_months = total_months - cliff_months
    num_quarters = remaining_months // 3

    if num_quarters <= 0:
        if remaining_qty > 0:
            events.append((_add_months(vesting_start_date, total_months), remaining_qty))
    else:
        per_quarter = remaining_qty // num_quarters
        allocated = 0
        for i in range(1, num_quarters + 1):
            qty = per_quarter if i < num_quarters else remaining_qty - allocated
            allocated += qty
            if qty > 0:
                events.append((_add_months(vesting_start_date, cliff_months + 3 * i), qty))

    return events


@router.post("/equity-grants", status_code=201)
async def create_equity_grant(
    payload: EquityGrantCreate,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantResponse:
    """Create an equity grant (stock option or RSU), pending HR approval.
    Vesting events aren't generated until the grant is approved."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (payload.employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO equity_grants
            (institution_id, employee_id, grant_type, grant_date, quantity, strike_price,
             fair_market_value_at_grant, vesting_start_date, vesting_years, cliff_months,
             notes, recommended_by_user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending Approval', ?, ?)
            """,
            (inst_id, payload.employee_id, payload.grant_type, payload.grant_date, payload.quantity,
             payload.strike_price, payload.fair_market_value_at_grant, payload.vesting_start_date,
             payload.vesting_years, payload.cliff_months, payload.notes, user_id, now, now),
        )
        grant_id = conn._last_id

        note_body = (
            f"Equity grant proposed: {payload.quantity:,} {payload.grant_type} units, "
            f"granted {payload.grant_date}, vesting over {payload.vesting_years}y "
            f"with a {payload.cliff_months}-month cliff."
        )
        _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

        conn.commit()

        grant = conn.execute("SELECT * FROM equity_grants WHERE id = ?", (grant_id,)).fetchone()
        return EquityGrantResponse(**dict(grant))

    finally:
        conn.close()


@router.get("/equity-grants")
async def list_equity_grants(
    current_user: dict = Depends(get_current_user),
) -> List[EquityGrantWithEmployee]:
    """List all equity grants in the institution, with employee names joined in."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            """
            SELECT g.*, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name
            FROM equity_grants g
            JOIN employees e ON g.employee_id = e.employee_id AND g.institution_id = e.institution_id
            WHERE g.institution_id = ?
            ORDER BY g.created_at DESC
            """,
            (inst_id,),
        ).fetchall()
        return [EquityGrantWithEmployee(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.get("/equity-grants/{grant_id}")
async def get_equity_grant(
    grant_id: int,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantDetail:
    """Get a single equity grant with its full vesting schedule."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        grant = conn.execute(
            """
            SELECT g.*, e.full_name AS employee_name, e.preferred_name AS employee_preferred_name
            FROM equity_grants g
            JOIN employees e ON g.employee_id = e.employee_id AND g.institution_id = e.institution_id
            WHERE g.id = ? AND g.institution_id = ?
            """,
            (grant_id, inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")

        events = conn.execute(
            "SELECT * FROM equity_vesting_events WHERE equity_grant_id = ? AND institution_id = ? ORDER BY vest_date ASC",
            (grant_id, inst_id),
        ).fetchall()

        # "Paid" only occurs for Phantom grants (cash-settled after vesting)
        # and is still a vested tranche, just further along — it must count
        # toward vested, not sit in limbo between Scheduled and Vested.
        vested = sum(e["quantity_vested"] for e in events if e["status"] in ("Vested", "Paid"))
        unvested = sum(e["quantity_vested"] for e in events if e["status"] == "Scheduled")

        grant_dict = dict(grant)
        return EquityGrantDetail(
            **grant_dict,
            vesting_events=[VestingEventResponse(**dict(e)) for e in events],
            quantity_vested=vested,
            quantity_unvested=unvested,
        )
    finally:
        conn.close()


@router.put("/equity-grants/{grant_id}/decide")
async def decide_equity_grant(
    grant_id: int,
    payload: EquityGrantDecide,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantResponse:
    """Approve or reject an equity grant. Approving generates the full
    vesting schedule as equity_vesting_events rows in the same transaction —
    there's no separate 'activate' step."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        grant = conn.execute(
            "SELECT * FROM equity_grants WHERE id = ? AND institution_id = ?",
            (grant_id, inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")
        if grant["status"] != "Pending Approval":
            raise HTTPException(400, detail="Only a Pending Approval grant can be approved or rejected")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE equity_grants
            SET status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, user_id, now, now, grant_id),
        )

        if payload.status == "Approved":
            schedule = _generate_vesting_schedule(
                grant["quantity"], grant["vesting_start_date"], grant["vesting_years"], grant["cliff_months"]
            )
            for vest_date, qty in schedule:
                conn.execute(
                    """
                    INSERT INTO equity_vesting_events
                    (institution_id, equity_grant_id, employee_id, vest_date, quantity_vested,
                     status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'Scheduled', ?, ?)
                    """,
                    (inst_id, grant_id, grant["employee_id"], vest_date, qty, now, now),
                )

        note_body = (
            f"Equity grant ({grant['quantity']:,} {grant['grant_type']} units, granted {grant['grant_date']}) "
            f"was {payload.status.lower()} by {current_user['username']}."
        )
        _add_hr_note(conn, inst_id, grant["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_grants WHERE id = ?", (grant_id,)).fetchone()
        return EquityGrantResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/equity-grants/{grant_id}/cancel")
async def cancel_equity_grant(
    grant_id: int,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantResponse:
    """Cancel an equity grant (e.g. on termination before fully vested).
    Already-vested tranches are left untouched — only remaining Scheduled
    tranches are cancelled, since vested shares are the employee's regardless
    of what happens to the grant afterward."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        grant = conn.execute(
            "SELECT * FROM equity_grants WHERE id = ? AND institution_id = ?",
            (grant_id, inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")
        if grant["status"] not in ("Approved",):
            raise HTTPException(400, detail="Only an Approved grant can be cancelled")

        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE equity_grants SET status = 'Cancelled', updated_at = ? WHERE id = ?",
            (now, grant_id),
        )
        conn.execute(
            "UPDATE equity_vesting_events SET status = 'Cancelled', updated_at = ? WHERE equity_grant_id = ? AND status = 'Scheduled'",
            (now, grant_id),
        )

        note_body = f"Equity grant ({grant['quantity']:,} {grant['grant_type']} units, granted {grant['grant_date']}) was cancelled by {current_user['username']}. Unvested tranches forfeited."
        _add_hr_note(conn, inst_id, grant["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_grants WHERE id = ?", (grant_id,)).fetchone()
        return EquityGrantResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/vesting-events/{event_id}/vest")
async def mark_vesting_event_vested(
    event_id: int,
    current_user: dict = Depends(get_current_user),
) -> VestingEventResponse:
    """Mark a scheduled vesting tranche as actually vested (i.e. its vest
    date has passed and the shares/units are now the employee's)."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        event = conn.execute(
            "SELECT * FROM equity_vesting_events WHERE id = ? AND institution_id = ?",
            (event_id, inst_id),
        ).fetchone()
        if not event:
            raise HTTPException(404, detail="Vesting event not found")
        if event["status"] != "Scheduled":
            raise HTTPException(400, detail="Only a Scheduled vesting event can be marked as Vested")

        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE equity_vesting_events SET status = 'Vested', vested_at = ?, updated_at = ? WHERE id = ?",
            (now, now, event_id),
        )

        grant = conn.execute("SELECT grant_type FROM equity_grants WHERE id = ?", (event["equity_grant_id"],)).fetchone()
        note_body = f"{event['quantity_vested']:,} {grant['grant_type'] if grant else ''} units vested on {event['vest_date']}."
        _add_hr_note(conn, inst_id, event["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_vesting_events WHERE id = ?", (event_id,)).fetchone()
        return VestingEventResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/vesting-events/{event_id}/settle")
async def settle_vesting_event(
    event_id: int,
    payload: VestingEventSettle,
    current_user: dict = Depends(get_current_user),
) -> VestingEventResponse:
    """Cash-settle a Vested Phantom stock tranche: pay out
    (settlement_price - fair_market_value_at_grant) x quantity_vested, i.e.
    the appreciation over the grant's baseline value, clamped at zero (a
    phantom award pays the *gain*, not a fixed amount — no negative payout
    if the price dropped). Only meaningful for Phantom grants, since RSU/
    ISO/NSO/ESPP settle in actual equity, not cash, and 'Vested' is already
    their terminal state."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_equity_grants_vesting")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        event = conn.execute(
            "SELECT * FROM equity_vesting_events WHERE id = ? AND institution_id = ?",
            (event_id, inst_id),
        ).fetchone()
        if not event:
            raise HTTPException(404, detail="Vesting event not found")
        if event["status"] != "Vested":
            raise HTTPException(400, detail="Only a Vested tranche can be settled")

        grant = conn.execute(
            "SELECT * FROM equity_grants WHERE id = ? AND institution_id = ?",
            (event["equity_grant_id"], inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")
        if grant["grant_type"] != "Phantom":
            raise HTTPException(400, detail="Only Phantom stock tranches can be cash-settled")

        baseline = float(grant["fair_market_value_at_grant"] or 0)
        cash_payout = max(0.0, payload.settlement_price - baseline) * event["quantity_vested"]

        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE equity_vesting_events
            SET status = 'Paid', settlement_price = ?, cash_payout = ?, payout_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.settlement_price, cash_payout, today, now, event_id),
        )

        note_body = (
            f"Phantom stock tranche ({event['quantity_vested']:,} units, vested {event['vest_date']}) "
            f"settled at RM {payload.settlement_price:,.4f}/unit — RM {cash_payout:,.2f} paid out on {today}."
        )
        _add_hr_note(conn, inst_id, event["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_vesting_events WHERE id = ?", (event_id,)).fetchone()
        return VestingEventResponse(**dict(updated))

    finally:
        conn.close()


