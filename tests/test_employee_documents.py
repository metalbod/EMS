"""
Integration tests for routers/employee_documents.py: HR-configurable
document types (Work Permit, Passport, etc — each with its own
reminder_window_days) and per-employee tracked document instances,
plus the Dashboard To-Do aggregate and monthly calendar integration.

Status (overdue / expiring_soon / ok) is computed lazily in SQL from
CURRENT_DATE, never stored — boundary tests below construct dates
relative to today rather than hardcoding, so they don't rot.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from conftest import _valid_employee_payload


def _today():
    return datetime.now(timezone.utc).date()


@pytest.fixture
def hr_admin_auth(make_test_user, test_institution):
    token, _ = make_test_user(role="hr_admin")
    return {
        "Authorization": f"Bearer {token}",
        "X-Institution-Id": str(test_institution["id"]),
    }


@pytest.fixture
def make_test_document_type(client, hr_manager_auth):
    """Factory fixture: creates a disposable document type, soft-deletes it
    on teardown (no hard-delete endpoint, only is_active=0 via DELETE)."""
    created_ids = []

    def _make(**overrides):
        payload = {"name": "ZZ Work Permit", "reminder_window_days": 30}
        payload.update(overrides)
        res = client.post("/api/employee-document-types", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test document type: {res.text}"
        dt = res.json()
        created_ids.append(dt["id"])
        return dt

    yield _make

    for tid in created_ids:
        client.delete(f"/api/employee-document-types/{tid}", headers=hr_manager_auth)


def _fresh_institution_hr_manager_auth(client, superadmin_headers):
    """An hr_manager account scoped to a brand-new, throwaway institution —
    not the shared session-wide test_institution. The Dashboard To-Do
    aggregate counts every qualifying document institution-wide, so an
    exact-count assertion against the shared test_institution could be
    thrown off by another test's leftover data; a dedicated fresh
    institution sidesteps that (same rationale as test_dashboard.py's
    identically-named helper)."""
    code = f"ZZDOCHR{os.urandom(4).hex()}".upper()
    username = f"zzdochr_admin_{os.urandom(4).hex()}"
    password = "ZzPytest@123"
    create = client.post("/api/institutions", headers=superadmin_headers, json={
        "name": "ZZ Document Compliance HR Institution",
        "code": code,
        "contact_email": "zzdochr@example.com",
        "admin_username": username,
        "admin_full_name": "ZZ Document Compliance HR Admin",
        "admin_password": password,
    })
    assert create.status_code == 201, create.text
    inst = create.json()
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": code,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return inst, headers


# ---------------------------------------------------------------------------
# Document Types
# ---------------------------------------------------------------------------
def test_list_document_types_requires_auth(client):
    res = client.get("/api/employee-document-types")
    assert res.status_code in (401, 403)


def test_create_document_type_requires_hr_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/employee-document-types", headers=headers, json={"name": "ZZ"})
    assert res.status_code == 403


def test_create_document_type_success(client, make_test_document_type):
    dt = make_test_document_type(name="ZZ Passport", reminder_window_days=90)
    assert dt["name"] == "ZZ Passport"
    assert dt["reminder_window_days"] == 90
    assert dt["is_active"]


def test_hr_admin_can_manage_document_types(client, hr_admin_auth):
    res = client.post("/api/employee-document-types", headers=hr_admin_auth, json={"name": "ZZ HR Admin Type"})
    assert res.status_code == 201
    client.delete(f"/api/employee-document-types/{res.json()['id']}", headers=hr_admin_auth)


def test_update_document_type_success(client, hr_manager_auth, make_test_document_type):
    dt = make_test_document_type()
    res = client.put(f"/api/employee-document-types/{dt['id']}", headers=hr_manager_auth,
                      json={"name": "ZZ Renamed", "reminder_window_days": 45})
    assert res.status_code == 200
    assert res.json()["name"] == "ZZ Renamed"
    assert res.json()["reminder_window_days"] == 45


def test_update_document_type_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/employee-document-types/999999999", headers=hr_manager_auth,
                      json={"name": "ZZ", "reminder_window_days": 30})
    assert res.status_code == 404


def test_delete_document_type_soft_deletes(client, hr_manager_auth, make_test_document_type):
    dt = make_test_document_type()
    res = client.delete(f"/api/employee-document-types/{dt['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/employee-document-types", headers=hr_manager_auth).json()
    assert dt["id"] not in [t["id"] for t in listed]


def test_document_type_reminder_window_below_1_rejected(client, hr_manager_auth):
    res = client.post("/api/employee-document-types", headers=hr_manager_auth,
                       json={"name": "ZZ Bad Window", "reminder_window_days": 0})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Per-employee tracked documents
# ---------------------------------------------------------------------------
def test_create_document_requires_hr_role(client, make_test_user, test_institution, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type()
    token, _ = make_test_user(role="manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=headers,
                       json={"document_type_id": dt["id"], "expiry_date": "2027-06-01"})
    assert res.status_code == 403


def test_create_document_unknown_employee_returns_404(client, hr_manager_auth, make_test_document_type):
    dt = make_test_document_type()
    res = client.post("/api/employees/ZZ_NOPE/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": "2027-06-01"})
    assert res.status_code == 404


def test_create_document_unknown_type_returns_404(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": 999999999, "expiry_date": "2027-06-01"})
    assert res.status_code == 404


def test_create_document_success_returns_status_and_days(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type(reminder_window_days=30)
    expiry = (_today() + timedelta(days=10)).isoformat()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "document_number": "A12345", "expiry_date": expiry})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "expiring_soon"
    assert body["days_until_expiry"] == 10
    assert body["document_number"] == "A12345"


def test_create_document_duplicate_type_returns_400(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type()
    body = {"document_type_id": dt["id"], "expiry_date": "2027-06-01"}
    first = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth, json=body)
    assert first.status_code == 201, first.text
    second = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth, json=body)
    assert second.status_code == 400
    assert "already tracked" in second.json()["detail"]


def test_update_document_renews_and_recomputes_status(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type(reminder_window_days=30)
    create = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                          json={"document_type_id": dt["id"], "expiry_date": (_today() - timedelta(days=1)).isoformat()})
    assert create.status_code == 201, create.text
    assert create.json()["status"] == "overdue"
    doc_id = create.json()["id"]

    renewed_expiry = (_today() + timedelta(days=365)).isoformat()
    update = client.put(f"/api/employees/{emp['employee_id']}/documents/{doc_id}", headers=hr_manager_auth,
                         json={"document_type_id": dt["id"], "expiry_date": renewed_expiry})
    assert update.status_code == 200, update.text
    assert update.json()["status"] == "ok"
    assert update.json()["expiry_date"] == renewed_expiry


def test_delete_document_removes_it(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type()
    create = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                          json={"document_type_id": dt["id"], "expiry_date": "2027-06-01"})
    doc_id = create.json()["id"]
    res = client.delete(f"/api/employees/{emp['employee_id']}/documents/{doc_id}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth).json()
    assert doc_id not in [d["id"] for d in listed]


def test_update_document_not_found_returns_404(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type()
    res = client.put(f"/api/employees/{emp['employee_id']}/documents/999999999", headers=hr_manager_auth,
                      json={"document_type_id": dt["id"], "expiry_date": "2027-06-01"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Status boundary cases
# ---------------------------------------------------------------------------
def test_status_boundary_exact_window_is_expiring_soon(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type(reminder_window_days=30)
    expiry = (_today() + timedelta(days=30)).isoformat()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": expiry})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "expiring_soon"


def test_status_boundary_beyond_window_is_ok(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type(reminder_window_days=30)
    expiry = (_today() + timedelta(days=31)).isoformat()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": expiry})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "ok"


def test_status_boundary_past_is_overdue(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type(reminder_window_days=30)
    expiry = (_today() - timedelta(days=1)).isoformat()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": expiry})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "overdue"


def test_status_boundary_today_is_expiring_soon(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type(reminder_window_days=30)
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": _today().isoformat()})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "expiring_soon"


# ---------------------------------------------------------------------------
# Calendar endpoint
# ---------------------------------------------------------------------------
def test_calendar_requires_hr_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/employee-documents/calendar", headers=headers, params={"year": 2027, "month": 6})
    assert res.status_code == 403


def test_calendar_returns_documents_in_month(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": "2027-06-15"})
    assert res.status_code == 201, res.text

    cal = client.get("/api/employee-documents/calendar", headers=hr_manager_auth, params={"year": 2027, "month": 6})
    assert cal.status_code == 200, cal.text
    matches = [r for r in cal.json() if r["employee_id"] == emp["employee_id"] and r["expiry_date"] == "2027-06-15"]
    assert len(matches) == 1
    assert matches[0]["document_type_name"] == dt["name"]


def test_calendar_excludes_documents_outside_month(client, hr_manager_auth, make_test_employee, make_test_document_type):
    emp = make_test_employee()
    dt = make_test_document_type()
    res = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_manager_auth,
                       json={"document_type_id": dt["id"], "expiry_date": "2027-07-15"})
    assert res.status_code == 201, res.text

    cal = client.get("/api/employee-documents/calendar", headers=hr_manager_auth, params={"year": 2027, "month": 6})
    assert cal.status_code == 200, cal.text
    assert emp["employee_id"] not in [r["employee_id"] for r in cal.json()]


# ---------------------------------------------------------------------------
# Dashboard To-Do integration
# ---------------------------------------------------------------------------
def test_todos_includes_expiring_document_count_for_hr(client, superadmin_headers, make_test_employee):
    inst, hr_headers = _fresh_institution_hr_manager_auth(client, superadmin_headers)

    before = client.get("/api/todos", headers=hr_headers).json()
    assert not any(t["key"] == "employee-documents-expiring" for t in before)

    dt = client.post("/api/employee-document-types", headers=hr_headers,
                      json={"name": "ZZ Work Permit", "reminder_window_days": 30}).json()
    emp = client.post("/api/employees", headers=hr_headers,
                       json=_valid_employee_payload(full_name="ZZ Dash Doc Employee")).json()
    doc = client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_headers,
                       json={"document_type_id": dt["id"], "expiry_date": (_today() + timedelta(days=5)).isoformat()})
    assert doc.status_code == 201, doc.text

    after = client.get("/api/todos", headers=hr_headers).json()
    item = next(t for t in after if t["key"] == "employee-documents-expiring")
    assert item["count"] == 1
    assert item["page"] == "dash-leave"
    assert "1 employee document" in item["label"]


def test_todos_absent_entirely_for_manager_role(client, superadmin_headers):
    inst, hr_headers = _fresh_institution_hr_manager_auth(client, superadmin_headers)
    dt = client.post("/api/employee-document-types", headers=hr_headers,
                      json={"name": "ZZ Work Permit", "reminder_window_days": 30}).json()
    emp = client.post("/api/employees", headers=hr_headers,
                       json=_valid_employee_payload(full_name="ZZ Dash Doc Manager Employee")).json()
    client.post(f"/api/employees/{emp['employee_id']}/documents", headers=hr_headers,
                json={"document_type_id": dt["id"], "expiry_date": (_today() + timedelta(days=5)).isoformat()})

    mgr_username = f"zzdocmgr_{os.urandom(4).hex()}"
    mgr_password = "ZzPytest@123"
    create_user = client.post("/api/users", headers=hr_headers, json={
        "username": mgr_username, "full_name": "ZZ Doc Manager", "password": mgr_password, "role": "manager",
    })
    assert create_user.status_code == 201, create_user.text
    login = client.post("/api/auth/login", json={
        "username": mgr_username, "password": mgr_password, "institution_code": inst["code"],
    })
    assert login.status_code == 200, login.text
    mgr_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    todos = client.get("/api/todos", headers=mgr_headers).json()
    assert not any(t["key"] == "employee-documents-expiring" for t in todos)
