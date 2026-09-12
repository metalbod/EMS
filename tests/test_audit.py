"""Integration tests for routers/audit.py."""
from conftest import _valid_employee_payload


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


def test_list_audit_logs_exposes_total_count_header(client, hr_manager_auth, make_test_employee):
    """Response stays a plain list (every existing caller reads it that
    way) — the total row count for building Prev/Next pagination is
    surfaced via X-Total-Count instead, so this endpoint's shape never
    needed to change for the callers that don't care about paging."""
    make_test_employee()  # guarantees at least one row exists
    res = client.get("/api/audit-logs", headers=hr_manager_auth, params={"limit": 1})
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    total = int(res.headers["X-Total-Count"])
    assert total >= 1
    assert total >= len(res.json())  # the header reflects the full count, not just this page


def test_list_audit_logs_offset_pages_through_results(client, hr_manager_auth, make_test_employee):
    """offset advances through the result set without overlap — scoped to
    one employee's own two audit entries (CREATE then UPDATE) via
    employee_id, so this isn't sensitive to unrelated audit activity
    elsewhere in the shared, session-scoped test institution (see
    conftest.py's test_institution docstring)."""
    emp = make_test_employee()
    update_res = client.put(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth,
                             json=_valid_employee_payload(full_name="ZZ Audit Paged Update"))
    assert update_res.status_code == 200, update_res.text

    all_rows = client.get("/api/audit-logs", headers=hr_manager_auth,
                           params={"employee_id": emp["employee_id"]}).json()
    assert len(all_rows) >= 2  # CREATE + UPDATE, most-recent-first

    page1 = client.get("/api/audit-logs", headers=hr_manager_auth,
                        params={"employee_id": emp["employee_id"], "limit": 1, "offset": 0}).json()
    page2 = client.get("/api/audit-logs", headers=hr_manager_auth,
                        params={"employee_id": emp["employee_id"], "limit": 1, "offset": 1}).json()
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]
    assert page1[0]["id"] == all_rows[0]["id"]
    assert page2[0]["id"] == all_rows[1]["id"]
