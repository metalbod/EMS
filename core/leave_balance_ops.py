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
    """How much of a prior year's unused balance rolls into the new year, per
    the leave type's policy. Two optional limits, each skipped when 0:
      - max days:    carry_forward_max_days
      - max percent: carry_forward_max_percent of EITHER the unused balance
                     (carry_forward_percent_basis='balance') or that
                     employee's own entitlement for the year being carried
                     from (='entitlement', prior_bal["entitled_days"] — so a
                     pro-rated first year is respected)
    With both set, carry_forward_cap_rule picks the 'lower' or the 'higher' of
    the two; with one set, that one applies. Whatever the rule says, never
    more than what was actually unused. Rounded to the nearest half-day,
    matching every other day-count in this module (see _accrued_days in
    routers/leave.py)."""
    if not lt or not prior_bal or not lt["carry_forward_enabled"]:
        return 0.0
    unused = prior_bal["entitled_days"] + prior_bal["carried_forward_days"] - prior_bal["used_days"]
    if unused <= 0:
        return 0.0
    limits = []
    if lt["carry_forward_max_days"]:
        limits.append(lt["carry_forward_max_days"])
    if lt["carry_forward_max_percent"]:
        basis = prior_bal["entitled_days"] if lt["carry_forward_percent_basis"] == "entitlement" else unused
        limits.append(basis * lt["carry_forward_max_percent"] / 100)
    if not limits:
        cap = unused
    elif lt["carry_forward_cap_rule"] == "higher":
        cap = min(unused, max(limits))
    else:
        cap = min(unused, min(limits))
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

    # ON CONFLICT DO NOTHING — two concurrent first-time callers for the
    # same employee+leave_type+year (e.g. a Dashboard widget and a page's
    # own load firing near-simultaneously) can both pass the SELECT above
    # seeing no row, then both attempt this INSERT; without this, the
    # loser hits leave_balances_employee_id_leave_type_id_year_key's
    # UniqueViolation as an unhandled 500. The re-SELECT below already
    # re-fetches by natural key rather than trusting this INSERT actually
    # inserted anything, so it transparently returns the winner's row
    # either way.
    conn.execute(
        "INSERT INTO leave_balances (institution_id,employee_id,leave_type_id,year,entitled_days,carried_forward_days,used_days,carried_forward_expires_on) VALUES (?,?,?,?,?,?,0,?) "
        "ON CONFLICT (employee_id,leave_type_id,year) DO NOTHING",
        (inst_id, employee_id, leave_type_id, year, entitled, carried, expires_on)
    )
    return conn.execute(
        "SELECT * FROM leave_balances WHERE employee_id=? AND leave_type_id=? AND year=?",
        (employee_id, leave_type_id, year)
    ).fetchone()


def _carry_usable_for(bal, start_date) -> float:
    """Carried-forward days that leave STARTING on `start_date` may draw on.
    Judged on the leave's own start date, not on today: leave that starts on
    or before the carry's expiry date may use it even if it is approved after
    the expiry (the lazy sweep may already have forfeited it — those days
    count as usable again for such leave), and leave that starts after the
    expiry never can, even if approved before it. start_date=None (an old
    caller that doesn't know the date) means "ignore expiry"."""
    expires_on = bal["carried_forward_expires_on"]
    if start_date and expires_on and start_date > expires_on:
        return 0.0
    remaining = max(0.0, bal["carried_forward_days"] - bal["carried_forward_used_days"])
    return remaining + (bal["carried_forward_forfeited_days"] or 0.0)


def _available_for(bal, entitled_for_check: float, start_date) -> float:
    """Days an employee can still book for leave starting on `start_date`:
    the carried days usable for that date plus what is left of this year's
    entitlement (`entitled_for_check` is the full or monthly-accrued figure).
    Without any expiry this equals entitled + carried_forward - used."""
    regular_used = bal["used_days"] - bal["carried_forward_used_days"]
    return _carry_usable_for(bal, start_date) + entitled_for_check - regular_used


def _consume_balance(conn, bal, days: float, start_date=None) -> float:
    """Deducts `days` from a balance, drawing down the carried-forward
    bucket first — used_days stays the combined total; carried_forward_used_days
    tracks just the carry-forward portion, which is what _sweep_expired_
    carry_forward needs to know how much is left to expire. `start_date` is
    the leave's start (see _carry_usable_for). Returns how many of the days
    came from carried-forward, which callers record on the application so a
    cancellation can give back exactly that split."""
    from_carry = min(days, _carry_usable_for(bal, start_date))
    remaining = max(0.0, bal["carried_forward_days"] - bal["carried_forward_used_days"])
    revived = max(0.0, from_carry - remaining)   # drawn from days the sweep had already forfeited
    conn.execute(
        "UPDATE leave_balances SET used_days=used_days+?,carried_forward_used_days=carried_forward_used_days+?,"
        "carried_forward_days=carried_forward_days+?,carried_forward_forfeited_days=carried_forward_forfeited_days-? WHERE id=?",
        (days, from_carry, revived, revived, bal["id"])
    )
    return from_carry


def _credit_balance(conn, bal, days: float):
    """Adds `days` onto a balance's entitled_days — used by Overtime's
    leave-conversion path (core/overtime.py) to grant extra days earned
    from approved overtime, on top of whatever the leave type's normal
    entitlement already is."""
    conn.execute("UPDATE leave_balances SET entitled_days=entitled_days+? WHERE id=?", (days, bal["id"]))


def _release_balance(conn, bal, days: float, carried_used=None) -> float:
    """Reverses _consume_balance (cancellation/rejection-after-approval, or a
    holiday shortening approved leave). `carried_used` is how many of the
    application's days were recorded as taken from carried-forward (None for
    an application approved before that was recorded: fall back to giving back
    to the carried bucket first, capped at what was used). Those days go back
    to the carried bucket — unless it has expired by now, in which case they
    lapse (counted as forfeited) rather than coming back to life. Returns how
    many carried-forward days were released, for the caller to take off the
    application's own record."""
    if carried_used is None:
        from_carry = min(days, bal["carried_forward_used_days"])
    else:
        from_carry = min(carried_used, days, bal["carried_forward_used_days"])
    expires_on = bal["carried_forward_expires_on"]
    if from_carry > 0 and expires_on and expires_on <= datetime.now().strftime("%Y-%m-%d"):
        conn.execute(
            "UPDATE leave_balances SET used_days=used_days-?,carried_forward_used_days=carried_forward_used_days-?,"
            "carried_forward_days=carried_forward_days-?,carried_forward_forfeited_days=carried_forward_forfeited_days+? WHERE id=?",
            (days, from_carry, from_carry, from_carry, bal["id"])
        )
    else:
        conn.execute(
            "UPDATE leave_balances SET used_days=used_days-?,carried_forward_used_days=carried_forward_used_days-? WHERE id=?",
            (days, from_carry, bal["id"])
        )
    return from_carry
