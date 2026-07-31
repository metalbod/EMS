"""Shared Pydantic response schemas for OpenAPI documentation."""
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


# Auth schemas
class InstitutionBrief(BaseModel):
    """The subset of an institution's columns needed for the logged-in-user
    header/branding — not the full InstitutionResponse (institution CRUD
    returns more than a session needs)."""
    id: int
    name: str
    code: str
    status: str
    logo_url: Optional[str] = None


class CurrentUserOut(BaseModel):
    """The one shape of "who's logged in" — returned by /login, /switch-role,
    and /me. Previously each of those three endpoints hand-assembled its own
    dict and drifted apart (roles as a string vs array, institution present
    vs missing, must_change_password present vs missing) — each drift was a
    real bug: crashed the frontend's role switcher, reverted institution
    branding on refresh, and left "No employees found" after a refresh. One
    model + one builder (core/deps.py's build_current_user_out) means a
    missing/wrong field fails at the response boundary, not in the browser.
    """
    id: int
    username: str
    full_name: str
    role: str
    roles: List[str]
    institution_id: Optional[int] = None
    department: Optional[str] = None
    employee_id: Optional[str] = None
    institution: Optional[InstitutionBrief] = None
    must_change_password: bool = False


class TokenResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra = {
        "example": {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer",
            "user": {"id": 1, "username": "admin", "role": "superadmin"}
        }
    })

    access_token: str
    token_type: str = "bearer"
    user: Optional[CurrentUserOut] = None


# User schemas
class UserResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra = {
        "example": {
            "id": 1,
            "username": "john.doe",
            "full_name": "John Doe",
            "email": "john@example.com",
            "role": "employee",
            "roles": ["employee"],
            "employee_id": "EMP001",
            "institution_id": 1,
            "is_active": True,
            "created_at": "2026-01-15 10:30:00"
        }
    })

    id: int
    username: str
    full_name: str
    email: Optional[str] = None
    role: str
    roles: Optional[List[str]] = None
    employee_id: Optional[str] = None
    institution_id: Optional[int] = None
    is_active: bool = True
    created_at: str


# Institution schemas
class InstitutionResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra = {
        "example": {
            "id": 1,
            "name": "Acme Corp",
            "code": "ACME",
            "status": "Active",
            "plan": "enterprise",
            "max_employees": 5000,
            "contact_name": "Jane Smith",
            "contact_email": "jane@acme.com",
            "phone": "+1-555-0100",
            "address": "123 Main St, City, State 12345",
            "logo_url": "https://example.com/logo.png",
            "created_at": "2025-06-01 08:00:00"
        }
    })

    id: int
    name: str
    code: str
    status: str
    plan: str
    max_employees: int
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    created_at: str


# Generic error response
class ErrorResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra = {
        "example": {
            "detail": "Not found"
        }
    })

    detail: str


# Health check
class HealthResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra = {
        "example": {
            "status": "ok"
        }
    })

    status: str
