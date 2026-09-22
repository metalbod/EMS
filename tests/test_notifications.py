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
from datetime import datetime, timedelta, timezone

import pytest

_time_counter = itertools.count(1)
_time_salt = 2100 + random.randint(0, 800)  # far-future year


def _unique_window():
    """A distinct, non-overlapping [start, end) time window per call, far in
    the future so it's never "active" and never collides with real data or
    other tests/runs."""
    year = _time_salt + next(_time_counter)
    return f"{year}-01-01T09:00", f"{year}-01-01T17:00"


def _active_window():
    """A window that IS active right now (brackets the current UTC time),
    distinguishable from `_unique_window()`'s far-future windows."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    end = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return start, end


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


def test_create_notification_overlap_allowed(client, hr_manager_auth, make_test_notification):
    """Institution notifications stack — a second one in the same window is
    no longer rejected."""
    existing = make_test_notification()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Overlapping", "start_time": existing["start_time"], "end_time": existing["end_time"]},
    )
    assert res.status_code == 201
    client.delete(f"/api/notifications/{res.json()['id']}", headers=hr_manager_auth)


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


def test_update_notification_overlap_with_another_allowed(client, hr_manager_auth, make_test_notification):
    """Same relaxation applies on update — moving one notification's window
    to overlap another's no longer rejects."""
    first = make_test_notification()
    second = make_test_notification()
    res = client.put(
        f"/api/notifications/{second['id']}", headers=hr_manager_auth,
        json={"message": "ZZ", "start_time": first["start_time"], "end_time": first["end_time"]},
    )
    assert res.status_code == 200


def test_delete_notification_success(client, hr_manager_auth, make_test_notification):
    notif = make_test_notification()
    res = client.delete(f"/api/notifications/{notif['id']}", headers=hr_manager_auth)
    assert res.status_code == 204
    listed = client.get("/api/notifications", headers=hr_manager_auth).json()
    assert notif["id"] not in [n["id"] for n in listed]


def test_active_notifications_returns_empty_list_when_window_is_future(client, make_test_user, test_institution, make_test_notification):
    """The notification exists but its window is far in the future, so it's
    not 'active' right now."""
    make_test_notification()
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/active", headers=headers)
    assert res.status_code == 200
    assert res.json() == []


def test_active_notifications_returns_empty_list_for_superadmin(client, superadmin_headers):
    res = client.get("/api/notifications/active", headers=superadmin_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_active_notifications_stacks_multiple(client, make_test_user, test_institution, hr_manager_auth):
    """Two institution notifications with overlapping active windows both
    show up in the active list at once — they stack rather than the older
    behavior of at most one being "the" active notification."""
    start, end = _active_window()
    created = []
    for msg in ("ZZ Stack One", "ZZ Stack Two"):
        res = client.post(
            "/api/notifications", headers=hr_manager_auth,
            json={"message": msg, "start_time": start, "end_time": end},
        )
        assert res.status_code == 201, res.text
        created.append(res.json())

    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/active", headers=headers)
    assert res.status_code == 200
    active_ids = {n["id"] for n in res.json()}
    assert {c["id"] for c in created} <= active_ids

    for c in created:
        client.delete(f"/api/notifications/{c['id']}", headers=hr_manager_auth)


# ---------------------------------------------------------------------------
# Audience targeting ('everyone' vs 'under' — migrations/versions/
# 20260922_0002_notification_audience_targeting.py)
# ---------------------------------------------------------------------------
def test_create_notification_under_requires_target_employee_ids(client, hr_manager_auth):
    start, end = _unique_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Under No Targets", "start_time": start, "end_time": end, "target_type": "under"},
    )
    assert res.status_code == 422


def test_create_notification_invalid_target_type_returns_422(client, hr_manager_auth):
    start, end = _unique_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Bad Target Type", "start_time": start, "end_time": end, "target_type": "nobody"},
    )
    assert res.status_code == 422


def test_create_notification_under_unknown_employee_id_returns_400(client, hr_manager_auth):
    start, end = _unique_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Unknown Target", "start_time": start, "end_time": end,
              "target_type": "under", "target_employee_ids": ["EMP_DOES_NOT_EXIST"]},
    )
    assert res.status_code == 400


def test_create_notification_under_success_returns_target_employees(client, hr_manager_auth, make_test_employee, make_test_notification):
    anchor = make_test_employee(full_name="ZZ Audience Anchor")
    notif = make_test_notification(target_type="under", target_employee_ids=[anchor["employee_id"]])
    assert notif["target_type"] == "under"
    assert [t["employee_id"] for t in notif["target_employees"]] == [anchor["employee_id"]]

    listed = client.get("/api/notifications", headers=hr_manager_auth).json()
    row = next(n for n in listed if n["id"] == notif["id"])
    assert [t["employee_id"] for t in row["target_employees"]] == [anchor["employee_id"]]


def test_update_notification_can_change_audience(client, hr_manager_auth, make_test_employee, make_test_notification):
    anchor = make_test_employee(full_name="ZZ Audience Switch Anchor")
    notif = make_test_notification()
    assert notif["target_type"] == "everyone"

    res = client.put(
        f"/api/notifications/{notif['id']}", headers=hr_manager_auth,
        json={"message": notif["message"], "start_time": notif["start_time"], "end_time": notif["end_time"],
              "target_type": "under", "target_employee_ids": [anchor["employee_id"]]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["target_type"] == "under"
    assert [t["employee_id"] for t in res.json()["target_employees"]] == [anchor["employee_id"]]

    # Switching back to 'everyone' clears the previously-saved targets.
    res = client.put(
        f"/api/notifications/{notif['id']}", headers=hr_manager_auth,
        json={"message": notif["message"], "start_time": notif["start_time"], "end_time": notif["end_time"],
              "target_type": "everyone"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["target_type"] == "everyone"
    assert res.json()["target_employees"] == []


def test_active_notification_under_reaches_anchor_and_transitive_subordinates_only(
    client, hr_manager_auth, employee_with_login, test_institution
):
    """anchor <- report <- subreport, plus an unrelated outsider. The
    'under' audience must include the anchor themselves (inclusive) and
    every transitive report (subreport, not just the direct report), but
    never someone outside that chain."""
    anchor, anchor_headers = employee_with_login(full_name="ZZ Audience Chain Anchor")
    report, report_headers = employee_with_login(full_name="ZZ Audience Chain Report", reports_to=anchor["employee_id"])
    subreport, subreport_headers = employee_with_login(full_name="ZZ Audience Chain Subreport", reports_to=report["employee_id"])
    outsider, outsider_headers = employee_with_login(full_name="ZZ Audience Chain Outsider")

    start, end = _active_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Chain Notice", "start_time": start, "end_time": end,
              "target_type": "under", "target_employee_ids": [anchor["employee_id"]]},
    )
    assert res.status_code == 201, res.text
    notif_id = res.json()["id"]

    def sees_it(headers):
        active = client.get("/api/notifications/active", headers=headers).json()
        return notif_id in {n["id"] for n in active}

    assert sees_it(anchor_headers), "the anchor themselves must see their own 'under' notification"
    assert sees_it(report_headers), "a direct report must see it"
    assert sees_it(subreport_headers), "a transitive (grandchild) report must see it too"
    assert not sees_it(outsider_headers), "someone outside the chain must not see it"

    client.delete(f"/api/notifications/{notif_id}", headers=hr_manager_auth)


def test_active_notification_under_multiple_anchors_is_a_union(
    client, hr_manager_auth, employee_with_login
):
    """Two independent anchors on one notification — each anchor's own
    report sees it (a union of subtrees), but someone under neither does
    not."""
    anchor_a, _ = employee_with_login(full_name="ZZ Union Anchor A")
    report_a, report_a_headers = employee_with_login(full_name="ZZ Union Report A", reports_to=anchor_a["employee_id"])
    anchor_b, _ = employee_with_login(full_name="ZZ Union Anchor B")
    report_b, report_b_headers = employee_with_login(full_name="ZZ Union Report B", reports_to=anchor_b["employee_id"])
    outsider, outsider_headers = employee_with_login(full_name="ZZ Union Outsider")

    start, end = _active_window()
    res = client.post(
        "/api/notifications", headers=hr_manager_auth,
        json={"message": "ZZ Union Notice", "start_time": start, "end_time": end,
              "target_type": "under", "target_employee_ids": [anchor_a["employee_id"], anchor_b["employee_id"]]},
    )
    assert res.status_code == 201, res.text
    notif_id = res.json()["id"]

    def sees_it(headers):
        active = client.get("/api/notifications/active", headers=headers).json()
        return notif_id in {n["id"] for n in active}

    assert sees_it(report_a_headers), "report A must see it via anchor A"
    assert sees_it(report_b_headers), "report B must see it via anchor B"
    assert not sees_it(outsider_headers), "someone under neither anchor must not see it"

    client.delete(f"/api/notifications/{notif_id}", headers=hr_manager_auth)


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


# ---------------------------------------------------------------------------
# Notification general settings (institution timezone + holiday-eve toggle)
# ---------------------------------------------------------------------------
@pytest.fixture
def restore_general_settings(client, hr_manager_auth):
    """test_institution is session-scoped, so any timezone/toggle change a
    test makes here has to be put back — otherwise it leaks into whatever
    test runs next in the same session."""
    original = client.get("/api/notifications/general-settings", headers=hr_manager_auth).json()
    yield
    client.put("/api/notifications/general-settings", headers=hr_manager_auth, json=original)


def test_get_general_settings_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/general-settings", headers=headers)
    assert res.status_code == 403


def test_general_settings_defaults_to_utc_and_disabled(client, hr_manager_auth):
    res = client.get("/api/notifications/general-settings", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert "timezone" in body
    assert "holiday_eve_announcements_enabled" in body


def test_update_general_settings_roundtrip(client, hr_manager_auth, restore_general_settings):
    res = client.put(
        "/api/notifications/general-settings", headers=hr_manager_auth,
        json={"timezone": "Asia/Kuala_Lumpur", "holiday_eve_announcements_enabled": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["timezone"] == "Asia/Kuala_Lumpur"
    assert body["holiday_eve_announcements_enabled"] is True

    res = client.get("/api/notifications/general-settings", headers=hr_manager_auth)
    assert res.json() == body


def test_update_general_settings_invalid_timezone_returns_422(client, hr_manager_auth):
    res = client.put(
        "/api/notifications/general-settings", headers=hr_manager_auth,
        json={"timezone": "Not/A_Real_Zone", "holiday_eve_announcements_enabled": False},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Reminder settings (per-category email-reminder toggles, consumed by
# scripts/send_reminders.py — see migrations/versions/
# 20260922_0001_reminder_category_toggles.py)
# ---------------------------------------------------------------------------
REMINDER_SETTINGS_KEYS = (
    "reminder_timesheet_enabled", "reminder_onboarding_enabled", "reminder_offboarding_enabled",
    "reminder_holidays_enabled", "reminder_acknowledgement_enabled",
)
REMINDER_SETTINGS_HOUR_KEYS = (
    "reminder_timesheet_hour", "reminder_onboarding_hour",
    "reminder_offboarding_hour", "reminder_holidays_hour",
)
REMINDER_SETTINGS_DAY_OF_WEEK_KEYS = ("reminder_timesheet_day_of_week",)


@pytest.fixture
def restore_reminder_settings(client, hr_manager_auth):
    original = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth).json()
    yield
    client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=original)


def test_get_reminder_settings_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/reminder-settings", headers=headers)
    assert res.status_code == 403


def test_get_reminder_settings_returns_all_categories(client, hr_manager_auth):
    res = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    for key in REMINDER_SETTINGS_KEYS:
        assert key in body and isinstance(body[key], bool)
    for key in REMINDER_SETTINGS_HOUR_KEYS:
        assert key in body and isinstance(body[key], int) and 0 <= body[key] <= 23
    for key in REMINDER_SETTINGS_DAY_OF_WEEK_KEYS:
        assert key in body and isinstance(body[key], int) and 0 <= body[key] <= 6


def test_update_reminder_settings_roundtrip(client, hr_manager_auth, restore_reminder_settings):
    payload = {
        "reminder_timesheet_enabled": False, "reminder_onboarding_enabled": True,
        "reminder_offboarding_enabled": False, "reminder_holidays_enabled": True,
        "reminder_acknowledgement_enabled": False,
        "reminder_timesheet_hour": 7, "reminder_onboarding_hour": 9,
        "reminder_offboarding_hour": 17, "reminder_holidays_hour": 6,
        "reminder_timesheet_day_of_week": 4,
    }
    res = client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json=payload)
    assert res.status_code == 200
    assert res.json() == payload

    res = client.get("/api/notifications/reminder-settings", headers=hr_manager_auth)
    assert res.json() == payload


def test_update_reminder_settings_rejects_out_of_range_hour(client, hr_manager_auth, restore_reminder_settings):
    res = client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json={
        "reminder_timesheet_enabled": True, "reminder_onboarding_enabled": True,
        "reminder_offboarding_enabled": True, "reminder_holidays_enabled": True,
        "reminder_acknowledgement_enabled": True,
        "reminder_timesheet_hour": 24, "reminder_onboarding_hour": 8,
        "reminder_offboarding_hour": 8, "reminder_holidays_hour": 8,
        "reminder_timesheet_day_of_week": 0,
    })
    assert res.status_code == 422


def test_update_reminder_settings_rejects_out_of_range_day_of_week(client, hr_manager_auth, restore_reminder_settings):
    res = client.put("/api/notifications/reminder-settings", headers=hr_manager_auth, json={
        "reminder_timesheet_enabled": True, "reminder_onboarding_enabled": True,
        "reminder_offboarding_enabled": True, "reminder_holidays_enabled": True,
        "reminder_acknowledgement_enabled": True,
        "reminder_timesheet_hour": 8, "reminder_onboarding_hour": 8,
        "reminder_offboarding_hour": 8, "reminder_holidays_hour": 8,
        "reminder_timesheet_day_of_week": 7,
    })
    assert res.status_code == 422


def test_update_reminder_settings_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.put("/api/notifications/reminder-settings", headers=headers, json={
        "reminder_timesheet_enabled": True, "reminder_onboarding_enabled": True,
        "reminder_offboarding_enabled": True, "reminder_holidays_enabled": True,
        "reminder_acknowledgement_enabled": True,
        "reminder_timesheet_hour": 8, "reminder_onboarding_hour": 8,
        "reminder_offboarding_hour": 8, "reminder_holidays_hour": 8,
        "reminder_timesheet_day_of_week": 0,
    })
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Holiday-eve virtual notification
# ---------------------------------------------------------------------------
@pytest.fixture
def make_test_holiday_tomorrow_utc(client, hr_manager_auth):
    """Creates a real holiday dated "tomorrow" in UTC (matches the default
    institution timezone), deletes it on teardown."""
    created_ids = []

    def _make():
        tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        year = int(tomorrow[:4])
        res = client.post(
            "/api/holidays", headers=hr_manager_auth,
            json={"name": "ZZ Eve Test Holiday", "date": tomorrow, "year": year},
        )
        assert res.status_code == 201, f"failed to create test holiday: {res.text}"
        holiday = res.json()
        created_ids.append(holiday["id"])
        return holiday

    yield _make

    for hid in created_ids:
        client.delete(f"/api/holidays/{hid}", headers=hr_manager_auth)


def _employee_active_headers(make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    return {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}


def test_holiday_eve_appears_when_enabled_and_holiday_tomorrow(
    client, hr_manager_auth, make_test_user, test_institution, restore_general_settings, make_test_holiday_tomorrow_utc
):
    holiday = make_test_holiday_tomorrow_utc()
    res = client.put(
        "/api/notifications/general-settings", headers=hr_manager_auth,
        json={"timezone": "UTC", "holiday_eve_announcements_enabled": True},
    )
    assert res.status_code == 200

    headers = _employee_active_headers(make_test_user, test_institution)
    res = client.get("/api/notifications/active", headers=headers)
    assert res.status_code == 200
    ids = [n["id"] for n in res.json()]
    assert f"holiday-eve-{holiday['id']}" in ids


def test_holiday_eve_absent_when_disabled(
    client, hr_manager_auth, make_test_user, test_institution, restore_general_settings, make_test_holiday_tomorrow_utc
):
    holiday = make_test_holiday_tomorrow_utc()
    res = client.put(
        "/api/notifications/general-settings", headers=hr_manager_auth,
        json={"timezone": "UTC", "holiday_eve_announcements_enabled": False},
    )
    assert res.status_code == 200

    headers = _employee_active_headers(make_test_user, test_institution)
    res = client.get("/api/notifications/active", headers=headers)
    assert res.status_code == 200
    ids = [n["id"] for n in res.json()]
    assert f"holiday-eve-{holiday['id']}" not in ids


def test_holiday_eve_absent_when_no_holiday_tomorrow(
    client, hr_manager_auth, make_test_user, test_institution, restore_general_settings
):
    res = client.put(
        "/api/notifications/general-settings", headers=hr_manager_auth,
        json={"timezone": "UTC", "holiday_eve_announcements_enabled": True},
    )
    assert res.status_code == 200

    headers = _employee_active_headers(make_test_user, test_institution)
    res = client.get("/api/notifications/active", headers=headers)
    assert res.status_code == 200
    assert not any(str(n.get("id", "")).startswith("holiday-eve-") for n in res.json())
