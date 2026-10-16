"""Claude self-service: who else is on leave (routers/me_leave.py). Names and dates of APPROVED leave only, never the type."""
from datetime import date, timedelta

import pytest

MON = date(2031, 3, 3)          # a Monday, far enough out to be clear of every other test's leave


def d(offset):
    return (MON + timedelta(days=offset)).isoformat()


@pytest.fixture
def approved_type(make_test_leave_type):
    return make_test_leave_type(name="ZZ Secret Medical Leave", requires_approval=False, annual_entitlement=40)


def _book(client, headers, emp, lt, start, end, **extra):
    res = client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"], "start_date": start, "end_date": end, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def names(day):
    return [p["full_name"] for p in day["on_leave"]]


def test_lists_colleagues_on_approved_leave_and_never_the_leave_type(client, employee_with_login, approved_type):
    me, my_headers = employee_with_login(full_name="ZZ Leave Viewer")
    amy, amy_headers = employee_with_login(full_name="ZZ Leave Amy")
    ben, ben_headers = employee_with_login(full_name="ZZ Leave Ben")
    _book(client, amy_headers, amy, approved_type, d(1), d(2))      # Tue-Wed
    _book(client, ben_headers, ben, approved_type, d(2), d(2))      # Wed only
    _book(client, my_headers, me, approved_type, d(1), d(1))        # the viewer's own leave is left out

    res = client.get("/api/me/leave-colleagues", headers=my_headers, params={"date": d(1), "end_date": d(2)})
    assert res.status_code == 200, res.text
    body = res.json()
    tue, wed = body["days"]
    assert names(tue) == ["ZZ Leave Amy"] and names(wed) == ["ZZ Leave Amy", "ZZ Leave Ben"]
    assert tue["weekday"] == "Tue" and tue["non_working_day"] is None
    text = res.text
    assert "Secret Medical" not in text and "leave_type" not in text and "ZZ Leave Viewer" not in text


def test_single_day_default_shape(client, employee_with_login, approved_type):
    _, headers = employee_with_login(full_name="ZZ Leave Solo")
    one = client.get("/api/me/leave-colleagues", headers=headers, params={"date": d(0)}).json()
    assert one["from"] == one["to"] == d(0) and len(one["days"]) == 1
    today = client.get("/api/me/leave-colleagues", headers=headers).json()      # no date = today
    assert len(today["days"]) == 1


def test_pending_leave_is_not_shown(client, employee_with_login, make_test_leave_type):
    _, headers = employee_with_login(full_name="ZZ Leave Pending Viewer")
    pending_type = make_test_leave_type(name="ZZ Needs Approval", requires_approval=True, annual_entitlement=40)
    amy, amy_headers = employee_with_login(full_name="ZZ Leave Pending Amy")
    app = _book(client, amy_headers, amy, pending_type, d(1), d(1))
    assert app["status"] != "Approved"
    day = client.get("/api/me/leave-colleagues", headers=headers, params={"date": d(1)}).json()["days"][0]
    assert "ZZ Leave Pending Amy" not in names(day)


def test_half_days_are_marked(client, employee_with_login, approved_type):
    _, headers = employee_with_login(full_name="ZZ Leave Half Viewer")
    amy, amy_headers = employee_with_login(full_name="ZZ Leave Half Amy")
    _book(client, amy_headers, amy, approved_type, d(1), d(1), start_day_period="AM")
    day = client.get("/api/me/leave-colleagues", headers=headers, params={"date": d(1)}).json()["days"][0]
    assert [(p["full_name"], p["half_day"]) for p in day["on_leave"]] == [("ZZ Leave Half Amy", "morning")]


def test_weekends_and_public_holidays_list_nobody(client, hr_manager_auth, employee_with_login, make_test_leave_type):
    _, headers = employee_with_login(full_name="ZZ Leave Cal Viewer")
    cal_type = make_test_leave_type(name="ZZ Calendar Days Leave", requires_approval=False, annual_entitlement=40, count_calendar_days=True)
    amy, amy_headers = employee_with_login(full_name="ZZ Leave Cal Amy")
    _book(client, amy_headers, amy, cal_type, d(4), d(7))             # Fri to Mon, spanning the weekend
    hol = client.post("/api/holidays", headers=hr_manager_auth, json={"name": "ZZ Test Day", "date": d(7), "year": 2031})
    assert hol.status_code == 201, hol.text
    try:
        days = client.get("/api/me/leave-colleagues", headers=headers, params={"date": d(4), "end_date": d(7)}).json()["days"]
        fri, sat, sun, mon = days
        assert names(fri) == ["ZZ Leave Cal Amy"]
        assert sat["non_working_day"] == "Weekend" and sat["on_leave"] == [] and sun["on_leave"] == []
        assert mon["non_working_day"] == "Public holiday: ZZ Test Day" and mon["on_leave"] == []
    finally:
        client.delete(f"/api/holidays/{hol.json()['id']}", headers=hr_manager_auth)


def test_department_filter(client, employee_with_login, approved_type):
    _, headers = employee_with_login(full_name="ZZ Leave Dept Viewer", department="Ops")
    amy, amy_headers = employee_with_login(full_name="ZZ Leave Dept Amy", department="Sales")
    ben, ben_headers = employee_with_login(full_name="ZZ Leave Dept Ben", department="Ops")
    _book(client, amy_headers, amy, approved_type, d(1), d(1))
    _book(client, ben_headers, ben, approved_type, d(1), d(1))
    allp = client.get("/api/me/leave-colleagues", headers=headers, params={"date": d(1)}).json()["days"][0]
    assert {"ZZ Leave Dept Amy", "ZZ Leave Dept Ben"} <= set(names(allp))
    sales = client.get("/api/me/leave-colleagues", headers=headers, params={"date": d(1), "department": "sales"}).json()
    assert sales["department"] == "sales" and names(sales["days"][0]) == ["ZZ Leave Dept Amy"]
    assert [p["department"] for p in sales["days"][0]["on_leave"]] == ["Sales"]


@pytest.mark.parametrize("params,fragment", [
    ({"date": "nope"}, "Dates must look like"),
    ({"date": "2031-03-05", "end_date": "2031-03-03"}, "before"),
    ({"date": "2031-03-01", "end_date": "2031-05-01"}, "at most 31"),
])
def test_bad_ranges(client, employee_with_login, params, fragment):
    _, headers = employee_with_login(full_name="ZZ Leave Range")
    res = client.get("/api/me/leave-colleagues", headers=headers, params=params)
    assert res.status_code == 400 and fragment in res.json()["detail"]


def test_needs_a_linked_employee(client, make_test_user):
    token, _ = make_test_user(role="hr_manager")
    res = client.get("/api/me/leave-colleagues", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400 and "employee record" in res.json()["detail"]


def test_requires_login(client):
    assert client.get("/api/me/leave-colleagues").status_code in (401, 403)


# --------------------------------------------------------------------------- public holidays
@pytest.fixture
def three_holidays(client, hr_manager_auth):
    ids = []
    for offset, name in ((10, "ZZ Hol A"), (20, "ZZ Hol B"), (30, "ZZ Hol C")):
        res = client.post("/api/holidays", headers=hr_manager_auth, json={"name": name, "date": d(offset), "year": 2031})
        assert res.status_code == 201, res.text
        ids.append(res.json()["id"])
    yield
    for i in ids:
        client.delete(f"/api/holidays/{i}", headers=hr_manager_auth)


def test_next_public_holidays_and_range(client, employee_with_login, three_holidays):
    _, headers = employee_with_login(full_name="ZZ Hol Viewer")
    nxt = client.get("/api/me/public-holidays", headers=headers, params={"date": d(0), "limit": 2}).json()
    assert [h["name"] for h in nxt["holidays"]] == ["ZZ Hol A", "ZZ Hol B"]
    assert nxt["holidays"][0]["days_from_start"] == 10 and nxt["holidays"][0]["weekday"] == (MON + timedelta(days=10)).strftime("%a")
    rng = client.get("/api/me/public-holidays", headers=headers, params={"date": d(15), "end_date": d(30)}).json()
    assert [h["name"] for h in rng["holidays"]] == ["ZZ Hol B", "ZZ Hol C"] and rng["to"] == d(30)


def test_is_that_day_a_public_holiday(client, employee_with_login, three_holidays):
    _, headers = employee_with_login(full_name="ZZ Hol Check")
    yes = client.get("/api/me/public-holidays", headers=headers, params={"date": d(20), "end_date": d(20)}).json()
    assert [h["name"] for h in yes["holidays"]] == ["ZZ Hol B"]
    no = client.get("/api/me/public-holidays", headers=headers, params={"date": d(21), "end_date": d(21)}).json()
    assert no["holidays"] == []


def test_public_holidays_defaults_and_bad_input(client, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ Hol Defaults")
    ok = client.get("/api/me/public-holidays", headers=headers)
    assert ok.status_code == 200 and len(ok.json()["holidays"]) <= 5
    assert len(client.get("/api/me/public-holidays", headers=headers, params={"limit": 500}).json()["holidays"]) <= 50
    assert client.get("/api/me/public-holidays", headers=headers, params={"date": "nope"}).status_code == 400
    assert client.get("/api/me/public-holidays", headers=headers, params={"date": "2031-03-05", "end_date": "2031-03-01"}).status_code == 400
    assert client.get("/api/me/public-holidays").status_code in (401, 403)
