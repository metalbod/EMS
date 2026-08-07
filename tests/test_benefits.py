"""Covers the auto-enroll-all bulk action on routers/benefits.py, the one
piece of the Benefits module with test coverage so far — see the plan/
enrollment endpoints themselves for everything else, which predates a
dedicated test file for this module.
"""
import os


def _unique_name(prefix="ZZ Test Plan"):
    return f"{prefix} {os.urandom(4).hex()}"


def _make_active_plan(client, hr_manager_auth, **overrides):
    body = {
        "plan_name": _unique_name(),
        "plan_category": "Medical",
        "contribution_type": "Fixed Premium",
        "employee_cost": 50,
        "employer_cost": 150,
        **overrides,
    }
    plan = client.post("/api/benefits/plans", headers=hr_manager_auth, json=body).json()
    client.put(f"/api/benefits/plans/{plan['id']}", headers=hr_manager_auth, json={"status": "Active"})
    return plan


def test_list_claims_manager_sees_subordinates_not_403(client, hr_manager_auth, make_test_employee, employee_with_login):
    """A manager eligible to approve a subordinate's claim via the
    approval-workflow engine's direct_manager/skip_level_manager step
    types must be able to see it in the claims list — this used to
    blanket-403 anyone who wasn't HR/Payroll/Compensation, so a manager's
    Dashboard To-Do item ("N benefit claims awaiting your approval") led
    to a page they couldn't view at all."""
    mgr_emp, mgr_headers = employee_with_login(full_name="ZZ Claims Manager")
    report_emp = make_test_employee(full_name="ZZ Claims Report", reports_to=mgr_emp["employee_id"])

    # Give the manager account a 'manager' role (employee_with_login
    # defaults to 'employee') so list_claims' manager-scoping branch applies.
    users = client.get("/api/users", headers=hr_manager_auth).json()
    mgr_user = next(u for u in users if u["employee_id"] == mgr_emp["employee_id"])
    client.put(f"/api/users/{mgr_user['id']}", headers=hr_manager_auth, json={
        "full_name": mgr_user["full_name"], "role": "manager", "employee_id": mgr_emp["employee_id"], "is_active": True,
    })

    plan = _make_active_plan(client, hr_manager_auth)
    claim = client.post(f"/api/benefits/employees/{report_emp['employee_id']}/claims", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 100,
    }).json()

    res = client.get("/api/benefits/claims", headers=mgr_headers)
    assert res.status_code == 200, res.text
    assert any(c["id"] == claim["id"] for c in res.json())

    # An employee role with no manager/HR access still gets 403.
    other_emp, other_headers = employee_with_login(full_name="ZZ Claims Unrelated Employee")
    res2 = client.get("/api/benefits/claims", headers=other_headers)
    assert res2.status_code == 403


def test_auto_enroll_all_requires_manage_role(client, make_test_user, test_institution, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=headers)
    assert res.status_code == 403


def test_auto_enroll_all_rejects_non_active_plan(client, hr_manager_auth):
    body = {
        "plan_name": _unique_name(),
        "plan_category": "Medical",
        "contribution_type": "Fixed Premium",
    }
    plan = client.post("/api/benefits/plans", headers=hr_manager_auth, json=body).json()
    assert plan["status"] == "Draft"
    res = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=hr_manager_auth)
    assert res.status_code == 404


def test_auto_enroll_all_enrolls_active_employees(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Auto Enroll Employee")
    plan = _make_active_plan(client, hr_manager_auth)

    res = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json()["enrolled_count"] >= 1

    enrollments = client.get(f"/api/benefits/employees/{emp['employee_id']}/enrollments", headers=hr_manager_auth).json()
    match = next((e for e in enrollments if e["benefit_plan_id"] == plan["id"]), None)
    assert match is not None
    assert match["status"] == "Enrolled"

    # Re-running is idempotent — the employee's row is refreshed, not duplicated.
    res2 = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=hr_manager_auth)
    assert res2.status_code == 200
    enrollments2 = client.get(f"/api/benefits/employees/{emp['employee_id']}/enrollments", headers=hr_manager_auth).json()
    assert sum(1 for e in enrollments2 if e["benefit_plan_id"] == plan["id"]) == 1
