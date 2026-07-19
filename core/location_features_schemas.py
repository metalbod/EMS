"""Pydantic schemas for location features: transfers, alerts, budgets, reports."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import date, datetime


# Transfer Request Schemas
class LocationTransferCreate(BaseModel):
    from_location_id: Optional[int] = Field(None, description="Current location ID")
    to_location_id: int = Field(..., description="Target location ID")
    transfer_date: Optional[date] = Field(None, description="Planned transfer date")


class LocationTransferResponse(BaseModel):
    id: int
    employee_id: str
    from_location_id: Optional[int]
    to_location_id: int
    transfer_date: Optional[date]
    status: str  # Pending, Approved, Rejected, Completed
    requested_by_user_id: Optional[int]
    approved_by_user_id: Optional[int]
    rejection_reason: Optional[str]
    created_at: str


# Capacity Alert Schemas
class CapacityAlert(BaseModel):
    id: int
    location_id: int
    alert_level: str  # Warning, Critical
    triggered_at: str
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[int]
    is_resolved: bool
    resolved_at: Optional[str]


class CapacityAlertAcknowledge(BaseModel):
    acknowledged_at: Optional[str] = Field(None, description="Acknowledge time")


# Budget Schemas
class LocationBudgetCreate(BaseModel):
    period_start: date
    period_end: date
    budget_amount: float


class LocationBudgetUpdate(BaseModel):
    budget_amount: Optional[float]
    actual_amount: Optional[float]


class LocationBudgetResponse(BaseModel):
    id: int
    location_id: int
    period_start: date
    period_end: date
    budget_amount: float
    actual_amount: Optional[float]
    created_at: str
    updated_at: str


# Assignment History Schemas
class AssignmentHistoryEntry(BaseModel):
    id: int
    location_id: int
    location_name: str
    location_code: str
    assignment_type: str
    start_date: str
    end_date: Optional[str]
    ended_by_user_id: Optional[int]
    end_reason: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


class EmployeeAssignmentHistory(BaseModel):
    employee_id: str
    total_assignments: int
    current_assignment: Optional[AssignmentHistoryEntry]
    assignment_history: List[AssignmentHistoryEntry]


class LocationAssignmentHistory(BaseModel):
    location_id: int
    location_name: str
    total_assignments: int
    current_employees: int
    assignment_history: List[Dict[str, Any]]


# Employee Report Schemas
class EmployeeReportRow(BaseModel):
    employee_id: str
    full_name: str
    designation: str
    department: str
    employment_type: str
    start_date: str
    status: str
    primary_location: Optional[str]
    all_locations: List[str]
    phone: Optional[str]
    email: Optional[str]


class LocationEmployeeReport(BaseModel):
    location_id: int
    location_name: str
    location_code: str
    report_date: str
    total_employees: int
    active_employees: int
    inactive_employees: int
    employees: List[EmployeeReportRow]
    summary: Dict[str, Any]


class EmployeeLocationReportRequest(BaseModel):
    location_id: int
    departments: Optional[List[str]] = None
    status_filter: Optional[str] = None
    include_inactive: bool = False
    export_format: Optional[str] = "json"  # json, csv, excel


# Capacity Planning Schemas
class CapacityStatus(BaseModel):
    location_id: int
    location_name: str
    current_employees: int
    capacity: int
    utilization_percent: float
    warning_threshold: int
    critical_threshold: int
    status: str  # Healthy, Warning, Critical
    alert_triggered: bool
    recommendation: Optional[str]


class CapacityForecast(BaseModel):
    location_id: int
    location_name: str
    forecast_period: str  # next-30-days, next-quarter, next-year
    current_headcount: int
    projected_departures: int
    planned_leaves: int
    projected_headcount: int
    forecast_utilization: float
    recruitment_needed: int
    actions_recommended: List[str]


class LocationCapacityDashboard(BaseModel):
    location_id: int
    location_name: str
    current_status: CapacityStatus
    forecast: CapacityForecast
    recent_alerts: List[CapacityAlert]
    trend_data: List[Dict[str, Any]]
    budget_info: Optional[LocationBudgetResponse]


# Report Schedule Schemas
class ReportScheduleCreate(BaseModel):
    name: str
    report_type: str
    location_id: Optional[int]
    frequency: str  # Daily, Weekly, Monthly
    scheduled_day_of_week: Optional[int]
    scheduled_day_of_month: Optional[int]
    email_recipients: Optional[List[str]]
    format: str = "CSV"


class ReportScheduleResponse(BaseModel):
    id: int
    name: str
    report_type: str
    location_id: Optional[int]
    frequency: str
    format: str
    is_active: bool
    email_recipients: Optional[List[str]]
    created_at: str


# Payroll by Location Schemas
class LocationPayrollSummary(BaseModel):
    location_id: int
    location_name: str
    location_code: str
    report_period: str
    total_employees: int
    payroll_run_status: Optional[str]
    total_gross_pay: float
    total_deductions: float
    total_net_pay: float
    average_salary: float
    budget_allocated: Optional[float]
    budget_variance: Optional[float]
    variance_percent: Optional[float]


class LocationPayrollDetail(BaseModel):
    location_id: int
    location_name: str
    period_start: str
    period_end: str
    payslips: List[Dict[str, Any]]
    summary: LocationPayrollSummary


class EmployeesByDepartmentReport(BaseModel):
    location_id: int
    location_name: str
    department: str
    headcount: int
    utilization_percent: float
    budget_allocation: Optional[float]
    actual_spend: Optional[float]
