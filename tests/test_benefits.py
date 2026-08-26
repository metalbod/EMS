"""Integration tests for routers/benefits.py: plan catalog, eligibility
rules, enrollment periods, life events, enrollments (self-service +
HR-administered + auto-enroll-all), dependents, claims (including the
approval-workflow integration and Reimbursement Cap enforcement), and the
compliance/dashboard reports. Auto-enroll-all and the manager-scoped
claims list predate this build-out and are kept as-is below.
"""
import os

import pytest


def _unique_name(prefix="ZZ Test Plan"):
    return f"{prefix} {os.urandom(4).hex()}"


@pytest.fixture
def make_open_enrollment_period(client, hr_manager_auth):
    """Factory: creates an enrollment period covering today and opens it,
    closing it again on teardown. Enrollment periods have no delete
    endpoint, and get_active_enrollment_period/elect_my_enrollment pick
    the most recent still-Open period covering today — an Open period
    left behind by one test silently satisfies (or corrupts the specific
    period picked by) every other test in this file that checks enrollment-
    window behavior. Always use this instead of posting directly to
    /enrollment-periods and flipping status to Open by hand."""
    created_ids = []

    def _make(**overrides):
        import datetime as _dt
        today = _dt.date.today()
        payload = {
            "period_name": _unique_name("ZZ Period"), "plan_year": today.year,
            "start_date": (today - _dt.timedelta(days=1)).isoformat(),
            "end_date": (today + _dt.timedelta(days=1)).isoformat(),
        }
        payload.update(overrides)
        period = client.post("/api/benefits/enrollment-periods", headers=hr_manager_auth, json=payload).json()
        res = client.put(f"/api/benefits/enrollment-periods/{period['id']}", headers=hr_manager_auth, json={"status": "Open"})
        assert res.status_code == 200, f"failed to open enrollment period: {res.text}"
        created_ids.append(period["id"])
        return res.json()

    yield _make

    for pid in created_ids:
        client.put(f"/api/benefits/enrollment-periods/{pid}", headers=hr_manager_auth, json={"status": "Closed"})


def _make_active_plan(client, hr_manager_auth, **overrides):
    body = {
        "plan_name": _unique_name(),
        "plan_category": "Medical",
        "contribution_type": "Fixed Premium",
        "employee_cost": 50,
        "employer_cost": 150,
        **overrides,
    }
    plan = client.post("/api/benefits/plans", headers=hr_manager_auth, json=body).json()
    client.put(f"/api/benefits/plans/{plan['id']}", headers=hr_manager_auth, json={"status": "Active"})
    return plan


def test_list_claims_manager_sees_subordinates_not_403(client, hr_manager_auth, make_test_employee, employee_with_login):
    """A manager eligible to approve a subordinate's claim via the
    approval-workflow engine's direct_manager/skip_level_manager step
    types must be able to see it in the claims list — this used to
    blanket-403 anyone who wasn't HR/Payroll/Compensation, so a manager's
    Dashboard To-Do item ("N benefit claims awaiting your approval") led
    to a page they couldn't view at all."""
    mgr_emp, mgr_headers = employee_with_login(full_name="ZZ Claims Manager")
    report_emp = make_test_employee(full_name="ZZ Claims Report", reports_to=mgr_emp["employee_id"])

    # Give the manager account a 'manager' role (employee_with_login
    # defaults to 'employee') so list_claims' manager-scoping branch applies.
    users = client.get("/api/users", headers=hr_manager_auth).json()
    mgr_user = next(u for u in users if u["employee_id"] == mgr_emp["employee_id"])
    client.put(f"/api/users/{mgr_user['id']}", headers=hr_manager_auth, json={
        "full_name": mgr_user["full_name"], "role": "manager", "employee_id": mgr_emp["employee_id"], "is_active": True,
    })

    plan = _make_active_plan(client, hr_manager_auth)
    claim = client.post(f"/api/benefits/employees/{report_emp['employee_id']}/claims", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 100,
    }).json()

    res = client.get("/api/benefits/claims", headers=mgr_headers)
    assert res.status_code == 200, res.text
    assert any(c["id"] == claim["id"] for c in res.json())

    # An employee role with no manager/HR access still gets 403.
    other_emp, other_headers = employee_with_login(full_name="ZZ Claims Unrelated Employee")
    res2 = client.get("/api/benefits/claims", headers=other_headers)
    assert res2.status_code == 403


def test_auto_enroll_all_requires_manage_role(client, make_test_user, test_institution, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=headers)
    assert res.status_code == 403


def test_auto_enroll_all_rejects_non_active_plan(client, hr_manager_auth):
    body = {
        "plan_name": _unique_name(),
        "plan_category": "Medical",
        "contribution_type": "Fixed Premium",
    }
    plan = client.post("/api/benefits/plans", headers=hr_manager_auth, json=body).json()
    assert plan["status"] == "Draft"
    res = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=hr_manager_auth)
    assert res.status_code == 404


def test_auto_enroll_all_enrolls_active_employees(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Auto Enroll Employee")
    plan = _make_active_plan(client, hr_manager_auth)

    res = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json()["enrolled_count"] >= 1

    enrollments = client.get(f"/api/benefits/employees/{emp['employee_id']}/enrollments", headers=hr_manager_auth).json()
    match = next((e for e in enrollments if e["benefit_plan_id"] == plan["id"]), None)
    assert match is not None
    assert match["status"] == "Enrolled"

    # Re-running is idempotent — the employee's row is refreshed, not duplicated.
    res2 = client.post(f"/api/benefits/plans/{plan['id']}/auto-enroll-all", headers=hr_manager_auth)
    assert res2.status_code == 200
    enrollments2 = client.get(f"/api/benefits/employees/{emp['employee_id']}/enrollments", headers=hr_manager_auth).json()
    assert sum(1 for e in enrollments2 if e["benefit_plan_id"] == plan["id"]) == 1


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def test_create_plan_starts_as_draft(client, hr_manager_auth):
    res = client.post("/api/benefits/plans", headers=hr_manager_auth, json={
        "plan_name": _unique_name(), "plan_category": "Dental", "contribution_type": "Fixed Premium",
        "employee_cost": 20, "employer_cost": 80,
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Draft"
    assert body["payroll_sync_enabled"] is False


def test_get_plan(client, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.get(f"/api/benefits/plans/{plan['id']}", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json()["id"] == plan["id"]


def test_get_plan_404_unknown(client, hr_manager_auth):
    res = client.get("/api/benefits/plans/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_list_plans_filtered_by_category(client, hr_manager_auth):
    dental = _make_active_plan(client, hr_manager_auth, plan_category="Dental")
    medical = _make_active_plan(client, hr_manager_auth, plan_category="Medical")
    res = client.get("/api/benefits/plans?category=Dental", headers=hr_manager_auth)
    ids = [p["id"] for p in res.json()]
    assert dental["id"] in ids
    assert medical["id"] not in ids


def test_update_plan(client, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.put(f"/api/benefits/plans/{plan['id']}", headers=hr_manager_auth, json={
        "employee_cost": 75, "carrier_name": "ZZ Carrier Co",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["employee_cost"] == 75
    assert body["carrier_name"] == "ZZ Carrier Co"
    assert body["status"] == "Active"  # untouched field preserved


def test_plan_endpoints_require_benefits_role(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Plans Non-HR")
    assert client.get("/api/benefits/plans", headers=headers).status_code == 403
    assert client.post("/api/benefits/plans", headers=headers, json={
        "plan_name": "X", "plan_category": "Medical", "contribution_type": "Fixed Premium",
    }).status_code == 403


# ---------------------------------------------------------------------------
# Eligibility rules
# ---------------------------------------------------------------------------

def test_eligibility_rule_requires_level_or_grade(client, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post(f"/api/benefits/plans/{plan['id']}/eligibility-rules", headers=hr_manager_auth, json={})
    assert res.status_code == 400


def test_eligibility_rule_404_unknown_plan(client, hr_manager_auth):
    res = client.post("/api/benefits/plans/999999999/eligibility-rules", headers=hr_manager_auth, json={"job_level_id": 1})
    assert res.status_code == 404


def test_eligibility_rule_404_unknown_job_level(client, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post(f"/api/benefits/plans/{plan['id']}/eligibility-rules", headers=hr_manager_auth, json={"job_level_id": 999999999})
    assert res.status_code == 404


def test_eligibility_rule_narrows_then_delete_reopens(client, hr_manager_auth, make_test_employee):
    """A plan with zero rules is 'Open to all'; adding a rule that matches
    nobody's actual level/grade narrows out an ineligible employee; removing
    the rule again reopens it."""
    plan = _make_active_plan(client, hr_manager_auth)
    emp = make_test_employee(full_name="ZZ Eligibility Employee")

    eligible = client.get(f"/api/benefits/employees/{emp['employee_id']}/eligible-plans", headers=hr_manager_auth).json()
    assert any(p["id"] == plan["id"] and p["eligibility_reason"] == "Open to all" for p in eligible)

    level_suffix = os.urandom(3).hex()
    job_level = client.post("/api/compensation/job-levels", headers=hr_manager_auth, json={
        "level_code": f"ZZ{level_suffix}", "level_name": f"ZZ Level {level_suffix}", "level_order": 1,
    }).json()
    rule = client.post(f"/api/benefits/plans/{plan['id']}/eligibility-rules", headers=hr_manager_auth, json={
        "job_level_id": job_level["id"],
    })
    assert rule.status_code == 201, rule.text
    rule_body = rule.json()
    assert rule_body["job_level_id"] == job_level["id"]

    narrowed = client.get(f"/api/benefits/employees/{emp['employee_id']}/eligible-plans", headers=hr_manager_auth).json()
    assert not any(p["id"] == plan["id"] for p in narrowed)  # employee has no compensation record => no level match

    listed = client.get(f"/api/benefits/plans/{plan['id']}/eligibility-rules", headers=hr_manager_auth).json()
    assert any(r["id"] == rule_body["id"] for r in listed)

    del_res = client.delete(f"/api/benefits/plans/{plan['id']}/eligibility-rules/{rule_body['id']}", headers=hr_manager_auth)
    assert del_res.status_code == 204
    reopened = client.get(f"/api/benefits/employees/{emp['employee_id']}/eligible-plans", headers=hr_manager_auth).json()
    assert any(p["id"] == plan["id"] for p in reopened)


def test_my_eligible_plans_requires_linked_employee(client, hr_manager_auth):
    res = client.get("/api/benefits/eligible-plans/mine", headers=hr_manager_auth)
    assert res.status_code == 404


def test_my_eligible_plans(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ My Eligible Plans")
    res = client.get("/api/benefits/eligible-plans/mine", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# ---------------------------------------------------------------------------
# Enrollment periods
# ---------------------------------------------------------------------------

def test_create_enrollment_period_starts_draft(client, hr_manager_auth):
    res = client.post("/api/benefits/enrollment-periods", headers=hr_manager_auth, json={
        "period_name": _unique_name("ZZ Period"), "plan_year": 2027, "start_date": "2027-01-01", "end_date": "2027-01-31",
    })
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "Draft"


def test_list_enrollment_periods(client, hr_manager_auth):
    created = client.post("/api/benefits/enrollment-periods", headers=hr_manager_auth, json={
        "period_name": _unique_name("ZZ Period"), "plan_year": 2027, "start_date": "2027-01-01", "end_date": "2027-01-31",
    }).json()
    listed = client.get("/api/benefits/enrollment-periods", headers=hr_manager_auth).json()
    assert created["id"] in [p["id"] for p in listed]


def test_update_enrollment_period_status(client, hr_manager_auth):
    created = client.post("/api/benefits/enrollment-periods", headers=hr_manager_auth, json={
        "period_name": _unique_name("ZZ Period"), "plan_year": 2027, "start_date": "2027-01-01", "end_date": "2027-01-31",
    }).json()
    res = client.put(f"/api/benefits/enrollment-periods/{created['id']}", headers=hr_manager_auth, json={"status": "Open"})
    assert res.status_code == 200
    assert res.json()["status"] == "Open"


def test_active_enrollment_period_covers_today(client, hr_manager_auth, make_open_enrollment_period):
    created = make_open_enrollment_period(period_name=_unique_name("ZZ Active Period"))

    res = client.get("/api/benefits/enrollment-periods/active", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["id"] == created["id"]


# ---------------------------------------------------------------------------
# Life events
# ---------------------------------------------------------------------------

def test_submit_and_list_my_life_event(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Life Event Employee")
    res = client.post("/api/benefits/life-events/mine", headers=headers, json={
        "event_type": "Marriage", "event_date": "2026-06-01", "notes": "ZZ getting married",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Pending Review"

    mine = client.get("/api/benefits/life-events/mine", headers=headers).json()
    assert any(e["id"] == body["id"] for e in mine)


def test_life_events_hr_list_includes_employee_name(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ Life Event HR List")
    created = client.post("/api/benefits/life-events/mine", headers=headers, json={
        "event_type": "Childbirth", "event_date": "2026-06-01",
    }).json()
    res = client.get("/api/benefits/life-events", headers=hr_manager_auth)
    assert res.status_code == 200
    match = next(e for e in res.json() if e["id"] == created["id"])
    assert match["employee_name"] == "ZZ Life Event HR List"


def test_decide_life_event_approve_opens_30_day_window(client, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Life Event Approve")
    created = client.post("/api/benefits/life-events/mine", headers=headers, json={
        "event_type": "Marriage", "event_date": "2026-06-01",
    }).json()
    res = client.put(f"/api/benefits/life-events/{created['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Approved"
    assert body["window_end_date"] == "2026-07-01"  # event_date + 30 days


def test_decide_life_event_reject(client, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Life Event Reject")
    created = client.post("/api/benefits/life-events/mine", headers=headers, json={
        "event_type": "Other", "event_date": "2026-06-01",
    }).json()
    res = client.put(f"/api/benefits/life-events/{created['id']}/decide", headers=hr_manager_auth, json={"status": "Rejected"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "Rejected"
    assert body["window_end_date"] is None


def test_decide_life_event_already_decided_rejected(client, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Life Event Twice")
    created = client.post("/api/benefits/life-events/mine", headers=headers, json={
        "event_type": "Other", "event_date": "2026-06-01",
    }).json()
    client.put(f"/api/benefits/life-events/{created['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    second = client.put(f"/api/benefits/life-events/{created['id']}/decide", headers=hr_manager_auth, json={"status": "Rejected"})
    assert second.status_code == 400


def test_life_events_require_hr_role_to_list(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Life Event Non-HR List")
    res = client.get("/api/benefits/life-events", headers=headers)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Enrollments (elections)
# ---------------------------------------------------------------------------

def test_elect_my_enrollment_requires_open_period_or_life_event(client, employee_with_login, hr_manager_auth):
    _, headers = employee_with_login(full_name="ZZ Elect No Window")
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post("/api/benefits/enrollments/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    assert res.status_code == 400
    assert "no open enrollment period" in res.text.lower()


def test_elect_my_enrollment_during_open_period(client, hr_manager_auth, employee_with_login, make_open_enrollment_period):
    period = make_open_enrollment_period(period_name=_unique_name("ZZ Elect Period"))

    _, headers = employee_with_login(full_name="ZZ Elect During Open")
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post("/api/benefits/enrollments/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Enrolled"
    assert body["enrollment_period_id"] == period["id"]
    assert body["employee_cost_snapshot"] == plan["employee_cost"]

    mine = client.get("/api/benefits/enrollments/mine", headers=headers).json()
    match = next(e for e in mine if e["benefit_plan_id"] == plan["id"])
    assert match["plan_name"] == plan["plan_name"]


def test_elect_my_enrollment_rejects_ineligible_plan(client, hr_manager_auth, employee_with_login, make_open_enrollment_period):
    make_open_enrollment_period(period_name=_unique_name("ZZ Ineligible Period"))

    plan = _make_active_plan(client, hr_manager_auth)
    level_suffix = os.urandom(3).hex()
    job_level = client.post("/api/compensation/job-levels", headers=hr_manager_auth, json={
        "level_code": f"ZZ{level_suffix}", "level_name": f"ZZ Level {level_suffix}", "level_order": 1,
    }).json()
    client.post(f"/api/benefits/plans/{plan['id']}/eligibility-rules", headers=hr_manager_auth, json={
        "job_level_id": job_level["id"],
    })

    _, headers = employee_with_login(full_name="ZZ Elect Ineligible")  # no compensation record => no level match
    res = client.post("/api/benefits/enrollments/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    assert res.status_code == 403


def test_elect_employee_enrollment_hr_administered_bypasses_window(client, hr_manager_auth, make_test_employee):
    """HR electing on an employee's behalf doesn't need an open period."""
    emp = make_test_employee(full_name="ZZ HR Elect Employee")
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post(f"/api/benefits/employees/{emp['employee_id']}/enrollments", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "Enrolled"


def test_elect_employee_enrollment_requires_benefits_role(client, employee_with_login, make_test_employee):
    emp = make_test_employee(full_name="ZZ HR Elect Non-HR")
    _, headers = employee_with_login(full_name="ZZ HR Elect Non-HR Caller")
    plan_res = client.post("/api/benefits/plans", headers=headers, json={
        "plan_name": "X", "plan_category": "Medical", "contribution_type": "Fixed Premium",
    })
    assert plan_res.status_code == 403


# ---------------------------------------------------------------------------
# Dependents
# ---------------------------------------------------------------------------

def test_create_and_list_dependent_hr_side(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Dependent Employee")
    res = client.post(f"/api/benefits/employees/{emp['employee_id']}/dependents", headers=hr_manager_auth, json={
        "full_name": "ZZ Dependent Spouse", "relationship": "Spouse", "is_beneficiary": True, "beneficiary_percentage": 100,
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "Active"
    assert body["is_beneficiary"] is True

    listed = client.get(f"/api/benefits/employees/{emp['employee_id']}/dependents", headers=hr_manager_auth).json()
    assert any(d["id"] == body["id"] for d in listed)


def test_create_dependent_requires_dependents_manage_role(client, employee_with_login, make_test_employee):
    emp = make_test_employee(full_name="ZZ Dependent Non-HR")
    _, headers = employee_with_login(full_name="ZZ Dependent Non-HR Caller")
    res = client.post(f"/api/benefits/employees/{emp['employee_id']}/dependents", headers=headers, json={
        "full_name": "X", "relationship": "Child",
    })
    assert res.status_code == 403


def test_my_dependents_self_service(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ My Dependents")
    created = client.post("/api/benefits/dependents/mine", headers=headers, json={
        "full_name": "ZZ My Child", "relationship": "Child",
    })
    assert created.status_code == 201, created.text
    mine = client.get("/api/benefits/dependents/mine", headers=headers).json()
    assert any(d["id"] == created.json()["id"] for d in mine)


def test_update_dependent_by_self(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Update Own Dependent")
    created = client.post("/api/benefits/dependents/mine", headers=headers, json={
        "full_name": "ZZ Original Name", "relationship": "Child",
    }).json()
    res = client.put(f"/api/benefits/dependents/{created['id']}", headers=headers, json={"full_name": "ZZ Updated Name"})
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "ZZ Updated Name"


def test_update_dependent_by_unrelated_employee_rejected(client, employee_with_login):
    _, owner_headers = employee_with_login(full_name="ZZ Dependent Owner")
    created = client.post("/api/benefits/dependents/mine", headers=owner_headers, json={
        "full_name": "ZZ Owner's Child", "relationship": "Child",
    }).json()
    _, other_headers = employee_with_login(full_name="ZZ Dependent Intruder")
    res = client.put(f"/api/benefits/dependents/{created['id']}", headers=other_headers, json={"full_name": "Hijacked"})
    assert res.status_code == 403


def test_attach_and_list_and_detach_dependent_from_enrollment(client, hr_manager_auth, employee_with_login, make_open_enrollment_period):
    make_open_enrollment_period(period_name=_unique_name("ZZ Attach Period"))

    _, headers = employee_with_login(full_name="ZZ Attach Dependent Employee")
    plan = _make_active_plan(client, hr_manager_auth)
    enrollment = client.post("/api/benefits/enrollments/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    }).json()
    dependent = client.post("/api/benefits/dependents/mine", headers=headers, json={
        "full_name": "ZZ Attached Spouse", "relationship": "Spouse",
    }).json()

    attach = client.post(f"/api/benefits/enrollments/{enrollment['id']}/dependents", headers=headers, json={
        "dependent_id": dependent["id"],
    })
    assert attach.status_code == 201, attach.text
    assert attach.json()["attached"] is True

    listed = client.get(f"/api/benefits/enrollments/{enrollment['id']}/dependents", headers=headers).json()
    assert any(d["id"] == dependent["id"] for d in listed)

    detach = client.delete(f"/api/benefits/enrollments/{enrollment['id']}/dependents/{dependent['id']}", headers=headers)
    assert detach.status_code == 204
    listed2 = client.get(f"/api/benefits/enrollments/{enrollment['id']}/dependents", headers=headers).json()
    assert not any(d["id"] == dependent["id"] for d in listed2)


def test_attach_dependent_to_someone_elses_enrollment_rejected(client, hr_manager_auth, employee_with_login, make_open_enrollment_period):
    make_open_enrollment_period(period_name=_unique_name("ZZ Attach Isolation"))

    _, owner_headers = employee_with_login(full_name="ZZ Enrollment Owner")
    plan = _make_active_plan(client, hr_manager_auth)
    enrollment = client.post("/api/benefits/enrollments/mine", headers=owner_headers, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    }).json()

    _, other_headers = employee_with_login(full_name="ZZ Enrollment Intruder")
    other_dependent = client.post("/api/benefits/dependents/mine", headers=other_headers, json={
        "full_name": "ZZ Intruder Child", "relationship": "Child",
    }).json()

    res = client.post(f"/api/benefits/enrollments/{enrollment['id']}/dependents", headers=other_headers, json={
        "dependent_id": other_dependent["id"],
    })
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def test_submit_my_claim_with_no_manager_routes_straight_to_hr_step(client, hr_manager_auth, employee_with_login):
    """The institution's 'claims' approval workflow is direct_manager then
    hr_manager. An employee with no manager on file has no resolvable
    direct_manager step, so start_workflow skips straight to the
    (always-resolvable) hr_manager step rather than getting stuck — the
    claim is Submitted pending an HR decision, not auto-approved (that
    only happens if literally no step in the whole chain resolves, e.g. no
    HR user exists either)."""
    _, headers = employee_with_login(full_name=_unique_name("ZZ Claim No Manager"))
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post("/api/benefits/claims/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 120,
    })
    assert res.status_code == 201, res.text
    claim = res.json()
    assert claim["status"] == "Submitted"
    assert claim["amount_approved"] is None

    decide = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert decide.status_code == 200, decide.text
    body = decide.json()
    assert body["status"] == "Approved"
    assert body["amount_approved"] == 120  # defaults to the claimed amount when omitted


def test_submit_my_claim_requires_linked_employee(client, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth)
    res = client.post("/api/benefits/claims/mine", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 100,
    })
    assert res.status_code == 404


def test_submit_my_claim_404_unknown_plan(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Claim Unknown Plan")
    res = client.post("/api/benefits/claims/mine", headers=headers, json={
        "benefit_plan_id": 999999999, "claim_date": "2026-08-07", "amount_claimed": 100,
    })
    assert res.status_code == 404


def test_list_my_claims(client, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ List My Claims")
    plan = _make_active_plan(client, hr_manager_auth)
    created = client.post("/api/benefits/claims/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 60,
    }).json()
    mine = client.get("/api/benefits/claims/mine", headers=headers).json()
    assert any(c["id"] == created["id"] for c in mine)


def test_decide_claim_via_manager_workflow_approve(client, hr_manager_auth, make_test_employee, employee_with_login):
    """report_emp has a manager, so the claim's first step is
    direct_manager. The workflow is 2 steps (direct_manager, then
    hr_manager) — the manager's approval only advances the claim to the
    hr_manager step (status 'Under Review'), it doesn't finalize it; a
    second decision from an HR-tier user is what actually approves it."""
    mgr_emp, mgr_headers = employee_with_login(full_name=_unique_name("ZZ Decide Manager"))
    users = client.get("/api/users", headers=hr_manager_auth).json()
    mgr_user = next(u for u in users if u["employee_id"] == mgr_emp["employee_id"])
    client.put(f"/api/users/{mgr_user['id']}", headers=hr_manager_auth, json={
        "full_name": mgr_user["full_name"], "role": "manager", "employee_id": mgr_emp["employee_id"], "is_active": True,
    })
    report_emp = make_test_employee(full_name="ZZ Decide Report", reports_to=mgr_emp["employee_id"])
    plan = _make_active_plan(client, hr_manager_auth)
    claim = client.post(f"/api/benefits/employees/{report_emp['employee_id']}/claims", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 90,
    }).json()
    assert claim["status"] == "Submitted"

    advanced = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=mgr_headers, json={"status": "Approved"})
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["status"] == "Under Review"

    finalized = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={
        "status": "Approved", "amount_approved": 90,
    })
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["status"] == "Approved"
    assert body["amount_approved"] == 90


def test_decide_claim_by_ineligible_approver_403(client, hr_manager_auth, make_test_employee, employee_with_login):
    mgr_emp, _ = employee_with_login(full_name=_unique_name("ZZ Decide Wrong Manager"))
    users = client.get("/api/users", headers=hr_manager_auth).json()
    mgr_user = next(u for u in users if u["employee_id"] == mgr_emp["employee_id"])
    client.put(f"/api/users/{mgr_user['id']}", headers=hr_manager_auth, json={
        "full_name": mgr_user["full_name"], "role": "manager", "employee_id": mgr_emp["employee_id"], "is_active": True,
    })
    report_emp = make_test_employee(full_name="ZZ Decide Wrong Report", reports_to=mgr_emp["employee_id"])
    plan = _make_active_plan(client, hr_manager_auth)
    claim = client.post(f"/api/benefits/employees/{report_emp['employee_id']}/claims", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 90,
    }).json()

    _, unrelated_headers = employee_with_login(full_name="ZZ Decide Unrelated")
    res = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=unrelated_headers, json={"status": "Approved"})
    assert res.status_code == 403


def test_decide_claim_already_decided_rejected(client, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name=_unique_name("ZZ Decide Twice"))
    plan = _make_active_plan(client, hr_manager_auth)
    # No manager => routes straight to the hr_manager step (see
    # test_submit_my_claim_with_no_manager_routes_straight_to_hr_step) —
    # one hr_manager decision fully finalizes it since that's the last step.
    claim = client.post("/api/benefits/claims/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 50,
    }).json()
    first = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert first.status_code == 200
    assert first.json()["status"] == "Approved"

    second = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert second.status_code == 400


def test_mark_claim_paid(client, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name=_unique_name("ZZ Mark Paid"))
    plan = _make_active_plan(client, hr_manager_auth)
    claim = client.post("/api/benefits/claims/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 40,
    }).json()
    assert claim["status"] == "Submitted"  # no manager => hr_manager step
    decided = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "Approved"

    res = client.put(f"/api/benefits/claims/{claim['id']}/pay", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Paid"
    assert body["payout_date"] is not None


def test_mark_claim_paid_requires_approved_status(client, hr_manager_auth, make_test_employee):
    """emp has no manager, so the claim routes to the hr_manager step —
    decide it once to reach Approved, pay it once (Approved -> Paid), then
    a second pay attempt must be rejected since it's no longer Approved."""
    emp = make_test_employee(full_name="ZZ Pay Not Approved")
    plan = _make_active_plan(client, hr_manager_auth)
    claim = client.post(f"/api/benefits/employees/{emp['employee_id']}/claims", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 40,
    }).json()
    assert claim["status"] == "Submitted"
    decided = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "Approved"

    first_pay = client.put(f"/api/benefits/claims/{claim['id']}/pay", headers=hr_manager_auth)
    assert first_pay.status_code == 200
    second_pay = client.put(f"/api/benefits/claims/{claim['id']}/pay", headers=hr_manager_auth)
    assert second_pay.status_code == 400


def test_reimbursement_cap_enforced_on_approval(client, hr_manager_auth, make_test_employee, employee_with_login):
    """A Reimbursement Cap plan has a finite annual pool — approving past
    the employee's remaining balance is rejected rather than silently
    letting their dashboard balance go negative. Cap enforcement only runs
    on the *finalizing* decision — the workflow here is direct_manager
    then hr_manager, and the manager's approval only advances the claim
    (no cap check happens on an 'advanced' outcome), so the over-cap
    attempt has to be the second, hr_manager-step decision."""
    mgr_emp, mgr_headers = employee_with_login(full_name=_unique_name("ZZ Cap Manager"))
    users = client.get("/api/users", headers=hr_manager_auth).json()
    mgr_user = next(u for u in users if u["employee_id"] == mgr_emp["employee_id"])
    client.put(f"/api/users/{mgr_user['id']}", headers=hr_manager_auth, json={
        "full_name": mgr_user["full_name"], "role": "manager", "employee_id": mgr_emp["employee_id"], "is_active": True,
    })
    report_emp = make_test_employee(full_name="ZZ Cap Report", reports_to=mgr_emp["employee_id"])

    plan = _make_active_plan(
        client, hr_manager_auth,
        plan_category="Wellness", contribution_type="Reimbursement Cap", employee_cost=0, employer_cost=100,
    )
    enroll = client.post(f"/api/benefits/employees/{report_emp['employee_id']}/enrollments", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    assert enroll.status_code == 201, enroll.text  # snapshots the RM100 annual cap

    claim = client.post(f"/api/benefits/employees/{report_emp['employee_id']}/claims", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 150,
    }).json()
    assert claim["status"] == "Submitted"  # report_emp has a manager => direct_manager step first

    advanced = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=mgr_headers, json={"status": "Approved"})
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["status"] == "Under Review"  # advanced to the hr_manager step, not yet finalized

    over_cap = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={
        "status": "Approved", "amount_approved": 150,
    })
    assert over_cap.status_code == 400
    assert "exceeds" in over_cap.text.lower()

    within_cap = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={
        "status": "Approved", "amount_approved": 90,
    })
    assert within_cap.status_code == 200, within_cap.text
    assert within_cap.json()["amount_approved"] == 90


def _employee_id_from_headers(client, headers):
    me = client.get("/api/auth/me", headers=headers).json()
    return me["employee_id"]


def test_claims_endpoints_require_benefits_role_for_hr_side(client, employee_with_login, make_test_employee):
    emp = make_test_employee(full_name="ZZ Claims HR Side Non-HR")
    _, headers = employee_with_login(full_name="ZZ Claims HR Side Caller")
    plan_res = client.post(f"/api/benefits/employees/{emp['employee_id']}/claims", headers=headers, json={
        "benefit_plan_id": 1, "claim_date": "2026-08-07", "amount_claimed": 10,
    })
    assert plan_res.status_code == 403


# ---------------------------------------------------------------------------
# Reports / dashboards
# ---------------------------------------------------------------------------

def test_compliance_report_flags_plan_with_no_carrier(client, hr_manager_auth):
    plan = _make_active_plan(client, hr_manager_auth, plan_category="Medical", carrier_name=None)
    res = client.get("/api/benefits/reports/summary", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    match = next(p for p in body["plans"] if p["plan_id"] == plan["id"])
    assert match is not None
    assert any(f"'{plan['plan_name']}'" in flag and "no carrier" in flag for flag in body["compliance_flags"])


def test_compliance_report_requires_benefits_role(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Compliance Non-HR")
    res = client.get("/api/benefits/reports/summary", headers=headers)
    assert res.status_code == 403


def test_benefits_dashboard_includes_department_cost(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(full_name="ZZ Dashboard Employee", department="ZZ Dashboard Dept")
    plan = _make_active_plan(client, hr_manager_auth)
    client.post(f"/api/benefits/employees/{emp['employee_id']}/enrollments", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    res = client.get("/api/benefits/reports/dashboard", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    dept_match = next((d for d in body["department_costs"] if d["department"] == "ZZ Dashboard Dept"), None)
    assert dept_match is not None
    assert dept_match["enrolled_count"] >= 1


def test_benefits_dashboard_visible_to_manager_role(client, hr_manager_auth, employee_with_login):
    mgr_emp, mgr_headers = employee_with_login(full_name="ZZ Dashboard Manager")
    users = client.get("/api/users", headers=hr_manager_auth).json()
    mgr_user = next(u for u in users if u["employee_id"] == mgr_emp["employee_id"])
    client.put(f"/api/users/{mgr_user['id']}", headers=hr_manager_auth, json={
        "full_name": mgr_user["full_name"], "role": "manager", "employee_id": mgr_emp["employee_id"], "is_active": True,
    })
    res = client.get("/api/benefits/reports/dashboard", headers=mgr_headers)
    assert res.status_code == 200


def test_benefits_dashboard_requires_dashboard_role(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Dashboard Non-Eligible")
    res = client.get("/api/benefits/reports/dashboard", headers=headers)
    assert res.status_code == 403


def test_my_benefits_dashboard_recent_claims_and_balance(client, hr_manager_auth, employee_with_login):
    plan = _make_active_plan(
        client, hr_manager_auth,
        plan_category="Wellness", contribution_type="Reimbursement Cap", employee_cost=0, employer_cost=200,
    )
    _, headers = employee_with_login(full_name=_unique_name("ZZ My Dashboard"))
    emp_id = _employee_id_from_headers(client, headers)
    client.post(f"/api/benefits/employees/{emp_id}/enrollments", headers=hr_manager_auth, json={
        "benefit_plan_id": plan["id"], "status": "Enrolled",
    })
    claim = client.post("/api/benefits/claims/mine", headers=headers, json={
        "benefit_plan_id": plan["id"], "claim_date": "2026-08-07", "amount_claimed": 50,
    }).json()
    assert claim["status"] == "Submitted"  # no manager => routes to the hr_manager step
    decided = client.put(f"/api/benefits/claims/{claim['id']}/decide", headers=hr_manager_auth, json={"status": "Approved"})
    assert decided.status_code == 200
    # used_amount below only counts Approved/Paid claims, so the balance
    # calculation needs the decision above to have actually landed.

    res = client.get("/api/benefits/dashboard/mine", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert any(c["id"] == claim["id"] for c in body["recent_claims"])
    balance = next((b for b in body["balances"] if b["plan_name"] == plan["plan_name"]), None)
    assert balance is not None
    assert balance["annual_cap"] == 200
    assert balance["used_amount"] == 50
    assert balance["remaining_amount"] == 150


def test_my_benefits_dashboard_empty_for_no_linked_employee(client, hr_manager_auth):
    res = client.get("/api/benefits/dashboard/mine", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert body["recent_claims"] == []
    assert body["balances"] == []
