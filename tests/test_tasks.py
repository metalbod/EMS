"""Tests for the async task status endpoint's per-task ownership authorization.

Previously GET /api/tasks/{task_id} had no authorization at all — any
authenticated user of any role could look up any task ID.
"""
import uuid
import pytest
from db import get_db


def _insert_tracking_row(user_id, inst_id, task_id=None):
    task_id = task_id or str(uuid.uuid4())
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO task_tracking (id, user_id, institution_id, task_type, status) VALUES (?, ?, ?, ?, ?)",
            (task_id, user_id, inst_id, "bulk_upload", "pending"),
        )
        conn.commit()
    finally:
        conn.close()
    return task_id


def _employee_headers(make_test_user, test_institution, role="employee"):
    token, user_id = make_test_user(role=role)
    return {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}, user_id


def test_owner_can_view_own_task(client, make_test_user, test_institution):
    headers, user_id = _employee_headers(make_test_user, test_institution)
    task_id = _insert_tracking_row(user_id, test_institution["id"])

    res = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == task_id


def test_non_owner_non_hr_cannot_view_others_task(client, make_test_user, test_institution):
    owner_headers, owner_id = _employee_headers(make_test_user, test_institution)
    task_id = _insert_tracking_row(owner_id, test_institution["id"])

    other_headers, _ = _employee_headers(make_test_user, test_institution)
    res = client.get(f"/api/tasks/{task_id}", headers=other_headers)
    assert res.status_code == 403


def test_hr_tier_can_view_any_tracked_task(client, make_test_user, hr_manager_auth, test_institution):
    owner_headers, owner_id = _employee_headers(make_test_user, test_institution)
    task_id = _insert_tracking_row(owner_id, test_institution["id"])

    res = client.get(f"/api/tasks/{task_id}", headers=hr_manager_auth)
    assert res.status_code == 200


def test_untracked_task_id_is_hr_tier_only(client, make_test_user, hr_manager_auth, test_institution):
    untracked_task_id = str(uuid.uuid4())

    employee_headers, _ = _employee_headers(make_test_user, test_institution)
    res = client.get(f"/api/tasks/{untracked_task_id}", headers=employee_headers)
    assert res.status_code == 403

    res = client.get(f"/api/tasks/{untracked_task_id}", headers=hr_manager_auth)
    assert res.status_code == 200
