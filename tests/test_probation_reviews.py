"""Integration tests for Onboarding Probation Reviews (Month 1/2/3) —
employee-scoped Performance cycles (core/performance_probation.py,
routers/onboarding.py's enable_probation_review/enable-probation-review/
probation-reviews endpoints, routers/performance.py's cycle_type
branches). See test_performance.py for the generic engine's own
coverage (standard org-wide cycles) — none of that behavior changes
here, since every branch this feature adds is guarded on
cycle_type=='probation'.
"""
from conftest import _valid_employee_payload


def test_enable_probation_review_at_start_creates_three_cycles_for_only_that_employee(
    client, employee_with_login, hr_manager_auth, make_test_employee
):
    emp, headers = employee_with_login(full_name="ZZ Probation Employee")
    other_emp = make_test_employee(full_name="ZZ Probation Bystander")  # must stay untouched

    start = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "type": "onboarding", "enable_probation_review": True,
    })
    assert start.status_code == 201, start.text
    checklist = start.json()
    assert checklist["probation_enabled"]  # stored as Postgres INTEGER 0/1, not a real bool

    reviews = client.get(f"/api/ob/checklists/{checklist['id']}/probation-reviews", headers=hr_manager_auth)
    assert reviews.status_code == 200, reviews.text
    rows = reviews.json()
    assert len(rows) == 3
    assert all(r["appraisal_status"] == "SelfReview" for r in rows)

    # Each cycle's appraisal list must contain exactly this one employee —
    # the regression this whole feature exists to prevent (accidentally
    # reusing activate_performance_cycle's org-wide fan-out).
    for r in rows:
        appraisals = client.get(f"/api/performance/appraisals?cycle_id={r['cycle_id']}", headers=hr_manager_auth).json()
        assert [a["employee_id"] for a in appraisals] == [emp["employee_id"]]

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_month2_period_start_equals_month1_period_end(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Probation Windows")
    start = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "type": "onboarding", "enable_probation_review": True,
    })
    checklist = start.json()
    rows = client.get(f"/api/ob/checklists/{checklist['id']}/probation-reviews", headers=hr_manager_auth).json()
    assert rows[0]["period_end"] == rows[1]["period_start"]
    assert rows[1]["period_end"] == rows[2]["period_start"]

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_enable_probation_review_later_and_rejects_double_enable(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Probation Later")
    start = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "type": "onboarding",
    })
    checklist = start.json()
    assert not checklist["probation_enabled"]

    reviews_before = client.get(f"/api/ob/checklists/{checklist['id']}/probation-reviews", headers=hr_manager_auth)
    assert reviews_before.json() == []

    enable = client.post(f"/api/ob/checklists/{checklist['id']}/enable-probation-review", headers=hr_manager_auth)
    assert enable.status_code == 201, enable.text
    assert enable.json()["probation_enabled"]

    reviews_after = client.get(f"/api/ob/checklists/{checklist['id']}/probation-reviews", headers=hr_manager_auth)
    assert len(reviews_after.json()) == 3

    double = client.post(f"/api/ob/checklists/{checklist['id']}/enable-probation-review", headers=hr_manager_auth)
    assert double.status_code == 400, double.text

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_probation_review_rejected_for_offboarding(client, make_test_employee, hr_manager_auth):
    emp = make_test_employee(full_name="ZZ Probation Offboarding Reject")
    res = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "type": "offboarding", "enable_probation_review": True,
    })
    assert res.status_code == 400, res.text


def test_full_self_manager_calibration_flow_computes_weighted_rating(client, employee_with_login, hr_manager_auth):
    emp, headers = employee_with_login(full_name="ZZ Probation FullFlow")
    start = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "type": "onboarding", "enable_probation_review": True,
    })
    checklist = start.json()
    month1 = client.get(f"/api/ob/checklists/{checklist['id']}/probation-reviews", headers=hr_manager_auth).json()[0]
    cycle_id, appraisal_id = month1["cycle_id"], month1["appraisal_id"]

    goals = client.get(f"/api/performance/goals?cycle_id={cycle_id}&employee_id={emp['employee_id']}", headers=headers).json()
    assert len(goals) == 6
    for g in goals:
        upd = client.put(f"/api/performance/goals/{g['id']}", headers=headers, json={"actual_value": 4})
        assert upd.status_code == 200, upd.text

    self_review = client.post(f"/api/performance/appraisals/{appraisal_id}/self-review", headers=headers,
                              json={"self_comments": "Settling in well"})
    assert self_review.status_code == 200, self_review.text
    assert self_review.json()["self_rating"] == 4.0
    assert self_review.json()["status"] == "ManagerReview"

    manager_review = client.post(f"/api/performance/appraisals/{appraisal_id}/manager-review", headers=hr_manager_auth,
                                 json={"manager_comments": "Agreed"})
    assert manager_review.status_code == 200, manager_review.text
    assert manager_review.json()["manager_rating"] == 4.0
    assert manager_review.json()["status"] == "Calibration"

    # The cycle itself must already be in Calibration (auto-opened after
    # manager review, since a cycle of one has nothing to batch-wait for)
    # — close would 400 otherwise.
    close = client.patch(f"/api/performance/cycles/{cycle_id}/close", headers=hr_manager_auth)
    assert close.status_code == 200, close.text
    assert close.json()["status"] == "Closed"

    final = client.get(f"/api/performance/appraisals/{appraisal_id}", headers=hr_manager_auth).json()
    assert final["status"] == "Finalized"
    assert final["final_rating"] == 4.0

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_hr_admin_can_view_but_not_manage_probation_cycle(client, employee_with_login, hr_manager_auth, make_test_user, test_institution):
    emp, headers = employee_with_login(full_name="ZZ Probation HrAdminView")
    start = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "type": "onboarding", "enable_probation_review": True,
    })
    checklist = start.json()
    month1 = client.get(f"/api/ob/checklists/{checklist['id']}/probation-reviews", headers=hr_manager_auth).json()[0]
    cycle_id, appraisal_id = month1["cycle_id"], month1["appraisal_id"]

    token, _ = make_test_user(role="hr_admin")
    admin_headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}

    goals = client.get(f"/api/performance/goals?cycle_id={cycle_id}&employee_id={emp['employee_id']}", headers=admin_headers)
    assert goals.status_code == 200, goals.text
    assert len(goals.json()) == 6

    appraisals = client.get(f"/api/performance/appraisals?cycle_id={cycle_id}", headers=admin_headers)
    assert appraisals.status_code == 200, appraisals.text
    assert [a["employee_id"] for a in appraisals.json()] == [emp["employee_id"]]

    single = client.get(f"/api/performance/appraisals/{appraisal_id}", headers=admin_headers)
    assert single.status_code == 200, single.text

    denied = client.post(f"/api/performance/appraisals/{appraisal_id}/manager-review", headers=admin_headers,
                         json={"manager_comments": "Should not be allowed"})
    assert denied.status_code == 403, denied.text

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_plain_employee_does_not_see_other_employees_probation_cycles_in_list(
    client, employee_with_login, hr_manager_auth
):
    """GET /api/performance/cycles has no per-row filtering for standard
    (org-wide) cycles — intentional, their name/dates aren't sensitive.
    A probation cycle's *name* embeds the employee's full name, so
    leaving it unfiltered would leak who's on probation to every
    employee in the company via the My Goals & Appraisal cycle dropdown
    (populateCycleSelect, static/js/performance.js)."""
    subject, _ = employee_with_login(full_name="ZZ Probation Privacy Subject")
    bystander, bystander_headers = employee_with_login(full_name="ZZ Probation Privacy Bystander")

    start = client.post("/api/ob/checklists", headers=hr_manager_auth, json={
        "employee_id": subject["employee_id"], "type": "onboarding", "enable_probation_review": True,
    })
    checklist = start.json()

    bystander_cycles = client.get("/api/performance/cycles", headers=bystander_headers).json()
    assert not any(c["employee_id"] == subject["employee_id"] for c in bystander_cycles), (
        "a plain employee must never see another employee's probation cycles in the cycle list"
    )

    hr_cycles = client.get("/api/performance/cycles", headers=hr_manager_auth).json()
    assert sum(1 for c in hr_cycles if c["employee_id"] == subject["employee_id"]) == 3

    client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)
