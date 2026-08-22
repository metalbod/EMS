"""Integration tests for core/resignation.py + routers/resignation.py:
self-service and HR-on-behalf submission, the 'resignation' approval
workflow module (core/approval_workflow.py), and the auto-started
Offboarding checklist on final approval. See test_approval_workflow.py
for the generic engine's own coverage (direct-manager-must-approve-first
enforcement etc.) — this file only covers what's specific to Resignation.

Every test here uses employee_with_login with no reports_to set, so the
default workflow's direct_manager step auto-skips (empty pool) and the
request lands straight on the hr_manager step — same shortcut
test_overtime.py's own approval test uses, avoiding the extra
reporting-chain fixture for cases that don't need it.
"""
from conftest import _valid_employee_payload


def test_resignations_require_auth(client):
    res = client.get("/api/resignations")
    assert res.status_code in (401, 403)


def test_employee_can_self_file_resignation(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Resign Self")
    res = client.post("/api/resignations", headers=headers, json={
        "reason": "Pursuing another opportunity",
        "effective_date": "2027-06-01", "last_working_day": "2027-06-30",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["employee_id"] == emp["employee_id"]
    assert body["status"] == "Pending"
    assert body["submitted_by"] != "hr_manager"  # submitted as the employee, not HR

    client.patch(f"/api/resignations/{body['id']}", headers=hr_manager_auth, json={"status": "Rejected"})


def test_hr_can_file_resignation_on_employees_behalf(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Resign OnBehalf")
    res = client.post("/api/resignations", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "reason": "Verbal resignation, documented by HR",
        "effective_date": "2027-06-01", "last_working_day": "2027-06-15",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["employee_id"] == emp["employee_id"]

    client.patch(f"/api/resignations/{body['id']}", headers=hr_manager_auth, json={"status": "Rejected"})


def test_plain_employee_cannot_file_on_someone_elses_behalf(client, employee_with_login, make_test_employee):
    _, headers = employee_with_login(full_name="ZZ Resign NotHR")
    other = make_test_employee(full_name="ZZ Resign Victim")
    res = client.post("/api/resignations", headers=headers, json={
        "employee_id": other["employee_id"], "reason": "Not my call",
        "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    assert res.status_code == 403, res.text


def test_last_working_day_before_effective_date_rejected(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Resign BadDates")
    res = client.post("/api/resignations", headers=headers, json={
        "reason": "Bad dates", "effective_date": "2027-06-15", "last_working_day": "2027-06-01",
    })
    assert res.status_code == 400, res.text


def test_duplicate_pending_request_rejected(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Resign Dup")
    first = client.post("/api/resignations", headers=headers, json={
        "reason": "First attempt", "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    assert first.status_code == 201, first.text
    second = client.post("/api/resignations", headers=headers, json={
        "reason": "Second attempt", "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    assert second.status_code == 400, second.text

    client.patch(f"/api/resignations/{first.json()['id']}", headers=hr_manager_auth, json={"status": "Rejected"})


def test_full_approval_stamps_employee_and_creates_offboarding_checklist(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Resign Approved")
    submit = client.post("/api/resignations", headers=headers, json={
        "reason": "Moving on", "effective_date": "2027-07-01", "last_working_day": "2027-07-31",
    })
    assert submit.status_code == 201, submit.text
    req_id = submit.json()["id"]

    # No manager on file -> direct_manager step auto-skips -> lands on
    # hr_manager directly, same shortcut test_overtime.py's approval test uses.
    approved = client.patch(f"/api/resignations/{req_id}", headers=hr_manager_auth, json={"status": "Approved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "Approved"
    ob_checklist_id = approved.json()["ob_checklist_id"]
    assert ob_checklist_id is not None

    emp_row = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth).json()
    assert emp_row["resign_date"] == "2027-07-01"
    assert emp_row["last_working_day"] == "2027-07-31"
    assert emp_row["status"] == "Active"  # never auto-deactivated — HR does that manually

    checklist = client.get(f"/api/ob/checklists/{ob_checklist_id}", headers=hr_manager_auth).json()
    assert checklist["type"] == "offboarding"
    assert checklist["employee_id"] == emp["employee_id"]

    client.delete(f"/api/ob/checklists/{ob_checklist_id}", headers=hr_manager_auth)


def test_rejection_leaves_employee_untouched_and_creates_no_checklist(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Resign Rejected")
    submit = client.post("/api/resignations", headers=headers, json={
        "reason": "Changed my mind later", "effective_date": "2027-08-01", "last_working_day": "2027-08-15",
    })
    req_id = submit.json()["id"]

    rejected = client.patch(f"/api/resignations/{req_id}", headers=hr_manager_auth, json={"status": "Rejected"})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "Rejected"
    assert rejected.json()["ob_checklist_id"] is None

    emp_row = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth).json()
    assert emp_row["resign_date"] is None
    assert emp_row["last_working_day"] is None


def test_employee_can_withdraw_while_pending(client, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ Resign Withdraw")
    submit = client.post("/api/resignations", headers=headers, json={
        "reason": "Reconsidering", "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    req_id = submit.json()["id"]

    withdrawn = client.patch(f"/api/resignations/{req_id}", headers=headers, json={"status": "Withdrawn"})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "Withdrawn"

    # A withdrawn request no longer blocks a fresh one for the same employee.
    resubmit = client.post("/api/resignations", headers=headers, json={
        "reason": "Actually leaving now", "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    assert resubmit.status_code == 201, resubmit.text


def test_role_scoped_visibility(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Resign Visible")
    other_emp, other_headers = employee_with_login(full_name="ZZ Resign NotVisible")
    submit = client.post("/api/resignations", headers=headers, json={
        "reason": "Visibility check", "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    req_id = submit.json()["id"]

    own = client.get("/api/resignations", headers=headers).json()
    assert any(r["id"] == req_id for r in own)

    other = client.get("/api/resignations", headers=other_headers).json()
    assert not any(r["id"] == req_id for r in other)

    hr_view = client.get("/api/resignations", headers=hr_manager_auth).json()
    assert any(r["id"] == req_id for r in hr_view)

    client.patch(f"/api/resignations/{req_id}", headers=hr_manager_auth, json={"status": "Rejected"})


def test_dashboard_todo_surfaces_pending_resignation_for_hr(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Resign Todo")
    submit = client.post("/api/resignations", headers=headers, json={
        "reason": "Todo check", "effective_date": "2027-06-01", "last_working_day": "2027-06-01",
    })
    req_id = submit.json()["id"]

    todos = client.get("/api/todos", headers=hr_manager_auth).json()
    assert any(t["key"] == "resignation-approvals" for t in todos)

    client.patch(f"/api/resignations/{req_id}", headers=hr_manager_auth, json={"status": "Rejected"})
