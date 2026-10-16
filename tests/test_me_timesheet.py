"""Claude self-service timesheet endpoints: routers/me_timesheet.py (log today's hours, see the week's hours)."""
from datetime import datetime, timedelta

import pytest


def _today(client, headers):
    return client.get("/api/me/week-hours", headers=headers).json()


@pytest.fixture
def open_project(make_test_project, make_test_project_task):
    project = make_test_project(name="ZZ Self Service Project", is_open_to_all=True)
    task = make_test_project_task(project["id"], name="ZZ Self Service Task")
    task2 = make_test_project_task(project["id"], name="ZZ Self Service Task B")
    return project, task, task2


def test_projects_list_has_tasks_and_hides_closed_projects(client, employee_with_login, open_project, make_test_project):
    _, headers = employee_with_login(full_name="ZZ Self Projects")
    project, task, _ = open_project
    closed = make_test_project(name="ZZ Members Only Project", is_open_to_all=False)
    rows = client.get("/api/me/timesheet/projects", headers=headers).json()
    mine = next(r for r in rows if r["project_id"] == project["id"])
    assert any(t["task_id"] == task["id"] for t in mine["tasks"])
    assert closed["id"] not in {r["project_id"] for r in rows}          # not open to all, and they're not a member


def test_log_hours_creates_the_week_draft_and_adds_to_existing(client, employee_with_login, open_project):
    emp, headers = employee_with_login(full_name="ZZ Self Logger")
    project, task, task2 = open_project
    res = client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task["id"], "hours": 2.5})
    assert res.status_code == 201, res.text
    a = res.json()
    assert a["hours_added"] == 2.5 and a["task_hours_that_day"] == 2.5 and a["added_to_existing"] is False
    assert a["timesheet_status"] == "Draft" and a["project_name"] == "ZZ Self Service Project"

    b = client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task["id"], "hours": 1}).json()
    assert b["task_hours_that_day"] == 3.5 and b["added_to_existing"] is True and b["entry_id"] == a["entry_id"]
    c = client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task2["id"], "hours": 4}).json()
    assert c["day_total_hours"] == 7.5 and c["week_logged_hours"] == 7.5

    # it landed on the same timesheet the web screen would use, as one cell per task
    week = client.get("/api/me/week-hours", headers=headers).json()
    ts = client.get("/api/timesheets", headers=headers, params={"employee_id": emp["employee_id"]}).json()[0]
    detail = client.get(f"/api/timesheets/{ts['id']}", headers=headers).json()
    assert sorted(e["hours"] for e in detail["entries"]) == [3.5, 4.0] and detail["total_hours"] == week["logged_hours"] == 7.5


@pytest.mark.parametrize("body,fragment", [
    ({"hours": 0}, "between 0 and 24"),
    ({"hours": 25}, "between 0 and 24"),
    ({"hours": 1, "date": "2000-01-03"}, "this week"),
    ({"hours": 1, "date": "not-a-date"}, "Dates must look like"),
])
def test_log_hours_rules(client, employee_with_login, open_project, body, fragment):
    _, headers = employee_with_login(full_name="ZZ Self Rules")
    project, task, _ = open_project
    res = client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task["id"], **body})
    assert res.status_code == 400 and fragment in res.json()["detail"], res.text


def test_cannot_log_future_days_or_over_24_hours_in_a_day(client, employee_with_login, open_project):
    _, headers = employee_with_login(full_name="ZZ Self Future")
    project, task, task2 = open_project
    today = datetime.strptime(client.get("/api/me/week-hours", headers=headers).json()["days"][0]["date"], "%Y-%m-%d")
    base = {"project_id": project["id"], "task_id": task["id"], "hours": 1}
    week = client.get("/api/me/week-hours", headers=headers).json()
    # a day later in the week than today, if there is one, is refused as a future day
    from core.institution_time import institution_today
    from db import get_admin_db
    conn = get_admin_db()
    try:
        # the company's own "today" (the test company's timezone), via the same helper the endpoint uses
        inst = conn.execute("SELECT id FROM institutions WHERE code='ZZPYTEST'").fetchone()
        today_str = institution_today(conn, inst["id"])
    finally:
        conn.close()
    t = datetime.strptime(today_str, "%Y-%m-%d")
    if t.weekday() < 6:
        res = client.post("/api/me/timesheet/log-hours", headers=headers, json={**base, "date": (t + timedelta(days=1)).strftime("%Y-%m-%d")})
        assert res.status_code == 400 and "future" in res.json()["detail"]
    assert client.post("/api/me/timesheet/log-hours", headers=headers, json={**base, "hours": 20}).status_code == 201
    over = client.post("/api/me/timesheet/log-hours", headers=headers, json={**base, "task_id": task2["id"], "hours": 5})
    assert over.status_code == 400 and "24" in over.json()["detail"]


def test_cannot_log_to_a_project_they_are_not_on(client, employee_with_login, make_test_project, make_test_project_task):
    _, headers = employee_with_login(full_name="ZZ Self Outsider")
    project = make_test_project(name="ZZ Closed Self", is_open_to_all=False)
    task = make_test_project_task(project["id"])
    res = client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task["id"], "hours": 1})
    assert res.status_code == 403
    assert client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": 99999999, "task_id": 1, "hours": 1}).status_code == 400


def test_week_hours_shows_clocked_logged_and_my_timesheets_missing_figure(client, employee_with_login, open_project):
    _, headers = employee_with_login(full_name="ZZ Self Week")
    project, task, _ = open_project
    empty = client.get("/api/me/week-hours", headers=headers).json()
    assert empty["timesheet_status"] == "Not started" and empty["logged_hours"] == 0 and empty["clocked_hours"] == 0
    assert len(empty["days"]) == 7 and empty["days"][0]["weekday"] == "Mon" and empty["week_end"] > empty["week_start"]
    assert empty["missing_hours"] == max(0, empty["expected_hours"] - empty["holiday_hours"] - empty["leave_hours"])

    assert client.post("/api/attendance/clock-in", headers=headers, json={}).status_code == 201
    client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task["id"], "hours": 6})
    w = client.get("/api/me/week-hours", headers=headers).json()
    assert w["clocked_in_now"] is not None and w["clocked_hours"] >= 0
    assert w["logged_hours"] == 6 and w["timesheet_status"] == "Draft"
    assert w["missing_hours"] == round(max(0, w["expected_hours"] - 6 - w["holiday_hours"] - w["leave_hours"]), 2)
    assert sum(d["logged_hours"] for d in w["days"]) == 6
    client.post("/api/attendance/clock-out", headers=headers, json={})
    assert client.get("/api/me/week-hours", headers=headers).json()["clocked_in_now"] is None


def test_week_hours_for_another_week_and_bad_dates(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Self Old Week")
    res = client.get("/api/me/week-hours", headers=headers, params={"date": "2026-01-14"})   # a Wednesday
    assert res.status_code == 200 and res.json()["week_start"] == "2026-01-12" and res.json()["week_end"] == "2026-01-18"
    assert client.get("/api/me/week-hours", headers=headers, params={"date": "nope"}).status_code == 400


def test_needs_a_linked_employee(client, make_test_user):
    token, _ = make_test_user(role="hr_manager")
    res = client.get("/api/me/week-hours", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400 and "employee record" in res.json()["detail"]


def test_logging_hours_leaves_an_audit_entry(client, employee_with_login, open_project):
    from db import get_admin_db
    emp, headers = employee_with_login(full_name="ZZ Self Audit")
    project, task, _ = open_project
    client.post("/api/me/timesheet/log-hours", headers=headers, json={"project_id": project["id"], "task_id": task["id"], "hours": 1.5})
    conn = get_admin_db()
    try:
        row = conn.execute("SELECT action, detail FROM timesheet_audit_log WHERE employee_id=? AND action='Hours logged' ORDER BY id DESC LIMIT 1",
                           (emp["employee_id"],)).fetchone()
    finally:
        conn.close()
    assert row and "1.5h on ZZ Self Service Project" in row["detail"]


def test_projects_include_managers_members_and_task_details(client, hr_manager_auth, employee_with_login, make_test_employee,
                                                             make_test_project, make_test_project_task):
    me, headers = employee_with_login(full_name="ZZ Proj Me")
    boss = make_test_employee(full_name="ZZ Proj Boss", designation="Lead")
    mate = make_test_employee(full_name="ZZ Proj Mate")
    gone = make_test_employee(full_name="ZZ Proj Gone")
    project = make_test_project(name="ZZ Teamed Project", customer="ZZ Client", manager_ids=[boss["employee_id"]],
                                member_ids=[me["employee_id"], mate["employee_id"], gone["employee_id"]])
    task = make_test_project_task(project["id"], name="ZZ Teamed Task", estimated_hours=12)
    assert client.patch(f"/api/employees/{gone['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"}).status_code == 200

    rows = client.get("/api/me/timesheet/projects", headers=headers).json()
    p = next(r for r in rows if r["project_id"] == project["id"])
    assert [m["full_name"] for m in p["managers"]] == ["ZZ Proj Boss"] and p["managers"][0]["designation"] == "Lead"
    assert sorted(m["full_name"] for m in p["members"]) == ["ZZ Proj Mate", "ZZ Proj Me"]        # the inactive employee is left out
    assert p["you_are_member"] is True and p["you_are_manager"] is False and p["open_to_all"] is False and p["customer"] == "ZZ Client"
    t = next(t for t in p["tasks"] if t["task_id"] == task["id"])
    assert t["estimated_hours"] == 12 and t["task_name"] == "ZZ Teamed Task"
    # names and roles only: no contact details or ids of the people
    assert set(p["managers"][0]) == {"name", "full_name", "designation", "department"}

    only = client.get("/api/me/timesheet/projects", headers=headers, params={"search": "teamed proj"}).json()
    assert [r["project_id"] for r in only] == [project["id"]]
    assert client.get("/api/me/timesheet/projects", headers=headers, params={"search": "no such project xyz"}).json() == []


def test_open_to_all_project_is_flagged_and_not_a_membership(client, employee_with_login, open_project):
    _, headers = employee_with_login(full_name="ZZ Proj Open")
    project, _, _ = open_project
    p = next(r for r in client.get("/api/me/timesheet/projects", headers=headers).json() if r["project_id"] == project["id"])
    assert p["open_to_all"] is True and p["you_are_member"] is False and p["you_are_manager"] is False
