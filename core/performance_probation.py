"""Onboarding Probation Reviews (Month 1/2/3): employee-scoped Performance
cycles, opted into per-employee by HR — not automatic, not template-
driven, since not every employee goes through probation (see
routers/onboarding.py's enable-probation-review endpoint and the
OBChecklistStartIn.enable_probation_review flag on starting a checklist).

Reuses the Performance module's Goals/Appraisal engine as-is (weighted
scoring, Self -> Manager -> Calibration -> Final — routers/performance.py)
via a second, single-employee cycle mode: cycle_type='probation' with
employee_id set, distinct from the institution-wide 'standard' cycles HR
creates manually. A probation cycle skips the manual Draft -> Activate
step (created pre-Active with its one appraisal already in place) and
skips activate_performance_cycle's org-wide employee fan-out entirely —
it only ever has the one appraisal it's created with.

Deliberately has no dependency on routers/onboarding.py (which imports
*this* module) — the caller computes each month's (period_start,
period_end) window with its own _add_months helper and passes them in,
rather than this module importing that helper back, to avoid a circular
import between the two.
"""
from datetime import date
from typing import Any, Dict, List, Tuple

# Fallback rubric only — used when an institution hasn't defined its own
# criteria in probation_goal_templates (Settings -> Performance, hr_manager
# only; see routers/performance.py's probation-goal-template endpoints and
# migrations/versions/20260923_0001_add_probation_goal_templates.py). Kept
# here, unchanged, as the zero-configuration default every institution
# started with before that screen existed.
PROBATION_RUBRIC = (
    ("Job Knowledge", "Understands the role's responsibilities and required skills."),
    ("Quality of Work", "Accuracy, thoroughness, and consistency of work produced."),
    ("Productivity", "Completes assigned tasks within expected timeframes."),
    ("Attendance & Punctuality", "Reliability in attendance and adherence to work hours."),
    ("Communication", "Clarity and effectiveness of communication with colleagues and managers."),
    ("Cultural Fit", "Alignment with company values and ability to work within the team."),
)


def _probation_goal_criteria(conn, inst_id: int) -> List[Tuple[str, str, float]]:
    """(title, description, weight%) for this institution's probation goal
    criteria — its own probation_goal_templates rows if it has any, else
    the fixed PROBATION_RUBRIC default. Template weights are *relative*
    (not required to sum to 100 — see the migration's docstring), so
    they're normalized proportionally to 100% here, at the one place
    they're actually turned into real goal rows; the settings screen
    itself never has to enforce a running total."""
    rows = conn.execute(
        "SELECT name, description, weight FROM probation_goal_templates WHERE institution_id=? ORDER BY sort_order, id",
        (inst_id,)
    ).fetchall()
    if not rows:
        even_weight = round(100 / len(PROBATION_RUBRIC), 2)
        return [(title, description, even_weight) for title, description in PROBATION_RUBRIC]
    total_weight = sum(r["weight"] for r in rows)
    return [(r["name"], r["description"], round(r["weight"] / total_weight * 100, 2)) for r in rows]


def create_probation_reviews(conn, inst_id: int, emp: Dict[str, Any], checklist_id: int,
                             month_windows: List[Tuple[int, date, date]], user: dict) -> None:
    """Creates one probation cycle per (month_number, period_start, period_end)
    window — each already Active with a single appraisal and this
    institution's probation goal criteria seeded as goals (its own
    probation_goal_templates rows, or the built-in default rubric if it
    hasn't defined any — see _probation_goal_criteria), ready for the
    employee to self-review immediately."""
    criteria = _probation_goal_criteria(conn, inst_id)
    for month, period_start, period_end in month_windows:
        conn.execute(
            """
            INSERT INTO performance_cycles
            (institution_id,name,period_start,period_end,status,created_by,
             employee_id,cycle_type,source_ob_checklist_id)
            VALUES (?,?,?,?,'Active',?,?,'probation',?)
            """,
            (inst_id, f"Probation Review — Month {month} — {emp['full_name']}",
             period_start.isoformat(), period_end.isoformat(), user["username"],
             emp["employee_id"], checklist_id)
        )
        cycle_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO appraisals (institution_id,cycle_id,employee_id,status) VALUES (?,?,?,'SelfReview')",
            (inst_id, cycle_id, emp["employee_id"])
        )
        for title, description, weight in criteria:
            conn.execute(
                """
                INSERT INTO goals (institution_id,cycle_id,employee_id,goal_type,title,description,
                                    weight,target_value,unit,created_by)
                VALUES (?,?,?,'KPI',?,?,?,5,'rating (1-5)',?)
                """,
                (inst_id, cycle_id, emp["employee_id"], title, description, weight, user["username"])
            )
    conn.commit()


def delete_probation_reviews(conn, inst_id: int, checklist_id: int) -> None:
    """Deletes every probation cycle create_probation_reviews() started
    for this onboarding checklist, and everything under them — none of
    this has a real foreign-key constraint back to ob_checklists (unlike
    ob_checklist_items, which does), so it would otherwise silently
    survive as orphaned performance-management data once the checklist
    that spawned it is deleted (routers/onboarding.py's
    delete_ob_checklist). Mirrors create_probation_reviews' own shape:
    cycle -> appraisal -> goals, plus whatever the employee did with
    those afterward (a PIP check-in, a payout) that a plain cycle/
    appraisal/goal delete would otherwise be blocked by (NO ACTION FKs)."""
    cycle_ids = [r[0] for r in conn.execute(
        "SELECT id FROM performance_cycles WHERE institution_id=? AND source_ob_checklist_id=?",
        (inst_id, checklist_id)
    ).fetchall()]
    if not cycle_ids:
        return
    cycle_ph = ",".join("?" for _ in cycle_ids)

    appraisal_ids = [r[0] for r in conn.execute(
        f"SELECT id FROM appraisals WHERE cycle_id IN ({cycle_ph})", cycle_ids
    ).fetchall()]
    goal_ids = [r[0] for r in conn.execute(
        f"SELECT id FROM goals WHERE cycle_id IN ({cycle_ph})", cycle_ids
    ).fetchall()]

    if appraisal_ids:
        appraisal_ph = ",".join("?" for _ in appraisal_ids)
        conn.execute(f"DELETE FROM performance_payouts WHERE appraisal_id IN ({appraisal_ph})", appraisal_ids)
    if goal_ids:
        goal_ph = ",".join("?" for _ in goal_ids)
        conn.execute(f"DELETE FROM okr_key_results WHERE goal_id IN ({goal_ph})", goal_ids)

    conn.execute(f"DELETE FROM pip_checkins WHERE cycle_id IN ({cycle_ph})", cycle_ids)
    if appraisal_ids:
        conn.execute(f"DELETE FROM appraisals WHERE id IN ({appraisal_ph})", appraisal_ids)
    if goal_ids:
        conn.execute(f"DELETE FROM goals WHERE id IN ({goal_ph})", goal_ids)
    conn.execute(f"DELETE FROM performance_cycles WHERE id IN ({cycle_ph})", cycle_ids)
