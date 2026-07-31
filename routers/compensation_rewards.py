"""Compensation: Total Rewards Statement and Pay Equity Analysis. One of
six routers split out of the former single routers/compensation.py."""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from db import get_db
from core.deps import get_current_user
from core.compensation_helpers import require_hr_role
from core.compensation_records import get_current as get_current_compensation
from core.compensation_schemas import (
    MeritRecommendationResponse,
    SalaryChangeResponse,
    TotalRewardsStatement,
    PayEquityReport, PayEquityItem,
)

logger = logging.getLogger("ems.compensation")
router = APIRouter(prefix="/api/compensation", tags=["compensation"])

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

    comp = get_current_compensation(conn, inst_id, employee_id)
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

        # gender_gap/department_gap only cover employees with a current
        # employee_compensation row (INNER JOIN — correct for the averages,
        # since a NULL salary would just skew them). Anyone without one is
        # invisible to those numbers, so surface how many are missing rather
        # than let the report look complete when it isn't.
        excluded_count = conn.execute(
            """
            SELECT COUNT(*) FROM employees e
            WHERE e.institution_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM employee_compensation ec
                  WHERE ec.employee_id = e.employee_id AND ec.institution_id = e.institution_id AND ec.is_current = 1
              )
            """,
            (inst_id,),
        ).fetchone()[0]

        return PayEquityReport(
            analysis_date=analysis_date,
            gender_gap=gender_gap,
            department_gap=department_gap,
            flagged_items=flagged_count,
            excluded_no_compensation_count=excluded_count,
        )

    finally:
        conn.close()


logger.info("Compensation router registered with endpoints for pay grades, job levels, salary structures, and equity analysis")
