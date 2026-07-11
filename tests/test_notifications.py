"""
Integration tests for routers/notifications.py.

Institution notifications are scoped to the test institution, so they're
safe to create freely. System-wide notifications have NO institution
scoping at all (they're global, shown to every institution including
superadmin) — tests use far-future timestamps so they never become
"active" and never overlap a real system notification, and every test
deletes what it created immediately rather than relying on fixture
teardown, to minimize the window where stray global data could be visible
to a real user.
"""
import itertools
import random

import pytest

_time_counter = itertools.count(1)
_time_salt = 2100 + random.randint(0, 800)  # far-future year


def _unique_window():
    """A distinct, non-overlapping [start, end) time window per call, far in
    the future so it's never "active" and never collides with real data or
    other tests/runs."""
    year = _time_salt + next(_time_counter)
    return f"{year}-01-01T09:00", f"{year}-01-01T17:00"


@pytest.fixture
def make_test_notification(client, hr_manager_auth):
    created_ids = []

    def _make(**overrides):
        start, end = _unique_window()
        payload = {"message": "ZZ Test Notification", "start_time": start, "end_time": end}
        payload.update(overrides)
        res = client.post("/api/notifications", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test notification: {res.text}"
        notif = res.json()
        created_ids.append(notif["id"])
        return notif

    yield _make

    for nid in created_ids:
        client.delete(f"/api/notifications/{nid}", headers=hr_manager_auth)


@pytest.fixture
def make_test_system_notification(client, superadmin_headers):
    """Same as above but for the global system_notifications table —
    deletes immediately after each assertion inside the test itself is
    preferred; this fixture is a teardown backstop only."""
    created_ids = []

    def _make(**overrides):
        start, end = _unique_window()
        payload = {"message": "ZZ Test System Notification", "start_time": start, "end_time": end}
        payload.update(overrides)
        res = client.post("/api/system-notifications", headers=superadmin_headers, json=payload)
        assert res.status_code == 201, f"failed to create test system notification: {res.text}"
        notif = res.json()
        created_ids.append(notif["id"])
        return notif

    yield _make

    for nid in created_ids:
        client.delete(f"/api/system-notifications/{nid}", headers=superadmin_headers)


# ---------------------------------------------------------------------------
# Institution notifications
# ---------------------------------------------------------------------------
def test_list_notifications_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications", headers=headers)
    assert res.status_code == 403


def test_create_notification_success(client, make_test_notification):
    notif = make_test_notification(message="ZZ Hello everyone")
    assert notif["message"] == "ZZ Hello everyone"


def test_create_notification_blank_message_returns_422(client, hr_manager_auth):
    start, end = _unique_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "   ", "start_time": start, "end_time": end},
    )
    assert res.status_code == 422


def test_create_notification_end_before_start_returns_400(client, hr_manager_auth):
    start, end = _unique_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ", "start_time": end, "end_time": start},
    )
    assert res.status_code == 400


def test_create_notification_overlap_rejected(client, hr_manager_auth, make_test_notification):
    existing = make_test_notification()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Overlapping", "start_time": existing["start_time"], "end_time": existing["end_time"]},
    )
    assert res.status_code == 400
    assert "already active/scheduled" in res.json()["detail"]


def test_list_notifications_includes_created(client, hr_manager_auth, make_test_notification):
    notif = make_test_notification()
    res = client.get("/api/notifications", headers=hr_manager_auth)
    assert res.status_code == 200
    assert notif["id"] in [n["id"] for n in res.json()]


def test_update_notification_success(client, hr_manager_auth, make_test_notification):
    notif = make_test_notification()
    res = client.put(
        f"/api/notifications/{notif['id']}", headers=hr_manager_auth,
        json={"message": "ZZ Updated", "start_time": notif["start_time"], "end_time": notif["end_time"]},
    )
    assert res.status_code == 200
    assert res.json()["message"] == "ZZ Updated"


def test_update_notification_not_found_returns_404(client, hr_manager_auth):
    start, end = _unique_window()
    res = client.put(
        "/api/notifications/999999999", headers=hr_manager_auth,
        json={"message": "ZZ", "start_time": start, "end_time": end},
    )
    assert res.status_code == 404


def test_update_notification_overlap_with_another_rejected(client, hr_manager_auth, make_test_notification):
    first = make_test_notification()
    second = make_test_notification()
    res = client.put(
        f"/api/notifications/{second['id']}", headers=hr_manager_auth,
        json={"message": "ZZ", "start_time": first["start_time"], "end_time": first["end_time"]},
    )
    assert res.status_code == 400


def test_delete_notification_success(client, hr_manager_auth, make_test_notification):
    notif = make_test_notification()
    res = client.delete(f"/api/notifications/{notif['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/notifications", headers=hr_manager_auth).json()
    assert notif["id"] not in [n["id"] for n in listed]


def test_active_notification_returns_none_when_window_is_future(client, make_test_user, test_institution, make_test_notification):
    """The notification exists but its window is far in the future, so it's
    not 'active' right now."""
    make_test_notification()
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/active", headers=headers)
    assert res.status_code == 200
    assert res.json() is None


def test_active_notification_returns_none_for_superadmin(client, superadmin_headers):
    res = client.get("/api/notifications/active", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json() is None


# ---------------------------------------------------------------------------
# System-wide notifications (global — superadmin only)
# ---------------------------------------------------------------------------
def test_list_system_notifications_requires_superadmin(client, hr_manager_auth):
    res = client.get("/api/system-notifications", headers=hr_manager_auth)
    assert res.status_code == 403


def test_create_system_notification_success(client, superadmin_headers, make_test_system_notification):
    notif = make_test_system_notification(message="ZZ System Message")
    assert notif["message"] == "ZZ System Message"


def test_create_system_notification_end_before_start_returns_400(client, superadmin_headers):
    start, end = _unique_window()
    res = client.post(
        "/api/system-notifications", headers=superadmin_headers,
        json={"message": "ZZ", "start_time": end, "end_time": start},
    )
    assert res.status_code == 400


def test_create_system_notification_overlap_rejected(client, superadmin_headers, make_test_system_notification):
    existing = make_test_system_notification()
    res = client.post(
        "/api/system-notifications", headers=superadmin_headers,
        json={"message": "ZZ Overlap", "start_time": existing["start_time"], "end_time": existing["end_time"]},
    )
    assert res.status_code == 400


def test_update_system_notification_not_found_returns_404(client, superadmin_headers):
    start, end = _unique_window()
    res = client.put(
        "/api/system-notifications/999999999", headers=superadmin_headers,
        json={"message": "ZZ", "start_time": start, "end_time": end},
    )
    assert res.status_code == 404


def test_delete_system_notification_success(client, superadmin_headers, make_test_system_notification):
    notif = make_test_system_notification()
    res = client.delete(f"/api/system-notifications/{notif['id']}", headers=superadmin_headers)
    assert res.status_code == 204
    listed = client.get("/api/system-notifications", headers=superadmin_headers).json()
    assert notif["id"] not in [n["id"] for n in listed]


def test_active_system_notification_returns_none_when_window_is_future(client, hr_manager_auth, make_test_system_notification):
    make_test_system_notification()
    res = client.get("/api/system-notifications/active", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() is None
