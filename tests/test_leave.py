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
