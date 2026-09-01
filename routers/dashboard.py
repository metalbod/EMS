"""
Dashboard To-Do List — personal items (about the logged-in user's own
data), plus items pending this user's own decision as an approval-workflow
approver (see core/approval_workflow.py) — the latter already had one
precedent before this module existed (the ManagerReview appraisal item
below), so this isn't a new exception to the "personal only" rule so much
as generalizing the one that was already there.
Computed on every request from live state (not stored), so items disappear
automatically once actioned. Excluded for superadmin (no personal employee record).
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from core.deps import get_current_user, need_inst

from core.org_queries import subordinates_in_clause

from core.approval_workflow import pending_rows_for_approver

from routers.employee_documents import STATUS_CASE_SQL

from db import get_db

from core.db_session import db_session

router = APIRouter()


def _approval_row_detail(conn, inst_id: int, module: str, row) -> Dict[str, Any]:
    """Resolve the (employee, stage label, stage type, due date) shown on
    one per-item To-Do row for a pending approval-workflow request —
    mirrors the shape the onboarding/offboarding checklist items below
    already use, rather than the aggregate "N items" count this replaced.
    One branch per module in MODULE_TABLE (core/approval_workflow.py);
    each row's own columns differ enough (a leave application isn't shaped
    like a benefit claim) that a generic renderer would just be a wall of
    "if this column exists" checks — see docs/adr/0001 on why this
    codebase doesn't force genuinely different row shapes through one
    renderer."""
    if module == "leave":
        lt = conn.execute("SELECT name FROM leave_types WHERE id=?", (row["leave_type_id"],)).fetchone()
        return {
            "employee_id": row["employee_id"],
            "stage": f"{lt['name'] if lt else 'Leave'}: {row['start_date']} to {row['end_date']}",
            "stage_type": "Leave", "due_date": row["start_date"],
        }
    if module == "claims":
        p = conn.execute("SELECT plan_name FROM benefit_plans WHERE id=?", (row["benefit_plan_id"],)).fetchone()
        return {
            "employee_id": row["employee_id"],
            "stage": f"{p['plan_name'] if p else 'Benefit'} claim — RM {row['amount_claimed']}",
            "stage_type": "Benefit Claim", "due_date": row["claim_date"],
        }
    if module == "requisition":
        u = conn.execute(
            "SELECT employee_id FROM users WHERE username=? AND institution_id=?",
            (row["created_by"], inst_id)
        ).fetchone()
        return {
            "employee_id": u["employee_id"] if u else None,
            "stage": f"{row['title']} ({row['department']})",
            "stage_type": "Job Requisition", "due_date": row["created_at"],
        }
    if module == "timesheet":
        return {
            "employee_id": row["employee_id"],
            "stage": f"Week of {row['period_start']}",
            "stage_type": "Timesheet", "due_date": row["period_start"],
        }
    if module == "ld_enrollment":
        c = conn.execute("SELECT title FROM ld_courses WHERE id=?", (row["course_id"],)).fetchone()
        return {
            "employee_id": row["employee_id"],
            "stage": c["title"] if c else "Training course",
            "stage_type": "Training Enrollment", "due_date": row["created_at"],
        }
    if module == "overtime":
        return {
            "employee_id": row["employee_id"],
            "stage": f"{row['overtime_hours']}h overtime on {row['work_date']}",
            "stage_type": "Overtime", "due_date": row["work_date"],
        }
    if module == "resignation":
        return {
            "employee_id": row["employee_id"],
            "stage": f"Resignation — last day {row['last_working_day']}",
            "stage_type": "Resignation", "due_date": row["effective_date"],
        }
    # pip: performance_cycles row (cycle_type='pip'), see MODULE_TABLE.
    return {
        "employee_id": row["employee_id"],
        "stage": row["name"],
        "stage_type": "PIP", "due_date": row["created_at"],
    }


@router.get("/api/todos")
@db_session
def get_todos(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    role = user["role"]
    if role == "superadmin":
        return []
    inst_id = need_inst(user)
    emp_id = user.get("employee_id")
    todos = []

    if emp_id:
        today = datetime.now(timezone.utc).date()
        monday = (today - timedelta(days=today.weekday())).isoformat()
        row = conn.execute(
            "SELECT id FROM timesheets WHERE institution_id=? AND employee_id=? AND period_start=? AND status='Draft'",
            (inst_id, emp_id, monday)
        ).fetchone()
        if row:
            todos.append({"key": "timesheet-my", "label": "Your timesheet for this week hasn't been submitted yet", "page": "timesheet-my", "count": 1})

        cnt = conn.execute(
            "SELECT COUNT(*) FROM ld_enrollments WHERE institution_id=? AND employee_id=? AND status='In Progress'",
            (inst_id, emp_id)
        ).fetchone()[0]
        if cnt:
            todos.append({"key": "ld-trainings", "label": f"{cnt} training course{'s' if cnt != 1 else ''} in progress", "page": "ld-trainings", "count": cnt})

        if role in ("manager", "hr_manager"):
            frag, fp = subordinates_in_clause(inst_id, emp_id)
            cnt = conn.execute(f"""
                SELECT COUNT(*) FROM appraisals a
                WHERE a.institution_id=? AND a.status='ManagerReview' AND a.employee_id != ?
                  AND a.employee_id IN {frag}
            """, (inst_id, emp_id, *fp)).fetchone()[0]
            if cnt:
                todos.append({"key": "perf-team", "label": f"{cnt} appraisal{'s' if cnt != 1 else ''} awaiting your manager review", "page": "perf-team", "count": cnt})

    # Items pending this user's own decision as an approval-workflow
    # approver — direct/skip-level manager steps naturally resolve to no
    # rows for users with no linked employee_id, so this is safe to run
    # regardless. One To-Do row per pending request (not an aggregate
    # count) so the queue shows what's actually waiting — matching the
    # onboarding/offboarding checklist items below, which already do this.
    approval_targets = (
        ("leave", "leave-approvals", "Leave"),
        ("claims", "ben-claims", "Benefit Claim"),
        ("requisition", "requisitions", "Job Requisition"),
        ("timesheet", "timesheet-approvals", "Timesheet"),
        ("ld_enrollment", "ld-trainings", "Training Enrollment"),
        ("overtime", "timesheet-approvals", "Overtime"),
        ("resignation", "resignation-approvals", "Resignation"),
        ("pip", "perf-team", "PIP"),
    )
    for module, page, noun in approval_targets:
        rows = pending_rows_for_approver(conn, inst_id, user, module)
        for row in rows:
            detail = _approval_row_detail(conn, inst_id, module, row)
            emp = conn.execute(
                "SELECT full_name FROM employees WHERE institution_id=? AND employee_id=?",
                (inst_id, detail["employee_id"])
            ).fetchone() if detail["employee_id"] else None
            employee_name = emp["full_name"] if emp else "Unknown"
            todos.append({
                "key": f"{module}-approval-{row['id']}",
                "label": f"{detail['stage']} — {employee_name} ({noun.lower()}, awaiting your approval)",
                "page": page, "count": 1,
                # Same extra keys the onboarding items below add, for the
                # Home page To-Do queue's per-item rendering.
                "employee_name": employee_name, "stage": detail["stage"],
                "stage_type": detail["stage_type"], "due_date": detail["due_date"],
            })

    # Employee document compliance reminders (work permit renewal, passport
    # expiry, etc — see routers/employee_documents.py) — HR-only,
    # institution-wide (no per-employee narrowing, same as the onboarding
    # block below for HR roles), one aggregate row rather than one per
    # document since counts could be numerous.
    if role in ("hr_manager", "hr_admin"):
        cnt = conn.execute(f"""
            SELECT COUNT(*) FROM employee_documents ed
            JOIN employee_document_types edt ON edt.id = ed.document_type_id
            WHERE ed.institution_id=? AND ({STATUS_CASE_SQL}) != 'ok'
        """, (inst_id,)).fetchone()[0]
        if cnt:
            todos.append({
                "key": "employee-documents-expiring",
                "label": f"{cnt} employee document{'s' if cnt != 1 else ''} expiring soon",
                "page": "dash-leave", "count": cnt,
            })

    # Onboarding/Offboarding checklist items assigned to this user's role —
    # same "my_pending" scoping list_ob_checklists (routers/onboarding.py)
    # already uses per-checklist, one row per pending item here so the
    # To-Do card shows what the task actually is (title), not just a
    # count. An employee only sees their own checklist's items, a manager
    # only their subordinates', HR sees institution-wide — matching that
    # endpoint's existing role scoping exactly.
    ob_q = """
        SELECT i.id, i.title, i.due_date, c.type, c.employee_id, e.full_name AS employee_name
        FROM ob_checklist_items i
        JOIN ob_checklists c ON c.id = i.checklist_id
        JOIN employees e ON e.employee_id = c.employee_id AND e.institution_id = c.institution_id
        WHERE c.institution_id=? AND i.status='Pending' AND i.assigned_role=?
    """
    ob_params: list = [inst_id, role]
    if role == "manager":
        frag, fp = subordinates_in_clause(inst_id, emp_id or "")
        ob_q += f" AND c.employee_id IN {frag}"; ob_params.extend(fp)
    elif role == "employee":
        ob_q += " AND c.employee_id=?"; ob_params.append(emp_id or "")
    ob_q += " ORDER BY c.type, c.employee_id, i.order_index"
    ob_rows = conn.execute(ob_q, ob_params).fetchall()
    ob_type_labels = {"onboarding": "Onboarding", "offboarding": "Offboarding"}
    for r in ob_rows:
        type_label = ob_type_labels.get(r["type"], r["type"].capitalize())
        # An employee's own items are obviously about themselves — only
        # name-drop the employee for HR/manager viewers looking at
        # someone else's checklist.
        label = r["title"] if role == "employee" else f"{r['title']} — {r['employee_name']}"
        todos.append({
            "key": f"ob-item-{r['id']}",
            "label": f"{label} ({type_label})",
            "page": r["type"], "count": 1,
            # Extra fields for the redesigned To-Do queue (Home page) to
            # render a real avatar/employee/stage/due-date row instead of
            # just a title — same shape the approval_targets loop above
            # now also produces. The two remaining aggregate-count sources
            # (training courses in progress, employee documents expiring)
            # stay plain counts: there's no single employee/date to
            # honestly show for "3 documents expiring soon" the way there
            # is for one specific pending request. Harmless extra keys for
            # any older client still reading just label/page/count.
            "employee_name": r["employee_name"], "stage": r["title"],
            "stage_type": type_label, "due_date": r["due_date"],
        })

    return todos
