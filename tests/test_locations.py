"""Tests for location and employee location assignment endpoints."""
import pytest
from tests.conftest import make_test_user


def test_create_location(client, hr_manager_auth, test_institution):
    """Test creating a new location."""
    location_data = {
        "name": "Kuala Lumpur HQ",
        "code": "KL_HQ",
        "address": "123 Jln Merdeka",
        "city": "Kuala Lumpur",
        "state": "KL",
        "postal_code": "50050",
        "phone": "+603-1234-5678",
        "location_type": "hq",
        "capacity": 100,
    }

    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["name"] == "Kuala Lumpur HQ"
    assert body["code"] == "KL_HQ"
    assert body["location_type"] == "hq"
    assert body["capacity"] == 100
    assert body["is_active"] == True
    assert body["employee_count"] == 0


def test_create_location_duplicate_code(client, hr_manager_auth, test_institution):
    """Test that duplicate location codes are rejected."""
    location_data = {
        "name": "Location 1",
        "code": "LOC_001",
        "location_type": "branch",
    }

    # First create should succeed
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    assert res.status_code == 201

    # Second with same code should fail
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    assert res.status_code == 400
    assert "already exists" in res.text.lower()


def test_list_locations(client, hr_manager_auth, test_institution):
    """Test listing locations for an institution."""
    # Create two locations
    for i in range(2):
        location_data = {
            "name": f"Location {i+1}",
            "code": f"LOC_{i+1:03d}",
            "location_type": "branch",
        }
        client.post("/api/locations", headers=hr_manager_auth, json=location_data)

    # List locations
    inst_id = test_institution["id"]
    res = client.get(f"/api/institutions/{inst_id}/locations", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()

    assert body["total_locations"] == 2
    assert len(body["locations"]) == 2


def test_get_location(client, hr_manager_auth, test_institution):
    """Test getting a specific location."""
    location_data = {
        "name": "Test Location",
        "code": "TST_LOC",
        "location_type": "branch",
        "capacity": 50,
    }

    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    assert res.status_code == 201
    location_id = res.json()["id"]

    res = client.get(f"/api/locations/{location_id}", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()

    assert body["id"] == location_id
    assert body["name"] == "Test Location"
    assert body["code"] == "TST_LOC"


def test_update_location(client, hr_manager_auth, test_institution):
    """Test updating a location."""
    location_data = {
        "name": "Original Name",
        "code": "ORIG",
        "location_type": "branch",
    }

    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    # Update the location
    updates = {
        "name": "Updated Name",
        "city": "Petaling Jaya",
    }

    res = client.put(f"/api/locations/{location_id}", headers=hr_manager_auth, json=updates)
    assert res.status_code == 200
    body = res.json()

    assert body["name"] == "Updated Name"
    assert body["city"] == "Petaling Jaya"
    assert body["code"] == "ORIG"  # Unchanged


def test_delete_location(client, hr_manager_auth, test_institution):
    """Test soft-deleting a location."""
    location_data = {
        "name": "To Delete",
        "code": "DEL_001",
        "location_type": "branch",
    }

    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    # Delete the location
    res = client.delete(f"/api/locations/{location_id}", headers=hr_manager_auth)
    assert res.status_code == 200

    # Verify is_active is now 0
    res = client.get(f"/api/locations/{location_id}", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json()["is_active"] == False


def test_get_location_stats(client, hr_manager_auth, test_institution, make_test_employee):
    """Test getting location statistics."""
    # Create location
    location_data = {
        "name": "Stats Location",
        "code": "STATS_001",
        "location_type": "branch",
        "capacity": 100,
    }
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    # Create employee and assign to location
    emp = make_test_employee(department="Engineering")
    assignment = {
        "location_id": location_id,
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201

    # Get stats
    res = client.get(f"/api/locations/{location_id}/stats", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()

    assert body["location_id"] == location_id
    assert body["total_employees"] == 1
    assert body["active_employees"] == 1
    assert body["utilization_percent"] == 1  # 1/100 = 1%
    assert "Engineering" in body["employees_by_department"]
    assert body["employees_by_department"]["Engineering"] == 1


def test_assign_employee_to_location(client, hr_manager_auth, make_test_employee, test_institution):
    """Test assigning an employee to a location."""
    # Create location
    location_data = {
        "name": "Assignment Location",
        "code": "ASGN_001",
        "location_type": "branch",
    }
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    # Create employee
    emp = make_test_employee()

    # Assign employee to location
    assignment = {
        "location_id": location_id,
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201
    body = res.json()

    assert body["employee_id"] == emp["employee_id"]
    assert body["location_id"] == location_id
    assert body["assignment_type"] == "primary"
    assert body["is_active"] == True


def test_assign_employee_duplicate_primary_location(client, hr_manager_auth, make_test_employee, test_institution):
    """Test that employee can't have two primary location assignments."""
    # Create two locations
    locations = []
    for i in range(2):
        location_data = {
            "name": f"Location {i+1}",
            "code": f"DUP_{i+1:03d}",
            "location_type": "branch",
        }
        res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
        locations.append(res.json()["id"])

    # Create employee
    emp = make_test_employee()

    # Assign to first location
    assignment = {
        "location_id": locations[0],
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201

    # Try to assign to second location with primary type
    assignment = {
        "location_id": locations[1],
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 400
    assert "primary" in res.text.lower()


def test_assign_employee_secondary_location(client, hr_manager_auth, make_test_employee, test_institution):
    """Test assigning employee to secondary location."""
    # Create locations
    locations = []
    for i in range(2):
        location_data = {
            "name": f"Location {i+1}",
            "code": f"SEC_{i+1:03d}",
            "location_type": "branch",
        }
        res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
        locations.append(res.json()["id"])

    emp = make_test_employee()

    # Assign primary location
    assignment = {
        "location_id": locations[0],
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201

    # Assign secondary location
    assignment = {
        "location_id": locations[1],
        "assignment_type": "secondary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201


def test_get_employee_locations(client, hr_manager_auth, make_test_employee, test_institution):
    """Test getting all locations for an employee."""
    # Create two locations
    locations = []
    for i in range(2):
        location_data = {
            "name": f"Location {i+1}",
            "code": f"GET_{i+1:03d}",
            "location_type": "branch",
        }
        res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
        locations.append(res.json())

    emp = make_test_employee()

    # Assign to both locations
    for loc in locations:
        assignment = {
            "location_id": loc["id"],
            "assignment_type": "primary" if loc == locations[0] else "secondary",
            "start_date": "2026-08-01",
        }
        res = client.post(
            f"/api/employees/{emp['employee_id']}/locations",
            headers=hr_manager_auth,
            json=assignment,
        )
        assert res.status_code == 201

    # Get employee locations
    res = client.get(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
    )
    assert res.status_code == 200
    body = res.json()

    assert body["employee_id"] == emp["employee_id"]
    assert len(body["locations"]) == 2
    # Primary should be first
    assert body["locations"][0]["assignment_type"] == "primary"
    assert body["locations"][1]["assignment_type"] == "secondary"


def test_update_employee_location_assignment(client, hr_manager_auth, make_test_employee, test_institution):
    """Test updating an employee's location assignment."""
    # Create location
    location_data = {
        "name": "Update Location",
        "code": "UPD_001",
        "location_type": "branch",
    }
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    emp = make_test_employee()

    # Assign to location
    assignment = {
        "location_id": location_id,
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201

    # Update assignment
    updates = {
        "end_date": "2026-12-31",
        "department_at_location": "Engineering",
    }
    res = client.put(
        f"/api/employees/{emp['employee_id']}/locations/{location_id}",
        headers=hr_manager_auth,
        json=updates,
    )
    assert res.status_code == 200
    body = res.json()

    assert body["end_date"] == "2026-12-31"
    assert body["department_at_location"] == "Engineering"


def test_remove_employee_from_location(client, hr_manager_auth, make_test_employee, test_institution):
    """Test removing an employee from a location."""
    # Create location
    location_data = {
        "name": "Remove Location",
        "code": "REM_001",
        "location_type": "branch",
    }
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    emp = make_test_employee()

    # Assign to location
    assignment = {
        "location_id": location_id,
        "assignment_type": "primary",
        "start_date": "2026-08-01",
    }
    res = client.post(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
        json=assignment,
    )
    assert res.status_code == 201

    # Remove from location
    res = client.delete(
        f"/api/employees/{emp['employee_id']}/locations/{location_id}",
        headers=hr_manager_auth,
    )
    assert res.status_code == 200

    # Verify is_active is now 0
    res = client.get(
        f"/api/employees/{emp['employee_id']}/locations",
        headers=hr_manager_auth,
    )
    assert res.status_code == 200
    body = res.json()
    # No active assignments
    assert len(body["locations"]) == 0


def test_bulk_assign_locations(client, hr_manager_auth, make_test_employee, test_institution):
    """Test bulk assigning employees to locations."""
    # Create location
    location_data = {
        "name": "Bulk Location",
        "code": "BULK_001",
        "location_type": "branch",
    }
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    # Create employees
    employees = [make_test_employee() for _ in range(3)]

    # Bulk assign
    assignments = [
        {
            "employee_id": emp["employee_id"],
            "location_id": location_id,
            "assignment_type": "primary",
            "start_date": "2026-08-01",
        }
        for emp in employees
    ]

    res = client.post(
        "/api/employees/bulk-assign-locations",
        headers=hr_manager_auth,
        json={"assignments": assignments},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["created"] == 3
    assert len(body["errors"]) == 0


def test_bulk_assign_locations_with_errors(client, hr_manager_auth, make_test_employee, test_institution):
    """Test bulk assign with some invalid assignments."""
    location_data = {
        "name": "Error Location",
        "code": "ERR_001",
        "location_type": "branch",
    }
    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    location_id = res.json()["id"]

    emp = make_test_employee()

    assignments = [
        {
            "employee_id": emp["employee_id"],
            "location_id": location_id,
            "assignment_type": "primary",
            "start_date": "2026-08-01",
        },
        {
            "employee_id": "NONEXISTENT",
            "location_id": location_id,
            "assignment_type": "primary",
            "start_date": "2026-08-01",
        },
    ]

    res = client.post(
        "/api/employees/bulk-assign-locations",
        headers=hr_manager_auth,
        json={"assignments": assignments},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["created"] == 1
    assert len(body["errors"]) == 1
    assert "NONEXISTENT" in str(body["errors"])


def test_get_institution_location_summary(client, hr_manager_auth, test_institution, make_test_employee):
    """Test getting location summary for an institution."""
    # Create locations
    locations = []
    for i in range(2):
        location_data = {
            "name": f"Summary Location {i+1}",
            "code": f"SUM_{i+1:03d}",
            "location_type": "branch",
        }
        res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
        locations.append(res.json())

    # Assign employees
    for i, loc in enumerate(locations):
        for j in range(i + 1):  # Loc 1 has 1 emp, Loc 2 has 2 emp
            emp = make_test_employee()
            assignment = {
                "location_id": loc["id"],
                "assignment_type": "primary",
                "start_date": "2026-08-01",
            }
            client.post(
                f"/api/employees/{emp['employee_id']}/locations",
                headers=hr_manager_auth,
                json=assignment,
            )

    # Get summary
    inst_id = test_institution["id"]
    res = client.get(
        f"/api/institutions/{inst_id}/location-summary",
        headers=hr_manager_auth,
    )
    assert res.status_code == 200
    body = res.json()

    assert body["total_locations"] == 2
    assert body["active_locations"] == 2
    assert body["total_employees"] == 3  # 1 + 2


def test_location_manager_optional(client, hr_manager_auth, test_institution):
    """Test that location manager is optional."""
    location_data = {
        "name": "No Manager Location",
        "code": "NO_MGR",
        "location_type": "branch",
        # No manager_user_id
    }

    res = client.post("/api/locations", headers=hr_manager_auth, json=location_data)
    assert res.status_code == 201
    body = res.json()

    assert body["manager_user_id"] is None
