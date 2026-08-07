"""Integration tests for routers/onboarding.py."""
import os

import pytest


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    """A real employee record with a linked login (role=employee)."""
    emp = make_test_employee()
    username = f"zztob_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Onboarding Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, f"failed to create employee-linked user: {res.text}"
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    yield emp, headers

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def _unique_title(prefix="ZZ Test Template"):
    return f"{prefix} {os.urandom(4).hex()}"


@pytest.fixture
def make_test_ob_checklist(client, hr_manager_auth):
    """Factory fixture: starts a checklist, deletes it (and its items) on
    teardown. Every test in this file that starts a checklist without
    cleaning it up left its snapshotted items (several assigned_role=
    hr_manager/hr_admin) pending forever — across enough test runs in the
    shared ZZPYTEST institution that routers/dashboard.py's To-Do count
    for those roles reached ~5,300 pending items. Usage:

        checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
        checklist = make_test_ob_checklist(employee_id=emp["employee_id"], type="offboarding")
    """
    created_ids = []

    def _make(**overrides):
        payload = {"type": "onboarding"}
        payload.update(overrides)
        res = client.post("/api/ob/checklists", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to start test checklist: {res.text}"
        checklist = res.json()
        created_ids.append(checklist["id"])
        return checklist

    yield _make

    for cl_id in created_ids:
        client.delete(f"/api/ob/checklists/{cl_id}", headers=hr_manager_auth)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def test_list_templates_requires_auth(client):
    res = client.get("/api/ob/templates")
    assert res.status_code in (401, 403)


def test_create_template_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/ob/templates", headers=headers, json={"title": _unique_title()})
    assert res.status_code == 403


def test_create_template_invalid_type_returns_400(client, hr_manager_auth):
    res = client.post("/api/ob/templates", headers=hr_manager_auth,
                       json={"title": _unique_title(), "type": "bogus"})
    assert res.status_code == 400


def test_create_template_invalid_assigned_role_returns_400(client, hr_manager_auth):
    res = client.post("/api/ob/templates", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "bogus_role"})
    assert res.status_code == 400


def test_create_template_success_and_appears_in_list(client, hr_manager_auth):
    title = _unique_title()
    res = client.post("/api/ob/templates", headers=hr_manager_auth,
                       json={"title": title, "type": "onboarding", "assigned_role": "hr_admin"})
    assert res.status_code == 201, res.text
    tmpl = res.json()

    listing = client.get("/api/ob/templates", headers=hr_manager_auth, params={"type": "onboarding"})
    assert listing.status_code == 200
    assert any(t["id"] == tmpl["id"] for t in listing.json())


def test_update_template_success(client, hr_manager_auth):
    title = _unique_title()
    created = client.post("/api/ob/templates", headers=hr_manager_auth,
                           json={"title": title, "type": "onboarding"}).json()
    updated = client.put(f"/api/ob/templates/{created['id']}", headers=hr_manager_auth, json={
        "title": "ZZ Updated Title", "type": "onboarding", "assigned_role": "manager",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "ZZ Updated Title"


def test_update_template_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/ob/templates/999999999", headers=hr_manager_auth,
                      json={"title": "ZZ Ghost", "type": "onboarding"})
    assert res.status_code == 404


def test_delete_template_soft_deletes(client, hr_manager_auth):
    title = _unique_title()
    created = client.post("/api/ob/templates", headers=hr_manager_auth,
                           json={"title": title, "type": "onboarding"}).json()
    delete = client.delete(f"/api/ob/templates/{created['id']}", headers=hr_manager_auth)
    assert delete.status_code == 204
    listing = client.get("/api/ob/templates", headers=hr_manager_auth, params={"type": "onboarding"})
    assert all(t["id"] != created["id"] for t in listing.json())


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------
def test_start_checklist_requires_manage_role(client, make_test_user, test_institution, make_test_employee):
    emp = make_test_employee()
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/ob/checklists", headers=headers,
                       json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert res.status_code == 403


def test_start_checklist_invalid_type_returns_400(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/ob/checklists", headers=hr_manager_auth,
                       json={"employee_id": emp["employee_id"], "type": "bogus"})
    assert res.status_code == 400


def test_start_checklist_employee_not_found_returns_404(client, hr_manager_auth):
    res = client.post("/api/ob/checklists", headers=hr_manager_auth,
                       json={"employee_id": "EMP_DOES_NOT_EXIST", "type": "onboarding"})
    assert res.status_code == 404


def test_start_checklist_success_snapshots_active_templates(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    title = _unique_title()
    client.post("/api/ob/templates", headers=hr_manager_auth,
                json={"title": title, "type": "onboarding", "assigned_role": "hr_admin"})
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    assert checklist["status"] == "In Progress"

    detail = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)
    assert detail.status_code == 200
    items = detail.json()["items"]
    assert any(i["title"] == title for i in items)


def test_start_checklist_duplicate_active_returns_400(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    make_test_ob_checklist(employee_id=emp["employee_id"])
    res2 = client.post("/api/ob/checklists", headers=hr_manager_auth,
                        json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert res2.status_code == 400


def test_get_checklist_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/ob/checklists/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_employee_can_view_own_checklist_but_only_own_role_items(client, hr_manager_auth, employee_with_user, make_test_ob_checklist):
    emp, emp_headers = employee_with_user
    title = _unique_title()
    client.post("/api/ob/templates", headers=hr_manager_auth,
                json={"title": title, "type": "onboarding", "assigned_role": "hr_admin"})
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])

    res = client.get(f"/api/ob/checklists/{checklist['id']}", headers=emp_headers)
    assert res.status_code == 200
    items = res.json()["items"]
    assert all(i["assigned_role"] == "employee" for i in items)


def test_employee_cannot_view_someone_elses_checklist(client, hr_manager_auth, make_test_employee, employee_with_user, make_test_ob_checklist):
    other_emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=other_emp["employee_id"])

    _, emp_headers = employee_with_user
    res = client.get(f"/api/ob/checklists/{checklist['id']}", headers=emp_headers)
    assert res.status_code == 403


def test_update_item_invalid_status_returns_400(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    add = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "hr_admin"})
    item = add.json()
    res = client.patch(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}", headers=hr_manager_auth,
                        json={"status": "Bogus"})
    assert res.status_code == 400


def test_update_item_not_found_returns_404(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    res = client.patch(f"/api/ob/checklists/{checklist['id']}/items/999999999", headers=hr_manager_auth,
                        json={"status": "Done"})
    assert res.status_code == 404


def test_update_item_denied_for_wrong_role(client, hr_manager_auth, make_test_employee, employee_with_user, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    add = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "manager"})
    item = add.json()

    _, emp_headers = employee_with_user
    res = client.patch(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}", headers=emp_headers,
                        json={"status": "Done"})
    assert res.status_code == 403


def test_update_item_success_and_auto_completes_checklist(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    add = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "hr_admin"})
    item = add.json()

    # No default templates active for this fresh test institution setup in
    # general, but any snapshotted items from other templates must also be
    # resolved for the checklist to auto-complete — delete them first so
    # this test only has to satisfy the one item it just added.
    detail = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth).json()
    for other in detail["items"]:
        if other["id"] != item["id"]:
            client.delete(f"/api/ob/checklists/{checklist['id']}/items/{other['id']}", headers=hr_manager_auth)

    res = client.patch(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}", headers=hr_manager_auth,
                        json={"status": "Done", "notes": "ZZ all set"})
    assert res.status_code == 200, res.text

    final = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth).json()
    assert final["status"] == "Completed"


def test_edit_item_success(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    add = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "hr_admin"})
    item = add.json()
    res = client.put(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}", headers=hr_manager_auth,
                      json={"title": "ZZ Renamed Item", "assigned_role": "manager"})
    assert res.status_code == 200, res.text

    detail = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth).json()
    updated_item = next(i for i in detail["items"] if i["id"] == item["id"])
    assert updated_item["title"] == "ZZ Renamed Item"
    assert updated_item["assigned_role"] == "manager"


def test_add_item_invalid_role_returns_400(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    res = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "bogus_role"})
    assert res.status_code == 400


def test_delete_item_success(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    add = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                       json={"title": _unique_title(), "assigned_role": "hr_admin"})
    item = add.json()
    delete = client.delete(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}", headers=hr_manager_auth)
    assert delete.status_code == 204

    detail = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth).json()
    assert all(i["id"] != item["id"] for i in detail["items"])


def test_delete_checklist_success(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    checklist = client.post("/api/ob/checklists", headers=hr_manager_auth,
                             json={"employee_id": emp["employee_id"], "type": "onboarding"}).json()
    delete = client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)
    assert delete.status_code == 204
    get = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)
    assert get.status_code == 404


def test_get_ob_history_records_checklist_started(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    assert checklist["status"] == "In Progress"

    history = client.get(f"/api/employees/{emp['employee_id']}/ob-history", headers=hr_manager_auth)
    assert history.status_code == 200
    assert any(h["action"] == "Checklist Started" for h in history.json())


def _tiny_data_url():
    return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


def test_add_item_attachment_success(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    """Optional proof-of-completion upload — not required to mark an item
    Done, attachable any time. See routers/onboarding.py's
    add_ob_item_attachments, same shape as candidate_documents."""
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    item = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                        json={"title": _unique_title(), "assigned_role": "hr_admin"}).json()

    res = client.post(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}/attachments", headers=hr_manager_auth,
                       json=[{"file_name": "handover.png", "mime_type": "image/png", "data_url": _tiny_data_url()}])
    assert res.status_code == 201, res.text
    attachments = res.json()
    assert len(attachments) == 1
    assert attachments[0]["file_name"] == "handover.png"
    assert attachments[0]["uploaded_by"]  # non-empty

    listing = client.get(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}/attachments", headers=hr_manager_auth)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = client.get(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth).json()
    detail_item = next(i for i in detail["items"] if i["id"] == item["id"])
    assert detail_item["attachment_count"] == 1

    # Marking the item Done doesn't require any attachment to exist.
    other_item = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                              json={"title": _unique_title(), "assigned_role": "hr_admin"}).json()
    done = client.patch(f"/api/ob/checklists/{checklist['id']}/items/{other_item['id']}", headers=hr_manager_auth,
                         json={"status": "Done"})
    assert done.status_code == 200, done.text


def test_add_item_attachment_denied_for_wrong_role(client, hr_manager_auth, make_test_employee, employee_with_user, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    item = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                        json={"title": _unique_title(), "assigned_role": "manager"}).json()

    _, emp_headers = employee_with_user
    res = client.post(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}/attachments", headers=emp_headers,
                       json=[{"file_name": "proof.png", "mime_type": "image/png", "data_url": _tiny_data_url()}])
    assert res.status_code == 403


def test_delete_item_attachment_success(client, hr_manager_auth, make_test_employee, make_test_ob_checklist):
    emp = make_test_employee()
    checklist = make_test_ob_checklist(employee_id=emp["employee_id"])
    item = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=hr_manager_auth,
                        json={"title": _unique_title(), "assigned_role": "hr_admin"}).json()
    added = client.post(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}/attachments", headers=hr_manager_auth,
                         json=[{"file_name": "proof.png", "mime_type": "image/png", "data_url": _tiny_data_url()}]).json()
    attachment_id = added[0]["id"]

    res = client.delete(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}/attachments/{attachment_id}",
                         headers=hr_manager_auth)
    assert res.status_code == 204

    listing = client.get(f"/api/ob/checklists/{checklist['id']}/items/{item['id']}/attachments", headers=hr_manager_auth)
    assert listing.json() == []


def test_get_ob_history_requires_manage_role(client, employee_with_user):
    emp, emp_headers = employee_with_user
    res = client.get(f"/api/employees/{emp['employee_id']}/ob-history", headers=emp_headers)
    assert res.status_code == 403
