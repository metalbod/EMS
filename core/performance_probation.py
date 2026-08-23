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

# Fixed rubric — no per-institution configuration screen, ships as-is.
PROBATION_RUBRIC = (
    ("Job Knowledge", "Understands the role's responsibilities and required skills."),
    ("Quality of Work", "Accuracy, thoroughness, and consistency of work produced."),
    ("Productivity", "Completes assigned tasks within expected timeframes."),
    ("Attendance & Punctuality", "Reliability in attendance and adherence to work hours."),
    ("Communication", "Clarity and effectiveness of communication with colleagues and managers."),
    ("Cultural Fit", "Alignment with company values and ability to work within the team."),
)


def create_probation_reviews(conn, inst_id: int, emp: Dict[str, Any], checklist_id: int,
                             month_windows: List[Tuple[int, date, date]], user: dict) -> None:
    """Creates one probation cycle per (month_number, period_start, period_end)
    window — each already Active with a single appraisal and the fixed
    6-criterion rubric seeded as goals, ready for the employee to
    self-review immediately."""
    weight = round(100 / len(PROBATION_RUBRIC), 2)
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
        for title, description in PROBATION_RUBRIC:
            conn.execute(
                """
                INSERT INTO goals (institution_id,cycle_id,employee_id,goal_type,title,description,
                                    weight,target_value,unit,created_by)
                VALUES (?,?,?,'KPI',?,?,?,5,'rating (1-5)',?)
                """,
                (inst_id, cycle_id, emp["employee_id"], title, description, weight, user["username"])
            )
    conn.commit()
