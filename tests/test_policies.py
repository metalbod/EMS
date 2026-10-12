"""Policy acknowledgements — routers/policies.py, core/policies.py, migration 20261013_0001."""
import base64
import os

import pytest

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def pdf_url(raw=PDF):
    return "data:application/pdf;base64," + base64.b64encode(raw).decode()


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    emp = make_test_employee(department=f"ZZ Dept {os.urandom(3).hex()}")
    username = f"zztpol_{emp['employee_id'].lower()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Policy Employee", "password": "ZzPytest@123",
        "role": "employee", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": "ZzPytest@123", "institution_code": test_institution["code"]})
    assert login.status_code == 200
    yield emp, {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def publish(client, headers, people=None, **over):
    body = {"title": f"ZZ Policy {os.urandom(3).hex()}", "audience_type": "people", "employee_ids": people or [],
            "file_name": "policy.pdf", "data_url": pdf_url(), "change_note": "First issue"}
    body.update(over)
    return client.post("/api/policies", headers=headers, json=body)


def test_publish_creates_a_policy_course_and_assigns_the_audience(client, hr_manager_auth, employee_with_user):
    emp, _ = employee_with_user
    res = publish(client, hr_manager_auth, [emp["employee_id"]])
    assert res.status_code == 201, res.text
    assert res.json()["assigned"] == 1 and res.json()["version"] == 1
    cid = res.json()["course_id"]
    listing = {p["course_id"]: p for p in client.get("/api/policies", headers=hr_manager_auth).json()}
    assert listing[cid]["assigned"] == 1 and listing[cid]["acknowledged"] == 0
    # not an enrollable course: hidden from the normal catalog, visible under the Policies category
    assert cid not in [c["id"] for c in client.get("/api/ld/courses", headers=hr_manager_auth).json()]
    assert cid in [c["id"] for c in client.get("/api/ld/courses", headers=hr_manager_auth, params={"category": "policy"}).json()]
    assert cid in [c["id"] for c in client.get("/api/ld/courses", headers=hr_manager_auth, params={"include_policies": "true"}).json()]


def test_employee_must_open_then_confirm_then_acknowledge(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    pub = publish(client, hr_manager_auth, [emp["employee_id"]]).json()
    vid = pub["version_id"]

    mine = client.get("/api/policies/mine", headers=me).json()
    row = next(r for r in mine if r["version_id"] == vid)
    assert row["status"] == "not_opened" and row["is_current"]

    # can't acknowledge before opening, nor without ticking the box
    assert client.post(f"/api/policies/versions/{vid}/acknowledge", headers=me, json={"confirm": True}).status_code == 400
    f = client.get(f"/api/policies/versions/{vid}/file", headers=me)
    assert f.status_code == 200 and f.content == PDF
    assert client.get("/api/policies/mine", headers=me).json()[0]["status"] == "opened"
    assert client.post(f"/api/policies/versions/{vid}/acknowledge", headers=me, json={"confirm": False}).status_code == 400

    ok = client.post(f"/api/policies/versions/{vid}/acknowledge", headers=me, json={"confirm": True})
    assert ok.status_code == 200 and ok.json()["acknowledged_at"]
    assert client.post(f"/api/policies/versions/{vid}/acknowledge", headers=me, json={"confirm": True}).json()["already"] is True
    assert next(r for r in client.get("/api/policies/mine", headers=me).json() if r["version_id"] == vid)["status"] == "acknowledged"

    tracker = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth).json()
    assert tracker["summary"] == {"assigned": 1, "opened": 1, "acknowledged": 1, "overdue": 0}
    assert tracker["rows"][0]["status"] == "acknowledged"
    assert client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth,
                      params={"status": "outstanding"}).json()["rows"] == []


def test_acknowledging_without_requiring_open_is_allowed(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    vid = publish(client, hr_manager_auth, [emp["employee_id"]], require_open=False).json()["version_id"]
    assert client.post(f"/api/policies/versions/{vid}/acknowledge", headers=me, json={"confirm": True}).status_code == 200


def test_a_new_version_asks_again_and_supersedes_the_old_request(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    pub = publish(client, hr_manager_auth, [emp["employee_id"]]).json()
    v1 = pub["version_id"]
    v2 = client.post(f"/api/policies/{pub['course_id']}/versions", headers=hr_manager_auth, json={
        "audience_type": "people", "employee_ids": [emp["employee_id"]], "file_name": "v2.pdf",
        "data_url": pdf_url(), "change_note": "Changed leave section"})
    assert v2.status_code == 201 and v2.json()["version"] == 2
    v2id = v2.json()["version_id"]

    mine = client.get("/api/policies/mine", headers=me).json()
    assert [r["version"] for r in mine] == [2], "the unacknowledged v1 is superseded and hidden"
    client.get(f"/api/policies/versions/{v1}/file", headers=me)
    assert client.post(f"/api/policies/versions/{v1}/acknowledge", headers=me, json={"confirm": True}).status_code == 400

    client.get(f"/api/policies/versions/{v2id}/file", headers=me)
    assert client.post(f"/api/policies/versions/{v2id}/acknowledge", headers=me, json={"confirm": True}).status_code == 200
    tracker = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth).json()
    assert [v["version"] for v in tracker["versions"]] == [2, 1] and tracker["version"]["version"] == 2
    old = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth, params={"version_id": v1}).json()
    assert old["is_current"] is False and old["summary"]["acknowledged"] == 0


def test_overdue_after_the_acknowledge_by_date(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    pub = publish(client, hr_manager_auth, [emp["employee_id"]], due_date="2020-01-01").json()
    assert client.get("/api/policies/mine", headers=me).json()[0]["status"] == "overdue"
    assert client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth).json()["summary"]["overdue"] == 1


def test_a_policy_not_assigned_to_you_is_not_yours_to_open_or_acknowledge(client, hr_manager_auth, employee_with_user, make_test_employee):
    emp, me = employee_with_user
    other = make_test_employee()
    vid = publish(client, hr_manager_auth, [other["employee_id"]]).json()["version_id"]
    assert client.get(f"/api/policies/versions/{vid}/file", headers=me).status_code == 403
    assert client.post(f"/api/policies/versions/{vid}/acknowledge", headers=me, json={"confirm": True}).status_code == 403
    assert client.get("/api/policies/mine", headers=me).json() == []


def test_tracker_and_publishing_are_not_open_to_ordinary_employees(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    pub = publish(client, hr_manager_auth, [emp["employee_id"]]).json()
    assert client.get("/api/policies", headers=me).status_code == 403
    assert client.get(f"/api/policies/{pub['course_id']}/tracker", headers=me).status_code == 403
    assert publish(client, me, [emp["employee_id"]]).status_code == 403
    assert client.post(f"/api/policies/versions/{pub['version_id']}/assign", headers=me,
                       json={"employee_ids": [emp["employee_id"]]}).status_code == 403


def test_audience_validation(client, hr_manager_auth):
    assert publish(client, hr_manager_auth, [], audience_type="people").status_code == 400
    assert publish(client, hr_manager_auth, audience_type="department").status_code == 400
    assert publish(client, hr_manager_auth, audience_type="department", audience_ref="ZZ No Such Dept").status_code == 400
    assert publish(client, hr_manager_auth, audience_type="team", audience_ref="NOPE").status_code == 400
    assert publish(client, hr_manager_auth, audience_type="galaxy").status_code == 400
    assert publish(client, hr_manager_auth, ["X"], title="  ").status_code == 400
    assert publish(client, hr_manager_auth, ["X"], due_date="31-12-2026").status_code == 400


def test_document_must_be_a_real_pdf_word_or_powerpoint(client, hr_manager_auth, employee_with_user):
    emp, _ = employee_with_user
    assert publish(client, hr_manager_auth, [emp["employee_id"]], file_name="x.exe").status_code == 400
    assert publish(client, hr_manager_auth, [emp["employee_id"]], data_url=pdf_url(b"not a pdf")).status_code == 400


def test_unassigned_hint_and_add_people(client, hr_manager_auth, make_test_employee):
    dept = f"ZZ Dept {os.urandom(3).hex()}"
    first = make_test_employee(department=dept)
    pub = publish(client, hr_manager_auth, audience_type="department", audience_ref=dept).json()
    assert pub["assigned"] == 1
    joiner = make_test_employee(department=dept)   # joins after it was published — not auto-assigned
    t = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth).json()
    assert [u["employee_id"] for u in t["unassigned"]] == [joiner["employee_id"]]
    res = client.post(f"/api/policies/versions/{pub['version_id']}/assign", headers=hr_manager_auth,
                      json={"employee_ids": [joiner["employee_id"]]})
    assert res.status_code == 200 and res.json()["added"] == 1
    again = client.post(f"/api/policies/versions/{pub['version_id']}/assign", headers=hr_manager_auth,
                        json={"employee_ids": [joiner["employee_id"]]})
    assert again.json()["added"] == 0
    t = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth).json()
    assert t["unassigned"] == [] and t["summary"]["assigned"] == 2


def test_manager_sees_only_their_own_team(client, hr_manager_auth, make_test_employee, make_test_user, test_institution):
    boss = make_test_employee()
    mine = make_test_employee(reports_to=boss["employee_id"])
    other = make_test_employee()
    pub = publish(client, hr_manager_auth, [mine["employee_id"], other["employee_id"]]).json()
    username = f"zzpolmgr_{boss['employee_id'].lower()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Policy Manager", "password": "ZzPytest@123",
        "role": "manager", "employee_id": boss["employee_id"]})
    assert res.status_code == 201, res.text
    try:
        login = client.post("/api/auth/login", json={"username": username, "password": "ZzPytest@123",
                                                     "institution_code": test_institution["code"]})
        mgr = {"Authorization": f"Bearer {login.json()['access_token']}"}
        t = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=mgr).json()
        assert [r["employee_id"] for r in t["rows"]] == [mine["employee_id"]]
        assert t["can_manage"] is False and t["unassigned"] == []
        listed = {p["course_id"]: p for p in client.get("/api/policies", headers=mgr).json()}
        assert listed[pub["course_id"]]["assigned"] == 1
        assert client.post(f"/api/policies/versions/{pub['version_id']}/assign", headers=mgr,
                           json={"employee_ids": [boss["employee_id"]]}).status_code == 403
    finally:
        client.delete(f"/api/users/{res.json()['id']}", headers=hr_manager_auth)


def test_policies_are_not_courses_to_enrol_in_edit_or_fill_with_lessons(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    cid = publish(client, hr_manager_auth, [emp["employee_id"]]).json()["course_id"]
    assert client.post("/api/ld/enrollments", headers=me, json={"employee_id": emp["employee_id"], "course_id": cid}).status_code == 400
    assert client.put(f"/api/ld/courses/{cid}", headers=hr_manager_auth,
                      json={"title": "x", "category": "mandatory"}).status_code == 400
    assert client.put(f"/api/ld/courses/{cid}/modules", headers=hr_manager_auth, json={"modules": []}).status_code == 400
    assert client.post("/api/ld/courses", headers=hr_manager_auth, json={"title": "x", "category": "policy"}).status_code == 400


def test_todo_lists_pending_policies(client, hr_manager_auth, employee_with_user):
    emp, me = employee_with_user
    pub = publish(client, hr_manager_auth, [emp["employee_id"]]).json()
    todos = client.get("/api/todos", headers=me).json()
    item = next(t for t in todos if t["key"] == "policy-ack")
    assert item["count"] == 1 and "acknowledgement" in item["label"]
    client.get(f"/api/policies/versions/{pub['version_id']}/file", headers=me)
    client.post(f"/api/policies/versions/{pub['version_id']}/acknowledge", headers=me, json={"confirm": True})
    assert not [t for t in client.get("/api/todos", headers=me).json() if t["key"] == "policy-ack"]


def test_onboarding_item_linked_to_a_policy_assigns_it_and_completes_on_acknowledge(
    client, hr_manager_auth, employee_with_user, make_test_employee
):
    emp, me = employee_with_user
    someone_else = make_test_employee()
    pol = publish(client, hr_manager_auth, [someone_else["employee_id"]]).json()   # the new hire isn't in it yet
    cl = client.post("/api/ob/checklists", headers=hr_manager_auth, json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert cl.status_code == 201, cl.text
    try:
        item = client.post(f"/api/ob/checklists/{cl.json()['id']}/items", headers=hr_manager_auth, json={
            "title": "ZZ Read the handbook", "assigned_role": "employee", "linked_ld_course_id": pol["course_id"]})
        assert item.status_code == 201, item.text
        assert item.json()["linked_ld_enrollment_id"] is None       # a policy has no enrollment
        assert [r["version_id"] for r in client.get("/api/policies/mine", headers=me).json()] == [pol["version_id"]]
        client.get(f"/api/policies/versions/{pol['version_id']}/file", headers=me)
        assert client.post(f"/api/policies/versions/{pol['version_id']}/acknowledge", headers=me,
                           json={"confirm": True}).status_code == 200
        detail = client.get(f"/api/ob/checklists/{cl.json()['id']}", headers=hr_manager_auth).json()
        got = next(i for i in detail["items"] if i["id"] == item.json()["id"])
        assert got["status"] == "Done"
    finally:
        client.delete(f"/api/ob/checklists/{cl.json()['id']}", headers=hr_manager_auth)
