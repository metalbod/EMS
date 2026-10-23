"""
Approvals inbox — everything waiting on the signed-in person's decision, in one list, with the context to decide it.

Two read-only endpoints; the decisions themselves are still made through each module's own endpoint (leave, timesheet,
overtime, claims, requisition, resignation, L&D, PIP), so every permission and workflow check stays exactly where it was:

* GET /api/approvals — the approval rows of the Home To-Do (routers/dashboard.py's build_todos), approvals only, with a
  count per module. Same rows, same order (past-deadline first, then longest-waiting), so the inbox and Home can't disagree.
* GET /api/approvals/{module}/{ref_id}/context — the facts beside a request (dates, reason, balance, who else is away,
  the approval steps). Fail-closed: only a request that is sitting at a step *this* person may act on right now is
  answered (the same test the To-Do uses), otherwise 404 — so it can't be used to read someone else's request.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.approval_workflow import (
    MODULE_DISPLAY_NAME, _describe_approver_type, _decided_step_orders, _get_workflow_mode,
    _request_identity_for_row, _requester_employee_id, get_steps, pending_rows_for_approver, project_ids_for_row,
)
from core.db_session import db_session
from core.deps import get_current_user, need_inst
from routers.dashboard import build_todos, module_is_project_row

router = APIRouter()

APPROVAL_MODULES = ("leave", "claims", "requisition", "timesheet", "ld_enrollment", "overtime", "resignation", "pip")


@router.get("/api/approvals")
@db_session
def list_approvals(conn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    items = [t for t in build_todos(conn, user) if t.get("kind") == "approval"]
    counts: Dict[str, int] = {m: 0 for m in APPROVAL_MODULES}
    for t in items:
        counts[t["module"]] = counts.get(t["module"], 0) + 1
    return {"items": items, "counts": counts, "total": len(items)}


def _fact(label: str, value: Any) -> Optional[Dict[str, str]]:
    if value is None or str(value).strip() == "":
        return None
    return {"label": label, "value": str(value)}


def _employee_card(conn, inst_id: int, employee_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not employee_id:
        return None
    e = conn.execute(
        "SELECT employee_id, full_name, preferred_name, department, designation FROM employees "
        "WHERE employee_id=? AND institution_id=?", (employee_id, inst_id)).fetchone()
    if not e:
        return None
    return {"employee_id": e["employee_id"], "name": (e["preferred_name"] or e["full_name"]),
            "department": e["department"], "designation": e["designation"]}


def _steps(conn, inst_id: int, module: str, employee_id: str, row) -> List[Dict[str, str]]:
    """Every approval step with where this request is: done / current / upcoming (flat workflows: decided or open)."""
    workflow_id = row["approval_workflow_id"]
    if not workflow_id:
        return []
    steps = get_steps(conn, workflow_id)
    project_ids = project_ids_for_row(conn, module, row)
    flat = _get_workflow_mode(conn, workflow_id) == "flat"
    decided = set()
    if flat:
        table, rid = _request_identity_for_row(module, row)
        decided = _decided_step_orders(conn, table, rid)
    out = []
    for s in steps:
        label = _describe_approver_type(conn, inst_id, employee_id, s["approver_type"], s["specific_employee_id"], project_ids)
        if s.get("alt_approver_type"):
            label += " or " + _describe_approver_type(conn, inst_id, employee_id, s["alt_approver_type"],
                                                      s.get("alt_specific_employee_id"), project_ids)
        if flat:
            state = "done" if s["step_order"] in decided else "current"
        else:
            state = "done" if s["step_order"] < row["approval_step"] else "current" if s["step_order"] == row["approval_step"] else "upcoming"
        out.append({"label": label, "state": state})
    return out


def _leave_facts(conn, inst_id: int, row) -> Dict[str, Any]:
    lt = conn.execute("SELECT name, shares_entitlement_with_id FROM leave_types WHERE id=? AND institution_id=?",
                      (row["leave_type_id"], inst_id)).fetchone()
    pool_id = (lt["shares_entitlement_with_id"] if lt and lt["shares_entitlement_with_id"] else row["leave_type_id"])
    year = int(str(row["start_date"])[:4])
    bal = conn.execute(
        "SELECT entitled_days, carried_forward_days, used_days FROM leave_balances "
        "WHERE employee_id=? AND leave_type_id=? AND year=? AND institution_id=?",
        (row["employee_id"], pool_id, year, inst_id)).fetchone()
    facts = [
        _fact("Leave type", lt["name"] if lt else None),
        _fact("Dates", f"{row['start_date']} to {row['end_date']}" if row["start_date"] != row["end_date"] else row["start_date"]),
        _fact("Days", row["days_count"]),
        _fact("Reason", row["reason"]),
    ]
    if bal:
        total = float(bal["entitled_days"] or 0) + float(bal["carried_forward_days"] or 0)
        left = total - float(bal["used_days"] or 0)
        facts.append(_fact(f"{year} balance", f"{left:g} of {total:g} days left (before this request is deducted)"))
    emp = conn.execute("SELECT department FROM employees WHERE employee_id=? AND institution_id=?",
                       (row["employee_id"], inst_id)).fetchone()
    warnings = []
    if emp and emp["department"]:
        clash = conn.execute(
            """SELECT DISTINCT e.full_name, e.preferred_name FROM leave_applications la
               JOIN employees e ON e.employee_id=la.employee_id AND e.institution_id=la.institution_id
               WHERE la.institution_id=? AND la.status='Approved' AND la.employee_id != ?
                 AND e.department=? AND e.status='Active'
                 AND la.start_date <= ? AND la.end_date >= ?
               ORDER BY 1""",
            (inst_id, row["employee_id"], emp["department"], row["end_date"], row["start_date"])).fetchall()
        if clash:
            names = [c["preferred_name"] or c["full_name"] for c in clash]
            shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
            warnings.append(f"{len(names)} from {emp['department']} already away on those dates: {shown}.")
    return {"facts": facts, "warnings": warnings}


def _simple_facts(conn, inst_id: int, module: str, row) -> Dict[str, Any]:
    warnings: List[str] = []
    if module == "claims":
        plan = conn.execute("SELECT plan_name FROM benefit_plans WHERE id=? AND institution_id=?",
                            (row["benefit_plan_id"], inst_id)).fetchone()
        facts = [_fact("Plan", plan["plan_name"] if plan else None), _fact("Amount claimed", f"RM {row['amount_claimed']}"),
                 _fact("Claim date", row["claim_date"]), _fact("Description", row["description"])]
    elif module == "requisition":
        sal = f"RM {row['salary_min']} to RM {row['salary_max']}" if row["salary_min"] or row["salary_max"] else None
        facts = [_fact("Title", row["title"]), _fact("Department", row["department"]), _fact("Headcount", row["headcount"]),
                 _fact("Type", row["employment_type"]), _fact("Priority", row["priority"]), _fact("Salary range", sal),
                 _fact("Description", row["description"]), _fact("Requirements", row["requirements"])]
    elif module == "timesheet":
        proj = ""
        args = [inst_id, row["timesheet_id"] if module_is_project_row(module, row) else row["id"]]
        if module_is_project_row(module, row):
            proj = " AND project_id=?"
            args.append(row["project_id"])
        tot = conn.execute(f"SELECT COALESCE(SUM(hours),0) AS h FROM timesheet_entries WHERE institution_id=? AND timesheet_id=?{proj}",
                           args).fetchone()
        facts = [_fact("Week", f"{row['period_start']} to {row['period_end']}"), _fact("Hours", f"{float(tot['h']):g}"),
                 _fact("Notes", row["notes"])]
    elif module == "ld_enrollment":
        c = conn.execute("SELECT title, category, cost FROM ld_courses WHERE id=? AND institution_id=?",
                         (row["course_id"], inst_id)).fetchone()
        facts = [_fact("Course", c["title"] if c else None), _fact("Category", c["category"] if c else None),
                 _fact("Cost", f"RM {c['cost']}" if c and c["cost"] else None), _fact("Notes", row["notes"])]
    elif module == "overtime":
        facts = [_fact("Work date", row["work_date"]), _fact("Overtime", f"{row['overtime_hours']} h"),
                 _fact("Paid as", row["conversion_mode"])]
    elif module == "resignation":
        facts = [_fact("Last working day", row["last_working_day"]), _fact("Effective date", row["effective_date"]),
                 _fact("Reason", row["reason"]), _fact("Notes", row["notes"])]
        warnings.append("Approving starts offboarding for this employee.")
    elif module == "pip":
        facts = [_fact("Plan", row["name"]), _fact("Period", f"{row['period_start']} to {row['period_end']}"), _fact("Reason", row["reason"])]
    else:
        facts = []
    return {"facts": facts, "warnings": warnings}


@router.get("/api/approvals/{module}/{ref_id}/context")
@db_session
def approval_context(conn, module: str, ref_id: int, project_row: bool = Query(False),
                     user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    if module not in APPROVAL_MODULES:
        raise HTTPException(404, "Unknown request type")
    inst_id = need_inst(user)
    row = next((r for r in pending_rows_for_approver(conn, inst_id, user, module)
                if r["id"] == ref_id and module_is_project_row(module, r) == project_row), None)
    if not row:
        raise HTTPException(404, "This request is no longer waiting on you")
    employee_id = _requester_employee_id(conn, inst_id, module, row)
    detail = _leave_facts(conn, inst_id, row) if module == "leave" else _simple_facts(conn, inst_id, module, row)
    return {
        "module": module, "ref_id": ref_id, "type_label": MODULE_DISPLAY_NAME.get(module, module),
        "employee": _employee_card(conn, inst_id, employee_id),
        "facts": [f for f in detail["facts"] if f],
        "warnings": detail["warnings"],
        "steps": _steps(conn, inst_id, module, employee_id, row) if employee_id else [],
    }
