"""
Integration tests for routers/leave.py: Leave Types, Balances, and
Applications. This is the most business-logic-heavy router tested so far
(weekday counting excluding holidays, balance deduction/reversal on
approve/cancel), so tests lean on real happy-path + reversal round-trips
rather than just CRUD.

Uses a fixed, known Mon-Fri work week (2027-03-01 to 2027-03-05, 5 working
days, no weekend in between) for application date ranges, verified via
Python's own date.weekday() rather than assumed.
"""
import pytest
from concurrent.futures import ThreadPoolExecutor

WORK_WEEK_START = "2027-03-01"  # Monday
WORK_WEEK_END = "2027-03-05"    # Friday (5 working days)


@pytest.fixture
def hr_admin_auth(make_test_user, test_institution):
    """LEAVE_MANAGE_ROLES includes hr_admin (unlike PROJECT_MANAGE_ROLES),
    so this covers a role not exercised by hr_manager_auth alone."""
    token, _ = make_test_user(role="hr_admin")
    return {
        "Authorization": f"Bearer {token}",
        "X-Institution-Id": str(test_institution["id"]),
    }


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    """A real employee record with a linked login (role=employee), since
    leave applications are scoped by employee_id/role, not just an
    hr_manager token with no employee_id. Returns (emp, headers).
    Cleans up the user account; the employee itself is deactivated by
    make_test_employee's own teardown."""
    emp = make_test_employee()
    username = f"zzleavetest_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Leave Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, f"failed to create employee-linked user: {res.text}"
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    yield emp, headers

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


# ---------------------------------------------------------------------------
# Leave Types
# ---------------------------------------------------------------------------
def test_list_leave_types_requires_auth(client):
    res = client.get("/api/leave/types")
    assert res.status_code in (401, 403)


def test_create_leave_type_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/leave/types", headers=headers, json={"name": "ZZ"})
    assert res.status_code == 403


def test_create_leave_type_success(client, make_test_leave_type):
    lt = make_test_leave_type(name="ZZ Annual Leave", annual_entitlement=20)
    assert lt["name"] == "ZZ Annual Leave"
    assert lt["annual_entitlement"] == 20


def test_hr_admin_can_manage_leave_types(client, hr_admin_auth):
    """hr_admin is in LEAVE_MANAGE_ROLES, unlike PROJECT_MANAGE_ROLES."""
    res = client.post("/api/leave/types", headers=hr_admin_auth, json={"name": "ZZ HR Admin Type"})
    assert res.status_code == 201
    client.delete(f"/api/leave/types/{res.json()['id']}", headers=hr_admin_auth)


def test_list_leave_types_includes_created(client, hr_manager_auth, make_test_leave_type):
    lt = make_test_leave_type()
    res = client.get("/api/leave/types", headers=hr_manager_auth)
    assert res.status_code == 200
    assert lt["id"] in [t["id"] for t in res.json()]


def test_update_leave_type_success(client, hr_manager_auth, make_test_leave_type):
    lt = make_test_leave_type()
    res = client.put(
        f"/api/leave/types/{lt['id']}", headers=hr_manager_auth,
        json={"name": "ZZ Renamed", "annual_entitlement": 10},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "ZZ Renamed"


def test_update_leave_type_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/leave/types/999999999", headers=hr_manager_auth, json={"name": "ZZ"})
    assert res.status_code == 404


def test_delete_leave_type_soft_deletes(client, hr_manager_auth, make_test_leave_type):
    lt = make_test_leave_type()
    res = client.delete(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/leave/types", headers=hr_manager_auth).json()
    assert lt["id"] not in [t["id"] for t in listed]


# ---------------------------------------------------------------------------
# Leave Applications: validation
# ---------------------------------------------------------------------------
def test_create_application_for_another_employee_as_employee_role_forbidden(
    client, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": "EMP_SOMEONE_ELSE", "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 403


def test_create_application_unknown_leave_type_returns_404(client, employee_with_user):
    emp, headers = employee_with_user
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": 999999999,
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 404


def test_create_application_requires_attachment_when_type_demands_it(
    client, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, requires_attachment=True)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 400
    assert "requires a supporting document" in res.json()["detail"]


def test_create_application_all_weekend_returns_400(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    # 2027-03-06 is a Saturday, 2027-03-07 is a Sunday.
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-06", "end_date": "2027-03-07",
    })
    assert res.status_code == 400
    assert "no working days" in res.json()["detail"]


def test_calendar_day_leave_type_counts_weekends_and_holidays(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    """Maternity/Paternity-style leave types (count_calendar_days=True) count
    every day in the range, unlike the working-days-only default."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, annual_entitlement=60, count_calendar_days=True)
    # 2027-03-06 is a Saturday, 2027-03-07 is a Sunday — a working-days type
    # would reject this range entirely (see test_create_application_all_weekend_returns_400).
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-06", "end_date": "2027-03-07",
    })
    assert res.status_code == 201, res.text
    assert res.json()["days_count"] == 2


def test_working_day_leave_type_still_excludes_weekends_by_default(client, employee_with_user, make_test_leave_type):
    """count_calendar_days defaults to False — existing leave types are unaffected."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    assert not lt["count_calendar_days"]
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201, res.text
    assert res.json()["days_count"] == 5


def test_create_application_exceeding_balance_returns_400(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, annual_entitlement=2)  # 5 working days requested > 2 entitled
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 400
    assert "Insufficient balance" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Leave Applications: happy path + status transitions + balance math
# ---------------------------------------------------------------------------
def test_create_application_auto_approved_when_type_does_not_require_approval(
    client, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, annual_entitlement=14)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "Approved"
    assert body["days_count"] == 5.0


def test_create_application_pending_when_type_requires_approval(
    client, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201
    assert res.json()["status"] == "Pending Approval"


def test_full_apply_approve_cancel_balance_round_trip(
    client, hr_manager_auth, employee_with_user, make_test_leave_type
):
    """Applies (Pending), approves (balance debited), cancels (balance
    credited back) — verifies the balance math nets out to zero."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)

    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert apply_res.status_code == 201
    app_id = apply_res.json()["id"]

    balance_before = client.get(
        "/api/leave/balances", headers=hr_manager_auth,
        params={"employee_id": emp["employee_id"], "year": 2027},
    ).json()
    bal_row = next(b for b in balance_before if b["leave_type_id"] == lt["id"])
    assert bal_row["used_days"] == 0.0

    approve_res = client.patch(
        f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Approved"}
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "Approved"

    balance_after_approve = client.get(
        "/api/leave/balances", headers=hr_manager_auth,
        params={"employee_id": emp["employee_id"], "year": 2027},
    ).json()
    bal_row = next(b for b in balance_after_approve if b["leave_type_id"] == lt["id"])
    assert bal_row["used_days"] == 5.0

    cancel_res = client.patch(
        f"/api/leave/applications/{app_id}/status", headers=headers, json={"status": "Cancelled"}
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "Cancelled"

    balance_after_cancel = client.get(
        "/api/leave/balances", headers=hr_manager_auth,
        params={"employee_id": emp["employee_id"], "year": 2027},
    ).json()
    bal_row = next(b for b in balance_after_cancel if b["leave_type_id"] == lt["id"])
    assert bal_row["used_days"] == 0.0


def test_approve_application_sets_approved_at(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    app_id = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    }).json()["id"]

    res = client.patch(f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 200, res.text
    assert res.json()["approved_at"] is not None
    assert res.json()["approved_by"] is not None


def test_reject_application_leaves_approved_at_null(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    app_id = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    }).json()["id"]
    res = client.patch(f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Rejected"})
    assert res.status_code == 200, res.text
    assert res.json()["approved_at"] is None


def test_reject_application(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    app_id = apply_res.json()["id"]
    res = client.patch(
        f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth,
        json={"status": "Rejected", "notes": "ZZ not enough coverage"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "Rejected"


def test_employee_cannot_approve_own_application(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    app_id = apply_res.json()["id"]
    res = client.patch(f"/api/leave/applications/{app_id}/status", headers=headers, json={"status": "Approved"})
    assert res.status_code == 403


def test_cannot_reapprove_already_finalized_application(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    app_id = apply_res.json()["id"]
    client.patch(f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Rejected"})
    res = client.patch(f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 400
    assert "already Rejected" in res.json()["detail"]


def test_update_status_invalid_value_returns_400(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    app_id = apply_res.json()["id"]
    res = client.patch(f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Bogus"})
    assert res.status_code == 400


def test_update_status_not_found_returns_404(client, hr_manager_auth):
    res = client.patch("/api/leave/applications/999999999/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 404


def test_list_applications_includes_created(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    app_id = apply_res.json()["id"]
    res = client.get("/api/leave/applications", headers=hr_manager_auth)
    assert res.status_code == 200
    assert app_id in [a["id"] for a in res.json()]


def test_list_applications_filters_by_status(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    app_id = apply_res.json()["id"]

    approved_only = client.get("/api/leave/applications", headers=hr_manager_auth, params={"status": "Approved"}).json()
    assert app_id not in [a["id"] for a in approved_only]

    pending_only = client.get("/api/leave/applications", headers=hr_manager_auth, params={"status": "Pending Approval"}).json()
    assert app_id in [a["id"] for a in pending_only]


# ---------------------------------------------------------------------------
# Leave Balances
# ---------------------------------------------------------------------------
def test_list_balances_requires_auth(client):
    res = client.get("/api/leave/balances")
    assert res.status_code in (401, 403)


def test_employee_auto_gets_balance_row_for_active_leave_type(client, employee_with_user, make_test_leave_type):
    """list_leave_balances auto-creates a balance row for any active leave
    type the employee doesn't have one for yet, when called as 'employee'."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(annual_entitlement=14)
    res = client.get("/api/leave/balances", headers=headers, params={"year": 2027})
    assert res.status_code == 200
    assert lt["id"] in [b["leave_type_id"] for b in res.json()]


def test_adjust_balance_requires_manage_role(client, make_test_user, test_institution, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type()
    balances = client.get("/api/leave/balances", headers=headers, params={"year": 2027}).json()
    bal = next(b for b in balances if b["leave_type_id"] == lt["id"])
    token, _ = make_test_user(role="employee")
    other_headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.patch(f"/api/leave/balances/{bal['id']}", headers=other_headers, json={"entitled_days": 99})
    assert res.status_code == 403


def test_adjust_balance_success(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type()
    balances = client.get("/api/leave/balances", headers=headers, params={"year": 2027}).json()
    bal = next(b for b in balances if b["leave_type_id"] == lt["id"])
    res = client.patch(f"/api/leave/balances/{bal['id']}", headers=hr_manager_auth, json={"entitled_days": 30})
    assert res.status_code == 200
    assert res.json()["entitled_days"] == 30


def test_adjust_balance_not_found_returns_404(client, hr_manager_auth):
    res = client.patch("/api/leave/balances/999999999", headers=hr_manager_auth, json={"entitled_days": 10})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Leave history
# ---------------------------------------------------------------------------
def test_leave_history_requires_manage_role(client, employee_with_user):
    emp, headers = employee_with_user
    res = client.get(f"/api/employees/{emp['employee_id']}/leave-history", headers=headers)
    assert res.status_code == 403


def test_leave_history_records_apply_action(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    res = client.get(f"/api/employees/{emp['employee_id']}/leave-history", headers=hr_manager_auth)
    assert res.status_code == 200
    actions = [entry["action"] for entry in res.json()]
    assert "Applied" in actions


# ---------------------------------------------------------------------------
# Leave Types: shared entitlement (a type draws from another type's balance)
# ---------------------------------------------------------------------------
def test_create_leave_type_sharing_with_another(client, hr_manager_auth, make_test_leave_type):
    parent = make_test_leave_type(annual_entitlement=14)
    res = client.post("/api/leave/types", headers=hr_manager_auth, json={
        "name": "ZZ Emergency Leave", "annual_entitlement": 3,
        "shares_entitlement_with_id": parent["id"],
    })
    assert res.status_code == 201, res.text
    assert res.json()["shares_entitlement_with_id"] == parent["id"]


def test_leave_type_cannot_share_with_itself(client, hr_manager_auth, make_test_leave_type):
    lt = make_test_leave_type()
    res = client.put(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth, json={
        "name": lt["name"], "annual_entitlement": 14, "shares_entitlement_with_id": lt["id"],
    })
    assert res.status_code == 400
    assert "itself" in res.json()["detail"]


def test_leave_type_cannot_share_with_a_type_that_already_shares(client, hr_manager_auth, make_test_leave_type):
    root = make_test_leave_type()
    middle = make_test_leave_type(shares_entitlement_with_id=root["id"])
    res = client.post("/api/leave/types", headers=hr_manager_auth, json={
        "name": "ZZ Chained Leave", "annual_entitlement": 1,
        "shares_entitlement_with_id": middle["id"],
    })
    assert res.status_code == 400
    assert "chain" in res.json()["detail"].lower()


def test_leave_type_with_dependents_cannot_itself_share(client, hr_manager_auth, make_test_leave_type):
    root = make_test_leave_type()
    make_test_leave_type(shares_entitlement_with_id=root["id"])  # dependent on root
    other = make_test_leave_type()
    res = client.put(f"/api/leave/types/{root['id']}", headers=hr_manager_auth, json={
        "name": root["name"], "annual_entitlement": root["annual_entitlement"],
        "shares_entitlement_with_id": other["id"],
    })
    assert res.status_code == 400
    assert "other leave types sharing" in res.json()["detail"]


def test_shared_leave_type_deducts_from_parent_balance(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    """Applying for a leave type that shares entitlement with another type
    should check/deduct the PARENT type's balance, not create its own."""
    emp, headers = employee_with_user
    parent = make_test_leave_type(annual_entitlement=10, requires_approval=False)
    child = make_test_leave_type(annual_entitlement=999, requires_approval=False,
                                  shares_entitlement_with_id=parent["id"])

    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": child["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201, res.text
    app = res.json()
    assert app["leave_type_id"] == child["id"]  # application itself still cites the specific type
    assert app["status"] == "Approved"

    balances = client.get("/api/leave/balances", headers=headers, params={"year": 2027}).json()
    parent_bal = next(b for b in balances if b["leave_type_id"] == parent["id"])
    assert parent_bal["used_days"] == 5  # 5 working days deducted from the PARENT's balance
    assert not any(b["leave_type_id"] == child["id"] for b in balances)  # child never gets its own row


def test_shared_leave_type_respects_parent_balance_limit(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    parent = make_test_leave_type(annual_entitlement=2, requires_approval=False)
    child = make_test_leave_type(annual_entitlement=999, requires_approval=False,
                                  shares_entitlement_with_id=parent["id"])
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": child["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,  # 5 working days > parent's 2
    })
    assert res.status_code == 400
    assert "Insufficient balance" in res.json()["detail"]


def test_cancel_shared_leave_type_application_refunds_parent_balance(
    client, hr_manager_auth, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    parent = make_test_leave_type(annual_entitlement=10, requires_approval=False)
    child = make_test_leave_type(annual_entitlement=999, requires_approval=False,
                                  shares_entitlement_with_id=parent["id"])
    app = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": child["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    }).json()

    res = client.patch(f"/api/leave/applications/{app['id']}/status", headers=headers, json={"status": "Cancelled"})
    assert res.status_code == 200, res.text

    balances = client.get("/api/leave/balances", headers=headers, params={"year": 2027}).json()
    parent_bal = next(b for b in balances if b["leave_type_id"] == parent["id"])
    assert parent_bal["used_days"] == 0


# ---------------------------------------------------------------------------
# Leave Utilization Dashboard (HR Manager / HR Admin only)
# ---------------------------------------------------------------------------
def test_leave_utilization_dashboard_requires_hr_role(client, employee_with_user):
    _, headers = employee_with_user
    res = client.get("/api/leave/dashboard/utilization", headers=headers)
    assert res.status_code == 403


def test_leave_utilization_dashboard_superadmin_denied(client, superadmin_headers):
    """The dashboard's Leave tab is explicitly HR Manager/HR Admin only —
    even superadmin, unlike LEAVE_MANAGE_ROLES elsewhere in this router."""
    res = client.get("/api/leave/dashboard/utilization", headers=superadmin_headers)
    assert res.status_code == 403


def test_leave_utilization_dashboard_reflects_usage_and_breakdown(
    client, hr_manager_auth, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    lt = make_test_leave_type(annual_entitlement=10, requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201, res.text

    dash = client.get("/api/leave/dashboard/utilization", headers=hr_manager_auth, params={"year": 2027}).json()

    # by_type sums every employee in the institution, unbounded — safe to
    # assert on directly. lt is a brand-new, disposable leave type this test
    # just created, so no other employee anywhere could already have a
    # balance row against it.
    by_type = next(t for t in dash["by_type"] if t["leave_type_id"] == lt["id"])
    assert by_type["total_used"] >= 5
    assert by_type["utilization_percent"] > 0

    # top_highest/top_lowest are capped at 10 each out of every employee this
    # shared, never-cleaned test institution has ever accumulated a balance
    # for — this test's own employee isn't guaranteed to make either cut, so
    # only assert response shape here rather than requiring membership.
    for entry in dash["top_highest"] + dash["top_lowest"]:
        assert {"employee_id", "full_name", "total_entitled", "total_used", "utilization_percent", "breakdown"} <= entry.keys()
        for b in entry["breakdown"]:
            assert {"leave_type_name", "entitled_days", "used_days", "utilization_percent"} <= b.keys()

    # If this test's employee did happen to land in a ranking (plausible —
    # 10 slots isn't a small sample), verify their breakdown is correct.
    match = next((e for e in dash["top_highest"] + dash["top_lowest"] if e["employee_id"] == emp["employee_id"]), None)
    if match:
        type_breakdown = next(b for b in match["breakdown"] if b["leave_type_name"] == lt["name"])
        assert type_breakdown["used_days"] == 5
        assert type_breakdown["entitled_days"] == 10


def test_leave_utilization_dashboard_leave_type_filter_narrows_ranking(
    client, hr_manager_auth, employee_with_user, make_test_leave_type
):
    """Clicking a row in the dashboard's "Utilization by Leave Type" list
    (static/js/dashboard.js's setLeaveDashTypeFilter) passes leave_type_id
    through to narrow the Top/Bottom 10 ranking to just that type, instead
    of each employee's total across every type. lt is a brand-new,
    disposable leave type this test just created, so this employee is
    provably the ONLY one who can have a balance row against it — the
    filtered ranking must contain exactly them, scoped to just this type's
    figures, not their unfiltered across-every-type total."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(annual_entitlement=10, requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201, res.text

    unfiltered = client.get("/api/leave/dashboard/utilization", headers=hr_manager_auth, params={"year": 2027}).json()
    dash = client.get(
        "/api/leave/dashboard/utilization", headers=hr_manager_auth,
        params={"year": 2027, "leave_type_id": lt["id"]},
    ).json()

    assert dash["leave_type_id"] == lt["id"]
    # by_type stays unfiltered — the clickable list of every type must be
    # identical whether or not a ranking filter is applied, so it never
    # collapses down to just the one selected type.
    assert {t["leave_type_id"] for t in dash["by_type"]} == {t["leave_type_id"] for t in unfiltered["by_type"]}

    for ranking in (dash["top_highest"], dash["top_lowest"]):
        assert len(ranking) == 1
        entry = ranking[0]
        assert entry["employee_id"] == emp["employee_id"]
        assert entry["total_entitled"] == 10
        assert entry["total_used"] == 5


def test_leave_utilization_dashboard_no_filter_still_returns_null_leave_type_id(
    client, hr_manager_auth,
):
    dash = client.get("/api/leave/dashboard/utilization", headers=hr_manager_auth, params={"year": 2027}).json()
    assert dash["leave_type_id"] is None


# ---------------------------------------------------------------------------
# Leave Types: monthly accrual + per-application/per-month caps
# ---------------------------------------------------------------------------
def test_leave_type_invalid_accrual_mode_returns_422(client, hr_manager_auth):
    res = client.post("/api/leave/types", headers=hr_manager_auth, json={
        "name": "ZZ Bad Accrual", "annual_entitlement": 12, "accrual_mode": "biweekly",
    })
    assert res.status_code == 422


def test_monthly_accrual_rejects_beyond_earned_so_far(client, make_test_leave_type, employee_with_user):
    """Employee joined 2027-01-01; as of the WORK_WEEK (March 2027), a
    12-day annual entitlement has earned 12*3/12=3 days — the 5-day
    application should be rejected as insufficient, even though the full
    annual figure (12) would easily cover it."""
    emp, headers = employee_with_user
    # employee_with_user's underlying employee defaults start_date 2026-01-01
    # (see _valid_employee_payload) — for a 2027 as-of date that's "joined
    # before this year", giving months_earned = as_of.month regardless of
    # day. Same math (3 months earned in March), so no override needed.
    lt = make_test_leave_type(name="ZZ Monthly Accrual Small", annual_entitlement=12,
                              accrual_mode="monthly", requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 400
    assert "Insufficient balance" in res.json()["detail"]


def test_monthly_accrual_allows_within_earned_so_far(client, make_test_leave_type, employee_with_user):
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Monthly Accrual Large", annual_entitlement=24,
                              accrual_mode="monthly", requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201, res.text
    assert res.json()["days_count"] == 5


def test_leave_balances_reports_accrued_days(client, make_test_leave_type, employee_with_user):
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Accrual Balance Check", annual_entitlement=24,
                              accrual_mode="monthly", requires_approval=False)
    balances = client.get("/api/leave/balances", headers=headers, params={"year": 2027}).json()
    bal = next(b for b in balances if b["leave_type_id"] == lt["id"])
    assert bal["entitled_days"] == 24
    # accrued_days is evaluated as of today (real "now"), not the fixed 2027
    # test dates, so just assert it's a fraction of the annual figure and
    # never exceeds it — the exact value depends on the current real month.
    assert 0 <= bal["accrued_days"] <= 24


def test_max_days_per_application_rejects_over_limit(client, make_test_leave_type, employee_with_user):
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Max Per App", annual_entitlement=30,
                              requires_approval=False, max_days_per_application=2)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,  # 5 working days
    })
    assert res.status_code == 400
    assert "at most 2.0 day(s) per application" in res.json()["detail"]


def test_max_days_per_application_allows_at_limit(client, make_test_leave_type, employee_with_user):
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Max Per App Exact", annual_entitlement=30,
                              requires_approval=False, max_days_per_application=5)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
    })
    assert res.status_code == 201, res.text


def test_max_days_per_month_rejects_when_combined_exceeds(client, make_test_leave_type, employee_with_user):
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Max Per Month", annual_entitlement=30,
                              requires_approval=False, max_days_per_month=4)
    # First 3 working days of the fixed test week (Mon-Wed).
    first = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-01", "end_date": "2027-03-03",
    })
    assert first.status_code == 201, first.text
    # 2 more days (Thu-Fri) would bring March to 5, over the 4/month cap.
    second = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-04", "end_date": "2027-03-05",
    })
    assert second.status_code == 400
    assert "day/month limit" in second.json()["detail"]


def test_max_days_per_month_allows_up_to_limit(client, make_test_leave_type, employee_with_user):
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Max Per Month Exact", annual_entitlement=30,
                              requires_approval=False, max_days_per_month=5)
    first = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-01", "end_date": "2027-03-03",
    })
    assert first.status_code == 201, first.text
    second = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-04", "end_date": "2027-03-05",
    })
    assert second.status_code == 201, second.text  # totals exactly 5, at the limit


def test_max_days_per_month_splits_across_month_boundary(client, make_test_leave_type, employee_with_user):
    """A single application straddling two months is bucketed per-month —
    can't dodge the cap by starting near month-end. Uses a calendar-day
    type so exact day counts per month are trivial to hand-verify."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Max Per Month Boundary", annual_entitlement=30,
                              requires_approval=False, max_days_per_month=2, count_calendar_days=True)
    # 2027-01-30 to 2027-02-02: Jan gets 30,31 (2 days), Feb gets 1,2 (2 days) — each at the cap.
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-01-30", "end_date": "2027-02-02",
    })
    assert res.status_code == 201, res.text

    # A further 1 day in January alone would push January to 3, over the cap.
    res2 = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-01-15", "end_date": "2027-01-15",
    })
    assert res2.status_code == 400
    assert "January 2027" in res2.json()["detail"]


# ---------------------------------------------------------------------------
# Leave Applications: half-day (AM/PM)
# ---------------------------------------------------------------------------
def test_half_day_start_deducts_half_a_day(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START,
        "start_day_period": "AM",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["days_count"] == 0.5
    assert body["start_day_period"] == "AM"
    assert body["end_day_period"] is None


def test_half_day_start_and_end_on_multi_day_range(client, employee_with_user, make_test_leave_type):
    """5 working days, PM on the first day and AM on the last — 4.0 days
    total, independent half-day flags on each edge of the range."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_END,
        "start_day_period": "PM", "end_day_period": "AM",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["days_count"] == 4.0
    assert body["start_day_period"] == "PM"
    assert body["end_day_period"] == "AM"


def test_half_day_allowed_for_calendar_day_leave_type_by_default(client, employee_with_user, make_test_leave_type):
    """allow_half_day is the SOLE control over half-day eligibility — a
    calendar-day-counting type (e.g. Maternity/Paternity) is no longer
    auto-blocked; it defaults to allowed like any other type."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, annual_entitlement=60, count_calendar_days=True)
    assert lt["allow_half_day"]
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START,
        "start_day_period": "AM",
    })
    assert res.status_code == 201, res.text
    assert res.json()["days_count"] == 0.5


def test_half_day_rejected_for_calendar_day_leave_type_when_disallowed(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, annual_entitlement=60,
                              count_calendar_days=True, allow_half_day=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START,
        "start_day_period": "AM",
    })
    assert res.status_code == 400
    assert "does not allow half-day" in res.json()["detail"]


def test_create_leave_type_defaults_to_allow_half_day(client, make_test_leave_type):
    lt = make_test_leave_type()
    assert lt["allow_half_day"]


def test_update_leave_type_can_disable_half_day(client, hr_manager_auth, make_test_leave_type):
    lt = make_test_leave_type()
    res = client.put(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth, json={
        "name": lt["name"], "annual_entitlement": lt["annual_entitlement"], "allow_half_day": False,
    })
    assert res.status_code == 200, res.text
    assert not res.json()["allow_half_day"]


def test_half_day_rejected_when_leave_type_disallows_it(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False, allow_half_day=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START,
        "start_day_period": "AM",
    })
    assert res.status_code == 400
    assert "does not allow half-day" in res.json()["detail"]


def test_end_day_period_rejected_when_start_equals_end_date(client, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START,
        "end_day_period": "AM",
    })
    assert res.status_code == 422


def test_half_day_on_non_working_day_returns_400(client, employee_with_user, make_test_leave_type):
    """2027-03-06 is a Saturday — not a countable day for a default
    (working-days-only) leave type, so a half-day flag on it is rejected
    even though the overall range (Mon-Sat) has other valid working days."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": "2027-03-06",
        "end_day_period": "AM",
    })
    assert res.status_code == 400
    assert "not a working day" in res.json()["detail"]


def test_half_day_deduction_respected_by_monthly_cap(client, employee_with_user, make_test_leave_type):
    """Two separate single-day half-day applications (0.5 day each) in the
    same month should both fit under a 1.0/month cap (total 1.0, exactly at
    the limit). If the cap math mistakenly treated each half-day
    application as a full day, the second would be wrongly rejected."""
    emp, headers = employee_with_user
    lt = make_test_leave_type(name="ZZ Half Day Monthly Cap", annual_entitlement=30,
                              requires_approval=False, max_days_per_month=1.0)
    first = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-01", "end_date": "2027-03-01", "start_day_period": "AM",
    })
    assert first.status_code == 201, first.text
    assert first.json()["days_count"] == 0.5

    second = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-02", "end_date": "2027-03-02", "start_day_period": "PM",
    })
    assert second.status_code == 201, second.text
    assert second.json()["days_count"] == 0.5

    # A third application would push March to 1.5, over the 1.0 cap.
    third = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-03-03", "end_date": "2027-03-03", "start_day_period": "AM",
    })
    assert third.status_code == 400
    assert "day/month limit" in third.json()["detail"]


def test_full_half_day_apply_approve_cancel_balance_round_trip(
    client, hr_manager_auth, employee_with_user, make_test_leave_type
):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)

    apply_res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START, "start_day_period": "AM",
    })
    assert apply_res.status_code == 201, apply_res.text
    app_id = apply_res.json()["id"]
    assert apply_res.json()["days_count"] == 0.5

    approve_res = client.patch(
        f"/api/leave/applications/{app_id}/status", headers=hr_manager_auth, json={"status": "Approved"}
    )
    assert approve_res.status_code == 200

    balance_after_approve = client.get(
        "/api/leave/balances", headers=hr_manager_auth,
        params={"employee_id": emp["employee_id"], "year": 2027},
    ).json()
    bal_row = next(b for b in balance_after_approve if b["leave_type_id"] == lt["id"])
    assert bal_row["used_days"] == 0.5

    cancel_res = client.patch(
        f"/api/leave/applications/{app_id}/status", headers=headers, json={"status": "Cancelled"}
    )
    assert cancel_res.status_code == 200

    balance_after_cancel = client.get(
        "/api/leave/balances", headers=hr_manager_auth,
        params={"employee_id": emp["employee_id"], "year": 2027},
    ).json()
    bal_row = next(b for b in balance_after_cancel if b["leave_type_id"] == lt["id"])
    assert bal_row["used_days"] == 0.0


def test_leave_calendar_includes_half_day_periods(client, hr_manager_auth, employee_with_user, make_test_leave_type):
    emp, headers = employee_with_user
    lt = make_test_leave_type(requires_approval=False)
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": WORK_WEEK_START, "end_date": WORK_WEEK_START, "start_day_period": "AM",
    })
    assert res.status_code == 201, res.text

    cal = client.get("/api/leave/calendar", headers=hr_manager_auth, params={"year": 2027, "month": 3})
    assert cal.status_code == 200, cal.text
    entry = next(e for e in cal.json() if e["employee_id"] == emp["employee_id"] and e["start_date"] == WORK_WEEK_START)
    assert entry["start_day_period"] == "AM"
    assert entry["end_day_period"] is None


def test_concurrent_first_time_balance_lookups_do_not_500(client, make_test_leave_type, employee_with_user):
    """_get_or_create_leave_balance (core/leave_balance_ops.py) used to
    SELECT-then-INSERT with no protection against two concurrent callers
    both seeing no row and both attempting the INSERT — the loser hit
    leave_balances' UNIQUE(employee_id,leave_type_id,year) constraint as
    an unhandled 500. Reproduced live via two near-simultaneous
    GET /api/leave/balances calls for a brand-new employee (zero
    pre-existing rows, so every call takes the auto-create path). Firing
    several concurrent requests here raises the odds of a real interleave
    within the test run; the fix (INSERT ... ON CONFLICT DO NOTHING) makes
    every outcome safe regardless of whether they actually race this time."""
    emp, headers = employee_with_user
    # A fresh leave type + a year no other test in this file touches, so
    # this is guaranteed to be this employee's very first balance row for
    # it — the only circumstance where the race window exists at all.
    make_test_leave_type(name="ZZ Concurrent Balance Type", annual_entitlement=10)

    def _fetch():
        return client.get("/api/leave/balances", headers=headers, params={"year": 2029})

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: _fetch(), range(5)))

    statuses = [r.status_code for r in results]
    assert all(s == 200 for s in statuses), f"expected all 200, got {statuses}"
