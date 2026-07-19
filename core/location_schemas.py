"""Pydantic schemas for locations and location assignments."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


# Location schemas

class LocationBase(BaseModel):
    name: str = Field(..., description="Location name (e.g., 'Kuala Lumpur HQ')")
    code: str = Field(..., description="Location code (e.g., 'KL_HQ')")
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = Field(default="Malaysia", description="Country name")
    phone: Optional[str] = None
    manager_user_id: Optional[int] = Field(None, description="User ID of location manager (optional)")
    location_type: str = Field(default="branch", description="Type of location: hq, branch, warehouse, outlet")
    capacity: Optional[int] = Field(None, description="Maximum number of employees this location can have")


class LocationCreate(LocationBase):
    """Schema for creating a new location."""
    pass


class LocationUpdate(BaseModel):
    """Schema for updating a location."""
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    manager_user_id: Optional[int] = None
    location_type: Optional[str] = None
    capacity: Optional[int] = None


class LocationResponse(LocationBase):
    """Schema for location response."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 1,
            "institution_id": 5,
            "name": "Kuala Lumpur Headquarters",
            "code": "KL_HQ",
            "address": "123 Jln Merdeka",
            "city": "Kuala Lumpur",
            "state": "KL",
            "postal_code": "50050",
            "country": "Malaysia",
            "phone": "+603-1234-5678",
            "manager_user_id": None,
            "location_type": "hq",
            "is_active": True,
            "capacity": 100,
            "employee_count": 45,
            "created_at": "2026-08-01 10:00:00",
            "updated_at": "2026-08-01 10:00:00"
        }
    })

    id: int
    institution_id: int
    is_active: bool
    employee_count: int = Field(default=0, description="Number of active employees at this location")
    created_at: str
    updated_at: str


class LocationStatsResponse(BaseModel):
    """Statistics for a location."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "location_id": 1,
            "location_name": "KL HQ",
            "total_employees": 45,
            "active_employees": 44,
            "capacity": 100,
            "utilization_percent": 44,
            "employees_by_department": {
                "Engineering": 15,
                "Sales": 12,
                "Admin": 8
            },
            "employees_by_status": {
                "Active": 44,
                "On Leave": 1
            }
        }
    })

    location_id: int
    location_name: str
    total_employees: int
    active_employees: int
    capacity: Optional[int] = None
    utilization_percent: Optional[int] = None
    employees_by_department: Dict[str, int] = Field(default_factory=dict)
    employees_by_status: Dict[str, int] = Field(default_factory=dict)


class LocationSummaryResponse(BaseModel):
    """Summary of all locations for an institution."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total_locations": 5,
            "active_locations": 5,
            "total_employees": 200,
            "locations": [
                {"name": "KL HQ", "code": "KL_HQ", "employee_count": 45},
                {"name": "PJ Branch", "code": "PJ_BR", "employee_count": 38}
            ]
        }
    })

    total_locations: int
    active_locations: int
    total_employees: int
    locations: List[Dict[str, Any]]


# Employee location assignment schemas

class EmployeeLocationAssignmentBase(BaseModel):
    location_id: int = Field(..., description="ID of the location")
    assignment_type: str = Field(default="primary", description="Type: primary, secondary, temporary")
    start_date: str = Field(..., description="Assignment start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="Assignment end date (YYYY-MM-DD), NULL = ongoing")
    reports_to_id: Optional[str] = Field(None, description="Employee ID of location-specific manager")
    department_at_location: Optional[str] = Field(None, description="Department assignment at this location")


class EmployeeLocationAssignmentCreate(EmployeeLocationAssignmentBase):
    """Schema for creating an employee location assignment."""
    pass


class EmployeeLocationAssignmentUpdate(BaseModel):
    """Schema for updating an employee location assignment."""
    assignment_type: Optional[str] = None
    end_date: Optional[str] = None
    reports_to_id: Optional[str] = None
    department_at_location: Optional[str] = None


class EmployeeLocationAssignmentResponse(EmployeeLocationAssignmentBase):
    """Schema for employee location assignment response."""
    id: int
    employee_id: str
    institution_id: int
    is_active: bool
    created_at: str
    updated_at: str


class EmployeeLocationsResponse(BaseModel):
    """List of locations where an employee is assigned."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "employee_id": "EMP001",
            "locations": [
                {
                    "location_id": 1,
                    "location_name": "KL HQ",
                    "location_code": "KL_HQ",
                    "assignment_type": "primary",
                    "start_date": "2026-01-01",
                    "end_date": None
                }
            ]
        }
    })

    employee_id: str
    locations: List[Dict[str, Any]]


class BulkLocationAssignment(BaseModel):
    """Schema for bulk assigning employees to locations."""
    employee_id: str
    location_id: int
    assignment_type: str = Field(default="primary", description="Type: primary, secondary, temporary")
    start_date: str
    end_date: Optional[str] = None


class BulkLocationAssignmentRequest(BaseModel):
    """Request body for bulk location assignments."""
    assignments: List[BulkLocationAssignment]


class BulkLocationAssignmentResponse(BaseModel):
    """Response from bulk location assignment."""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "created": 98,
            "errors": [
                {"employee_id": "EMP002", "reason": "Employee not found"}
            ]
        }
    })

    created: int
    errors: List[Dict[str, Any]] = Field(default_factory=list)
