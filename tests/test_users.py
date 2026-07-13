"""Integration tests for routers/users.py."""
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from db import get_db


def test_list_users_requires_auth(client):
    res = client.get("/api/users")
    assert res.status_code in (401, 403)


def test_create_user_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/users", headers=headers, json={
        "username": f"zztest_{os.urandom(4).hex()}", "full_name": "ZZ Nope",
        "password": "ZzPytest@123", "role": "employee",
    })
    assert res.status_code == 403


def test_hr_manager_cannot_create_superadmin(client, hr_manager_auth):
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": f"zztest_{os.urandom(4).hex()}", "full_name": "ZZ Nope",
        "password": "ZzPytest@123", "role": "superadmin",
    })
    assert res.status_code == 403


def test_create_user_invalid_role_returns_422(client, hr_manager_auth):
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": f"zztest_{os.urandom(4).hex()}", "full_name": "ZZ Nope",
        "password": "ZzPytest@123", "role": "not_a_real_role",
    })
    assert res.status_code == 422


def test_create_user_duplicate_username_returns_400(client, hr_manager_auth):
    username = f"zztest_{os.urandom(4).hex()}"
    payload = {"username": username, "full_name": "ZZ Dup", "password": "ZzPytest@123", "role": "employee"}
    res1 = client.post("/api/users", headers=hr_manager_auth, json=payload)
    assert res1.status_code == 201, res1.text
    res2 = client.post("/api/users", headers=hr_manager_auth, json=payload)
    assert res2.status_code == 400
    client.delete(f"/api/users/{res1.json()['id']}", headers=hr_manager_auth)


def test_create_user_success_and_appears_in_list(client, hr_manager_auth, test_institution):
    username = f"zztest_{os.urandom(4).hex()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ New User", "password": "ZzPytest@123", "role": "employee",
    })
    assert res.status_code == 201, res.text
    user = res.json()
    assert user["institution_id"] == test_institution["id"]
    # create_user returns the raw DB row (roles as a comma string); list_users
    # is the endpoint that parses it into a list — see routers/users.py.
    assert user["roles"] == "employee"

    listing = client.get("/api/users", headers=hr_manager_auth)
    assert listing.status_code == 200
    assert any(u["id"] == user["id"] for u in listing.json())

    client.delete(f"/api/users/{user['id']}", headers=hr_manager_auth)


def test_create_user_with_multi_roles(client, hr_manager_auth):
    username = f"zztest_{os.urandom(4).hex()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Multi Role", "password": "ZzPytest@123",
        "role": "employee", "roles": ["employee", "hr_admin"],
    })
    assert res.status_code == 201, res.text
    user = res.json()
    assert user["roles"] == "employee,hr_admin"

    listing = client.get("/api/users", headers=hr_manager_auth)
    listed = next(u for u in listing.json() if u["id"] == user["id"])
    assert set(listed["roles"]) == {"employee", "hr_admin"}

    client.delete(f"/api/users/{user['id']}", headers=hr_manager_auth)


def test_update_user_success(client, hr_manager_auth):
    username = f"zztest_{os.urandom(4).hex()}"
    create = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Before", "password": "ZzPytest@123", "role": "employee",
    })
    user_id = create.json()["id"]

    update = client.put(f"/api/users/{user_id}", headers=hr_manager_auth, json={
        "full_name": "ZZ After", "role": "employee", "is_active": True,
    })
    assert update.status_code == 200, update.text
    assert update.json()["full_name"] == "ZZ After"

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_update_user_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/users/999999999", headers=hr_manager_auth, json={
        "full_name": "ZZ Ghost", "role": "employee",
    })
    assert res.status_code == 404


def test_hr_manager_cannot_edit_superadmin(client, hr_manager_auth, superadmin_headers):
    # Look up the seeded platform superadmin's own user id via /api/users global list.
    global_list = client.get("/api/users", headers={"Authorization": superadmin_headers["Authorization"]})
    assert global_list.status_code == 200
    superadmin_row = next((u for u in global_list.json() if u["role"] == "superadmin"), None)
    assert superadmin_row is not None, "expected at least one superadmin user to exist"

    res = client.put(f"/api/users/{superadmin_row['id']}", headers=hr_manager_auth, json={
        "full_name": "ZZ Hacked", "role": "superadmin",
    })
    # 404, not 403: RLS now hides platform-level rows (institution_id IS
    # NULL) from an institution-scoped hr_manager connection entirely — the
    # endpoint's own SELECT WHERE id=? finds nothing, so it 404s before ever
    # reaching the app-level "Cannot edit Platform Admin" check that used to
    # return 403. Arguably more secure than before: hr_manager can no
    # longer even confirm the superadmin row exists, rather than being
    # explicitly told "found it, but access denied."
    assert res.status_code == 404


def test_hr_manager_cannot_assign_superadmin_role(client, hr_manager_auth):
    username = f"zztest_{os.urandom(4).hex()}"
    create = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Target", "password": "ZzPytest@123", "role": "employee",
    })
    user_id = create.json()["id"]

    res = client.put(f"/api/users/{user_id}", headers=hr_manager_auth, json={
        "full_name": "ZZ Target", "role": "superadmin",
    })
    assert res.status_code == 403

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_cannot_change_own_role(client, make_test_user, test_institution):
    token, user_id = make_test_user(role="hr_manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.put(f"/api/users/{user_id}", headers=headers, json={
        "full_name": "ZZ Self", "role": "employee",
    })
    assert res.status_code == 400


def test_delete_user_success(client, hr_manager_auth):
    username = f"zztest_{os.urandom(4).hex()}"
    create = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Delete Me", "password": "ZzPytest@123", "role": "employee",
    })
    user_id = create.json()["id"]
    res = client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)
    assert res.status_code == 204
    get_list = client.get("/api/users", headers=hr_manager_auth)
    assert all(u["id"] != user_id for u in get_list.json())


def test_delete_user_not_found_returns_404(client, hr_manager_auth):
    res = client.delete("/api/users/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_cannot_delete_own_account(client, make_test_user, test_institution):
    token, user_id = make_test_user(role="hr_manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.delete(f"/api/users/{user_id}", headers=headers)
    assert res.status_code == 400


def test_new_user_login_does_not_require_password_change(client, hr_manager_auth, test_institution):
    username = f"zztest_{os.urandom(4).hex()}"
    password = "ZzPytest@123"
    create = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Fresh User", "password": password, "role": "employee",
    })
    user_id = create.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is False
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_flagged_password_change_required_clears_on_real_password_change(client, hr_manager_auth, test_institution):
    """No API sets must_change_password=1 directly (only main.py's superadmin
    seed/backfill does) — simulate the flagged state the same way a real
    forced-rotation account would arrive at it, via a direct DB write, then
    verify the flag surfaces on login and clears once the password actually
    changes via PUT /api/users/{id}."""
    username = f"zztest_{os.urandom(4).hex()}"
    password = "ZzPytest@123"
    create = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Flagged User", "password": password, "role": "employee",
    })
    user_id = create.json()["id"]

    conn = get_db()
    conn.execute("UPDATE users SET must_change_password=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True

    update = client.put(f"/api/users/{user_id}", headers=hr_manager_auth, json={
        "full_name": "ZZ Flagged User", "role": "employee", "password": "ZzNewPassword@456",
    })
    assert update.status_code == 200, update.text

    listing = client.get("/api/users", headers=hr_manager_auth)
    updated = next(u for u in listing.json() if u["id"] == user_id)
    assert updated["must_change_password"] is False

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)

