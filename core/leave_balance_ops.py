"""Leave balance lookup/creation and deduction — shared between
routers/leave.py (applications, approvals) and routers/attendance.py
(reclassifying an attendance record as leave), since both need to touch
the same leave_balances row the same way. See docs/leave-carry-forward.md
for the carry-forward mechanism these functions implement.
"""
from datetime import date, datetime, timedelta


def _sweep_expired_carry_forward(conn, bal):
    """A balance row's carried_forward_days stays in the availability total
    (entitled_days + carried_forward_days - used_days) until its
    carried_forward_expires_on date passes, at which point whatever's left
    unused is forfeited: moved into carried_forward_forfeited_days (audit
    trail) and carried_forward_days is capped down to what's already been
    used, so it stops counting. Called on every read/use of a balance row —
    there's no scheduled job in this codebase, so this lazy check is what
    actually enforces the "use it within X days of the new year" deadline.
    Returns the row, refreshed if a sweep happened."""
    expires_on = bal["carried_forward_expires_on"]
    if not expires_on or expires_on > datetime.now().strftime("%Y-%m-%d"):
        return bal
    remaining = bal["carried_forward_days"] - bal["carried_forward_used_days"]
    if remaining <= 0:
        return bal
    conn.execute(
        "UPDATE leave_balances SET carried_forward_days=carried_forward_used_days,"
        "carried_forward_forfeited_days=carried_forward_forfeited_days+? WHERE id=?",
        (remaining, bal["id"])
    )
    conn.commit()
    return conn.execute("SELECT * FROM leave_balances WHERE id=?", (bal["id"],)).fetchone()


def _compute_carry_forward(lt, prior_bal) -> float:
    """How much of a prior year's unused balance rolls into the new year,
    per the leave type's policy: min(unused, max_days if set, unused *
    max_percent/100 if set) — whichever cap is lowest, never more than what
    was actually unused. Rounded to the nearest half-day, matching every
    other day-count in this module (see _accrued_days in routers/leave.py)."""
    if not lt or not prior_bal or not lt["carry_forward_enabled"]:
        return 0.0
    unused = prior_bal["entitled_days"] + prior_bal["carried_forward_days"] - prior_bal["used_days"]
    if unused <= 0:
        return 0.0
    cap = unused
    if lt["carry_forward_max_days"]:
        cap = min(cap, lt["carry_forward_max_days"])
    if lt["carry_forward_max_percent"]:
        cap = min(cap, unused * lt["carry_forward_max_percent"] / 100)
    return round(cap * 2) / 2


def _get_or_create_leave_balance(conn, inst_id: int, employee_id: str, leave_type_id: int, year: int):
    row = conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()
    if row:
        return _sweep_expired_carry_forward(conn, row)
    lt = conn.execute("SELECT * FROM leave_types WHERE id=? AND institution_id=?", (leave_type_id, inst_id)).fetchone()
    entitled = lt["annual_entitlement"] if lt else 0

    # Roll unused balance forward from last year's row, if any — swept first
    # so an already-expired carry-forward from *that* year isn't carried
    # again (carry-forward is a one-year grace period, not compounding).
    prior_bal = conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year - 1)
    ).fetchone()
    if prior_bal:
        prior_bal = _sweep_expired_carry_forward(conn, prior_bal)
    carried = _compute_carry_forward(lt, prior_bal)
    expires_on = None
    if carried > 0 and lt and lt["carry_forward_expiry_days"]:
        expires_on = (date(year, 1, 1) + timedelta(days=lt["carry_forward_expiry_days"])).isoformat()

    conn.execute(
        "INSERT INTO leave_balances (institution_id,employee_id,leave_type_id,year,entitled_days,carried_forward_days,used_days,carried_forward_expires_on) VALUES (?,?,?,?,?,?,0,?)",
        (inst_id, employee_id, leave_type_id, year, entitled, carried, expires_on)
    )
    return conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()


def _consume_balance(conn, bal, days: float):
    """Deducts `days` from a balance, drawing down the carried-forward
    bucket first — used_days stays the combined total; carried_forward_used_days
    tracks just the carry-forward portion, which is what _sweep_expired_
    carry_forward needs to know how much is left to expire."""
    carry_remaining = max(0.0, bal["carried_forward_days"] - bal["carried_forward_used_days"])
    from_carry = min(days, carry_remaining)
    conn.execute(
        "UPDATE leave_balances SET used_days=used_days+?,carried_forward_used_days=carried_forward_used_days+? WHERE id=?",
        (days, from_carry, bal["id"])
    )


def _credit_balance(conn, bal, days: float):
    """Adds `days` onto a balance's entitled_days — used by Overtime's
    leave-conversion path (core/overtime.py) to grant extra days earned
    from approved overtime, on top of whatever the leave type's normal
    entitlement already is."""
    conn.execute("UPDATE leave_balances SET entitled_days=entitled_days+? WHERE id=?", (days, bal["id"]))


def _release_balance(conn, bal, days: float):
    """Reverses _consume_balance (cancellation/rejection-after-approval),
    giving back to the carried-forward bucket first — mirroring consumption
    order so carried_forward_used_days can't go negative."""
    from_carry = min(days, bal["carried_forward_used_days"])
    conn.execute(
        "UPDATE leave_balances SET used_days=used_days-?,carried_forward_used_days=carried_forward_used_days-? WHERE id=?",
        (days, from_carry, bal["id"])
    )
