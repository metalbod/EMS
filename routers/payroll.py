"""
Payroll (Malaysia, salaried employees — Phase 1)
payroll_manager: create/edit/finalize runs, export bank CSV.
hr_manager: view-only (all runs/payslips, no mutation).
Everyone with an employee record: view/print their own payslips.
"""
import csv
import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    import payroll_calc
except ImportError:
    from ems import payroll_calc

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.roles import PAYROLL_VIEW_ROLES
except ImportError:
    from ems.core.roles import PAYROLL_VIEW_ROLES

try:
    from core.tasks import generate_payroll_run
except ImportError:
    from ems.core.tasks import generate_payroll_run

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

try:
    from db import get_db, IntegrityError
except ImportError:
    from ems.db import get_db, IntegrityError

router = APIRouter()

PAYROLL_MANAGE_ROLES = ("payroll_manager",)


class PayrollRunIn(BaseModel):
    period_start: str  # YYYY-MM-DD
    period_end: str


class PayslipAdjustIn(BaseModel):
    basic_salary: Optional[float] = None
    unpaid_leave_days: Optional[float] = None


def _employee_age(dob_str):
    if not dob_str:
        return 30  # sensible default if DOB missing, so calculators don't crash
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    except ValueError:
        return 30
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# Simplified monthly normal-hours threshold (8hrs x 22 working days) used to split
# Hourly employees' approved timesheet hours into regular vs. overtime (1.5x rate).
# This is an approximation — Malaysia's Employment Act overtime rules are based on
# daily/weekly limits, not a flat monthly figure; verify before relying on it.
MONTHLY_NORMAL_HOURS = 176.0
OVERTIME_MULTIPLIER = 1.5


def _compute_pay(conn, inst_id, emp, period_start, period_end):
    """Returns (basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay)."""
    salary_type = emp["salary_type"] or "Monthly"

    if salary_type == "Hourly":
        approved_hours = conn.execute("""
            SELECT COALESCE(SUM(te.hours), 0) FROM timesheet_entries te
            JOIN timesheets t ON t.id = te.timesheet_id
            WHERE t.institution_id=? AND t.employee_id=? AND t.status='Approved'
              AND te.date >= ? AND te.date <= ?
        """, (inst_id, emp["employee_id"], period_start, period_end)).fetchone()[0]
        approved_hours = float(approved_hours or 0)
        hourly_rate = emp["hourly_rate"] or 0.0
        regular_hours = min(approved_hours, MONTHLY_NORMAL_HOURS)
        overtime_hours = max(0.0, approved_hours - MONTHLY_NORMAL_HOURS)
        basic_salary = round(regular_hours * hourly_rate, 2)
        overtime_pay = round(overtime_hours * hourly_rate * OVERTIME_MULTIPLIER, 2)
        gross_pay = round(basic_salary + overtime_pay, 2)
        return basic_salary, 0.0, 0.0, regular_hours, overtime_hours, overtime_pay, gross_pay

    basic_salary = emp["basic_salary"] or 0.0
    # Unpaid-leave deduction: sum days_count of Approved leave in unpaid leave types
    # that overlaps this period.
    unpaid_days = conn.execute("""
        SELECT COALESCE(SUM(a.days_count), 0) FROM leave_applications a
        JOIN leave_types lt ON lt.id = a.leave_type_id
        WHERE a.institution_id=? AND a.employee_id=? AND a.status='Approved' AND lt.is_paid=0
          AND a.start_date <= ? AND a.end_date >= ?
    """, (inst_id, emp["employee_id"], period_end, period_start)).fetchone()[0]
    unpaid_days = float(unpaid_days or 0)
    daily_rate = basic_salary / 26 if basic_salary else 0.0  # 26 working days/month, common MY convention
    unpaid_deduction = round(daily_rate * unpaid_days, 2)
    gross_pay = round(basic_salary - unpaid_deduction, 2)
    return basic_salary, unpaid_days, unpaid_deduction, 0.0, 0.0, 0.0, gross_pay


def _generate_payslip(conn, inst_id, run_id, emp, period_start, period_end):
    """Compute and insert one payslip row for an employee for this run.

    Folds in any Pending performance bonus payouts for this employee — they
    were queued from a Finalized appraisal (see queue_bonus_payout) and ride
    along on the next payroll run generated for them, then get marked Applied.
    """
    salary_type = emp["salary_type"] or "Monthly"
    basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay = \
        _compute_pay(conn, inst_id, emp, period_start, period_end)

    pending_bonuses = conn.execute(
        "SELECT id, amount FROM performance_payouts WHERE institution_id=? AND employee_id=? AND payout_type='Bonus' AND status='Pending'",
        (inst_id, emp["employee_id"])
    ).fetchall()
    bonus_amount = round(sum(b["amount"] for b in pending_bonuses), 2)
    gross_pay = round(gross_pay + bonus_amount, 2)

    age = _employee_age(emp["date_of_birth"])

    epf = payroll_calc.calc_epf(gross_pay)
    socso = payroll_calc.calc_socso(gross_pay, age)
    eis = payroll_calc.calc_eis(gross_pay, age)
    tax_category = "Married" if emp["marital_status"] == "Married" else "Single"
    pcb = payroll_calc.calc_pcb(gross_pay, tax_category, emp["num_children"] or 0, epf["employee"])

    net_pay = round(gross_pay - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)

    conn.execute("""
        INSERT INTO payslips (
            institution_id, payroll_run_id, employee_id, basic_salary, unpaid_leave_days, unpaid_leave_deduction,
            salary_type, regular_hours, overtime_hours, overtime_pay, bonus_amount,
            gross_pay, epf_employee, epf_employer, socso_employee, socso_employer, eis_employee, eis_employer, pcb, net_pay
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, run_id, emp["employee_id"], basic_salary, unpaid_days, unpaid_deduction,
          salary_type, regular_hours, overtime_hours, overtime_pay, bonus_amount,
          gross_pay, epf["employee"], epf["employer"], socso["employee"], socso["employer"],
          eis["employee"], eis["employer"], pcb, net_pay))

    if pending_bonuses:
        ids = tuple(b["id"] for b in pending_bonuses)
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE performance_payouts SET status='Applied', payroll_run_id=?, applied_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id IN ({placeholders})",
            (run_id, *ids)
        )


@router.get("/api/payroll/runs")
@db_session
def list_payroll_runs(conn, user: dict = Depends(require_roles(*PAYROLL_VIEW_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute("""
        SELECT r.*, COUNT(p.id) AS employee_count, COALESCE(SUM(p.net_pay),0) AS total_net_pay
        FROM payroll_runs r
        LEFT JOIN payslips p ON p.payroll_run_id = r.id
        WHERE r.institution_id=?
        GROUP BY r.id ORDER BY r.period_start DESC
    """, (inst_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/payroll/runs", status_code=202)
@db_session
def create_payroll_run(conn, body: PayrollRunIn, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.period_end <= body.period_start:
        raise HTTPException(400, "Period end must be after period start")
    try:
        conn.execute(
            "INSERT INTO payroll_runs (institution_id, period_start, period_end, created_by) VALUES (?,?,?,?)",
            (inst_id, body.period_start, body.period_end, user["username"])
        )
        conn.commit()
        run = conn.execute("SELECT * FROM payroll_runs WHERE id=last_insert_rowid()").fetchone()

        # Queue async task to generate payslips
        task = generate_payroll_run.apply_async(
            args=[inst_id, run["id"], body.period_start, body.period_end]
        )

        # Track the task in database
        conn.execute("""
            INSERT INTO task_tracking (id, user_id, institution_id, task_type, status)
            VALUES (?, ?, ?, ?, ?)
        """, (task.id, user["id"], inst_id, "payroll_run", "pending"))
        conn.commit()

        return {
            "task_id": task.id,
            "run_id": run["id"],
            "status": "pending",
            "message": "Payroll run is being generated. Check task status with GET /api/tasks/{task_id}",
        }
    except IntegrityError:
        conn.rollback()
        raise HTTPException(400, "A payroll run already exists for this exact period")


@router.get("/api/payroll/runs/{run_id}")
@db_session
def get_payroll_run(conn, run_id: int, user: dict = Depends(require_roles(*PAYROLL_VIEW_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    payslips = conn.execute("""
        SELECT p.*, e.full_name, e.department, e.designation, e.bank_name, e.bank_account
        FROM payslips p JOIN employees e ON e.employee_id=p.employee_id AND e.institution_id=p.institution_id
        WHERE p.payroll_run_id=? ORDER BY e.full_name
    """, (run_id,)).fetchall()
    result = dict(run)
    result["payslips"] = [dict(r) for r in payslips]
    return result


@router.put("/api/payroll/payslips/{payslip_id}")
@db_session
def adjust_payslip(conn, payslip_id: int, body: PayslipAdjustIn, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    slip = conn.execute("SELECT * FROM payslips WHERE id=? AND institution_id=?", (payslip_id, inst_id)).fetchone()
    if not slip:
        raise HTTPException(404, "Payslip not found")
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (slip["payroll_run_id"],)).fetchone()
    if run["status"] != "Draft":
        raise HTTPException(400, "Cannot edit a payslip on a Finalized run")
    if slip["salary_type"] == "Hourly":
        raise HTTPException(400, "Hourly payslips are computed from approved timesheets — use Recompute instead")
    emp = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, slip["employee_id"])).fetchone()

    basic_salary = body.basic_salary if body.basic_salary is not None else slip["basic_salary"]
    unpaid_days = body.unpaid_leave_days if body.unpaid_leave_days is not None else slip["unpaid_leave_days"]
    daily_rate = basic_salary / 26 if basic_salary else 0.0
    unpaid_deduction = round(daily_rate * unpaid_days, 2)
    gross_pay = round(basic_salary - unpaid_deduction + (slip["bonus_amount"] or 0), 2)
    age = _employee_age(emp["date_of_birth"])
    epf = payroll_calc.calc_epf(gross_pay)
    socso = payroll_calc.calc_socso(gross_pay, age)
    eis = payroll_calc.calc_eis(gross_pay, age)
    tax_category = "Married" if emp["marital_status"] == "Married" else "Single"
    pcb = payroll_calc.calc_pcb(gross_pay, tax_category, emp["num_children"] or 0, epf["employee"])
    net_pay = round(gross_pay - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)

    conn.execute("""
        UPDATE payslips SET basic_salary=?, unpaid_leave_days=?, unpaid_leave_deduction=?, gross_pay=?,
            epf_employee=?, epf_employer=?, socso_employee=?, socso_employer=?, eis_employee=?, eis_employer=?, pcb=?, net_pay=?
        WHERE id=?
    """, (basic_salary, unpaid_days, unpaid_deduction, gross_pay,
          epf["employee"], epf["employer"], socso["employee"], socso["employer"],
          eis["employee"], eis["employer"], pcb, net_pay, payslip_id))
    conn.commit()
    row = conn.execute("SELECT * FROM payslips WHERE id=?", (payslip_id,)).fetchone()
    return dict(row)


@router.patch("/api/payroll/payslips/{payslip_id}/recompute")
@db_session
def recompute_payslip(conn, payslip_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))) -> Dict[str, Any]:
    """Re-derive an Hourly payslip from currently-Approved timesheet hours for the run's period."""
    inst_id = need_inst(user)
    slip = conn.execute("SELECT * FROM payslips WHERE id=? AND institution_id=?", (payslip_id, inst_id)).fetchone()
    if not slip:
        raise HTTPException(404, "Payslip not found")
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (slip["payroll_run_id"],)).fetchone()
    if run["status"] != "Draft":
        raise HTTPException(400, "Cannot edit a payslip on a Finalized run")
    emp = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, slip["employee_id"])).fetchone()

    basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay = \
        _compute_pay(conn, inst_id, emp, run["period_start"], run["period_end"])
    gross_pay = round(gross_pay + (slip["bonus_amount"] or 0), 2)
    age = _employee_age(emp["date_of_birth"])
    epf = payroll_calc.calc_epf(gross_pay)
    socso = payroll_calc.calc_socso(gross_pay, age)
    eis = payroll_calc.calc_eis(gross_pay, age)
    tax_category = "Married" if emp["marital_status"] == "Married" else "Single"
    pcb = payroll_calc.calc_pcb(gross_pay, tax_category, emp["num_children"] or 0, epf["employee"])
    net_pay = round(gross_pay - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)

    conn.execute("""
        UPDATE payslips SET basic_salary=?, unpaid_leave_days=?, unpaid_leave_deduction=?,
            regular_hours=?, overtime_hours=?, overtime_pay=?, gross_pay=?,
            epf_employee=?, epf_employer=?, socso_employee=?, socso_employer=?, eis_employee=?, eis_employer=?, pcb=?, net_pay=?
        WHERE id=?
    """, (basic_salary, unpaid_days, unpaid_deduction, regular_hours, overtime_hours, overtime_pay, gross_pay,
          epf["employee"], epf["employer"], socso["employee"], socso["employer"],
          eis["employee"], eis["employer"], pcb, net_pay, payslip_id))
    conn.commit()
    row = conn.execute("SELECT * FROM payslips WHERE id=?", (payslip_id,)).fetchone()
    return dict(row)


@router.patch("/api/payroll/runs/{run_id}/finalize")
@db_session
def finalize_payroll_run(conn, run_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(400, f"Run is already {run['status']}")
    conn.execute(
        "UPDATE payroll_runs SET status='Finalized', finalized_by=?, finalized_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
        (user["username"], run_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row)


@router.delete("/api/payroll/runs/{run_id}", status_code=204)
@db_session
def delete_payroll_run(conn, run_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))) -> None:
    inst_id = need_inst(user)
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run["status"] != "Draft":
        raise HTTPException(400, "Cannot delete a Finalized run")
    conn.execute("DELETE FROM payslips WHERE payroll_run_id=?", (run_id,))
    conn.execute("DELETE FROM payroll_runs WHERE id=?", (run_id,))
    conn.commit()


@router.get("/api/payroll/runs/{run_id}/bank-csv")
@db_session
def export_bank_csv(conn, run_id: int, user: dict = Depends(require_roles(*PAYROLL_MANAGE_ROLES))) -> StreamingResponse:
    inst_id = need_inst(user)
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=? AND institution_id=?", (run_id, inst_id)).fetchone()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    payslips = conn.execute("""
        SELECT p.net_pay, e.full_name, e.employee_id, e.bank_name, e.bank_account
        FROM payslips p JOIN employees e ON e.employee_id=p.employee_id AND e.institution_id=p.institution_id
        WHERE p.payroll_run_id=? ORDER BY e.full_name
    """, (run_id,)).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Employee ID", "Full Name", "Bank Name", "Bank Account", "Net Pay"])
    for r in payslips:
        writer.writerow([r["employee_id"], r["full_name"], r["bank_name"] or "", r["bank_account"] or "", r["net_pay"]])
    buf.seek(0)
    filename = f"bank-file-{run['period_start']}-to-{run['period_end']}.csv"
    return StreamingResponse(buf, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/api/payroll/payslips/mine")
@db_session
def my_payslips(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    emp_id = user.get("employee_id")
    if not emp_id:
        return []
    rows = conn.execute("""
        SELECT p.*, r.period_start, r.period_end, r.status AS run_status
        FROM payslips p JOIN payroll_runs r ON r.id = p.payroll_run_id
        WHERE p.institution_id=? AND p.employee_id=? AND r.status='Finalized'
        ORDER BY r.period_start DESC
    """, (inst_id, emp_id)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/payroll/payslips/{payslip_id}")
@db_session
def get_payslip(conn, payslip_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    row = conn.execute("""
        SELECT p.*, r.period_start, r.period_end, r.status AS run_status,
               e.full_name, e.designation, e.department, e.bank_name, e.bank_account, e.ic_number
        FROM payslips p
        JOIN payroll_runs r ON r.id = p.payroll_run_id
        JOIN employees e ON e.employee_id = p.employee_id AND e.institution_id = p.institution_id
        WHERE p.id=? AND p.institution_id=?
    """, (payslip_id, inst_id)).fetchone()
    if not row:
        raise HTTPException(404, "Payslip not found")
    if user["role"] not in PAYROLL_VIEW_ROLES and user.get("employee_id") != row["employee_id"]:
        raise HTTPException(403, "Access denied")
    return dict(row)
