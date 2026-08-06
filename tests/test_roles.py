"""Integration tests for routers/roles.py (per-institution custom roles)
and their downstream usage: routers/users.py's dynamic role validation
and routers/onboarding.py's assigned_role validation. See
core/roles.py's get_valid_roles and README.md-adjacent context in
migrations/versions/20260807_0001_custom_roles.py.
"""
import os


def _unique_name(prefix="ZZ Custom Role"):
    return f"{prefix} {os.urandom(4).hex()}"


def test_list_roles_includes_builtins(client, hr_manager_auth):
    res = client.get("/api/roles", headers=hr_manager_auth)
    assert res.status_code == 200
    roles = res.json()
    keys = {r["role_key"] for r in roles}
    for builtin in ("hr_manager", "hr_admin", "manager", "payroll_manager", "compensation_manager", "employee"):
        assert builtin in keys
    builtin_rows = [r for r in roles if r["role_key"] == "hr_manager"]
    assert builtin_rows[0]["is_builtin"] is True


def test_create_role_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/roles", headers=headers, json={"display_name": "IT Infra"})
    assert res.status_code == 403


def test_create_role_success_and_appears_in_list(client, hr_manager_auth):
    name = _unique_name("IT Infra")
    res = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name})
    assert res.status_code == 201, res.text
    role = res.json()
    assert role["display_name"] == name
    assert role["is_builtin"] is False
    assert role["role_key"]  # auto-slugged, non-empty

    listing = client.get("/api/roles", headers=hr_manager_auth).json()
    assert any(r["role_key"] == role["role_key"] for r in listing)

    client.delete(f"/api/roles/{role['id']}", headers=hr_manager_auth)


def test_create_role_rejects_builtin_key(client, hr_manager_auth):
    res = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": "HR Manager"})
    assert res.status_code == 400


def test_create_role_rejects_duplicate(client, hr_manager_auth):
    name = _unique_name("Facilities")
    res1 = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name})
    assert res1.status_code == 201
    role_id = res1.json()["id"]

    res2 = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name})
    assert res2.status_code == 400

    client.delete(f"/api/roles/{role_id}", headers=hr_manager_auth)


def test_delete_role_blocked_when_assigned_to_user(client, hr_manager_auth, make_test_employee, test_institution):
    name = _unique_name("IT Support")
    role = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name}).json()

    emp = make_test_employee(full_name="ZZ Custom Role Employee")
    username = f"zzcustomrole_{emp['employee_id'].lower()}"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Custom Role User", "password": "ZzPytest@123",
        "role": role["role_key"], "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]

    denied = client.delete(f"/api/roles/{role['id']}", headers=hr_manager_auth)
    assert denied.status_code == 400
    assert "user" in denied.text.lower()

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)
    ok = client.delete(f"/api/roles/{role['id']}", headers=hr_manager_auth)
    assert ok.status_code == 204


def test_custom_role_assignable_to_user(client, hr_manager_auth, make_test_employee):
    name = _unique_name("Facilities Manager")
    role = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name}).json()

    emp = make_test_employee(full_name="ZZ Custom Role User Employee")
    username = f"zzcrassign_{emp['employee_id'].lower()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ CR Assign", "password": "ZzPytest@123",
        "role": role["role_key"], "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, res.text
    assert res.json()["role"] == role["role_key"]

    client.delete(f"/api/users/{res.json()['id']}", headers=hr_manager_auth)
    client.delete(f"/api/roles/{role['id']}", headers=hr_manager_auth)


def test_create_user_unknown_role_rejected(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Unknown Role Employee")
    username = f"zzunkrole_{emp['employee_id'].lower()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Unknown Role", "password": "ZzPytest@123",
        "role": "not_a_real_role", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 400


def test_custom_role_usable_as_ob_template_assigned_role(client, hr_manager_auth):
    name = _unique_name("IT Infra")
    role = client.post("/api/roles", headers=hr_manager_auth, json={"display_name": name}).json()

    res = client.post("/api/ob/templates", headers=hr_manager_auth, json={
        "title": _unique_name("ZZ Setup Laptop"), "type": "onboarding", "assigned_role": role["role_key"],
    })
    assert res.status_code == 201, res.text
    assert res.json()["assigned_role"] == role["role_key"]

    client.delete(f"/api/ob/templates/{res.json()['id']}", headers=hr_manager_auth)
    client.delete(f"/api/roles/{role['id']}", headers=hr_manager_auth)
