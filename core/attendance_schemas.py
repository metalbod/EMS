"""Pydantic schemas for the Attendance module (shifts, clock-in/out,
attendance settings, HR review)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# SHIFTS
# ============================================================================

class ShiftBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    start_time: str = Field(..., description="HH:MM, 24-hour")
    end_time: str = Field(..., description="HH:MM, 24-hour")
    grace_period_minutes: int = Field(0, ge=0, le=480)


class ShiftCreate(ShiftBase):
    pass


class ShiftUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    grace_period_minutes: Optional[int] = Field(None, ge=0, le=480)
    is_active: Optional[bool] = None


class ShiftResponse(ShiftBase):
    id: int
    crosses_midnight: bool
    is_active: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# SHIFT ASSIGNMENTS
# ============================================================================

class ShiftAssignmentCreate(BaseModel):
    employee_id: str
    shift_id: int
    effective_from: str = Field(..., description="YYYY-MM-DD")
    effective_to: Optional[str] = Field(None, description="YYYY-MM-DD, null = ongoing")


class ShiftAssignmentResponse(BaseModel):
    id: int
    employee_id: str
    shift_id: int
    shift_name: Optional[str] = None
    effective_from: str
    effective_to: Optional[str] = None
    is_active: bool
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# ATTENDANCE SETTINGS
# ============================================================================

class AttendanceSettingCreate(BaseModel):
    department: Optional[str] = None
    employee_id: Optional[str] = None
    required: bool = True
    default_shift_id: Optional[int] = None


class AttendanceSettingUpdate(BaseModel):
    required: Optional[bool] = None
    default_shift_id: Optional[int] = None
    is_active: Optional[bool] = None


class AttendanceSettingResponse(BaseModel):
    id: int
    department: Optional[str] = None
    employee_id: Optional[str] = None
    required: bool
    default_shift_id: Optional[int] = None
    default_shift_name: Optional[str] = None
    is_active: bool
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# CLOCK IN / OUT
# ============================================================================

class ClockInRequest(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


class ClockOutRequest(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


class AttendanceRecordResponse(BaseModel):
    id: int
    employee_id: str
    work_date: str
    shift_id: Optional[int] = None
    shift_name: Optional[str] = None
    clock_in_at: Optional[str] = None
    clock_out_at: Optional[str] = None
    clock_in_distance_meters: Optional[int] = None
    outside_geofence: bool
    clock_in_source: str = "web"
    clock_out_source: Optional[str] = None
    worked_minutes: Optional[int] = None
    status: str
    suggested_action: Optional[str] = None
    reviewed_by_user_id: Optional[int] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[str] = None
    leave_application_id: Optional[int] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class AttendanceRecordWithEmployee(AttendanceRecordResponse):
    employee_name: Optional[str] = None
    employee_preferred_name: Optional[str] = None
    department: Optional[str] = None


# ============================================================================
# HR REVIEW / RESOLUTION
# ============================================================================

class AttendanceResolve(BaseModel):
    action: Literal["Excuse", "ReclassifyAsLeave", "ConfirmAbsent"]
    leave_type_id: Optional[int] = Field(None, description="Required when action=ReclassifyAsLeave")
    half_day: bool = Field(False, description="If true and action=ReclassifyAsLeave, applies 0.5 days_count")
    notes: Optional[str] = None


# ============================================================================
# DEVICES (external clock-in/out integrations, e.g. facial-recognition cameras)
# ============================================================================

class DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    location_id: Optional[int] = None


class DeviceResponse(BaseModel):
    id: int
    name: str
    location_id: Optional[int] = None
    location_name: Optional[str] = None
    key_prefix: str
    is_active: bool
    last_used_at: Optional[str] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class DeviceCreateResponse(DeviceResponse):
    api_key: str = Field(..., description="Full API key — shown once, never retrievable again")


# ============================================================================
# WEBHOOK (device-authenticated, X-Device-Api-Key header instead of a user JWT)
# ============================================================================

class DeviceClockEventRequest(BaseModel):
    employee_id: str
    event_type: Literal["in", "out"]
    event_time: Optional[str] = Field(None, description="ISO 8601 UTC timestamp; defaults to now if omitted")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="Facial-match confidence score, if the device reports one")
