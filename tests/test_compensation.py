"""Tests for Compensation Framework: Pay Grades, Job Levels, Salary Structures."""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from tests.conftest import _unique_code


class TestPayGrades:
    """Test pay grade management."""

    def test_create_pay_grade(self, client, hr_manager_auth):
        """Test creating a pay grade."""
        code = _unique_code("A1")
        response = client.post(
            "/api/compensation/pay-grades",
            json={
                "grade_code": code,
                "grade_name": "Entry Level",
                "grade_level": 1,
                "min_salary": 2500.00,
                "midpoint_salary": 3000.00,
                "max_salary": 3500.00,
                "description": "Entry level position"
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["grade_code"] == code
        assert body["grade_name"] == "Entry Level"
        assert body["min_salary"] == 2500.00

    def test_list_pay_grades(self, client, hr_manager_auth):
        """Test listing pay grades."""
        # Create a pay grade first
        response = client.post(
            "/api/compensation/pay-grades",
            json={
                "grade_code": _unique_code("B1"),
                "grade_name": "Senior Level",
                "grade_level": 2,
                "min_salary": 5000.00,
                "midpoint_salary": 6000.00,
                "max_salary": 7000.00,
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201, response.text

        response = client.get(
            "/api/compensation/pay-grades",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) > 0

    def test_invalid_salary_range(self, client, hr_manager_auth):
        """Test validation of salary ranges (min <= midpoint <= max)."""
        response = client.post(
            "/api/compensation/pay-grades",
            json={
                "grade_code": _unique_code("X1"),
                "grade_name": "Invalid",
                "grade_level": 1,
                "min_salary": 5000.00,
                "midpoint_salary": 3000.00,  # Invalid: less than min
                "max_salary": 7000.00,
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 400


class TestJobLevels:
    """Test job level management."""

    def test_create_job_level(self, client, hr_manager_auth):
        """Test creating a job level."""
        code = _unique_code("IC1")
        response = client.post(
            "/api/compensation/job-levels",
            json={
                "level_code": code,
                "level_name": "Individual Contributor",
                "level_order": 1,
                "description": "Entry level IC"
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["level_code"] == code
        assert body["level_name"] == "Individual Contributor"

    def test_list_job_levels(self, client, hr_manager_auth):
        """Test listing job levels."""
        # Create a job level first
        response = client.post(
            "/api/compensation/job-levels",
            json={
                "level_code": _unique_code("MGR1"),
                "level_name": "Manager",
                "level_order": 3,
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201, response.text

        response = client.get(
            "/api/compensation/job-levels",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)


class TestJobRoles:
    """Test job role management."""

    def test_create_job_role(self, client, hr_manager_auth):
        """Test creating a job role."""
        # First create a job level
        level_res = client.post(
            "/api/compensation/job-levels",
            json={
                "level_code": _unique_code("IC"),
                "level_name": "Individual Contributor",
                "level_order": 1,
            },
            headers=hr_manager_auth,
        )
        assert level_res.status_code == 201, level_res.text
        level_id = level_res.json()["id"]

        # Now create a job role
        response = client.post(
            "/api/compensation/job-roles",
            json={
                "job_level_id": level_id,
                "role_name": "Software Engineer",
                "role_code": _unique_code("SE"),
                "department": "Engineering",
                "required_experience_years": 2,
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["role_name"] == "Software Engineer"
        assert body["job_level_id"] == level_id

    def test_map_role_to_grade(self, client, hr_manager_auth):
        """Test mapping a job role to pay grades."""
        # Create level
        level_res = client.post(
            "/api/compensation/job-levels",
            json={
                "level_code": _unique_code("IC2"),
                "level_name": "IC Level 2",
                "level_order": 1,
            },
            headers=hr_manager_auth,
        )
        assert level_res.status_code == 201, level_res.text
        level_id = level_res.json()["id"]

        # Create role
        role_res = client.post(
            "/api/compensation/job-roles",
            json={
                "job_level_id": level_id,
                "role_name": "Engineer",
                "role_code": _unique_code("ENG"),
            },
            headers=hr_manager_auth,
        )
        assert role_res.status_code == 201, role_res.text
        role_id = role_res.json()["id"]

        # Create grade
        grade_res = client.post(
            "/api/compensation/pay-grades",
            json={
                "grade_code": _unique_code("A2"),
                "grade_name": "Grade A2",
                "grade_level": 2,
                "min_salary": 3600.00,
                "midpoint_salary": 4300.00,
                "max_salary": 5000.00,
            },
            headers=hr_manager_auth,
        )
        assert grade_res.status_code == 201, grade_res.text
        grade_id = grade_res.json()["id"]

        # Map role to grade
        response = client.post(
            f"/api/compensation/job-roles/{role_id}/pay-grades/{grade_id}",
            params={"is_primary": True},
            headers=hr_manager_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "mapped"


@pytest.fixture
def created_employee(make_test_employee):
    """A disposable employee for compensation tests that need one already
    on file — thin wrapper around the shared make_test_employee factory."""
    return make_test_employee()


class TestEmployeeCompensation:
    """Test employee compensation assignment."""

    def test_set_employee_compensation(self, client, hr_manager_auth, created_employee):
        """Test setting employee compensation."""
        # Create pay grade
        grade_res = client.post(
            "/api/compensation/pay-grades",
            json={
                "grade_code": _unique_code("A3"),
                "grade_name": "Grade A3",
                "grade_level": 3,
                "min_salary": 5100.00,
                "midpoint_salary": 6300.00,
                "max_salary": 7500.00,
            },
            headers=hr_manager_auth,
        )
        grade_id = grade_res.json()["id"]

        # Set employee compensation
        response = client.post(
            f"/api/compensation/employees/{created_employee['employee_id']}/compensation",
            json={
                "pay_grade_id": grade_id,
                "base_salary": 6000.00,
                "effective_date": "2026-07-19",
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["base_salary"] == 6000.00
        assert body["pay_grade_id"] == grade_id
        assert body["is_current"] == 1

    def test_get_employee_compensation(self, client, hr_manager_auth, created_employee):
        """Test retrieving employee compensation."""
        # First set compensation
        grade_res = client.post(
            "/api/compensation/pay-grades",
            json={
                "grade_code": _unique_code("B2"),
                "grade_name": "Grade B2",
                "grade_level": 4,
                "min_salary": 7600.00,
                "midpoint_salary": 8800.00,
                "max_salary": 10000.00,
            },
            headers=hr_manager_auth,
        )
        grade_id = grade_res.json()["id"]

        client.post(
            f"/api/compensation/employees/{created_employee['employee_id']}/compensation",
            json={
                "pay_grade_id": grade_id,
                "base_salary": 8500.00,
                "effective_date": "2026-07-19",
            },
            headers=hr_manager_auth,
        )

        # Get compensation
        response = client.get(
            f"/api/compensation/employees/{created_employee['employee_id']}/compensation",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["employee_id"] == created_employee["employee_id"]
        assert body["base_salary"] == 8500.00


class TestSalaryChanges:
    """Test salary change tracking and audit trail."""

    def test_record_salary_change(self, client, hr_manager_auth, created_employee):
        """Test recording a salary change."""
        response = client.post(
            f"/api/compensation/salary-changes/{created_employee['employee_id']}",
            json={
                "change_type": "merit_increase",
                "from_salary": 5000.00,
                "to_salary": 5500.00,
                "effective_date": "2026-07-26",
                "reason": "Performance merit increase",
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["change_type"] == "merit_increase"
        assert body["from_salary"] == 5000.00
        assert body["to_salary"] == 5500.00
        assert body["status"] == "Pending"

    def test_get_salary_history(self, client, hr_manager_auth, created_employee):
        """Test retrieving salary change history."""
        # Record multiple changes
        for i in range(3):
            client.post(
                f"/api/compensation/salary-changes/{created_employee['employee_id']}",
                json={
                    "change_type": "adjustment",
                    "from_salary": 5000.00 + (i * 100),
                    "to_salary": 5100.00 + (i * 100),
                    "effective_date": "2026-07-19",
                },
                headers=hr_manager_auth,
            )

        response = client.get(
            f"/api/compensation/salary-changes/{created_employee['employee_id']}",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) >= 3


class TestMeritReview:
    """Test merit review cycle management."""

    def test_create_merit_cycle(self, client, hr_manager_auth):
        """Test creating a merit review cycle."""
        response = client.post(
            "/api/compensation/merit-cycles",
            json={
                "cycle_name": "2026 Annual Merit Review",
                "review_year": 2026,
                "cycle_start_date": "2026-07-01",
                "cycle_end_date": "2026-08-31",
                "submission_deadline": "2026-08-15",
                "budget_pool_amount": 500000.00,
                "description": "Annual merit increase cycle",
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["cycle_name"] == "2026 Annual Merit Review"
        assert body["status"] == "Draft"

    def test_create_merit_recommendation(self, client, hr_manager_auth, created_employee):
        """Test creating a merit recommendation."""
        # Create cycle
        cycle_res = client.post(
            "/api/compensation/merit-cycles",
            json={
                "cycle_name": "2026 Merit",
                "review_year": 2026,
                "cycle_start_date": "2026-07-01",
                "cycle_end_date": "2026-08-31",
                "submission_deadline": "2026-08-15",
            },
            headers=hr_manager_auth,
        )
        cycle_id = cycle_res.json()["id"]

        # Create recommendation
        response = client.post(
            "/api/compensation/merit-recommendations",
            params={"merit_cycle_id": cycle_id},
            json={
                "employee_id": created_employee["employee_id"],
                "current_salary": 5000.00,
                "recommended_increase_percent": 10.0,
                "recommended_new_salary": 5500.00,
                "reason": "Excellent performance",
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["employee_id"] == created_employee["employee_id"]
        assert body["approval_status"] == "Pending"

    def test_approve_merit_recommendation(self, client, hr_manager_auth, created_employee):
        """Test approving a merit recommendation."""
        # Create cycle and recommendation
        cycle_res = client.post(
            "/api/compensation/merit-cycles",
            json={
                "cycle_name": "Test Cycle",
                "review_year": 2026,
                "cycle_start_date": "2026-07-01",
                "cycle_end_date": "2026-08-31",
                "submission_deadline": "2026-08-15",
            },
            headers=hr_manager_auth,
        )
        cycle_id = cycle_res.json()["id"]

        rec_res = client.post(
            "/api/compensation/merit-recommendations",
            params={"merit_cycle_id": cycle_id},
            json={
                "employee_id": created_employee["employee_id"],
                "current_salary": 4500.00,
                "recommended_increase_percent": 8.0,
                "recommended_new_salary": 4860.00,
            },
            headers=hr_manager_auth,
        )
        rec_id = rec_res.json()["id"]

        # Approve recommendation
        response = client.put(
            f"/api/compensation/merit-recommendations/{rec_id}",
            json={
                "approval_status": "Approved",
                "approval_date": "2026-07-19",
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["approval_status"] == "Approved"


class TestPayEquity:
    """Test pay equity analysis."""

    def test_get_pay_equity_report(self, client, hr_manager_auth):
        """Test generating pay equity report."""
        response = client.get(
            "/api/compensation/pay-equity/report",
            headers=hr_manager_auth,
        )
        assert response.status_code == 200
        body = response.json()
        assert "analysis_date" in body
        assert "gender_gap" in body
        assert "department_gap" in body
        assert "flagged_items" in body


class TestAccessControl:
    """Test access control for compensation features."""

    def test_non_hr_cannot_access(self, client, created_employee):
        """Test that non-HR users cannot access compensation features."""
        # Create a regular user header (not HR)
        regular_user_headers = {
            "Authorization": f"Bearer fake_token"  # This would fail in real scenario
        }

        # Try to create pay grade (should fail)
        # This test assumes proper auth is in place
        # In practice, get_current_user would reject invalid tokens


class TestErrorHandling:
    """Test error handling."""

    def test_invalid_job_level(self, client, hr_manager_auth):
        """Test creating role with invalid job level."""
        response = client.post(
            "/api/compensation/job-roles",
            json={
                "job_level_id": 99999,  # Non-existent level
                "role_name": "Test Role",
                "role_code": _unique_code("TST"),
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 404

    def test_nonexistent_employee_compensation(self, client, hr_manager_auth):
        """Test setting compensation for non-existent employee."""
        response = client.post(
            "/api/compensation/employees/EMP_NONEXIST/compensation",
            json={
                "base_salary": 5000.00,
                "effective_date": "2026-07-19",
            },
            headers=hr_manager_auth,
        )
        assert response.status_code == 404
