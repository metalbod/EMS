"""Integration tests for routers/dashboard.py (/api/todos).

Computed live from today's wall-clock date (not stored), so only the
current-week timesheet case is exercised here with a real "this week"
period_start — the ld_enrollments and manager-appraisal todo branches
are covered indirectly once ld.py/performance.py get their own test files.
"""
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from conftest import _valid_employee_payload
from routers.dashboard import _add_day_counts, _approval_row_detail, _first_col, _to_local_date, _todo_sort_key

KL = ZoneInfo("Asia/Kuala_Lumpur")


def _this_monday():
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def _fresh_institution_hr_manager_auth(client, superadmin_headers):
    """An hr_manager account scoped to a brand-new, throwaway institution —
    NOT the shared session-wide test_institution. The hr_manager approver
    type is role-based and institution-wide (any hr_manager-role account is
    eligible for any pending hr_manager-step item in their institution, not
    just their own subordinates' — see core/approval_workflow.py), so an
    "expect zero todos" assertion against the shared test_institution is
    only true when no *other* test file in the same run has left a pending
    hr_manager-step item behind there — which, across the full suite, isn't
    reliably true. A dedicated fresh institution sidesteps that entirely."""
    code = f"ZZDASHHR{os.urandom(4).hex()}".upper()
    username = f"zzdashhr_admin_{os.urandom(4).hex()}"
    password = "ZzPytest@123"
    create = client.post("/api/institutions", headers=superadmin_headers, json={
        "name": "ZZ Dashboard HR Institution",
        "code": code,
        "contact_email": "zzdashhr@example.com",
        "admin_username": username,
        "admin_full_name": "ZZ Dashboard HR Admin",
        "admin_password": password,
    })
    assert create.status_code == 201, create.text
    inst = create.json()
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": code,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return inst, headers


def test_get_todos_requires_auth(client):
    res = client.get("/api/todos")
    assert res.status_code in (401, 403)


def test_superadmin_gets_empty_todos(client, superadmin_headers):
    res = client.get("/api/todos", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_hr_manager_with_no_employee_record_gets_empty_todos(client, superadmin_headers):
    # A fresh, dedicated institution — not the shared test_institution — so
    # this genuinely starts with zero pending items regardless of what any
    # other test file in this run has left behind there (see
    # _fresh_institution_hr_manager_auth's docstring).
    _, hr_headers = _fresh_institution_hr_manager_auth(client, superadmin_headers)
    res = client.get("/api/todos", headers=hr_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_employee_with_draft_timesheet_this_week_gets_todo(
    client, hr_manager_auth, test_institution, make_test_employee
):
    emp = make_test_employee()
    username = f"zztdash_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Dashboard Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    monday = _this_monday()
    sunday = (datetime.fromisoformat(monday).date() + timedelta(days=6)).isoformat()
    ts = client.post("/api/timesheets", headers=emp_headers,
                      json={"employee_id": emp["employee_id"], "period_start": monday, "period_end": sunday})
    assert ts.status_code == 201, ts.text

    res = client.get("/api/todos", headers=emp_headers)
    assert res.status_code == 200
    todos = res.json()
    assert any(t["key"] == "timesheet-my" for t in todos)

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_pending_leave_approval_appears_as_one_per_item_todo(
    client, hr_manager_auth, test_institution, make_test_employee, make_test_leave_type
):
    """A pending approval-workflow request (Leave here, but the same
    _approval_row_detail branch structure in routers/dashboard.py covers
    Claims/Requisition/Timesheet/L&D Enrollment/Overtime/Resignation/PIP
    too) shows up as one real row — employee, stage, due date — not
    folded into an aggregate "N items awaiting approval" count. Regression
    coverage for the Phase 2 rollout (see docs/VISUAL_REDESIGN_ROLLOUT_PLAN.md):
    count_pending_for_approver's count-only query became
    pending_rows_for_approver, and the dashboard renders one To-Do per row."""
    emp = make_test_employee()
    username = f"zzdashleave_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Dashboard Leave Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    lt = make_test_leave_type(requires_approval=True, annual_entitlement=14)
    app = client.post("/api/leave/applications", headers=emp_headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"],
        "start_date": "2027-04-05", "end_date": "2027-04-06",
    })
    assert app.status_code == 201, app.text
    assert app.json()["status"] == "Pending Approval"
    app_id = app.json()["id"]

    # This employee has no manager set, so the default workflow's
    # direct_manager step resolves to nothing and it's immediately at the
    # hr_manager step — hr_manager_auth (no linked employee_id) is exactly
    # the "approving someone else's request" case this feature is for.
    todos = client.get("/api/todos", headers=hr_manager_auth).json()
    key = f"leave-approval-{app_id}"
    match = next((t for t in todos if t["key"] == key), None)
    assert match, f"expected a per-item leave-approval todo, got: {todos}"
    assert match["page"] == "leave-approvals"
    assert match["count"] == 1
    assert match["employee_name"] == emp["full_name"]
    assert match["stage_type"] == "Leave"
    assert match["due_date"] == "2027-04-05"
    # New contract: kind/ref_id for the UI, and a real waiting time computed
    # server-side (submitted just now, and 2027 leave isn't overdue).
    assert match["kind"] == "approval"
    assert match["module"] == "leave"  # lets Home offer inline Approve/Reject for this kind of request
    assert match["ref_id"] == app_id
    assert match["focus_id"] == app_id  # the id the Leave Approvals page opens
    assert match["event_date"] == "2027-04-05"
    assert match["waiting_since"] and match["days_waiting"] == 0
    assert match["days_overdue"] is None
    # Approvals sort ahead of every task/reminder.
    kinds = [t["kind"] for t in todos]
    assert kinds == sorted(kinds, key=lambda k: {"approval": 0, "task": 1, "reminder": 2}[k])
    assert lt["name"] in match["stage"]
    assert emp["full_name"] in match["label"]
    assert "awaiting your approval" in match["label"]

    # The Leave Approvals page deep-links with ?id= — exactly that application,
    # regardless of status filters, and nothing for an id that doesn't exist.
    one = client.get(f"/api/leave/applications?id={app_id}&limit=10", headers=hr_manager_auth)
    assert one.status_code == 200
    assert [a["id"] for a in one.json()] == [app_id]
    assert one.headers["X-Total-Count"] == "1"
    assert client.get("/api/leave/applications?id=2147483000&limit=10", headers=hr_manager_auth).json() == []

    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_onboarding_checklist_items_appear_for_assigned_role(client, superadmin_headers):
    """A checklist item's assigned_role determines whose To-Do it shows up
    in — the new hire sees their own 'employee'-assigned items, HR sees
    the institution's 'hr_manager'-assigned items — one row per pending
    item (not an aggregate count), each labeled with the item's title so
    the To-Do card shows what the task actually is. See
    routers/dashboard.py's ob_q, which mirrors list_ob_checklists'
    (routers/onboarding.py) existing my_pending scoping.

    Uses a fresh, dedicated institution (not the shared test_institution) —
    this test doubles as the regression check for a real bug found while
    debugging it: routers/onboarding.py's start_checklist queried
    `template_set_id=?` with a bound None whenever an institution had no
    ob_template_sets row yet (only ever used the legacy templates from
    seed_ob_templates, which leave template_set_id NULL) — `x = NULL` is
    never true in SQL even when x genuinely IS NULL, so every such
    institution silently got zero checklist items on every
    POST /api/ob/checklists call. Never surfaced against the shared
    test_institution because an earlier feature (custom template sets) had
    already given it a real ob_template_sets row, masking the bug — a fresh
    institution has no such row, so it reproduces the original bug
    reliably. Now fixed with an explicit `IS NULL` branch."""
    inst, hr_headers = _fresh_institution_hr_manager_auth(client, superadmin_headers)
    inst_code = inst["code"]

    emp_res = client.post("/api/employees", headers=hr_headers,
                           json=_valid_employee_payload(full_name="ZZ Dashboard OB Employee"))
    assert emp_res.status_code == 201, emp_res.text
    emp = emp_res.json()

    username = f"zztdashob_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_headers, json={
        "username": username, "full_name": "ZZ Dashboard OB Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": inst_code,
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    started = client.post("/api/ob/checklists", headers=hr_headers,
                           json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert started.status_code == 201, started.text
    cl_id = started.json()["id"]
    item_ids = {i["id"] for i in client.get(f"/api/ob/checklists/{cl_id}", headers=hr_headers).json()["items"]}

    # The new hire sees their own 'employee'-assigned items (e.g. "Welcome
    # Acknowledgement" in the seeded default templates) as individual rows,
    # not their own name (that'd be redundant for their own to-do).
    emp_todos = client.get("/api/todos", headers=emp_headers).json()
    emp_ob_todos = [t for t in emp_todos if t["key"].startswith("ob-item-") and int(t["key"].removeprefix("ob-item-")) in item_ids]
    assert emp_ob_todos, f"expected at least one ob-item todo, got: {emp_todos}"
    assert all(t["page"] == "onboarding" and t["count"] == 1 for t in emp_ob_todos)
    assert any("Welcome Acknowledgement" in t["label"] for t in emp_ob_todos)
    assert not any(emp["full_name"] in t["label"] for t in emp_ob_todos)
    # Checklist grouping fields: one checklist, progress counts consistent
    # with the full item list, ref_id = the item, kind = "task".
    assert all(t["kind"] == "task" and t["checklist_id"] == cl_id and t["employee_id"] == emp["employee_id"]
               for t in emp_ob_todos)
    assert all(t["ref_id"] in item_ids for t in emp_ob_todos)
    assert all(t["focus_id"] == cl_id for t in emp_ob_todos)  # a task is opened by opening its checklist
    assert all(t["checklist_total"] == len(item_ids) and 1 <= t["checklist_open"] <= t["checklist_total"]
               for t in emp_ob_todos)
    # Onboarding has no "leaves on" context (that's offboarding-only).
    assert all(t["event_date"] is None for t in emp_ob_todos)

    # HR sees their own 'hr_admin'/'hr_manager'-assigned items across the
    # institution (not the employee's), each labeled with the employee's
    # name since it's someone else's checklist.
    hr_todos = client.get("/api/todos", headers=hr_headers).json()
    hr_ob_todos = [t for t in hr_todos if t["key"].startswith("ob-item-") and int(t["key"].removeprefix("ob-item-")) in item_ids]
    assert hr_ob_todos
    assert all(emp["full_name"] in t["label"] for t in hr_ob_todos)


def test_dashboard_todo_resignation_has_no_fake_deadline(client, employee_with_login, hr_manager_auth):
    """A pending resignation has no deadline of its own — `effective_date`
    used to be shown as "due", which coloured it red as soon as the
    (often back-dated) effective date passed. Now due_date is None, the
    last working day is informational `event_date`, and the wait is shown
    as days_waiting from submission."""
    emp, headers = employee_with_login(full_name="ZZ Resign Dates")
    submit = client.post("/api/resignations", headers=headers, json={
        "reason": "Date semantics", "effective_date": "2020-01-01", "last_working_day": "2027-06-30",
    })
    assert submit.status_code == 201, submit.text
    req_id = submit.json()["id"]

    todos = client.get("/api/todos", headers=hr_manager_auth).json()
    match = next(t for t in todos if t["key"] == f"resignation-approval-{req_id}")
    assert match["kind"] == "approval" and match["ref_id"] == req_id and match["focus_id"] == req_id
    assert match["due_date"] is None and match["days_overdue"] is None
    assert match["event_date"] == "2027-06-30"
    assert match["days_waiting"] == 0 and match["waiting_since"]

    client.patch(f"/api/resignations/{req_id}", headers=hr_manager_auth, json={"status": "Rejected"})


def test_reminder_rows_share_the_same_shape(client, hr_manager_auth):
    """Aggregate rows (no single employee/request) still carry every new
    field, as None, so the UI can read them uniformly."""
    for t in client.get("/api/todos", headers=hr_manager_auth).json():
        for field in ("kind", "ref_id", "employee_id", "due_date", "waiting_since", "event_date",
                      "days_waiting", "days_overdue", "days_until_event", "checklist_id", "checklist_open", "checklist_total", "action_label", "focus_id", "module"):
            assert field in t, f"{t['key']} is missing {field}"
        if t["kind"] == "reminder":
            assert t["ref_id"] is None and t["due_date"] is None and t["days_overdue"] is None


def test_to_local_date_converts_utc_timestamps_but_not_plain_dates():
    # 17:30 UTC on 27 Sep is already 01:30 on 28 Sep in Malaysia (UTC+8).
    assert _to_local_date("2026-09-27 17:30:00", KL) == date(2026, 9, 28)
    assert _to_local_date("2026-09-27 15:59:00", KL) == date(2026, 9, 27)
    # A bare date is a calendar date already — never shifted.
    assert _to_local_date("2026-09-27", KL) == date(2026, 9, 27)
    assert _to_local_date(None, KL) is None
    assert _to_local_date("not a date", KL) is None


def test_add_day_counts_waiting_and_overdue():
    today = date(2026, 9, 28)
    t = {"waiting_since": "2026-09-11 02:00:00", "due_date": "2026-09-25"}
    _add_day_counts(t, today, KL)
    assert t["waiting_since"] == "2026-09-11"
    assert t["days_waiting"] == 17
    assert t["days_overdue"] == 3
    assert t["days_until_event"] is None  # no event_date on this item

    # event_date is signed: future is positive, today 0, past negative.
    for ev, expected in (("2026-10-12", 14), ("2026-09-28", 0), ("2026-09-25", -3), (None, None)):
        t = {"waiting_since": None, "due_date": None, "event_date": ev}
        _add_day_counts(t, today, KL)
        assert t["days_until_event"] == expected

    # Due today is not overdue; a future or missing due date never is; a
    # missing waiting_since gives no wait at all (not 0).
    for due in ("2026-09-28", "2026-10-01", None):
        t = {"waiting_since": None, "due_date": due}
        _add_day_counts(t, today, KL)
        assert t["days_overdue"] is None and t["days_waiting"] is None and t["waiting_since"] is None


def test_todo_sort_key_orders_approvals_then_tasks_then_reminders():
    items = [
        {"key": "rem", "kind": "reminder", "waiting_since": None, "due_date": None, "days_overdue": None},
        {"key": "task-undated", "kind": "task", "waiting_since": None, "due_date": None, "days_overdue": None},
        {"key": "task-late", "kind": "task", "waiting_since": None, "due_date": "2026-09-01", "days_overdue": 27},
        {"key": "appr-new", "kind": "approval", "waiting_since": "2026-09-20", "due_date": None, "days_overdue": None},
        {"key": "appr-old", "kind": "approval", "waiting_since": "2026-09-01", "due_date": None, "days_overdue": None},
    ]
    assert [t["key"] for t in sorted(items, key=_todo_sort_key)] == [
        "appr-old", "appr-new", "task-late", "task-undated", "rem",
    ]


def test_todo_sort_key_puts_overdue_approvals_first_most_overdue_first():
    """An approval past a real deadline (a leave request that has already
    started) outranks an older approval with no deadline, and among overdue
    ones the most overdue leads; the rest stay longest-waiting first."""
    def appr(key, waiting, overdue=None):
        return {"key": key, "kind": "approval", "waiting_since": waiting, "due_date": None, "days_overdue": overdue}

    items = [
        appr("resignation-17d", "2026-09-11"),
        appr("leave-overdue-3", "2026-09-20", overdue=3),
        appr("claim-3d", "2026-09-25"),
        appr("leave-overdue-9", "2026-09-22", overdue=9),
    ]
    assert [t["key"] for t in sorted(items, key=_todo_sort_key)] == [
        "leave-overdue-9", "leave-overdue-3", "resignation-17d", "claim-3d",
    ]


def test_first_col_skips_missing_and_null_columns():
    class FakeRow(dict):
        pass

    # timesheet_project_approvals rows have no submitted_at at all.
    assert _first_col(FakeRow(created_at="2026-09-01 00:00:00"), "submitted_at", "created_at") == "2026-09-01 00:00:00"
    assert _first_col(FakeRow(submitted_at=None, created_at="x"), "submitted_at", "created_at") == "x"
    assert _first_col(FakeRow(), "submitted_at", "created_at") is None


class _Row(dict):
    """Stand-in for db.Row: subscriptable by column name, with keys()."""


def _detail(module, row, **lookups):
    base = {"leave_types": {}, "benefit_plans": {}, "ld_courses": {}, "requisition_creator_emp": {}, "overtime_timesheet": {}}
    base.update(lookups)
    return _approval_row_detail(_Row(row), module, base)


def test_focus_id_is_the_record_the_destination_page_opens():
    """Most modules open the request itself; the timesheet page also decides
    overtime, and a per-project split row is a child of its timesheet."""
    plain = {"id": 7, "employee_id": "E1", "created_at": "2026-09-01 00:00:00"}
    assert _detail("leave", {**plain, "leave_type_id": 1, "start_date": "2026-10-01", "end_date": "2026-10-02"})["focus_id"] == 7
    assert _detail("claims", {**plain, "benefit_plan_id": 1, "amount_claimed": 5, "claim_date": "2026-09-01"})["focus_id"] == 7
    assert _detail("requisition", {**plain, "created_by": "u", "title": "T", "department": "D"})["focus_id"] == 7
    assert _detail("ld_enrollment", {**plain, "course_id": 1})["focus_id"] == 7
    assert _detail("resignation", {**plain, "last_working_day": "2026-12-10", "effective_date": "2026-09-01"})["focus_id"] == 7
    assert _detail("pip", {**plain, "name": "PIP"})["focus_id"] == 7


def test_focus_id_for_timesheet_and_overtime_split_rows_is_the_parent_timesheet():
    # legacy timesheet row: its own id
    legacy_ts = {"id": 40, "employee_id": "E1", "period_start": "2026-09-21", "created_at": "2026-09-27 01:00:00"}
    assert _detail("timesheet", legacy_ts)["focus_id"] == 40
    # per-project split row: id is the child; timesheet_id is the parent
    split_ts = {"id": 901, "timesheet_id": 40, "employee_id": "E1", "period_start": "2026-09-21", "created_at": "2026-09-27 01:00:00"}
    assert _detail("timesheet", split_ts)["focus_id"] == 40

    # legacy overtime record carries timesheet_id itself
    legacy_ot = {"id": 5, "timesheet_id": 40, "employee_id": "E1", "overtime_hours": 2, "work_date": "2026-09-22", "created_at": "2026-09-27 01:00:00"}
    assert _detail("overtime", legacy_ot)["focus_id"] == 40
    # split overtime row only knows its record — resolved through the batched lookup
    split_ot = {"id": 88, "overtime_record_id": 5, "employee_id": "E1", "overtime_hours": 1, "work_date": "2026-09-22", "created_at": "2026-09-27 01:00:00"}
    assert _detail("overtime", split_ot, overtime_timesheet={5: 40})["focus_id"] == 40
    # a record the lookup can't resolve degrades to None (the UI then just opens the page)
    assert _detail("overtime", split_ot)["focus_id"] is None
