"""Carried-forward leave is used first, judged on the LEAVE's start date, and
each application records how many of its days came from carry-forward
(leave_applications.carried_days_used). See core/leave_balance_ops.py."""
import os
from datetime import date, timedelta

import pytest

from core.leave_balance_ops import _available_for, _carry_usable_for
from db import get_admin_db


def bal(entitled=10, carried=3, used=0, carried_used=0, forfeited=0, expires=None):
    return {"entitled_days": entitled, "carried_forward_days": carried, "used_days": used,
            "carried_forward_used_days": carried_used, "carried_forward_forfeited_days": forfeited,
            "carried_forward_expires_on": expires}


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------
def test_carry_usable_depends_on_the_leave_start_date_not_today():
    b = bal(carried=3, expires="2027-06-29")
    assert _carry_usable_for(b, "2027-06-29") == 3          # starts on the expiry date: usable
    assert _carry_usable_for(b, "2027-06-30") == 0          # starts after: not usable
    assert _carry_usable_for(b, None) == 3                  # unknown date: ignore expiry
    assert _carry_usable_for(bal(carried=3, expires=None), "2030-01-01") == 3


def test_carry_already_forfeited_by_the_sweep_is_usable_again_for_earlier_leave():
    swept = bal(carried=1, carried_used=1, forfeited=2, expires="2027-06-29")   # 3 carried, 1 used, 2 lapsed
    assert _carry_usable_for(swept, "2027-06-10") == 2                          # leave before expiry may still use the 2
    assert _carry_usable_for(swept, "2027-07-10") == 0


def test_available_equals_the_old_formula_without_expiry_and_excludes_unusable_carry_with_it():
    b = bal(entitled=10, carried=3, used=4, carried_used=2)
    assert _available_for(b, 10, None) == 10 + 3 - 4
    exp = bal(entitled=10, carried=3, used=4, carried_used=2, expires="2027-06-29")
    assert _available_for(exp, 10, "2027-06-01") == 9       # 1 carry left + (10 - 2 regular used)
    assert _available_for(exp, 10, "2027-08-01") == 8       # carry not usable: 10 - 2


# ---------------------------------------------------------------------------
# End to end through the API
# ---------------------------------------------------------------------------
def _weekdays(start: date, n: int):
    """First date on/after `start` that is a Monday, then the date of the n-th weekday from it."""
    d = start
    while d.weekday() != 0:
        d += timedelta(days=1)
    first, last, count = d, d, 1
    while count < n:
        last += timedelta(days=1)
        if last.weekday() < 5:
            count += 1
    return first, last


class Setup:
    def __init__(self, client, hr, headers, emp, lt, year):
        self.client, self.hr, self.headers, self.emp, self.lt, self.year = client, hr, headers, emp, lt, year

    def balance(self, as_hr=True):
        h = self.hr if as_hr else self.headers
        rows = self.client.get(f"/api/leave/balances?year={self.year}&employee_id={self.emp['employee_id']}", headers=h).json()
        return next(r for r in rows if r["leave_type_id"] == self.lt["id"])

    def db(self, sql, params=()):
        conn = get_admin_db()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def row(self, sql, params=()):
        conn = get_admin_db()
        try:
            r = conn.execute(sql, params).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def set_carry(self, days, expires_on=None):
        b = self.balance()
        r = self.client.patch(f"/api/leave/balances/{b['id']}", headers=self.hr, json={"carried_forward_days": days})
        assert r.status_code == 200, r.text
        self.db("UPDATE leave_balances SET carried_forward_expires_on=? WHERE id=?", (expires_on, b["id"]))

    def apply(self, start, days):
        s, e = _weekdays(start, days)
        r = self.client.post("/api/leave/applications", headers=self.headers, json={
            "employee_id": self.emp["employee_id"], "leave_type_id": self.lt["id"],
            "start_date": s.isoformat(), "end_date": e.isoformat(), "reason": "carry test"})
        return r

    def app(self, app_id):
        return self.row("SELECT * FROM leave_applications WHERE id=?", (app_id,))

    def bal_row(self):
        return self.row("SELECT * FROM leave_balances WHERE id=?", (self.balance()["id"],))


@pytest.fixture
def carry_setup(client, hr_manager_auth, employee_with_login):
    created = []

    def make(entitlement=10, requires_approval=False):
        emp, headers = employee_with_login(full_name="ZZ Carry Priority")
        lt = client.post("/api/leave/types", headers=hr_manager_auth, json={
            "name": f"ZZ CP {os.urandom(3).hex()}", "annual_entitlement": entitlement, "requires_approval": requires_approval}).json()
        created.append(lt["id"])
        start = date.today() + timedelta(days=45)
        s = Setup(client, hr_manager_auth, headers, emp, lt, start.year)
        client.get(f"/api/leave/balances?year={start.year}", headers=headers)   # creates the balance row
        return s, start

    yield make
    for tid in created:
        client.delete(f"/api/leave/types/{tid}", headers=hr_manager_auth)


def test_carried_days_are_used_first_and_the_split_is_recorded(carry_setup):
    s, start = carry_setup(entitlement=10)
    s.set_carry(3)
    a1 = s.apply(start, 2)
    a2 = s.apply(start + timedelta(days=14), 3)
    assert a1.status_code == 201 and a2.status_code == 201, (a1.text, a2.text)
    assert s.app(a1.json()["id"])["carried_days_used"] == 2
    assert s.app(a2.json()["id"])["carried_days_used"] == 1            # only 1 carried day was left
    b = s.bal_row()
    assert (b["carried_forward_used_days"], b["used_days"]) == (3, 5)


def test_balances_api_reports_the_carried_forward_remaining(carry_setup):
    s, start = carry_setup()
    s.set_carry(3)
    s.apply(start, 2)
    b = s.balance()
    assert b["carried_forward_remaining"] == 1 and b["carried_forward_days"] == 3


def test_cancelling_gives_back_exactly_the_recorded_split(carry_setup, client):
    s, start = carry_setup(entitlement=10)
    s.set_carry(3)
    s.apply(start, 2)
    a2 = s.apply(start + timedelta(days=14), 3).json()                  # 1 carried + 2 regular
    r = client.patch(f"/api/leave/applications/{a2['id']}/status", headers=s.hr, json={"status": "Cancelled"})
    assert r.status_code == 200, r.text
    b = s.bal_row()
    assert (b["carried_forward_used_days"], b["used_days"]) == (2, 2)  # 1 carried day back, 3 days off used


def test_leave_starting_after_the_carry_expires_cannot_use_it(carry_setup):
    s, start = carry_setup(entitlement=2)
    s.set_carry(3, expires_on=(start - timedelta(days=10)).isoformat())   # expires before the leave starts
    too_long = s.apply(start, 3)
    assert too_long.status_code == 400 and "Insufficient balance" in too_long.text   # 2 available, not 5
    ok = s.apply(start, 2)
    assert ok.status_code == 201, ok.text
    assert s.app(ok.json()["id"])["carried_days_used"] == 0
    assert s.bal_row()["carried_forward_used_days"] == 0


def test_leave_starting_before_expiry_uses_carry_even_if_approved_after_expiry(carry_setup, client):
    today = date.today()
    if today.month == 1 and today.day <= 12:
        pytest.skip("needs a past date inside the current year")
    s, _ = carry_setup(entitlement=2, requires_approval=True)
    yr = today.year
    s.year = yr
    client.get(f"/api/leave/balances?year={yr}", headers=s.headers)
    s.set_carry(3, expires_on=f"{yr}-01-31")
    pending = s.apply(today + timedelta(days=45), 2)
    assert pending.status_code == 201, pending.text
    app_id = pending.json()["id"]
    s_date, e_date = _weekdays(date(yr, 1, 7), 2)                         # move the booking to early January, before expiry
    s.db("UPDATE leave_applications SET start_date=?, end_date=? WHERE id=?", (s_date.isoformat(), e_date.isoformat(), app_id))
    # Today is long past the 31 Jan expiry, so reading the balance forfeits the 3 carried days...
    swept = s.balance()
    assert swept["carried_forward_remaining"] == 0 and swept["carried_forward_forfeited_days"] == 3
    # ...but approving leave that STARTED before the expiry brings them back for it.
    ok = client.patch(f"/api/leave/applications/{app_id}/status", headers=s.hr, json={"status": "Approved"})
    assert ok.status_code == 200, ok.text
    assert s.app(app_id)["carried_days_used"] == 2
    b = s.bal_row()
    assert (b["carried_forward_used_days"], b["carried_forward_forfeited_days"]) == (2, 1)


def test_cancelling_after_the_carry_expired_lets_those_days_lapse(carry_setup, client):
    s, start = carry_setup(entitlement=10)
    s.set_carry(3)
    a = s.apply(start, 2).json()
    assert s.app(a["id"])["carried_days_used"] == 2
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    s.db("UPDATE leave_balances SET carried_forward_expires_on=? WHERE id=?", (yesterday, s.bal_row()["id"]))
    r = client.patch(f"/api/leave/applications/{a['id']}/status", headers=s.hr, json={"status": "Cancelled"})
    assert r.status_code == 200, r.text
    b = s.bal_row()
    assert b["used_days"] == 0
    assert b["carried_forward_days"] - b["carried_forward_used_days"] == 0       # nothing came back to life
    assert b["carried_forward_forfeited_days"] >= 3                              # 1 swept as unused + 2 lapsed on cancel


def test_applications_approved_before_the_split_was_recorded_still_cancel_sensibly(carry_setup, client):
    s, start = carry_setup(entitlement=10)
    s.set_carry(3)
    a = s.apply(start, 2).json()
    s.db("UPDATE leave_applications SET carried_days_used=NULL WHERE id=?", (a["id"],))   # as if approved pre-migration
    client.patch(f"/api/leave/applications/{a['id']}/status", headers=s.hr, json={"status": "Cancelled"})
    b = s.bal_row()
    assert (b["carried_forward_used_days"], b["used_days"]) == (0, 0)
