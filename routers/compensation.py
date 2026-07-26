"""API endpoints for Compensation Framework: Pay Grades, Job Levels, Salary Structures."""
import calendar
import logging
from typing import List, Optional
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_schemas import (
    PayGradeCreate, PayGradeResponse, PayGradeUpdate,
    JobLevelCreate, JobLevelResponse, JobLevelUpdate,
    JobRoleCreate, JobRoleResponse, JobRoleUpdate, JobRoleWithGrades, JobRoleListItem,
    SalaryStructureCreate, SalaryStructureResponse, SalaryStructureUpdate,
    EmployeeCompensationCreate, EmployeeCompensationResponse, EmployeeCompensationDetail,
    SalaryChangeCreate, SalaryChangeResponse,
    MeritReviewCycleCreate, MeritReviewCycleResponse,
    MeritRecommendationCreate, MeritRecommendationApprove, MeritRecommendationResponse,
    MeritRecommendationWithEmployee,
    BonusPlanCreate, BonusPlanUpdate, BonusPlanResponse,
    BonusPayoutCreate, BonusPayoutDecide, BonusPayoutResponse, BonusPayoutWithEmployee,
    CommissionPlanCreate, CommissionPlanUpdate, CommissionPlanResponse,
    CommissionEntryCreate, CommissionEntryDecide, CommissionEntryResponse, CommissionEntryWithEmployee,
    EquityGrantCreate, EquityGrantDecide, EquityGrantResponse, EquityGrantWithEmployee,
    EquityGrantDetail, VestingEventResponse, VestingEventSettle,
    TotalRewardsStatement,
    PayEquityReport, PayEquityItem,
    BulkMeritIncrease,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])


# Helper: Check compensation access permissions
def require_hr_role(current_user: dict):
    """Require HR Manager, Payroll Manager, or Compensation Manager role.

    Deliberately excludes hr_admin (previously included) — matches the
    frontend nav visibility change, so this isn't just a hidden menu with
    the API still wide open to a role that shouldn't see it.

    compensation_manager is a module-scoped role — full access here, but
    (by design, via omission from every other router's own role allow-list)
    no access to unrelated modules like payroll runs, recruitment, etc."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "payroll_manager", "compensation_manager"]:
        raise HTTPException(403, detail="HR Manager, Payroll Manager, or Compensation Manager access required")


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
            "grade_name": payload.grade_name if payload.grade_name is not None else grade["grade_name"],
            "grade_level": payload.grade_level if payload.grade_level is not None else grade["grade_level"],
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
) -> List[JobRoleListItem]:
    """List all job roles, with each role's pay-grade mappings embedded.

    Previously returned bare roles and made the frontend fetch
    /job-roles/{id}/pay-grades separately for every single role (an N+1
    pattern — 40 roles meant 41 sequential-feeling round trips, each paying
    its own JWT-decode + RLS-context-setup + DB-connection-pool-wait
    overhead on top of the actual query). One extra JOIN query here,
    grouped in Python, replaces all of that.
    """
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        roles = conn.execute(
            "SELECT * FROM job_roles WHERE institution_id = ? AND is_active = 1",
            (inst_id,),
        ).fetchall()

        # job_role_pay_grades has no institution_id of its own, so scoping
        # goes through the job_roles join (same reasoning as
        # list_role_pay_grades's per-role query, just for all roles at once).
        mapping_rows = conn.execute(
            """
            SELECT m.job_role_id, g.id, g.grade_code, g.grade_name, m.is_primary
            FROM job_role_pay_grades m
            JOIN pay_grades g ON g.id = m.pay_grade_id
            JOIN job_roles r ON r.id = m.job_role_id
            WHERE r.institution_id = ?
            ORDER BY m.is_primary DESC, g.grade_level
            """,
            (inst_id,),
        ).fetchall()

        grades_by_role = {}
        for row in mapping_rows:
            grades_by_role.setdefault(row["job_role_id"], []).append({
                "id": row["id"], "grade_code": row["grade_code"],
                "grade_name": row["grade_name"], "is_primary": row["is_primary"],
            })

        return [
            JobRoleListItem(**dict(r), pay_grades=grades_by_role.get(r["id"], []))
            for r in roles
        ]
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

        # An "Approved" merit recommendation previously only produced this HR
        # note — the employee's actual base salary never moved, so
        # Total Rewards / payroll / pay grades kept reading the stale
        # figure. Approving now also supersedes employee_compensation (same
        # is_current handoff as set_employee_compensation) and records a
        # salary_changes audit row, already marked Approved since the merit
        # approval itself *is* the approval — a second manual approval step
        # would be redundant.
        if payload.approval_status == "Approved":
            effective_date = datetime.utcnow().date().isoformat()

            prev_comp = conn.execute(
                "SELECT * FROM employee_compensation WHERE employee_id = ? AND institution_id = ? AND is_current = 1",
                (rec["employee_id"], inst_id),
            ).fetchone()

            conn.execute(
                "UPDATE employee_compensation SET is_current = 0, end_date = ? WHERE employee_id = ? AND institution_id = ? AND is_current = 1",
                (effective_date, rec["employee_id"], inst_id),
            )
            conn.execute(
                """
                INSERT INTO employee_compensation
                (institution_id, employee_id, job_role_id, job_level_id, pay_grade_id,
                 salary_structure_id, base_salary, effective_date, is_current, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (inst_id, rec["employee_id"],
                 prev_comp["job_role_id"] if prev_comp else None,
                 prev_comp["job_level_id"] if prev_comp else None,
                 prev_comp["pay_grade_id"] if prev_comp else None,
                 prev_comp["salary_structure_id"] if prev_comp else None,
                 rec["recommended_new_salary"], effective_date, now, now),
            )

            conn.execute(
                """
                INSERT INTO salary_changes
                (institution_id, employee_id, change_type, from_salary, to_salary,
                 from_pay_grade_id, to_pay_grade_id, from_job_level_id, to_job_level_id,
                 effective_date, approved_by_user_id, approval_date, reason, status, created_at)
                VALUES (?, ?, 'merit_increase', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Approved', ?)
                """,
                (inst_id, rec["employee_id"], rec["current_salary"], rec["recommended_new_salary"],
                 prev_comp["pay_grade_id"] if prev_comp else None,
                 prev_comp["pay_grade_id"] if prev_comp else None,
                 prev_comp["job_level_id"] if prev_comp else None,
                 prev_comp["job_level_id"] if prev_comp else None,
                 effective_date, user_id, now,
                 f"Merit recommendation under '{cycle_name}'", now),
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
# VARIABLE PAY: BONUS / INCENTIVE PLAN ENDPOINTS
# ============================================================================

@router.post("/bonus-plans", status_code=201)
async def create_bonus_plan(
    payload: BonusPlanCreate,
    current_user: dict = Depends(get_current_user),
) -> BonusPlanResponse:
    """Create a bonus/incentive plan."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO bonus_plans
            (institution_id, plan_name, plan_type, plan_year, period_start, period_end,
             budget_pool_amount, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
            """,
            (inst_id, payload.plan_name, payload.plan_type, payload.plan_year,
             payload.period_start, payload.period_end, payload.budget_pool_amount,
             payload.description, now, now),
        )
        conn.commit()
        plan_id = conn._last_id

        plan = conn.execute("SELECT * FROM bonus_plans WHERE id = ?", (plan_id,)).fetchone()
        return BonusPlanResponse(**dict(plan))

    finally:
        conn.close()


@router.get("/bonus-plans")
async def list_bonus_plans(
    current_user: dict = Depends(get_current_user),
) -> List[BonusPlanResponse]:
    """List bonus/incentive plans."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plans = conn.execute(
            "SELECT * FROM bonus_plans WHERE institution_id = ? ORDER BY plan_year DESC, id DESC",
            (inst_id,),
        ).fetchall()
        return [BonusPlanResponse(**dict(p)) for p in plans]
    finally:
        conn.close()


@router.put("/bonus-plans/{plan_id}")
async def update_bonus_plan(
    plan_id: int,
    payload: BonusPlanUpdate,
    current_user: dict = Depends(get_current_user),
) -> BonusPlanResponse:
    """Update a bonus plan (name, status, budget, description)."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plan = conn.execute(
            "SELECT * FROM bonus_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Bonus plan not found")

        updates = {
            "plan_name": payload.plan_name if payload.plan_name is not None else plan["plan_name"],
            "status": payload.status if payload.status is not None else plan["status"],
            "budget_pool_amount": payload.budget_pool_amount if payload.budget_pool_amount is not None else plan["budget_pool_amount"],
            "description": payload.description if payload.description is not None else plan["description"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        conn.execute(f"UPDATE bonus_plans SET {set_clause} WHERE id = ?", (*updates.values(), plan_id))
        conn.commit()

        updated = conn.execute("SELECT * FROM bonus_plans WHERE id = ?", (plan_id,)).fetchone()
        return BonusPlanResponse(**dict(updated))

    finally:
        conn.close()


@router.get("/bonus-plans/{plan_id}/payouts")
async def list_bonus_payouts(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[BonusPayoutWithEmployee]:
    """List payouts for a bonus plan, with employee names joined in."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        plan = conn.execute(
            "SELECT * FROM bonus_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Bonus plan not found")

        # employee_id is only unique per institution, so the join must also
        # match institution_id — see the pay-equity report fix for the same
        # cross-tenant-fan-out pattern.
        rows = conn.execute(
            """
            SELECT p.*, e.full_name AS employee_name
            FROM bonus_payouts p
            JOIN employees e ON p.employee_id = e.employee_id AND p.institution_id = e.institution_id
            WHERE p.bonus_plan_id = ? AND p.institution_id = ?
            ORDER BY p.created_at DESC
            """,
            (plan_id, inst_id),
        ).fetchall()
        return [BonusPayoutWithEmployee(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/bonus-payouts", status_code=201)
async def create_bonus_payout(
    bonus_plan_id: int,
    payload: BonusPayoutCreate,
    current_user: dict = Depends(get_current_user),
) -> BonusPayoutResponse:
    """Award a bonus payout to an employee under a plan."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        plan = conn.execute(
            "SELECT * FROM bonus_plans WHERE id = ? AND institution_id = ?",
            (bonus_plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Bonus plan not found")

        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (payload.employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO bonus_payouts
            (institution_id, bonus_plan_id, employee_id, target_amount, awarded_amount,
             reason, recommended_by_user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
            """,
            (inst_id, bonus_plan_id, payload.employee_id, payload.target_amount,
             payload.awarded_amount, payload.reason, user_id, now, now),
        )
        # Capture this INSERT's id before the HR note INSERT overwrites
        # conn._last_id.
        payout_id = conn._last_id

        note_body = f"Bonus payout of RM {payload.awarded_amount:,.2f} proposed under '{plan['plan_name']}' ({plan['plan_type']})."
        if payload.reason:
            note_body += f" Reason: {payload.reason}"
        _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

        conn.commit()

        payout = conn.execute("SELECT * FROM bonus_payouts WHERE id = ?", (payout_id,)).fetchone()
        return BonusPayoutResponse(**dict(payout))

    finally:
        conn.close()


@router.put("/bonus-payouts/{payout_id}")
async def decide_bonus_payout(
    payout_id: int,
    payload: BonusPayoutDecide,
    current_user: dict = Depends(get_current_user),
) -> BonusPayoutResponse:
    """Approve or reject a bonus payout."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        payout = conn.execute(
            "SELECT * FROM bonus_payouts WHERE id = ? AND institution_id = ?",
            (payout_id, inst_id),
        ).fetchone()
        if not payout:
            raise HTTPException(404, detail="Bonus payout not found")

        plan = conn.execute("SELECT plan_name FROM bonus_plans WHERE id = ?", (payout["bonus_plan_id"],)).fetchone()
        plan_name = plan["plan_name"] if plan else "bonus plan"

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE bonus_payouts
            SET status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, user_id, now, now, payout_id),
        )

        note_body = (
            f"Bonus payout of RM {float(payout['awarded_amount']):,.2f} under '{plan_name}' "
            f"was {payload.status.lower()} by {current_user['username']}."
        )
        _add_hr_note(conn, inst_id, payout["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM bonus_payouts WHERE id = ?", (payout_id,)).fetchone()
        return BonusPayoutResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/bonus-payouts/{payout_id}/pay")
async def mark_bonus_payout_paid(
    payout_id: int,
    current_user: dict = Depends(get_current_user),
) -> BonusPayoutResponse:
    """Mark an approved bonus payout as actually paid out."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        payout = conn.execute(
            "SELECT * FROM bonus_payouts WHERE id = ? AND institution_id = ?",
            (payout_id, inst_id),
        ).fetchone()
        if not payout:
            raise HTTPException(404, detail="Bonus payout not found")
        if payout["status"] != "Approved":
            raise HTTPException(400, detail="Only an Approved payout can be marked as Paid")

        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE bonus_payouts SET status = 'Paid', payout_date = ?, updated_at = ? WHERE id = ?",
            (today, now, payout_id),
        )

        note_body = f"Bonus payout of RM {float(payout['awarded_amount']):,.2f} paid out on {today}."
        _add_hr_note(conn, inst_id, payout["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM bonus_payouts WHERE id = ?", (payout_id,)).fetchone()
        return BonusPayoutResponse(**dict(updated))

    finally:
        conn.close()


# ============================================================================
# VARIABLE PAY: COMMISSION STRUCTURE ENDPOINTS
# ============================================================================

@router.post("/commission-plans", status_code=201)
async def create_commission_plan(
    payload: CommissionPlanCreate,
    current_user: dict = Depends(get_current_user),
) -> CommissionPlanResponse:
    """Create a commission plan."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO commission_plans
            (institution_id, plan_name, plan_type, default_rate_percent, plan_year,
             period_start, period_end, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
            """,
            (inst_id, payload.plan_name, payload.plan_type, payload.default_rate_percent,
             payload.plan_year, payload.period_start, payload.period_end,
             payload.description, now, now),
        )
        conn.commit()
        plan_id = conn._last_id

        plan = conn.execute("SELECT * FROM commission_plans WHERE id = ?", (plan_id,)).fetchone()
        return CommissionPlanResponse(**dict(plan))

    finally:
        conn.close()


@router.get("/commission-plans")
async def list_commission_plans(
    current_user: dict = Depends(get_current_user),
) -> List[CommissionPlanResponse]:
    """List commission plans."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plans = conn.execute(
            "SELECT * FROM commission_plans WHERE institution_id = ? ORDER BY plan_year DESC, id DESC",
            (inst_id,),
        ).fetchall()
        return [CommissionPlanResponse(**dict(p)) for p in plans]
    finally:
        conn.close()


@router.put("/commission-plans/{plan_id}")
async def update_commission_plan(
    plan_id: int,
    payload: CommissionPlanUpdate,
    current_user: dict = Depends(get_current_user),
) -> CommissionPlanResponse:
    """Update a commission plan (name, status, default rate, description)."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plan = conn.execute(
            "SELECT * FROM commission_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Commission plan not found")

        updates = {
            "plan_name": payload.plan_name if payload.plan_name is not None else plan["plan_name"],
            "status": payload.status if payload.status is not None else plan["status"],
            "default_rate_percent": payload.default_rate_percent if payload.default_rate_percent is not None else plan["default_rate_percent"],
            "description": payload.description if payload.description is not None else plan["description"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        conn.execute(f"UPDATE commission_plans SET {set_clause} WHERE id = ?", (*updates.values(), plan_id))
        conn.commit()

        updated = conn.execute("SELECT * FROM commission_plans WHERE id = ?", (plan_id,)).fetchone()
        return CommissionPlanResponse(**dict(updated))

    finally:
        conn.close()


@router.get("/commission-plans/{plan_id}/entries")
async def list_commission_entries(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[CommissionEntryWithEmployee]:
    """List commission entries for a plan, with employee names joined in."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        plan = conn.execute(
            "SELECT * FROM commission_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Commission plan not found")

        # employee_id is only unique per institution, so the join must also
        # match institution_id — see the pay-equity report fix for the same
        # cross-tenant-fan-out pattern.
        rows = conn.execute(
            """
            SELECT c.*, e.full_name AS employee_name
            FROM commission_entries c
            JOIN employees e ON c.employee_id = e.employee_id AND c.institution_id = e.institution_id
            WHERE c.commission_plan_id = ? AND c.institution_id = ?
            ORDER BY c.created_at DESC
            """,
            (plan_id, inst_id),
        ).fetchall()
        return [CommissionEntryWithEmployee(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/commission-entries", status_code=201)
async def create_commission_entry(
    commission_plan_id: int,
    payload: CommissionEntryCreate,
    current_user: dict = Depends(get_current_user),
) -> CommissionEntryResponse:
    """Record a sales/attainment entry for an employee under a commission
    plan. The commission amount is calculated server-side from
    sales_amount x commission_rate_percent and stored, so a later change
    to the plan's default rate never retroactively alters this entry."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        plan = conn.execute(
            "SELECT * FROM commission_plans WHERE id = ? AND institution_id = ?",
            (commission_plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Commission plan not found")

        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (payload.employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        calculated_commission = round(payload.sales_amount * payload.commission_rate_percent / 100, 2)

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO commission_entries
            (institution_id, commission_plan_id, employee_id, sales_amount, quota_target,
             commission_rate_percent, calculated_commission, notes, recommended_by_user_id,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)
            """,
            (inst_id, commission_plan_id, payload.employee_id, payload.sales_amount,
             payload.quota_target, payload.commission_rate_percent, calculated_commission,
             payload.notes, user_id, now, now),
        )
        # Capture this INSERT's id before the HR note INSERT overwrites
        # conn._last_id.
        entry_id = conn._last_id

        note_body = (
            f"Commission entry of RM {calculated_commission:,.2f} "
            f"(RM {payload.sales_amount:,.2f} sales @ {payload.commission_rate_percent}%) "
            f"proposed under '{plan['plan_name']}' ({plan['plan_type']})."
        )
        if payload.notes:
            note_body += f" Notes: {payload.notes}"
        _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

        conn.commit()

        entry = conn.execute("SELECT * FROM commission_entries WHERE id = ?", (entry_id,)).fetchone()
        return CommissionEntryResponse(**dict(entry))

    finally:
        conn.close()


@router.put("/commission-entries/{entry_id}")
async def decide_commission_entry(
    entry_id: int,
    payload: CommissionEntryDecide,
    current_user: dict = Depends(get_current_user),
) -> CommissionEntryResponse:
    """Approve or reject a commission entry."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        entry = conn.execute(
            "SELECT * FROM commission_entries WHERE id = ? AND institution_id = ?",
            (entry_id, inst_id),
        ).fetchone()
        if not entry:
            raise HTTPException(404, detail="Commission entry not found")

        plan = conn.execute("SELECT plan_name FROM commission_plans WHERE id = ?", (entry["commission_plan_id"],)).fetchone()
        plan_name = plan["plan_name"] if plan else "commission plan"

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE commission_entries
            SET status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, user_id, now, now, entry_id),
        )

        note_body = (
            f"Commission entry of RM {float(entry['calculated_commission']):,.2f} under '{plan_name}' "
            f"was {payload.status.lower()} by {current_user['username']}."
        )
        _add_hr_note(conn, inst_id, entry["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM commission_entries WHERE id = ?", (entry_id,)).fetchone()
        return CommissionEntryResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/commission-entries/{entry_id}/pay")
async def mark_commission_entry_paid(
    entry_id: int,
    current_user: dict = Depends(get_current_user),
) -> CommissionEntryResponse:
    """Mark an approved commission entry as actually paid out."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        entry = conn.execute(
            "SELECT * FROM commission_entries WHERE id = ? AND institution_id = ?",
            (entry_id, inst_id),
        ).fetchone()
        if not entry:
            raise HTTPException(404, detail="Commission entry not found")
        if entry["status"] != "Approved":
            raise HTTPException(400, detail="Only an Approved commission entry can be marked as Paid")

        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE commission_entries SET status = 'Paid', payout_date = ?, updated_at = ? WHERE id = ?",
            (today, now, entry_id),
        )

        note_body = f"Commission payout of RM {float(entry['calculated_commission']):,.2f} paid out on {today}."
        _add_hr_note(conn, inst_id, entry["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM commission_entries WHERE id = ?", (entry_id,)).fetchone()
        return CommissionEntryResponse(**dict(updated))

    finally:
        conn.close()


# ============================================================================
# EQUITY & LONG-TERM INCENTIVES
# ============================================================================

def _add_months(date_str: str, months: int) -> str:
    """Add whole calendar months to a YYYY-MM-DD string, clamping the day to
    the target month's length (e.g. Jan 31 + 1 month -> Feb 28/29, not an
    invalid Feb 31). No dateutil dependency in this project, so this is the
    plain-stdlib equivalent of relativedelta(months=+months)."""
    y, m, d = (int(p) for p in date_str.split('-'))
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    last_day = calendar.monthrange(ny, nm)[1]
    return date(ny, nm, min(d, last_day)).isoformat()


def _generate_vesting_schedule(quantity: int, vesting_start_date: str, vesting_years: int, cliff_months: int):
    """Standard cliff + quarterly vesting: cliff_months worth of shares vest
    in one tranche at the cliff date (proportional to time elapsed), then
    the remainder vests in equal quarterly tranches for the rest of the
    schedule. The final quarter absorbs any rounding remainder so the
    tranches always sum to exactly `quantity`. Returns a list of
    (vest_date, quantity) tuples."""
    total_months = vesting_years * 12
    events = []

    cliff_qty = 0
    if cliff_months > 0:
        cliff_qty = round(quantity * cliff_months / total_months)
        if cliff_qty > 0:
            events.append((_add_months(vesting_start_date, cliff_months), cliff_qty))

    remaining_qty = quantity - cliff_qty
    remaining_months = total_months - cliff_months
    num_quarters = remaining_months // 3

    if num_quarters <= 0:
        if remaining_qty > 0:
            events.append((_add_months(vesting_start_date, total_months), remaining_qty))
    else:
        per_quarter = remaining_qty // num_quarters
        allocated = 0
        for i in range(1, num_quarters + 1):
            qty = per_quarter if i < num_quarters else remaining_qty - allocated
            allocated += qty
            if qty > 0:
                events.append((_add_months(vesting_start_date, cliff_months + 3 * i), qty))

    return events


@router.post("/equity-grants", status_code=201)
async def create_equity_grant(
    payload: EquityGrantCreate,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantResponse:
    """Create an equity grant (stock option or RSU), pending HR approval.
    Vesting events aren't generated until the grant is approved."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (payload.employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO equity_grants
            (institution_id, employee_id, grant_type, grant_date, quantity, strike_price,
             fair_market_value_at_grant, vesting_start_date, vesting_years, cliff_months,
             notes, recommended_by_user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending Approval', ?, ?)
            """,
            (inst_id, payload.employee_id, payload.grant_type, payload.grant_date, payload.quantity,
             payload.strike_price, payload.fair_market_value_at_grant, payload.vesting_start_date,
             payload.vesting_years, payload.cliff_months, payload.notes, user_id, now, now),
        )
        grant_id = conn._last_id

        note_body = (
            f"Equity grant proposed: {payload.quantity:,} {payload.grant_type} units, "
            f"granted {payload.grant_date}, vesting over {payload.vesting_years}y "
            f"with a {payload.cliff_months}-month cliff."
        )
        _add_hr_note(conn, inst_id, payload.employee_id, note_body, current_user["username"])

        conn.commit()

        grant = conn.execute("SELECT * FROM equity_grants WHERE id = ?", (grant_id,)).fetchone()
        return EquityGrantResponse(**dict(grant))

    finally:
        conn.close()


@router.get("/equity-grants")
async def list_equity_grants(
    current_user: dict = Depends(get_current_user),
) -> List[EquityGrantWithEmployee]:
    """List all equity grants in the institution, with employee names joined in."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            """
            SELECT g.*, e.full_name AS employee_name
            FROM equity_grants g
            JOIN employees e ON g.employee_id = e.employee_id AND g.institution_id = e.institution_id
            WHERE g.institution_id = ?
            ORDER BY g.created_at DESC
            """,
            (inst_id,),
        ).fetchall()
        return [EquityGrantWithEmployee(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.get("/equity-grants/{grant_id}")
async def get_equity_grant(
    grant_id: int,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantDetail:
    """Get a single equity grant with its full vesting schedule."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        grant = conn.execute(
            """
            SELECT g.*, e.full_name AS employee_name
            FROM equity_grants g
            JOIN employees e ON g.employee_id = e.employee_id AND g.institution_id = e.institution_id
            WHERE g.id = ? AND g.institution_id = ?
            """,
            (grant_id, inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")

        events = conn.execute(
            "SELECT * FROM equity_vesting_events WHERE equity_grant_id = ? AND institution_id = ? ORDER BY vest_date ASC",
            (grant_id, inst_id),
        ).fetchall()

        # "Paid" only occurs for Phantom grants (cash-settled after vesting)
        # and is still a vested tranche, just further along — it must count
        # toward vested, not sit in limbo between Scheduled and Vested.
        vested = sum(e["quantity_vested"] for e in events if e["status"] in ("Vested", "Paid"))
        unvested = sum(e["quantity_vested"] for e in events if e["status"] == "Scheduled")

        grant_dict = dict(grant)
        return EquityGrantDetail(
            **grant_dict,
            vesting_events=[VestingEventResponse(**dict(e)) for e in events],
            quantity_vested=vested,
            quantity_unvested=unvested,
        )
    finally:
        conn.close()


@router.put("/equity-grants/{grant_id}/decide")
async def decide_equity_grant(
    grant_id: int,
    payload: EquityGrantDecide,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantResponse:
    """Approve or reject an equity grant. Approving generates the full
    vesting schedule as equity_vesting_events rows in the same transaction —
    there's no separate 'activate' step."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        grant = conn.execute(
            "SELECT * FROM equity_grants WHERE id = ? AND institution_id = ?",
            (grant_id, inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")
        if grant["status"] != "Pending Approval":
            raise HTTPException(400, detail="Only a Pending Approval grant can be approved or rejected")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE equity_grants
            SET status = ?, approved_by_user_id = ?, approval_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, user_id, now, now, grant_id),
        )

        if payload.status == "Approved":
            schedule = _generate_vesting_schedule(
                grant["quantity"], grant["vesting_start_date"], grant["vesting_years"], grant["cliff_months"]
            )
            for vest_date, qty in schedule:
                conn.execute(
                    """
                    INSERT INTO equity_vesting_events
                    (institution_id, equity_grant_id, employee_id, vest_date, quantity_vested,
                     status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'Scheduled', ?, ?)
                    """,
                    (inst_id, grant_id, grant["employee_id"], vest_date, qty, now, now),
                )

        note_body = (
            f"Equity grant ({grant['quantity']:,} {grant['grant_type']} units, granted {grant['grant_date']}) "
            f"was {payload.status.lower()} by {current_user['username']}."
        )
        _add_hr_note(conn, inst_id, grant["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_grants WHERE id = ?", (grant_id,)).fetchone()
        return EquityGrantResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/equity-grants/{grant_id}/cancel")
async def cancel_equity_grant(
    grant_id: int,
    current_user: dict = Depends(get_current_user),
) -> EquityGrantResponse:
    """Cancel an equity grant (e.g. on termination before fully vested).
    Already-vested tranches are left untouched — only remaining Scheduled
    tranches are cancelled, since vested shares are the employee's regardless
    of what happens to the grant afterward."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        grant = conn.execute(
            "SELECT * FROM equity_grants WHERE id = ? AND institution_id = ?",
            (grant_id, inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")
        if grant["status"] not in ("Approved",):
            raise HTTPException(400, detail="Only an Approved grant can be cancelled")

        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE equity_grants SET status = 'Cancelled', updated_at = ? WHERE id = ?",
            (now, grant_id),
        )
        conn.execute(
            "UPDATE equity_vesting_events SET status = 'Cancelled', updated_at = ? WHERE equity_grant_id = ? AND status = 'Scheduled'",
            (now, grant_id),
        )

        note_body = f"Equity grant ({grant['quantity']:,} {grant['grant_type']} units, granted {grant['grant_date']}) was cancelled by {current_user['username']}. Unvested tranches forfeited."
        _add_hr_note(conn, inst_id, grant["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_grants WHERE id = ?", (grant_id,)).fetchone()
        return EquityGrantResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/vesting-events/{event_id}/vest")
async def mark_vesting_event_vested(
    event_id: int,
    current_user: dict = Depends(get_current_user),
) -> VestingEventResponse:
    """Mark a scheduled vesting tranche as actually vested (i.e. its vest
    date has passed and the shares/units are now the employee's)."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        event = conn.execute(
            "SELECT * FROM equity_vesting_events WHERE id = ? AND institution_id = ?",
            (event_id, inst_id),
        ).fetchone()
        if not event:
            raise HTTPException(404, detail="Vesting event not found")
        if event["status"] != "Scheduled":
            raise HTTPException(400, detail="Only a Scheduled vesting event can be marked as Vested")

        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE equity_vesting_events SET status = 'Vested', vested_at = ?, updated_at = ? WHERE id = ?",
            (now, now, event_id),
        )

        grant = conn.execute("SELECT grant_type FROM equity_grants WHERE id = ?", (event["equity_grant_id"],)).fetchone()
        note_body = f"{event['quantity_vested']:,} {grant['grant_type'] if grant else ''} units vested on {event['vest_date']}."
        _add_hr_note(conn, inst_id, event["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_vesting_events WHERE id = ?", (event_id,)).fetchone()
        return VestingEventResponse(**dict(updated))

    finally:
        conn.close()


@router.put("/vesting-events/{event_id}/settle")
async def settle_vesting_event(
    event_id: int,
    payload: VestingEventSettle,
    current_user: dict = Depends(get_current_user),
) -> VestingEventResponse:
    """Cash-settle a Vested Phantom stock tranche: pay out
    (settlement_price - fair_market_value_at_grant) x quantity_vested, i.e.
    the appreciation over the grant's baseline value, clamped at zero (a
    phantom award pays the *gain*, not a fixed amount — no negative payout
    if the price dropped). Only meaningful for Phantom grants, since RSU/
    ISO/NSO/ESPP settle in actual equity, not cash, and 'Vested' is already
    their terminal state."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        event = conn.execute(
            "SELECT * FROM equity_vesting_events WHERE id = ? AND institution_id = ?",
            (event_id, inst_id),
        ).fetchone()
        if not event:
            raise HTTPException(404, detail="Vesting event not found")
        if event["status"] != "Vested":
            raise HTTPException(400, detail="Only a Vested tranche can be settled")

        grant = conn.execute(
            "SELECT * FROM equity_grants WHERE id = ? AND institution_id = ?",
            (event["equity_grant_id"], inst_id),
        ).fetchone()
        if not grant:
            raise HTTPException(404, detail="Equity grant not found")
        if grant["grant_type"] != "Phantom":
            raise HTTPException(400, detail="Only Phantom stock tranches can be cash-settled")

        baseline = float(grant["fair_market_value_at_grant"] or 0)
        cash_payout = max(0.0, payload.settlement_price - baseline) * event["quantity_vested"]

        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE equity_vesting_events
            SET status = 'Paid', settlement_price = ?, cash_payout = ?, payout_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.settlement_price, cash_payout, today, now, event_id),
        )

        note_body = (
            f"Phantom stock tranche ({event['quantity_vested']:,} units, vested {event['vest_date']}) "
            f"settled at RM {payload.settlement_price:,.4f}/unit — RM {cash_payout:,.2f} paid out on {today}."
        )
        _add_hr_note(conn, inst_id, event["employee_id"], note_body, current_user["username"])

        conn.commit()

        updated = conn.execute("SELECT * FROM equity_vesting_events WHERE id = ?", (event_id,)).fetchone()
        return VestingEventResponse(**dict(updated))

    finally:
        conn.close()


# ============================================================================
# TOTAL REWARDS STATEMENT
# ============================================================================

def _build_total_rewards_statement(conn, inst_id: int, employee_id: str, year: int) -> TotalRewardsStatement:
    """Shared aggregation for both the HR-facing and self-service total
    rewards endpoints. Raises HTTPException(404) if the employee doesn't
    exist in this institution."""
    employee = conn.execute(
        "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
        (employee_id, inst_id),
    ).fetchone()
    if not employee:
        raise HTTPException(404, detail="Employee not found")

    comp = conn.execute(
        "SELECT * FROM employee_compensation WHERE employee_id = ? AND institution_id = ? AND is_current = 1",
        (employee_id, inst_id),
    ).fetchone()
    base_monthly = float(comp["base_salary"]) if comp else None
    base_annual = base_monthly * 12 if base_monthly is not None else None

    year_prefix = f"{year}-"
    bonus_row = conn.execute(
        """
        SELECT COALESCE(SUM(awarded_amount), 0) AS total FROM bonus_payouts
        WHERE employee_id = ? AND institution_id = ? AND status IN ('Approved', 'Paid')
          AND created_at LIKE ?
        """,
        (employee_id, inst_id, year_prefix + '%'),
    ).fetchone()
    commission_row = conn.execute(
        """
        SELECT COALESCE(SUM(calculated_commission), 0) AS total FROM commission_entries
        WHERE employee_id = ? AND institution_id = ? AND status IN ('Approved', 'Paid')
          AND created_at LIKE ?
        """,
        (employee_id, inst_id, year_prefix + '%'),
    ).fetchone()
    bonus_ytd = float(bonus_row["total"])
    commission_ytd = float(commission_row["total"])

    salary_changes = conn.execute(
        "SELECT * FROM salary_changes WHERE employee_id = ? AND institution_id = ? ORDER BY created_at DESC LIMIT 10",
        (employee_id, inst_id),
    ).fetchall()
    merit_history = conn.execute(
        """
        SELECT * FROM merit_recommendations
        WHERE employee_id = ? AND institution_id = ? AND approval_status = 'Approved'
        ORDER BY created_at DESC LIMIT 10
        """,
        (employee_id, inst_id),
    ).fetchall()

    # Since approving a merit recommendation now also writes a salary_changes
    # row (see approve_merit_recommendation), an approval already represented
    # there would otherwise show up twice — once as its own salary_changes
    # entry, once again here. Both inserts share the same approval_date
    # (written from the same `now` in that transaction), so match on that to
    # drop the redundant merit_recommendations copy. Approvals from before
    # this fix existed have no matching salary_changes row and still show.
    salary_change_approval_dates = {
        c["approval_date"] for c in salary_changes if c["change_type"] == "merit_increase"
    }
    merit_history = [m for m in merit_history if m["approval_date"] not in salary_change_approval_dates]

    return TotalRewardsStatement(
        employee_id=employee_id,
        employee_name=employee["full_name"],
        designation=employee["designation"],
        department=employee["department"],
        year=year,
        base_salary_monthly=base_monthly,
        base_salary_annualized=base_annual,
        compensation_effective_date=comp["effective_date"] if comp else None,
        bonus_ytd=bonus_ytd,
        commission_ytd=commission_ytd,
        total_cash_compensation=(base_annual or 0) + bonus_ytd + commission_ytd,
        salary_changes=[SalaryChangeResponse(**dict(c)) for c in salary_changes],
        merit_history=[MeritRecommendationResponse(**dict(m)) for m in merit_history],
    )


@router.get("/total-rewards/mine")
async def get_my_total_rewards(
    year: int = None,
    current_user: dict = Depends(get_current_user),
) -> TotalRewardsStatement:
    """Self-service: the logged-in employee's own total rewards statement.
    No require_hr_role gate — every employee can see their own pay, just
    not anyone else's (employee_id is pinned to current_user, not a
    caller-supplied param)."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        raise HTTPException(404, detail="No employee record linked to this account")
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        return _build_total_rewards_statement(conn, inst_id, emp_id, year or datetime.utcnow().year)
    finally:
        conn.close()


@router.get("/total-rewards/{employee_id}")
async def get_employee_total_rewards(
    employee_id: str,
    year: int = None,
    current_user: dict = Depends(get_current_user),
) -> TotalRewardsStatement:
    """HR-facing: total rewards statement for any employee in the institution."""
    require_hr_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        return _build_total_rewards_statement(conn, inst_id, employee_id, year or datetime.utcnow().year)
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
