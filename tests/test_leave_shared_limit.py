"""A leave type that shares another type's entitlement keeps its own yearly
limit (leave_types.annual_entitlement, 0 = none) and its own working/calendar
day counting. The days still come out of the shared pool."""
import os
from datetime import date, timedelta

import pytest


def _monday_after(d: date) -> date:
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


@pytest.fixture
def pool_setup(client, hr_manager_auth, employee_with_login):
    created = []

    def make(pool_days=14, limit=3, shared_requires_approval=False, shared_calendar=False):
        emp, headers = employee_with_login(full_name="ZZ Shared Limit")
        tag = os.urandom(3).hex()
        pool = client.post("/api/leave/types", headers=hr_manager_auth, json={
            "name": f"ZZ Pool {tag}", "annual_entitlement": pool_days, "requires_approval": False}).json()
        shared = client.post("/api/leave/types", headers=hr_manager_auth, json={
            "name": f"ZZ Shared {tag}", "annual_entitlement": limit, "requires_approval": shared_requires_approval,
            "shares_entitlement_with_id": pool["id"], "count_calendar_days": shared_calendar}).json()
        created.extend([shared["id"], pool["id"]])      # delete the sharing type first
        return emp, headers, pool, shared

    yield make
    for tid in created:
        client.delete(f"/api/leave/types/{tid}", headers=hr_manager_auth)


def _apply(client, headers, emp, lt, start: date, end: date, **extra):
    return client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"], "start_date": start.isoformat(),
        "end_date": end.isoformat(), "reason": "shared limit test", **extra})


def _pool_used(client, hr, emp, pool, year):
    rows = client.get(f"/api/leave/balances?year={year}&employee_id={emp['employee_id']}", headers=hr).json()
    return next(r["used_days"] for r in rows if r["leave_type_id"] == pool["id"])


def test_own_limit_caps_the_type_while_days_come_out_of_the_pool(client, hr_manager_auth, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=3)
    mon = _monday_after(date.today() + timedelta(days=45))
    ok = _apply(client, headers, emp, shared, mon, mon + timedelta(days=1))               # 2 days
    assert ok.status_code == 201, ok.text
    over = _apply(client, headers, emp, shared, mon + timedelta(days=7), mon + timedelta(days=8))   # +2 = 4 > 3
    assert over.status_code == 400
    assert "3 day/year limit" in over.json()["detail"] and "(2 already applied + 2 requested = 4)" in over.json()["detail"]
    assert _pool_used(client, hr_manager_auth, emp, pool, mon.year) == 2                   # drawn from the pool
    one = _apply(client, headers, emp, shared, mon + timedelta(days=14), mon + timedelta(days=14))  # 1 more fits
    assert one.status_code == 201, one.text


def test_the_shared_pool_still_binds_when_it_is_the_tighter_limit(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=2, limit=20)
    mon = _monday_after(date.today() + timedelta(days=45))
    r = _apply(client, headers, emp, shared, mon, mon + timedelta(days=2))                # 3 days, pool has 2
    assert r.status_code == 400
    assert "Insufficient balance in the" in r.json()["detail"] and pool["name"] in r.json()["detail"]


def test_a_limit_of_zero_means_no_limit_of_its_own(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=0)
    mon = _monday_after(date.today() + timedelta(days=45))
    assert _apply(client, headers, emp, shared, mon, mon + timedelta(days=4)).status_code == 201   # 5 days


def test_pending_applications_count_towards_the_yearly_limit(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=3, shared_requires_approval=True)
    mon = _monday_after(date.today() + timedelta(days=45))
    first = _apply(client, headers, emp, shared, mon, mon + timedelta(days=1))
    assert first.status_code == 201 and first.json()["status"] == "Pending Approval"
    second = _apply(client, headers, emp, shared, mon + timedelta(days=7), mon + timedelta(days=8))
    assert second.status_code == 400 and "day/year limit" in second.json()["detail"]


def test_the_shared_type_counts_calendar_days_even_if_the_pool_counts_working_days(client, hr_manager_auth, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=10, shared_calendar=True)
    mon = _monday_after(date.today() + timedelta(days=45))
    r = _apply(client, headers, emp, shared, mon, mon + timedelta(days=6))                # Mon-Sun = 7 calendar days
    assert r.status_code == 201, r.text
    assert r.json()["days_count"] == 7
    assert _pool_used(client, hr_manager_auth, emp, pool, mon.year) == 7                  # the pool is charged what the type counted


def test_half_days_count_as_half_towards_the_limit(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=1)
    mon = _monday_after(date.today() + timedelta(days=45))
    assert _apply(client, headers, emp, shared, mon, mon, start_day_period="AM").status_code == 201
    assert _apply(client, headers, emp, shared, mon + timedelta(days=1), mon + timedelta(days=1), start_day_period="PM").status_code == 201
    third = _apply(client, headers, emp, shared, mon + timedelta(days=2), mon + timedelta(days=2), start_day_period="AM")
    assert third.status_code == 400 and "day/year limit" in third.json()["detail"]


def test_leave_straddling_new_year_is_counted_per_year(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=2)
    start, end = date(2027, 12, 29), date(2028, 1, 3)       # Wed-Mon: 3 working days in 2027 (29, 30, 31), 1 in 2028 (3 Jan)
    over = _apply(client, headers, emp, shared, start, end)
    assert over.status_code == 400 and "for 2027" in over.json()["detail"]
    shorter = _apply(client, headers, emp, shared, date(2027, 12, 30), date(2028, 1, 3))   # 2 in 2027 (30, 31), 1 in 2028
    assert shorter.status_code == 201, shorter.text


def test_other_types_applications_do_not_use_up_this_types_limit(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=2)
    mon = _monday_after(date.today() + timedelta(days=45))
    assert _apply(client, headers, emp, pool, mon, mon + timedelta(days=3)).status_code == 201     # 4 days of the pool type itself
    assert _apply(client, headers, emp, shared, mon + timedelta(days=7), mon + timedelta(days=8)).status_code == 201


def test_type_limits_endpoint_reports_limit_used_and_remaining(client, hr_manager_auth, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=5)
    mon = _monday_after(date.today() + timedelta(days=45))
    assert _apply(client, headers, emp, shared, mon, mon + timedelta(days=1)).status_code == 201
    rows = client.get(f"/api/leave/type-limits?year={mon.year}", headers=headers).json()
    mine = next(r for r in rows if r["leave_type_id"] == shared["id"])
    assert (mine["limit_days"], mine["used_days"], mine["remaining_days"]) == (5, 2, 3)
    assert mine["pool_name"] == pool["name"]
    assert all(r["leave_type_id"] != pool["id"] for r in rows)               # the pool owner has no separate limit
    hr_view = client.get(f"/api/leave/type-limits?year={mon.year}&employee_id={emp['employee_id']}", headers=hr_manager_auth).json()
    assert any(r["leave_type_id"] == shared["id"] and r["used_days"] == 2 for r in hr_view)


def test_type_limits_endpoint_is_private_to_the_employee(client, hr_manager_auth, pool_setup, make_test_employee):
    emp, headers, pool, shared = pool_setup()
    other = make_test_employee(full_name="ZZ Someone Else")
    res = client.get(f"/api/leave/type-limits?employee_id={other['employee_id']}", headers=headers)
    assert res.status_code == 403


def test_a_sharing_type_never_stores_its_own_carry_forward(client, hr_manager_auth):
    tag = os.urandom(3).hex()
    pool = client.post("/api/leave/types", headers=hr_manager_auth, json={
        "name": f"ZZ CF Pool {tag}", "annual_entitlement": 14, "carry_forward_enabled": True, "carry_forward_max_days": 5}).json()
    ids = [pool["id"]]
    try:
        assert pool["carry_forward_enabled"] in (1, True) and pool["carry_forward_max_days"] == 5   # the pool owner keeps it
        res = client.post("/api/leave/types", headers=hr_manager_auth, json={
            "name": f"ZZ CF Shared {tag}", "annual_entitlement": 3, "shares_entitlement_with_id": pool["id"],
            "carry_forward_enabled": True, "carry_forward_max_days": 4, "carry_forward_max_percent": 50,
            "carry_forward_expiry_days": 90, "carry_forward_percent_basis": "entitlement", "carry_forward_cap_rule": "higher"})
        assert res.status_code == 201, res.text
        shared = res.json()
        ids.insert(0, shared["id"])
        assert not shared["carry_forward_enabled"]
        assert (shared["carry_forward_max_days"], shared["carry_forward_max_percent"], shared["carry_forward_expiry_days"]) == (0, 0, 0)
        assert (shared["carry_forward_percent_basis"], shared["carry_forward_cap_rule"]) == ("balance", "lower")
        # ...and switching an existing carrying type to share clears it too
        other = client.post("/api/leave/types", headers=hr_manager_auth, json={
            "name": f"ZZ CF Other {tag}", "annual_entitlement": 10, "carry_forward_enabled": True, "carry_forward_max_days": 2}).json()
        ids.insert(0, other["id"])
        upd = client.put(f"/api/leave/types/{other['id']}", headers=hr_manager_auth, json={
            "name": other["name"], "annual_entitlement": 2, "shares_entitlement_with_id": pool["id"],
            "carry_forward_enabled": True, "carry_forward_max_days": 2})
        assert upd.status_code == 200 and not upd.json()["carry_forward_enabled"]
    finally:
        for tid in ids:
            client.delete(f"/api/leave/types/{tid}", headers=hr_manager_auth)


def test_type_limits_endpoint_also_lists_sharing_types_without_a_limit(client, pool_setup):
    emp, headers, pool, shared = pool_setup(pool_days=14, limit=0)
    mon = _monday_after(date.today() + timedelta(days=45))
    assert _apply(client, headers, emp, shared, mon, mon + timedelta(days=2)).status_code == 201
    rows = client.get(f"/api/leave/type-limits?year={mon.year}", headers=headers).json()
    mine = next(r for r in rows if r["leave_type_id"] == shared["id"])
    assert (mine["limit_days"], mine["used_days"], mine["remaining_days"]) == (0, 3, None)
    assert mine["pool_leave_type_id"] == pool["id"]
