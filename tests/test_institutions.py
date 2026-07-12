"""Integration tests for routers/institutions.py.

Institutions have no delete endpoint (only Active/Suspended status), so
every institution created here is disposable-but-permanent data — same
accumulation trade-off already accepted for employees/timesheets. Each
test uses a fresh random-salted code so runs never collide.
"""
import os


def _unique_code():
    return f"ZZTINST{os.urandom(4).hex()}".upper()


def _valid_institution_payload(**overrides):
    code = _unique_code()
    payload = {
        "name": "ZZ Test Institution",
        "code": code,
        "contact_email": "zztest@example.com",
        "admin_username": f"zztinst_admin_{code.lower()}",
        "admin_full_name": "ZZ Test Admin",
        "admin_password": "ZzPytest@123",
    }
    payload.update(overrides)
    return payload


def test_list_institutions_requires_auth(client):
    res = client.get("/api/institutions")
    assert res.status_code in (401, 403)


def test_list_institutions_requires_superadmin(client, hr_manager_auth):
    res = client.get("/api/institutions", headers=hr_manager_auth)
    assert res.status_code == 403


def test_create_institution_requires_superadmin(client, hr_manager_auth):
    res = client.post("/api/institutions", headers=hr_manager_auth, json=_valid_institution_payload())
    assert res.status_code == 403


def test_create_institution_success_and_appears_in_list(client, superadmin_headers):
    payload = _valid_institution_payload()
    res = client.post("/api/institutions", headers=superadmin_headers, json=payload)
    assert res.status_code == 201, res.text
    inst = res.json()
    assert inst["code"] == payload["code"]
    assert inst["employee_count"] == 0
    assert inst["user_count"] == 1

    listing = client.get("/api/institutions", headers=superadmin_headers)
    assert listing.status_code == 200
    assert any(i["id"] == inst["id"] for i in listing.json())


def test_create_institution_duplicate_code_returns_400(client, superadmin_headers):
    payload = _valid_institution_payload()
    res1 = client.post("/api/institutions", headers=superadmin_headers, json=payload)
    assert res1.status_code == 201, res1.text
    dup = _valid_institution_payload(code=payload["code"])
    res2 = client.post("/api/institutions", headers=superadmin_headers, json=dup)
    assert res2.status_code == 400


def test_create_institution_duplicate_admin_username_returns_400(client, superadmin_headers):
    payload = _valid_institution_payload()
    res1 = client.post("/api/institutions", headers=superadmin_headers, json=payload)
    assert res1.status_code == 201, res1.text
    dup = _valid_institution_payload(admin_username=payload["admin_username"])
    res2 = client.post("/api/institutions", headers=superadmin_headers, json=dup)
    assert res2.status_code == 400


def test_get_institution_success(client, superadmin_headers):
    payload = _valid_institution_payload()
    created = client.post("/api/institutions", headers=superadmin_headers, json=payload).json()
    res = client.get(f"/api/institutions/{created['id']}", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json()["code"] == payload["code"]


def test_get_institution_not_found_returns_404(client, superadmin_headers):
    res = client.get("/api/institutions/999999999", headers=superadmin_headers)
    assert res.status_code == 404


def test_update_institution_success(client, superadmin_headers):
    payload = _valid_institution_payload()
    created = client.post("/api/institutions", headers=superadmin_headers, json=payload).json()
    update = client.put(f"/api/institutions/{created['id']}", headers=superadmin_headers, json={
        "name": "ZZ Renamed Institution",
        "contact_email": "zzrenamed@example.com",
        "plan": "enterprise",
        "max_employees": 200,
    })
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "ZZ Renamed Institution"
    assert update.json()["max_employees"] == 200


def test_update_institution_not_found_returns_404(client, superadmin_headers):
    res = client.put("/api/institutions/999999999", headers=superadmin_headers, json={
        "name": "ZZ Ghost", "contact_email": "ghost@example.com",
    })
    assert res.status_code == 404


def test_toggle_institution_status_success(client, superadmin_headers):
    payload = _valid_institution_payload()
    created = client.post("/api/institutions", headers=superadmin_headers, json=payload).json()
    res = client.patch(f"/api/institutions/{created['id']}/status", headers=superadmin_headers,
                        json={"status": "Suspended"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Suspended"
    # restore, since institutions can't be deleted and shouldn't linger Suspended
    restore = client.patch(f"/api/institutions/{created['id']}/status", headers=superadmin_headers,
                            json={"status": "Active"})
    assert restore.status_code == 200
    assert restore.json()["status"] == "Active"


def test_toggle_institution_status_invalid_value_returns_400(client, superadmin_headers):
    payload = _valid_institution_payload()
    created = client.post("/api/institutions", headers=superadmin_headers, json=payload).json()
    res = client.patch(f"/api/institutions/{created['id']}/status", headers=superadmin_headers,
                        json={"status": "Bogus"})
    assert res.status_code == 400
