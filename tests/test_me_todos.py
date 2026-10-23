"""Claude self-service To-Do list: routers/me_todos.py. The same list as the Home widget, read-only, in overdue / today / waiting buckets,
with resignation and PIP approvals and offboarding tasks reported as COUNTS ONLY (never named)."""
import pytest

from routers import me_todos


@pytest.fixture
def hr_with_employee(client, hr_manager_auth, make_test_employee, test_institution):
    """An HR Manager login that is linked to an employee record (the Claude endpoints need one), so they can be an approver."""
    emp = make_test_employee(full_name="ZZ Todo HR")
    uname = f"zztodohr_{emp['employee_id'].lower()}"
    created = client.post("/api/users", headers=hr_manager_auth, json={"username": uname, "full_name": emp["full_name"], "password": "ZzPytest@123",
                                                                       "role": "hr_manager", "employee_id": emp["employee_id"]})
    assert created.status_code == 201, created.text
    login = client.post("/api/auth/login", json={"username": uname, "password": "ZzPytest@123", "institution_code": test_institution["code"]})
    assert login.status_code == 200, login.text
    yield {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.delete(f"/api/users/{created.json()['id']}", headers=hr_manager_auth)


def row(**kw):
    base = {"key": "x", "label": "Something", "kind": "reminder", "count": 1, "employee_name": None, "due_date": None, "days_overdue": None,
            "days_waiting": None, "event_date": None, "days_until_event": None, "module": None, "stage_type": None}
    base.update(kw)
    return base


def test_the_approval_row_detail_gives_claude_dates_not_the_leave_type_or_the_claim_plan():
    from routers.dashboard import _approval_row_detail
    leave = {"id": 1, "employee_id": "E1", "leave_type_id": 7, "start_date": "2027-04-19", "end_date": "2027-04-20", "created_at": "2027-04-01 00:00:00"}
    d = _approval_row_detail(leave, "leave", {"leave_types": {7: "Secret Medical Leave"}})
    assert d["safe_detail"] == "2027-04-19 to 2027-04-20" and "Secret Medical" in d["stage"] and "Secret Medical" not in d["safe_detail"]
    claim = {"id": 2, "employee_id": "E1", "benefit_plan_id": 3, "amount_claimed": 1234.5, "created_at": "2027-04-01 00:00:00"}
    c = _approval_row_detail(claim, "claims", {"benefit_plans": {3: "Dental Plan"}})
    assert c["safe_detail"] is None and "Dental" in c["stage"]                     # the web widget keeps its full wording


def test_claude_titles_use_the_safe_wording_not_the_widgets_label():
    leave_row = row(kind="approval", module="leave", key="leave-approval-1", employee_name="Amy Tan",
                    label="Secret Medical Leave: 2027-04-19 to 2027-04-20 — Amy Tan (leave, awaiting your approval)", safe_detail="2027-04-19 to 2027-04-20")
    assert me_todos._title(leave_row, "Leave approval") == "Leave approval: Amy Tan (2027-04-19 to 2027-04-20)"
    claim_row = row(kind="approval", module="claims", key="claims-approval-2", employee_name="Bob Lee",
                    label="Dental Plan claim — RM 1234.5 — Bob Lee (benefit claim, awaiting your approval)", safe_detail=None)
    assert me_todos._title(claim_row, "Benefit claim approval") == "Benefit claim approval: Bob Lee"
    assert me_todos._title(row(key="timesheet-my", label="Your timesheet is a draft"), "Timesheet draft") == "Your timesheet is a draft"


def test_classify_names_every_category_and_flags_only_the_sensitive_ones():
    c = me_todos.classify
    assert c(row(kind="approval", module="leave")) == ("Leave approval", False)
    assert c(row(kind="approval", module="claims")) == ("Benefit claim approval", False)
    assert c(row(kind="approval", module="overtime")) == ("Overtime approval", False)
    assert c(row(kind="approval", module="resignation")) == ("Resignation approvals", True)
    assert c(row(kind="approval", module="pip")) == ("PIP approvals", True)
    assert c(row(kind="task", key="ob-item-4", stage_type="Onboarding")) == ("Onboarding task", False)
    assert c(row(kind="task", key="ob-item-5", stage_type="Offboarding")) == ("Offboarding checklist tasks", True)
    assert c(row(key="interview-9")) == ("Interview", False)
    assert c(row(key="timesheet-my")) == ("Timesheet draft", False)
    assert c(row(key="perf-team")) == ("Appraisal review", False)
    assert c(row(key="something-new")) == ("Other", False)


def test_buckets_counts_and_the_sensitive_rows_never_listed(client, hr_with_employee, monkeypatch):
    rows = [
        row(kind="approval", module="leave", key="leave-approval-1", label="Secret Type: 2026-01-01 to 2026-01-01 — Amy Tan (leave, awaiting your approval)", safe_detail="2026-01-01 to 2026-01-01", employee_name="Amy Tan", days_overdue=3, due_date="2026-01-01", days_waiting=5),
        row(key="interview-2", label="Interview Zed — today", event_date="PLACEHOLDER"),
        row(key="timesheet-my", label="Your timesheet for this week hasn't been submitted yet"),
        row(kind="approval", module="resignation", key="resignation-approval-7", label="x — Secret Person (resignation)", employee_name="Secret Person"),
        row(kind="approval", module="pip", key="pip-approval-8", employee_name="Pip Person"),
        row(kind="task", key="ob-item-9", stage_type="Offboarding", employee_name="Leaver Person", label="Return laptop — Leaver Person (Offboarding)"),
        row(key="ld-trainings", label="3 training courses in progress", count=3),
    ]
    today = client.get("/api/me/todos", headers=hr_with_employee).json()["date"]
    rows[1]["event_date"] = today
    monkeypatch.setattr(me_todos, "build_todos", lambda conn, user: rows)
    res = client.get("/api/me/todos", headers=hr_with_employee)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [i["person"] for i in body["overdue"]] == ["Amy Tan"] and body["overdue"][0]["days_overdue"] == 3
    assert body["overdue"][0]["title"] == "Leave approval: Amy Tan (2026-01-01 to 2026-01-01)" and "Secret Type" not in res.text
    assert [i["category"] for i in body["today"]] == ["Interview"]
    assert [i["category"] for i in body["waiting"]] == ["Timesheet draft", "Training in progress"]
    assert body["waiting"][1]["count"] == 3
    assert body["sensitive_counts"] == {"Resignation approvals": 1, "PIP approvals": 1, "Offboarding checklist tasks": 1}
    assert body["total_items"] == 1 + 1 + 1 + 1 + 1 + 1 + 3 and body["counts"]["Training in progress"] == 3
    assert body["listed"] == 4 and body["truncated"] is False
    # the sensitive people are not named anywhere in the response
    for name in ("Secret Person", "Pip Person", "Leaver Person", "Return laptop"):
        assert name not in res.text


def test_a_long_list_is_capped_most_pressing_first(client, hr_with_employee, monkeypatch):
    rows = ([row(kind="approval", module="leave", key=f"o{i}", label=f"overdue {i}", employee_name="P", days_overdue=1) for i in range(10)]
            + [row(kind="approval", module="leave", key=f"w{i}", label=f"waiting {i}", employee_name="P") for i in range(80)])
    monkeypatch.setattr(me_todos, "build_todos", lambda conn, user: rows)
    body = client.get("/api/me/todos", headers=hr_with_employee).json()
    assert body["total_items"] == 90 and body["listed"] == 50 and body["truncated"] is True
    assert len(body["overdue"]) == 10 and len(body["waiting"]) == 40


def test_it_shows_the_real_widget_content_a_draft_timesheet_and_a_leave_request_waiting_for_you(
        client, hr_with_employee, employee_with_login, make_test_leave_type):
    week = client.get("/api/me/week-hours", headers=hr_with_employee).json()
    emp_id = client.get("/api/auth/me", headers=hr_with_employee).json()["employee_id"]
    assert client.post("/api/timesheets", headers=hr_with_employee, json={"employee_id": emp_id, "period_start": week["week_start"], "period_end": week["week_end"]}).status_code == 201
    lt = make_test_leave_type(name="ZZ Todo Leave", requires_approval=True, annual_entitlement=20)
    amy, amy_h = employee_with_login(full_name="ZZ Todo Amy")
    app = client.post("/api/leave/applications", headers=amy_h, json={"employee_id": amy["employee_id"], "leave_type_id": lt["id"],
                                                                      "start_date": "2031-03-03", "end_date": "2031-03-03"})
    assert app.status_code == 201, app.text

    # The shared test company has hundreds of leftover pending approvals, so the 50-item cap may push these out of the *listed* items:
    # the per-category counts always include them.
    res = client.get("/api/me/todos", headers=hr_with_employee)
    body = res.json()
    assert body["counts"].get("Timesheet draft") == 1 and body["counts"].get("Leave approval", 0) >= 1
    assert "Todo Leave" not in res.text                                                    # the leave type never appears anywhere


def test_resignation_waiting_for_you_is_only_a_count(client, hr_with_employee, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ Todo Leaver Secret")
    assert client.post("/api/resignations", headers=headers, json={"reason": "private reason", "effective_date": "2027-06-01", "last_working_day": "2027-06-01"}).status_code == 201
    res = client.get("/api/me/todos", headers=hr_with_employee)
    assert res.json()["sensitive_counts"].get("Resignation approvals", 0) >= 1
    assert "ZZ Todo Leaver Secret" not in res.text and "private reason" not in res.text


def test_needs_a_linked_employee_and_a_login(client, make_test_user):
    token, _ = make_test_user(role="hr_manager")
    res = client.get("/api/me/todos", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400 and "employee record" in res.json()["detail"]
    assert client.get("/api/me/todos").status_code in (401, 403)
