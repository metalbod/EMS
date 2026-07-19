"""API endpoints for managing locations and employee location assignments."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from db import get_db, IntegrityError
from core.deps import get_current_user
from core.location_schemas import (
    LocationCreate,
    LocationUpdate,
    LocationResponse,
    LocationStatsResponse,
    LocationSummaryResponse,
    EmployeeLocationAssignmentCreate,
    EmployeeLocationAssignmentResponse,
    EmployeeLocationAssignmentUpdate,
    EmployeeLocationsResponse,
    BulkLocationAssignmentRequest,
    BulkLocationAssignmentResponse,
)

logger = logging.getLogger("ems.locations")
router = APIRouter(prefix="/api", tags=["locations"])


@router.post("/locations")
async def create_location(
    location_data: LocationCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new location/outlet for the institution."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")
        if not inst_id:
            raise HTTPException(401, detail="Institution context required")

        # Check if location code is unique within institution
        existing = conn.execute(
            "SELECT id FROM locations WHERE institution_id = ? AND code = ?",
            (inst_id, location_data.code),
        ).fetchone()
        if existing:
            raise HTTPException(400, detail=f"Location code '{location_data.code}' already exists in this institution")

        # Insert location
        conn.execute(
            """
            INSERT INTO locations (
                institution_id, name, code, address, city, state, postal_code,
                country, phone, manager_user_id, location_type, capacity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inst_id,
                location_data.name,
                location_data.code,
                location_data.address,
                location_data.city,
                location_data.state,
                location_data.postal_code,
                location_data.country,
                location_data.phone,
                location_data.manager_user_id,
                location_data.location_type,
                location_data.capacity,
            ),
        )
        location_id = conn.lastrowid
        conn.commit()

        # Fetch and return created location
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()
        employee_count = conn.execute(
            "SELECT COUNT(*) FROM employee_location_assignments WHERE location_id = ? AND is_active = 1",
            (location_id,),
        ).fetchone()[0]

        return {
            **dict(location),
            "employee_count": employee_count,
        }
    finally:
        conn.close()


@router.get("/institutions/{inst_id}/locations")
async def list_locations(
    inst_id: int,
    is_active: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """List all locations for an institution."""
    conn = get_db()
    try:
        # Verify user has access to this institution
        if current_user.get("institution_id") != inst_id and current_user.get("role") != "superadmin":
            raise HTTPException(403, detail="Access denied to this institution")

        query = "SELECT * FROM locations WHERE institution_id = ?"
        params = [inst_id]

        if is_active is not None:
            query += " AND is_active = ?"
            params.append(is_active)

        query += " ORDER BY name"

        locations = conn.execute(query, params).fetchall()

        # Add employee count to each location
        result = []
        for loc in locations:
            loc_dict = dict(loc)
            employee_count = conn.execute(
                "SELECT COUNT(*) FROM employee_location_assignments WHERE location_id = ? AND is_active = 1",
                (loc["id"],),
            ).fetchone()[0]
            loc_dict["employee_count"] = employee_count
            result.append(loc_dict)

        return {
            "locations": result,
            "total_locations": len(result),
        }
    finally:
        conn.close()


@router.get("/locations/{location_id}")
async def get_location(
    location_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get location details including employee count and capacity."""
    conn = get_db()
    try:
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Verify user has access
        if current_user.get("institution_id") != location["institution_id"] and current_user.get("role") != "superadmin":
            raise HTTPException(403, detail="Access denied")

        employee_count = conn.execute(
            "SELECT COUNT(*) FROM employee_location_assignments WHERE location_id = ? AND is_active = 1",
            (location_id,),
        ).fetchone()[0]

        loc_dict = dict(location)
        loc_dict["employee_count"] = employee_count
        return loc_dict
    finally:
        conn.close()


@router.put("/locations/{location_id}")
async def update_location(
    location_id: int,
    location_data: LocationUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update location details."""
    conn = get_db()
    try:
        # Get location to verify access
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        if current_user.get("institution_id") != location["institution_id"] and current_user.get("role") != "superadmin":
            raise HTTPException(403, detail="Access denied")

        # Build update statement
        updates = {}
        for field in ["name", "address", "city", "state", "postal_code", "phone", "manager_user_id", "location_type", "capacity"]:
            value = getattr(location_data, field, None)
            if value is not None:
                updates[field] = value

        if not updates:
            return dict(location)

        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        query = f"UPDATE locations SET {set_clause} WHERE id = ?"

        conn.execute(query, (*updates.values(), location_id))
        conn.commit()

        # Return updated location
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()

        employee_count = conn.execute(
            "SELECT COUNT(*) FROM employee_location_assignments WHERE location_id = ? AND is_active = 1",
            (location_id,),
        ).fetchone()[0]

        loc_dict = dict(location)
        loc_dict["employee_count"] = employee_count
        return loc_dict
    finally:
        conn.close()


@router.delete("/locations/{location_id}")
async def delete_location(
    location_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Soft-delete a location by setting is_active = 0."""
    conn = get_db()
    try:
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        if current_user.get("institution_id") != location["institution_id"] and current_user.get("role") != "superadmin":
            raise HTTPException(403, detail="Access denied")

        conn.execute("UPDATE locations SET is_active = 0 WHERE id = ?", (location_id,))
        conn.commit()

        return {"detail": "Location deleted successfully"}
    finally:
        conn.close()


@router.get("/locations/{location_id}/stats")
async def get_location_stats(
    location_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get statistics for a location."""
    conn = get_db()
    try:
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        if current_user.get("institution_id") != location["institution_id"] and current_user.get("role") != "superadmin":
            raise HTTPException(403, detail="Access denied")

        # Get employee count
        total_employees = conn.execute(
            "SELECT COUNT(*) FROM employee_location_assignments WHERE location_id = ? AND is_active = 1",
            (location_id,),
        ).fetchone()[0]

        active_employees = conn.execute(
            """
            SELECT COUNT(DISTINCT e.id)
            FROM employee_location_assignments ela
            JOIN employees e ON ela.employee_id = e.employee_id
            WHERE ela.location_id = ? AND ela.is_active = 1 AND e.status = 'Active'
            """,
            (location_id,),
        ).fetchone()[0]

        # Get employees by department
        dept_rows = conn.execute(
            """
            SELECT COALESCE(ela.department_at_location, e.department) as dept, COUNT(*)
            FROM employee_location_assignments ela
            JOIN employees e ON ela.employee_id = e.employee_id
            WHERE ela.location_id = ? AND ela.is_active = 1 AND e.status = 'Active'
            GROUP BY dept
            ORDER BY COUNT(*) DESC
            """,
            (location_id,),
        ).fetchall()

        employees_by_department = {row[0]: row[1] for row in dept_rows} if dept_rows else {}

        # Get employees by status
        status_rows = conn.execute(
            """
            SELECT e.status, COUNT(*)
            FROM employee_location_assignments ela
            JOIN employees e ON ela.employee_id = e.employee_id
            WHERE ela.location_id = ? AND ela.is_active = 1
            GROUP BY e.status
            """,
            (location_id,),
        ).fetchall()

        employees_by_status = {row[0]: row[1] for row in status_rows} if status_rows else {}

        utilization_percent = None
        if location["capacity"]:
            utilization_percent = round(100.0 * total_employees / location["capacity"])

        return LocationStatsResponse(
            location_id=location["id"],
            location_name=location["name"],
            total_employees=total_employees,
            active_employees=active_employees,
            capacity=location["capacity"],
            utilization_percent=utilization_percent,
            employees_by_department=employees_by_department,
            employees_by_status=employees_by_status,
        )
    finally:
        conn.close()


@router.get("/institutions/{inst_id}/location-summary")
async def get_institution_location_summary(
    inst_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get summary of all locations for an institution."""
    conn = get_db()
    try:
        if current_user.get("institution_id") != inst_id and current_user.get("role") != "superadmin":
            raise HTTPException(403, detail="Access denied")

        locations = conn.execute(
            "SELECT id, name, code FROM locations WHERE institution_id = ? AND is_active = 1 ORDER BY name",
            (inst_id,),
        ).fetchall()

        total_employees = 0
        locations_data = []

        for loc in locations:
            emp_count = conn.execute(
                "SELECT COUNT(*) FROM employee_location_assignments WHERE location_id = ? AND is_active = 1",
                (loc["id"],),
            ).fetchone()[0]
            total_employees += emp_count
            locations_data.append({
                "name": loc["name"],
                "code": loc["code"],
                "employee_count": emp_count,
            })

        return LocationSummaryResponse(
            total_locations=len(locations),
            active_locations=len([l for l in locations]),
            total_employees=total_employees,
            locations=locations_data,
        )
    finally:
        conn.close()


# Employee Location Assignment endpoints

@router.post("/employees/{employee_id}/locations")
async def assign_employee_to_location(
    employee_id: str,
    assignment: EmployeeLocationAssignmentCreate,
    current_user: dict = Depends(get_current_user),
):
    """Assign an employee to a location."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()

        if not employee:
            raise HTTPException(404, detail="Employee not found")

        # Verify location exists
        location = conn.execute(
            "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
            (assignment.location_id, inst_id),
        ).fetchone()

        if not location:
            raise HTTPException(404, detail="Location not found")

        # Check for duplicate primary assignment
        if assignment.assignment_type == "primary":
            existing = conn.execute(
                """
                SELECT id FROM employee_location_assignments
                WHERE employee_id = ? AND assignment_type = 'primary' AND is_active = 1
                """,
                (employee_id,),
            ).fetchone()
            if existing:
                raise HTTPException(400, detail="Employee already has a primary location assignment")

        # Insert assignment
        conn.execute(
            """
            INSERT INTO employee_location_assignments (
                institution_id, employee_id, location_id, assignment_type,
                start_date, end_date, reports_to_id, department_at_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inst_id,
                employee_id,
                assignment.location_id,
                assignment.assignment_type,
                assignment.start_date,
                assignment.end_date,
                assignment.reports_to_id,
                assignment.department_at_location,
            ),
        )
        assignment_id = conn.lastrowid
        conn.commit()

        # Return created assignment
        result = conn.execute(
            "SELECT * FROM employee_location_assignments WHERE id = ?",
            (assignment_id,),
        ).fetchone()

        return dict(result)
    except IntegrityError as e:
        conn.rollback()
        if "unique" in str(e).lower():
            raise HTTPException(400, detail="Employee already assigned to this location with this assignment type")
        raise HTTPException(400, detail=str(e))
    finally:
        conn.close()


@router.get("/employees/{employee_id}/locations")
async def get_employee_locations(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all locations where an employee is assigned."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()

        if not employee:
            raise HTTPException(404, detail="Employee not found")

        assignments = conn.execute(
            """
            SELECT ela.*, l.name as location_name, l.code as location_code
            FROM employee_location_assignments ela
            JOIN locations l ON ela.location_id = l.id
            WHERE ela.employee_id = ? AND ela.institution_id = ?
            ORDER BY CASE WHEN ela.assignment_type = 'primary' THEN 1 ELSE 2 END,
                     ela.start_date DESC
            """,
            (employee_id, inst_id),
        ).fetchall()

        locations = []
        for asg in assignments:
            locations.append({
                "location_id": asg["location_id"],
                "location_name": asg["location_name"],
                "location_code": asg["location_code"],
                "assignment_type": asg["assignment_type"],
                "start_date": asg["start_date"],
                "end_date": asg["end_date"],
                "is_active": bool(asg["is_active"]),
            })

        return EmployeeLocationsResponse(
            employee_id=employee_id,
            locations=locations,
        )
    finally:
        conn.close()


@router.put("/employees/{employee_id}/locations/{location_id}")
async def update_employee_location_assignment(
    employee_id: str,
    location_id: int,
    updates: EmployeeLocationAssignmentUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update an employee's assignment to a location."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        # Verify assignment exists
        assignment = conn.execute(
            """
            SELECT * FROM employee_location_assignments
            WHERE employee_id = ? AND location_id = ? AND institution_id = ?
            """,
            (employee_id, location_id, inst_id),
        ).fetchone()

        if not assignment:
            raise HTTPException(404, detail="Location assignment not found")

        # Build update statement
        update_fields = {}
        for field in ["assignment_type", "end_date", "reports_to_id", "department_at_location"]:
            value = getattr(updates, field, None)
            if value is not None:
                update_fields[field] = value

        if not update_fields:
            return dict(assignment)

        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        query = f"UPDATE employee_location_assignments SET {set_clause} WHERE id = ?"

        conn.execute(query, (*update_fields.values(), assignment["id"]))
        conn.commit()

        # Return updated assignment
        result = conn.execute(
            "SELECT * FROM employee_location_assignments WHERE id = ?",
            (assignment["id"],),
        ).fetchone()

        return dict(result)
    finally:
        conn.close()


@router.delete("/employees/{employee_id}/locations/{location_id}")
async def remove_employee_from_location(
    employee_id: str,
    location_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Remove an employee from a location by setting end_date to today."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")

        assignment = conn.execute(
            """
            SELECT * FROM employee_location_assignments
            WHERE employee_id = ? AND location_id = ? AND institution_id = ?
            """,
            (employee_id, location_id, inst_id),
        ).fetchone()

        if not assignment:
            raise HTTPException(404, detail="Location assignment not found")

        # Set end_date to today (soft delete)
        conn.execute(
            """
            UPDATE employee_location_assignments
            SET end_date = to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD'), is_active = 0
            WHERE id = ?
            """,
            (assignment["id"],),
        )
        conn.commit()

        return {"detail": "Employee removed from location"}
    finally:
        conn.close()


@router.post("/employees/bulk-assign-locations")
async def bulk_assign_locations(
    request: BulkLocationAssignmentRequest,
    current_user: dict = Depends(get_current_user),
):
    """Bulk assign multiple employees to locations."""
    conn = get_db()
    try:
        inst_id = current_user.get("institution_id")
        created = 0
        errors = []

        for assignment_data in request.assignments:
            try:
                # Verify employee exists
                employee = conn.execute(
                    "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
                    (assignment_data.employee_id, inst_id),
                ).fetchone()

                if not employee:
                    errors.append({
                        "employee_id": assignment_data.employee_id,
                        "reason": "Employee not found",
                    })
                    continue

                # Verify location exists
                location = conn.execute(
                    "SELECT * FROM locations WHERE id = ? AND institution_id = ?",
                    (assignment_data.location_id, inst_id),
                ).fetchone()

                if not location:
                    errors.append({
                        "employee_id": assignment_data.employee_id,
                        "reason": f"Location {assignment_data.location_id} not found",
                    })
                    continue

                # Insert assignment
                conn.execute(
                    """
                    INSERT INTO employee_location_assignments (
                        institution_id, employee_id, location_id, assignment_type,
                        start_date, end_date
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inst_id,
                        assignment_data.employee_id,
                        assignment_data.location_id,
                        assignment_data.assignment_type,
                        assignment_data.start_date,
                        assignment_data.end_date,
                    ),
                )
                created += 1
            except IntegrityError as e:
                if "unique" in str(e).lower():
                    errors.append({
                        "employee_id": assignment_data.employee_id,
                        "reason": "Employee already assigned to this location with this type",
                    })
                else:
                    errors.append({
                        "employee_id": assignment_data.employee_id,
                        "reason": str(e),
                    })

        conn.commit()
        return BulkLocationAssignmentResponse(created=created, errors=errors)
    finally:
        conn.close()
