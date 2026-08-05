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

try:
    from core.deps import get_current_user, need_inst
except ImportError:
    from ems.core.deps import get_current_user, need_inst

try:
    from core.org_queries import subordinates_in_clause
except ImportError:
    from ems.core.org_queries import subordinates_in_clause

try:
    from core.approval_workflow import count_pending_for_approver
except ImportError:
    from ems.core.approval_workflow import count_pending_for_approver

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()


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
    # approver — direct/skip-level manager steps naturally resolve to 0 for
    # users with no linked employee_id, so this is safe to run regardless.
    approval_targets = (
        ("leave", "leave-approvals", "leave application"),
        ("claims", "ben-claims", "benefit claim"),
        ("requisition", "requisitions", "job requisition"),
        ("timesheet", "timesheet-approvals", "timesheet"),
        ("ld_enrollment", "ld-trainings", "training enrollment"),
        ("overtime", "timesheet-approvals", "overtime record"),
    )
    for module, page, noun in approval_targets:
        cnt = count_pending_for_approver(conn, inst_id, user, module)
        if cnt:
            todos.append({
                "key": f"{module}-approvals",
                "label": f"{cnt} {noun}{'s' if cnt != 1 else ''} awaiting your approval",
                "page": page, "count": cnt,
            })

    return todos
