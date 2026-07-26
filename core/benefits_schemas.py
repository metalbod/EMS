"""Pydantic schemas for the Benefits module."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


# ============================================================================
# PLAN TYPES (BENEFIT PLAN CATALOG)
# ============================================================================

class BenefitPlanBase(BaseModel):
    """Base benefit plan."""
    plan_name: str = Field(..., min_length=1, max_length=150)
    plan_category: Literal["Medical", "Dental", "Vision", "Life", "Disability", "Retirement", "Wellness", "Perks"]
    contribution_type: Literal["Fixed Premium", "Percent of Salary", "Reimbursement Cap"]
    employee_cost: Optional[float] = Field(None, ge=0)
    employer_cost: Optional[float] = Field(None, ge=0)
    plan_year: Optional[int] = None
    effective_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    description: Optional[str] = None
    carrier_name: Optional[str] = None
    carrier_group_policy_number: Optional[str] = None
    payroll_sync_enabled: bool = False


class BenefitPlanCreate(BenefitPlanBase):
    """Create a benefit plan."""
    pass


class BenefitPlanUpdate(BaseModel):
    """Update a benefit plan."""
    plan_name: Optional[str] = None
    status: Optional[Literal["Draft", "Active", "Closed"]] = None
    employee_cost: Optional[float] = Field(None, ge=0)
    employer_cost: Optional[float] = Field(None, ge=0)
    description: Optional[str] = None
    carrier_name: Optional[str] = None
    carrier_group_policy_number: Optional[str] = None
    payroll_sync_enabled: Optional[bool] = None


class BenefitPlanResponse(BenefitPlanBase):
    """Benefit plan response."""
    id: int
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ============================================================================
# ELIGIBILITY RULES (BY JOB LEVEL / PAY GRADE)
# ============================================================================

class EligibilityRuleCreate(BaseModel):
    """Create an eligibility rule for a plan. At least one of job_level_id/
    pay_grade_id must be set (enforced by a DB CHECK constraint too)."""
    job_level_id: Optional[int] = None
    pay_grade_id: Optional[int] = None


class EligibilityRuleResponse(BaseModel):
    """Eligibility rule response, with the level/grade name joined in so
    the UI doesn't need a second lookup per row."""
    id: int
    benefit_plan_id: int
    job_level_id: Optional[int] = None
    job_level_name: Optional[str] = None
    pay_grade_id: Optional[int] = None
    pay_grade_name: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class EligiblePlanResponse(BenefitPlanResponse):
    """A benefit plan an employee is eligible for, with the reason —
    'Open to all' when the plan has no eligibility rules, or which
    level/grade rule matched."""
    eligibility_reason: str


# ============================================================================
# ENROLLMENT & ADMINISTRATION
# ============================================================================

class EnrollmentPeriodCreate(BaseModel):
    """Create an open enrollment period."""
    period_name: str = Field(..., min_length=1, max_length=150)
    plan_year: int
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")


class EnrollmentPeriodUpdate(BaseModel):
    """Update an enrollment period (mainly status)."""
    status: Optional[Literal["Draft", "Open", "Closed"]] = None


class EnrollmentPeriodResponse(EnrollmentPeriodCreate):
    """Enrollment period response."""
    id: int
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class LifeEventCreate(BaseModel):
    """Submit a qualifying life event."""
    event_type: Literal["Marriage", "Divorce", "Childbirth", "Adoption", "Death of Dependent", "Loss of Other Coverage", "Other"]
    event_date: str = Field(..., description="YYYY-MM-DD")
    notes: Optional[str] = None


class LifeEventDecide(BaseModel):
    """Approve or reject a life event."""
    status: Literal["Approved", "Rejected"]


class LifeEventResponse(LifeEventCreate):
    """Life event response."""
    id: int
    employee_id: str
    status: str
    reviewed_by_user_id: Optional[int] = None
    review_date: Optional[str] = None
    window_end_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class LifeEventWithEmployee(LifeEventResponse):
    """Life event response with the employee's display name joined in."""
    employee_name: Optional[str] = None


class EnrollmentElect(BaseModel):
    """Elect or waive coverage under a plan."""
    benefit_plan_id: int
    status: Literal["Enrolled", "Waived"]
    life_event_id: Optional[int] = None
    # If set, this election is being made under an approved life event's
    # window rather than an open enrollment period — omit for a normal
    # open-enrollment election.


class EnrollmentResponse(BaseModel):
    """Benefit enrollment (election) response."""
    id: int
    employee_id: str
    benefit_plan_id: int
    enrollment_period_id: Optional[int] = None
    life_event_id: Optional[int] = None
    status: str
    employee_cost_snapshot: Optional[float] = None
    employer_cost_snapshot: Optional[float] = None
    effective_date: Optional[str] = None
    elected_at: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class EnrollmentWithPlan(EnrollmentResponse):
    """Enrollment response with the plan's name/category joined in."""
    plan_name: Optional[str] = None
    plan_category: Optional[str] = None


# ============================================================================
# DEPENDENT / BENEFICIARY MANAGEMENT
# ============================================================================

class DependentBase(BaseModel):
    """Base dependent/beneficiary."""
    full_name: str = Field(..., min_length=1, max_length=150)
    relationship: Literal["Spouse", "Child", "Domestic Partner", "Parent", "Other"]
    date_of_birth: Optional[str] = Field(None, description="YYYY-MM-DD")
    national_id: Optional[str] = None
    is_beneficiary: bool = False
    beneficiary_percentage: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None


class DependentCreate(DependentBase):
    """Add a dependent/beneficiary."""
    pass


class DependentUpdate(BaseModel):
    """Update a dependent/beneficiary."""
    full_name: Optional[str] = None
    relationship: Optional[Literal["Spouse", "Child", "Domestic Partner", "Parent", "Other"]] = None
    date_of_birth: Optional[str] = None
    national_id: Optional[str] = None
    is_beneficiary: Optional[bool] = None
    beneficiary_percentage: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None
    status: Optional[Literal["Active", "Removed"]] = None


class DependentResponse(DependentBase):
    """Dependent/beneficiary response."""
    id: int
    employee_id: str
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class EnrollmentDependentLink(BaseModel):
    """Attach a dependent to a specific enrollment (election) for coverage."""
    dependent_id: int


# ============================================================================
# CLAIMS TRACKING
# ============================================================================

class ClaimCreate(BaseModel):
    """Submit a benefit claim under a plan."""
    benefit_plan_id: int
    claim_date: str = Field(..., description="YYYY-MM-DD")
    amount_claimed: float = Field(..., gt=0)
    description: Optional[str] = None


class ClaimDecide(BaseModel):
    """Approve or reject a claim, optionally with a partial approved amount."""
    status: Literal["Approved", "Rejected"]
    amount_approved: Optional[float] = Field(None, ge=0)


class ClaimResponse(BaseModel):
    """Benefit claim response."""
    id: int
    employee_id: str
    benefit_plan_id: int
    claim_date: str
    amount_claimed: float
    amount_approved: Optional[float] = None
    description: Optional[str] = None
    status: str
    reviewed_by_user_id: Optional[int] = None
    review_date: Optional[str] = None
    payout_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ClaimWithDetails(ClaimResponse):
    """Claim response with employee name and plan name/category joined in."""
    employee_name: Optional[str] = None
    plan_name: Optional[str] = None
    plan_category: Optional[str] = None


# ============================================================================
# COMPLIANCE & REPORTING
# ============================================================================

class PlanUtilization(BaseModel):
    """Per-plan cost + utilization figures for the compliance report."""
    plan_id: int
    plan_name: str
    plan_category: str
    contribution_type: str
    status: str
    carrier_name: Optional[str] = None
    enrolled_count: int
    waived_count: int
    participation_rate: Optional[float] = None
    monthly_employer_cost_total: float
    monthly_employee_cost_total: float
    claims_submitted_count: int
    claims_paid_total: float


class ComplianceReport(BaseModel):
    """Institution-wide benefits cost analysis, utilization, and
    compliance-documentation summary."""
    generated_at: str
    total_active_plans: int
    total_enrolled_employees: int
    total_monthly_employer_cost: float
    total_monthly_employee_cost: float
    total_claims_paid_ytd: float
    plans: List[PlanUtilization]
    compliance_flags: List[str]


# ============================================================================
# DASHBOARD WIDGETS (HR/manager cost reporting + employee self-service)
# ============================================================================

class DepartmentCost(BaseModel):
    """Monthly benefits cost attributable to one department (Fixed
    Premium plans only — see get_benefits_dashboard for why)."""
    department: str
    enrolled_count: int
    monthly_employer_cost_total: float
    monthly_employee_cost_total: float


class PlanUtilizationBrief(BaseModel):
    """Lightweight per-plan utilization figure for the manager dashboard
    widget — enrollment counts plus claims paid YTD."""
    plan_name: str
    plan_category: str
    enrolled_count: int
    waived_count: int
    participation_rate: Optional[float] = None
    claims_claimed_ytd: float = 0.0
    claims_paid_ytd: float = 0.0


class BenefitsDashboardSummary(BaseModel):
    """HR/Compensation Manager/Manager dashboard widget: company-wide
    benefits cost and utilization at a glance, plus a cost breakdown by
    department. A trimmed, dashboard-sized sibling of ComplianceReport —
    that endpoint stays the full drill-down page, this one is sized for a
    homepage card."""
    total_active_plans: int
    total_enrolled_employees: int
    total_monthly_employer_cost: float
    total_monthly_employee_cost: float
    total_claims_paid_ytd: float
    department_costs: List[DepartmentCost]
    plan_utilization: List[PlanUtilizationBrief]


class ClaimBrief(BaseModel):
    """Lightweight claim entry for the employee's own dashboard widget."""
    id: int
    plan_name: str
    plan_category: str
    claim_date: str
    amount_claimed: float
    amount_approved: Optional[float] = None
    status: str


class BenefitBalance(BaseModel):
    """Remaining balance under a Reimbursement Cap plan the employee is
    enrolled in — e.g. 'RM500/year wellness allowance, RM320 used,
    RM180 left'. Only meaningful for Reimbursement Cap plans; Fixed
    Premium/Percent of Salary plans don't have a balance to draw down."""
    plan_name: str
    plan_category: str
    annual_cap: float
    used_amount: float
    remaining_amount: float


class MyBenefitsDashboard(BaseModel):
    """Employee's own dashboard widget: recent claims + any unutilized
    reimbursement-cap balances."""
    recent_claims: List[ClaimBrief]
    balances: List[BenefitBalance]
