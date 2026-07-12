"""Integration tests for routers/performance.py."""
import itertools
import os
import random
from datetime import date, timedelta

import pytest

# A day-granularity random offset (not just a small year range) gives a vastly
# larger no-collision space — performance_cycles are never deleted, so a small
# fixed set of (year, month) combinations would eventually collide after
# enough repeated full-suite runs (this exact failure mode hit test_payroll.py
# elsewhere in this session).
_base_date = date(2200, 1, 1) + timedelta(days=random.randint(0, 2_000_000))
_period_counter = itertools.count()


def _period(month=None):
    """A unique 4-week period far in the future. `month` is accepted-but-ignored
    for call-site readability; periods are actually spaced out via a counter
    from a randomized base date so no two calls collide, regardless of how
    many fixtures/tests request one."""
    base = _base_date + timedelta(days=35 * next(_period_counter))
    start = base.isoformat()
    end = (base + timedelta(days=27)).isoformat()
    return start, end


@pytest.fixture(scope="module", autouse=True)
def _deactivate_stray_active_employees(superadmin_token, test_institution):
    """activate_performance_cycle snapshots EVERY Active employee in the
    institution into new appraisals, and close_performance_cycle requires all
    of a cycle's appraisals to reach Calibration/Finalized. Employees left
    Active by an interrupted test run elsewhere (e.g. a killed pytest process
    whose make_test_employee teardown never ran) would otherwise get swept
    into every cycle this file activates and permanently block cycle-close
    assertions. One-time sweep at module start so only employees created
    within this file's own tests are Active when a cycle is activated."""
    import main as app_module
    from fastapi.testclient import TestClient
    c = TestClient(app_module.app)
    headers = {"Authorization": f"Bearer {superadmin_token}", "X-Institution-Id": str(test_institution["id"])}
    listing = c.get("/api/employees", headers=headers, params={"status": "Active"})
    if listing.status_code == 200:
        for emp in listing.json():
            c.patch(f"/api/employees/{emp['employee_id']}/status", headers=headers, json={"status": "Inactive"})
    yield


@pytest.fixture
def employee_with_user(make_test_employee, hr_manager_auth, client, test_institution):
    """A real employee record with a linked login (role=employee)."""
    emp = make_test_employee()
    username = f"zztperf_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Performance Test Employee",
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


@pytest.fixture
def manager_with_subordinate(make_test_employee, hr_manager_auth, client, test_institution):
    """A manager employee + linked login, and a subordinate employee reporting to them."""
    manager_emp = make_test_employee()
    sub_emp = make_test_employee(reports_to=manager_emp["employee_id"])

    username = f"zztperfmgr_{manager_emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Performance Test Manager",
        "password": password, "role": "manager", "employee_id": manager_emp["employee_id"],
    })
    assert res.status_code == 201, f"failed to create manager-linked user: {res.text}"
    user_id = res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    yield manager_emp, headers, sub_emp

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


@pytest.fixture
def active_cycle(client, hr_manager_auth):
    """A Draft cycle already moved to Active (so goals can be created against it)."""
    start, end = _period()
    create = client.post("/api/performance/cycles", headers=hr_manager_auth,
                          json={"name": f"ZZ Cycle {os.urandom(4).hex()}", "period_start": start, "period_end": end})
    assert create.status_code == 201, create.text
    cycle = create.json()
    activate = client.patch(f"/api/performance/cycles/{cycle['id']}/activate", headers=hr_manager_auth)
    assert activate.status_code == 200, activate.text
    return activate.json()


@pytest.fixture
def active_cycle_with_other_employee(client, hr_manager_auth, make_test_employee):
    """Like active_cycle, but with a second employee created (and thus already
    Active) BEFORE the cycle is activated, so that employee's appraisal is
    guaranteed to be snapshotted into the cycle too. Creating the "other"
    employee inside a test body instead would happen after this fixture's
    setup already ran, missing the cycle's activation snapshot entirely."""
    other_emp = make_test_employee()
    start, end = _period()
    create = client.post("/api/performance/cycles", headers=hr_manager_auth,
                          json={"name": f"ZZ Cycle {os.urandom(4).hex()}", "period_start": start, "period_end": end})
    assert create.status_code == 201, create.text
    cycle = create.json()
    activate = client.patch(f"/api/performance/cycles/{cycle['id']}/activate", headers=hr_manager_auth)
    assert activate.status_code == 200, activate.text
    return activate.json(), other_emp


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------
def test_list_cycles_requires_auth(client):
    res = client.get("/api/performance/cycles")
    assert res.status_code in (401, 403)


def test_superadmin_gets_empty_cycles(client, superadmin_headers):
    res = client.get("/api/performance/cycles", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_create_cycle_requires_manage_role(client, employee_with_user):
    _, emp_headers = employee_with_user
    start, end = _period(1)
    res = client.post("/api/performance/cycles", headers=emp_headers,
                       json={"name": "ZZ Nope", "period_start": start, "period_end": end})
    assert res.status_code == 403


def test_create_cycle_end_before_start_returns_400(client, hr_manager_auth):
    res = client.post("/api/performance/cycles", headers=hr_manager_auth,
                       json={"name": "ZZ Bad Cycle", "period_start": "2200-02-01", "period_end": "2200-01-01"})
    assert res.status_code == 400


def test_activate_cycle_creates_appraisals_for_active_employees(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    start, end = _period(2)
    create = client.post("/api/performance/cycles", headers=hr_manager_auth,
                          json={"name": f"ZZ Cycle {os.urandom(4).hex()}", "period_start": start, "period_end": end})
    cycle = create.json()
    res = client.patch(f"/api/performance/cycles/{cycle['id']}/activate", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Active"

    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth, params={"cycle_id": cycle["id"]})
    assert appraisals.status_code == 200
    assert any(a["employee_id"] == emp["employee_id"] and a["status"] == "SelfReview" for a in appraisals.json())


def test_activate_already_active_cycle_returns_400(client, hr_manager_auth, active_cycle):
    res = client.patch(f"/api/performance/cycles/{active_cycle['id']}/activate", headers=hr_manager_auth)
    assert res.status_code == 400


def test_activate_cycle_not_found_returns_404(client, hr_manager_auth):
    res = client.patch("/api/performance/cycles/999999999/activate", headers=hr_manager_auth)
    assert res.status_code == 404


def test_open_calibration_requires_active_status(client, hr_manager_auth):
    start, end = _period(3)
    create = client.post("/api/performance/cycles", headers=hr_manager_auth,
                          json={"name": f"ZZ Draft Cycle {os.urandom(4).hex()}", "period_start": start, "period_end": end})
    cycle = create.json()
    res = client.patch(f"/api/performance/cycles/{cycle['id']}/open-calibration", headers=hr_manager_auth)
    assert res.status_code == 400


def test_close_cycle_requires_calibration_status(client, hr_manager_auth, active_cycle):
    res = client.patch(f"/api/performance/cycles/{active_cycle['id']}/close", headers=hr_manager_auth)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
def test_create_goal_requires_active_cycle(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    start, end = _period(4)
    create = client.post("/api/performance/cycles", headers=hr_manager_auth,
                          json={"name": f"ZZ Draft {os.urandom(4).hex()}", "period_start": start, "period_end": end})
    cycle = create.json()
    res = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI", "title": "ZZ Goal", "weight": 50,
    })
    assert res.status_code == 400


def test_create_goal_invalid_goal_type_returns_422(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "Bogus", "title": "ZZ Goal", "weight": 50,
    })
    assert res.status_code == 422


def test_create_goal_weight_out_of_range_returns_422(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    res = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI", "title": "ZZ Goal", "weight": 150,
    })
    assert res.status_code == 422


def test_employee_can_create_own_goal(client, employee_with_user, active_cycle):
    emp, emp_headers = employee_with_user
    res = client.post("/api/performance/goals", headers=emp_headers, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI",
        "title": "ZZ Sales Target", "weight": 100, "target_value": 100, "actual_value": 90, "unit": "units",
    })
    assert res.status_code == 201, res.text
    assert res.json()["title"] == "ZZ Sales Target"  # create_goal returns the raw row; score is a list-endpoint enrichment


def test_employee_cannot_create_goal_for_someone_else(client, employee_with_user, make_test_employee, active_cycle):
    _, emp_headers = employee_with_user
    other_emp = make_test_employee()
    res = client.post("/api/performance/goals", headers=emp_headers, json={
        "cycle_id": active_cycle["id"], "employee_id": other_emp["employee_id"], "goal_type": "KPI", "title": "ZZ Goal", "weight": 50,
    })
    assert res.status_code == 403


def test_list_goals_kpi_score_computed(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI",
        "title": "ZZ KPI Goal", "weight": 100, "target_value": 100, "actual_value": 100,
    })
    res = client.get("/api/performance/goals", headers=hr_manager_auth,
                      params={"cycle_id": active_cycle["id"], "employee_id": emp["employee_id"]})
    assert res.status_code == 200
    goals = res.json()
    assert len(goals) == 1
    assert goals[0]["score"] == 4.0  # ratio 1.0 -> bucket 4


def test_update_goal_success(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    goal = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI", "title": "ZZ Goal", "weight": 50,
    }).json()
    res = client.put(f"/api/performance/goals/{goal['id']}", headers=hr_manager_auth, json={"title": "ZZ Renamed Goal"})
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "ZZ Renamed Goal"


def test_update_goal_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/performance/goals/999999999", headers=hr_manager_auth, json={"title": "ZZ Ghost"})
    assert res.status_code == 404


def test_delete_goal_success(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    goal = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI", "title": "ZZ Goal", "weight": 50,
    }).json()
    res = client.delete(f"/api/performance/goals/{goal['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listing = client.get("/api/performance/goals", headers=hr_manager_auth,
                          params={"cycle_id": active_cycle["id"], "employee_id": emp["employee_id"]})
    assert all(g["id"] != goal["id"] for g in listing.json())


# ---------------------------------------------------------------------------
# OKR Key Results
# ---------------------------------------------------------------------------
def test_add_key_result_requires_okr_goal(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    goal = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI", "title": "ZZ KPI Goal", "weight": 50,
    }).json()
    res = client.post(f"/api/performance/goals/{goal['id']}/key-results", headers=hr_manager_auth,
                       json={"description": "ZZ KR", "target_value": 100, "actual_value": 0})
    assert res.status_code == 400


def test_okr_goal_score_averages_key_results(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    goal = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "OKR",
        "title": "ZZ OKR Goal", "weight": 100,
    }).json()
    client.post(f"/api/performance/goals/{goal['id']}/key-results", headers=hr_manager_auth,
                json={"description": "KR1", "target_value": 100, "actual_value": 100})
    client.post(f"/api/performance/goals/{goal['id']}/key-results", headers=hr_manager_auth,
                json={"description": "KR2", "target_value": 100, "actual_value": 100})

    res = client.get("/api/performance/goals", headers=hr_manager_auth,
                      params={"cycle_id": active_cycle["id"], "employee_id": emp["employee_id"]})
    okr_goal = next(g for g in res.json() if g["id"] == goal["id"])
    assert len(okr_goal["key_results"]) == 2
    assert okr_goal["score"] == 4.0  # ratio 1.0 average -> bucket 4


def test_update_key_result_success(client, hr_manager_auth, active_cycle, make_test_employee):
    emp = make_test_employee()
    goal = client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "OKR", "title": "ZZ OKR", "weight": 100,
    }).json()
    kr = client.post(f"/api/performance/goals/{goal['id']}/key-results", headers=hr_manager_auth,
                      json={"description": "KR1", "target_value": 100, "actual_value": 0}).json()
    res = client.put(f"/api/performance/key-results/{kr['id']}", headers=hr_manager_auth,
                      json={"description": "KR1 Updated", "target_value": 100, "actual_value": 50})
    assert res.status_code == 200, res.text
    assert res.json()["actual_value"] == 50


def test_delete_key_result_not_found_returns_404(client, hr_manager_auth):
    res = client.delete("/api/performance/key-results/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Appraisal workflow (Self -> Manager -> Calibration -> Finalized)
# ---------------------------------------------------------------------------
def test_self_review_success_moves_to_manager_review(client, hr_manager_auth, employee_with_user, active_cycle):
    emp, emp_headers = employee_with_user
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    appraisal = next(a for a in appraisals if a["employee_id"] == emp["employee_id"])

    res = client.post(f"/api/performance/appraisals/{appraisal['id']}/self-review", headers=emp_headers,
                       json={"self_comments": "ZZ self comment"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ManagerReview"


def test_self_review_denied_for_other_employee(client, employee_with_user, hr_manager_auth, active_cycle_with_other_employee):
    cycle, other_emp = active_cycle_with_other_employee
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": cycle["id"]}).json()
    other_appraisal = next(a for a in appraisals if a["employee_id"] == other_emp["employee_id"])

    _, emp_headers = employee_with_user
    res = client.post(f"/api/performance/appraisals/{other_appraisal['id']}/self-review", headers=emp_headers,
                       json={"self_comments": "ZZ sneaky"})
    assert res.status_code == 403


def test_self_review_not_found_returns_404(client, employee_with_user):
    _, emp_headers = employee_with_user
    res = client.post("/api/performance/appraisals/999999999/self-review", headers=emp_headers, json={})
    assert res.status_code == 404


def test_manager_review_cannot_review_own_appraisal(client, hr_manager_auth, manager_with_subordinate, active_cycle):
    manager_emp, manager_headers, _ = manager_with_subordinate
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    own_appraisal = next((a for a in appraisals if a["employee_id"] == manager_emp["employee_id"]), None)
    if own_appraisal is None:
        pytest.skip("manager's own appraisal not present in this cycle")

    res = client.post(f"/api/performance/appraisals/{own_appraisal['id']}/manager-review", headers=manager_headers, json={})
    assert res.status_code == 403


def test_manager_review_denied_for_non_subordinate(client, hr_manager_auth, manager_with_subordinate, active_cycle_with_other_employee):
    _, manager_headers, _ = manager_with_subordinate
    cycle, unrelated_emp = active_cycle_with_other_employee
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": cycle["id"]}).json()
    unrelated_appraisal = next(a for a in appraisals if a["employee_id"] == unrelated_emp["employee_id"])

    res = client.post(f"/api/performance/appraisals/{unrelated_appraisal['id']}/manager-review",
                       headers=manager_headers, json={})
    assert res.status_code == 403


def test_manager_review_wrong_status_returns_400(client, hr_manager_auth, manager_with_subordinate, active_cycle):
    _, manager_headers, sub_emp = manager_with_subordinate
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    sub_appraisal = next(a for a in appraisals if a["employee_id"] == sub_emp["employee_id"])
    assert sub_appraisal["status"] == "SelfReview"

    res = client.post(f"/api/performance/appraisals/{sub_appraisal['id']}/manager-review", headers=manager_headers, json={})
    assert res.status_code == 400


def test_calibrate_requires_calibration_status(client, hr_manager_auth, employee_with_user, active_cycle):
    emp, emp_headers = employee_with_user
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    appraisal = next(a for a in appraisals if a["employee_id"] == emp["employee_id"])
    res = client.post(f"/api/performance/appraisals/{appraisal['id']}/calibrate", headers=hr_manager_auth,
                       json={"calibrated_rating": 4.5})
    assert res.status_code == 400


def test_calibrate_requires_manage_role(client, employee_with_user):
    _, emp_headers = employee_with_user
    res = client.post("/api/performance/appraisals/1/calibrate", headers=emp_headers, json={"calibrated_rating": 4.0})
    assert res.status_code == 403


def test_end_to_end_self_manager_calibrate_close(client, hr_manager_auth, employee_with_user, active_cycle):
    emp, emp_headers = employee_with_user
    client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI",
        "title": "ZZ E2E Goal", "weight": 100, "target_value": 100, "actual_value": 100,
    })
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    appraisal = next(a for a in appraisals if a["employee_id"] == emp["employee_id"])

    self_review = client.post(f"/api/performance/appraisals/{appraisal['id']}/self-review",
                               headers=emp_headers, json={"self_comments": "ZZ self"})
    assert self_review.status_code == 200, self_review.text

    manager_review = client.post(f"/api/performance/appraisals/{appraisal['id']}/manager-review",
                                  headers=hr_manager_auth, json={"manager_comments": "ZZ manager"})
    assert manager_review.status_code == 200, manager_review.text
    assert manager_review.json()["status"] == "Calibration"

    open_cal = client.patch(f"/api/performance/cycles/{active_cycle['id']}/open-calibration", headers=hr_manager_auth)
    assert open_cal.status_code == 200, open_cal.text

    calibrate = client.post(f"/api/performance/appraisals/{appraisal['id']}/calibrate", headers=hr_manager_auth,
                             json={"calibrated_rating": 4.2, "calibration_notes": "ZZ adjusted"})
    assert calibrate.status_code == 200, calibrate.text

    close = client.patch(f"/api/performance/cycles/{active_cycle['id']}/close", headers=hr_manager_auth)
    assert close.status_code == 200, close.text
    assert close.json()["status"] == "Closed"

    final = client.get(f"/api/performance/appraisals/{appraisal['id']}", headers=hr_manager_auth)
    assert final.status_code == 200
    assert final.json()["status"] == "Finalized"
    assert final.json()["final_rating"] == 4.2


def test_get_appraisal_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/performance/appraisals/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_get_appraisal_denied_for_unrelated_employee(client, hr_manager_auth, employee_with_user, active_cycle_with_other_employee):
    cycle, other_emp = active_cycle_with_other_employee
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": cycle["id"]}).json()
    other_appraisal = next(a for a in appraisals if a["employee_id"] == other_emp["employee_id"])

    _, emp_headers = employee_with_user
    res = client.get(f"/api/performance/appraisals/{other_appraisal['id']}", headers=emp_headers)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Performance -> Payroll integration (merit increments, bonuses)
# ---------------------------------------------------------------------------
def test_merit_increment_requires_finalized_appraisal(client, hr_manager_auth, employee_with_user, active_cycle):
    emp, _ = employee_with_user
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    appraisal = next(a for a in appraisals if a["employee_id"] == emp["employee_id"])
    res = client.post(f"/api/performance/appraisals/{appraisal['id']}/merit-increment",
                       headers=hr_manager_auth, json={"increment_pct": 5})
    assert res.status_code == 400


def test_merit_increment_invalid_pct_returns_422(client, hr_manager_auth):
    res = client.post("/api/performance/appraisals/1/merit-increment", headers=hr_manager_auth,
                       json={"increment_pct": 0})
    assert res.status_code == 422


def test_bonus_payout_requires_finalized_appraisal(client, hr_manager_auth, employee_with_user, active_cycle):
    emp, _ = employee_with_user
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    appraisal = next(a for a in appraisals if a["employee_id"] == emp["employee_id"])
    res = client.post(f"/api/performance/appraisals/{appraisal['id']}/bonus",
                       headers=hr_manager_auth, json={"amount": 500})
    assert res.status_code == 400


def test_bonus_payout_invalid_amount_returns_422(client, hr_manager_auth):
    res = client.post("/api/performance/appraisals/1/bonus", headers=hr_manager_auth, json={"amount": -5})
    assert res.status_code == 422


def test_full_merit_and_bonus_flow(client, hr_manager_auth, employee_with_user, active_cycle):
    emp, emp_headers = employee_with_user
    old_salary = emp["basic_salary"]
    client.post("/api/performance/goals", headers=hr_manager_auth, json={
        "cycle_id": active_cycle["id"], "employee_id": emp["employee_id"], "goal_type": "KPI",
        "title": "ZZ Merit Goal", "weight": 100, "target_value": 100, "actual_value": 100,
    })
    appraisals = client.get("/api/performance/appraisals", headers=hr_manager_auth,
                             params={"cycle_id": active_cycle["id"]}).json()
    appraisal = next(a for a in appraisals if a["employee_id"] == emp["employee_id"])

    client.post(f"/api/performance/appraisals/{appraisal['id']}/self-review", headers=emp_headers, json={})
    client.post(f"/api/performance/appraisals/{appraisal['id']}/manager-review", headers=hr_manager_auth, json={})
    client.patch(f"/api/performance/cycles/{active_cycle['id']}/open-calibration", headers=hr_manager_auth)
    client.post(f"/api/performance/appraisals/{appraisal['id']}/calibrate", headers=hr_manager_auth, json={})
    close = client.patch(f"/api/performance/cycles/{active_cycle['id']}/close", headers=hr_manager_auth)
    assert close.status_code == 200, close.text

    merit = client.post(f"/api/performance/appraisals/{appraisal['id']}/merit-increment",
                         headers=hr_manager_auth, json={"increment_pct": 10})
    assert merit.status_code == 201, merit.text
    assert merit.json()["payout_type"] == "MeritIncrement"

    duplicate = client.post(f"/api/performance/appraisals/{appraisal['id']}/merit-increment",
                             headers=hr_manager_auth, json={"increment_pct": 5})
    assert duplicate.status_code == 400

    emp_check = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth)
    new_salary = emp_check.json()["basic_salary"]
    assert new_salary == round(old_salary + old_salary * 0.10, 2)

    bonus = client.post(f"/api/performance/appraisals/{appraisal['id']}/bonus",
                         headers=hr_manager_auth, json={"amount": 300})
    assert bonus.status_code == 201, bonus.text
    payout = bonus.json()
    assert payout["status"] == "Pending"

    listing = client.get("/api/performance/payouts", headers=hr_manager_auth, params={"status": "Pending"})
    assert listing.status_code == 200
    assert any(p["id"] == payout["id"] for p in listing.json())

    cancel = client.delete(f"/api/performance/payouts/{payout['id']}", headers=hr_manager_auth)
    assert cancel.status_code == 204

    listing2 = client.get("/api/performance/payouts", headers=hr_manager_auth)
    assert all(p["id"] != payout["id"] for p in listing2.json())


def test_cancel_payout_not_found_returns_404(client, hr_manager_auth):
    res = client.delete("/api/performance/payouts/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_list_payouts_requires_manage_or_payroll_view_role(client, employee_with_user):
    _, emp_headers = employee_with_user
    res = client.get("/api/performance/payouts", headers=emp_headers)
    assert res.status_code == 403
