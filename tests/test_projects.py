"""
Integration tests for routers/projects.py: Projects, Project Tasks, and
Task Assignments. Uses the shared make_test_project/make_test_project_task
fixtures from conftest.py (also reused by leave/timesheets tests, since
both need a real project+task to log time against).
"""
import pytest


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def test_list_projects_requires_auth(client):
    res = client.get("/api/projects")
    assert res.status_code in (401, 403)


def test_create_project_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/projects", headers=headers, json={"name": "ZZ", "status": "Active"})
    assert res.status_code == 403


def test_create_project_success(client, make_test_project):
    project = make_test_project(name="ZZ Special Project")
    assert project["name"] == "ZZ Special Project"
    assert project["status"] == "Active"


def test_create_project_missing_name_returns_422(client, hr_manager_auth):
    res = client.post("/api/projects", headers=hr_manager_auth, json={"status": "Active"})
    assert res.status_code == 422


def test_list_projects_includes_created_project(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.get("/api/projects", headers=hr_manager_auth)
    assert res.status_code == 200
    assert project["id"] in [p["id"] for p in res.json()]


def test_list_projects_filters_by_status(client, hr_manager_auth, make_test_project):
    project = make_test_project(status="On Hold")
    active_only = client.get("/api/projects", headers=hr_manager_auth, params={"status": "Active"}).json()
    assert project["id"] not in [p["id"] for p in active_only]

    on_hold_only = client.get("/api/projects", headers=hr_manager_auth, params={"status": "On Hold"}).json()
    assert project["id"] in [p["id"] for p in on_hold_only]


def test_update_project_success(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.put(
        f"/api/projects/{project['id']}", headers=hr_manager_auth,
        json={"name": "ZZ Renamed", "status": "Completed"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "ZZ Renamed"
    assert res.json()["status"] == "Completed"


def test_update_project_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/projects/999999999", headers=hr_manager_auth, json={"name": "ZZ", "status": "Active"})
    assert res.status_code == 404


def test_delete_project_success(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.delete(f"/api/projects/{project['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/projects", headers=hr_manager_auth).json()
    assert project["id"] not in [p["id"] for p in listed]


def test_project_utilization_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/projects/utilization", headers=headers)
    assert res.status_code == 403


def test_project_utilization_includes_active_project(client, hr_manager_auth, make_test_project):
    project = make_test_project(status="Active")
    res = client.get("/api/projects/utilization", headers=hr_manager_auth)
    assert res.status_code == 200
    assert project["id"] in [p["id"] for p in res.json()]


def test_my_projects_empty_for_user_with_no_employee_record(client, hr_manager_auth):
    """The hr_manager test user has no linked employee_id."""
    res = client.get("/api/projects/mine", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Project Tasks
# ---------------------------------------------------------------------------
def test_create_task_success(client, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"], name="ZZ Design phase", estimated_hours=10)
    assert task["name"] == "ZZ Design phase"
    assert task["estimated_hours"] == 10
    assert task["open_to_all"] is False or task["open_to_all"] == 0


def test_create_task_for_nonexistent_project_returns_404(client, hr_manager_auth):
    res = client.post("/api/projects/999999999/tasks", headers=hr_manager_auth, json={"name": "ZZ"})
    assert res.status_code == 404


def test_create_task_end_before_start_returns_400(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.post(
        f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth,
        json={"name": "ZZ", "start_date": "2026-02-01", "end_date": "2026-01-01"},
    )
    assert res.status_code == 400


def test_list_tasks_includes_created_task(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.get(f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth)
    assert res.status_code == 200
    assert task["id"] in [t["id"] for t in res.json()]


def test_employee_without_assignment_only_sees_open_to_all_tasks(
    client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task
):
    project = make_test_project()
    closed_task = make_test_project_task(project["id"], name="ZZ Closed Task")
    open_task = make_test_project_task(project["id"], name="ZZ Open Task")
    res = client.patch(
        f"/api/projects/{project['id']}/tasks/{open_task['id']}/open-to-all",
        headers=hr_manager_auth, json={"open_to_all": True},
    )
    assert res.status_code == 200

    emp = make_test_employee()
    emp_login = client.post("/api/users", headers=hr_manager_auth, json={
        "username": f"zzprojtest_{emp['employee_id'].lower()}",
        "full_name": "ZZ Project Test Employee",
        "password": "ZzPytest@123",
        "role": "employee",
        "employee_id": emp["employee_id"],
    })
    assert emp_login.status_code == 201
    login = client.post("/api/auth/login", json={
        "username": emp_login.json()["username"], "password": "ZzPytest@123",
        "institution_code": "ZZPYTEST",
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    res = client.get(f"/api/projects/{project['id']}/tasks", headers=emp_headers)
    assert res.status_code == 200
    visible_ids = [t["id"] for t in res.json()]
    assert open_task["id"] in visible_ids
    assert closed_task["id"] not in visible_ids

    client.delete(f"/api/users/{emp_login.json()['id']}", headers=hr_manager_auth)


def test_update_task_success(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.put(
        f"/api/projects/{project['id']}/tasks/{task['id']}", headers=hr_manager_auth,
        json={"name": "ZZ Updated Task", "status": "In Progress"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "ZZ Updated Task"


def test_update_task_not_found_returns_404(client, hr_manager_auth, make_test_project):
    project = make_test_project()
    res = client.put(f"/api/projects/{project['id']}/tasks/999999999", headers=hr_manager_auth, json={"name": "ZZ"})
    assert res.status_code == 404


def test_delete_task_success(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.delete(f"/api/projects/{project['id']}/tasks/{task['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get(f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth).json()
    assert task["id"] not in [t["id"] for t in listed]


# ---------------------------------------------------------------------------
# Task Assignments
# ---------------------------------------------------------------------------
def test_add_assignment_success(client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    emp = make_test_employee()
    res = client.post(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth,
        json={"employee_id": emp["employee_id"], "start_datetime": "2026-08-01T09:00", "duration_hours": 4},
    )
    assert res.status_code == 201
    assert res.json()["employee_id"] == emp["employee_id"]


def test_add_assignment_for_nonexistent_employee_returns_404(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.post(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth,
        json={"employee_id": "EMP_ZZ_NONEXISTENT", "start_datetime": "2026-08-01T09:00", "duration_hours": 4},
    )
    assert res.status_code == 404


def test_add_assignment_zero_duration_returns_400(client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    emp = make_test_employee()
    res = client.post(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth,
        json={"employee_id": emp["employee_id"], "start_datetime": "2026-08-01T09:00", "duration_hours": 0},
    )
    assert res.status_code == 400


def test_add_duplicate_assignment_returns_400(client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    emp = make_test_employee()
    payload = {"employee_id": emp["employee_id"], "start_datetime": "2026-08-01T09:00", "duration_hours": 4}
    first = client.post(f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth, json=payload)
    assert first.status_code == 201
    dup = client.post(f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth, json=payload)
    assert dup.status_code == 400


def test_list_assignments_includes_added_assignment(client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    emp = make_test_employee()
    client.post(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth,
        json={"employee_id": emp["employee_id"], "start_datetime": "2026-08-01T09:00", "duration_hours": 4},
    )
    res = client.get(f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth)
    assert res.status_code == 200
    assert emp["employee_id"] in [a["employee_id"] for a in res.json()]


def test_remove_assignment_success(client, hr_manager_auth, make_test_employee, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    emp = make_test_employee()
    client.post(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth,
        json={"employee_id": emp["employee_id"], "start_datetime": "2026-08-01T09:00", "duration_hours": 4},
    )
    res = client.delete(
        f"/api/projects/{project['id']}/tasks/{task['id']}/assignments/{emp['employee_id']}", headers=hr_manager_auth
    )
    assert res.status_code == 204
    listed = client.get(f"/api/projects/{project['id']}/tasks/{task['id']}/assignments", headers=hr_manager_auth).json()
    assert emp["employee_id"] not in [a["employee_id"] for a in listed]


def test_set_task_open_to_all(client, hr_manager_auth, make_test_project, make_test_project_task):
    project = make_test_project()
    task = make_test_project_task(project["id"])
    res = client.patch(
        f"/api/projects/{project['id']}/tasks/{task['id']}/open-to-all", headers=hr_manager_auth,
        json={"open_to_all": True},
    )
    assert res.status_code == 200
    assert res.json()["open_to_all"] in (True, 1)
