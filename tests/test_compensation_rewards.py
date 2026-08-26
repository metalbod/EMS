"""Integration tests for routers/compensation_rewards.py's Total Rewards
Statement endpoints (self-service /mine and HR-facing /{employee_id}) —
the pay-equity report endpoint in the same file already has coverage in
test_compensation.py. One of four compensation sub-routers split out of
the former routers/compensation.py that had zero dedicated test coverage
before this build-out.
"""
import datetime
import os

import pytest


def _unique_name(prefix="ZZ Rewards Employee"):
    return f"{prefix} {os.urandom(4).hex()}"


def _set_compensation(client, hr_manager_auth, employee_id, effective_date="2026-01-01"):
    res = client.post(f"/api/compensation/employees/{employee_id}/compensation", headers=hr_manager_auth, json={
        "effective_date": effective_date,
    })
    assert res.status_code == 201, f"failed to set compensation: {res.text}"
    return res.json()


def _approve_bonus(client, hr_manager_auth, employee_id, amount):
    plan = client.post("/api/compensation/bonus-plans", headers=hr_manager_auth, json={
        "plan_name": _unique_name("ZZ Rewards Bonus Plan"), "plan_type": "Spot",
    }).json()
    payout = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": employee_id, "awarded_amount": amount,
    }).json()
    res = client.put(f"/api/compensation/bonus-payouts/{payout['id']}", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 200
    return payout


def _approve_commission(client, hr_manager_auth, employee_id, sales_amount, rate_percent):
    plan = client.post("/api/compensation/commission-plans", headers=hr_manager_auth, json={
        "plan_name": _unique_name("ZZ Rewards Commission Plan"), "plan_type": "Flat Rate",
    }).json()
    entry = client.post(f"/api/compensation/commission-entries?commission_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": employee_id, "sales_amount": sales_amount, "commission_rate_percent": rate_percent,
    }).json()
    res = client.put(f"/api/compensation/commission-entries/{entry['id']}", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 200
    return entry


def test_my_total_rewards_aggregates_salary_bonus_and_commission(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login(full_name=_unique_name(), basic_salary=6000.00)
    _set_compensation(client, hr_manager_auth, emp["employee_id"])
    _approve_bonus(client, hr_manager_auth, emp["employee_id"], 2000)
    _approve_commission(client, hr_manager_auth, emp["employee_id"], 10000, 5)  # RM500 commission

    res = client.get("/api/compensation/total-rewards/mine", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["base_salary_monthly"] == 6000.00
    assert body["base_salary_annualized"] == 72000.00
    assert body["bonus_ytd"] == 2000.0
    assert body["commission_ytd"] == 500.0
    assert body["total_cash_compensation"] == 72000.0 + 2000.0 + 500.0


def test_my_total_rewards_requires_linked_employee(client, hr_manager_auth):
    res = client.get("/api/compensation/total-rewards/mine", headers=hr_manager_auth)
    assert res.status_code == 404


def test_my_total_rewards_defaults_to_current_year(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login(full_name=_unique_name(), basic_salary=1000.00)
    res = client.get("/api/compensation/total-rewards/mine", headers=headers)
    assert res.status_code == 200
    assert res.json()["year"] == datetime.datetime.utcnow().year


def test_employee_total_rewards_hr_facing(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name(), basic_salary=4500.00)
    _set_compensation(client, hr_manager_auth, emp["employee_id"])

    res = client.get(f"/api/compensation/total-rewards/{emp['employee_id']}", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["employee_id"] == emp["employee_id"]
    assert body["employee_name"] == emp["full_name"]
    assert body["base_salary_monthly"] == 4500.00


def test_employee_total_rewards_404_unknown_employee(client, hr_manager_auth):
    res = client.get("/api/compensation/total-rewards/NONEXISTENT", headers=hr_manager_auth)
    assert res.status_code == 404


def test_employee_total_rewards_requires_comp_hr_role(client, employee_with_login, make_test_employee):
    emp = make_test_employee(full_name=_unique_name())
    _, headers = employee_with_login(full_name=_unique_name())
    res = client.get(f"/api/compensation/total-rewards/{emp['employee_id']}", headers=headers)
    assert res.status_code == 403


def test_my_total_rewards_no_compensation_record_returns_nulls(client, hr_manager_auth, employee_with_login):
    """An employee with no employee_compensation row at all (never had one
    set) gets None salary figures rather than a crash."""
    emp, headers = employee_with_login(full_name=_unique_name())
    res = client.get("/api/compensation/total-rewards/mine", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["base_salary_monthly"] is None
    assert body["base_salary_annualized"] is None
    assert body["total_cash_compensation"] == 0
