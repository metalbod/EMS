"""
Dashboard To-Do List — personal items (about the logged-in user's own
data), plus items pending this user's own decision as an approval-workflow
approver (see core/approval_workflow.py) — the latter already had one
precedent before this module existed (the ManagerReview appraisal item
below), so this isn't a new exception to the "personal only" rule so much
as generalizing the one that was already there.
Computed on every request from live state (not stored), so items disappear
automatically once actioned. Excluded for superadmin (no personal employee record).

Every item carries a `kind` ("approval" | "task" | "reminder") plus three
deliberately separate date concepts, so the UI never has to guess what a
date means: `due_date` is only ever a real deadline (an approval that has
no deadline of its own, e.g. a resignation, has none), `waiting_since` is
when a pending approval request was submitted (a proxy for time-in-queue —
the schema has no timestamp for when a request reached *this* approver's
step), and `event_date` is purely informational context (a last working
day, a leave start). `days_waiting`/`days_overdue` are computed here
against the institution's own timezone, not by the browser in UTC.

`ref_id` is this row's own id (for a per-project timesheet/overtime split it
is the child project-approval row); `focus_id` is the id the destination page
actually opens — the parent timesheet for a split timesheet or overtime row,
the checklist for a checklist task, otherwise the same as `ref_id`. The
Home to-do links with `showPage(page, {focus: focus_id})`.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from core.deps import get_current_user, need_inst

from core.org_queries import subordinates_in_clause

from core.approval_workflow import pending_rows_for_approver

from routers.employee_documents import STATUS_CASE_SQL

from db import get_db

from core.db_session import db_session

router = APIRouter()


def _batch_lookup(conn, table: str, key_col: str, value_col: str, ids, inst_id: int = None) -> Dict[Any, Any]:
    """Resolves many {key_col: value_col} pairs in one query instead of one
    query per id — the batched-IN-query pattern the onboarding/offboarding
    block further down this file already uses, now also applied to the
    approval-queue lookups above it. Returns {} without querying at all
    when ids is empty (a module with no pending rows costs nothing here)."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    q = f"SELECT {key_col}, {value_col} FROM {table} WHERE {key_col} IN ({placeholders})"
    params = list(ids)
    if inst_id is not None:
        q += " AND institution_id=?"
        params.append(inst_id)
    rows = conn.execute(q, params).fetchall()
    return {r[key_col]: r[value_col] for r in rows}


def _institution_tz(conn, inst_id: int) -> ZoneInfo:
    """The institution's own `timezone` column, falling back to UTC on a
    missing/invalid value (same fallback core/tasks.py's reminder sweeps use)."""
    row = conn.execute("SELECT timezone FROM institutions WHERE id=?", (inst_id,)).fetchone()
    try:
        return ZoneInfo((row["timezone"] if row else None) or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _to_local_date(value, tz: ZoneInfo) -> Optional[date]:
    """A date column ('YYYY-MM-DD') passes through as-is; a timestamp column
    ('YYYY-MM-DD HH:MM:SS', stored in UTC — see the created_at defaults) is
    converted to the institution's local calendar date first, so a request
    submitted at 23:30 UTC counts as the next day in Malaysia."""
    if not value:
        return None
    s = str(value)
    try:
        if len(s) > 10:
            return datetime.fromisoformat(s.replace("T", " ")[:19]).replace(tzinfo=timezone.utc).astimezone(tz).date()
        return date.fromisoformat(s)
    except ValueError:
        return None


def _first_col(row, *names):
    """First of `names` that exists on `row` and is non-null — the per-project
    timesheet/overtime child tables don't carry every column their parent
    table does (e.g. timesheet_project_approvals has no submitted_at)."""
    cols = row.keys()
    for n in names:
        if n in cols and row[n] is not None:
            return row[n]
    return None


def _add_day_counts(todo: Dict[str, Any], today: date, tz: ZoneInfo) -> None:
    """Normalizes waiting_since to a local date and adds days_waiting
    (approvals: how long since submission), days_overdue (only when a
    real due_date is in the past; None otherwise — never 0 or negative)
    and days_until_event."""
    waiting = _to_local_date(todo.get("waiting_since"), tz)
    todo["waiting_since"] = waiting.isoformat() if waiting else None
    todo["days_waiting"] = max((today - waiting).days, 0) if waiting else None
    due = _to_local_date(todo.get("due_date"), tz)
    todo["days_overdue"] = (today - due).days if due and due < today else None
    # Days until the informational event_date (an offboarding employee's last
    # working day, a leave start): negative once it has passed, None if none.
    event = _to_local_date(todo.get("event_date"), tz)
    todo["days_until_event"] = (event - today).days if event else None


_KIND_ORDER = {"approval": 0, "task": 1, "reminder": 2}


def _todo_sort_key(t: Dict[str, Any]):
    """Approvals first, then checklist tasks, then aggregate reminders.
    Within approvals: anything past a real deadline first (most overdue
    first — e.g. a leave request that has already started), then everything
    else longest-waiting first. Within tasks: earliest deadline first, which
    is also most-overdue first, undated last. sort() is stable, so ties keep
    their query order (employee, then checklist item order)."""
    kind = _KIND_ORDER[t["kind"]]
    if kind == 0:
        return (0, -(t["days_overdue"] or 0), t["waiting_since"] is None, t["waiting_since"] or "")
    if kind == 1:
        return (1, t["due_date"] is None, t["due_date"] or "")
    return (2, False, "")


def _approval_row_detail(row, module: str, lookups: Dict[str, Dict]) -> Dict[str, Any]:
    """Resolve the (employee, stage label, stage type, dates) shown on
    one per-item To-Do row for a pending approval-workflow request —
    mirrors the shape the onboarding/offboarding checklist items below
    already use, rather than the aggregate "N items" count this replaced.
    One branch per module in MODULE_TABLE (core/approval_workflow.py);
    each row's own columns differ enough (a leave application isn't shaped
    like a benefit claim) that a generic renderer would just be a wall of
    "if this column exists" checks — see docs/adr/0001 on why this
    codebase doesn't force genuinely different row shapes through one
    renderer.

    Takes pre-fetched `lookups` (see _batch_lookup calls in get_todos)
    instead of querying inline — this used to run its own query per row
    per module (leave_types/benefit_plans/users/ld_courses), which meant
    a user with 20-30 pending items triggered 20-30+ individual round
    trips just for this step, on the page that loads on every login.

    Dates: `due_date` is only set where the approver has a real deadline
    (a leave request should be decided before it starts); `waiting_since`
    is the raw submission timestamp/date (normalized to a local date in
    get_todos); `event_date` is display-only context."""
    if module == "leave":
        name = lookups["leave_types"].get(row["leave_type_id"], "Leave")
        return {
            "focus_id": row["id"],
            "employee_id": row["employee_id"],
            "stage": f"{name}: {row['start_date']} to {row['end_date']}",
            "stage_type": "Leave", "due_date": row["start_date"],
            "waiting_since": row["created_at"], "event_date": row["start_date"],
        }
    if module == "claims":
        name = lookups["benefit_plans"].get(row["benefit_plan_id"], "Benefit")
        return {
            "focus_id": row["id"],
            "employee_id": row["employee_id"],
            "stage": f"{name} claim — RM {row['amount_claimed']}",
            "stage_type": "Benefit Claim", "due_date": None,
            "waiting_since": _first_col(row, "created_at", "claim_date"), "event_date": None,
        }
    if module == "requisition":
        return {
            "focus_id": row["id"],
            "employee_id": lookups["requisition_creator_emp"].get(row["created_by"]),
            "stage": f"{row['title']} ({row['department']})",
            "stage_type": "Job Requisition", "due_date": None,
            "waiting_since": row["created_at"], "event_date": None,
        }
    if module == "timesheet":
        return {
            # a per-project split row carries its parent timesheet's id
            "focus_id": row["timesheet_id"] if "timesheet_id" in row.keys() else row["id"],
            "employee_id": row["employee_id"],
            "stage": f"Week of {row['period_start']}",
            "stage_type": "Timesheet", "due_date": None,
            "waiting_since": _first_col(row, "submitted_at", "created_at"), "event_date": row["period_start"],
        }
    if module == "ld_enrollment":
        title = lookups["ld_courses"].get(row["course_id"], "Training course")
        return {
            "focus_id": row["id"],
            "employee_id": row["employee_id"],
            "stage": title,
            "stage_type": "Training Enrollment", "due_date": None,
            "waiting_since": row["created_at"], "event_date": None,
        }
    if module == "overtime":
        # Overtime is decided from its timesheet's detail. A legacy record has
        # timesheet_id itself; a per-project split row only has the record id.
        if "timesheet_id" in row.keys():
            focus_id = row["timesheet_id"]
        else:
            focus_id = lookups["overtime_timesheet"].get(row["overtime_record_id"])
        return {
            "focus_id": focus_id,
            "employee_id": row["employee_id"],
            "stage": f"{row['overtime_hours']}h overtime on {row['work_date']}",
            "stage_type": "Overtime", "due_date": None,
            "waiting_since": row["created_at"], "event_date": row["work_date"],
        }
    if module == "resignation":
        return {
            "focus_id": row["id"],
            "employee_id": row["employee_id"],
            "stage": f"Resignation — last day {row['last_working_day']}",
            "stage_type": "Resignation", "due_date": None,
            "waiting_since": row["created_at"], "event_date": row["last_working_day"],
        }
    # pip: performance_cycles row (cycle_type='pip'), see MODULE_TABLE.
    return {
        "focus_id": row["id"],
        "employee_id": row["employee_id"],
        "stage": row["name"],
        "stage_type": "PIP", "due_date": None,
        "waiting_since": row["created_at"], "event_date": None,
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
    # Institution-local calendar date, not UTC — in Malaysia (UTC+8) the two
    # disagree between 00:00 and 08:00, which used to make "this week's
    # timesheet" resolve to last week on early Monday mornings.
    tz = _institution_tz(conn, inst_id)
    today = datetime.now(tz).date()

    if emp_id:
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
    # One pending_rows_for_approver query per module first (8 total,
    # unavoidable — each module's own table/eligibility shape differs),
    # then every per-row lookup _approval_row_detail used to make
    # individually is batched into one IN-query per lookup type below —
    # same pattern the onboarding/offboarding block further down already
    # uses. A user with 20-30 pending items across these modules used to
    # cost 20-30+ extra round trips just for this step; now it's a fixed
    # handful regardless of how many items there are.
    module_rows = {module: pending_rows_for_approver(conn, inst_id, user, module) for module, _, _ in approval_targets}
    lookups = {
        "leave_types": _batch_lookup(conn, "leave_types", "id", "name",
                                      {r["leave_type_id"] for r in module_rows["leave"]}),
        "benefit_plans": _batch_lookup(conn, "benefit_plans", "id", "plan_name",
                                        {r["benefit_plan_id"] for r in module_rows["claims"]}),
        "ld_courses": _batch_lookup(conn, "ld_courses", "id", "title",
                                     {r["course_id"] for r in module_rows["ld_enrollment"]}),
        "requisition_creator_emp": _batch_lookup(conn, "users", "username", "employee_id",
                                                   {r["created_by"] for r in module_rows["requisition"]}, inst_id=inst_id),
        "overtime_timesheet": _batch_lookup(conn, "overtime_records", "id", "timesheet_id",
                                              {r["overtime_record_id"] for r in module_rows["overtime"]
                                               if "overtime_record_id" in r.keys()}, inst_id=inst_id),
    }
    approval_details = [
        (module, page, noun, row, _approval_row_detail(row, module, lookups))
        for module, page, noun in approval_targets
        for row in module_rows[module]
    ]
    employee_names = _batch_lookup(conn, "employees", "employee_id", "full_name",
                                    {d["employee_id"] for _, _, _, _, d in approval_details}, inst_id=inst_id)
    for module, page, noun, row, detail in approval_details:
        employee_name = employee_names.get(detail["employee_id"], "Unknown")
        todos.append({
            "key": f"{module}-approval-{row['id']}",
            "label": f"{detail['stage']} — {employee_name} ({noun.lower()}, awaiting your approval)",
            "page": page, "count": 1,
            # Same extra keys the onboarding items below add, for the
            # Home page To-Do queue's per-item rendering.
            "employee_name": employee_name, "stage": detail["stage"],
            "stage_type": detail["stage_type"], "due_date": detail["due_date"],
            # `module` lets the UI decide which requests can be approved/rejected
            # straight from Home (see static/js/todo-decisions.js).
            "kind": "approval", "module": module, "ref_id": row["id"], "focus_id": detail["focus_id"],
            "employee_id": detail["employee_id"],
            "waiting_since": detail["waiting_since"], "event_date": detail["event_date"],
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
                # There is no standalone documents list — expiries only surface
                # on the Leave tab's calendar — so say where the button goes.
                "action_label": "View calendar",
            })

    # Onboarding/Offboarding checklist items assigned to this user's role —
    # same "my_pending" scoping list_ob_checklists (routers/onboarding.py)
    # already uses per-checklist, one row per pending item here so the
    # To-Do card shows what the task actually is (title), not just a
    # count. An employee only sees their own checklist's items, a manager
    # only their subordinates', HR sees institution-wide — matching that
    # endpoint's existing role scoping exactly.
    ob_q = """
        SELECT i.id, i.title, i.due_date, c.id AS checklist_id, c.type, c.employee_id,
               e.full_name AS employee_name, e.last_working_day
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
    # Per-checklist progress ("2 of 5 left") in one grouped query — counts
    # every item on the checklist, not just those assigned to this role, so
    # the number reflects how far along the whole checklist is.
    ob_progress = {}
    checklist_ids = sorted({r["checklist_id"] for r in ob_rows})
    if checklist_ids:
        placeholders = ",".join("?" * len(checklist_ids))
        for pr in conn.execute(
            f"SELECT checklist_id, COUNT(*) AS total, "
            f"SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) AS open_items "
            f"FROM ob_checklist_items WHERE checklist_id IN ({placeholders}) GROUP BY checklist_id",
            checklist_ids
        ).fetchall():
            ob_progress[pr["checklist_id"]] = (int(pr["open_items"] or 0), int(pr["total"]))
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
            # A task is opened by opening its checklist.
            "kind": "task", "ref_id": r["id"], "focus_id": r["checklist_id"], "employee_id": r["employee_id"],
            "checklist_id": r["checklist_id"],
            "checklist_open": ob_progress.get(r["checklist_id"], (None, None))[0],
            "checklist_total": ob_progress.get(r["checklist_id"], (None, None))[1],
            # An offboarding checklist's own context: when this person leaves.
            "event_date": r["last_working_day"] if r["type"] == "offboarding" else None,
        })

    # Every item gets the same shape: the aggregate reminder rows (timesheet
    # draft, training in progress, appraisals, expiring documents) have no
    # single employee/request/date, so their new fields are just None.
    for t in todos:
        t.setdefault("kind", "reminder")
        for field in ("module", "ref_id", "focus_id", "employee_id", "due_date", "waiting_since", "event_date",
                      "checklist_id", "checklist_open", "checklist_total", "action_label"):
            t.setdefault(field, None)
        _add_day_counts(t, today, tz)
    todos.sort(key=_todo_sort_key)
    return todos
