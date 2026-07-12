"""Integration tests for routers/audit.py."""


def test_list_audit_logs_requires_auth(client):
    res = client.get("/api/audit-logs")
    assert res.status_code in (401, 403)


def test_list_audit_logs_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/audit-logs", headers=headers)
    assert res.status_code == 403


def test_creating_employee_writes_audit_log(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get("/api/audit-logs", headers=hr_manager_auth,
                      params={"employee_id": emp["employee_id"]})
    assert res.status_code == 200
    logs = res.json()
    assert any(l["action"] == "CREATE" and l["target_employee_id"] == emp["employee_id"] for l in logs)


def test_filter_by_action(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get("/api/audit-logs", headers=hr_manager_auth,
                      params={"employee_id": emp["employee_id"], "action": "CREATE"})
    assert res.status_code == 200
    logs = res.json()
    assert len(logs) >= 1
    assert all(l["action"] == "CREATE" for l in logs)

    res_none = client.get("/api/audit-logs", headers=hr_manager_auth,
                           params={"employee_id": emp["employee_id"], "action": "NO_SUCH_ACTION"})
    assert res_none.status_code == 200
    assert res_none.json() == []


def test_list_audit_logs_respects_limit(client, hr_manager_auth):
    res = client.get("/api/audit-logs", headers=hr_manager_auth, params={"limit": 1})
    assert res.status_code == 200
    assert len(res.json()) <= 1
