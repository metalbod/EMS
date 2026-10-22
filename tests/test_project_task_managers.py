"""A project's own managers may add, edit and delete its tasks (routers/projects.py's require_task_manage), and /api/auth/me tells the
web app when to show them the Projects page (manages_projects). HR Manager keeps full access; everyone else is still refused."""
import pytest


@pytest.fixture
def team(client, employee_with_login, make_test_project):
    """boss manages the project (and is NOT a member); mate is a member only; stranger is neither; other_boss manages a different project."""
    boss, boss_h = employee_with_login(full_name="ZZ PM Boss")
    mate, mate_h = employee_with_login(full_name="ZZ PM Mate")
    stranger, stranger_h = employee_with_login(full_name="ZZ PM Stranger")
    other_boss, other_h = employee_with_login(full_name="ZZ PM Other Boss")
    project = make_test_project(name="ZZ PM Project", manager_ids=[boss["employee_id"]], member_ids=[mate["employee_id"]], is_open_to_all=False)
    other = make_test_project(name="ZZ PM Other Project", manager_ids=[other_boss["employee_id"]], is_open_to_all=False)
    return {"project": project, "other": other, "boss": boss_h, "mate": mate_h, "stranger": stranger_h, "other_boss": other_h}


def test_a_project_manager_can_add_edit_and_delete_tasks_on_their_project(client, team):
    p, boss = team["project"], team["boss"]
    created = client.post(f"/api/projects/{p['id']}/tasks", headers=boss, json={"name": "ZZ New Task", "estimated_hours": 5})
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    edited = client.put(f"/api/projects/{p['id']}/tasks/{tid}", headers=boss, json={"name": "ZZ Renamed", "status": "In Progress"})
    assert edited.status_code == 200 and edited.json()["name"] == "ZZ Renamed" and edited.json()["status"] == "In Progress"
    assert client.delete(f"/api/projects/{p['id']}/tasks/{tid}", headers=boss).status_code == 204


@pytest.mark.parametrize("who", ["mate", "stranger", "other_boss"])
def test_nobody_else_can_change_the_tasks(client, team, who):
    """A member, an outsider, and the manager of a DIFFERENT project are all refused; the project's own tasks are untouched."""
    p = team["project"]
    h = team[who]
    assert client.post(f"/api/projects/{p['id']}/tasks", headers=h, json={"name": "ZZ Nope"}).status_code == 403
    assert client.put(f"/api/projects/{p['id']}/tasks/1", headers=h, json={"name": "ZZ Nope"}).status_code == 403
    assert client.delete(f"/api/projects/{p['id']}/tasks/1", headers=h).status_code == 403


def test_hr_manager_still_manages_every_project(client, team, hr_manager_auth):
    res = client.post(f"/api/projects/{team['other']['id']}/tasks", headers=hr_manager_auth, json={"name": "ZZ HR Task"})
    assert res.status_code == 201


def test_a_manager_who_is_not_a_member_can_still_see_the_tasks(client, team, hr_manager_auth):
    p = team["project"]
    client.post(f"/api/projects/{p['id']}/tasks", headers=hr_manager_auth, json={"name": "ZZ Visible"})
    assert [t["name"] for t in client.get(f"/api/projects/{p['id']}/tasks", headers=team["boss"]).json()] == ["ZZ Visible"]
    assert client.get(f"/api/projects/{p['id']}/tasks", headers=team["stranger"]).json() == []      # unchanged for an outsider


def test_task_date_rules_still_apply_to_project_managers(client, employee_with_login, make_test_project):
    boss, h = employee_with_login(full_name="ZZ PM Dates")
    p = make_test_project(name="ZZ PM Dated", manager_ids=[boss["employee_id"]], start_date="2027-01-01", end_date="2027-03-31")
    bad = client.post(f"/api/projects/{p['id']}/tasks", headers=h, json={"name": "ZZ Early", "start_date": "2026-12-01"})
    assert bad.status_code == 400 and "before the project's start date" in bad.json()["detail"]
    assert client.post(f"/api/projects/{p['id']}/tasks", headers=h, json={"name": "ZZ Ok", "start_date": "2027-01-05"}).status_code == 201


def test_deleting_a_task_with_logged_hours_is_still_refused(client, team, hr_manager_auth):
    p = team["project"]
    task = client.post(f"/api/projects/{p['id']}/tasks", headers=hr_manager_auth, json={"name": "ZZ Worked"}).json()
    logged = client.post("/api/me/timesheet/log-hours", headers=team["mate"], json={"project_id": p["id"], "task_id": task["id"], "hours": 2})
    assert logged.status_code == 201, logged.text
    res = client.delete(f"/api/projects/{p['id']}/tasks/{task['id']}", headers=team["boss"])
    assert res.status_code == 400 and "Completed" in res.json()["detail"]


def test_me_says_who_manages_projects(client, team):
    assert client.get("/api/auth/me", headers=team["boss"]).json()["manages_projects"] is True
    assert client.get("/api/auth/me", headers=team["other_boss"]).json()["manages_projects"] is True
    assert client.get("/api/auth/me", headers=team["mate"]).json()["manages_projects"] is False
    assert client.get("/api/auth/me", headers=team["stranger"]).json()["manages_projects"] is False
