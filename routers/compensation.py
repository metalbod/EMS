"""API endpoints for Compensation Framework: Pay Grades, Job Levels, Salary Structures."""
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_schemas import (
    PayGradeCreate, PayGradeResponse, PayGradeUpdate,
    JobLevelCreate, JobLevelResponse, JobLevelUpdate,
    JobRoleCreate, JobRoleResponse, JobRoleUpdate, JobRoleWithGrades,
    SalaryStructureCreate, SalaryStructureResponse, SalaryStructureUpdate,
    EmployeeCompensationCreate, EmployeeCompensationResponse, EmployeeCompensationDetail,
    SalaryChangeCreate, SalaryChangeResponse,
    MeritReviewCycleCreate, MeritReviewCycleResponse,
    MeritRecommendationCreate, MeritRecommendationApprove, MeritRecommendationResponse,
    MeritRecommendationWithEmployee,
    PayEquityReport, PayEquityItem,
    BulkMeritIncrease,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])


# Helper: Check compensation access permissions
def require_hr_role(current_user: dict):
    """Require HR Manager or Payroll Manager role.

    Deliberately excludes hr_admin (previously included) — matches the
    frontend nav visibility change, so this isn't just a hidden menu with
    the API still wide open to a role that shouldn't see it."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "payroll_manager"]:
        raise HTTPException(403, detail="HR Manager or Payroll Manager access required")


def _add_hr_note(conn, inst_id: int, employee_id: str, body: str, username: str):
    """Log a compensation event (merit recommendation created/decided, salary
    adjusted) as an HR note on the employee's record, so it shows up in the
    same history HR already reviews on the employee profile — matches the
    existing note_type values used by routers/hr_notes.py's UI dropdown
    (General/Disciplinary/Performance/Warning/Commendation)."""
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?, ?, ?, ?, ?)",
        (inst_id, employee_id, "performance", body, username),
    )


# ============================================================================
# PAY GRADES ENDPOINTS
# ============================================================================

@router.post("/pay-grades", status_code=201)
async def create_pay_grade(
    payload: PayGradeCreate,
    current_user: dict = Depends(get_current_user),
) -> PayGradeResponse:
    """Create a new pay grade."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        # Validate salary progression
        if payload.min_salary > payload.midpoint_salary or payload.midpoint_salary > payload.max_salary:
            raise HTTPException(400, detail="Min <= Midpoint <= Max required")

        conn.execute(
            """
            INSERT INTO pay_grades (institution_id, grade_code, grade_name, grade_level,
                                   min_salary, midpoint_salary, max_salary, description,
                                   created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (inst_id, payload.grade_code, payload.grade_name, payload.grade_level,
             payload.min_salary, payload.midpoint_salary, payload.max_salary,
             payload.description, now, now),
        )
        conn.commit()
        grade_id = conn._last_id

        grade = conn.execute("SELECT * FROM pay_grades WHERE id = ?", (grade_id,)).fetchone()
        return PayGradeResponse(**dict(grade))

    finally:
        conn.close()


@router.get("/pay-grades")
async def list_pay_grades(
    current_user: dict = Depends(get_current_user),
) -> List[PayGradeResponse]:
    """List all pay grades."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        grades = conn.execute(
            "SELECT * FROM pay_grades WHERE institution_id = ? AND is_active = 1 ORDER BY grade_level",
            (inst_id,),
        ).fetchall()
        return [PayGradeResponse(**dict(g)) for g in grades]
    finally:
        conn.close()


@router.get("/pay-grades/{grade_id}")
async def get_pay_grade(
    grade_id: int,
    current_user: dict = Depends(get_current_user),
) -> PayGradeResponse:
    """Get pay grade details."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        grade = conn.execute(
            "SELECT * FROM pay_grades WHERE id = ? AND institution_id = ?",
            (grade_id, inst_id),
        ).fetchone()
        if not grade:
            raise HTTPException(404, detail="Pay grade not found")
        return PayGradeResponse(**dict(grade))
    finally:
        conn.close()


@router.put("/pay-grades/{grade_id}")
async def update_pay_grade(
    grade_id: int,
    payload: PayGradeUpdate,
    current_user: dict = Depends(get_current_user),
) -> PayGradeResponse:
    """Update pay grade."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        grade = conn.execute(
            "SELECT * FROM pay_grades WHERE id = ? AND institution_id = ?",
            (grade_id, inst_id),
        ).fetchone()
        if not grade:
            raise HTTPException(404, detail="Pay grade not found")

        # Use existing values if not provided
        min_sal = payload.min_salary or grade["min_salary"]
        mid_sal = payload.midpoint_salary or grade["midpoint_salary"]
        max_sal = payload.max_salary or grade["max_salary"]

        if min_sal > mid_sal or mid_sal > max_sal:
            raise HTTPException(400, detail="Min <= Midpoint <= Max required")

        updates = {
            "min_salary": min_sal,
            "midpoint_salary": mid_sal,
            "max_salary": max_sal,
            "description": payload.description if payload.description is not None else grade["description"],
            "is_active": payload.is_active if payload.is_active is not None else grade["is_active"],
        }

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        conn.execute(
            f"UPDATE pay_grades SET {set_clause} WHERE id = ?",
            (*updates.values(), grade_id),
        )
        conn.commit()

        updated = conn.execute("SELECT * FROM pay_grades WHERE id = ?", (grade_id,)).fetchone()
        return PayGradeResponse(**dict(updated))

    finally:
        conn.close()


# ============================================================================
# JOB LEVELS ENDPOINTS
# ============================================================================

@router.post("/job-levels", status_code=201)
async def create_job_level(
    payload: JobLevelCreate,
    current_user: dict = Depends(get_current_user),
) -> JobLevelResponse:
    """Create a new job level."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO job_levels (institution_id, level_code, level_name, level_order,
                                   description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (inst_id, payload.level_code, payload.level_name, payload.level_order,
             payload.description, now, now),
        )
        conn.commit()
        level_id = conn._last_id

        level = conn.execute("SELECT * FROM job_levels WHERE id = ?", (level_id,)).fetchone()
        return JobLevelResponse(**dict(level))

    finally:
        conn.close()


@router.get("/job-levels")
async def list_job_levels(
    current_user: dict = Depends(get_current_user),
) -> List[JobLevelResponse]:
    """List all job levels."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        levels = conn.execute(
            "SELECT * FROM job_levels WHERE institution_id = ? AND is_active = 1 ORDER BY level_order",
            (inst_id,),
        ).fetchall()
        return [JobLevelResponse(**dict(l)) for l in levels]
    finally:
        conn.close()


@router.get("/job-levels/{level_id}")
async def get_job_level(
    level_id: int,
    current_user: dict = Depends(get_current_user),
) -> JobLevelResponse:
    """Get job level details."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        level = conn.execute(
            "SELECT * FROM job_levels WHERE id = ? AND institution_id = ?",
            (level_id, inst_id),
        ).fetchone()
        if not level:
            raise HTTPException(404, detail="Job level not found")
        return JobLevelResponse(**dict(level))
    finally:
        conn.close()


@router.put("/job-levels/{level_id}")
async def update_job_level(
    level_id: int,
    payload: JobLevelUpdate,
    current_user: dict = Depends(get_current_user),
) -> JobLevelResponse:
    """Update job level."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        level = conn.execute(
            "SELECT * FROM job_levels WHERE id = ? AND institution_id = ?",
            (level_id, inst_id),
        ).fetchone()
        if not level:
            raise HTTPException(404, detail="Job level not found")

        updates = {}
        if payload.level_name:
            updates["level_name"] = payload.level_name
        if payload.level_order:
            updates["level_order"] = payload.level_order
        if payload.description is not None:
            updates["description"] = payload.description
        if payload.is_active is not None:
            updates["is_active"] = payload.is_active

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            conn.execute(
                f"UPDATE job_levels SET {set_clause} WHERE id = ?",
                (*updates.values(), level_id),
            )
            conn.commit()

        updated = conn.execute("SELECT * FROM job_levels WHERE id = ?", (level_id,)).fetchone()
        return JobLevelResponse(**dict(updated))

    finally:
        conn.close()


# ============================================================================
# JOB ROLES ENDPOINTS
# ============================================================================

@router.post("/job-roles", status_code=201)
async def create_job_role(
    payload: JobRoleCreate,
    current_user: dict = Depends(get_current_user),
) -> JobRoleResponse:
    """Create a new job role."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        # Verify job level exists
        level = conn.execute(
            "SELECT * FROM job_levels WHERE id = ? AND institution_id = ?",
            (payload.job_level_id, inst_id),
        ).fetchone()
        if not level:
            raise HTTPException(404, detail="Job level not found")

        conn.execute(
            """
            INSERT INTO job_roles (institution_id, job_level_id, role_name, role_code,
                                  description, department, required_experience_years,
                                  created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (inst_id, payload.job_level_id, payload.role_name, payload.role_code,
             payload.description, payload.department, payload.required_experience_years,
             now, now),
        )
        conn.commit()
        role_id = conn._last_id

        role = conn.execute("SELECT * FROM job_roles WHERE id = ?", (role_id,)).fetchone()
        return JobRoleResponse(**dict(role))

    finally:
        conn.close()


@router.get("/job-roles")
async def list_job_roles(
    current_user: dict = Depends(get_current_user),
) -> List[JobRoleResponse]:
    """List all job roles."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        roles = conn.execute(
            "SELECT * FROM job_roles WHERE institution_id = ? AND is_active = 1",
            (inst_id,),
        ).fetchall()
        return [JobRoleResponse(**dict(r)) for r in roles]
    finally:
        conn.close()


@router.get("/job-roles/{role_id}/pay-grades")
async def list_role_pay_grades(
    role_id: int,
    current_user: dict = Depends(get_current_user),
):
    """List pay grades mapped to a job role."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        role = conn.execute(
            "SELECT * FROM job_roles WHERE id = ? AND institution_id = ?",
            (role_id, inst_id),
        ).fetchone()
        if not role:
            raise HTTPException(404, detail="Job role not found")

        rows = conn.execute(
            """
            SELECT g.id, g.grade_code, g.grade_name, m.is_primary
            FROM job_role_pay_grades m
            JOIN pay_grades g ON g.id = m.pay_grade_id
            WHERE m.job_role_id = ?
            ORDER BY m.is_primary DESC, g.grade_level
            """,
            (role_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/job-roles/{role_id}/pay-grades/{grade_id}", status_code=201)
async def map_role_to_grade(
    role_id: int,
    grade_id: int,
    is_primary: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """Map a job role to one or more pay grades."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        # Verify role exists
        role = conn.execute(
            "SELECT * FROM job_roles WHERE id = ? AND institution_id = ?",
            (role_id, inst_id),
        ).fetchone()
        if not role:
            raise HTTPException(404, detail="Job role not found")

        # Verify grade exists
        grade = conn.execute(
            "SELECT * FROM pay_grades WHERE id = ? AND institution_id = ?",
            (grade_id, inst_id),
        ).fetchone()
        if not grade:
            raise HTTPException(404, detail="Pay grade not found")

        # Create mapping
        conn.execute(
            "INSERT INTO job_role_pay_grades (job_role_id, pay_grade_id, is_primary, created_at) VALUES (?, ?, ?, ?)",
            (role_id, grade_id, 1 if is_primary else 0, datetime.utcnow().isoformat()),
        )
        conn.commit()

        return {"status": "mapped", "role_id": role_id, "grade_id": grade_id, "is_primary": is_primary}

    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(400, detail="Role-grade mapping already exists")
        raise
    finally:
        conn.close()


# ============================================================================
# EMPLOYEE COMPENSATION ENDPOINTS
# ============================================================================

@router.post("/employees/{employee_id}/compensation", status_code=201)
async def set_employee_compensation(
    employee_id: str,
    payload: EmployeeCompensationCreate,
    current_user: dict = Depends(get_current_user),
) -> EmployeeCompensationResponse:
    """Set or update employee compensation."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        # Capture the outgoing salary (if any) before superseding it, so the
        # HR note below can record "from X to Y" rather than just the new
        # figure.
        prev_comp = conn.execute(
            "SELECT base_salary FROM employee_compensation WHERE employee_id = ? AND institution_id = ? AND is_current = 1",
            (employee_id, inst_id),
        ).fetchone()

        # Mark previous record as not current. employee_id alone is not a
        # safe filter here — it's only unique per institution (composite
        # unique with institution_id), so a bare WHERE employee_id=? could
        # match a same-numbered employee in a different institution for a
        # superadmin (bypass_rls=true) connection, where RLS itself won't
        # catch the cross-tenant row.
        conn.execute(
            "UPDATE employee_compensation SET is_current = 0, end_date = ? WHERE employee_id = ? AND institution_id = ? AND is_current = 1",
            (payload.effective_date, employee_id, inst_id),
        )

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO employee_compensation
            (institution_id, employee_id, job_role_id, job_level_id, pay_grade_id,
             salary_structure_id, base_salary, effective_date, is_current, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (inst_id, employee_id, payload.job_role_id, payload.job_level_id,
             payload.pay_grade_id, payload.salary_structure_id, payload.base_salary,
             payload.effective_date, now, now),
        )
        # Capture this INSERT's id before the HR note INSERT overwrites
        # conn._last_id.
        comp_id = conn._last_id

        if prev_comp and prev_comp["base_salary"] is not None:
            note_body = (
                f"Salary adjusted from RM {float(prev_comp['base_salary']):,.2f} to "
                f"RM {payload.base_salary:,.2f}, effective {payload.effective_date}."
            )
        else:
            note_body = f"Salary set to RM {payload.base_salary:,.2f}, effective {payload.effective_date}."
        _add_hr_note(conn, inst_id, employee_id, note_body, current_user["username"])

        conn.commit()

        comp = conn.execute(
            "SELECT * FROM employee_compensation WHERE id = ?",
            (comp_id,),
        ).fetchone()
        return EmployeeCompensationResponse(**dict(comp))

    finally:
        conn.close()


@router.get("/employees/{employee_id}/compensation")
async def get_employee_compensation(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
) -> EmployeeCompensationDetail:
    """Get current employee compensation."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        comp = conn.execute(
            """
            SELECT * FROM employee_compensation
            WHERE employee_id = ? AND institution_id = ? AND is_current = 1
            """,
            (employee_id, inst_id),
        ).fetchone()

        if not comp:
            raise HTTPException(404, detail="Employee compensation not found")

        comp_dict = dict(comp)

        # Load related data
        if comp["job_level_id"]:
            level = conn.execute("SELECT * FROM job_levels WHERE id = ?", (comp["job_level_id"],)).fetchone()
            comp_dict["job_level"] = dict(level) if level else None

        if comp["job_role_id"]:
            role = conn.execute("SELECT * FROM job_roles WHERE id = ?", (comp["job_role_id"],)).fetchone()
            comp_dict["job_role"] = dict(role) if role else None

        if comp["pay_grade_id"]:
            grade = conn.execute("SELECT * FROM pay_grades WHERE id = ?", (comp["pay_grade_id"],)).fetchone()
            comp_dict["pay_grade"] = dict(grade) if grade else None

        if comp["salary_structure_id"]:
            struct = conn.execute("SELECT * FROM salary_structures WHERE id = ?", (comp["salary_structure_id"],)).fetchone()
            comp_dict["salary_structure"] = dict(struct) if struct else None

        return EmployeeCompensationDetail(**comp_dict)

    finally:
        conn.close()


# ============================================================================
# SALARY CHANGES (AUDIT TRAIL)
# ============================================================================

@router.post("/salary-changes/{employee_id}", status_code=201)
async def record_salary_change(
    employee_id: str,
    payload: SalaryChangeCreate,
    current_user: dict = Depends(get_current_user),
) -> SalaryChangeResponse:
    """Record a salary change with audit trail."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO salary_changes
            (institution_id, employee_id, change_type, from_salary, to_salary,
             from_pay_grade_id, to_pay_grade_id, from_job_level_id, to_job_level_id,
             effective_date, reason, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
            """,
            (inst_id, employee_id, payload.change_type, payload.from_salary, payload.to_salary,
             payload.from_pay_grade_id, payload.to_pay_grade_id, payload.from_job_level_id,
             payload.to_job_level_id, payload.effective_date, payload.reason, now),
        )
        conn.commit()
        change_id = conn._last_id

        change = conn.execute("SELECT * FROM salary_changes WHERE id = ?", (change_id,)).fetchone()
        return SalaryChangeResponse(**dict(change))

    finally:
        conn.close()


@router.get("/salary-changes/{employee_id}")
async def get_salary_history(
    employee_id: str,
    limit: int = 10,
    current_user: dict = Depends(get_current_user),
) -> List[SalaryChangeResponse]:
    """Get salary change history for an employee."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        changes = conn.execute(
            """
            SELECT * FROM salary_changes
            WHERE employee_id = ? AND institution_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (employee_id, inst_id, limit),
        ).fetchall()
        return [SalaryChangeResponse(**dict(c)) for c in changes]
    finally:
        conn.close()


# ============================================================================
# MERIT REVIEW ENDPOINTS
# ============================================================================

@router.post("/merit-cycles", status_code=201)
async def create_merit_cycle(
    payload: MeritReviewCycleCreate,
    current_user: dict = Depends(get_current_user),
) -> MeritReviewCycleResponse:
    """Create a merit review cycle."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO merit_review_cycles
            (institution_id, cycle_name, review_year, cycle_start_date, cycle_end_date,
             submission_deadline, budget_pool_amount, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
            """,
            (inst_id, payload.cycle_name, payload.review_year, payload.cycle_start_date,
             payload.cycle_end_date, payload.submission_deadline, payload.budget_pool_amount,
             payload.description, now, now),
        )
        conn.commit()
        cycle_id = conn._last_id

        cycle = conn.execute("SELECT * FROM merit_review_cycles WHERE id = ?", (cycle_id,)).fetchone()
        return MeritReviewCycleResponse(**dict(cycle))

    finally:
        conn.close()


@router.get("/merit-cycles")
async def list_merit_cycles(
    current_user: dict = Depends(get_current_user),
) -> List[MeritReviewCycleResponse]:
    """List merit review cycles."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        cycles = conn.execute(
            "SELECT * FROM merit_review_cycles WHERE institution_id = ? ORDER BY review_year DESC",
            (inst_id,),
        ).fetchall()
        return [MeritReviewCycleResponse(**dict(c)) for c in cycles]
    finally:
        conn.close()


@router.get("/merit-cycles/{cycle_id}/recommendations")
async def list_merit_recommendations(
    cycle_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[MeritRecommendationWithEmployee]:
    """List merit recommendations for a review cycle, with employee names joined in."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        cycle = conn.execute(
            "SELECT * FROM merit_review_cycles WHERE id = ? AND institution_id = ?",
            (cycle_id, inst_id),
        ).fetchone()
        if not cycle:
            raise HTTPException(404, detail="Merit review cycle not found")

        # employee_id is only unique per institution, so the join must also
        # match institution_id — see the pay-equity report fix for the same
        # pattern (a bare employee_id join fans out across every tenant
        # reusing that code, e.g. auto-generated EMP0001/EMP0002/...).
        rows = conn.execute(
            """
            SELECT r.*, e.full_name AS employee_name
            FROM merit_recommendations r
            JOIN employees e ON r.employee_id = e.employee_id AND r.institution_id = e.institution_id
            WHERE r.merit_review_cycle_id = ? AND r.institution_id = ?
            ORDER BY r.created_at DESC
            """,
            (cycle_id, inst_id),
        ).fetchall()
        return [MeritRecommendationWithEmployee(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/merit-recommendations", status_code=201)
async def create_merit_recommendation(
    merit_cycle_id: int,
    payload: MeritRecommendationCreate,
    current_user: dict = Depends(get_current_user),
) -> MeritRecommendationResponse:
    """Create a merit recommendation."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        # Verify cycle exists
        cycle = conn.execute(
            "SELECT * FROM merit_review_cycles WHERE id = ? AND institution_id = ?",
            (merit_cycle_id, inst_id),
        ).fetchone()
        if not cycle:
            raise HTTPException(404, detail="Merit review cycle not found")

        # Verify employee exists
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (payload.employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO merit_recommendations
            (institution_id, merit_review_cycle_id, employee_id, current_salary,
             recommended_increase_percent, recommended_new_salary, reason,
             recommended_by_user_id, approval_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
            """,
            (inst_id, merit_cycle_id, payload.employee_id, payload.current_salary,
             payload.recommended_increase_percent, payload.recommended_new_salary,
             payload.reason, user_id, now, now),
        )
        # Capture this INSERT's id before any other statement runs — _last_id
        # gets overwritten by the next INSERT (the HR note) otherwise.
        rec_id = conn._last_id

        note_body = (
            f"Merit recommendation submitted under '{cycle['cycle_name']}': "
            f"{payload.recommended_increase_percent:g}% increase "
            f"(RM {payload.current_salary:,.2f} → RM {payload.recommended_new_salary:,.2f})."
        )
        if payload.reason:
            note_body += f" Reason: {payload.reason}"
        _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

        conn.commit()

        rec = conn.execute(
            "SELECT * FROM merit_recommendations WHERE id = ?",
            (rec_id,),
        ).fetchone()
        return MeritRecommendationResponse(**dict(rec))

    finally:
        conn.close()


@router.put("/merit-recommendations/{recommendation_id}")
async def approve_merit_recommendation(
    recommendation_id: int,
    payload: MeritRecommendationApprove,
    current_user: dict = Depends(get_current_user),
) -> MeritRecommendationResponse:
    """Approve or reject merit recommendation."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        rec = conn.execute(
            "SELECT * FROM merit_recommendations WHERE id = ? AND institution_id = ?",
            (recommendation_id, inst_id),
        ).fetchone()
        if not rec:
            raise HTTPException(404, detail="Recommendation not found")

        cycle = conn.execute(
            "SELECT cycle_name FROM merit_review_cycles WHERE id = ?",
            (rec["merit_review_cycle_id"],),
        ).fetchone()
        cycle_name = cycle["cycle_name"] if cycle else "merit cycle"

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE merit_recommendations
            SET approval_status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.approval_status, user_id, payload.approval_date or now, now, recommendation_id),
        )

        note_body = (
            f"Merit recommendation ({rec['recommended_increase_percent']:g}% increase, "
            f"RM {rec['current_salary']:,.2f} → RM {rec['recommended_new_salary']:,.2f}) "
            f"under '{cycle_name}' was {payload.approval_status.lower()} by {current_user['username']}."
        )
        _add_hr_note(conn, inst_id, rec["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute(
            "SELECT * FROM merit_recommendations WHERE id = ?",
            (recommendation_id,),
        ).fetchone()
        return MeritRecommendationResponse(**dict(updated))

    finally:
        conn.close()


# ============================================================================
# PAY EQUITY ANALYSIS ENDPOINTS
# ============================================================================

@router.get("/pay-equity/report")
async def get_pay_equity_report(
    current_user: dict = Depends(get_current_user),
) -> PayEquityReport:
    """Get comprehensive pay equity analysis report."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        analysis_date = datetime.utcnow().isoformat()

        # Gender gap analysis
        gender_data = conn.execute(
            """
            SELECT e.gender, COUNT(*) as count, AVG(ec.base_salary) as avg_salary
            FROM employee_compensation ec
            JOIN employees e ON ec.employee_id = e.employee_id AND ec.institution_id = e.institution_id
            WHERE ec.institution_id = ? AND ec.is_current = 1
            GROUP BY e.gender
            """,
            (inst_id,),
        ).fetchall()

        gender_gap = []
        if len(gender_data) == 2:
            g1, g2 = gender_data[0], gender_data[1]
            gap = ((float(g2["avg_salary"]) - float(g1["avg_salary"])) / float(g1["avg_salary"]) * 100) if g1["avg_salary"] else 0
            gender_gap = [
                PayEquityItem(
                    analysis_type="gender",
                    category_1=g1["gender"],
                    category_2=g2["gender"],
                    count_1=g1["count"],
                    count_2=g2["count"],
                    avg_salary_1=float(g1["avg_salary"]),
                    avg_salary_2=float(g2["avg_salary"]),
                    pay_gap_percent=gap,
                    flagged=1 if abs(gap) > 5 else 0,
                )
            ]

        # Department gap analysis
        dept_data = conn.execute(
            """
            SELECT e.department, COUNT(*) as count, AVG(ec.base_salary) as avg_salary
            FROM employee_compensation ec
            JOIN employees e ON ec.employee_id = e.employee_id AND ec.institution_id = e.institution_id
            WHERE ec.institution_id = ? AND ec.is_current = 1
            GROUP BY e.department
            ORDER BY avg_salary DESC
            """,
            (inst_id,),
        ).fetchall()

        department_gap = [
            PayEquityItem(
                analysis_type="department",
                category_1=d["department"],
                count_1=d["count"],
                avg_salary_1=float(d["avg_salary"]),
                flagged=0,
            )
            for d in dept_data
        ]

        flagged_count = sum(1 for item in gender_gap + department_gap if item.flagged)

        return PayEquityReport(
            analysis_date=analysis_date,
            gender_gap=gender_gap,
            department_gap=department_gap,
            flagged_items=flagged_count,
        )

    finally:
        conn.close()


logger.info("Compensation router registered with endpoints for pay grades, job levels, salary structures, and equity analysis")
