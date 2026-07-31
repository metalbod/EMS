"""Compensation: Pay Grades, Job Levels, Job Roles, Employee Compensation
assignment, and Salary Changes (audit trail). One of six routers split out
of the former single routers/compensation.py — see the others (merit,
bonus, commission, equity, rewards) for the rest of the Compensation
module.

SalaryStructureCreate/Response/Update, JobRoleUpdate, and JobRoleWithGrades
are imported but not yet wired to an endpoint — carried over unchanged from
the original file, not something this split introduced or removed."""
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_helpers import require_hr_role, add_hr_note as _add_hr_note
from core.compensation_records import get_current as get_current_compensation, retire_and_replace as retire_and_replace_compensation
from core.compensation_schemas import (
    PayGradeCreate, PayGradeResponse, PayGradeUpdate,
    JobLevelCreate, JobLevelResponse, JobLevelUpdate,
    JobRoleCreate, JobRoleResponse, JobRoleUpdate, JobRoleWithGrades, JobRoleListItem, JobRoleGradeMapping,
    SalaryStructureCreate, SalaryStructureResponse, SalaryStructureUpdate,
    EmployeeCompensationCreate, EmployeeCompensationResponse, EmployeeCompensationDetail,
    SalaryChangeCreate, SalaryChangeResponse,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])

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


@router.get("/job-roles/{role_id}/pay-grades", response_model=List[JobRoleGradeMapping])
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

        # base_salary is never taken from the client — employees.basic_salary
        # (what payroll actually reads) is the single source of truth, so the
        # compensation record just mirrors it rather than storing a second,
        # independently-editable number that could drift out of sync.
        actual_base_salary = float(employee["basic_salary"] or 0)

        # Capture the outgoing salary (if any) before superseding it, so the
        # HR note below can record "from X to Y" rather than just the new
        # figure.
        prev_comp = get_current_compensation(conn, inst_id, employee_id)

        comp_id = retire_and_replace_compensation(
            conn, inst_id, employee_id,
            job_role_id=payload.job_role_id, job_level_id=payload.job_level_id,
            pay_grade_id=payload.pay_grade_id, salary_structure_id=payload.salary_structure_id,
            base_salary=actual_base_salary, effective_date=payload.effective_date,
        )
        # retire_and_replace_compensation's own INSERT is followed here by the
        # HR note INSERT below, which would otherwise overwrite conn._last_id
        # before we can use it — comp_id above already captured it.

        if prev_comp and prev_comp["base_salary"] is not None and float(prev_comp["base_salary"]) != actual_base_salary:
            note_body = (
                f"Salary adjusted from RM {float(prev_comp['base_salary']):,.2f} to "
                f"RM {actual_base_salary:,.2f}, effective {payload.effective_date}."
            )
        else:
            note_body = f"Compensation record updated (role/level/grade), effective {payload.effective_date}."
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

        comp = get_current_compensation(conn, inst_id, employee_id)

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


