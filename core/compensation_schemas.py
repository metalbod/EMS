"""Pydantic schemas for Compensation Framework."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, model_validator
from datetime import date


# ============================================================================
# PAY GRADES
# ============================================================================

class PayGradeBase(BaseModel):
    """Base pay grade schema."""
    grade_code: str = Field(..., min_length=1, max_length=20)
    grade_name: str = Field(..., min_length=1, max_length=100)
    grade_level: int = Field(..., ge=1, description="Hierarchy level (1=lowest)")
    min_salary: float = Field(..., gt=0)
    midpoint_salary: float = Field(..., gt=0)
    max_salary: float = Field(..., gt=0)
    description: Optional[str] = None


class PayGradeCreate(PayGradeBase):
    """Create pay grade."""
    pass


class PayGradeUpdate(BaseModel):
    """Update pay grade."""
    grade_name: Optional[str] = None
    grade_level: Optional[int] = None
    min_salary: Optional[float] = None
    midpoint_salary: Optional[float] = None
    max_salary: Optional[float] = None
    description: Optional[str] = None
    is_active: Optional[int] = None


class PayGradeResponse(PayGradeBase):
    """Pay grade response."""
    id: int
    is_active: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ============================================================================
# JOB LEVELS
# ============================================================================

class JobLevelBase(BaseModel):
    """Base job level schema."""
    level_code: str = Field(..., min_length=1, max_length=20)
    level_name: str = Field(..., min_length=1, max_length=100)
    level_order: int = Field(..., ge=1, description="1=entry level, ascending")
    description: Optional[str] = None


class JobLevelCreate(JobLevelBase):
    """Create job level."""
    pass


class JobLevelUpdate(BaseModel):
    """Update job level."""
    level_name: Optional[str] = None
    level_order: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[int] = None


class JobLevelResponse(JobLevelBase):
    """Job level response."""
    id: int
    is_active: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ============================================================================
# JOB ROLES
# ============================================================================

class JobRoleBase(BaseModel):
    """Base job role schema."""
    job_level_id: int
    role_name: str = Field(..., min_length=1, max_length=100)
    role_code: str = Field(..., min_length=1, max_length=20)
    description: Optional[str] = None
    department: Optional[str] = None
    required_experience_years: Optional[int] = None


class JobRoleCreate(JobRoleBase):
    """Create job role."""
    pass


class JobRoleUpdate(BaseModel):
    """Update job role."""
    role_name: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    required_experience_years: Optional[int] = None
    is_active: Optional[int] = None


class JobRoleResponse(JobRoleBase):
    """Job role response."""
    id: int
    is_active: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class JobRoleWithGrades(JobRoleResponse):
    """Job role with associated pay grades."""
    pay_grades: List[PayGradeResponse] = []


class JobRoleGradeMapping(BaseModel):
    """Lightweight grade reference for the job-roles list — just enough to
    render the 'Pay Grades' column (code/name + primary flag) without the
    full PayGradeResponse (salary bounds, description, etc.)."""
    id: int
    grade_code: str
    grade_name: str
    is_primary: int


class JobRoleListItem(JobRoleResponse):
    """Job role list entry with grade mappings embedded, so the frontend
    doesn't need a separate request per role to render them."""
    pay_grades: List[JobRoleGradeMapping] = []


# ============================================================================
# SALARY STRUCTURES
# ============================================================================

class SalaryComponentBase(BaseModel):
    """Base salary component."""
    component_name: str = Field(..., min_length=1, max_length=100)
    component_type: str = Field(..., description="'base', 'allowance', 'benefit', 'deduction'")
    amount: Optional[float] = None
    percentage_of_base: Optional[float] = None
    is_taxable: int = 1
    description: Optional[str] = None
    sort_order: int = 0


class SalaryComponentCreate(SalaryComponentBase):
    """Create salary component."""
    pass


class SalaryComponentResponse(SalaryComponentBase):
    """Salary component response."""
    id: int
    is_active: int
    created_at: str

    class Config:
        from_attributes = True


class SalaryStructureBase(BaseModel):
    """Base salary structure."""
    structure_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    structure_type: str = Field(..., description="'template', 'role', 'location', 'business_unit'")
    applicable_to_id: Optional[int] = None


class SalaryStructureCreate(SalaryStructureBase):
    """Create salary structure."""
    components: Optional[List[SalaryComponentCreate]] = []


class SalaryStructureUpdate(BaseModel):
    """Update salary structure."""
    structure_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[int] = None


class SalaryStructureResponse(SalaryStructureBase):
    """Salary structure response."""
    id: int
    is_active: int
    components: List[SalaryComponentResponse] = []
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ============================================================================
# EMPLOYEE COMPENSATION
# ============================================================================

class EmployeeCompensationBase(BaseModel):
    """Base employee compensation."""
    job_role_id: Optional[int] = None
    job_level_id: Optional[int] = None
    pay_grade_id: Optional[int] = None
    salary_structure_id: Optional[int] = None
    # Not client-supplied on create/update: the single source of truth for an
    # employee's salary is employees.basic_salary (what payroll actually
    # reads) — this is only ever set server-side, mirrored from that column,
    # so the two numbers can't drift apart. Still present here because the
    # response/history models return it.
    base_salary: float = 0
    effective_date: str = Field(..., description="YYYY-MM-DD")


class EmployeeCompensationCreate(EmployeeCompensationBase):
    """Create/update employee compensation (role/level/grade/effective date only —
    base_salary is ignored if sent; see EmployeeCompensationBase)."""
    pass


class EmployeeCompensationResponse(EmployeeCompensationBase):
    """Employee compensation response."""
    id: int
    employee_id: str
    is_current: int
    end_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class EmployeeCompensationDetail(EmployeeCompensationResponse):
    """Detailed employee compensation with related data."""
    job_level: Optional[JobLevelResponse] = None
    job_role: Optional[JobRoleResponse] = None
    pay_grade: Optional[PayGradeResponse] = None
    salary_structure: Optional[SalaryStructureResponse] = None


# ============================================================================
# SALARY CHANGES (AUDIT TRAIL)
# ============================================================================

class SalaryChangeBase(BaseModel):
    """Base salary change."""
    change_type: str = Field(..., description="'merit_increase', 'promotion', 'adjustment', 'role_change'")
    from_salary: float
    to_salary: float
    from_pay_grade_id: Optional[int] = None
    to_pay_grade_id: Optional[int] = None
    from_job_level_id: Optional[int] = None
    to_job_level_id: Optional[int] = None
    effective_date: str = Field(..., description="YYYY-MM-DD")
    reason: Optional[str] = None


class SalaryChangeCreate(SalaryChangeBase):
    """Create salary change."""
    pass


class SalaryChangeResponse(SalaryChangeBase):
    """Salary change response."""
    id: int
    employee_id: str
    approved_by_user_id: Optional[int] = None
    approval_date: Optional[str] = None
    status: str
    created_at: str

    class Config:
        from_attributes = True


# ============================================================================
# MERIT REVIEW
# ============================================================================

class MeritReviewCycleBase(BaseModel):
    """Base merit review cycle."""
    cycle_name: str = Field(..., min_length=1, max_length=100)
    review_year: int
    cycle_start_date: str = Field(..., description="YYYY-MM-DD")
    cycle_end_date: str = Field(..., description="YYYY-MM-DD")
    submission_deadline: str = Field(..., description="YYYY-MM-DD")
    budget_pool_amount: Optional[float] = None
    description: Optional[str] = None


class MeritReviewCycleCreate(MeritReviewCycleBase):
    """Create merit review cycle."""
    pass


class MeritReviewCycleResponse(MeritReviewCycleBase):
    """Merit review cycle response."""
    id: int
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class MeritRecommendationBase(BaseModel):
    """Base merit recommendation."""
    employee_id: str
    current_salary: float
    recommended_increase_percent: float = Field(..., ge=0, le=100)
    recommended_new_salary: float
    reason: Optional[str] = None


class MeritRecommendationCreate(MeritRecommendationBase):
    """Create merit recommendation.

    current_salary/recommended_increase_percent/recommended_new_salary were
    stored and trusted as independent fields even though they're
    mathematically related — nothing stopped them disagreeing (e.g. a typo
    in one field with no cross-check against the other). Enforced only here,
    not on MeritRecommendationBase/Response: a handful of existing rows in
    this shared DB (see tests/conftest.py's header note — no separate test
    DB) predate this check and would fail it, so reading them back must stay
    permissive; only new submissions are held to the invariant.
    """
    @model_validator(mode="after")
    def check_new_salary_matches_percent(self):
        expected = self.current_salary * (1 + self.recommended_increase_percent / 100)
        tolerance = max(5.0, abs(self.current_salary) * 0.005)  # RM5 or 0.5%, whichever is larger — allows reasonable manual rounding
        if abs(expected - self.recommended_new_salary) > tolerance:
            raise ValueError(
                f"recommended_new_salary ({self.recommended_new_salary:,.2f}) doesn't match "
                f"current_salary * (1 + recommended_increase_percent/100) = {expected:,.2f} "
                f"(within RM{tolerance:,.2f} tolerance)"
            )
        return self


class MeritRecommendationApprove(BaseModel):
    """Approve merit recommendation."""
    approval_status: Literal["Approved", "Rejected"]
    approval_date: Optional[str] = None


class MeritRecommendationResponse(MeritRecommendationBase):
    """Merit recommendation response."""
    id: int
    merit_review_cycle_id: int
    recommended_by_user_id: Optional[int] = None
    approval_status: str
    approved_by_user_id: Optional[int] = None
    approval_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class MeritRecommendationWithEmployee(MeritRecommendationResponse):
    """Merit recommendation response with the employee's display name joined in."""
    employee_name: Optional[str] = None


# ============================================================================
# VARIABLE PAY: BONUS / INCENTIVE PLANS
# ============================================================================

class BonusPlanBase(BaseModel):
    """Base bonus/incentive plan."""
    plan_name: str = Field(..., min_length=1, max_length=150)
    plan_type: Literal["Annual", "Spot", "Sign-on", "Retention", "Referral", "Other"]
    plan_year: Optional[int] = None
    period_start: Optional[str] = Field(None, description="YYYY-MM-DD")
    period_end: Optional[str] = Field(None, description="YYYY-MM-DD")
    budget_pool_amount: Optional[float] = None
    description: Optional[str] = None


class BonusPlanCreate(BonusPlanBase):
    """Create bonus plan."""
    pass


class BonusPlanUpdate(BaseModel):
    """Update bonus plan."""
    plan_name: Optional[str] = None
    status: Optional[Literal["Draft", "Active", "Closed"]] = None
    budget_pool_amount: Optional[float] = None
    description: Optional[str] = None


class BonusPlanResponse(BonusPlanBase):
    """Bonus plan response."""
    id: int
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class BonusPayoutBase(BaseModel):
    """Base bonus payout."""
    employee_id: str
    target_amount: Optional[float] = None
    awarded_amount: float = Field(..., gt=0)
    reason: Optional[str] = None


class BonusPayoutCreate(BonusPayoutBase):
    """Create a bonus payout under a plan."""
    pass


class BonusPayoutDecide(BaseModel):
    """Approve or reject a bonus payout."""
    status: Literal["Approved", "Rejected"]


class BonusPayoutResponse(BonusPayoutBase):
    """Bonus payout response."""
    id: int
    bonus_plan_id: int
    status: str
    recommended_by_user_id: Optional[int] = None
    approved_by_user_id: Optional[int] = None
    approval_date: Optional[str] = None
    payout_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class BonusPayoutWithEmployee(BonusPayoutResponse):
    """Bonus payout with the employee's display name joined in."""
    employee_name: Optional[str] = None


# ============================================================================
# VARIABLE PAY: COMMISSION STRUCTURES
# ============================================================================

class CommissionPlanBase(BaseModel):
    """Base commission plan."""
    plan_name: str = Field(..., min_length=1, max_length=150)
    plan_type: Literal["Flat Rate", "Tiered", "Quota-based"]
    default_rate_percent: Optional[float] = Field(None, ge=0, le=100)
    plan_year: Optional[int] = None
    period_start: Optional[str] = Field(None, description="YYYY-MM-DD")
    period_end: Optional[str] = Field(None, description="YYYY-MM-DD")
    description: Optional[str] = None


class CommissionPlanCreate(CommissionPlanBase):
    """Create commission plan."""
    pass


class CommissionPlanUpdate(BaseModel):
    """Update commission plan."""
    plan_name: Optional[str] = None
    status: Optional[Literal["Draft", "Active", "Closed"]] = None
    default_rate_percent: Optional[float] = Field(None, ge=0, le=100)
    description: Optional[str] = None


class CommissionPlanResponse(CommissionPlanBase):
    """Commission plan response."""
    id: int
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CommissionEntryBase(BaseModel):
    """Base commission entry."""
    employee_id: str
    sales_amount: float = Field(..., gt=0)
    quota_target: Optional[float] = None
    commission_rate_percent: float = Field(..., ge=0, le=100)
    notes: Optional[str] = None


class CommissionEntryCreate(CommissionEntryBase):
    """Create a commission entry under a plan. calculated_commission is
    derived server-side (sales_amount x commission_rate_percent) rather
    than trusted from the client."""
    pass


class CommissionEntryDecide(BaseModel):
    """Approve or reject a commission entry."""
    status: Literal["Approved", "Rejected"]


class CommissionEntryResponse(CommissionEntryBase):
    """Commission entry response."""
    id: int
    commission_plan_id: int
    calculated_commission: float
    status: str
    recommended_by_user_id: Optional[int] = None
    approved_by_user_id: Optional[int] = None
    approval_date: Optional[str] = None
    payout_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CommissionEntryWithEmployee(CommissionEntryResponse):
    """Commission entry response with the employee's display name joined in."""
    employee_name: Optional[str] = None


# ============================================================================
# EQUITY & LONG-TERM INCENTIVES
# ============================================================================

class EquityGrantBase(BaseModel):
    """Base equity grant."""
    employee_id: str
    grant_type: Literal["ISO", "NSO", "RSU", "ESPP", "Phantom"]
    grant_date: str = Field(..., description="YYYY-MM-DD")
    quantity: int = Field(..., gt=0)
    strike_price: Optional[float] = Field(None, ge=0)
    fair_market_value_at_grant: Optional[float] = Field(None, ge=0)
    vesting_start_date: str = Field(..., description="YYYY-MM-DD")
    vesting_years: int = Field(4, ge=1, le=10)
    cliff_months: int = Field(12, ge=0, le=48)
    notes: Optional[str] = None


class EquityGrantCreate(EquityGrantBase):
    """Create an equity grant. Starts life as 'Pending Approval' — vesting
    events are only generated once HR approves it."""
    pass


class EquityGrantDecide(BaseModel):
    """Approve or reject an equity grant."""
    status: Literal["Approved", "Rejected"]


class EquityGrantResponse(EquityGrantBase):
    """Equity grant response."""
    id: int
    status: str
    recommended_by_user_id: Optional[int] = None
    approved_by_user_id: Optional[int] = None
    approval_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class EquityGrantWithEmployee(EquityGrantResponse):
    """Equity grant response with the employee's display name joined in."""
    employee_name: Optional[str] = None


class VestingEventResponse(BaseModel):
    """A single vesting tranche of an equity grant. settlement_price /
    cash_payout / payout_date are only populated for Phantom grants, where
    'Vested' isn't terminal — a further cash-settlement step follows."""
    id: int
    equity_grant_id: int
    vest_date: str
    quantity_vested: int
    status: str
    vested_at: Optional[str] = None
    settlement_price: Optional[float] = None
    cash_payout: Optional[float] = None
    payout_date: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class VestingEventSettle(BaseModel):
    """Cash-settle a Vested phantom stock tranche at a given per-unit price."""
    settlement_price: float = Field(..., ge=0)


class EquityGrantDetail(EquityGrantWithEmployee):
    """Equity grant with its full vesting schedule embedded."""
    vesting_events: List[VestingEventResponse] = []
    quantity_vested: int = 0
    quantity_unvested: int = 0


# ============================================================================
# TOTAL REWARDS STATEMENT
# ============================================================================

class TotalRewardsStatement(BaseModel):
    """Aggregated view of an employee's total compensation for a given
    calendar year: current base salary, plus variable pay actually earned
    (Approved/Paid bonus + commission), plus the salary-change and merit
    history that explains how the base salary got to where it is. Not a
    new table — pure read-side aggregation over pay_grades/employee_compensation,
    bonus_payouts, commission_entries, salary_changes, and merit_recommendations,
    the same tables the rest of the compensation module already writes to."""
    employee_id: str
    employee_name: str
    designation: Optional[str] = None
    department: Optional[str] = None
    year: int
    base_salary_monthly: Optional[float] = None
    base_salary_annualized: Optional[float] = None
    compensation_effective_date: Optional[str] = None
    bonus_ytd: float = 0
    commission_ytd: float = 0
    total_cash_compensation: float = 0
    salary_changes: List[SalaryChangeResponse] = []
    merit_history: List[MeritRecommendationResponse] = []


# ============================================================================
# PAY EQUITY ANALYSIS
# ============================================================================

class PayEquityItem(BaseModel):
    """Single pay equity analysis item."""
    analysis_type: str  # 'gender', 'department', 'role', 'location', 'tenure'
    category_1: str
    category_2: Optional[str] = None
    count_1: int
    count_2: Optional[int] = None
    avg_salary_1: float
    avg_salary_2: Optional[float] = None
    pay_gap_percent: Optional[float] = None
    flagged: int


class PayEquityReport(BaseModel):
    """Complete pay equity report."""
    analysis_date: str
    gender_gap: Optional[List[PayEquityItem]] = []
    department_gap: Optional[List[PayEquityItem]] = []
    role_consistency: Optional[List[PayEquityItem]] = []
    location_gap: Optional[List[PayEquityItem]] = []
    tenure_gap: Optional[List[PayEquityItem]] = []
    flagged_items: int
    excluded_no_compensation_count: int = Field(
        0, description="Employees with no current employee_compensation record — "
                        "not represented in any of the averages above."
    )


# ============================================================================
# BULK OPERATIONS
# ============================================================================

class BulkMeritIncrease(BaseModel):
    """Bulk merit increase request."""
    employee_ids: List[str]
    increase_percent: float = Field(..., ge=0, le=100)
    effective_date: str = Field(..., description="YYYY-MM-DD")
    reason: Optional[str] = None


class CompensationAnalyticsRequest(BaseModel):
    """Request for compensation analytics."""
    filter_by: Optional[str] = None  # 'department', 'location', 'role', 'pay_grade'
    filter_value: Optional[str] = None
    include_historical: bool = False
