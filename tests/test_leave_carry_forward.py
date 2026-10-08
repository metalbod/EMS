"""Leave type carry-forward rules: the percentage base (leave balance vs the
employee's own entitlement) and how the two limits combine (lower vs higher).
core/leave_balance_ops.py's _compute_carry_forward is pure, so most of this is
a table of cases; the API tests cover persistence, validation and defaults."""
import os

import pytest

from core.leave_balance_ops import _compute_carry_forward


def lt(max_days=0, max_pct=0, basis="balance", rule="lower", enabled=True):
    return {"carry_forward_enabled": enabled, "carry_forward_max_days": max_days,
            "carry_forward_max_percent": max_pct, "carry_forward_percent_basis": basis,
            "carry_forward_cap_rule": rule}


def bal(entitled=14, carried_in=0, used=6):
    return {"entitled_days": entitled, "carried_forward_days": carried_in, "used_days": used}


# (leave type, last year's balance row, days that should carry)
CASES = [
    # --- the original behaviour (defaults): % of unused balance, lower of the two ---
    (lt(7, 50), bal(14, 0, 6), 4),                       # balance 8: 50% = 4, max 7 -> lower = 4
    (lt(3, 50), bal(14, 0, 6), 3),                       # max days is the lower one
    (lt(0, 50), bal(14, 0, 6), 4),                       # only the % set
    (lt(7, 0), bal(14, 0, 6), 7),                        # only max days set
    (lt(0, 0), bal(14, 0, 6), 8),                        # no limits: everything unused
    (lt(20, 0), bal(14, 0, 6), 8),                       # never more than unused
    # --- percentage of the employee's own entitlement ---
    (lt(7, 50, "entitlement"), bal(14, 0, 6), 7),        # 50% of 14 = 7, max 7
    (lt(0, 50, "entitlement"), bal(14, 0, 6), 7),        # % alone: 7 (of 8 left)
    (lt(0, 50, "entitlement"), bal(14, 0, 12), 2),       # only 2 left, so 2 not 7
    (lt(0, 25, "entitlement"), bal(10, 0, 0), 2.5),      # 25% of 10, half-day rounding
    (lt(0, 50, "entitlement"), bal(7, 0, 0), 3.5),       # uses THIS employee's 7 (pro-rated), not a type default
    # --- the 'higher' rule ---
    (lt(7, 50, "balance", "higher"), bal(14, 0, 6), 7),  # 4 vs 7 -> 7
    (lt(3, 50, "balance", "higher"), bal(14, 0, 6), 4),  # 3 vs 4 -> 4
    (lt(7, 50, "entitlement", "higher"), bal(20, 0, 12), 8),   # 7 vs 10 -> 10, but only 8 left -> 8 (not capped at 7)
    (lt(7, 50, "entitlement", "higher"), bal(20, 0, 5), 10),   # 7 vs 10 -> 10, 15 left -> 10 (exceeds max days)
    (lt(7, 0, "balance", "higher"), bal(14, 0, 6), 7),   # one limit only: rule irrelevant
    (lt(0, 50, "balance", "higher"), bal(14, 0, 6), 4),
    # --- carried-in days count as unused balance, not as entitlement ---
    (lt(0, 50, "balance"), bal(14, 4, 6), 6),            # balance 12 -> 6
    (lt(0, 50, "entitlement"), bal(14, 4, 6), 7),        # 50% of entitlement 14 = 7 (of 12 left)
    # --- nothing to carry ---
    (lt(7, 50), bal(14, 0, 14), 0),
    (lt(7, 50), bal(14, 0, 20), 0),
    (lt(7, 50, enabled=False), bal(14, 0, 6), 0),
]


@pytest.mark.parametrize("leave_type,prior,expected", CASES)
def test_compute_carry_forward(leave_type, prior, expected):
    assert _compute_carry_forward(leave_type, prior) == expected


def test_no_prior_balance_or_leave_type_carries_nothing():
    assert _compute_carry_forward(lt(7, 50), None) == 0
    assert _compute_carry_forward(None, bal()) == 0


# ---------------------------------------------------------------------------
# API: persistence, defaults, validation, audit
# ---------------------------------------------------------------------------
def _payload(**over):
    p = {"name": f"ZZ Carry {os.urandom(3).hex()}", "annual_entitlement": 14, "carry_forward_enabled": True,
         "carry_forward_max_days": 7, "carry_forward_max_percent": 50}
    p.update(over)
    return p


def test_leave_type_defaults_keep_the_original_rules(client, hr_manager_auth):
    res = client.post("/api/leave/types", headers=hr_manager_auth, json=_payload())
    assert res.status_code == 201, res.text
    body = res.json()
    try:
        assert body["carry_forward_percent_basis"] == "balance" and body["carry_forward_cap_rule"] == "lower"
    finally:
        client.delete(f"/api/leave/types/{body['id']}", headers=hr_manager_auth)


def test_leave_type_stores_and_updates_the_new_options(client, hr_manager_auth):
    res = client.post("/api/leave/types", headers=hr_manager_auth, json=_payload(
        carry_forward_percent_basis="entitlement", carry_forward_cap_rule="higher"))
    assert res.status_code == 201, res.text
    created = res.json()
    try:
        assert (created["carry_forward_percent_basis"], created["carry_forward_cap_rule"]) == ("entitlement", "higher")
        listed = next(t for t in client.get("/api/leave/types", headers=hr_manager_auth).json() if t["id"] == created["id"])
        assert (listed["carry_forward_percent_basis"], listed["carry_forward_cap_rule"]) == ("entitlement", "higher")

        upd = client.put(f"/api/leave/types/{created['id']}", headers=hr_manager_auth, json=_payload(
            name=created["name"], carry_forward_percent_basis="balance", carry_forward_cap_rule="lower"))
        assert upd.status_code == 200, upd.text
        assert (upd.json()["carry_forward_percent_basis"], upd.json()["carry_forward_cap_rule"]) == ("balance", "lower")
    finally:
        client.delete(f"/api/leave/types/{created['id']}", headers=hr_manager_auth)


@pytest.mark.parametrize("field,value", [("carry_forward_percent_basis", "everything"), ("carry_forward_cap_rule", "average")])
def test_leave_type_rejects_unknown_option_values(client, hr_manager_auth, field, value):
    assert client.post("/api/leave/types", headers=hr_manager_auth, json=_payload(**{field: value})).status_code == 422
