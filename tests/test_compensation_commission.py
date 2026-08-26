"""Integration tests for routers/compensation_commission.py: commission
plan CRUD and the entry record -> decide -> pay lifecycle, including the
server-side calculated_commission derivation. One of four compensation
sub-routers split out of the former routers/compensation.py that had zero
dedicated test coverage before this build-out.
"""
import os

import pytest


def _unique_name(prefix="ZZ Commission Plan"):
    return f"{prefix} {os.urandom(4).hex()}"


@pytest.fixture
def make_commission_plan(client, hr_manager_auth):
    def _make(**overrides):
        payload = {"plan_name": _unique_name(), "plan_type": "Flat Rate", "default_rate_percent": 5, "plan_year": 2027}
        payload.update(overrides)
        res = client.post("/api/compensation/commission-plans", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create commission plan: {res.text}"
        return res.json()
    return _make


def test_create_commission_plan_starts_draft(client, make_commission_plan):
    plan = make_commission_plan(plan_type="Tiered")
    assert plan["status"] == "Draft"
    assert plan["plan_type"] == "Tiered"


def test_list_commission_plans(client, hr_manager_auth, make_commission_plan):
    plan = make_commission_plan()
    listed = client.get("/api/compensation/commission-plans", headers=hr_manager_auth).json()
    assert plan["id"] in [p["id"] for p in listed]


def test_update_commission_plan(client, hr_manager_auth, make_commission_plan):
    plan = make_commission_plan()
    res = client.put(f"/api/compensation/commission-plans/{plan['id']}", headers=hr_manager_auth, json={
        "status": "Active", "default_rate_percent": 8,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Active"
    assert body["default_rate_percent"] == 8


def test_commission_plan_endpoints_require_comp_hr_role(client, employee_with_login, make_commission_plan):
    plan = make_commission_plan()
    _, headers = employee_with_login(full_name="ZZ Commission Non-HR")
    assert client.get("/api/compensation/commission-plans", headers=headers).status_code == 403
    assert client.get(f"/api/compensation/commission-plans/{plan['id']}/entries", headers=headers).status_code == 403


def test_create_commission_entry_calculates_commission_server_side(client, hr_manager_auth, make_commission_plan, make_test_employee):
    plan = make_commission_plan()
    emp = make_test_employee(full_name="ZZ Commission Entry Employee")
    res = client.post(f"/api/compensation/commission-entries?commission_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "sales_amount": 10000, "commission_rate_percent": 7.5, "notes": "ZZ Q1 sales",
    })
    assert res.status_code == 201, res.text
    entry = res.json()
    assert entry["calculated_commission"] == 750.0  # 10000 * 7.5%
    assert entry["status"] == "Pending"

    listed = client.get(f"/api/compensation/commission-plans/{plan['id']}/entries", headers=hr_manager_auth).json()
    match = next(e for e in listed if e["id"] == entry["id"])
    assert match["employee_name"] == "ZZ Commission Entry Employee"


def test_create_commission_entry_404_unknown_plan(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/compensation/commission-entries?commission_plan_id=999999999", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "sales_amount": 1000, "commission_rate_percent": 5,
    })
    assert res.status_code == 404


def test_create_commission_entry_404_unknown_employee(client, hr_manager_auth, make_commission_plan):
    plan = make_commission_plan()
    res = client.post(f"/api/compensation/commission-entries?commission_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": "NONEXISTENT", "sales_amount": 1000, "commission_rate_percent": 5,
    })
    assert res.status_code == 404


def test_decide_and_pay_commission_entry(client, hr_manager_auth, make_commission_plan, make_test_employee):
    plan = make_commission_plan()
    emp = make_test_employee(full_name="ZZ Commission Decide Pay")
    entry = client.post(f"/api/compensation/commission-entries?commission_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "sales_amount": 2000, "commission_rate_percent": 10,
    }).json()

    decide_res = client.put(f"/api/compensation/commission-entries/{entry['id']}", headers=hr_manager_auth, json={"status": "Approved"})
    assert decide_res.status_code == 200, decide_res.text
    assert decide_res.json()["status"] == "Approved"

    pay_res = client.put(f"/api/compensation/commission-entries/{entry['id']}/pay", headers=hr_manager_auth)
    assert pay_res.status_code == 200, pay_res.text
    paid = pay_res.json()
    assert paid["status"] == "Paid"
    assert paid["payout_date"] is not None


def test_mark_commission_entry_paid_requires_approved(client, hr_manager_auth, make_commission_plan, make_test_employee):
    plan = make_commission_plan()
    emp = make_test_employee(full_name="ZZ Commission Pay Not Approved")
    entry = client.post(f"/api/compensation/commission-entries?commission_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "sales_amount": 500, "commission_rate_percent": 5,
    }).json()
    res = client.put(f"/api/compensation/commission-entries/{entry['id']}/pay", headers=hr_manager_auth)
    assert res.status_code == 400


def test_decide_commission_entry_reject(client, hr_manager_auth, make_commission_plan, make_test_employee):
    plan = make_commission_plan()
    emp = make_test_employee(full_name="ZZ Commission Reject")
    entry = client.post(f"/api/compensation/commission-entries?commission_plan_id={plan['id']}", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "sales_amount": 500, "commission_rate_percent": 5,
    }).json()
    res = client.put(f"/api/compensation/commission-entries/{entry['id']}", headers=hr_manager_auth, json={"status": "Rejected"})
    assert res.status_code == 200
    assert res.json()["status"] == "Rejected"
