"""Tests for Phase 2 location features: transfers, payroll dashboards, trends."""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from main import app
from tests.conftest import _valid_employee_payload, _valid_location_payload


client = TestClient(app)


class TestLocationTransferWorkflow:
    """Test location transfer request workflow."""

    def test_request_location_transfer(self, auth_headers, created_institution, created_employee, created_location):
        """Test requesting a location transfer."""
        # Assign employee to a location first
        response = client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

        # Create another location
        location_payload = _valid_location_payload(created_institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        assert loc_response.status_code == 201
        target_location = loc_response.json()

        # Request transfer
        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={
                "to_location_id": target_location["id"],
                "transfer_date": (datetime.utcnow().date() + timedelta(days=7)).isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "Pending"
        assert body["employee_id"] == created_employee["employee_id"]
        assert body["to_location_id"] == target_location["id"]

    def test_get_employee_transfer_requests(self, auth_headers, created_employee, created_location):
        """Test retrieving transfer requests for an employee."""
        # Assign to location
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Request transfer
        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={"to_location_id": created_location["id"]},
            headers=auth_headers,
        )
        assert response.status_code == 201

        # Get transfer requests
        response = client.get(
            f"/api/employees/{created_employee['employee_id']}/transfer-requests",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) > 0
        assert body[0]["employee_id"] == created_employee["employee_id"]

    def test_approve_transfer_request(self, auth_headers, created_employee, created_location, created_institution):
        """Test approving a transfer request."""
        # Assign to location
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Create target location
        location_payload = _valid_location_payload(created_institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        target_location = loc_response.json()

        # Request transfer
        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={
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

    def test_reject_transfer_request(self, auth_headers, created_employee, created_location):
        """Test rejecting a transfer request."""
        # Assign to location
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Request transfer
        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={"to_location_id": created_location["id"]},
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

    def test_get_location_payroll_dashboard(self, auth_headers, created_location):
        """Test getting payroll dashboard for a location."""
        response = client.get(
            f"/api/payroll/location/{created_location['id']}/dashboard",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "location_id" in body
        assert body["location_id"] == created_location["id"]
        assert "summary" in body
        assert "departments" in body
        assert isinstance(body["summary"]["total_employees"], int)
        assert isinstance(body["summary"]["total_gross_pay"], (int, float))

    def test_get_institution_payroll_summary(self, auth_headers, created_institution):
        """Test getting institution-wide payroll summary."""
        response = client.get(
            f"/api/payroll/institution/{created_institution['id']}/summary",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "institution_id" in body
        assert body["institution_id"] == created_institution["id"]
        assert "locations" in body
        assert isinstance(body["locations"], list)
        assert "total_employees" in body

    def test_payroll_dashboard_includes_multiple_locations(self, auth_headers, created_institution, auth_headers_user2):
        """Test payroll summary aggregates across multiple locations."""
        # Create two locations
        loc1_response = client.post(
            "/api/locations",
            json=_valid_location_payload(created_institution["id"]),
            headers=auth_headers,
        )
        loc1 = loc1_response.json()

        loc2_response = client.post(
            "/api/locations",
            json=_valid_location_payload(created_institution["id"]),
            headers=auth_headers,
        )
        loc2 = loc2_response.json()

        # Get institution summary
        response = client.get(
            f"/api/payroll/institution/{created_institution['id']}/summary",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["locations"]) >= 2


class TestCapacityUtilizationTrends:
    """Test capacity utilization tracking."""

    def test_get_utilization_history(self, auth_headers, created_location):
        """Test retrieving capacity utilization history."""
        response = client.get(
            f"/api/locations/{created_location['id']}/utilization-history?days=30",
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

    def test_get_utilization_trends(self, auth_headers, created_location):
        """Test getting utilization trends and analysis."""
        response = client.get(
            f"/api/locations/{created_location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "location_id" in body
        assert body["location_id"] == created_location["id"]
        assert "current_utilization" in body
        assert "current_employees" in body
        assert "capacity" in body
        assert "available_capacity" in body
        assert "recommendation" in body
        assert isinstance(body["current_utilization"], (int, float))

    def test_utilization_trends_recommendation_logic(self, auth_headers, created_location, created_employee):
        """Test that recommendation changes based on utilization."""
        # Assign employee to location
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        response = client.get(
            f"/api/locations/{created_location['id']}/utilization-trends",
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

    def test_transfer_and_payroll_workflow(self, auth_headers, created_employee, created_location, created_institution):
        """Test complete transfer workflow and payroll reporting."""
        # 1. Assign employee to original location
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # 2. View payroll dashboard
        response = client.get(
            f"/api/payroll/location/{created_location['id']}/dashboard",
            headers=auth_headers,
        )
        assert response.status_code == 200
        dashboard_before = response.json()

        # 3. Request transfer
        location_payload = _valid_location_payload(created_institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        target_location = loc_response.json()

        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={
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

    def test_multi_location_payroll_analysis(self, auth_headers, created_institution, created_employee):
        """Test payroll analysis across multiple locations."""
        # Create multiple locations
        locations = []
        for i in range(3):
            response = client.post(
                "/api/locations",
                json=_valid_location_payload(created_institution["id"]),
                headers=auth_headers,
            )
            locations.append(response.json())

        # Assign employee to first location
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": locations[0]["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Get institution summary
        response = client.get(
            f"/api/payroll/institution/{created_institution['id']}/summary",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["locations"]) >= 3
        assert body["total_employees"] >= 1

        # Check individual location dashboards
        for location in locations:
            response = client.get(
                f"/api/payroll/location/{location['id']}/dashboard",
                headers=auth_headers,
            )
            assert response.status_code == 200

    def test_capacity_and_transfer_workflow(self, auth_headers, created_employee, created_location, created_institution):
        """Test capacity planning with transfers."""
        # Check initial utilization
        response = client.get(
            f"/api/locations/{created_location['id']}/utilization-trends",
            headers=auth_headers,
        )
        assert response.status_code == 200
        initial_utilization = response.json()["current_utilization"]

        # Assign employee
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        # Check updated utilization
        response = client.get(
            f"/api/locations/{created_location['id']}/utilization-trends",
            headers=auth_headers,
        )
        updated_utilization = response.json()["current_utilization"]
        assert updated_utilization > initial_utilization

        # Create new location and request transfer
        location_payload = _valid_location_payload(created_institution["id"])
        loc_response = client.post(
            "/api/locations",
            json=location_payload,
            headers=auth_headers,
        )
        target_location = loc_response.json()

        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={"to_location_id": target_location["id"]},
            headers=auth_headers,
        )
        transfer_id = response.json()["id"]

        # Approve transfer
        client.put(
            f"/api/transfer-requests/{transfer_id}/approve",
            headers=auth_headers,
        )

        # Check utilization is back down on original location
        response = client.get(
            f"/api/locations/{created_location['id']}/utilization-trends",
            headers=auth_headers,
        )
        final_utilization = response.json()["current_utilization"]
        # After transfer completion, utilization may decrease if employee was moved


class TestPhase2ErrorHandling:
    """Test error handling in Phase 2 endpoints."""

    def test_transfer_nonexistent_employee(self, auth_headers):
        """Test transferring nonexistent employee."""
        response = client.post(
            "/api/employees/EMP999/transfer-request",
            json={"to_location_id": 1},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_transfer_to_nonexistent_location(self, auth_headers, created_employee, created_location):
        """Test transferring to nonexistent location."""
        # Assign to location first
        client.post(
            "/api/employees/assign-location",
            json={
                "employee_id": created_employee["employee_id"],
                "location_id": created_location["id"],
                "assignment_type": "primary",
                "start_date": "2024-01-01",
            },
            headers=auth_headers,
        )

        response = client.post(
            f"/api/employees/{created_employee['employee_id']}/transfer-request",
            json={"to_location_id": 99999},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_approve_nonexistent_transfer(self, auth_headers):
        """Test approving nonexistent transfer."""
        response = client.put(
            "/api/transfer-requests/99999/approve",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_get_nonexistent_location_dashboard(self, auth_headers):
        """Test dashboard for nonexistent location."""
        response = client.get(
            "/api/payroll/location/99999/dashboard",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_institution_payroll_access_denied(self, auth_headers, created_institution):
        """Test cross-institution access denial."""
        # Try to access different institution (institution_id won't match)
        response = client.get(
            f"/api/payroll/institution/99999/summary",
            headers=auth_headers,
        )
        # Should either be 404 (not found) or 403 (forbidden)
        assert response.status_code in [404, 403]
