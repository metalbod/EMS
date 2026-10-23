"""Claude self-service: the signed-in person's To-Do list (the MCP server's my_todos tool).

It is the same list the Home To-Do widget shows (routers/dashboard.py's build_todos), read-only, with two decisions made on top:

* "Everything outstanding": the widget has no notion of a daily list, so this returns what is waiting now, in three buckets: overdue (a
  real deadline has passed), today (due or happening today: an interview, a leave starting) and everything else still waiting.
* Sensitive matters are COUNTS ONLY: resignation and PIP approvals and offboarding checklist tasks (who is leaving) come back as a number
  per category and are never named. What Claude says gets pasted into chats and notes, which is also why colleagues_on_leave never says
  the type of leave. The person still sees the names in EMS.

Leave approvals are described by their dates only (never the leave type) and benefit claims without the plan or amount.

No approving or rejecting here: that stays on the Home screen.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.db_session import db_session
from core.deps import get_current_user, need_inst
from core.institution_time import institution_today
from routers.dashboard import build_todos

router = APIRouter()
MAX_LISTED = 50

APPROVAL_CATEGORIES = {
    "leave": "Leave approval", "claims": "Benefit claim approval", "requisition": "Job requisition approval",
    "timesheet": "Timesheet approval", "ld_enrollment": "Training enrolment approval", "overtime": "Overtime approval",
}
SENSITIVE_APPROVALS = {"resignation": "Resignation approvals", "pip": "PIP approvals"}
OFFBOARDING = "Offboarding checklist tasks"
REMINDER_CATEGORIES = {
    "timesheet-my": "Timesheet draft", "ld-trainings": "Training in progress", "policy-ack": "Policy to acknowledge",
    "perf-team": "Appraisal review", "employee-documents-expiring": "Employee documents expiring",
}


def classify(t: Dict[str, Any]):
    """(category, sensitive) for one To-Do row. `sensitive` rows are reported only as a count."""
    if t.get("kind") == "approval":
        if t.get("module") in SENSITIVE_APPROVALS:
            return SENSITIVE_APPROVALS[t["module"]], True
        return APPROVAL_CATEGORIES.get(t.get("module"), "Approval"), False
    key = t.get("key") or ""
    if key.startswith("ob-item-"):
        return (OFFBOARDING, True) if t.get("stage_type") == "Offboarding" else ("Onboarding task", False)
    if key.startswith("interview-"):
        return "Interview", False
    return REMINDER_CATEGORIES.get(key, "Other"), False


def _title(t: Dict[str, Any], category: str) -> Optional[str]:
    """What Claude is allowed to say for this row. The widget's own label for a LEAVE approval carries the leave type and for a benefit
    claim the plan and amount, so approvals are re-worded here from `safe_detail` (dates only, never the type) instead of reusing it."""
    if t.get("kind") == "approval":
        detail = t.get("safe_detail")
        return f"{category}: {t.get('employee_name') or 'someone'}" + (f" ({detail})" if detail else "")
    return t.get("label")


def _item(t: Dict[str, Any], category: str) -> Dict[str, Any]:
    out = {"category": category, "title": _title(t, category), "person": t.get("employee_name"),
           "due_date": t.get("due_date"), "days_overdue": t.get("days_overdue"), "days_waiting": t.get("days_waiting"),
           "event_date": t.get("event_date"), "days_until_event": t.get("days_until_event")}
    if (t.get("count") or 1) > 1:
        out["count"] = t["count"]
    return {k: v for k, v in out.items() if v is not None}


@router.get("/api/me/todos", tags=["dashboard"])
@db_session
def my_todos(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not user.get("employee_id"):
        raise HTTPException(400, "No employee record is linked to this account")
    today = institution_today(conn, inst_id)
    overdue: List[Dict[str, Any]] = []
    due_today: List[Dict[str, Any]] = []
    waiting: List[Dict[str, Any]] = []
    sensitive: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    total = 0
    for t in build_todos(conn, user):
        category, is_sensitive = classify(t)
        n = int(t.get("count") or 1)
        counts[category] = counts.get(category, 0) + n
        total += n
        if is_sensitive:
            sensitive[category] = sensitive.get(category, 0) + n
            continue
        item = _item(t, category)
        if t.get("days_overdue") is not None:
            overdue.append(item)
        elif t.get("due_date") == today or t.get("event_date") == today:
            due_today.append(item)
        else:
            waiting.append(item)
    listed = overdue + due_today + waiting
    truncated = len(listed) > MAX_LISTED
    if truncated:                                            # keep the most pressing first: overdue, then today, then the rest
        overdue, due_today = overdue[:MAX_LISTED], due_today[:max(0, MAX_LISTED - len(overdue))]
        waiting = waiting[:max(0, MAX_LISTED - len(overdue) - len(due_today))]
    return {"date": today, "total_items": total, "counts": counts, "overdue": overdue, "today": due_today, "waiting": waiting,
            "sensitive_counts": sensitive, "listed": len(overdue) + len(due_today) + len(waiting), "truncated": truncated}
