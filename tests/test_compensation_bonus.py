"""Integration tests for routers/compensation_bonus.py: bonus/incentive
plan CRUD and the payout propose -> decide -> pay lifecycle. One of four
compensation sub-routers split out of the former routers/compensation.py
that had zero dedicated test coverage before this build-out.
"""
import os

import pytest


def _unique_name(prefix="ZZ Bonus Plan"):
    return f"{prefix} {os.urandom(4).hex()}"


@pytest.fixture
def make_bonus_plan(client, hr_manager_auth):
    def _make(**overrides):
        payload = {"plan_name": _unique_name(), "plan_type": "Annual", "plan_year": 2027}
        payload.update(overrides)
        res = client.post("/api/compensation/bonus-plans", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create bonus plan: {res.text}"
        return res.json()
    return _make


def test_create_bonus_plan_starts_draft(client, make_bonus_plan):
    plan = make_bonus_plan(plan_type="Spot", budget_pool_amount=10000)
    assert plan["status"] == "Draft"
    assert plan["plan_type"] == "Spot"
    assert plan["budget_pool_amount"] == 10000


def test_list_bonus_plans(client, hr_manager_auth, make_bonus_plan):
    plan = make_bonus_plan()
    listed = client.get("/api/compensation/bonus-plans", headers=hr_manager_auth).json()
    assert plan["id"] in [p["id"] for p in listed]


def test_update_bonus_plan(client, hr_manager_auth, make_bonus_plan):
    plan = make_bonus_plan()
    res = client.put(f"/api/compensation/bonus-plans/{plan['id']}", headers=hr_manager_auth, json={
        "status": "Active", "budget_pool_amount": 5000,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Active"
    assert body["budget_pool_amount"] == 5000
    assert body["plan_name"] == plan["plan_name"]  # untouched field preserved


def test_update_bonus_plan_404_unknown(client, hr_manager_auth):
    res = client.put("/api/compensation/bonus-plans/999999999", headers=hr_manager_auth, json={"status": "Active"})
    assert res.status_code == 404


def test_bonus_plan_endpoints_require_comp_hr_role(client, employee_with_login, make_bonus_plan):
    plan = make_bonus_plan()
    _, headers = employee_with_login(full_name="ZZ Bonus Non-HR")
    assert client.get("/api/compensation/bonus-plans", headers=headers).status_code == 403
    assert client.post("/api/compensation/bonus-plans", headers=headers, json={
        "plan_name": "X", "plan_type": "Annual",
    }).status_code == 403
    assert client.get(f"/api/compensation/bonus-plans/{plan['id']}/payouts", headers=headers).status_code == 403


def test_create_and_list_bonus_payout(client, hr_manager_auth, make_bonus_plan, make_test_employee):
    plan = make_bonus_plan()
    emp = make_test_employee(full_name="ZZ Bonus Payout Employee")
    res = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "target_amount": 1000, "awarded_amount": 800, "reason": "ZZ strong quarter",
    })
    assert res.status_code == 201, res.text
    payout = res.json()
    assert payout["status"] == "Pending"
    assert payout["awarded_amount"] == 800
    assert payout["bonus_plan_id"] == plan["id"]

    listed = client.get(f"/api/compensation/bonus-plans/{plan['id']}/payouts", headers=hr_manager_auth).json()
    match = next(p for p in listed if p["id"] == payout["id"])
    assert match["employee_name"] == "ZZ Bonus Payout Employee"


def test_create_bonus_payout_404_unknown_plan(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/compensation/bonus-payouts?bonus_plan_id=999999999", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "awarded_amount": 100,
    })
    assert res.status_code == 404


def test_create_bonus_payout_404_unknown_employee(client, hr_manager_auth, make_bonus_plan):
    plan = make_bonus_plan()
    res = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": "NONEXISTENT", "awarded_amount": 100,
    })
    assert res.status_code == 404


def test_decide_bonus_payout_approve_then_pay(client, hr_manager_auth, make_bonus_plan, make_test_employee):
    plan = make_bonus_plan()
    emp = make_test_employee(full_name="ZZ Bonus Approve Pay")
    payout = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "awarded_amount": 500,
    }).json()

    decide_res = client.put(f"/api/compensation/bonus-payouts/{payout['id']}", headers=hr_manager_auth, json={"status": "Approved"})
    assert decide_res.status_code == 200, decide_res.text
    decided = decide_res.json()
    assert decided["status"] == "Approved"
    assert decided["approved_by_user_id"] is not None
    assert decided["approval_date"] is not None

    pay_res = client.put(f"/api/compensation/bonus-payouts/{payout['id']}/pay", headers=hr_manager_auth)
    assert pay_res.status_code == 200, pay_res.text
    paid = pay_res.json()
    assert paid["status"] == "Paid"
    assert paid["payout_date"] is not None


def test_decide_bonus_payout_reject(client, hr_manager_auth, make_bonus_plan, make_test_employee):
    plan = make_bonus_plan()
    emp = make_test_employee(full_name="ZZ Bonus Reject")
    payout = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "awarded_amount": 300,
    }).json()
    res = client.put(f"/api/compensation/bonus-payouts/{payout['id']}", headers=hr_manager_auth, json={"status": "Rejected"})
    assert res.status_code == 200
    assert res.json()["status"] == "Rejected"


def test_mark_bonus_payout_paid_requires_approved(client, hr_manager_auth, make_bonus_plan, make_test_employee):
    plan = make_bonus_plan()
    emp = make_test_employee(full_name="ZZ Bonus Pay Not Approved")
    payout = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "awarded_amount": 300,
    }).json()
    res = client.put(f"/api/compensation/bonus-payouts/{payout['id']}/pay", headers=hr_manager_auth)
    assert res.status_code == 400
