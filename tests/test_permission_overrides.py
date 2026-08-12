"""Integration tests for the Settings > Roles > Permission Matrix override
system (core/permission_matrix.py's has_permission, routers/roles.py's
PUT/DELETE .../permission-matrix/override) — the pilot retrofit of
routers/employees.py's 6 flat-gated actions. See permission_matrix.py's
module docstring for why this started as a small pilot instead of every
router at once.
"""
from conftest import _valid_employee_payload


def test_override_actually_changes_behavior_not_just_the_matrix(client, hr_manager_auth, make_test_user, test_institution):
    """The core claim of this feature: overriding manager's access to
    "Create employee" from Denied to Allowed must really let a manager
    create an employee, not just change what the matrix displays."""
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/employees", headers=mgr_headers, json=_valid_employee_payload())
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "employees.create_employee", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text

    try:
        after = client.post("/api/employees", headers=mgr_headers, json=_valid_employee_payload())
        assert after.status_code == 201, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "employees.create_employee", "role": "manager"})

    after_reset = client.post("/api/employees", headers=mgr_headers, json=_valid_employee_payload())
    assert after_reset.status_code == 403, after_reset.text


def test_matrix_reflects_override_default_and_editable_flag(client, hr_manager_auth):
    action_key = "employees.create_employee"
    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": action_key, "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        matrix = client.get("/api/roles/permission-matrix", headers=hr_manager_auth)
        assert matrix.status_code == 200, matrix.text
        mod = next(m for m in matrix.json()["modules"] if m["module"] == "Employees")
        action = next(a for a in mod["actions"] if a["key"] == action_key)
        assert action["access"]["manager"] == "allow"
        assert action["access_default"]["manager"] == "deny"
        assert action["editable"]["manager"] is True
        assert action["enforced"] is True
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": action_key, "role": "manager"})


def test_locked_roles_cannot_be_overridden(client, hr_manager_auth):
    for role in ("hr_manager", "hr_admin", "payroll_manager", "compensation_manager"):
        res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
            "action_key": "employees.create_employee", "role": role, "access_value": "allow",
        })
        assert res.status_code == 400, f"{role} should be locked: {res.text}"


def test_non_enforced_action_cannot_be_overridden(client, hr_manager_auth):
    """"List employees" is relationship-scoped (manager=subordinate,
    employee=own) — not a flat allow/deny row, so it's never enforced."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "employees.list_employees", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


def test_override_requires_role_manage_permission(client, make_test_user, test_institution):
    token, _ = make_test_user(role="manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.put("/api/roles/permission-matrix/override", headers=headers, json={
        "action_key": "employees.create_employee", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 403, res.text
