"""Interview interviewers: the picker's linked employees, the Home To-Do, and the My Interviews screen
(routers/recruitment.py, routers/dashboard.py, migration 20261016_0001)."""
import os

import pytest

PDF_URL = "data:application/pdf;base64,JVBERi0xLjQKJcOkw7zDtsO4Cg=="


def _login(client, test_institution, username):
    res = client.post("/api/auth/login", json={"username": username, "password": "ZzPytest@123",
                                               "institution_code": test_institution["code"]})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def make_interviewer(client, hr_manager_auth, make_test_employee, test_institution):
    """A real employee with a login (role employee): returns (employee, auth headers)."""
    made = []

    def _make(**emp_over):
        emp = make_test_employee(**emp_over)
        username = f"zzint_{emp['employee_id'].lower()}"
        res = client.post("/api/users", headers=hr_manager_auth, json={
            "username": username, "full_name": emp["full_name"], "password": "ZzPytest@123",
            "role": "employee", "employee_id": emp["employee_id"]})
        assert res.status_code == 201, res.text
        made.append(res.json()["id"])
        return emp, _login(client, test_institution, username)

    yield _make
    for uid in made:
        client.delete(f"/api/users/{uid}", headers=hr_manager_auth)


@pytest.fixture
def candidate(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth, json={
        "full_name": "ZZ Interviewed Candidate", "email": f"zzpytest.intr.{os.urandom(4).hex()}@example.com",
        "phone": "012-3456789", "current_position": "Engineer", "skills": "Python"}).json()
    client.post(f"/api/recruitment/candidates/{cand['id']}/documents", headers=hr_manager_auth,
                json=[{"file_name": "resume.pdf", "mime_type": "application/pdf", "data_url": PDF_URL}])
    return cand


def schedule(client, headers, candidate, ids=None, **over):
    body = {"candidate_id": candidate["id"], "interview_type": "Panel", "scheduled_date": "2030-05-01",
            "scheduled_time": "10:00", "location": "Room A"}
    if ids is not None:
        body["interviewer_ids"] = ids
    body.update(over)
    res = client.post("/api/recruitment/interviews", headers=headers, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def listed(client, headers, int_id):
    return next(r for r in client.get("/api/recruitment/interviews", headers=headers).json() if r["id"] == int_id)


def test_picked_interviewers_are_linked_and_their_names_become_the_display_text(client, hr_manager_auth, candidate, make_interviewer):
    a, _ = make_interviewer(full_name="ZZ Alpha Interviewer")
    b, _ = make_interviewer(full_name="ZZ Beta Interviewer", preferred_name="Beta")
    iv = schedule(client, hr_manager_auth, candidate, [a["employee_id"], b["employee_id"], a["employee_id"]])
    row = listed(client, hr_manager_auth, iv["id"])
    assert row["interviewer_ids"] == [a["employee_id"], b["employee_id"]]          # duplicates collapse
    assert row["interviewers"] == "ZZ Alpha Interviewer, Beta"                      # preferred name when set
    assert [(s["name"], s["scored"], s["has_login"]) for s in row["interviewer_status"]] == [
        ("ZZ Alpha Interviewer", False, True), ("Beta", False, True)]


def test_only_active_employees_can_be_picked(client, hr_manager_auth, candidate, make_test_employee):
    gone = make_test_employee(full_name="ZZ Left Interviewer")
    client.patch(f"/api/employees/{gone['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})
    for bad in (gone["employee_id"], "ZZ-NOBODY"):
        res = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
            "candidate_id": candidate["id"], "scheduled_date": "2030-05-01", "scheduled_time": "10:00", "interviewer_ids": [bad]})
        assert res.status_code == 400, bad


def test_typed_names_still_work_for_interviews_without_the_picker(client, hr_manager_auth, candidate):
    iv = schedule(client, hr_manager_auth, candidate, None, interviewers="Ahmad, Siti")
    row = listed(client, hr_manager_auth, iv["id"])
    assert row["interviewers"] == "Ahmad, Siti" and row["interviewer_ids"] == []


def test_editing_replaces_the_interviewers_and_leaving_the_ids_out_keeps_them(client, hr_manager_auth, candidate, make_interviewer):
    a, _ = make_interviewer(full_name="ZZ Edit Alpha")
    b, _ = make_interviewer(full_name="ZZ Edit Beta")
    iv = schedule(client, hr_manager_auth, candidate, [a["employee_id"]])
    body = {"candidate_id": candidate["id"], "interview_type": "Panel", "scheduled_date": "2030-05-02", "scheduled_time": "11:00"}
    assert client.put(f"/api/recruitment/interviews/{iv['id']}", headers=hr_manager_auth,
                      json={**body, "interviewer_ids": [b["employee_id"]]}).status_code == 200
    row = listed(client, hr_manager_auth, iv["id"])
    assert row["interviewer_ids"] == [b["employee_id"]] and row["interviewers"] == "ZZ Edit Beta"
    # no interviewer_ids sent: the linked people are left alone
    assert client.put(f"/api/recruitment/interviews/{iv['id']}", headers=hr_manager_auth, json=body).status_code == 200
    assert listed(client, hr_manager_auth, iv["id"])["interviewer_ids"] == [b["employee_id"]]
    # an empty list clears them
    client.put(f"/api/recruitment/interviews/{iv['id']}", headers=hr_manager_auth, json={**body, "interviewer_ids": []})
    assert listed(client, hr_manager_auth, iv["id"])["interviewer_ids"] == []


def test_interviewer_gets_a_todo_then_a_score_todo_then_nothing(client, hr_manager_auth, candidate, make_interviewer):
    emp, me = make_interviewer(full_name="ZZ Todo Interviewer")
    iv = schedule(client, hr_manager_auth, candidate, [emp["employee_id"]])        # 2030: in the future

    def mine():
        return [t for t in client.get("/api/todos", headers=me).json() if t["key"] == f"interview-{iv['id']}"]

    [item] = mine()
    assert item["label"] == "Interview ZZ Interviewed Candidate — 2030-05-01 10:00"
    assert item["page"] == "my-interviews" and item["action_label"] == "View"

    client.patch(f"/api/recruitment/interviews/{iv['id']}/status", headers=hr_manager_auth, json={"status": "Completed"})
    [item] = mine()
    assert item["label"] == "Score ZZ Interviewed Candidate's interview" and item["action_label"] == "Score"

    assert client.post(f"/api/recruitment/interviews/{iv['id']}/scores", headers=me, json={"overall_score": 4}).status_code == 201
    assert mine() == []


def test_a_cancelled_interview_leaves_the_todo_and_other_people_dont_get_it(client, hr_manager_auth, candidate, make_interviewer):
    emp, me = make_interviewer(full_name="ZZ Cancel Interviewer")
    other, other_me = make_interviewer(full_name="ZZ Not Picked")
    iv = schedule(client, hr_manager_auth, candidate, [emp["employee_id"]])
    key = f"interview-{iv['id']}"
    assert any(t["key"] == key for t in client.get("/api/todos", headers=me).json())
    assert not any(t["key"] == key for t in client.get("/api/todos", headers=other_me).json())
    client.patch(f"/api/recruitment/interviews/{iv['id']}/status", headers=hr_manager_auth, json={"status": "Cancelled"})
    assert not any(t["key"] == key for t in client.get("/api/todos", headers=me).json())


def test_an_interview_whose_time_has_passed_asks_for_a_score(client, hr_manager_auth, candidate, make_interviewer):
    emp, me = make_interviewer(full_name="ZZ Past Interviewer")
    iv = schedule(client, hr_manager_auth, candidate, [emp["employee_id"]], scheduled_date="2020-01-01")
    [item] = [t for t in client.get("/api/todos", headers=me).json() if t["key"] == f"interview-{iv['id']}"]
    assert item["action_label"] == "Score"


def test_is_interviewer_flag_on_the_current_user(client, hr_manager_auth, candidate, make_interviewer):
    emp, me = make_interviewer(full_name="ZZ Flag Interviewer")
    assert client.get("/api/auth/me", headers=me).json()["is_interviewer"] is False
    schedule(client, hr_manager_auth, candidate, [emp["employee_id"]])
    assert client.get("/api/auth/me", headers=me).json()["is_interviewer"] is True


def test_my_interviews_lists_only_mine_and_the_candidate_brief_hides_personal_details(client, hr_manager_auth, candidate, make_interviewer):
    emp, me = make_interviewer(full_name="ZZ Brief Interviewer")
    _, stranger = make_interviewer(full_name="ZZ Stranger")
    iv = schedule(client, hr_manager_auth, candidate, [emp["employee_id"]])

    mine = client.get("/api/recruitment/my-interviews", headers=me).json()
    row = next(r for r in mine if r["id"] == iv["id"])
    assert row["candidate_name"] == "ZZ Interviewed Candidate" and row["location"] == "Room A" and row["scored"] is False
    assert client.get("/api/recruitment/my-interviews", headers=stranger).json() == []

    brief = client.get(f"/api/recruitment/my-interviews/{iv['id']}/candidate", headers=me)
    assert brief.status_code == 200, brief.text
    body = brief.json()
    assert body["candidate"]["full_name"] == "ZZ Interviewed Candidate" and body["candidate"]["skills"] == "Python"
    for private in ("email", "phone", "ic_number", "date_of_birth", "address", "gender", "nationality"):
        assert private not in body["candidate"], private
    [doc] = body["documents"]
    got = client.get(f"/api/recruitment/my-interviews/{iv['id']}/documents/{doc['id']}", headers=me)
    assert got.status_code == 200 and got.json()["data_url"] == PDF_URL

    # someone not picked learns nothing, not even that it exists
    for url in (f"/api/recruitment/my-interviews/{iv['id']}/candidate",
                f"/api/recruitment/my-interviews/{iv['id']}/documents/{doc['id']}"):
        assert client.get(url, headers=stranger).status_code == 404


def test_interviewers_can_score_their_own_interview_and_see_only_their_own_scorecard(client, hr_manager_auth, candidate, make_interviewer):
    a, a_me = make_interviewer(full_name="ZZ Scorer A")
    b, b_me = make_interviewer(full_name="ZZ Scorer B")
    _, stranger = make_interviewer(full_name="ZZ Scorer Stranger")
    iv = schedule(client, hr_manager_auth, candidate, [a["employee_id"], b["employee_id"]])
    url = f"/api/recruitment/interviews/{iv['id']}/scores"

    assert client.post(url, headers=stranger, json={"overall_score": 5}).status_code == 403
    assert client.get(url, headers=stranger).status_code == 403
    assert client.post(url, headers=a_me, json={"overall_score": 4, "recommendation": "Yes", "comments": "solid"}).status_code == 201
    assert client.post(url, headers=b_me, json={"overall_score": 2, "recommendation": "No", "comments": "weak"}).status_code == 201

    own = client.get(url, headers=a_me).json()
    assert [r["overall_score"] for r in own] == [4], "an interviewer must not see their colleagues' scores"
    assert len(client.get(url, headers=hr_manager_auth).json()) == 2

    row = listed(client, hr_manager_auth, iv["id"])
    assert row["avg_score"] == 3.0
    assert {(s["name"], s["scored"], s["score"]) for s in row["interviewer_status"]} == {("ZZ Scorer A", True, 4.0), ("ZZ Scorer B", True, 2.0)}
    mine = next(r for r in client.get("/api/recruitment/my-interviews", headers=a_me).json() if r["id"] == iv["id"])
    assert mine["scored"] is True and mine["my_score"] == 4.0
