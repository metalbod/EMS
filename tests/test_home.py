"""Integration tests for routers/home.py — the Today tab's team-today and glance figures."""
import os
from datetime import datetime, timedelta, timezone


def _login(client, hr_headers, institution_code, emp, role, label):
    username = f"zzhome_{label}_{os.urandom(3).hex()}"
    res = client.post("/api/users", headers=hr_headers, json={
        "username": username, "full_name": f"ZZ Home {label}", "password": "ZzPytest@123",
        "role": role, "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, res.text
    login = client.post("/api/auth/login", json={"username": username, "password": "ZzPytest@123", "institution_code": institution_code})
    assert login.status_code == 200, login.text
    return res.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ids(block):
    return {p["employee_id"] for p in block["people"]}


def test_requires_auth_and_is_closed_to_employees(client, hr_manager_auth, test_institution, make_test_employee):
    assert client.get("/api/home/team-today").status_code in (401, 403)
    assert client.get("/api/home/glance").status_code in (401, 403)
    emp = make_test_employee()
    uid, h = _login(client, hr_manager_auth, test_institution["code"], emp, "employee", "emp")
    assert client.get("/api/home/team-today", headers=h).status_code == 403
    g = client.get("/api/home/glance", headers=h)
    assert g.status_code == 200 and set(g.json()) == {"next_pay_date", "pay_days_until"}
    assert g.json()["next_pay_date"] and g.json()["pay_days_until"] >= 0
    client.delete(f"/api/users/{uid}", headers=hr_manager_auth)


def test_manager_sees_only_their_own_reports_and_never_themself(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    mgr = make_test_employee(designation="ZZ Home Manager")
    report = make_test_employee(designation="ZZ Home Report", reports_to=mgr["employee_id"])
    stranger = make_test_employee(designation="ZZ Home Stranger")
    uid, mh = _login(client, hr_manager_auth, test_institution["code"], mgr, "manager", "mgr")
    ruid, rh = _login(client, hr_manager_auth, test_institution["code"], report, "employee", "rep")
    suid, sh = _login(client, hr_manager_auth, test_institution["code"], stranger, "employee", "str")
    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14, count_calendar_days=True, name="ZZ Home Secret Leave Type")

    today = client.get("/api/home/team-today", headers=mh).json()["date"]
    for e, h in ((report, rh), (stranger, sh)):
        app = client.post("/api/leave/applications", headers=h, json={
            "employee_id": e["employee_id"], "leave_type_id": lt["id"], "start_date": today, "end_date": today})
        assert app.status_code == 201, app.text
        # whoever the workflow asks (the direct manager first, then HR) approves until it is Approved
        for approver in (mh, hr_manager_auth, mh, hr_manager_auth):
            r = client.patch(f"/api/leave/applications/{app.json()['id']}/status", headers=approver, json={"status": "Approved"})
            if r.status_code == 200 and r.json()["status"] == "Approved":
                break
        else:
            raise AssertionError(f"leave never reached Approved: {r.status_code} {r.text}")

    m = client.get("/api/home/team-today", headers=mh)
    assert m.status_code == 200, m.text
    body = m.json()
    assert body["scope"] == "team" and body["total_people"] == 1
    assert _ids(body["on_leave"]) == {report["employee_id"]}
    assert mgr["employee_id"] not in _ids(body["on_leave"]) | _ids(body["clocked_in"]) | _ids(body["late_or_missing"])
    assert "ZZ Home Secret Leave Type" not in m.text          # that someone is away, never what kind of leave
    assert [w["employee_id"] for w in body["away_this_week"]] == [report["employee_id"]]

    hr = client.get("/api/home/team-today", headers=hr_manager_auth).json()
    assert hr["scope"] == "company"
    assert {report["employee_id"], stranger["employee_id"]} <= _ids(hr["on_leave"]) or hr["on_leave"]["count"] > len(hr["on_leave"]["people"])
    assert hr["total_people"] >= 3
    for u in (uid, ruid, suid):
        client.delete(f"/api/users/{u}", headers=hr_manager_auth)


def test_coming_up_lists_probation_and_contract_ends_within_a_month_for_the_viewers_scope(
    client, hr_manager_auth, test_institution, make_test_employee
):
    mgr = make_test_employee(designation="ZZ Home M2")
    soon = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
    later = (datetime.now(timezone.utc).date() + timedelta(days=90)).isoformat()
    mine = make_test_employee(designation="ZZ Home Probation", reports_to=mgr["employee_id"], probation_end_date=soon)
    far = make_test_employee(designation="ZZ Home Far", reports_to=mgr["employee_id"], contract_end_date=later)
    other = make_test_employee(designation="ZZ Home Other", contract_end_date=soon)
    uid, mh = _login(client, hr_manager_auth, test_institution["code"], mgr, "manager", "m2")

    up = client.get("/api/home/team-today", headers=mh).json()["coming_up"]
    assert [(u["employee_id"], u["kind"]) for u in up] == [(mine["employee_id"], "Probation ends")]
    assert up[0]["days"] in (4, 5, 6) and up[0]["date"] == soon
    hr_up = {(u["employee_id"], u["kind"]) for u in client.get("/api/home/team-today", headers=hr_manager_auth).json()["coming_up"]}
    assert (other["employee_id"], "Contract ends") in hr_up or len(hr_up) >= 8   # HR list is capped; scope is wider
    assert far["employee_id"] not in {u[0] for u in hr_up}                        # 90 days out: not "coming up"
    client.delete(f"/api/users/{uid}", headers=hr_manager_auth)


def test_profile_attention_is_scoped_like_opening_the_record(client, hr_manager_auth, test_institution, make_test_employee):
    soon = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
    later = (datetime.now(timezone.utc).date() + timedelta(days=200)).isoformat()
    mgr = make_test_employee(designation="ZZ Attn Mgr")
    report = make_test_employee(designation="ZZ Attn Report", reports_to=mgr["employee_id"], probation_end_date=soon, contract_end_date=later)
    peer = make_test_employee(designation="ZZ Attn Peer", probation_end_date=soon)
    muid, mh = _login(client, hr_manager_auth, test_institution["code"], mgr, "manager", "am")
    ruid, rh = _login(client, hr_manager_auth, test_institution["code"], report, "employee", "ar")

    own = client.get(f"/api/employees/{report['employee_id']}/attention", headers=rh)
    assert own.status_code == 200, own.text
    kinds = [i["kind"] for i in own.json()["items"]]
    assert kinds == ["probation"]                              # contract is 200 days away: not "needs attention"
    assert own.json()["items"][0]["days"] in (9, 10, 11)       # the company's own calendar day, which can differ from UTC's
    assert client.get(f"/api/employees/{peer['employee_id']}/attention", headers=rh).status_code == 404       # employee: only themself
    assert client.get(f"/api/employees/{report['employee_id']}/attention", headers=mh).status_code == 200      # manager: their chain
    assert client.get(f"/api/employees/{peer['employee_id']}/attention", headers=mh).status_code == 404        # …not a peer outside it
    assert client.get(f"/api/employees/{peer['employee_id']}/attention", headers=hr_manager_auth).status_code == 200
    assert client.get("/api/employees/EMP-NOPE-1/attention", headers=hr_manager_auth).status_code == 404
    assert client.get(f"/api/employees/{peer['employee_id']}/attention").status_code in (401, 403)
    # HR-only kinds never reach a manager
    assert all(i["kind"] not in ("documents", "checklist") for i in client.get(f"/api/employees/{report['employee_id']}/attention", headers=mh).json()["items"])
    for u in (muid, ruid):
        client.delete(f"/api/users/{u}", headers=hr_manager_auth)


def test_profile_attention_counts_expiring_documents_for_hr_only(client, hr_manager_auth, test_institution, make_test_employee):
    emp = make_test_employee(designation="ZZ Attn Docs")
    dt = client.post("/api/employee-document-types", headers=hr_manager_auth, json={"name": f"ZZ Attn Permit {os.urandom(2).hex()}", "reminder_window_days": 30})
    assert dt.status_code in (200, 201), dt.text
    soon = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
    doc = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth, json={
        "document_type_id": dt.json()["id"], "expiry_date": soon})
    assert doc.status_code == 201, doc.text
    items = client.get(f"/api/employees/{emp['employee_id']}/attention", headers=hr_manager_auth).json()["items"]
    assert [i["kind"] for i in items if i["kind"] == "documents"] == ["documents"]
    assert next(i for i in items if i["kind"] == "documents")["tab"] == "vt-documents"
    client.delete(f"/api/employees/{emp['employee_id']}/documents/{doc.json()['id']}", headers=hr_manager_auth)
    client.delete(f"/api/employee-document-types/{dt.json()['id']}", headers=hr_manager_auth)
