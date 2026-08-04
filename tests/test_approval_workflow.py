"""Integration tests for core/approval_workflow.py and
routers/approval_workflow_settings.py — the generic engine wired into
Leave, Benefits Claims, Job Requisition, Timesheet, and L&D Enrollment
approvals. See README.md's "Approval workflow module" section.

Most of the wiring's regression coverage lives in each module's own test
file (test_leave.py, test_timesheets.py, test_recruitment.py, test_ld.py)
— those already exercise "hr_manager approves" against employees with no
reports_to set, which the auto-skip-empty-steps rule here should make
behave exactly as before. This file instead covers what those files
can't: the actual direct-manager-must-approve-first enforcement (which
needs a real reporting-chain fixture), and the workflow-settings CRUD.
"""
import os

import pytest


@pytest.fixture
def manager_with_report(client, hr_manager_auth, make_test_employee, test_institution):
    """A real employee (the manager) with a linked login, plus a second
    employee whose reports_to points at the manager — the minimal
    reporting-chain fixture needed to exercise direct_manager resolution.
    Returns (report_emp, manager_headers)."""
    mgr_emp = make_test_employee(full_name="ZZ Test Manager")
    report_emp = make_test_employee(full_name="ZZ Test Report", reports_to=mgr_emp["employee_id"])

    username = f"zzawmgr_{mgr_emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ AW Manager", "password": password,
        "role": "manager", "employee_id": mgr_emp["employee_id"],
    })
    assert res.status_code == 201, f"failed to create manager user: {res.text}"
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    mgr_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    yield report_emp, mgr_headers

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def _unique_name(prefix="ZZ Test Workflow"):
    return f"{prefix} {os.urandom(4).hex()}"


# ---------------------------------------------------------------------------
# Engine behavior (via the Leave module, the simplest requester-linked one)
# ---------------------------------------------------------------------------
def test_hr_cannot_skip_direct_manager_step(client, hr_manager_auth, manager_with_report, make_test_leave_type):
    """With a real reporting chain in place, HR must not be able to approve
    the direct_manager step directly — only the actual manager can."""
    report_emp, mgr_headers = manager_with_report
    lt = make_test_leave_type(requires_approval=True)
    start = "2027-04-05"  # Monday
    app = client.post("/api/leave/applications", headers=hr_manager_auth, json={
        "employee_id": report_emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": start, "end_date": start,
    }).json()
    assert app["status"] == "Pending Approval"
    assert app["approval_step"] == 1

    denied = client.patch(f"/api/leave/applications/{app['id']}/status", headers=hr_manager_auth,
                           json={"status": "Approved"})
    assert denied.status_code == 403, denied.text

    advanced = client.patch(f"/api/leave/applications/{app['id']}/status", headers=mgr_headers,
                             json={"status": "Approved"})
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["status"] == "Pending Approval"
    assert advanced.json()["approval_step"] == 2

    final = client.patch(f"/api/leave/applications/{app['id']}/status", headers=hr_manager_auth,
                          json={"status": "Approved"})
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "Approved"
    assert final.json()["approval_step"] is None


def test_manager_cannot_approve_unrelated_employees_leave(client, hr_manager_auth, manager_with_report,
                                                            make_test_employee, make_test_leave_type):
    """The manager from manager_with_report is NOT this other employee's
    direct manager — they must not be able to approve it."""
    _, mgr_headers = manager_with_report
    other_emp = make_test_employee(full_name="ZZ Unrelated Employee")
    lt = make_test_leave_type(requires_approval=True)
    start = "2027-04-12"
    app = client.post("/api/leave/applications", headers=hr_manager_auth, json={
        "employee_id": other_emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": start, "end_date": start,
    }).json()

    denied = client.patch(f"/api/leave/applications/{app['id']}/status", headers=mgr_headers,
                           json={"status": "Approved"})
    assert denied.status_code == 403, denied.text


def test_employee_with_no_manager_auto_skips_to_hr(client, hr_manager_auth, make_test_employee, make_test_leave_type):
    """No reports_to on file -> the direct_manager step's pool is empty and
    is skipped automatically, so HR can approve step 1 directly. This is
    the behavior every other module's existing test suite already relies
    on implicitly (make_test_employee doesn't set reports_to)."""
    emp = make_test_employee(full_name="ZZ No Manager Employee")
    lt = make_test_leave_type(requires_approval=True)
    start = "2027-04-19"
    app = client.post("/api/leave/applications", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": start, "end_date": start,
    }).json()
    assert app["approval_step"] == 2  # step 1 (direct_manager) auto-skipped

    res = client.patch(f"/api/leave/applications/{app['id']}/status", headers=hr_manager_auth,
                        json={"status": "Approved"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Approved"


# ---------------------------------------------------------------------------
# Workflow settings CRUD
# ---------------------------------------------------------------------------
def test_create_workflow_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/approval-workflows", headers=headers, json={"module": "leave", "name": _unique_name()})
    assert res.status_code == 403


def test_create_workflow_invalid_module_returns_422(client, hr_manager_auth):
    res = client.post("/api/approval-workflows", headers=hr_manager_auth, json={"module": "bogus", "name": _unique_name()})
    assert res.status_code == 422


def test_create_workflow_success_and_appears_in_list(client, hr_manager_auth):
    # Deletes itself at the end — a leftover workflow would otherwise become
    # this shared session-scoped institution's *default* timesheet workflow
    # (first-created-for-the-module wins), silently auto-approving every
    # other test's timesheet submissions for the rest of the session.
    name = _unique_name()
    res = client.post("/api/approval-workflows", headers=hr_manager_auth, json={"module": "timesheet", "name": name})
    assert res.status_code == 201, res.text
    wf = res.json()
    assert wf["steps"] == []

    listing = client.get("/api/approval-workflows", headers=hr_manager_auth, params={"module": "timesheet"})
    assert any(w["id"] == wf["id"] for w in listing.json())

    client.delete(f"/api/approval-workflows/{wf['id']}", headers=hr_manager_auth)


def test_add_step_specific_employee_requires_valid_employee(client, hr_manager_auth):
    wf = client.post("/api/approval-workflows", headers=hr_manager_auth,
                      json={"module": "requisition", "name": _unique_name()}).json()
    res = client.post(f"/api/approval-workflows/{wf['id']}/steps", headers=hr_manager_auth,
                       json={"approver_type": "specific_employee", "specific_employee_id": None})
    assert res.status_code == 400

    res2 = client.post(f"/api/approval-workflows/{wf['id']}/steps", headers=hr_manager_auth,
                        json={"approver_type": "specific_employee", "specific_employee_id": "NOPE_NOT_REAL"})
    assert res2.status_code == 404

    client.delete(f"/api/approval-workflows/{wf['id']}", headers=hr_manager_auth)


def test_add_step_success_and_move_and_delete(client, hr_manager_auth):
    wf = client.post("/api/approval-workflows", headers=hr_manager_auth,
                      json={"module": "claims", "name": _unique_name()}).json()
    s1 = client.post(f"/api/approval-workflows/{wf['id']}/steps", headers=hr_manager_auth,
                      json={"approver_type": "direct_manager"}).json()["steps"][0]
    s2 = client.post(f"/api/approval-workflows/{wf['id']}/steps", headers=hr_manager_auth,
                      json={"approver_type": "hr_manager"}).json()["steps"][-1]
    assert s1["step_order"] == 1 and s2["step_order"] == 2

    moved = client.post(f"/api/approval-workflows/{wf['id']}/steps/{s2['id']}/move", headers=hr_manager_auth,
                         json={"direction": "up"}).json()
    orders = {s["id"]: s["step_order"] for s in moved["steps"]}
    assert orders[s2["id"]] == 1 and orders[s1["id"]] == 2

    deleted = client.delete(f"/api/approval-workflows/{wf['id']}/steps/{s1['id']}", headers=hr_manager_auth)
    assert deleted.status_code == 204

    client.delete(f"/api/approval-workflows/{wf['id']}", headers=hr_manager_auth)


def test_workflow_step_cap_at_four(client, hr_manager_auth):
    wf = client.post("/api/approval-workflows", headers=hr_manager_auth,
                      json={"module": "ld_enrollment", "name": _unique_name()}).json()
    for _ in range(4):
        res = client.post(f"/api/approval-workflows/{wf['id']}/steps", headers=hr_manager_auth,
                           json={"approver_type": "hr_manager"})
        assert res.status_code == 201
    over_cap = client.post(f"/api/approval-workflows/{wf['id']}/steps", headers=hr_manager_auth,
                            json={"approver_type": "hr_manager"})
    assert over_cap.status_code == 400

    client.delete(f"/api/approval-workflows/{wf['id']}", headers=hr_manager_auth)


def test_delete_workflow_promotes_another_default(client, hr_manager_auth):
    # test_institution is session-scoped (shared across this whole file), so
    # another test earlier in the session may have already lazily created a
    # default "leave" workflow via get_or_create_default_workflow — don't
    # assume wf_a is the module's first-ever workflow, just that making it
    # the explicit default and then deleting it promotes something else.
    name_a = _unique_name("ZZ Workflow A")
    name_b = _unique_name("ZZ Workflow B")
    wf_a = client.post("/api/approval-workflows", headers=hr_manager_auth,
                        json={"module": "leave", "name": name_a}).json()
    client.put(f"/api/approval-workflows/{wf_a['id']}", headers=hr_manager_auth,
               json={"name": name_a, "is_default": True})
    wf_b = client.post("/api/approval-workflows", headers=hr_manager_auth,
                        json={"module": "leave", "name": name_b}).json()
    assert wf_b["is_default"] == 0  # wf_a is still the default

    client.delete(f"/api/approval-workflows/{wf_a['id']}", headers=hr_manager_auth)
    listing = client.get("/api/approval-workflows", headers=hr_manager_auth, params={"module": "leave"}).json()
    # Some other active workflow got promoted to default (could be wf_b, or a
    # pre-existing lazily-created default from an earlier test in this shared
    # session-scoped institution — the promotion tie-break isn't wf_b-specific).
    assert not any(w["id"] == wf_a["id"] for w in listing)
    assert any(w["is_default"] == 1 for w in listing)

    client.delete(f"/api/approval-workflows/{wf_b['id']}", headers=hr_manager_auth)
