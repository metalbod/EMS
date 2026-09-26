"""Integration tests for the generic entity_audit_log trail (core/audit.py's
write_entity_audit, GET /api/entity-audit-log) — Phase 1: users, roles &
permission overrides, approval workflows, payroll, institution/secret
settings — plus the read-only union of the older per-module trails."""
import os

from test_payroll import _period


def _log(client, headers, **params):
    res = client.get("/api/entity-audit-log", headers=headers, params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _actions(rows):
    return [r["action"] for r in rows]


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_activity_log_requires_auth(client):
    assert client.get("/api/entity-audit-log").status_code in (401, 403)


def test_activity_log_forbidden_for_non_hr_roles(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    assert client.get("/api/entity-audit-log", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def test_user_lifecycle_is_audited_without_leaking_the_password(client, hr_manager_auth):
    username = f"zzaudit_user_{os.urandom(4).hex()}"
    created = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Audit User", "password": "ZzSecretPw@123", "role": "employee",
    })
    assert created.status_code == 201, created.text
    uid = created.json()["id"]

    upd = client.put(f"/api/users/{uid}", headers=hr_manager_auth, json={
        "full_name": "ZZ Audit User Renamed", "password": "ZzAnotherSecret@456", "role": "employee", "is_active": True,
    })
    assert upd.status_code == 200, upd.text
    assert client.delete(f"/api/users/{uid}", headers=hr_manager_auth).status_code == 204

    rows = _log(client, hr_manager_auth, entity_type="user", entity_id=str(uid))
    assert set(_actions(rows)) >= {"Created", "Updated", "Deleted"}
    updated = next(r for r in rows if r["action"] == "Updated")
    assert any(c["field"] == "full_name" and c["new"] == "ZZ Audit User Renamed" for c in updated["changes"])
    assert "password" in updated["detail"].lower()
    blob = repr(rows)
    assert "ZzSecretPw@123" not in blob and "ZzAnotherSecret@456" not in blob
    assert all(r["actor_username"] for r in rows)


def test_user_audit_row_not_visible_to_another_institution(client, hr_manager_auth, superadmin_headers):
    username = f"zzaudit_iso_{os.urandom(4).hex()}"
    created = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Iso", "password": "ZzPytest@123", "role": "employee",
    }).json()
    try:
        payload = {
            "name": "ZZ Audit Iso Institution", "code": f"ZZAI{os.urandom(4).hex()}".upper(),
            "contact_email": "zzauditiso@example.com", "admin_username": f"zzaiadmin_{os.urandom(4).hex()}",
            "admin_full_name": "ZZ AI Admin", "admin_password": "ZzPytest@123",
        }
        inst = client.post("/api/institutions", headers=superadmin_headers, json=payload)
        assert inst.status_code == 201, inst.text
        login = client.post("/api/auth/login", json={
            "username": payload["admin_username"], "password": payload["admin_password"],
            "institution_code": inst.json()["code"],
        })
        other = {"Authorization": f"Bearer {login.json()['access_token']}"}
        rows = _log(client, other, entity_type="user", entity_id=str(created["id"]))
        assert rows == []
    finally:
        client.delete(f"/api/users/{created['id']}", headers=hr_manager_auth)


# ---------------------------------------------------------------------------
# Roles & permission overrides
# ---------------------------------------------------------------------------
def test_custom_role_and_permission_override_are_audited(client, hr_manager_auth):
    name = f"ZZ Audit Role {os.urandom(3).hex()}"
    role = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name})
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]

    ov = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                    json={"action_key": "employees.create_employee", "role": "manager", "access_value": "allow"})
    assert ov.status_code == 200, ov.text
    client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                  params={"action_key": "employees.create_employee", "role": "manager"})
    assert client.delete(f"/api/roles/{role_id}", headers=hr_manager_auth).status_code == 204

    role_rows = _log(client, hr_manager_auth, entity_type="role", entity_id=str(role_id))
    assert set(_actions(role_rows)) >= {"Created", "Deleted"}
    ov_rows = _log(client, hr_manager_auth, entity_type="permission_override",
                   entity_id="employees.create_employee:manager")
    assert "Override set" in _actions(ov_rows) and "Override reset" in _actions(ov_rows)
    setrow = next(r for r in ov_rows if r["action"] == "Override set")
    assert setrow["changes"][0]["new"] == "allow"


# ---------------------------------------------------------------------------
# Approval workflows
# ---------------------------------------------------------------------------
def test_approval_workflow_and_step_changes_are_audited(client, hr_manager_auth):
    wf = client.post("/api/approval-workflows", headers=hr_manager_auth, json={
        "module": "requisition", "name": f"ZZ Audit WF {os.urandom(3).hex()}", "mode": "sequential",
    }).json()
    wid = wf["id"]
    try:
        s1 = client.post(f"/api/approval-workflows/{wid}/steps", headers=hr_manager_auth, json={"approver_type": "hr_manager"})
        assert s1.status_code == 201, s1.text
        s2 = client.post(f"/api/approval-workflows/{wid}/steps", headers=hr_manager_auth, json={"approver_type": "hr_manager"})
        step_ids = [s["id"] for s in s2.json()["steps"]]
        client.put(f"/api/approval-workflows/{wid}", headers=hr_manager_auth,
                   json={"name": wf["name"] + " v2", "is_default": False, "mode": "flat"})
        client.post(f"/api/approval-workflows/{wid}/steps/{step_ids[1]}/move", headers=hr_manager_auth, json={"direction": "up"})
        client.delete(f"/api/approval-workflows/{wid}/steps/{step_ids[0]}", headers=hr_manager_auth)
    finally:
        client.delete(f"/api/approval-workflows/{wid}", headers=hr_manager_auth)

    rows = _log(client, hr_manager_auth, entity_type="approval_workflow", entity_id=str(wid))
    assert set(_actions(rows)) >= {"Created", "Step added", "Updated", "Step moved", "Step deleted", "Deleted"}
    upd = next(r for r in rows if r["action"] == "Updated")
    assert any(c["field"] == "mode" and c["new"] == "flat" for c in upd["changes"])


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------
def test_payroll_run_payslip_adjust_finalize_are_audited(client, hr_manager_auth, payroll_manager_auth, make_test_employee):
    emp = make_test_employee(salary_type="Monthly", basic_salary=4000.0, date_of_birth="1988-01-01")
    start, end = _period()
    run_id = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                         json={"period_start": start, "period_end": end}).json()["run_id"]
    detail = client.get(f"/api/payroll/runs/{run_id}", headers=payroll_manager_auth).json()
    slip = next(p for p in detail["payslips"] if p["employee_id"] == emp["employee_id"])
    assert client.put(f"/api/payroll/payslips/{slip['id']}", headers=payroll_manager_auth,
                      json={"basic_salary": 4500.0}).status_code == 200
    assert client.patch(f"/api/payroll/runs/{run_id}/finalize", headers=payroll_manager_auth).status_code == 200

    rows = _log(client, hr_manager_auth, entity_type="payroll_run", entity_id=str(run_id))
    assert set(_actions(rows)) >= {"Created", "Payslip adjusted", "Finalized"}
    adj = next(r for r in rows if r["action"] == "Payslip adjusted")
    assert emp["employee_id"] in adj["detail"]
    bs = next(c for c in adj["changes"] if c["field"] == "basic_salary")
    assert bs["old"] == "4000.0" and bs["new"] == "4500.0"
    assert all(r["actor_role"] == "payroll_manager" for r in rows if r["action"] in ("Created", "Finalized"))


def test_payroll_run_delete_is_audited(client, hr_manager_auth, payroll_manager_auth):
    start, end = _period()
    run_id = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                         json={"period_start": start, "period_end": end}).json()["run_id"]
    assert client.delete(f"/api/payroll/runs/{run_id}", headers=payroll_manager_auth).status_code == 204
    rows = _log(client, hr_manager_auth, entity_type="payroll_run", entity_id=str(run_id))
    assert set(_actions(rows)) >= {"Created", "Deleted"}


# ---------------------------------------------------------------------------
# Institution & secret settings
# ---------------------------------------------------------------------------
def test_institution_lifecycle_is_audited(client, superadmin_token):
    payload = {
        "name": "ZZ Audit Inst", "code": f"ZZAU{os.urandom(4).hex()}".upper(), "contact_email": "zzau@example.com",
        "admin_username": f"zzauadmin_{os.urandom(4).hex()}", "admin_full_name": "ZZ AU Admin",
        "admin_password": "ZzPytest@123",
    }
    base = {"Authorization": f"Bearer {superadmin_token}"}
    inst = client.post("/api/institutions", headers=base, json=payload).json()
    iid = inst["id"]
    scoped = {**base, "X-Institution-Id": str(iid)}
    client.put(f"/api/institutions/{iid}", headers=base, json={
        "name": "ZZ Audit Inst Renamed", "contact_name": None, "contact_email": "zzau@example.com",
        "phone": None, "address": None, "plan": inst["plan"], "max_employees": inst["max_employees"], "logo_url": None,
    })
    client.patch(f"/api/institutions/{iid}/status", headers=base, json={"status": "Suspended"})
    client.patch(f"/api/institutions/{iid}/status", headers=base, json={"status": "Active"})

    rows = _log(client, scoped, entity_type="institution", entity_id=str(iid))
    assert set(_actions(rows)) >= {"Created", "Updated", "Suspended", "Activated"}
    assert "ZzPytest@123" not in repr(rows)


def test_clearing_email_and_ai_key_settings_is_audited(client, hr_manager_auth):
    assert client.delete("/api/notifications/email-settings", headers=hr_manager_auth).status_code == 200
    assert client.delete("/api/assistant/settings", headers=hr_manager_auth).status_code == 200
    email_rows = _log(client, hr_manager_auth, entity_type="email_settings")
    key_rows = _log(client, hr_manager_auth, entity_type="ai_assistant_key")
    assert "SMTP settings cleared" in _actions(email_rows)
    assert "API key removed" in _actions(key_rows)


# ---------------------------------------------------------------------------
# Read-only union of the older per-module trails
# ---------------------------------------------------------------------------
def test_activity_log_includes_legacy_requisition_trail(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                      json={"title": f"ZZ Audit Req {os.urandom(3).hex()}", "department": "Sales"}).json()
    rows = _log(client, hr_manager_auth, module="Recruitment", entity_type="requisition", entity_id=str(req["id"]))
    assert "Created" in _actions(rows)
    assert all(r["source"] == "legacy" for r in rows)
    assert _log(client, hr_manager_auth, entity_type="requisition", entity_id=str(req["id"]), include_legacy="false") == []


def test_activity_log_filters_and_pagination(client, hr_manager_auth):
    res = client.get("/api/entity-audit-log", headers=hr_manager_auth, params={"limit": 2})
    assert res.status_code == 200
    assert len(res.json()) <= 2
    assert int(res.headers["X-Total-Count"]) >= len(res.json())
    assert _log(client, hr_manager_auth, actor="zz-no-such-actor-xyz") == []
    assert _log(client, hr_manager_auth, date_from="2999-01-01") == []


# ===========================================================================
# Phase 2 — compensation & pay config, leave, overtime/timesheet settings
# ===========================================================================
def _uniq(prefix):
    return f"{prefix}{os.urandom(3).hex()}".upper()


def test_pay_structure_changes_are_audited(client, hr_manager_auth):
    grade = client.post("/api/compensation/pay-grades", headers=hr_manager_auth, json={
        "grade_code": _uniq("ZG"), "grade_name": "ZZ Audit Grade", "grade_level": 1,
        "min_salary": 2500, "midpoint_salary": 3000, "max_salary": 3500,
    }).json()
    upd = client.put(f"/api/compensation/pay-grades/{grade['id']}", headers=hr_manager_auth,
                     json={"max_salary": 4000})
    assert upd.status_code == 200, upd.text
    level = client.post("/api/compensation/job-levels", headers=hr_manager_auth, json={
        "level_code": _uniq("ZL"), "level_name": "ZZ Audit Level", "level_order": 1}).json()
    client.put(f"/api/compensation/job-levels/{level['id']}", headers=hr_manager_auth,
               json={"level_name": "ZZ Audit Level Renamed"})
    role = client.post("/api/compensation/job-roles", headers=hr_manager_auth, json={
        "job_level_id": level["id"], "role_name": "ZZ Audit Role", "role_code": _uniq("ZR")})
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]
    client.post(f"/api/compensation/job-roles/{role_id}/pay-grades/{grade['id']}", headers=hr_manager_auth)

    g = _log(client, hr_manager_auth, entity_type="pay_grade", entity_id=str(grade["id"]))
    assert set(_actions(g)) >= {"Created", "Updated"}
    ms = next(c for c in next(r for r in g if r["action"] == "Updated")["changes"] if c["field"] == "max_salary")
    assert ms["old"] == "3500.0" and ms["new"] == "4000.0"
    assert set(_actions(_log(client, hr_manager_auth, entity_type="job_level", entity_id=str(level["id"])))) >= {"Created", "Updated"}
    assert set(_actions(_log(client, hr_manager_auth, entity_type="job_role", entity_id=str(role_id)))) >= {"Created", "Mapped to pay grade"}


def test_salary_change_and_compensation_are_audited(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Audit Salary Employee", basic_salary=5000.0)
    res = client.post(f"/api/compensation/salary-changes/{emp['employee_id']}", headers=hr_manager_auth, json={
        "change_type": "merit_increase", "from_salary": 5000.00, "to_salary": 5500.00,
        "effective_date": "2026-07-26", "reason": "ZZ audit merit"})
    assert res.status_code == 201, res.text
    rows = _log(client, hr_manager_auth, entity_type="employee_compensation", entity_id=emp["employee_id"])
    assert "Salary change recorded" in _actions(rows)
    row = next(r for r in rows if r["action"] == "Salary change recorded")
    assert "5,500.00" in row["detail"] and "ZZ audit merit" in row["detail"]


def test_bonus_commission_merit_plans_and_payouts_are_audited(client, hr_manager_auth, make_test_employee):
    bonus = client.post("/api/compensation/bonus-plans", headers=hr_manager_auth, json={
        "plan_name": f"ZZ Audit Bonus {os.urandom(3).hex()}", "plan_type": "Annual", "plan_year": 2027,
        "budget_pool_amount": 1000}).json()
    client.put(f"/api/compensation/bonus-plans/{bonus['id']}", headers=hr_manager_auth,
               json={"status": "Active", "budget_pool_amount": 9000})
    emp = make_test_employee(full_name="ZZ Audit Payout Employee")
    payout = client.post(f"/api/compensation/bonus-payouts?bonus_plan_id={bonus['id']}", headers=hr_manager_auth,
                         json={"employee_id": emp["employee_id"], "target_amount": 1000, "awarded_amount": 800}).json()
    client.put(f"/api/compensation/bonus-payouts/{payout['id']}", headers=hr_manager_auth, json={"status": "Approved"})
    client.put(f"/api/compensation/bonus-payouts/{payout['id']}/pay", headers=hr_manager_auth)

    comm = client.post("/api/compensation/commission-plans", headers=hr_manager_auth, json={
        "plan_name": f"ZZ Audit Comm {os.urandom(3).hex()}", "plan_type": "Flat Rate",
        "default_rate_percent": 5, "plan_year": 2027}).json()
    client.put(f"/api/compensation/commission-plans/{comm['id']}", headers=hr_manager_auth,
               json={"default_rate_percent": 7})
    cycle = client.post("/api/compensation/merit-cycles", headers=hr_manager_auth, json={
        "cycle_name": f"ZZ Audit Cycle {os.urandom(3).hex()}", "review_year": 2027, "cycle_start_date": "2027-07-01",
        "cycle_end_date": "2027-08-31", "submission_deadline": "2027-08-15"})
    assert cycle.status_code == 201, cycle.text

    b = _log(client, hr_manager_auth, entity_type="bonus_plan", entity_id=str(bonus["id"]))
    assert set(_actions(b)) >= {"Created", "Updated"}
    assert any(c["field"] == "status" and c["new"] == "Active" for c in next(r for r in b if r["action"] == "Updated")["changes"])
    p = _log(client, hr_manager_auth, entity_type="bonus_payout", entity_id=str(payout["id"]))
    assert set(_actions(p)) >= {"Payout proposed", "Payout decided", "Payout marked paid"}
    c = _log(client, hr_manager_auth, entity_type="commission_plan", entity_id=str(comm["id"]))
    assert any(x["field"] == "default_rate_percent" and x["new"] == "7.0" for x in next(r for r in c if r["action"] == "Updated")["changes"])
    assert "Created" in _actions(_log(client, hr_manager_auth, entity_type="merit_cycle", entity_id=str(cycle.json()["id"])))


def test_leave_type_and_balance_changes_are_audited(client, hr_manager_auth, make_test_employee):
    lt = client.post("/api/leave/types", headers=hr_manager_auth,
                     json={"name": f"ZZ Audit Leave {os.urandom(3).hex()}", "annual_entitlement": 10.0}).json()
    client.put(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth,
               json={"name": lt["name"], "annual_entitlement": 12.0})
    emp = make_test_employee(full_name="ZZ Audit Leave Employee")
    # Balance rows are created lazily — applying for leave (on the
    # employee's behalf, as HR) is what creates this type's row.
    app = client.post("/api/leave/applications", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-04-05", "end_date": "2027-04-05"})
    assert app.status_code == 201, app.text
    bals = client.get("/api/leave/balances", headers=hr_manager_auth,
                      params={"employee_id": emp["employee_id"], "year": 2027}).json()
    bal = next(b for b in bals if b["leave_type_id"] == lt["id"])
    adj = client.patch(f"/api/leave/balances/{bal['id']}", headers=hr_manager_auth, json={"entitled_days": 20})
    assert adj.status_code == 200, adj.text
    assert client.delete(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth).status_code == 204

    t = _log(client, hr_manager_auth, entity_type="leave_type", entity_id=str(lt["id"]))
    assert set(_actions(t)) >= {"Created", "Updated", "Deactivated"}
    ent = next(c for c in next(r for r in t if r["action"] == "Updated")["changes"] if c["field"] == "annual_entitlement")
    assert ent["old"] == "10.0" and ent["new"] == "12.0"
    b = _log(client, hr_manager_auth, entity_type="leave_balance", entity_id=str(bal["id"]))
    assert "Balance adjusted" in _actions(b)
    assert any(c["field"] == "entitled_days" and c["new"] == "20.0" for c in b[0]["changes"])


def test_overtime_and_timesheet_settings_changes_are_audited(client, hr_manager_auth):
    client.put("/api/overtime/settings", headers=hr_manager_auth,
               json={"overtime_conversion_mode": "pay", "overtime_pay_multiplier": 1.5})
    client.put("/api/overtime/settings", headers=hr_manager_auth,
               json={"overtime_conversion_mode": "pay", "overtime_pay_multiplier": 2.25})
    client.put("/api/timesheets/settings", headers=hr_manager_auth, json={"standard_weekly_hours": 40})
    client.put("/api/timesheets/settings", headers=hr_manager_auth, json={"standard_weekly_hours": 44})
    client.put("/api/timesheets/settings", headers=hr_manager_auth, json={"standard_weekly_hours": 40})

    ot = _log(client, hr_manager_auth, entity_type="overtime_settings")
    assert any(c["field"] == "overtime_pay_multiplier" and c["new"] == "2.25" for r in ot for c in r["changes"])
    ts = _log(client, hr_manager_auth, entity_type="timesheet_settings")
    assert any(c["field"] == "standard_weekly_hours" and c["new"] == "44.0" for r in ts for c in r["changes"])
