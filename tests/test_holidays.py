"""
Integration tests for routers/holidays.py — hits the real app and real DB
(see conftest.py's test_institution fixture) using disposable, zz-prefixed
data. Unlike employees, holidays have a real delete endpoint, so cleanup
deletes rather than deactivates.
"""
import itertools
import random

import pytest

_year_counter = itertools.count(1)
_year_salt = 2100 + random.randint(0, 800)  # far-future year, unlikely to collide with real data


def _unique_year():
    """A distinct year per call so date-uniqueness constraints across tests
    (and across separate test runs) never collide."""
    return _year_salt + next(_year_counter)


@pytest.fixture
def make_test_holiday(client, hr_manager_auth):
    """Factory: creates a disposable holiday, deletes it on teardown (any
    not already deleted by the test itself)."""
    created_ids = []

    def _make(**overrides):
        year = _unique_year()
        payload = {"name": "ZZ Test Holiday", "date": f"{year}-01-01", "year": year}
        payload.update(overrides)
        res = client.post("/api/holidays", headers=hr_manager_auth, json=payload)
        assert res.status_code == 201, f"failed to create test holiday: {res.text}"
        holiday = res.json()
        created_ids.append(holiday["id"])
        return holiday

    yield _make

    for hid in created_ids:
        client.delete(f"/api/holidays/{hid}", headers=hr_manager_auth)


# ---------------------------------------------------------------------------
# Auth / permissions
# ---------------------------------------------------------------------------
def test_list_holidays_requires_auth(client):
    res = client.get("/api/holidays")
    assert res.status_code in (401, 403)


def test_create_holiday_requires_manage_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/holidays", headers=headers, json={"name": "ZZ", "date": "2100-01-01", "year": 2100})
    assert res.status_code == 403


def test_delete_holiday_requires_manage_role(client, make_test_user, test_institution, make_test_holiday):
    holiday = make_test_holiday()
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.delete(f"/api/holidays/{holiday['id']}", headers=headers)
    assert res.status_code == 403


def test_list_holidays_readable_by_plain_employee(client, make_test_user, test_institution):
    """Listing has no require_roles guard — only get_current_user."""
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/holidays", headers=headers)
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def test_create_holiday_success(client, hr_manager_auth, make_test_holiday):
    holiday = make_test_holiday(name="ZZ New Year")
    assert holiday["name"] == "ZZ New Year"
    assert holiday["institution_id"]


def test_create_holiday_missing_field_returns_422(client, hr_manager_auth):
    res = client.post("/api/holidays", headers=hr_manager_auth, json={"name": "ZZ"})
    assert res.status_code == 422


def test_create_holiday_duplicate_date_returns_400(client, hr_manager_auth, make_test_holiday):
    holiday = make_test_holiday()
    dup = client.post(
        "/api/holidays", headers=hr_manager_auth,
        json={"name": "ZZ Duplicate", "date": holiday["date"], "year": holiday["year"]},
    )
    assert dup.status_code == 400
    assert "already exists" in dup.json()["detail"]


# ---------------------------------------------------------------------------
# List / filter
# ---------------------------------------------------------------------------
def test_list_holidays_includes_created_holiday(client, hr_manager_auth, make_test_holiday):
    holiday = make_test_holiday()
    res = client.get("/api/holidays", headers=hr_manager_auth)
    assert res.status_code == 200
    assert holiday["id"] in [h["id"] for h in res.json()]


def test_list_holidays_filters_by_year(client, hr_manager_auth, make_test_holiday):
    holiday = make_test_holiday()
    other_year = holiday["year"] + 500  # guaranteed no other holiday exists in this year
    res = client.get("/api/holidays", headers=hr_manager_auth, params={"year": other_year})
    assert res.status_code == 200
    assert holiday["id"] not in [h["id"] for h in res.json()]

    res = client.get("/api/holidays", headers=hr_manager_auth, params={"year": holiday["year"]})
    assert res.status_code == 200
    assert holiday["id"] in [h["id"] for h in res.json()]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
def test_delete_holiday_success(client, hr_manager_auth, make_test_holiday):
    holiday = make_test_holiday()
    res = client.delete(f"/api/holidays/{holiday['id']}", headers=hr_manager_auth)
    assert res.status_code == 204

    listed = client.get("/api/holidays", headers=hr_manager_auth).json()
    assert holiday["id"] not in [h["id"] for h in listed]


def test_delete_nonexistent_holiday_is_a_no_op(client, hr_manager_auth):
    """delete_holiday has no existence check — deleting a nonexistent id is
    idempotent, not a 404."""
    res = client.delete("/api/holidays/999999999", headers=hr_manager_auth)
    assert res.status_code == 204
