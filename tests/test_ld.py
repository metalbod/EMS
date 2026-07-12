"""Integration tests for routers/ld.py."""
import os

import pytest


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    """A real employee record with a linked login (role=employee)."""
    emp = make_test_employee()
    username = f"zztld_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ LD Test Employee",
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


def _unique_title(prefix="ZZ Test Course"):
    return f"{prefix} {os.urandom(4).hex()}"


@pytest.fixture
def free_course(client, hr_manager_auth):
    res = client.post("/api/ld/courses", headers=hr_manager_auth,
                       json={"title": _unique_title(), "category": "professional_development", "cost": 0.0})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def paid_course(client, hr_manager_auth):
    res = client.post("/api/ld/courses", headers=hr_manager_auth,
                       json={"title": _unique_title("ZZ Paid Course"), "category": "certification", "cost": 500.0})
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------
def test_list_courses_requires_auth(client):
    res = client.get("/api/ld/courses")
    assert res.status_code in (401, 403)


def test_create_course_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/ld/courses", headers=headers, json={"title": _unique_title()})
    assert res.status_code == 403


def test_create_course_invalid_category_returns_400(client, hr_manager_auth):
    res = client.post("/api/ld/courses", headers=hr_manager_auth,
                       json={"title": _unique_title(), "category": "bogus"})
    assert res.status_code == 400


def test_create_course_success_and_appears_in_list(client, hr_manager_auth, free_course):
    listing = client.get("/api/ld/courses", headers=hr_manager_auth,
                          params={"category": "professional_development"})
    assert listing.status_code == 200
    assert any(c["id"] == free_course["id"] for c in listing.json())


def test_update_course_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/ld/courses/999999999", headers=hr_manager_auth,
                      json={"title": "ZZ Ghost", "category": "professional_development"})
    assert res.status_code == 404


def test_update_course_success(client, hr_manager_auth, free_course):
    res = client.put(f"/api/ld/courses/{free_course['id']}", headers=hr_manager_auth,
                      json={"title": "ZZ Renamed Course", "category": "mandatory", "cost": 10.0})
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "ZZ Renamed Course"


def test_delete_course_soft_deletes(client, hr_manager_auth, free_course):
    res = client.delete(f"/api/ld/courses/{free_course['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listing = client.get("/api/ld/courses", headers=hr_manager_auth)
    assert all(c["id"] != free_course["id"] for c in listing.json())


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------
def test_create_enrollment_free_course_goes_in_progress(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    res = client.post("/api/ld/enrollments", headers=emp_headers,
                       json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "In Progress"


def test_create_enrollment_paid_course_goes_pending_approval(client, hr_manager_auth, employee_with_user, paid_course):
    emp, emp_headers = employee_with_user
    res = client.post("/api/ld/enrollments", headers=emp_headers,
                       json={"employee_id": emp["employee_id"], "course_id": paid_course["id"]})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "Pending Approval"


def test_employee_cannot_enroll_someone_else(client, employee_with_user, make_test_employee, free_course):
    emp, emp_headers = employee_with_user
    other_emp = make_test_employee()
    res = client.post("/api/ld/enrollments", headers=emp_headers,
                       json={"employee_id": other_emp["employee_id"], "course_id": free_course["id"]})
    assert res.status_code == 403


def test_create_enrollment_unknown_course_returns_404(client, employee_with_user):
    emp, emp_headers = employee_with_user
    res = client.post("/api/ld/enrollments", headers=emp_headers,
                       json={"employee_id": emp["employee_id"], "course_id": 999999999})
    assert res.status_code == 404


def test_create_enrollment_duplicate_active_returns_400(client, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    res1 = client.post("/api/ld/enrollments", headers=emp_headers,
                        json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    assert res1.status_code == 201, res1.text
    res2 = client.post("/api/ld/enrollments", headers=emp_headers,
                        json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    assert res2.status_code == 400


def test_approve_enrollment_requires_manage_or_manager_role(client, employee_with_user, paid_course):
    emp, emp_headers = employee_with_user
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": paid_course["id"]}).json()
    res = client.patch(f"/api/ld/enrollments/{enroll['id']}/status", headers=emp_headers,
                        json={"status": "Approved"})
    assert res.status_code == 403


def test_approve_enrollment_success(client, hr_manager_auth, employee_with_user, paid_course):
    emp, emp_headers = employee_with_user
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": paid_course["id"]}).json()
    res = client.patch(f"/api/ld/enrollments/{enroll['id']}/status", headers=hr_manager_auth,
                        json={"status": "Approved"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "In Progress"


def test_reject_enrollment_success(client, hr_manager_auth, employee_with_user, paid_course):
    emp, emp_headers = employee_with_user
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": paid_course["id"]}).json()
    res = client.patch(f"/api/ld/enrollments/{enroll['id']}/status", headers=hr_manager_auth,
                        json={"status": "Rejected"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Rejected"


def test_update_enrollment_invalid_status_returns_400(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": free_course["id"]}).json()
    res = client.patch(f"/api/ld/enrollments/{enroll['id']}/status", headers=hr_manager_auth,
                        json={"status": "Bogus"})
    assert res.status_code == 400


def test_update_enrollment_not_found_returns_404(client, hr_manager_auth):
    res = client.patch("/api/ld/enrollments/999999999/status", headers=hr_manager_auth,
                        json={"status": "Approved"})
    assert res.status_code == 404


def test_mark_enrollment_completed_by_own_employee(client, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": free_course["id"]}).json()
    res = client.patch(f"/api/ld/enrollments/{enroll['id']}/status", headers=emp_headers,
                        json={"status": "Completed"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Completed"


def test_mark_enrollment_completed_denied_for_other_employee(client, employee_with_user, make_test_employee, free_course, hr_manager_auth):
    other_emp = make_test_employee()
    enroll_res = client.post("/api/ld/enrollments", headers=hr_manager_auth,
                              json={"employee_id": other_emp["employee_id"], "course_id": free_course["id"]})
    assert enroll_res.status_code == 201, enroll_res.text
    enroll = enroll_res.json()

    _, emp_headers = employee_with_user
    res = client.patch(f"/api/ld/enrollments/{enroll['id']}/status", headers=emp_headers,
                        json={"status": "Completed"})
    assert res.status_code == 403


def test_list_enrollments_employee_sees_only_own(client, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    client.post("/api/ld/enrollments", headers=emp_headers,
                json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    res = client.get("/api/ld/enrollments", headers=emp_headers)
    assert res.status_code == 200
    assert all(e["employee_id"] == emp["employee_id"] for e in res.json())


def test_ld_history_requires_manage_role(client, employee_with_user):
    emp, emp_headers = employee_with_user
    res = client.get(f"/api/employees/{emp['employee_id']}/ld-history", headers=emp_headers)
    assert res.status_code == 403


def test_ld_history_records_enrollment(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    client.post("/api/ld/enrollments", headers=emp_headers,
                json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    res = client.get(f"/api/employees/{emp['employee_id']}/ld-history", headers=hr_manager_auth)
    assert res.status_code == 200
    assert any(h["action"] == "Enrolled" for h in res.json())


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------
def _valid_quiz_payload(**overrides):
    payload = {
        "title": "ZZ Test Quiz",
        "pass_threshold": 50,
        "max_attempts": 3,
        "questions": [{
            "question_text": "2 + 2 = ?",
            "question_type": "single",
            "options": [
                {"text": "3", "is_correct": False},
                {"text": "4", "is_correct": True},
            ],
        }],
    }
    payload.update(overrides)
    return payload


def test_upsert_quiz_requires_manage_role(client, employee_with_user, free_course):
    _, emp_headers = employee_with_user
    res = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=emp_headers,
                      json=_valid_quiz_payload())
    assert res.status_code == 403


def test_upsert_quiz_no_questions_returns_400(client, hr_manager_auth, free_course):
    res = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                      json=_valid_quiz_payload(questions=[]))
    assert res.status_code == 400


def test_upsert_quiz_no_correct_answer_returns_400(client, hr_manager_auth, free_course):
    payload = _valid_quiz_payload()
    payload["questions"][0]["options"] = [{"text": "3", "is_correct": False}, {"text": "4", "is_correct": False}]
    res = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth, json=payload)
    assert res.status_code == 400


def test_upsert_quiz_single_type_multiple_correct_returns_400(client, hr_manager_auth, free_course):
    payload = _valid_quiz_payload()
    payload["questions"][0]["options"] = [{"text": "3", "is_correct": True}, {"text": "4", "is_correct": True}]
    res = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth, json=payload)
    assert res.status_code == 400


def test_upsert_quiz_success_and_hides_correct_answers_for_take_view(client, hr_manager_auth, employee_with_user, free_course):
    res = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                      json=_valid_quiz_payload())
    assert res.status_code == 200, res.text

    _, emp_headers = employee_with_user
    take = client.get(f"/api/ld/courses/{free_course['id']}/quiz", headers=emp_headers)
    assert take.status_code == 200
    for q in take.json()["questions"]:
        for o in q["options"]:
            assert "is_correct" not in o

    manage = client.get(f"/api/ld/courses/{free_course['id']}/quiz/manage", headers=hr_manager_auth)
    assert manage.status_code == 200
    assert any(o.get("is_correct") for q in manage.json()["questions"] for o in q["options"])


def test_get_quiz_not_found_returns_404(client, hr_manager_auth, free_course):
    res = client.get(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth)
    assert res.status_code == 404


def test_delete_quiz_success(client, hr_manager_auth, free_course):
    client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth, json=_valid_quiz_payload())
    res = client.delete(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth)
    assert res.status_code == 204
    get_res = client.get(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth)
    assert get_res.status_code == 404


def test_submit_quiz_attempt_pass_completes_enrollment(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    quiz = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                       json=_valid_quiz_payload()).json()
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": free_course["id"]}).json()
    question = quiz["questions"][0]
    correct_option = next(o for o in question["options"] if o["is_correct"])

    res = client.post(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers,
                       json={"answers": {str(question["id"]): [correct_option["id"]]}})
    assert res.status_code == 201, res.text
    result = res.json()
    assert result["passed"] is True
    assert result["score"] == 100.0

    enroll_check = client.get("/api/ld/enrollments", headers=emp_headers)
    updated = next(e for e in enroll_check.json() if e["id"] == enroll["id"])
    assert updated["status"] == "Completed"


def test_submit_quiz_attempt_fail_does_not_complete(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    quiz = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                       json=_valid_quiz_payload()).json()
    client.post("/api/ld/enrollments", headers=emp_headers,
                json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    question = quiz["questions"][0]
    wrong_option = next(o for o in question["options"] if not o["is_correct"])

    res = client.post(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers,
                       json={"answers": {str(question["id"]): [wrong_option["id"]]}})
    assert res.status_code == 201, res.text
    assert res.json()["passed"] is False


def test_submit_quiz_attempt_without_enrollment_returns_403(client, hr_manager_auth, employee_with_user, free_course):
    _, emp_headers = employee_with_user
    quiz = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                       json=_valid_quiz_payload()).json()
    question = quiz["questions"][0]
    res = client.post(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers,
                       json={"answers": {str(question["id"]): [question["options"][0]["id"]]}})
    assert res.status_code == 403


def test_quiz_attempt_max_attempts_enforced(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    quiz = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                       json=_valid_quiz_payload(max_attempts=1)).json()
    client.post("/api/ld/enrollments", headers=emp_headers,
                json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    question = quiz["questions"][0]
    wrong_option = next(o for o in question["options"] if not o["is_correct"])

    first = client.post(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers,
                         json={"answers": {str(question["id"]): [wrong_option["id"]]}})
    assert first.status_code == 201, first.text

    second = client.post(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers,
                          json={"answers": {str(question["id"]): [wrong_option["id"]]}})
    assert second.status_code == 400


def test_list_quiz_attempts_employee_sees_only_own(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    quiz = client.put(f"/api/ld/courses/{free_course['id']}/quiz", headers=hr_manager_auth,
                       json=_valid_quiz_payload()).json()
    client.post("/api/ld/enrollments", headers=emp_headers,
                json={"employee_id": emp["employee_id"], "course_id": free_course["id"]})
    question = quiz["questions"][0]
    client.post(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers,
                json={"answers": {str(question["id"]): [question["options"][0]["id"]]}})

    res = client.get(f"/api/ld/quizzes/{quiz['id']}/attempts", headers=emp_headers)
    assert res.status_code == 200
    assert all(a["employee_id"] == emp["employee_id"] for a in res.json())


# ---------------------------------------------------------------------------
# Course Modules
# ---------------------------------------------------------------------------
def test_replace_modules_requires_manage_role(client, employee_with_user, free_course):
    _, emp_headers = employee_with_user
    res = client.put(f"/api/ld/courses/{free_course['id']}/modules", headers=emp_headers,
                      json={"modules": [{"title": "ZZ Module 1", "content_type": "text", "content": "hello"}]})
    assert res.status_code == 403


def test_replace_modules_invalid_content_type_returns_400(client, hr_manager_auth, free_course):
    res = client.put(f"/api/ld/courses/{free_course['id']}/modules", headers=hr_manager_auth,
                      json={"modules": [{"title": "ZZ Module 1", "content_type": "bogus", "content": "x"}]})
    assert res.status_code == 400


def test_replace_modules_course_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/ld/courses/999999999/modules", headers=hr_manager_auth,
                      json={"modules": [{"title": "ZZ Module 1", "content_type": "text", "content": "x"}]})
    assert res.status_code == 404


def test_replace_and_list_modules(client, hr_manager_auth, free_course):
    res = client.put(f"/api/ld/courses/{free_course['id']}/modules", headers=hr_manager_auth, json={
        "modules": [
            {"title": "ZZ Module 1", "content_type": "text", "content": "hello"},
            {"title": "ZZ Module 2", "content_type": "video", "content": "https://example.com/vid.mp4"},
        ]
    })
    assert res.status_code == 200, res.text
    assert len(res.json()) == 2

    listing = client.get(f"/api/ld/courses/{free_course['id']}/modules", headers=hr_manager_auth)
    assert listing.status_code == 200
    assert len(listing.json()) == 2


def test_mark_module_viewed_idempotent(client, hr_manager_auth, employee_with_user, free_course):
    emp, emp_headers = employee_with_user
    modules = client.put(f"/api/ld/courses/{free_course['id']}/modules", headers=hr_manager_auth, json={
        "modules": [{"title": "ZZ Module 1", "content_type": "text", "content": "hello"}]
    }).json()
    module_id = modules[0]["id"]
    enroll = client.post("/api/ld/enrollments", headers=emp_headers,
                          json={"employee_id": emp["employee_id"], "course_id": free_course["id"]}).json()

    first = client.post(f"/api/ld/enrollments/{enroll['id']}/modules/{module_id}/viewed", headers=emp_headers)
    assert first.status_code == 201, first.text
    second = client.post(f"/api/ld/enrollments/{enroll['id']}/modules/{module_id}/viewed", headers=emp_headers)
    assert second.status_code == 201, second.text

    listing = client.get(f"/api/ld/courses/{free_course['id']}/modules", headers=emp_headers,
                          params={"enrollment_id": enroll["id"]})
    assert listing.status_code == 200
    assert listing.json()[0]["viewed"] is True


def test_mark_module_viewed_denied_for_other_employee(client, hr_manager_auth, employee_with_user, make_test_employee, free_course):
    other_emp = make_test_employee()
    modules = client.put(f"/api/ld/courses/{free_course['id']}/modules", headers=hr_manager_auth, json={
        "modules": [{"title": "ZZ Module 1", "content_type": "text", "content": "hello"}]
    }).json()
    module_id = modules[0]["id"]
    enroll = client.post("/api/ld/enrollments", headers=hr_manager_auth,
                          json={"employee_id": other_emp["employee_id"], "course_id": free_course["id"]}).json()

    _, emp_headers = employee_with_user
    res = client.post(f"/api/ld/enrollments/{enroll['id']}/modules/{module_id}/viewed", headers=emp_headers)
    assert res.status_code == 403
