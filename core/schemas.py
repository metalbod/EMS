"""Shared Pydantic response schemas for OpenAPI documentation."""
from typing import Optional, List
from pydantic import BaseModel, Field


# Auth schemas
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Optional[dict] = None

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user": {"id": 1, "username": "admin", "role": "superadmin"}
            }
        }


# User schemas
class UserResponse(BaseModel):
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

    class Config:
        json_schema_extra = {
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
        }


# Institution schemas
class InstitutionResponse(BaseModel):
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

    class Config:
        json_schema_extra = {
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
        }


# Generic error response
class ErrorResponse(BaseModel):
    detail: str

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Not found"
            }
        }


# Health check
class HealthResponse(BaseModel):
    status: str

    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok"
            }
        }
