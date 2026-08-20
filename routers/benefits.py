"""API endpoints for the Benefits module."""
import logging
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from db import get_db
from core.deps import get_current_user
from core.approval_workflow import start_workflow, advance_or_finalize, filter_actionable
from core.org_queries import subordinates_in_clause
from core.permission_matrix import require_permission
from core.benefits_schemas import (
    BenefitPlanCreate, BenefitPlanUpdate, BenefitPlanResponse,
    EligibilityRuleCreate, EligibilityRuleResponse, EligiblePlanResponse,
    EnrollmentPeriodCreate, EnrollmentPeriodUpdate, EnrollmentPeriodResponse,
    LifeEventCreate, LifeEventDecide, LifeEventResponse, LifeEventWithEmployee,
    EnrollmentElect, EnrollmentResponse, EnrollmentWithPlan,
    DependentCreate, DependentUpdate, DependentResponse, EnrollmentDependentLink,
    ClaimCreate, ClaimDecide, ClaimResponse, ClaimWithDetails,
    PlanUtilization, ComplianceReport,
    DepartmentCost, PlanUtilizationBrief, BenefitsDashboardSummary,
    ClaimBrief, BenefitBalance, MyBenefitsDashboard,
)

logger = logging.getLogger("ems.benefits")
router = APIRouter(prefix="/api/benefits", tags=["benefits"])


def require_benefits_role(current_user: dict):
    """Require HR Manager, Payroll Manager, or Compensation Manager role —
    same access gate as the Compensation module (matches the user's
    explicit choice to reuse that gate rather than add a dedicated
    Benefits Manager role). Excludes hr_admin, matching the Compensation
    module's own precedent."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "payroll_manager", "compensation_manager"]:
        raise HTTPException(403, detail="HR Manager, Payroll Manager, or Compensation Manager access required")


def require_dependents_manage_role(current_user: dict):
    """Dependent/beneficiary records live on the employee's own profile now
    (Edit Employee > Dependents tab), so this is scoped to the same role set
    as employee-record edits (CAN_WRITE in routers/employees.py) minus
    superadmin's usual carve-outs — narrower than require_benefits_role on
    purpose, per explicit product decision to drop payroll/compensation
    manager access to this specific data."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "hr_admin"]:
        raise HTTPException(403, detail="HR Manager or HR Admin access required")


# ============================================================================
# PLAN TYPES (BENEFIT PLAN CATALOG)
# ============================================================================

def _plan_response(row) -> BenefitPlanResponse:
    """payroll_sync_enabled is stored as an integer flag (same pattern as
    benefit_dependents.is_beneficiary) — convert to bool for the response."""
    d = dict(row)
    d["payroll_sync_enabled"] = bool(d["payroll_sync_enabled"])
    return BenefitPlanResponse(**d)


@router.post("/plans", status_code=201)
async def create_benefit_plan(
    payload: BenefitPlanCreate,
    current_user: dict = Depends(get_current_user),
) -> BenefitPlanResponse:
    """Create a benefit plan."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()

        conn.execute(
            """
            INSERT INTO benefit_plans
            (institution_id, plan_name, plan_category, contribution_type, employee_cost,
             employer_cost, plan_year, effective_date, end_date, description,
             carrier_name, carrier_group_policy_number, payroll_sync_enabled, status,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
            """,
            (inst_id, payload.plan_name, payload.plan_category, payload.contribution_type,
             payload.employee_cost, payload.employer_cost, payload.plan_year,
             payload.effective_date, payload.end_date, payload.description,
             payload.carrier_name, payload.carrier_group_policy_number,
             1 if payload.payroll_sync_enabled else 0, now, now),
        )
        conn.commit()
        plan_id = conn._last_id

        plan = conn.execute("SELECT * FROM benefit_plans WHERE id = ?", (plan_id,)).fetchone()
        return _plan_response(plan)

    finally:
        conn.close()


@router.get("/plans")
async def list_benefit_plans(
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[BenefitPlanResponse]:
    """List benefit plans, optionally filtered by category."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        if category:
            plans = conn.execute(
                "SELECT * FROM benefit_plans WHERE institution_id = ? AND plan_category = ? ORDER BY plan_category, plan_name",
                (inst_id, category),
            ).fetchall()
        else:
            plans = conn.execute(
                "SELECT * FROM benefit_plans WHERE institution_id = ? ORDER BY plan_category, plan_name",
                (inst_id,),
            ).fetchall()
        return [_plan_response(p) for p in plans]
    finally:
        conn.close()


@router.get("/plans/{plan_id}")
async def get_benefit_plan(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> BenefitPlanResponse:
    """Get a single benefit plan."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plan = conn.execute(
            "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Benefit plan not found")
        return _plan_response(plan)
    finally:
        conn.close()


@router.put("/plans/{plan_id}")
async def update_benefit_plan(
    plan_id: int,
    payload: BenefitPlanUpdate,
    current_user: dict = Depends(get_current_user),
) -> BenefitPlanResponse:
    """Update a benefit plan (name, status, costs, description, carrier info)."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plan = conn.execute(
            "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Benefit plan not found")

        updates = {
            "plan_name": payload.plan_name if payload.plan_name is not None else plan["plan_name"],
            "status": payload.status if payload.status is not None else plan["status"],
            "employee_cost": payload.employee_cost if payload.employee_cost is not None else plan["employee_cost"],
            "employer_cost": payload.employer_cost if payload.employer_cost is not None else plan["employer_cost"],
            "description": payload.description if payload.description is not None else plan["description"],
            "carrier_name": payload.carrier_name if payload.carrier_name is not None else plan["carrier_name"],
            "carrier_group_policy_number": payload.carrier_group_policy_number if payload.carrier_group_policy_number is not None else plan["carrier_group_policy_number"],
            "payroll_sync_enabled": (1 if payload.payroll_sync_enabled else 0) if payload.payroll_sync_enabled is not None else plan["payroll_sync_enabled"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        conn.execute(f"UPDATE benefit_plans SET {set_clause} WHERE id = ?", (*updates.values(), plan_id))
        conn.commit()

        updated = conn.execute("SELECT * FROM benefit_plans WHERE id = ?", (plan_id,)).fetchone()
        return _plan_response(updated)

    finally:
        conn.close()


# ============================================================================
# ELIGIBILITY RULES (BY JOB LEVEL / PAY GRADE)
# ============================================================================

@router.post("/plans/{plan_id}/eligibility-rules", status_code=201)
async def create_eligibility_rule(
    plan_id: int,
    payload: EligibilityRuleCreate,
    current_user: dict = Depends(get_current_user),
) -> EligibilityRuleResponse:
    """Restrict a plan to a job level and/or pay grade. A plan with no
    rules at all is open to every employee — rules only narrow it down."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        if payload.job_level_id is None and payload.pay_grade_id is None:
            raise HTTPException(400, detail="Provide at least one of job_level_id or pay_grade_id")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        plan = conn.execute(
            "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ?",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Benefit plan not found")

        if payload.job_level_id is not None:
            level = conn.execute(
                "SELECT id FROM job_levels WHERE id = ? AND institution_id = ?",
                (payload.job_level_id, inst_id),
            ).fetchone()
            if not level:
                raise HTTPException(404, detail="Job level not found")
        if payload.pay_grade_id is not None:
            grade = conn.execute(
                "SELECT id FROM pay_grades WHERE id = ? AND institution_id = ?",
                (payload.pay_grade_id, inst_id),
            ).fetchone()
            if not grade:
                raise HTTPException(404, detail="Pay grade not found")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO benefit_plan_eligibility
            (institution_id, benefit_plan_id, job_level_id, pay_grade_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (inst_id, plan_id, payload.job_level_id, payload.pay_grade_id, now),
        )
        conn.commit()
        rule_id = conn._last_id

        rule = conn.execute(
            """
            SELECT r.*, jl.level_name AS job_level_name, pg.grade_name AS pay_grade_name
            FROM benefit_plan_eligibility r
            LEFT JOIN job_levels jl ON r.job_level_id = jl.id
            LEFT JOIN pay_grades pg ON r.pay_grade_id = pg.id
            WHERE r.id = ?
            """,
            (rule_id,),
        ).fetchone()
        return EligibilityRuleResponse(**dict(rule))

    finally:
        conn.close()


@router.get("/plans/{plan_id}/eligibility-rules")
async def list_eligibility_rules(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[EligibilityRuleResponse]:
    """List eligibility rules for a plan, with level/grade names joined in."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rules = conn.execute(
            """
            SELECT r.*, jl.level_name AS job_level_name, pg.grade_name AS pay_grade_name
            FROM benefit_plan_eligibility r
            LEFT JOIN job_levels jl ON r.job_level_id = jl.id
            LEFT JOIN pay_grades pg ON r.pay_grade_id = pg.id
            WHERE r.benefit_plan_id = ? AND r.institution_id = ?
            ORDER BY r.created_at
            """,
            (plan_id, inst_id),
        ).fetchall()
        return [EligibilityRuleResponse(**dict(r)) for r in rules]
    finally:
        conn.close()


@router.delete("/plans/{plan_id}/eligibility-rules/{rule_id}", status_code=204)
async def delete_eligibility_rule(
    plan_id: int,
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Remove an eligibility rule — widens the plan back toward open-to-all
    as rules are removed (a plan with zero rules left is open to everyone)."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rule = conn.execute(
            "SELECT * FROM benefit_plan_eligibility WHERE id = ? AND benefit_plan_id = ? AND institution_id = ?",
            (rule_id, plan_id, inst_id),
        ).fetchone()
        if not rule:
            raise HTTPException(404, detail="Eligibility rule not found")
        conn.execute("DELETE FROM benefit_plan_eligibility WHERE id = ?", (rule_id,))
        conn.commit()
    finally:
        conn.close()


def _compute_eligible_plans(conn, inst_id: int, employee_id: str) -> List[EligiblePlanResponse]:
    """Shared eligibility computation — used by the HR-facing endpoint,
    the self-service 'mine' endpoint, and enrollment-election validation
    (an employee can't elect a plan they're not eligible for)."""
    comp = conn.execute(
        "SELECT * FROM employee_compensation WHERE employee_id = ? AND institution_id = ? AND is_current = 1",
        (employee_id, inst_id),
    ).fetchone()
    emp_level_id = comp["job_level_id"] if comp else None
    emp_grade_id = comp["pay_grade_id"] if comp else None

    plans = conn.execute(
        "SELECT * FROM benefit_plans WHERE institution_id = ? AND status = 'Active'",
        (inst_id,),
    ).fetchall()

    results = []
    for plan in plans:
        plan_dict = dict(plan)
        plan_dict["payroll_sync_enabled"] = bool(plan_dict["payroll_sync_enabled"])
        rules = conn.execute(
            "SELECT * FROM benefit_plan_eligibility WHERE benefit_plan_id = ?",
            (plan["id"],),
        ).fetchall()
        if not rules:
            results.append(EligiblePlanResponse(**plan_dict, eligibility_reason="Open to all"))
            continue
        matched = next(
            (r for r in rules if (r["job_level_id"] is not None and r["job_level_id"] == emp_level_id)
             or (r["pay_grade_id"] is not None and r["pay_grade_id"] == emp_grade_id)),
            None,
        )
        if matched:
            reason = "Job level match" if matched["job_level_id"] == emp_level_id and matched["job_level_id"] is not None else "Pay grade match"
            results.append(EligiblePlanResponse(**plan_dict, eligibility_reason=reason))

    return results


@router.get("/employees/{employee_id}/eligible-plans")
async def get_employee_eligible_plans(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
) -> List[EligiblePlanResponse]:
    """HR-facing: which Active benefit plans an employee is eligible for."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")
        return _compute_eligible_plans(conn, inst_id, employee_id)
    finally:
        conn.close()


@router.get("/eligible-plans/mine")
async def get_my_eligible_plans(
    current_user: dict = Depends(get_current_user),
) -> List[EligiblePlanResponse]:
    """Self-service: the logged-in employee's own eligible plans."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        raise HTTPException(404, detail="No employee record linked to this account")
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        return _compute_eligible_plans(conn, inst_id, emp_id)
    finally:
        conn.close()


# ============================================================================
# ENROLLMENT PERIODS (OPEN ENROLLMENT)
# ============================================================================

@router.post("/enrollment-periods", status_code=201)
async def create_enrollment_period(
    payload: EnrollmentPeriodCreate,
    current_user: dict = Depends(get_current_user),
) -> EnrollmentPeriodResponse:
    """Create an open enrollment period, starting as Draft."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO benefit_enrollment_periods
            (institution_id, period_name, plan_year, start_date, end_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'Draft', ?, ?)
            """,
            (inst_id, payload.period_name, payload.plan_year, payload.start_date, payload.end_date, now, now),
        )
        conn.commit()
        period_id = conn._last_id
        period = conn.execute("SELECT * FROM benefit_enrollment_periods WHERE id = ?", (period_id,)).fetchone()
        return EnrollmentPeriodResponse(**dict(period))
    finally:
        conn.close()


@router.get("/enrollment-periods")
async def list_enrollment_periods(
    current_user: dict = Depends(get_current_user),
) -> List[EnrollmentPeriodResponse]:
    """List enrollment periods (HR-facing)."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        periods = conn.execute(
            "SELECT * FROM benefit_enrollment_periods WHERE institution_id = ? ORDER BY plan_year DESC, start_date DESC",
            (inst_id,),
        ).fetchall()
        return [EnrollmentPeriodResponse(**dict(p)) for p in periods]
    finally:
        conn.close()


@router.get("/enrollment-periods/active")
async def get_active_enrollment_period(
    current_user: dict = Depends(get_current_user),
) -> Optional[EnrollmentPeriodResponse]:
    """The currently Open enrollment period covering today, if any — used
    by self-service to decide whether normal (non-life-event) elections
    are currently allowed."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        today = datetime.utcnow().date().isoformat()
        period = conn.execute(
            """
            SELECT * FROM benefit_enrollment_periods
            WHERE institution_id = ? AND status = 'Open' AND start_date <= ? AND end_date >= ?
            ORDER BY start_date DESC LIMIT 1
            """,
            (inst_id, today, today),
        ).fetchone()
        return EnrollmentPeriodResponse(**dict(period)) if period else None
    finally:
        conn.close()


@router.put("/enrollment-periods/{period_id}")
async def update_enrollment_period(
    period_id: int,
    payload: EnrollmentPeriodUpdate,
    current_user: dict = Depends(get_current_user),
) -> EnrollmentPeriodResponse:
    """Update an enrollment period's status (Draft -> Open -> Closed)."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_benefit_plans_eligibility_enrollment_periods")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        period = conn.execute(
            "SELECT * FROM benefit_enrollment_periods WHERE id = ? AND institution_id = ?",
            (period_id, inst_id),
        ).fetchone()
        if not period:
            raise HTTPException(404, detail="Enrollment period not found")
        status = payload.status if payload.status is not None else period["status"]
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE benefit_enrollment_periods SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, period_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM benefit_enrollment_periods WHERE id = ?", (period_id,)).fetchone()
        return EnrollmentPeriodResponse(**dict(updated))
    finally:
        conn.close()


# ============================================================================
# LIFE EVENTS
# ============================================================================

@router.post("/life-events/mine", status_code=201)
async def submit_my_life_event(
    payload: LifeEventCreate,
    current_user: dict = Depends(get_current_user),
) -> LifeEventResponse:
    """Self-service: submit a qualifying life event for HR review."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        raise HTTPException(404, detail="No employee record linked to this account")
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO benefit_life_events
            (institution_id, employee_id, event_type, event_date, notes, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'Pending Review', ?, ?)
            """,
            (inst_id, emp_id, payload.event_type, payload.event_date, payload.notes, now, now),
        )
        conn.commit()
        event_id = conn._last_id
        event = conn.execute("SELECT * FROM benefit_life_events WHERE id = ?", (event_id,)).fetchone()
        return LifeEventResponse(**dict(event))
    finally:
        conn.close()


@router.get("/life-events/mine")
async def list_my_life_events(
    current_user: dict = Depends(get_current_user),
) -> List[LifeEventResponse]:
    """Self-service: the logged-in employee's own life event submissions."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        return []
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        events = conn.execute(
            "SELECT * FROM benefit_life_events WHERE employee_id = ? AND institution_id = ? ORDER BY created_at DESC",
            (emp_id, inst_id),
        ).fetchall()
        return [LifeEventResponse(**dict(e)) for e in events]
    finally:
        conn.close()


@router.get("/life-events")
async def list_life_events(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[LifeEventWithEmployee]:
    """HR-facing: list all life event submissions, optionally filtered by status."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.decide_life_events_auto_enroll_view_compliance_report")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        query = """
            SELECT le.*, e.full_name AS employee_name
            FROM benefit_life_events le
            JOIN employees e ON le.employee_id = e.employee_id AND le.institution_id = e.institution_id
            WHERE le.institution_id = ?
        """
        params = [inst_id]
        if status:
            query += " AND le.status = ?"
            params.append(status)
        query += " ORDER BY le.created_at DESC"
        events = conn.execute(query, tuple(params)).fetchall()
        return [LifeEventWithEmployee(**dict(e)) for e in events]
    finally:
        conn.close()


@router.put("/life-events/{event_id}/decide")
async def decide_life_event(
    event_id: int,
    payload: LifeEventDecide,
    current_user: dict = Depends(get_current_user),
) -> LifeEventResponse:
    """Approve or reject a life event. Approving opens a 30-day
    self-service enrollment window from the event date — a fixed,
    generous window rather than something HR has to remember to set
    manually per event."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.decide_life_events_auto_enroll_view_compliance_report")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        event = conn.execute(
            "SELECT * FROM benefit_life_events WHERE id = ? AND institution_id = ?",
            (event_id, inst_id),
        ).fetchone()
        if not event:
            raise HTTPException(404, detail="Life event not found")
        if event["status"] != "Pending Review":
            raise HTTPException(400, detail="Only a Pending Review life event can be approved or rejected")

        now = datetime.utcnow().isoformat()
        window_end = None
        if payload.status == "Approved":
            event_date = date.fromisoformat(event["event_date"])
            window_end = (event_date + timedelta(days=30)).isoformat()

        conn.execute(
            """
            UPDATE benefit_life_events
            SET status = ?, reviewed_by_user_id = ?, review_date = ?, window_end_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, user_id, now, window_end, now, event_id),
        )

        note_body = f"Life event ({event['event_type']}, {event['event_date']}) was {payload.status.lower()} by {current_user['username']}."
        _add_benefits_note(conn, inst_id, event["employee_id"], note_body, current_user["username"])

        conn.commit()
        updated = conn.execute("SELECT * FROM benefit_life_events WHERE id = ?", (event_id,)).fetchone()
        return LifeEventResponse(**dict(updated))
    finally:
        conn.close()


# ============================================================================
# ENROLLMENTS (ELECTIONS)
# ============================================================================

def _add_benefits_note(conn, inst_id: int, employee_id: str, body: str, username: str):
    """Log a benefits event as an HR note, matching the pattern used by
    the Compensation module's _add_hr_note."""
    conn.execute(
        "INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by) VALUES (?, ?, ?, ?, ?)",
        (inst_id, employee_id, "performance", body, username),
    )


def _elect_enrollment(conn, inst_id: int, employee_id: str, plan_id: int, status: str,
                       enrollment_period_id: Optional[int], life_event_id: Optional[int]) -> dict:
    """Shared upsert logic for both self-service and HR-administered
    elections. Snapshots the plan's current cost onto the enrollment row
    so later plan cost changes don't retroactively rewrite what the
    employee actually agreed to."""
    plan = conn.execute(
        "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ? AND status = 'Active'",
        (plan_id, inst_id),
    ).fetchone()
    if not plan:
        raise HTTPException(404, detail="Benefit plan not found or not Active")

    now = datetime.utcnow().isoformat()
    today = datetime.utcnow().date().isoformat()
    conn.execute(
        """
        INSERT INTO benefit_enrollments
        (institution_id, employee_id, benefit_plan_id, enrollment_period_id, life_event_id,
         status, employee_cost_snapshot, employer_cost_snapshot, effective_date, elected_at,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (employee_id, benefit_plan_id) DO UPDATE SET
            status = EXCLUDED.status,
            enrollment_period_id = EXCLUDED.enrollment_period_id,
            life_event_id = EXCLUDED.life_event_id,
            employee_cost_snapshot = EXCLUDED.employee_cost_snapshot,
            employer_cost_snapshot = EXCLUDED.employer_cost_snapshot,
            effective_date = EXCLUDED.effective_date,
            elected_at = EXCLUDED.elected_at,
            updated_at = EXCLUDED.updated_at
        """,
        (inst_id, employee_id, plan_id, enrollment_period_id, life_event_id,
         status, plan["employee_cost"], plan["employer_cost"], today, now, now, now),
    )

    note_body = f"{status} in '{plan['plan_name']}' ({plan['plan_category']})."
    _add_benefits_note(conn, inst_id, employee_id, note_body, "benefits-enrollment")
    conn.commit()

    row = conn.execute(
        "SELECT * FROM benefit_enrollments WHERE employee_id = ? AND benefit_plan_id = ?",
        (employee_id, plan_id),
    ).fetchone()
    return dict(row)


@router.post("/plans/{plan_id}/auto-enroll-all")
async def auto_enroll_all_active_employees(
    plan_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """HR-triggered bulk action (button on the plan screen, not an implicit
    side effect of activating a plan) — enrolls every currently Active
    employee into this plan with status 'Enrolled'. Re-running is
    idempotent: an employee already enrolled just has their row refreshed
    (ON CONFLICT DO UPDATE), not duplicated.

    Deliberately a single set-based INSERT...SELECT rather than a Python
    loop calling _elect_enrollment per employee — institutions here can have
    thousands of active employees, and a per-employee round trip made this
    endpoint effectively hang at that scale."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.decide_life_events_auto_enroll_view_compliance_report")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        plan = conn.execute(
            "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ? AND status = 'Active'",
            (plan_id, inst_id),
        ).fetchone()
        if not plan:
            raise HTTPException(404, detail="Benefit plan not found or not Active")

        now = datetime.utcnow().isoformat()
        today = datetime.utcnow().date().isoformat()
        note_body = f"Enrolled in '{plan['plan_name']}' ({plan['plan_category']})."

        result = conn.execute(
            """
            INSERT INTO benefit_enrollments
            (institution_id, employee_id, benefit_plan_id, enrollment_period_id, life_event_id,
             status, employee_cost_snapshot, employer_cost_snapshot, effective_date, elected_at,
             created_at, updated_at)
            SELECT ?, e.employee_id, ?, NULL, NULL, 'Enrolled', ?, ?, ?, ?, ?, ?
            FROM employees e
            WHERE e.institution_id = ? AND e.status = 'Active'
            ON CONFLICT (employee_id, benefit_plan_id) DO UPDATE SET
                status = EXCLUDED.status,
                enrollment_period_id = EXCLUDED.enrollment_period_id,
                life_event_id = EXCLUDED.life_event_id,
                employee_cost_snapshot = EXCLUDED.employee_cost_snapshot,
                employer_cost_snapshot = EXCLUDED.employer_cost_snapshot,
                effective_date = EXCLUDED.effective_date,
                elected_at = EXCLUDED.elected_at,
                updated_at = EXCLUDED.updated_at
            RETURNING employee_id
            """,
            (inst_id, plan_id, plan["employee_cost"], plan["employer_cost"], today, now, now, now, inst_id),
        )
        enrolled_ids = [row["employee_id"] for row in result.fetchall()]

        if enrolled_ids:
            conn.execute(
                """
                INSERT INTO hr_notes (institution_id, employee_id, note_type, body, created_by)
                SELECT ?, e.employee_id, 'performance', ?, 'benefits-enrollment'
                FROM employees e
                WHERE e.institution_id = ? AND e.status = 'Active'
                """,
                (inst_id, note_body, inst_id),
            )

        conn.commit()
        return {"enrolled_count": len(enrolled_ids)}
    finally:
        conn.close()


@router.post("/enrollments/mine", status_code=201)
async def elect_my_enrollment(
    payload: EnrollmentElect,
    current_user: dict = Depends(get_current_user),
) -> EnrollmentResponse:
    """Self-service: elect or waive coverage under a plan. Requires either
    an active open enrollment period, or an approved life event (owned by
    this employee) whose 30-day window hasn't lapsed — an employee can't
    just enroll whenever they feel like it outside those windows."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        raise HTTPException(404, detail="No employee record linked to this account")
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        today = datetime.utcnow().date().isoformat()

        eligible = _compute_eligible_plans(conn, inst_id, emp_id)
        if not any(p.id == payload.benefit_plan_id for p in eligible):
            raise HTTPException(403, detail="Not eligible for this plan")

        enrollment_period_id = None
        if payload.life_event_id is not None:
            event = conn.execute(
                "SELECT * FROM benefit_life_events WHERE id = ? AND employee_id = ? AND institution_id = ?",
                (payload.life_event_id, emp_id, inst_id),
            ).fetchone()
            if not event or event["status"] != "Approved":
                raise HTTPException(400, detail="Life event not found or not Approved")
            if not event["window_end_date"] or today > event["window_end_date"]:
                raise HTTPException(400, detail="Life event enrollment window has closed")
        else:
            period = conn.execute(
                """
                SELECT * FROM benefit_enrollment_periods
                WHERE institution_id = ? AND status = 'Open' AND start_date <= ? AND end_date >= ?
                ORDER BY start_date DESC LIMIT 1
                """,
                (inst_id, today, today),
            ).fetchone()
            if not period:
                raise HTTPException(400, detail="No open enrollment period is currently active, and no life event window applies")
            enrollment_period_id = period["id"]

        row = _elect_enrollment(conn, inst_id, emp_id, payload.benefit_plan_id, payload.status,
                                 enrollment_period_id, payload.life_event_id)
        return EnrollmentResponse(**row)
    finally:
        conn.close()


@router.get("/enrollments/mine")
async def list_my_enrollments(
    current_user: dict = Depends(get_current_user),
) -> List[EnrollmentWithPlan]:
    """Self-service: the logged-in employee's own current elections."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        return []
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            """
            SELECT en.*, bp.plan_name, bp.plan_category
            FROM benefit_enrollments en
            JOIN benefit_plans bp ON en.benefit_plan_id = bp.id
            WHERE en.employee_id = ? AND en.institution_id = ?
            ORDER BY bp.plan_category
            """,
            (emp_id, inst_id),
        ).fetchall()
        return [EnrollmentWithPlan(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.get("/employees/{employee_id}/enrollments")
async def list_employee_enrollments(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
) -> List[EnrollmentWithPlan]:
    """HR-facing: an employee's current elections."""
    require_benefits_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            """
            SELECT en.*, bp.plan_name, bp.plan_category
            FROM benefit_enrollments en
            JOIN benefit_plans bp ON en.benefit_plan_id = bp.id
            WHERE en.employee_id = ? AND en.institution_id = ?
            ORDER BY bp.plan_category
            """,
            (employee_id, inst_id),
        ).fetchall()
        return [EnrollmentWithPlan(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/employees/{employee_id}/enrollments", status_code=201)
async def elect_employee_enrollment(
    employee_id: str,
    payload: EnrollmentElect,
    current_user: dict = Depends(get_current_user),
) -> EnrollmentResponse:
    """HR-administered election on behalf of an employee — bypasses the
    open-enrollment/life-event window checks (HR processing an exception
    is exactly the kind of case those windows shouldn't block), but still
    enforces the plan being Active and the employee being eligible."""
    require_benefits_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")

        eligible = _compute_eligible_plans(conn, inst_id, employee_id)
        if not any(p.id == payload.benefit_plan_id for p in eligible):
            raise HTTPException(403, detail="Employee is not eligible for this plan")

        row = _elect_enrollment(conn, inst_id, employee_id, payload.benefit_plan_id, payload.status,
                                 None, payload.life_event_id)
        return EnrollmentResponse(**row)
    finally:
        conn.close()


# ============================================================================
# DEPENDENT / BENEFICIARY MANAGEMENT
# ============================================================================

@router.post("/employees/{employee_id}/dependents", status_code=201)
async def create_dependent(
    employee_id: str,
    payload: DependentCreate,
    current_user: dict = Depends(get_current_user),
) -> DependentResponse:
    """HR-facing: add a dependent/beneficiary to an employee's roster."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_employee_dependents_hr_side")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")
        return _insert_dependent(conn, inst_id, employee_id, payload)
    finally:
        conn.close()


def _insert_dependent(conn, inst_id: int, employee_id: str, payload: DependentCreate) -> DependentResponse:
    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO benefit_dependents
        (institution_id, employee_id, full_name, relationship, date_of_birth, national_id,
         is_beneficiary, beneficiary_percentage, notes, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?, ?)
        """,
        (inst_id, employee_id, payload.full_name, payload.relationship, payload.date_of_birth,
         payload.national_id, 1 if payload.is_beneficiary else 0, payload.beneficiary_percentage,
         payload.notes, now, now),
    )
    conn.commit()
    dep_id = conn._last_id
    row = conn.execute("SELECT * FROM benefit_dependents WHERE id = ?", (dep_id,)).fetchone()
    d = dict(row)
    d["is_beneficiary"] = bool(d["is_beneficiary"])
    return DependentResponse(**d)


@router.get("/employees/{employee_id}/dependents")
async def list_employee_dependents(
    employee_id: str,
    current_user: dict = Depends(get_current_user),
) -> List[DependentResponse]:
    """HR-facing: an employee's dependent/beneficiary roster."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.manage_employee_dependents_hr_side")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            "SELECT * FROM benefit_dependents WHERE employee_id = ? AND institution_id = ? AND status = 'Active' ORDER BY created_at",
            (employee_id, inst_id),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_beneficiary"] = bool(d["is_beneficiary"])
            results.append(DependentResponse(**d))
        return results
    finally:
        conn.close()


@router.put("/dependents/{dependent_id}")
async def update_dependent(
    dependent_id: int,
    payload: DependentUpdate,
    current_user: dict = Depends(get_current_user),
) -> DependentResponse:
    """Shared by HR (any employee, via the Edit Employee > Dependents tab)
    and self-service (an employee editing their own roster) — the same
    modal/form is reused on both surfaces, so authorization is resolved
    here rather than by two separate endpoints."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        dep = conn.execute(
            "SELECT * FROM benefit_dependents WHERE id = ? AND institution_id = ?",
            (dependent_id, inst_id),
        ).fetchone()
        if not dep:
            raise HTTPException(404, detail="Dependent not found")
        is_self = current_user.get("employee_id") and current_user["employee_id"] == dep["employee_id"]
        if not is_self and current_user.get("role") not in ["superadmin", "hr_manager", "hr_admin"]:
            raise HTTPException(403, detail="HR Manager or HR Admin access required")

        updates = {
            "full_name": payload.full_name if payload.full_name is not None else dep["full_name"],
            "relationship": payload.relationship if payload.relationship is not None else dep["relationship"],
            "date_of_birth": payload.date_of_birth if payload.date_of_birth is not None else dep["date_of_birth"],
            "national_id": payload.national_id if payload.national_id is not None else dep["national_id"],
            "is_beneficiary": (1 if payload.is_beneficiary else 0) if payload.is_beneficiary is not None else dep["is_beneficiary"],
            "beneficiary_percentage": payload.beneficiary_percentage if payload.beneficiary_percentage is not None else dep["beneficiary_percentage"],
            "notes": payload.notes if payload.notes is not None else dep["notes"],
            "status": payload.status if payload.status is not None else dep["status"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        conn.execute(f"UPDATE benefit_dependents SET {set_clause} WHERE id = ?", (*updates.values(), dependent_id))
        conn.commit()

        row = conn.execute("SELECT * FROM benefit_dependents WHERE id = ?", (dependent_id,)).fetchone()
        d = dict(row)
        d["is_beneficiary"] = bool(d["is_beneficiary"])
        return DependentResponse(**d)
    finally:
        conn.close()


@router.get("/dependents/mine")
async def list_my_dependents(
    current_user: dict = Depends(get_current_user),
) -> List[DependentResponse]:
    """Self-service: the logged-in employee's own dependent/beneficiary roster."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        return []
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            "SELECT * FROM benefit_dependents WHERE employee_id = ? AND institution_id = ? AND status = 'Active' ORDER BY created_at",
            (emp_id, inst_id),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_beneficiary"] = bool(d["is_beneficiary"])
            results.append(DependentResponse(**d))
        return results
    finally:
        conn.close()


@router.post("/dependents/mine", status_code=201)
async def create_my_dependent(
    payload: DependentCreate,
    current_user: dict = Depends(get_current_user),
) -> DependentResponse:
    """Self-service: add a dependent/beneficiary to my own roster."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        raise HTTPException(404, detail="No employee record linked to this account")
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        return _insert_dependent(conn, inst_id, emp_id, payload)
    finally:
        conn.close()


@router.post("/enrollments/{enrollment_id}/dependents", status_code=201)
async def attach_dependent_to_enrollment(
    enrollment_id: int,
    payload: EnrollmentDependentLink,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Attach a dependent to a specific enrollment for coverage (e.g. 'my
    spouse is covered under this medical plan'). Both self-service and HR
    can call this — self-service is restricted to the caller's own
    enrollment and dependent; HR (require_benefits_role) can act on any."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        emp_id = current_user.get("employee_id")
        is_hr = current_user.get("role") in ["superadmin", "hr_manager", "payroll_manager", "compensation_manager"]
        if not is_hr and not emp_id:
            raise HTTPException(403, detail="Not authorized")

        enrollment = conn.execute(
            "SELECT * FROM benefit_enrollments WHERE id = ? AND institution_id = ?",
            (enrollment_id, inst_id),
        ).fetchone()
        if not enrollment:
            raise HTTPException(404, detail="Enrollment not found")
        if not is_hr and enrollment["employee_id"] != emp_id:
            raise HTTPException(403, detail="Not your enrollment")

        dependent = conn.execute(
            "SELECT * FROM benefit_dependents WHERE id = ? AND institution_id = ? AND employee_id = ?",
            (payload.dependent_id, inst_id, enrollment["employee_id"]),
        ).fetchone()
        if not dependent:
            raise HTTPException(404, detail="Dependent not found for this employee")

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO benefit_enrollment_dependents (institution_id, enrollment_id, dependent_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (enrollment_id, dependent_id) DO NOTHING
            """,
            (inst_id, enrollment_id, payload.dependent_id, now),
        )
        conn.commit()
        return {"enrollment_id": enrollment_id, "dependent_id": payload.dependent_id, "attached": True}
    finally:
        conn.close()


@router.get("/enrollments/{enrollment_id}/dependents")
async def list_enrollment_dependents(
    enrollment_id: int,
    current_user: dict = Depends(get_current_user),
) -> List[DependentResponse]:
    """List dependents attached to a specific enrollment."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        emp_id = current_user.get("employee_id")
        is_hr = current_user.get("role") in ["superadmin", "hr_manager", "payroll_manager", "compensation_manager"]

        enrollment = conn.execute(
            "SELECT * FROM benefit_enrollments WHERE id = ? AND institution_id = ?",
            (enrollment_id, inst_id),
        ).fetchone()
        if not enrollment:
            raise HTTPException(404, detail="Enrollment not found")
        if not is_hr and enrollment["employee_id"] != emp_id:
            raise HTTPException(403, detail="Not your enrollment")

        rows = conn.execute(
            """
            SELECT d.* FROM benefit_enrollment_dependents ed
            JOIN benefit_dependents d ON ed.dependent_id = d.id
            WHERE ed.enrollment_id = ? AND ed.institution_id = ?
            """,
            (enrollment_id, inst_id),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_beneficiary"] = bool(d["is_beneficiary"])
            results.append(DependentResponse(**d))
        return results
    finally:
        conn.close()


@router.delete("/enrollments/{enrollment_id}/dependents/{dependent_id}", status_code=204)
async def detach_dependent_from_enrollment(
    enrollment_id: int,
    dependent_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Detach a dependent from an enrollment (coverage removed, dependent
    record itself is untouched)."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        emp_id = current_user.get("employee_id")
        is_hr = current_user.get("role") in ["superadmin", "hr_manager", "payroll_manager", "compensation_manager"]

        enrollment = conn.execute(
            "SELECT * FROM benefit_enrollments WHERE id = ? AND institution_id = ?",
            (enrollment_id, inst_id),
        ).fetchone()
        if not enrollment:
            raise HTTPException(404, detail="Enrollment not found")
        if not is_hr and enrollment["employee_id"] != emp_id:
            raise HTTPException(403, detail="Not your enrollment")

        conn.execute(
            "DELETE FROM benefit_enrollment_dependents WHERE enrollment_id = ? AND dependent_id = ? AND institution_id = ?",
            (enrollment_id, dependent_id, inst_id),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================================
# CLAIMS TRACKING (internal-only — no real carrier integration)
# ============================================================================

def _submit_claim(conn, inst_id: int, employee_id: str, payload: ClaimCreate) -> ClaimResponse:
    plan = conn.execute(
        "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ?",
        (payload.benefit_plan_id, inst_id),
    ).fetchone()
    if not plan:
        raise HTTPException(404, detail="Benefit plan not found")

    now = datetime.utcnow().isoformat()
    project_ids = {payload.project_id} if payload.project_id else set()
    workflow_id, step_order, auto_approved = start_workflow(conn, inst_id, "claims", employee_id, project_ids)
    # A fully-unresolvable chain (no manager, no HR user at all) auto-approves
    # rather than getting stuck — skips the reimbursement-cap check decide_claim
    # normally runs, which is an acceptable trade-off for this edge case only.
    status = "Approved" if auto_approved else "Submitted"
    amount_approved = float(payload.amount_claimed) if auto_approved else None
    conn.execute(
        """
        INSERT INTO benefit_claims
        (institution_id, employee_id, benefit_plan_id, claim_date, amount_claimed,
         description, status, amount_approved, created_at, updated_at, approval_workflow_id, approval_step, project_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (inst_id, employee_id, payload.benefit_plan_id, payload.claim_date,
         payload.amount_claimed, payload.description, status, amount_approved, now, now, workflow_id, step_order,
         payload.project_id),
    )
    claim_id = conn._last_id

    note_body = f"Benefit claim submitted: RM {payload.amount_claimed:,.2f} under '{plan['plan_name']}' ({plan['plan_category']})."
    _add_benefits_note(conn, inst_id, employee_id, note_body, "benefits-claims")
    conn.commit()

    row = conn.execute("SELECT * FROM benefit_claims WHERE id = ?", (claim_id,)).fetchone()
    return ClaimResponse(**dict(row))


@router.post("/claims/mine", status_code=201)
async def submit_my_claim(
    payload: ClaimCreate,
    current_user: dict = Depends(get_current_user),
) -> ClaimResponse:
    """Self-service: submit a claim under one of my plans."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        raise HTTPException(404, detail="No employee record linked to this account")
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        return _submit_claim(conn, inst_id, emp_id, payload)
    finally:
        conn.close()


@router.get("/claims/mine")
async def list_my_claims(
    current_user: dict = Depends(get_current_user),
) -> List[ClaimWithDetails]:
    """Self-service: my own submitted claims."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        return []
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        rows = conn.execute(
            """
            SELECT c.*, bp.plan_name, bp.plan_category
            FROM benefit_claims c
            JOIN benefit_plans bp ON c.benefit_plan_id = bp.id
            WHERE c.employee_id = ? AND c.institution_id = ?
            ORDER BY c.created_at DESC
            """,
            (emp_id, inst_id),
        ).fetchall()
        return [ClaimWithDetails(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/employees/{employee_id}/claims", status_code=201)
async def submit_employee_claim(
    employee_id: str,
    payload: ClaimCreate,
    current_user: dict = Depends(get_current_user),
) -> ClaimResponse:
    """HR-administered: submit a claim on behalf of an employee."""
    require_benefits_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        employee = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ? AND institution_id = ?",
            (employee_id, inst_id),
        ).fetchone()
        if not employee:
            raise HTTPException(404, detail="Employee not found")
        return _submit_claim(conn, inst_id, employee_id, payload)
    finally:
        conn.close()


@router.get("/claims")
async def list_claims(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[ClaimWithDetails]:
    """HR-facing: all claims, optionally filtered by status. A manager
    (eligible to approve a subordinate's claim via the approval-workflow
    engine's direct_manager/skip_level_manager step types — see
    core/approval_workflow.py) sees their subordinates' claims instead of
    the full institution list, the same scoping list_leave_applications/
    list_timesheets already use — previously this blanket-gated to HR/
    Payroll/Compensation roles only, so a manager's pending-approval
    To-Do item led to a page they got 403'd out of."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        query = """
            SELECT c.*, e.full_name AS employee_name, bp.plan_name, bp.plan_category
            FROM benefit_claims c
            JOIN employees e ON c.employee_id = e.employee_id AND c.institution_id = e.institution_id
            JOIN benefit_plans bp ON c.benefit_plan_id = bp.id
            WHERE c.institution_id = ?
        """
        params = [inst_id]
        if current_user.get("role") == "manager":
            frag, fp = subordinates_in_clause(inst_id, current_user.get("employee_id", ""))
            query += f" AND e.employee_id IN {frag}"
            params.extend(fp)
        else:
            require_benefits_role(current_user)
        if status:
            query += " AND c.status = ?"
            params.append(status)
        query += " ORDER BY c.created_at DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
        result = filter_actionable(conn, inst_id, "claims", [dict(r) for r in rows], current_user)
        return [ClaimWithDetails(**r) for r in result]
    finally:
        conn.close()


@router.put("/claims/{claim_id}/decide")
async def decide_claim(
    claim_id: int,
    payload: ClaimDecide,
    current_user: dict = Depends(get_current_user),
) -> ClaimResponse:
    """Approve (optionally partial) or reject a claim."""
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        user_id = current_user.get("id")

        claim = conn.execute(
            "SELECT * FROM benefit_claims WHERE id = ? AND institution_id = ?",
            (claim_id, inst_id),
        ).fetchone()
        if not claim:
            raise HTTPException(404, detail="Claim not found")
        if claim["status"] not in ("Submitted", "Under Review"):
            raise HTTPException(400, detail="Only a Submitted or Under Review claim can be decided")

        action = "reject" if payload.status == "Rejected" else "approve"
        if claim["approval_workflow_id"] and claim["approval_step"] is not None:
            try:
                project_ids = {claim["project_id"]} if claim["project_id"] else set()
                outcome, next_step = advance_or_finalize(
                    conn, inst_id, "claims", claim["employee_id"],
                    claim["approval_workflow_id"], claim["approval_step"], action, current_user, project_ids
                )
            except PermissionError as e:
                raise HTTPException(403, detail=str(e))
        else:
            require_benefits_role(current_user)
            outcome, next_step = ("rejected" if action == "reject" else "approved"), None

        if outcome == "advanced":
            conn.execute(
                "UPDATE benefit_claims SET status='Under Review', approval_step=?, updated_at=? WHERE id=?",
                (next_step, datetime.utcnow().isoformat(), claim_id)
            )
            conn.commit()
            row = conn.execute("SELECT * FROM benefit_claims WHERE id = ?", (claim_id,)).fetchone()
            return ClaimResponse(**dict(row))

        amount_approved = payload.amount_approved if payload.status == "Approved" else None
        if payload.status == "Approved" and amount_approved is None:
            amount_approved = float(claim["amount_claimed"])

        # Reimbursement Cap plans have a finite annual pool — approving past
        # it silently would let the balance shown on the employee's own
        # dashboard go negative with nothing here to stop it. Enforce the
        # same cap math the dashboard displays, not just show it after the
        # fact.
        if payload.status == "Approved":
            plan = conn.execute(
                "SELECT * FROM benefit_plans WHERE id = ? AND institution_id = ?",
                (claim["benefit_plan_id"], inst_id),
            ).fetchone()
            if plan and plan["contribution_type"] == "Reimbursement Cap":
                enrollment = conn.execute(
                    "SELECT * FROM benefit_enrollments WHERE employee_id = ? AND benefit_plan_id = ? AND institution_id = ?",
                    (claim["employee_id"], claim["benefit_plan_id"], inst_id),
                ).fetchone()
                annual_cap = float(enrollment["employer_cost_snapshot"]) if enrollment and enrollment["employer_cost_snapshot"] is not None else float(plan["employer_cost"] or 0)

                this_year_prefix = f"{datetime.utcnow().year}-"
                used_elsewhere = conn.execute(
                    """
                    SELECT COALESCE(SUM(amount_approved), 0) AS total FROM benefit_claims
                    WHERE employee_id = ? AND benefit_plan_id = ? AND institution_id = ?
                      AND status IN ('Approved', 'Paid') AND claim_date LIKE ? AND id != ?
                    """,
                    (claim["employee_id"], claim["benefit_plan_id"], inst_id, this_year_prefix + '%', claim_id),
                ).fetchone()
                remaining = annual_cap - float(used_elsewhere["total"])
                if amount_approved > remaining:
                    raise HTTPException(
                        400,
                        detail=(
                            f"Approved amount RM{amount_approved:,.2f} exceeds the employee's remaining "
                            f"RM{max(0.0, remaining):,.2f} balance under this plan's RM{annual_cap:,.2f} annual cap "
                            f"(RM{float(used_elsewhere['total']):,.2f} already used this year). "
                            f"Approve RM{max(0.0, remaining):,.2f} or less, or reject the claim."
                        ),
                    )

        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE benefit_claims
            SET status = ?, amount_approved = ?, reviewed_by_user_id = ?, review_date = ?, updated_at = ?, approval_step = NULL
            WHERE id = ?
            """,
            (payload.status, amount_approved, user_id, now, now, claim_id),
        )

        note_body = (
            f"Benefit claim (RM {float(claim['amount_claimed']):,.2f} claimed) was {payload.status.lower()} by {current_user['username']}"
            + (f" — RM {amount_approved:,.2f} approved." if amount_approved is not None else ".")
        )
        _add_benefits_note(conn, inst_id, claim["employee_id"], note_body, current_user["username"])

        conn.commit()
        updated = conn.execute("SELECT * FROM benefit_claims WHERE id = ?", (claim_id,)).fetchone()
        return ClaimResponse(**dict(updated))
    finally:
        conn.close()


@router.put("/claims/{claim_id}/pay")
async def mark_claim_paid(
    claim_id: int,
    current_user: dict = Depends(get_current_user),
) -> ClaimResponse:
    """Mark an Approved claim as paid out."""
    require_benefits_role(current_user)
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        claim = conn.execute(
            "SELECT * FROM benefit_claims WHERE id = ? AND institution_id = ?",
            (claim_id, inst_id),
        ).fetchone()
        if not claim:
            raise HTTPException(404, detail="Claim not found")
        if claim["status"] != "Approved":
            raise HTTPException(400, detail="Only an Approved claim can be marked as Paid")

        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE benefit_claims SET status = 'Paid', payout_date = ?, updated_at = ? WHERE id = ?",
            (today, now, claim_id),
        )

        note_body = f"Benefit claim payout of RM {float(claim['amount_approved'] or 0):,.2f} paid out on {today}."
        _add_benefits_note(conn, inst_id, claim["employee_id"], note_body, current_user["username"])

        conn.commit()
        updated = conn.execute("SELECT * FROM benefit_claims WHERE id = ?", (claim_id,)).fetchone()
        return ClaimResponse(**dict(updated))
    finally:
        conn.close()


# ============================================================================
# COMPLIANCE & REPORTING
# ============================================================================

@router.get("/reports/summary")
async def get_compliance_report(
    current_user: dict = Depends(get_current_user),
) -> ComplianceReport:
    """Institution-wide cost analysis, utilization, and compliance
    documentation summary — pure aggregation over benefit_plans,
    benefit_enrollments, and benefit_claims (no separate reporting
    tables, same approach as the Compensation module's Total Rewards
    statement). Employer/employee cost totals only sum Fixed Premium
    plans, since Percent of Salary and Reimbursement Cap plans don't
    have a fixed monthly figure to add up the same way."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.decide_life_events_auto_enroll_view_compliance_report")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        plans = conn.execute(
            "SELECT * FROM benefit_plans WHERE institution_id = ? AND status = 'Active' ORDER BY plan_category, plan_name",
            (inst_id,),
        ).fetchall()

        plan_utils = []
        compliance_flags = []
        total_employer_cost = 0.0
        total_employee_cost = 0.0
        total_claims_paid = 0.0
        enrolled_employee_ids = set()

        this_year_prefix = f"{datetime.utcnow().year}-"

        for plan in plans:
            enrolled = conn.execute(
                "SELECT * FROM benefit_enrollments WHERE benefit_plan_id = ? AND institution_id = ? AND status = 'Enrolled'",
                (plan["id"], inst_id),
            ).fetchall()
            waived = conn.execute(
                "SELECT COUNT(*) AS n FROM benefit_enrollments WHERE benefit_plan_id = ? AND institution_id = ? AND status = 'Waived'",
                (plan["id"], inst_id),
            ).fetchone()

            for e in enrolled:
                enrolled_employee_ids.add(e["employee_id"])

            enrolled_count = len(enrolled)
            waived_count = waived["n"]
            total_elections = enrolled_count + waived_count
            participation_rate = round(100 * enrolled_count / total_elections, 1) if total_elections > 0 else None

            plan_employer_cost = 0.0
            plan_employee_cost = 0.0
            if plan["contribution_type"] == "Fixed Premium":
                for e in enrolled:
                    plan_employer_cost += float(e["employer_cost_snapshot"] or 0)
                    plan_employee_cost += float(e["employee_cost_snapshot"] or 0)
                total_employer_cost += plan_employer_cost
                total_employee_cost += plan_employee_cost

            claims = conn.execute(
                "SELECT * FROM benefit_claims WHERE benefit_plan_id = ? AND institution_id = ?",
                (plan["id"], inst_id),
            ).fetchall()
            claims_paid_total = sum(
                float(c["amount_approved"] or 0) for c in claims
                if c["status"] == "Paid" and c["payout_date"] and c["payout_date"].startswith(this_year_prefix)
            )
            total_claims_paid += claims_paid_total

            if plan["plan_category"] in ("Medical", "Dental", "Vision", "Life", "Disability") and not plan["carrier_name"]:
                compliance_flags.append(f"'{plan['plan_name']}' ({plan['plan_category']}) has no carrier/vendor on file.")
            if enrolled_count == 0 and total_elections == 0:
                compliance_flags.append(f"'{plan['plan_name']}' has zero elections recorded — confirm it was included in the current enrollment period.")

            plan_utils.append(PlanUtilization(
                plan_id=plan["id"],
                plan_name=plan["plan_name"],
                plan_category=plan["plan_category"],
                contribution_type=plan["contribution_type"],
                status=plan["status"],
                carrier_name=plan["carrier_name"],
                enrolled_count=enrolled_count,
                waived_count=waived_count,
                participation_rate=participation_rate,
                monthly_employer_cost_total=plan_employer_cost,
                monthly_employee_cost_total=plan_employee_cost,
                claims_submitted_count=len(claims),
                claims_paid_total=claims_paid_total,
            ))

        return ComplianceReport(
            generated_at=datetime.utcnow().isoformat(),
            total_active_plans=len(plans),
            total_enrolled_employees=len(enrolled_employee_ids),
            total_monthly_employer_cost=total_employer_cost,
            total_monthly_employee_cost=total_employee_cost,
            total_claims_paid_ytd=total_claims_paid,
            plans=plan_utils,
            compliance_flags=compliance_flags,
        )
    finally:
        conn.close()


# ============================================================================
# DASHBOARD WIDGETS
# ============================================================================

def require_benefits_dashboard_role(current_user: dict):
    """The dashboard reporting widget (cost-per-department, utilization)
    has a deliberately different — wider — audience than the rest of the
    Benefits module: line Managers get a read-only view here even though
    they can't administer plans/enrollments/claims anywhere else in this
    module. Superadmin included for consistency with every other gate in
    this file, though it won't normally have an institution context."""
    if current_user.get("role") not in ["superadmin", "hr_manager", "compensation_manager", "manager"]:
        raise HTTPException(403, detail="HR Manager, Compensation Manager, or Manager access required")


@router.get("/reports/dashboard")
async def get_benefits_dashboard(
    current_user: dict = Depends(get_current_user),
) -> BenefitsDashboardSummary:
    """Dashboard-sized cost + utilization summary for HR Manager /
    Compensation Manager / Manager, including cost broken down by
    department — the fuller drill-down report lives at /reports/summary."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "benefits.view_reports_dashboard")
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")

        plans = conn.execute(
            "SELECT * FROM benefit_plans WHERE institution_id = ? AND status = 'Active'",
            (inst_id,),
        ).fetchall()

        this_year_prefix = f"{datetime.utcnow().year}-"
        dept_costs: Dict[str, Dict[str, float]] = {}
        plan_utils = []
        total_employer_cost = 0.0
        total_employee_cost = 0.0
        total_claims_paid = 0.0
        enrolled_employee_ids = set()

        for plan in plans:
            enrolled = conn.execute(
                """
                SELECT en.*, e.department AS employee_department
                FROM benefit_enrollments en
                JOIN employees e ON en.employee_id = e.employee_id AND en.institution_id = e.institution_id
                WHERE en.benefit_plan_id = ? AND en.institution_id = ? AND en.status = 'Enrolled'
                """,
                (plan["id"], inst_id),
            ).fetchall()
            waived_count = conn.execute(
                "SELECT COUNT(*) AS n FROM benefit_enrollments WHERE benefit_plan_id = ? AND institution_id = ? AND status = 'Waived'",
                (plan["id"], inst_id),
            ).fetchone()["n"]

            for e in enrolled:
                enrolled_employee_ids.add(e["employee_id"])
                if plan["contribution_type"] == "Fixed Premium":
                    dept = e["employee_department"] or "Unassigned"
                    bucket = dept_costs.setdefault(dept, {"count": 0, "employer": 0.0, "employee": 0.0})
                    bucket["count"] += 1
                    bucket["employer"] += float(e["employer_cost_snapshot"] or 0)
                    bucket["employee"] += float(e["employee_cost_snapshot"] or 0)
                    total_employer_cost += float(e["employer_cost_snapshot"] or 0)
                    total_employee_cost += float(e["employee_cost_snapshot"] or 0)

            enrolled_count = len(enrolled)
            total_elections = enrolled_count + waived_count
            participation_rate = round(100 * enrolled_count / total_elections, 1) if total_elections > 0 else None

            claims_claimed = conn.execute(
                "SELECT COALESCE(SUM(amount_claimed), 0) AS total FROM benefit_claims WHERE benefit_plan_id = ? AND institution_id = ? AND claim_date LIKE ?",
                (plan["id"], inst_id, this_year_prefix + '%'),
            ).fetchone()
            plan_claims_claimed_ytd = float(claims_claimed["total"])

            claims_paid = conn.execute(
                "SELECT COALESCE(SUM(amount_approved), 0) AS total FROM benefit_claims WHERE benefit_plan_id = ? AND institution_id = ? AND status = 'Paid' AND payout_date LIKE ?",
                (plan["id"], inst_id, this_year_prefix + '%'),
            ).fetchone()
            plan_claims_paid_ytd = float(claims_paid["total"])
            total_claims_paid += plan_claims_paid_ytd

            plan_utils.append(PlanUtilizationBrief(
                plan_name=plan["plan_name"], plan_category=plan["plan_category"],
                enrolled_count=enrolled_count, waived_count=waived_count,
                participation_rate=participation_rate,
                claims_claimed_ytd=plan_claims_claimed_ytd,
                claims_paid_ytd=plan_claims_paid_ytd,
            ))

        department_costs = [
            DepartmentCost(department=d, enrolled_count=int(v["count"]),
                            monthly_employer_cost_total=v["employer"], monthly_employee_cost_total=v["employee"])
            for d, v in sorted(dept_costs.items(), key=lambda kv: -kv[1]["employer"])
        ]

        return BenefitsDashboardSummary(
            total_active_plans=len(plans),
            total_enrolled_employees=len(enrolled_employee_ids),
            total_monthly_employer_cost=total_employer_cost,
            total_monthly_employee_cost=total_employee_cost,
            total_claims_paid_ytd=total_claims_paid,
            department_costs=department_costs,
            plan_utilization=plan_utils,
        )
    finally:
        conn.close()


@router.get("/dashboard/mine")
async def get_my_benefits_dashboard(
    current_user: dict = Depends(get_current_user),
) -> MyBenefitsDashboard:
    """Employee's own dashboard widget: recent claims and any unutilized
    balance under Reimbursement Cap plans they're enrolled in."""
    emp_id = current_user.get("employee_id")
    if not emp_id:
        return MyBenefitsDashboard(recent_claims=[], balances=[])
    conn = get_db()
    try:
        inst_id = current_user.get("active_institution_id") or current_user.get("institution_id")
        this_year_prefix = f"{datetime.utcnow().year}-"

        claims = conn.execute(
            """
            SELECT c.*, bp.plan_name, bp.plan_category
            FROM benefit_claims c
            JOIN benefit_plans bp ON c.benefit_plan_id = bp.id
            WHERE c.employee_id = ? AND c.institution_id = ?
            ORDER BY c.created_at DESC LIMIT 5
            """,
            (emp_id, inst_id),
        ).fetchall()
        recent_claims = [ClaimBrief(**dict(c)) for c in claims]

        cap_enrollments = conn.execute(
            """
            SELECT en.*, bp.plan_name, bp.plan_category
            FROM benefit_enrollments en
            JOIN benefit_plans bp ON en.benefit_plan_id = bp.id
            WHERE en.employee_id = ? AND en.institution_id = ? AND en.status = 'Enrolled'
              AND bp.contribution_type = 'Reimbursement Cap'
            """,
            (emp_id, inst_id),
        ).fetchall()

        balances = []
        for en in cap_enrollments:
            annual_cap = float(en["employer_cost_snapshot"] or 0)
            used = conn.execute(
                """
                SELECT COALESCE(SUM(amount_approved), 0) AS total FROM benefit_claims
                WHERE employee_id = ? AND institution_id = ? AND benefit_plan_id = ?
                  AND status IN ('Approved', 'Paid') AND claim_date LIKE ?
                """,
                (emp_id, inst_id, en["benefit_plan_id"], this_year_prefix + '%'),
            ).fetchone()
            used_amount = float(used["total"])
            balances.append(BenefitBalance(
                plan_name=en["plan_name"], plan_category=en["plan_category"],
                annual_cap=annual_cap, used_amount=used_amount,
                remaining_amount=max(0.0, annual_cap - used_amount),
            ))

        return MyBenefitsDashboard(recent_claims=recent_claims, balances=balances)
    finally:
        conn.close()
