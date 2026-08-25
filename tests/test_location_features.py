"""Tests for location features: history, alerts, reports, capacity planning."""
import pytest
from datetime import datetime, timedelta, date
from db import get_db
from conftest import _valid_employee_payload


@pytest.fixture
def setup_location_features(client, hr_manager_auth, test_institution):
    """Set up test data for location features tests."""
    inst_id = test_institution["id"]

    # Create two locations
    loc1_res = client.post(
        "/api/locations",
        headers=hr_manager_auth,
        json={
            "name": "KL HQ",
            "code": "KL_HQ_" + str(datetime.utcnow().timestamp()).replace(".", ""),
            "city": "Kuala Lumpur",
            "state": "KL",
            "location_type": "hq",
            "capacity": 100,
        },
    )
    assert loc1_res.status_code == 201
    loc1_id = loc1_res.json()["id"]

    loc2_res = client.post(
        "/api/locations",
        headers=hr_manager_auth,
        json={
            "name": "Penang Branch",
            "code": "PG_BR_" + str(datetime.utcnow().timestamp()).replace(".", ""),
            "city": "Penang",
            "state": "PG",
            "location_type": "branch",
            "capacity": 50,
        },
    )
    assert loc2_res.status_code == 201
    loc2_id = loc2_res.json()["id"]

    # Create employees with all required fields
    emp1_res = client.post(
        "/api/employees",
        headers=hr_manager_auth,
        json=_valid_employee_payload(
            full_name="John Doe",
            designation="Manager",
            department="Operations",
        ),
    )
    assert emp1_res.status_code == 201, emp1_res.text
    emp1_id = emp1_res.json()["employee_id"]

    emp2_res = client.post(
        "/api/employees",
        headers=hr_manager_auth,
        json=_valid_employee_payload(
            full_name="Jane Smith",
            designation="Team Lead",
            department="HR",
        ),
    )
    assert emp2_res.status_code == 201, emp2_res.text
    emp2_id = emp2_res.json()["employee_id"]

    # Assign employees to locations (with required start_date)
    asg1_res = client.post(
        f"/api/employees/{emp1_id}/locations",
        headers=hr_manager_auth,
        json={
            "location_id": loc1_id,
            "assignment_type": "primary",
            "start_date": "2024-01-01",
        },
    )
    assert asg1_res.status_code == 201, asg1_res.text

    asg2_res = client.post(
        f"/api/employees/{emp2_id}/locations",
        headers=hr_manager_auth,
        json={
            "location_id": loc2_id,
            "assignment_type": "primary",
            "start_date": "2024-01-01",
        },
    )
    assert asg2_res.status_code == 201, asg2_res.text

    yield {
        "inst_id": inst_id,
        "loc1_id": loc1_id,
        "loc2_id": loc2_id,
        "emp1_id": emp1_id,
        "emp2_id": emp2_id,
    }

    # This fixture is function-scoped and runs fresh for every test in this
    # file (no `test_institution`-level teardown exists for employees), so
    # without this the two employees it creates every run permanently
    # accumulate as Active rows on the shared test institution — this was
    # the single largest contributor (525 of each name) to a real
    # multi-minute "hang" in test_benefits.py's auto-enroll-all test, which
    # loops over every Active employee in the institution.
    for emp_id in (emp1_id, emp2_id):
        client.patch(f"/api/employees/{emp_id}/status", headers=hr_manager_auth, json={"status": "Inactive"})


# ============================================================================
# ASSIGNMENT HISTORY TESTS
# ============================================================================

def test_get_employee_assignment_history(client, setup_location_features, hr_manager_auth):
    """Test retrieving assignment history for an employee."""
    data = setup_location_features
    response = client.get(
        f"/api/employees/{data['emp1_id']}/locations/history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["employee_id"] == data["emp1_id"]
    assert body["total_assignments"] >= 1
    assert body["current_assignment"] is not None
    assert body["assignment_history"] is not None


def test_get_employee_assignment_history_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test retrieving history for non-existent employee."""
    data = setup_location_features
    response = client.get(
        "/api/employees/NONEXISTENT/locations/history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


def test_get_location_assignment_history(client, setup_location_features, hr_manager_auth):
    """Test retrieving assignment history for a location."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/assignment-history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert body["location_name"] == "KL HQ"
    assert body["total_assignments"] >= 1
    assert body["current_employees"] >= 1
    assert body["assignment_history"] is not None


def test_get_location_assignment_history_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test retrieving history for non-existent location."""
    data = setup_location_features
    response = client.get(
        "/api/locations/99999/assignment-history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


# ============================================================================
# CAPACITY ALERTS TESTS
# ============================================================================

def test_get_location_capacity_alerts_empty(
    client, setup_location_features, hr_manager_auth
):
    """Test retrieving alerts when none exist."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-alerts",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 0


def test_check_and_trigger_capacity_alerts_healthy(
    client, setup_location_features, hr_manager_auth
):
    """Test capacity check when utilization is healthy."""
    data = setup_location_features
    response = client.post(
        f"/api/locations/{data['loc1_id']}/capacity-alerts/check",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert body["current_employees"] >= 0
    assert body["capacity"] == 100
    assert "utilization_percent" in body
    assert "alert_triggered" in body


def test_acknowledge_capacity_alert_not_found(client, setup_location_features, hr_manager_auth):
    """Test acknowledging non-existent alert."""
    data = setup_location_features
    response = client.put(
        "/api/capacity-alerts/99999/acknowledge",
        json={"acknowledged_at": datetime.utcnow().isoformat()},
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


# ============================================================================
# EMPLOYEE REPORT TESTS
# ============================================================================

def test_get_employee_report_by_location(
    client, setup_location_features, hr_manager_auth
):
    """Test generating employee report for a location."""
    data = setup_location_features
    response = client.post(
        f"/api/reports/location/{data['loc1_id']}/employees",
        json={
            "location_id": data["loc1_id"],
            "include_inactive": False,
        },
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert body["location_name"] == "KL HQ"
    assert "total_employees" in body
    assert "employees" in body
    assert isinstance(body["employees"], list)
    assert "summary" in body


def test_get_employee_report_with_filters(
    client, setup_location_features, hr_manager_auth
):
    """Test employee report with filters."""
    data = setup_location_features
    response = client.post(
        f"/api/reports/location/{data['loc1_id']}/employees",
        json={
            "location_id": data["loc1_id"],
            "departments": ["Operations"],
            "status_filter": "Active",
            "include_inactive": False,
        },
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert "employees" in body


def test_get_employee_report_location_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test report for non-existent location."""
    data = setup_location_features
    response = client.post(
        "/api/reports/location/99999/employees",
        json={"location_id": 99999, "include_inactive": False},
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


# ============================================================================
# CAPACITY PLANNING TESTS
# ============================================================================

def test_get_location_capacity_status(client, setup_location_features, hr_manager_auth):
    """Test getting location capacity status."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-status",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert body["location_name"] == "KL HQ"
    assert "current_employees" in body
    assert "capacity" in body
    assert "utilization_percent" in body
    assert body["status"] in ["Healthy", "Warning", "Critical"]
    assert "alert_triggered" in body


def test_get_location_capacity_status_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test capacity status for non-existent location."""
    data = setup_location_features
    response = client.get(
        "/api/locations/99999/capacity-status",
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


def test_get_location_capacity_dashboard(
    client, setup_location_features, hr_manager_auth
):
    """Test getting complete capacity planning dashboard."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-dashboard",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert body["location_name"] == "KL HQ"
    assert "current_status" in body
    assert "forecast" in body
    assert "recent_alerts" in body
    assert isinstance(body["recent_alerts"], list)


def test_get_location_capacity_dashboard_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test dashboard for non-existent location."""
    data = setup_location_features
    response = client.get(
        "/api/locations/99999/capacity-dashboard",
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


# ============================================================================
# PAYROLL SCOPING TESTS
# ============================================================================

def test_get_location_payroll_runs(
    client, setup_location_features, hr_manager_auth
):
    """Test retrieving payroll runs for a location."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/payroll-runs",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)


def test_get_location_payroll_runs_with_filters(
    client, setup_location_features, hr_manager_auth
):
    """Test payroll runs with period filters."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/payroll-runs?period_start=2024-01-01&period_end=2024-12-31",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)


def test_get_location_payroll_runs_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test payroll runs for non-existent location."""
    data = setup_location_features
    response = client.get(
        "/api/locations/99999/payroll-runs",
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


def test_get_location_payroll_summary(
    client, setup_location_features, hr_manager_auth
):
    """Test getting location payroll summary."""
    data = setup_location_features
    response = client.get(
        f"/api/locations/{data['loc1_id']}/payroll-summary",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location_id"] == data["loc1_id"]
    assert "location_name" in body
    assert "total_employees" in body
    assert "total_gross_pay" in body
    assert "total_deductions" in body
    assert "total_net_pay" in body
    assert "average_salary" in body


def test_get_location_payroll_summary_not_found(
    client, setup_location_features, hr_manager_auth
):
    """Test payroll summary for non-existent location."""
    data = setup_location_features
    response = client.get(
        "/api/locations/99999/payroll-summary",
        headers=hr_manager_auth,
    )
    assert response.status_code == 404


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

def test_assignment_history_workflow(client, setup_location_features, hr_manager_auth):
    """Test complete assignment history workflow."""
    data = setup_location_features

    # Get employee history
    response = client.get(
        f"/api/employees/{data['emp1_id']}/locations/history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    employee_history = response.json()
    assert employee_history["employee_id"] == data["emp1_id"]

    # Get location history
    response = client.get(
        f"/api/locations/{data['loc1_id']}/assignment-history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    location_history = response.json()
    assert location_history["location_id"] == data["loc1_id"]

    # Both should have consistent data
    assert employee_history["total_assignments"] >= 1
    assert location_history["total_assignments"] >= 1


def test_capacity_workflow(client, setup_location_features, hr_manager_auth):
    """Test complete capacity management workflow."""
    data = setup_location_features

    # Check capacity status
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-status",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    status = response.json()
    assert status["status"] in ["Healthy", "Warning", "Critical"]

    # Check for alerts
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-alerts",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    alerts = response.json()
    assert isinstance(alerts, list)

    # Get full dashboard
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-dashboard",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["location_id"] == data["loc1_id"]


def test_reporting_workflow(client, setup_location_features, hr_manager_auth):
    """Test complete reporting workflow."""
    data = setup_location_features

    # Get employee report
    response = client.post(
        f"/api/reports/location/{data['loc1_id']}/employees",
        json={"location_id": data["loc1_id"], "include_inactive": False},
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    report = response.json()
    assert report["location_id"] == data["loc1_id"]
    assert "employees" in report
    assert "summary" in report

    # Report should have employee data
    assert report["total_employees"] >= 0
    assert isinstance(report["employees"], list)


def test_multi_location_capacity_comparison(
    client, setup_location_features, hr_manager_auth
):
    """Test capacity status across multiple locations."""
    data = setup_location_features

    # Get status for first location
    response1 = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-status",
        headers=hr_manager_auth,
    )
    assert response1.status_code == 200
    status1 = response1.json()

    # Get status for second location
    response2 = client.get(
        f"/api/locations/{data['loc2_id']}/capacity-status",
        headers=hr_manager_auth,
    )
    assert response2.status_code == 200
    status2 = response2.json()

    # Both should have valid data
    assert status1["location_id"] == data["loc1_id"]
    assert status2["location_id"] == data["loc2_id"]
    assert status1["status"] in ["Healthy", "Warning", "Critical"]
    assert status2["status"] in ["Healthy", "Warning", "Critical"]


def test_payroll_workflow(client, setup_location_features, hr_manager_auth):
    """Test complete payroll workflow for a location."""
    data = setup_location_features

    # Get payroll runs for location
    response = client.get(
        f"/api/locations/{data['loc1_id']}/payroll-runs",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    runs = response.json()
    assert isinstance(runs, list)

    # Get payroll summary
    response = client.get(
        f"/api/locations/{data['loc1_id']}/payroll-summary",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["location_id"] == data["loc1_id"]
    assert summary["total_employees"] >= 0
    assert summary["total_gross_pay"] >= 0


def test_complete_location_feature_workflow(
    client, setup_location_features, hr_manager_auth
):
    """Test all Phase 1 features in a complete workflow."""
    data = setup_location_features

    # 1. Check assignment history
    response = client.get(
        f"/api/employees/{data['emp1_id']}/locations/history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    assert response.json()["employee_id"] == data["emp1_id"]

    # 2. Check location assignment history
    response = client.get(
        f"/api/locations/{data['loc1_id']}/assignment-history",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    assert response.json()["location_id"] == data["loc1_id"]

    # 3. Check capacity status
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-status",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    assert response.json()["location_id"] == data["loc1_id"]

    # 4. Check capacity alerts
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-alerts",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    # 5. Get employee report
    response = client.post(
        f"/api/reports/location/{data['loc1_id']}/employees",
        json={"location_id": data["loc1_id"], "include_inactive": False},
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    assert response.json()["location_id"] == data["loc1_id"]

    # 6. Get payroll data
    response = client.get(
        f"/api/locations/{data['loc1_id']}/payroll-summary",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    assert response.json()["location_id"] == data["loc1_id"]

    # 7. Get full dashboard
    response = client.get(
        f"/api/locations/{data['loc1_id']}/capacity-dashboard",
        headers=hr_manager_auth,
    )
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["location_id"] == data["loc1_id"]
    assert "current_status" in dashboard
    assert "forecast" in dashboard


# ============================================================================
# ROLE GATING (previously these endpoints had no role gate at all)
# ============================================================================

def _employee_headers(make_test_user, test_institution, role="employee"):
    token, _ = make_test_user(role=role)
    return {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}


def test_payroll_runs_requires_payroll_view_role(client, setup_location_features, make_test_user, test_institution):
    data = setup_location_features
    headers = _employee_headers(make_test_user, test_institution)
    res = client.get(f"/api/locations/{data['loc1_id']}/payroll-runs", headers=headers)
    assert res.status_code == 403


def test_payroll_summary_requires_payroll_view_role(client, setup_location_features, make_test_user, test_institution):
    data = setup_location_features
    headers = _employee_headers(make_test_user, test_institution)
    res = client.get(f"/api/locations/{data['loc1_id']}/payroll-summary", headers=headers)
    assert res.status_code == 403


def test_payroll_manager_can_view_payroll_summary(client, setup_location_features, payroll_manager_auth):
    data = setup_location_features
    res = client.get(f"/api/locations/{data['loc1_id']}/payroll-summary", headers=payroll_manager_auth)
    assert res.status_code == 200


def test_acknowledge_capacity_alert_requires_manage_role(client, setup_location_features, make_test_user, test_institution):
    headers = _employee_headers(make_test_user, test_institution)
    res = client.put(
        "/api/capacity-alerts/99999/acknowledge",
        json={"acknowledged_at": datetime.utcnow().isoformat()},
        headers=headers,
    )
    assert res.status_code == 403


# ============================================================================
# REAL average_tenure_days / projected_departures / planned_leaves
# (previously hardcoded TODO placeholders)
# ============================================================================

def test_employee_report_average_tenure_days_is_computed(client, hr_manager_auth, test_institution, make_test_location):
    location = client.post(
        "/api/locations", headers=hr_manager_auth,
        json={
            "name": "Tenure Location",
            "code": "TEN_" + str(datetime.utcnow().timestamp()).replace(".", ""),
            "city": "Kuala Lumpur", "state": "KL", "location_type": "branch", "capacity": 50,
        },
    ).json()

    start_date = (date.today() - timedelta(days=100)).isoformat()
    emp = client.post(
        "/api/employees", headers=hr_manager_auth,
        json=_valid_employee_payload(full_name="Tenure Test Employee", start_date=start_date),
    ).json()
    client.post(
        f"/api/employees/{emp['employee_id']}/locations", headers=hr_manager_auth,
        json={"location_id": location["id"], "assignment_type": "primary", "start_date": start_date},
    )

    res = client.post(
        f"/api/reports/location/{location['id']}/employees",
        json={"location_id": location["id"], "include_inactive": False},
        headers=hr_manager_auth,
    )
    assert res.status_code == 200
    avg_tenure = res.json()["summary"]["average_tenure_days"]
    assert 99 <= avg_tenure <= 101

    client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})


def test_capacity_forecast_reflects_upcoming_contract_end(client, hr_manager_auth, test_institution, make_test_location):
    location = client.post(
        "/api/locations", headers=hr_manager_auth,
        json={
            "name": "Forecast Location",
            "code": "FC_" + str(datetime.utcnow().timestamp()).replace(".", ""),
            "city": "Kuala Lumpur", "state": "KL", "location_type": "branch", "capacity": 50,
        },
    ).json()

    contract_end = (date.today() + timedelta(days=10)).isoformat()
    emp = client.post(
        "/api/employees", headers=hr_manager_auth,
        json=_valid_employee_payload(
            full_name="Departing Test Employee",
            employment_type="Contract",
            contract_end_date=contract_end,
        ),
    ).json()
    client.post(
        f"/api/employees/{emp['employee_id']}/locations", headers=hr_manager_auth,
        json={"location_id": location["id"], "assignment_type": "primary", "start_date": "2026-01-01"},
    )

    res = client.get(f"/api/locations/{location['id']}/capacity-dashboard", headers=hr_manager_auth)
    assert res.status_code == 200
    forecast = res.json()["forecast"]
    assert forecast["projected_departures"] == 1
    assert forecast["projected_headcount"] == forecast["current_headcount"] - 1

    client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})


def test_capacity_forecast_reflects_planned_leave(client, hr_manager_auth, test_institution, make_test_location, make_test_leave_type):
    location = client.post(
        "/api/locations", headers=hr_manager_auth,
        json={
            "name": "Leave Forecast Location",
            "code": "LFC_" + str(datetime.utcnow().timestamp()).replace(".", ""),
            "city": "Kuala Lumpur", "state": "KL", "location_type": "branch", "capacity": 50,
        },
    ).json()
    emp = client.post(
        "/api/employees", headers=hr_manager_auth,
        json=_valid_employee_payload(full_name="Leave Forecast Employee"),
    ).json()
    client.post(
        f"/api/employees/{emp['employee_id']}/locations", headers=hr_manager_auth,
        json={"location_id": location["id"], "assignment_type": "primary", "start_date": "2026-01-01"},
    )
    lt = make_test_leave_type(requires_approval=False)

    leave_start = (date.today() + timedelta(days=5)).isoformat()
    leave_end = (date.today() + timedelta(days=6)).isoformat()
    leave_res = client.post(
        "/api/leave/applications", headers=hr_manager_auth,
        json={"employee_id": emp["employee_id"], "leave_type_id": lt["id"], "start_date": leave_start, "end_date": leave_end},
    )
    assert leave_res.status_code == 201
    assert leave_res.json()["status"] == "Approved"

    res = client.get(f"/api/locations/{location['id']}/capacity-dashboard", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json()["forecast"]["planned_leaves"] == 1

    client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})
