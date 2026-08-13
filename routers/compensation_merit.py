"""Compensation: Merit Review Cycles and Merit Recommendations. One of six
routers split out of the former single routers/compensation.py.

BulkMeritIncrease is imported but not yet wired to an endpoint — carried
over unchanged from the original file."""
import logging
from typing import List
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_helpers import add_hr_note as _add_hr_note
from core.permission_matrix import require_permission
from core.compensation_records import get_current as get_current_compensation, retire_and_replace as retire_and_replace_compensation
from core.compensation_schemas import (
    MeritReviewCycleCreate, MeritReviewCycleResponse,
    MeritRecommendationCreate, MeritRecommendationApprove, MeritRecommendationResponse,
    MeritRecommendationWithEmployee,
    BulkMeritIncrease,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])

# ============================================================================
# MERIT REVIEW ENDPOINTS
# ============================================================================

@router.post("/merit-cycles", status_code=201)
async def create_merit_cycle(
    payload: MeritReviewCycleCreate,
    current_user: dict = Depends(get_current_user),
) -> MeritReviewCycleResponse:
    """Create a merit review cycle."""
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_merit_cycles_recommendations")
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
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_merit_cycles_recommendations")
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
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_merit_cycles_recommendations")
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
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_merit_cycles_recommendations")
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
    conn = get_db()
    try:
        require_permission(conn, current_user, "compensation.manage_merit_cycles_recommendations")
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

            prev_comp = get_current_compensation(conn, inst_id, rec["employee_id"])

            retire_and_replace_compensation(
                conn, inst_id, rec["employee_id"],
                job_role_id=prev_comp["job_role_id"] if prev_comp else None,
                job_level_id=prev_comp["job_level_id"] if prev_comp else None,
                pay_grade_id=prev_comp["pay_grade_id"] if prev_comp else None,
                salary_structure_id=prev_comp["salary_structure_id"] if prev_comp else None,
                base_salary=rec["recommended_new_salary"], effective_date=effective_date,
            )
            # employees.basic_salary is the one source of truth payroll reads
            # (see routers/employees.py) — a merit approval that only wrote
            # employee_compensation.base_salary would leave the two figures
            # out of sync, same drift this whole base_salary/basic_salary
            # split was meant to eliminate.
            conn.execute(
                "UPDATE employees SET basic_salary=?, updated_at=? WHERE employee_id=? AND institution_id=?",
                (rec["recommended_new_salary"], now, rec["employee_id"], inst_id),
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


