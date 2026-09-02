"""Pydantic schemas for the FR (facial-recognition attendance kiosk)
integration — see routers/fr_integration.py and docs/FR_INTEGRATION.md
for the full contract this implements."""
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class FrEmployeeOut(BaseModel):
    """One roster row — field names/casing match the FR contract exactly
    (ems_employee_id, lowercase active/inactive status, etc.), which is
    why this isn't just EmployeeOut: FR's shape is a deliberately narrow,
    stable external contract, independent of whatever EmployeeOut's own
    internal shape happens to look like."""
    ems_employee_id: str
    full_name: str
    display_name: str
    department: Optional[str] = None
    email: Optional[str] = None
    start_date: str
    date_of_birth: Optional[str] = None
    status: Literal["active", "inactive"]
    consent_recognition: bool
    consent_display_name: bool
    consent_dob: bool

    model_config = ConfigDict(from_attributes=True)


class FrAttendanceRow(BaseModel):
    ems_employee_id: str
    work_date: str = Field(..., description="YYYY-MM-DD, local calendar date")
    clock_in_ts: str = Field(..., description="ISO 8601 UTC timestamp")
    clock_out_ts: Optional[str] = Field(None, description="ISO 8601 UTC timestamp, or null if never clocked out")


class FrAttendanceRejection(BaseModel):
    ems_employee_id: str
    work_date: str
    reason: str


class FrAttendancePushResult(BaseModel):
    ok: bool
    accepted: int
    rejected: List[FrAttendanceRejection]
    detail: Optional[str] = None
