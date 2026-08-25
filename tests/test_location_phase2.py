"""Tests for Phase 2 location features: transfers, payroll dashboards, trends."""
import pytest
from datetime import datetime, timedelta
from conftest import _valid_employee_payload, _valid_location_payload


def _employee_headers(make_test_user, test_institution, role="employee"):
    token, _ = make_test_user(role=role)
    return {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}


@pytest.fixture
def setup_phase2_data(client, hr_manager_auth, test_institution):
    """Set up test data for Phase 2 tests."""
    inst_id = test_institution["id"]

    # Create location
    loc_res = client.post(
        "/api/locations",
        headers=hr_manager_auth,
        json=_valid_location_payload(inst_id),
    )
    assert loc_res.status_code == 201
    location = loc_res.json()

    # Create employee
    emp_payload = _valid_employee_payload()
    emp_res = client.post(
        "/api/employees",
        headers=hr_manager_auth,
        json=emp_payload,
    )
    assert emp_res.status_code in [200, 201]
    employee = emp_res.json()

    yield {
        "institution": test_institution,
        "location": location,
        "employee": employee,
        "client": client,
        "auth_headers": hr_manager_auth,
    }

    # Function-scoped and run once per test in this file with no other
    # cleanup — left unchecked, the created employee stays Active forever
    # on the shared test institution (see test_location_features.py's
    # setup_location_features fixture for the same issue and its effect on
    # test_benefits.py's auto-enroll-all test).
    client.patch(f"/api/employees/{employee['employee_id']}/status",
                 headers=hr_manager_auth, json={"status": "Inactive"})


class TestLocationTransferWorkflow:
    """Test location transfer request workflow."""

    def test_request_location_transfer(self, setup_phase2_data):
        """Test requesting a location transfer."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]
        institution = data["institution"]

        # Assign employee to a location first
        response = client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

        # Create another location
        location_payload = _valid_location_payload(institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        assert loc_response.status_code == 201
        target_location = loc_response.json()

        # Request transfer
        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={
                "to_location_id": target_location["id"],
                "transfer_date": (datetime.utcnow().date() + timedelta(days=7)).isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "Pending"
        assert body["employee_id"] == employee["employee_id"]
        assert body["to_location_id"] == target_location["id"]

    def test_get_employee_transfer_requests(self, setup_phase2_data):
        """Test retrieving transfer requests for an employee."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]

        # Assign to location
        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Request transfer
        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": location["id"]},
            headers=auth_headers,
        )
        assert response.status_code == 201

        # Get transfer requests
        response = client.get(
            f"/api/employees/{employee['employee_id']}/transfer-requests",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) > 0
        assert body[0]["employee_id"] == employee["employee_id"]

    def test_approve_transfer_request(self, setup_phase2_data):
        """Test approving a transfer request."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]
        institution = data["institution"]

        # Assign to location
        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Create target location
        location_payload = _valid_location_payload(institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        target_location = loc_response.json()

        # Request transfer
        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={
                "to_location_id": target_location["id"],
                "transfer_date": datetime.utcnow().date().isoformat(),
            },
            headers=auth_headers,
        )
        transfer_id = response.json()["id"]

        # Approve transfer
        response = client.put(
            f"/api/transfer-requests/{transfer_id}/approve",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ["Approved", "Completed"]

    def test_reject_transfer_request(self, setup_phase2_data):
        """Test rejecting a transfer request."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]

        # Assign to location
        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Request transfer
        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": location["id"]},
            headers=auth_headers,
        )
        transfer_id = response.json()["id"]

        # Reject transfer
        response = client.put(
            f"/api/transfer-requests/{transfer_id}/reject",
            params={"reason": "Not approved by manager"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "Rejected"
        assert body["rejection_reason"] == "Not approved by manager"


class TestLocationPayrollDashboard:
    """Test location-based payroll dashboards."""

    def test_get_location_payroll_dashboard(self, setup_phase2_data):
        """Test getting payroll dashboard for a location."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        location = data["location"]

        response = client.get(
            f"/api/payroll/location/{location['id']}/dashboard",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "location_id" in body
        assert body["location_id"] == location["id"]
        assert "summary" in body
        assert "departments" in body
        assert isinstance(body["summary"]["total_employees"], int)
        assert isinstance(body["summary"]["total_gross_pay"], (int, float))

    def test_get_institution_payroll_summary(self, setup_phase2_data):
        """Test getting institution-wide payroll summary."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        institution = data["institution"]

        response = client.get(
            f"/api/payroll/institution/{institution['id']}/summary",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "institution_id" in body
        assert body["institution_id"] == institution["id"]
        assert "locations" in body
        assert isinstance(body["locations"], list)
        assert "total_employees" in body

    def test_payroll_dashboard_includes_multiple_locations(self, client, hr_manager_auth, test_institution):
        """Test payroll summary aggregates across multiple locations."""
        inst_id = test_institution["id"]

        # Create two locations
        loc1_response = client.post(
            "/api/locations",
            json=_valid_location_payload(inst_id),
            headers=hr_manager_auth,
        )
        loc1 = loc1_response.json()

        loc2_response = client.post(
            "/api/locations",
            json=_valid_location_payload(inst_id),
            headers=hr_manager_auth,
        )
        loc2 = loc2_response.json()

        # Get institution summary
        response = client.get(
            f"/api/payroll/institution/{inst_id}/summary",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["locations"]) >= 2


class TestCapacityUtilizationTrends:
    """Test capacity utilization tracking."""

    def test_get_utilization_history(self, setup_phase2_data):
        """Test retrieving capacity utilization history."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        location = data["location"]

        response = client.get(
            f"/api/locations/{location['id']}/utilization-history?days=30",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        if len(body) > 0:
            assert "date" in body[0]
            assert "employee_count" in body[0]
            assert "capacity" in body[0]
            assert "utilization_percent" in body[0]

    def test_get_utilization_trends(self, setup_phase2_data):
        """Test getting utilization trends and analysis."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        location = data["location"]

        response = client.get(
            f"/api/locations/{location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "location_id" in body
        assert body["location_id"] == location["id"]
        assert "current_utilization" in body
        assert "current_employees" in body
        assert "capacity" in body
        assert "available_capacity" in body
        assert "recommendation" in body
        assert isinstance(body["current_utilization"], (int, float))

    def test_utilization_trends_recommendation_logic(self, setup_phase2_data):
        """Test that recommendation changes based on utilization."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]

        # Assign employee to location
        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        response = client.get(
            f"/api/locations/{location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "recommendation" in body
        # Recommendation should be one of the valid messages
        valid_recommendations = [
            "URGENT: Recruit immediately or reduce assignments",
            "Plan recruitment to maintain buffer",
            "Monitor and plan for growth",
            "Capacity available for additional assignments",
        ]
        assert body["recommendation"] in valid_recommendations


class TestPhase2IntegrationWorkflows:
    """Test complex workflows across Phase 2 features."""

    def test_transfer_and_payroll_workflow(self, setup_phase2_data):
        """Test complete transfer workflow and payroll reporting."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]
        institution = data["institution"]

        # 1. Assign employee to original location
        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # 2. View payroll dashboard
        response = client.get(
            f"/api/payroll/location/{location['id']}/dashboard",
            headers=auth_headers,
        )
        assert response.status_code == 200

        # 3. Request transfer
        location_payload = _valid_location_payload(institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        target_location = loc_response.json()

        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={
                "to_location_id": target_location["id"],
                "transfer_date": datetime.utcnow().date().isoformat(),
            },
            headers=auth_headers,
        )
        transfer_id = response.json()["id"]

        # 4. Approve transfer
        client.put(
            f"/api/transfer-requests/{transfer_id}/approve",
            headers=auth_headers,
        )

        # 5. Check capacity trends on new location
        response = client.get(
            f"/api/locations/{target_location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_multi_location_payroll_analysis(self, client, hr_manager_auth, test_institution):
        """Test payroll analysis across multiple locations."""
        inst_id = test_institution["id"]

        # Create multiple locations
        locations = []
        for i in range(3):
            response = client.post(
                "/api/locations",
                json=_valid_location_payload(inst_id),
                headers=hr_manager_auth,
            )
            locations.append(response.json())

        # Create and assign an employee
        emp_payload = _valid_employee_payload()
        emp_res = client.post(
            "/api/employees",
            headers=hr_manager_auth,
            json=emp_payload,
        )
        employee = emp_res.json()

        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": locations[0]["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=hr_manager_auth,
        )

        # Get institution summary
        response = client.get(
            f"/api/payroll/institution/{inst_id}/summary",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["locations"]) >= 3
        assert body["total_employees"] >= 1

        # Check individual location dashboards
        for location in locations:
            response = client.get(
                f"/api/payroll/location/{location['id']}/dashboard",
                headers=hr_manager_auth,
            )
            assert response.status_code == 200

        client.patch(f"/api/employees/{employee['employee_id']}/status",
                     headers=hr_manager_auth, json={"status": "Inactive"})

    def test_capacity_and_transfer_workflow(self, setup_phase2_data):
        """Test capacity planning with transfers."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]
        institution = data["institution"]

        # Check initial utilization
        response = client.get(
            f"/api/locations/{location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200
        initial_utilization = response.json()["current_utilization"]

        # Assign employee
        assign_res = client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )
        assert assign_res.status_code == 201, assign_res.text

        # Check updated utilization
        response = client.get(
            f"/api/locations/{location['id']}/utilization-trends",
            headers=auth_headers,
        )
        updated_utilization = response.json()["current_utilization"]
        assert updated_utilization > initial_utilization

        # Create new location and request transfer
        location_payload = _valid_location_payload(institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        target_location = loc_response.json()

        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": target_location["id"]},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        transfer_id = response.json()["id"]

        # Approve transfer
        client.put(
            f"/api/transfer-requests/{transfer_id}/approve",
            headers=auth_headers,
        )

        # Check utilization is back down on original location (if transfer completed)
        response = client.get(
            f"/api/locations/{location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestPhase2ErrorHandling:
    """Test error handling in Phase 2 endpoints."""

    def test_transfer_nonexistent_employee(self, client, hr_manager_auth):
        """Test transferring nonexistent employee."""
        response = client.post(
            "/api/employees/EMP999/transfer-request",
            params={"to_location_id": 1},
            headers=hr_manager_auth,
        )
        assert response.status_code == 404

    def test_transfer_to_nonexistent_location(self, setup_phase2_data):
        """Test transferring to nonexistent location."""
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]

        # Assign to location first
        client.post(
            f"/api/employees/{employee['employee_id']}/locations",
            json={
                "employee_id": employee["employee_id"],
                "location_id": location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": 99999},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_approve_nonexistent_transfer(self, client, hr_manager_auth):
        """Test approving nonexistent transfer."""
        response = client.put(
            "/api/transfer-requests/99999/approve",
            headers=hr_manager_auth,
        )
        assert response.status_code == 404

    def test_get_nonexistent_location_dashboard(self, client, hr_manager_auth):
        """Test dashboard for nonexistent location."""
        response = client.get(
            "/api/payroll/location/99999/dashboard",
            headers=hr_manager_auth,
        )
        assert response.status_code == 404

    def test_institution_payroll_access_denied(self, client, hr_manager_auth):
        """Test cross-institution access denial."""
        # Try to access different institution
        response = client.get(
            f"/api/payroll/institution/99999/summary",
            headers=hr_manager_auth,
        )
        # Should either be 404 (not found) or 403 (forbidden)
        assert response.status_code in [404, 403]


class TestPhase2RoleGating:
    """Previously none of these endpoints had any role gate at all."""

    def test_transfer_request_requires_manage_role(self, setup_phase2_data, make_test_user, test_institution):
        data = setup_phase2_data
        employee = data["employee"]
        location = data["location"]
        headers = _employee_headers(make_test_user, test_institution)
        response = data["client"].post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": location["id"]},
            headers=headers,
        )
        assert response.status_code == 403

    def test_approve_transfer_requires_manage_role(self, setup_phase2_data, make_test_user, test_institution):
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]

        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": location["id"]},
            headers=auth_headers,
        )
        transfer_id = response.json()["id"]

        headers = _employee_headers(make_test_user, test_institution)
        response = client.put(f"/api/transfer-requests/{transfer_id}/approve", headers=headers)
        assert response.status_code == 403

    def test_reject_transfer_requires_manage_role(self, setup_phase2_data, make_test_user, test_institution):
        data = setup_phase2_data
        client = data["client"]
        auth_headers = data["auth_headers"]
        employee = data["employee"]
        location = data["location"]

        response = client.post(
            f"/api/employees/{employee['employee_id']}/transfer-request",
            params={"to_location_id": location["id"]},
            headers=auth_headers,
        )
        transfer_id = response.json()["id"]

        headers = _employee_headers(make_test_user, test_institution)
        response = client.put(
            f"/api/transfer-requests/{transfer_id}/reject",
            params={"reason": "test"},
            headers=headers,
        )
        assert response.status_code == 403

    def test_location_payroll_dashboard_requires_payroll_view_role(self, setup_phase2_data, make_test_user, test_institution):
        data = setup_phase2_data
        headers = _employee_headers(make_test_user, test_institution)
        response = data["client"].get(
            f"/api/payroll/location/{data['location']['id']}/dashboard",
            headers=headers,
        )
        assert response.status_code == 403

    def test_institution_payroll_summary_requires_payroll_view_role(self, setup_phase2_data, make_test_user, test_institution):
        data = setup_phase2_data
        headers = _employee_headers(make_test_user, test_institution)
        response = data["client"].get(
            f"/api/payroll/institution/{data['institution']['id']}/summary",
            headers=headers,
        )
        assert response.status_code == 403

    def test_payroll_manager_can_view_location_dashboard(self, setup_phase2_data, payroll_manager_auth):
        data = setup_phase2_data
        response = data["client"].get(
            f"/api/payroll/location/{data['location']['id']}/dashboard",
            headers=payroll_manager_auth,
        )
        assert response.status_code == 200

    def test_utilization_trends_does_not_require_manage_role(self, setup_phase2_data, make_test_user, test_institution):
        """Read-only endpoints stay open to any authenticated in-tenant user."""
        data = setup_phase2_data
        headers = _employee_headers(make_test_user, test_institution)
        response = data["client"].get(
            f"/api/locations/{data['location']['id']}/utilization-trends",
            headers=headers,
        )
        assert response.status_code == 200
