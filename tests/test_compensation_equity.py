"""Integration tests for routers/compensation_equity.py: equity grant
propose -> approve/reject -> cancel lifecycle, the generated cliff +
quarterly vesting schedule, marking tranches vested, and Phantom-stock
cash settlement. One of four compensation sub-routers split out of the
former routers/compensation.py that had zero dedicated test coverage
before this build-out.
"""
import os

import pytest


def _unique_name(prefix="ZZ Employee"):
    return f"{prefix} {os.urandom(4).hex()}"


def test_create_equity_grant_starts_pending_approval(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Equity Grant Employee"))
    res = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 4800, "vesting_start_date": "2026-01-01", "vesting_years": 4, "cliff_months": 12,
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Pending Approval"
    assert body["quantity"] == 4800


def test_create_equity_grant_404_unknown_employee(client, hr_manager_auth):
    res = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": "NONEXISTENT", "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 100, "vesting_start_date": "2026-01-01",
    })
    assert res.status_code == 404


def test_list_equity_grants(client, hr_manager_auth, make_test_employee):
    name = _unique_name("ZZ Equity List Employee")
    emp = make_test_employee(full_name=name)
    created = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "ISO", "grant_date": "2026-01-01",
        "quantity": 1000, "vesting_start_date": "2026-01-01",
    }).json()
    listed = client.get("/api/compensation/equity-grants", headers=hr_manager_auth).json()
    match = next(g for g in listed if g["id"] == created["id"])
    assert match["employee_name"] == name


def test_equity_endpoints_require_comp_hr_role(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Equity Non-HR")
    assert client.get("/api/compensation/equity-grants", headers=headers).status_code == 403
    assert client.post("/api/compensation/equity-grants", headers=headers, json={
        "employee_id": "X", "grant_type": "RSU", "grant_date": "2026-01-01", "quantity": 1, "vesting_start_date": "2026-01-01",
    }).status_code == 403


def test_decide_equity_grant_approve_generates_vesting_schedule(client, hr_manager_auth, make_test_employee):
    """quantity=4800, 4yr vest, 12mo cliff: cliff tranche is 4800*12/48=1200
    at the 1yr mark, then the remaining 3600 splits evenly across the 12
    remaining quarters (300 each) — 13 events total, summing back to 4800,
    ending exactly 4 years after the vesting start date."""
    emp = make_test_employee(full_name=_unique_name("ZZ Vesting Schedule Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 4800, "vesting_start_date": "2026-01-01", "vesting_years": 4, "cliff_months": 12,
    }).json()

    res = client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Approved"

    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    events = detail["vesting_events"]
    assert len(events) == 13  # 1 cliff tranche + 12 quarterly tranches
    assert sum(e["quantity_vested"] for e in events) == 4800
    assert all(e["status"] == "Scheduled" for e in events)
    assert detail["quantity_vested"] == 0
    assert detail["quantity_unvested"] == 4800

    cliff_event = min(events, key=lambda e: e["vest_date"])
    assert cliff_event["vest_date"] == "2027-01-01"
    assert cliff_event["quantity_vested"] == 1200

    last_event = max(events, key=lambda e: e["vest_date"])
    assert last_event["vest_date"] == "2030-01-01"  # exactly 4 years after vesting_start_date


def test_decide_equity_grant_reject_generates_no_vesting_schedule(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Vesting Reject Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1000, "vesting_start_date": "2026-01-01",
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Rejected"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    assert detail["vesting_events"] == []


def test_decide_equity_grant_already_decided_rejected(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Vesting Twice Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1000, "vesting_start_date": "2026-01-01",
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    second = client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Rejected"})
    assert second.status_code == 400


def test_mark_vesting_event_vested(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Mark Vested Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1200, "vesting_start_date": "2026-01-01", "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    event = detail["vesting_events"][0]

    res = client.put(f"/api/compensation/vesting-events/{event['id']}/vest", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Vested"
    assert body["vested_at"] is not None

    detail2 = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    assert detail2["quantity_vested"] == event["quantity_vested"]


def test_mark_vesting_event_vested_requires_scheduled(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Mark Vested Twice Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1200, "vesting_start_date": "2026-01-01", "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    event_id = detail["vesting_events"][0]["id"]
    client.put(f"/api/compensation/vesting-events/{event_id}/vest", headers=hr_manager_auth)
    second = client.put(f"/api/compensation/vesting-events/{event_id}/vest", headers=hr_manager_auth)
    assert second.status_code == 400


def test_cancel_equity_grant_cancels_only_scheduled_tranches(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Cancel Grant Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1200, "vesting_start_date": "2026-01-01", "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    events = detail["vesting_events"]
    assert len(events) >= 2, "need at least 2 tranches to distinguish vested-preserved from scheduled-cancelled"
    vested_event, scheduled_event = events[0], events[1]
    client.put(f"/api/compensation/vesting-events/{vested_event['id']}/vest", headers=hr_manager_auth)

    res = client.put(f"/api/compensation/equity-grants/{grant['id']}/cancel", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Cancelled"

    detail2 = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    by_id = {e["id"]: e for e in detail2["vesting_events"]}
    assert by_id[vested_event["id"]]["status"] == "Vested"  # untouched
    assert by_id[scheduled_event["id"]]["status"] == "Cancelled"


def test_cancel_equity_grant_requires_approved_status(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Cancel Not Approved Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1000, "vesting_start_date": "2026-01-01",
    }).json()
    res = client.put(f"/api/compensation/equity-grants/{grant['id']}/cancel", headers=hr_manager_auth)
    assert res.status_code == 400


def test_settle_phantom_vesting_event_pays_appreciation_only(client, hr_manager_auth, make_test_employee):
    """Phantom stock pays out (settlement_price - fair_market_value_at_grant)
    x quantity_vested — the gain over the grant's baseline, not a fixed
    amount, and never negative."""
    emp = make_test_employee(full_name=_unique_name("ZZ Phantom Settle Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "Phantom", "grant_date": "2026-01-01",
        "quantity": 1000, "fair_market_value_at_grant": 10, "vesting_start_date": "2026-01-01",
        "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    event = detail["vesting_events"][0]
    client.put(f"/api/compensation/vesting-events/{event['id']}/vest", headers=hr_manager_auth)

    res = client.put(f"/api/compensation/vesting-events/{event['id']}/settle", headers=hr_manager_auth, json={
        "settlement_price": 15,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Paid"
    assert body["settlement_price"] == 15
    assert body["cash_payout"] == (15 - 10) * event["quantity_vested"]
    assert body["payout_date"] is not None


def test_settle_phantom_vesting_event_clamps_at_zero_when_price_dropped(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Phantom Loss Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "Phantom", "grant_date": "2026-01-01",
        "quantity": 1000, "fair_market_value_at_grant": 10, "vesting_start_date": "2026-01-01",
        "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    event = detail["vesting_events"][0]
    client.put(f"/api/compensation/vesting-events/{event['id']}/vest", headers=hr_manager_auth)

    res = client.put(f"/api/compensation/vesting-events/{event['id']}/settle", headers=hr_manager_auth, json={
        "settlement_price": 5,  # below the RM10 baseline
    })
    assert res.status_code == 200, res.text
    assert res.json()["cash_payout"] == 0.0


def test_settle_vesting_event_rejects_non_phantom_grant(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Non-Phantom Settle Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "RSU", "grant_date": "2026-01-01",
        "quantity": 1000, "vesting_start_date": "2026-01-01", "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    event = detail["vesting_events"][0]
    client.put(f"/api/compensation/vesting-events/{event['id']}/vest", headers=hr_manager_auth)

    res = client.put(f"/api/compensation/vesting-events/{event['id']}/settle", headers=hr_manager_auth, json={"settlement_price": 15})
    assert res.status_code == 400


def test_settle_vesting_event_requires_vested_status(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name=_unique_name("ZZ Settle Not Vested Employee"))
    grant = client.post("/api/compensation/equity-grants", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "grant_type": "Phantom", "grant_date": "2026-01-01",
        "quantity": 1000, "fair_market_value_at_grant": 10, "vesting_start_date": "2026-01-01",
        "vesting_years": 1, "cliff_months": 0,
    }).json()
    client.put(f"/api/compensation/equity-grants/{grant['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    detail = client.get(f"/api/compensation/equity-grants/{grant['id']}", headers=hr_manager_auth).json()
    event = detail["vesting_events"][0]  # still Scheduled, never marked Vested

    res = client.put(f"/api/compensation/vesting-events/{event['id']}/settle", headers=hr_manager_auth, json={"settlement_price": 15})
    assert res.status_code == 400
