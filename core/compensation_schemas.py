"""Pydantic schemas for Compensation Framework."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
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
    base_salary: float = Field(..., gt=0)
    effective_date: str = Field(..., description="YYYY-MM-DD")


class EmployeeCompensationCreate(EmployeeCompensationBase):
    """Create/update employee compensation."""
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
    """Create merit recommendation."""
    pass


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
