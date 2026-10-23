"""Integration tests for routers/approvals.py — the Approvals inbox's list and per-request context."""
import os


def _employee_login(client, hr_headers, institution_code, emp, label):
    username = f"zzappr_{label}_{os.urandom(3).hex()}"
    res = client.post("/api/users", headers=hr_headers, json={
        "username": username, "full_name": f"ZZ Approvals {label}", "password": "ZzPytest@123",
        "role": "employee", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, res.text
    login = client.post("/api/auth/login", json={"username": username, "password": "ZzPytest@123", "institution_code": institution_code})
    assert login.status_code == 200, login.text
    return res.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def _pending_leave(client, hr_headers, test_institution, make_test_employee, make_test_leave_type, start="2027-05-10", end="2027-05-11", **emp_overrides):
    emp = make_test_employee(**emp_overrides)
    user_id, emp_headers = _employee_login(client, hr_headers, test_institution["code"], emp, "req")
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    app = client.post("/api/leave/applications", headers=emp_headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"], "start_date": start, "end_date": end, "reason": "Family event",
    })
    assert app.status_code == 201, app.text
    assert app.json()["status"] == "Pending Approval"
    return emp, lt, app.json()["id"], user_id, emp_headers


def test_approvals_require_auth(client):
    assert client.get("/api/approvals").status_code in (401, 403)
    assert client.get("/api/approvals/leave/1/context").status_code in (401, 403)


def test_list_shows_only_approvals_with_counts_and_project_flags(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    emp, lt, app_id, user_id, _ = _pending_leave(client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type)
    body = client.get("/api/approvals", headers=hr_manager_auth).json()
    assert set(body) == {"items", "counts", "total"}
    assert body["total"] == len(body["items"])
    assert all(t["kind"] == "approval" for t in body["items"])
    row = next(t for t in body["items"] if t["key"] == f"leave-approval-{app_id}")
    assert row["module"] == "leave" and row["ref_id"] == app_id
    assert row["project_row"] is False and row["project_id"] is None
    assert body["counts"]["leave"] == sum(1 for t in body["items"] if t["module"] == "leave") >= 1
    assert set(body["counts"]) >= {"leave", "claims", "requisition", "timesheet", "ld_enrollment", "overtime", "resignation", "pip"}
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_leave_context_has_facts_steps_and_balance(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    emp, lt, app_id, user_id, _ = _pending_leave(client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type)
    res = client.get(f"/api/approvals/leave/{app_id}/context", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    ctx = res.json()
    assert ctx["module"] == "leave" and ctx["type_label"] == "Leave Application"
    assert ctx["employee"]["employee_id"] == emp["employee_id"]
    facts = {f["label"]: f["value"] for f in ctx["facts"]}
    assert facts["Leave type"] == lt["name"]
    assert facts["Dates"] == "2027-05-10 to 2027-05-11"
    assert facts["Reason"] == "Family event"
    assert any(label.endswith("balance") for label in facts)
    assert ctx["steps"] and any(s["state"] == "current" for s in ctx["steps"])
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_context_is_closed_to_anyone_who_cannot_decide_the_request(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    emp, lt, app_id, user_id, emp_headers = _pending_leave(client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type)
    # the requester can't read their own request through the inbox, nor can an unrelated employee
    assert client.get(f"/api/approvals/leave/{app_id}/context", headers=emp_headers).status_code == 404
    other = make_test_employee()
    other_id, other_headers = _employee_login(client, hr_manager_auth, test_institution["code"], other, "other")
    assert client.get(f"/api/approvals/leave/{app_id}/context", headers=other_headers).status_code == 404
    client.delete(f"/api/users/{other_id}", headers=hr_manager_auth)
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_context_rejects_unknown_type_missing_id_and_wrong_row_kind(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    emp, lt, app_id, user_id, _ = _pending_leave(client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type)
    assert client.get(f"/api/approvals/payroll/{app_id}/context", headers=hr_manager_auth).status_code == 404
    assert client.get("/api/approvals/leave/2147483000/context", headers=hr_manager_auth).status_code == 404
    # a whole-record leave row asked for as a "project row" is not that request
    assert client.get(f"/api/approvals/leave/{app_id}/context?project_row=true", headers=hr_manager_auth).status_code == 404
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_leave_context_warns_when_a_department_colleague_is_already_away(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    dept = f"ZZApprDept{os.urandom(2).hex()}"
    emp, lt, app_id, user_id, _ = _pending_leave(client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type,
                                                 start="2027-06-14", end="2027-06-15", department=dept)
    mate = make_test_employee(department=dept)
    mate_user, mate_headers = _employee_login(client, hr_manager_auth, test_institution["code"], mate, "mate")
    mate_app = client.post("/api/leave/applications", headers=mate_headers, json={
        "employee_id": mate["employee_id"], "leave_type_id": lt["id"], "start_date": "2027-06-15", "end_date": "2027-06-15",
    })
    assert mate_app.status_code == 201, mate_app.text
    approved = client.patch(f"/api/leave/applications/{mate_app.json()['id']}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert approved.status_code == 200, approved.text
    ctx = client.get(f"/api/approvals/leave/{app_id}/context", headers=hr_manager_auth).json()
    assert any("already away" in w for w in ctx["warnings"]), ctx
    client.delete(f"/api/users/{mate_user}", headers=hr_manager_auth)
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_timesheet_split_row_is_flagged_and_its_context_covers_only_that_projects_hours(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_project, make_test_project_task
):
    emp = make_test_employee()
    user_id, headers = _employee_login(client, hr_manager_auth, test_institution["code"], emp, "ts")
    p1 = make_test_project(name="ZZ Appr Project A", is_open_to_all=True)
    t1 = make_test_project_task(p1["id"])
    p2 = make_test_project(name="ZZ Appr Project B", is_open_to_all=True)
    t2 = make_test_project_task(p2["id"])
    ts = client.post("/api/timesheets", headers=headers, json={
        "employee_id": emp["employee_id"], "period_start": "2027-07-05", "period_end": "2027-07-11"}).json()
    for p, t, h in ((p1, t1, 4), (p2, t2, 2)):
        assert client.post(f"/api/timesheets/{ts['id']}/entries", headers=headers, json={
            "project_id": p["id"], "task_id": t["id"], "date": "2027-07-06", "hours": h}).status_code == 201
    assert client.patch(f"/api/timesheets/{ts['id']}/status", headers=headers, json={"status": "Submitted"}).status_code == 200

    rows = [t for t in client.get("/api/approvals", headers=hr_manager_auth).json()["items"]
            if t["module"] == "timesheet" and t["focus_id"] == ts["id"]]
    assert len(rows) == 2 and all(r["project_row"] for r in rows)
    by_project = {r["project_id"]: r for r in rows}
    assert set(by_project) == {p1["id"], p2["id"]}
    row = by_project[p1["id"]]
    ctx = client.get(f"/api/approvals/timesheet/{row['ref_id']}/context?project_row=true", headers=hr_manager_auth)
    assert ctx.status_code == 200, ctx.text
    assert {f["label"]: f["value"] for f in ctx.json()["facts"]}["Hours"] == "4"
    # asked for as a whole-timesheet row, that id isn't one
    assert client.get(f"/api/approvals/timesheet/{row['ref_id']}/context", headers=hr_manager_auth).status_code == 404
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)
