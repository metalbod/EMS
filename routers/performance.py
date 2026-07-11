"""
Performance (Phase 1) — Cycles, Goals (KPI/OKR), Appraisal workflow
(Self -> Manager -> HR Calibration -> Final).
hr_manager: creates/runs cycles, calibrates, closes cycles.
manager: reviews self + downstream reporting chain (reuses employee subordinate helpers).
employee: sets own goals, self-reviews, views own appraisal history.
superadmin: excluded, consistent with the rest of the app.

Performance -> Payroll integration (Phase 2): merit increments apply
immediately to the employee's basic salary; bonuses are queued as Pending
performance_payouts and get folded into gross pay the next time a payroll
run is generated for that employee (see routers/payroll.py's _generate_payslip).
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from core.org_queries import subordinates_in_clause, is_self_or_subordinate
except ImportError:
    from ems.core.org_queries import subordinates_in_clause, is_self_or_subordinate

try:
    from core.roles import PAYROLL_VIEW_ROLES
except ImportError:
    from ems.core.roles import PAYROLL_VIEW_ROLES

try:
    from core.audit import write_audit
except ImportError:
    from ems.core.audit import write_audit

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

router = APIRouter()

PERFORMANCE_MANAGE_ROLES = ("hr_manager",)


class PerformanceCycleIn(BaseModel):
    name: str
    period_start: str  # YYYY-MM-DD
    period_end: str


class GoalIn(BaseModel):
    cycle_id: int
    employee_id: str
    goal_type: str = "KPI"  # KPI | OKR
    title: str
    description: Optional[str] = None
    weight: float = 0.0
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    unit: Optional[str] = None

    @field_validator("goal_type")
    @classmethod
    def validate_goal_type(cls, v):
        if v not in ("KPI", "OKR"):
            raise ValueError("goal_type must be KPI or OKR")
        return v

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v):
        if v < 0 or v > 100:
            raise ValueError("weight must be between 0 and 100")
        return v


class KeyResultIn(BaseModel):
    description: str
    target_value: float = 100.0
    actual_value: float = 0.0


class SelfReviewIn(BaseModel):
    self_comments: Optional[str] = None


class ManagerReviewIn(BaseModel):
    manager_comments: Optional[str] = None
    manager_rating: Optional[float] = None  # overrides the auto-computed weighted score if provided


class CalibrateIn(BaseModel):
    calibrated_rating: Optional[float] = None
    calibration_notes: Optional[str] = None


class GoalUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    unit: Optional[str] = None


class MeritIncrementIn(BaseModel):
    increment_pct: float

    @field_validator("increment_pct")
    @classmethod
    def _pct_range(cls, v):
        if v <= 0 or v > 100:
            raise ValueError("increment_pct must be between 0 and 100")
        return v


class BonusPayoutIn(BaseModel):
    amount: float

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v):
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


def _bucket_score(ratio: float) -> int:
    if ratio >= 1.15: return 5
    if ratio >= 1.00: return 4
    if ratio >= 0.85: return 3
    if ratio >= 0.70: return 2
    return 1


def _score_goal(conn, goal) -> Optional[float]:
    if goal["goal_type"] == "KPI":
        if not goal["target_value"] or goal["actual_value"] is None:
            return None
        return float(_bucket_score(goal["actual_value"] / goal["target_value"]))
    krs = conn.execute("SELECT * FROM okr_key_results WHERE goal_id=?", (goal["id"],)).fetchall()
    if not krs:
        return None
    ratios = [(kr["actual_value"] / kr["target_value"]) if kr["target_value"] else 0.0 for kr in krs]
    return float(_bucket_score(sum(ratios) / len(ratios)))


def _compute_weighted_rating(conn, cycle_id, employee_id) -> Optional[float]:
    goals = conn.execute("SELECT * FROM goals WHERE cycle_id=? AND employee_id=?", (cycle_id, employee_id)).fetchall()
    total_weight, weighted_sum = 0.0, 0.0
    for g in goals:
        s = _score_goal(conn, g)
        if s is None:
            continue
        w = g["weight"] or 0
        total_weight += w
        weighted_sum += w * s
    if total_weight <= 0:
        return None
    return round(weighted_sum / total_weight, 2)


def _can_access_employee_performance(conn, inst_id, user, employee_id) -> bool:
    if user["role"] == "hr_manager":
        return True
    if user.get("employee_id") == employee_id:
        return True
    if user["role"] == "manager":
        return is_self_or_subordinate(conn, inst_id, user.get("employee_id"), employee_id)
    return False


def _log_appraisal(conn, inst_id, appraisal_id, employee_id, action, detail, user):
    conn.execute(
        "INSERT INTO appraisal_audit_log (institution_id,appraisal_id,employee_id,action,detail,performed_by,performer_role) VALUES (?,?,?,?,?,?,?)",
        (inst_id, appraisal_id, employee_id, action, detail, user["username"], user["role"])
    )


# --- Cycles ---
@router.get("/api/performance/cycles")
def list_performance_cycles(user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "superadmin":
        return []
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM performance_cycles WHERE institution_id=? ORDER BY period_start DESC", (inst_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/performance/cycles", status_code=201)
def create_performance_cycle(body: PerformanceCycleIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    if body.period_end <= body.period_start:
        raise HTTPException(400, "Period end must be after period start")
    conn = get_db()
    conn.execute(
        "INSERT INTO performance_cycles (institution_id,name,period_start,period_end,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.name, body.period_start, body.period_end, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)


@router.patch("/api/performance/cycles/{cycle_id}/activate")
def activate_performance_cycle(cycle_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Draft":
        conn.close(); raise HTTPException(400, f"Cycle is already {cycle['status']}")
    employees = conn.execute("SELECT employee_id FROM employees WHERE institution_id=? AND status='Active'", (inst_id,)).fetchall()
    for e in employees:
        conn.execute(
            "INSERT INTO appraisals (institution_id,cycle_id,employee_id,status) VALUES (?,?,?,'SelfReview') ON CONFLICT (cycle_id, employee_id) DO NOTHING",
            (inst_id, cycle_id, e["employee_id"])
        )
    conn.execute("UPDATE performance_cycles SET status='Active' WHERE id=?", (cycle_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)


@router.patch("/api/performance/cycles/{cycle_id}/open-calibration")
def open_calibration(cycle_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, f"Cycle must be Active to open calibration (currently {cycle['status']})")
    conn.execute("UPDATE performance_cycles SET status='Calibration' WHERE id=?", (cycle_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)


@router.patch("/api/performance/cycles/{cycle_id}/close")
def close_performance_cycle(cycle_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Calibration":
        conn.close(); raise HTTPException(400, f"Cycle must be in Calibration to close (currently {cycle['status']})")
    not_ready = conn.execute(
        "SELECT COUNT(*) FROM appraisals WHERE cycle_id=? AND status NOT IN ('Calibration','Finalized')", (cycle_id,)
    ).fetchone()[0]
    if not_ready:
        conn.close(); raise HTTPException(400, f"{not_ready} appraisal(s) have not completed manager review yet")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE appraisals SET
            final_rating = COALESCE(calibrated_rating, manager_rating),
            status='Finalized', finalized_by=?, finalized_at=?
        WHERE cycle_id=? AND status='Calibration'
    """, (user["username"], now, cycle_id))
    conn.execute("UPDATE performance_cycles SET status='Closed' WHERE id=?", (cycle_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM performance_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)


# --- Goals ---
@router.get("/api/performance/goals")
def list_goals(cycle_id: int, employee_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "superadmin":
        return []
    conn = get_db()
    if employee_id:
        if not _can_access_employee_performance(conn, inst_id, user, employee_id):
            conn.close(); raise HTTPException(403, "Access denied")
        rows = conn.execute(
            "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id=? ORDER BY created_at",
            (inst_id, cycle_id, employee_id)
        ).fetchall()
    elif user["role"] == "hr_manager":
        rows = conn.execute(
            "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? ORDER BY employee_id, created_at",
            (inst_id, cycle_id)
        ).fetchall()
    elif user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        rows = conn.execute(
            f"SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id IN {frag} ORDER BY employee_id, created_at",
            [inst_id, cycle_id, *fp]
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id=? ORDER BY created_at",
            (inst_id, cycle_id, user.get("employee_id", ""))
        ).fetchall()
    result = []
    for g in rows:
        d = dict(g)
        d["score"] = _score_goal(conn, g)
        if d["goal_type"] == "OKR":
            krs = conn.execute("SELECT * FROM okr_key_results WHERE goal_id=?", (g["id"],)).fetchall()
            d["key_results"] = [dict(k) for k in krs]
        result.append(d)
    conn.close()
    return result


@router.post("/api/performance/goals", status_code=201)
def create_goal(body: GoalIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    if not _can_access_employee_performance(conn, inst_id, user, body.employee_id):
        conn.close(); raise HTTPException(403, "Access denied")
    cycle = conn.execute("SELECT * FROM performance_cycles WHERE id=? AND institution_id=?", (body.cycle_id, inst_id)).fetchone()
    if not cycle: conn.close(); raise HTTPException(404, "Cycle not found")
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, f"Goals can only be added while the cycle is Active (currently {cycle['status']})")
    conn.execute("""
        INSERT INTO goals (institution_id,cycle_id,employee_id,goal_type,title,description,weight,target_value,actual_value,unit,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, body.cycle_id, body.employee_id, body.goal_type, body.title, body.description,
          body.weight, body.target_value, body.actual_value, body.unit, user["username"]))
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)


@router.put("/api/performance/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalUpdateIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND institution_id=?", (goal_id, inst_id)).fetchone()
    if not goal: conn.close(); raise HTTPException(404, "Goal not found")
    if not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    cycle = conn.execute("SELECT status FROM performance_cycles WHERE id=?", (goal["cycle_id"],)).fetchone()
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, "Goals can only be edited while the cycle is Active")
    title = body.title if body.title is not None else goal["title"]
    description = body.description if body.description is not None else goal["description"]
    weight = body.weight if body.weight is not None else goal["weight"]
    target_value = body.target_value if body.target_value is not None else goal["target_value"]
    actual_value = body.actual_value if body.actual_value is not None else goal["actual_value"]
    unit = body.unit if body.unit is not None else goal["unit"]
    conn.execute(
        "UPDATE goals SET title=?,description=?,weight=?,target_value=?,actual_value=?,unit=? WHERE id=?",
        (title, description, weight, target_value, actual_value, unit, goal_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/performance/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND institution_id=?", (goal_id, inst_id)).fetchone()
    if not goal: conn.close(); raise HTTPException(404, "Goal not found")
    if not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    cycle = conn.execute("SELECT status FROM performance_cycles WHERE id=?", (goal["cycle_id"],)).fetchone()
    if cycle["status"] != "Active":
        conn.close(); raise HTTPException(400, "Goals can only be deleted while the cycle is Active")
    conn.execute("DELETE FROM okr_key_results WHERE goal_id=?", (goal_id,))
    conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
    conn.commit(); conn.close()


@router.post("/api/performance/goals/{goal_id}/key-results", status_code=201)
def add_key_result(goal_id: int, body: KeyResultIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND institution_id=?", (goal_id, inst_id)).fetchone()
    if not goal: conn.close(); raise HTTPException(404, "Goal not found")
    if goal["goal_type"] != "OKR":
        conn.close(); raise HTTPException(400, "Key results can only be added to OKR goals")
    if not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute(
        "INSERT INTO okr_key_results (goal_id,description,target_value,actual_value) VALUES (?,?,?,?)",
        (goal_id, body.description, body.target_value, body.actual_value)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM okr_key_results WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)


@router.put("/api/performance/key-results/{kr_id}")
def update_key_result(kr_id: int, body: KeyResultIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    kr = conn.execute("SELECT * FROM okr_key_results WHERE id=?", (kr_id,)).fetchone()
    if not kr: conn.close(); raise HTTPException(404, "Key result not found")
    goal = conn.execute("SELECT * FROM goals WHERE id=?", (kr["goal_id"],)).fetchone()
    if goal["institution_id"] != inst_id or not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute(
        "UPDATE okr_key_results SET description=?,target_value=?,actual_value=? WHERE id=?",
        (body.description, body.target_value, body.actual_value, kr_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM okr_key_results WHERE id=?", (kr_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/performance/key-results/{kr_id}", status_code=204)
def delete_key_result(kr_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    kr = conn.execute("SELECT * FROM okr_key_results WHERE id=?", (kr_id,)).fetchone()
    if not kr: conn.close(); raise HTTPException(404, "Key result not found")
    goal = conn.execute("SELECT * FROM goals WHERE id=?", (kr["goal_id"],)).fetchone()
    if goal["institution_id"] != inst_id or not _can_access_employee_performance(conn, inst_id, user, goal["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    conn.execute("DELETE FROM okr_key_results WHERE id=?", (kr_id,))
    conn.commit(); conn.close()


# --- Appraisals ---
@router.get("/api/performance/appraisals")
def list_appraisals(cycle_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    if user["role"] == "superadmin":
        return []
    conn = get_db()
    base = """
        SELECT a.*, e.full_name, e.department, e.designation
        FROM appraisals a JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id
        WHERE a.institution_id=? AND a.cycle_id=?
    """
    if user["role"] == "hr_manager":
        rows = conn.execute(base + " ORDER BY e.full_name", (inst_id, cycle_id)).fetchall()
    elif user["role"] == "manager":
        frag, fp = subordinates_in_clause(inst_id, user.get("employee_id", ""))
        rows = conn.execute(base + f" AND a.employee_id IN {frag} ORDER BY e.full_name", [inst_id, cycle_id, *fp]).fetchall()
    else:
        rows = conn.execute(base + " AND a.employee_id=? ORDER BY e.full_name", (inst_id, cycle_id, user.get("employee_id", ""))).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/performance/appraisals/{appraisal_id}")
def get_appraisal(appraisal_id: int, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("""
        SELECT a.*, e.full_name, e.department, e.designation
        FROM appraisals a JOIN employees e ON e.employee_id=a.employee_id AND e.institution_id=a.institution_id
        WHERE a.id=? AND a.institution_id=?
    """, (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if not _can_access_employee_performance(conn, inst_id, user, ap["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    goals = conn.execute(
        "SELECT * FROM goals WHERE institution_id=? AND cycle_id=? AND employee_id=? ORDER BY created_at",
        (inst_id, ap["cycle_id"], ap["employee_id"])
    ).fetchall()
    result = dict(ap)
    goal_list, total_weight = [], 0.0
    for g in goals:
        d = dict(g)
        d["score"] = _score_goal(conn, g)
        if d["goal_type"] == "OKR":
            krs = conn.execute("SELECT * FROM okr_key_results WHERE goal_id=?", (g["id"],)).fetchall()
            d["key_results"] = [dict(k) for k in krs]
        total_weight += g["weight"] or 0
        goal_list.append(d)
    result["goals"] = goal_list
    result["total_weight"] = total_weight
    result["live_computed_rating"] = _compute_weighted_rating(conn, ap["cycle_id"], ap["employee_id"])
    conn.close()
    return result


@router.post("/api/performance/appraisals/{appraisal_id}/self-review")
def submit_self_review(appraisal_id: int, body: SelfReviewIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if user.get("employee_id") != ap["employee_id"]:
        conn.close(); raise HTTPException(403, "You can only submit your own self-review")
    if ap["status"] != "SelfReview":
        conn.close(); raise HTTPException(400, f"Appraisal is not awaiting self-review (current status: {ap['status']})")
    rating = _compute_weighted_rating(conn, ap["cycle_id"], ap["employee_id"])
    conn.execute(
        "UPDATE appraisals SET self_rating=?, self_comments=?, status='ManagerReview' WHERE id=?",
        (rating, body.self_comments, appraisal_id)
    )
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Self-Review Submitted", f"Self rating: {rating}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM appraisals WHERE id=?", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)


@router.post("/api/performance/appraisals/{appraisal_id}/manager-review")
def submit_manager_review(appraisal_id: int, body: ManagerReviewIn, user: dict = Depends(get_current_user)):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if user["role"] not in ("manager", "hr_manager"):
        conn.close(); raise HTTPException(403, "Only a manager or HR can submit a manager review")
    if user.get("employee_id") == ap["employee_id"]:
        conn.close(); raise HTTPException(403, "You cannot manager-review your own appraisal")
    if not _can_access_employee_performance(conn, inst_id, user, ap["employee_id"]):
        conn.close(); raise HTTPException(403, "Access denied")
    if ap["status"] != "ManagerReview":
        conn.close(); raise HTTPException(400, f"Appraisal is not awaiting manager review (current status: {ap['status']})")
    rating = body.manager_rating if body.manager_rating is not None else _compute_weighted_rating(conn, ap["cycle_id"], ap["employee_id"])
    conn.execute(
        "UPDATE appraisals SET manager_rating=?, manager_comments=?, status='Calibration' WHERE id=?",
        (rating, body.manager_comments, appraisal_id)
    )
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Manager Review Submitted", f"Manager rating: {rating}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM appraisals WHERE id=?", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)


@router.post("/api/performance/appraisals/{appraisal_id}/calibrate")
def calibrate_appraisal(appraisal_id: int, body: CalibrateIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if ap["status"] != "Calibration":
        conn.close(); raise HTTPException(400, f"Appraisal is not awaiting calibration (current status: {ap['status']})")
    conn.execute(
        "UPDATE appraisals SET calibrated_rating=?, calibration_notes=? WHERE id=?",
        (body.calibrated_rating, body.calibration_notes, appraisal_id)
    )
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Calibrated",
                    f"Calibrated rating: {body.calibrated_rating}" if body.calibrated_rating is not None else "No override", user)
    conn.commit()
    row = conn.execute("SELECT * FROM appraisals WHERE id=?", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)


# ---------------------------------------------------------------------------
# Performance -> Payroll integration (Phase 2)
# ---------------------------------------------------------------------------
@router.post("/api/performance/appraisals/{appraisal_id}/merit-increment", status_code=201)
def apply_merit_increment(appraisal_id: int, body: MeritIncrementIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if ap["status"] != "Finalized":
        conn.close(); raise HTTPException(400, "Merit increments can only be applied to a Finalized appraisal")
    existing = conn.execute(
        "SELECT id FROM performance_payouts WHERE appraisal_id=? AND payout_type='MeritIncrement'", (appraisal_id,)
    ).fetchone()
    if existing:
        conn.close(); raise HTTPException(400, "A merit increment has already been applied for this appraisal")
    emp = conn.execute("SELECT * FROM employees WHERE institution_id=? AND employee_id=?", (inst_id, ap["employee_id"])).fetchone()
    if not emp: conn.close(); raise HTTPException(404, "Employee not found")
    old_salary = emp["basic_salary"] or 0.0
    delta = round(old_salary * body.increment_pct / 100, 2)
    new_salary = round(old_salary + delta, 2)
    conn.execute("UPDATE employees SET basic_salary=? WHERE institution_id=? AND employee_id=?", (new_salary, inst_id, ap["employee_id"]))
    conn.execute("""
        INSERT INTO performance_payouts (institution_id, appraisal_id, employee_id, payout_type, amount, increment_pct, status, created_by, applied_at)
        VALUES (?,?,?,?,?,?,?,?, to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'))
    """, (inst_id, appraisal_id, ap["employee_id"], "MeritIncrement", delta, body.increment_pct, "Applied", user["username"]))
    write_audit(conn, user, inst_id, ap["employee_id"], emp["full_name"], "Merit Increment Applied",
                [f"Basic Salary: {old_salary:.2f} -> {new_salary:.2f} ({body.increment_pct}% via appraisal #{appraisal_id})"])
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Merit Increment Applied",
                    f"{body.increment_pct}% (+{delta:.2f}), new basic salary {new_salary:.2f}", user)
    conn.commit()
    row = conn.execute("SELECT * FROM performance_payouts WHERE appraisal_id=? AND payout_type='MeritIncrement'", (appraisal_id,)).fetchone()
    conn.close()
    return dict(row)


@router.post("/api/performance/appraisals/{appraisal_id}/bonus", status_code=201)
def queue_bonus_payout(appraisal_id: int, body: BonusPayoutIn, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    ap = conn.execute("SELECT * FROM appraisals WHERE id=? AND institution_id=?", (appraisal_id, inst_id)).fetchone()
    if not ap: conn.close(); raise HTTPException(404, "Appraisal not found")
    if ap["status"] != "Finalized":
        conn.close(); raise HTTPException(400, "Bonuses can only be queued for a Finalized appraisal")
    conn.execute("""
        INSERT INTO performance_payouts (institution_id, appraisal_id, employee_id, payout_type, amount, status, created_by)
        VALUES (?,?,?,?,?,?,?)
    """, (inst_id, appraisal_id, ap["employee_id"], "Bonus", body.amount, "Pending", user["username"]))
    _log_appraisal(conn, inst_id, appraisal_id, ap["employee_id"], "Bonus Queued",
                    f"RM {body.amount:.2f} queued — will be added to the next payroll run", user)
    conn.commit()
    row = conn.execute(
        "SELECT * FROM performance_payouts WHERE appraisal_id=? AND payout_type='Bonus' ORDER BY id DESC LIMIT 1", (appraisal_id,)
    ).fetchone()
    conn.close()
    return dict(row)


@router.get("/api/performance/payouts")
def list_performance_payouts(status: Optional[str] = None, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES, *PAYROLL_VIEW_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    sql = """
        SELECT po.*, e.full_name, e.department, e.designation
        FROM performance_payouts po
        JOIN employees e ON e.institution_id=po.institution_id AND e.employee_id=po.employee_id
        WHERE po.institution_id=?
    """
    params = [inst_id]
    if status:
        sql += " AND po.status=?"
        params.append(status)
    sql += " ORDER BY po.created_at DESC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.delete("/api/performance/payouts/{payout_id}", status_code=204)
def cancel_bonus_payout(payout_id: int, user: dict = Depends(require_roles(*PERFORMANCE_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    payout = conn.execute("SELECT * FROM performance_payouts WHERE id=? AND institution_id=?", (payout_id, inst_id)).fetchone()
    if not payout: conn.close(); raise HTTPException(404, "Payout not found")
    if payout["status"] != "Pending":
        conn.close(); raise HTTPException(400, "Only a Pending bonus payout can be cancelled")
    conn.execute("DELETE FROM performance_payouts WHERE id=?", (payout_id,))
    _log_appraisal(conn, inst_id, payout["appraisal_id"], payout["employee_id"], "Bonus Cancelled",
                    f"RM {payout['amount']:.2f} cancelled before payout", user)
    conn.commit()
    conn.close()
