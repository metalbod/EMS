"""Who may use a leave type: the rule function (pure), and every place the API enforces it (core/leave_eligibility.py)."""
import os
from datetime import date, timedelta

import pytest

from conftest import company_today
from core.leave_eligibility import add_months, eligible_from, has_rules, ineligible_reason, is_eligible, rule_badges

# ---------------------------------------------------------------------------------------------------------------------
# the rule function, no database
# ---------------------------------------------------------------------------------------------------------------------
def T(gender="Any", married=0, months=0):
    return {"eligible_gender": gender, "require_married": married, "min_service_months": months}


def E(gender="Female", marital="Single", start="2020-01-01"):
    return {"gender": gender, "marital_status": marital, "start_date": start}


ON = date(2026, 10, 24)


def test_no_conditions_means_everyone():
    assert not has_rules(T())
    assert is_eligible(T(), E(gender=None, marital=None, start=None), ON)


@pytest.mark.parametrize("lt,emp,why", [
    (T("Female"), E("Female"), None),
    (T("Female"), E("Male"), "for female staff only"),
    (T("Male"), E("Male"), None),
    (T("Male"), E("Female"), "for male staff only"),
    (T("Female"), E(None), "for female staff only"),                      # nothing on file counts as not matching
    (T(married=1), E(marital="Married"), None),
    (T(married=1), E(marital="Single"), "for married staff only"),
    (T(married=1), E(marital="Divorced"), "for married staff only"),
    (T("Male", 1, 12), E("Male", "Married", "2025-10-24"), None),         # exactly 12 months on the day
    (T("Male", 1, 12), E("Male", "Married", "2025-10-25"), "only after 12 months of service (from 25-Oct-2026)"),
    (T("Male", 1, 12), E("Female", "Married", "2020-01-01"), "for male staff only"),   # gender is judged before the others
    (T("Male", 1, 12), E("Male", "Single", "2020-01-01"), "for married staff only"),
    (T(months=6), E(start=None), "only after 6 months of service (no start date on file)"),
    (T(months=1), E(start="2026-09-24"), None),
    (T(months=1), E(start="2026-09-25"), "only after 1 month of service (from 25-Oct-2026)"),
])
def test_rules(lt, emp, why):
    assert ineligible_reason(lt, emp, ON) == why
    assert is_eligible(lt, emp, ON) is (why is None)


def test_service_is_judged_on_the_leave_start_date_not_today():
    lt, emp = T(months=12), E(start="2026-01-01")
    assert not is_eligible(lt, emp, date(2026, 10, 24))
    assert is_eligible(lt, emp, date(2027, 1, 1))       # leave booked for a date after they qualify
    assert not is_eligible(lt, emp, date(2026, 12, 31))
    assert eligible_from(lt, emp) == date(2027, 1, 1)
    assert eligible_from(T(), emp) is None


def test_an_exception_beats_the_rules_either_way():
    lt, male = T("Female"), E("Male")
    assert is_eligible(lt, male, ON, override={"allowed": 1})
    assert ineligible_reason(T("Any"), E("Female"), ON, override={"allowed": 0}) == "HR has withheld it"
    assert not is_eligible(T("Female"), E("Female"), ON, override={"allowed": 0})


def test_add_months_clamps_a_short_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 12, 15), 12) == date(2027, 12, 15)


def test_badges():
    assert rule_badges(T()) == []
    assert rule_badges(T("Female", 0, 0)) == ["Female only"]
    assert rule_badges(T("Male", 1, 12)) == ["Male only", "Married", "12+ months"]


# ---------------------------------------------------------------------------------------------------------------------
# the API
# ---------------------------------------------------------------------------------------------------------------------
def _login(client, hr, code, emp, label):
    username = f"zzelig_{label}_{os.urandom(3).hex()}"
    r = client.post("/api/users", headers=hr, json={"username": username, "full_name": f"ZZ Elig {label}", "password": "ZzPytest@123",
                                                    "role": "employee", "employee_id": emp["employee_id"]})
    assert r.status_code == 201, r.text
    lg = client.post("/api/auth/login", json={"username": username, "password": "ZzPytest@123", "institution_code": code})
    assert lg.status_code == 200, lg.text
    return r.json()["id"], {"Authorization": f"Bearer {lg.json()['access_token']}"}


@pytest.fixture
def staff(client, hr_manager_auth, test_institution, make_test_employee):
    """A woman, a man, a married man with 13 months' service, a married man with 6 months, each with a login."""
    today = company_today(client, hr_manager_auth)
    old = (today - timedelta(days=800)).isoformat()
    made = {
        "woman": make_test_employee(gender="Female", marital_status="Single", start_date=old),
        "man": make_test_employee(gender="Male", marital_status="Single", start_date=old),
        "dad": make_test_employee(gender="Male", marital_status="Married", start_date=(today - timedelta(days=400)).isoformat()),
        "newdad": make_test_employee(gender="Male", marital_status="Married", start_date=(today - timedelta(days=180)).isoformat()),
    }
    ids, heads = [], {}
    for k, e in made.items():
        uid, h = _login(client, hr_manager_auth, test_institution["code"], e, k)
        ids.append(uid); heads[k] = h
    yield made, heads
    for uid in ids:
        client.delete(f"/api/users/{uid}", headers=hr_manager_auth)


@pytest.fixture
def maternity(make_test_leave_type):
    return make_test_leave_type(name=f"ZZ Maternity {os.urandom(2).hex()}", annual_entitlement=98, eligible_gender="Female", count_calendar_days=True)


@pytest.fixture
def paternity(make_test_leave_type):
    return make_test_leave_type(name=f"ZZ Paternity {os.urandom(2).hex()}", annual_entitlement=7, eligible_gender="Male", require_married=True,
                                min_service_months=12, count_calendar_days=True)


def names(rows):
    return {r["name"] for r in rows}


def balance_names(client, headers, **params):
    r = client.get("/api/leave/balances", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return {b["leave_type_name"] for b in r.json()}


def test_a_type_without_rules_is_open_to_everyone_as_before(client, staff, make_test_leave_type):
    made, heads = staff
    lt = make_test_leave_type(name=f"ZZ Open {os.urandom(2).hex()}")
    assert lt["eligible_gender"] == "Any" and lt["require_married"] == 0 and lt["min_service_months"] == 0
    for h in heads.values():
        assert lt["name"] in names(client.get("/api/leave/types", headers=h).json())


def test_types_list_is_filtered_per_person_and_complete_for_admin(client, hr_manager_auth, staff, maternity, paternity):
    made, heads = staff
    woman = names(client.get("/api/leave/types", headers=heads["woman"]).json())
    man = names(client.get("/api/leave/types", headers=heads["man"]).json())
    dad = names(client.get("/api/leave/types", headers=heads["dad"]).json())
    newdad = names(client.get("/api/leave/types", headers=heads["newdad"]).json())
    assert maternity["name"] in woman and paternity["name"] not in woman
    assert maternity["name"] not in man and paternity["name"] not in man          # single man: not married
    assert paternity["name"] in dad and maternity["name"] not in dad
    assert paternity["name"] not in newdad                                       # under 12 months today
    # HR applying for someone sees that person's list; with no employee it is the full admin list, with badges
    for_dad = client.get("/api/leave/types", headers=hr_manager_auth, params={"employee_id": made["dad"]["employee_id"]}).json()
    assert paternity["name"] in names(for_dad) and maternity["name"] not in names(for_dad)
    full = {r["name"]: r for r in client.get("/api/leave/types", headers=hr_manager_auth).json()}
    assert maternity["name"] in full and paternity["name"] in full
    assert full[maternity["name"]]["eligibility_badges"] == ["Female only"]
    assert full[paternity["name"]]["eligibility_badges"] == ["Male only", "Married", "12+ months"]


def test_balances_show_and_create_only_what_a_person_may_use(client, hr_manager_auth, staff, maternity, paternity):
    made, heads = staff
    assert maternity["name"] in balance_names(client, heads["woman"])
    assert maternity["name"] not in balance_names(client, heads["man"])
    assert paternity["name"] in balance_names(client, heads["dad"])
    assert paternity["name"] not in balance_names(client, heads["newdad"])
    # no row was ever created for the people it isn't for, even for HR who can ask for ineligible ones too
    everything = balance_names(client, hr_manager_auth, employee_id=made["man"]["employee_id"], include_ineligible=True)
    assert maternity["name"] not in everything and paternity["name"] not in everything
    # HR looking at one person sees what that person sees
    assert maternity["name"] not in balance_names(client, hr_manager_auth, employee_id=made["man"]["employee_id"])
    assert maternity["name"] in balance_names(client, hr_manager_auth, employee_id=made["woman"]["employee_id"])


def apply(client, headers, emp, lt, start="2027-03-01", end="2027-03-02"):
    return client.post("/api/leave/applications", headers=headers, json={
        "employee_id": emp["employee_id"], "leave_type_id": lt["id"], "start_date": start, "end_date": end})


def test_applying_is_refused_server_side_with_a_plain_reason(client, hr_manager_auth, staff, maternity, paternity):
    made, heads = staff
    mine = apply(client, heads["man"], made["man"], maternity)
    assert mine.status_code == 403 and "isn't available to you" in mine.json()["detail"] and "for female staff only" in mine.json()["detail"]
    onbehalf = apply(client, hr_manager_auth, made["man"], maternity)
    assert onbehalf.status_code == 403 and "isn't available to this employee" in onbehalf.json()["detail"]
    single = apply(client, heads["man"], made["man"], paternity)
    assert single.status_code == 403 and "for married staff only" in single.json()["detail"]
    new = apply(client, heads["newdad"], made["newdad"], paternity)
    assert new.status_code == 403 and "only after 12 months of service (from " in new.json()["detail"]
    assert apply(client, heads["woman"], made["woman"], maternity).status_code == 201
    assert apply(client, heads["dad"], made["dad"], paternity).status_code == 201


def test_a_hr_exception_overrides_the_rules_and_can_be_removed(client, hr_manager_auth, staff, maternity):
    made, heads = staff
    man = made["man"]["employee_id"]
    url = f"/api/leave/types/{maternity['id']}/overrides/{man}"
    assert client.put(url, headers=hr_manager_auth, json={"allowed": True, "reason": "x"}).status_code == 422       # a reason is required
    ok = client.put(url, headers=hr_manager_auth, json={"allowed": True, "reason": "Adopting a newborn"})
    assert ok.status_code == 200, ok.text
    assert maternity["name"] in names(client.get("/api/leave/types", headers=heads["man"]).json())
    assert maternity["name"] in balance_names(client, heads["man"])
    assert apply(client, heads["man"], made["man"], maternity).status_code == 201
    listed = client.get(f"/api/leave/types/{maternity['id']}/overrides", headers=hr_manager_auth).json()
    assert [(o["employee_id"], o["allowed"], o["reason"]) for o in listed] == [(man, True, "Adopting a newborn")]
    assert client.delete(url, headers=hr_manager_auth).status_code == 204
    assert maternity["name"] not in names(client.get("/api/leave/types", headers=heads["man"]).json())
    assert client.get(f"/api/leave/types/{maternity['id']}/overrides", headers=hr_manager_auth).json() == []


def test_a_withholding_exception_beats_a_matching_rule(client, hr_manager_auth, staff, maternity):
    made, heads = staff
    woman = made["woman"]["employee_id"]
    assert client.put(f"/api/leave/types/{maternity['id']}/overrides/{woman}", headers=hr_manager_auth, json={"allowed": False, "reason": "Not entitled under contract"}).status_code == 200
    assert maternity["name"] not in names(client.get("/api/leave/types", headers=heads["woman"]).json())
    r = apply(client, heads["woman"], made["woman"], maternity)
    assert r.status_code == 403 and "HR has withheld it" in r.json()["detail"]


def test_exceptions_need_the_manage_leave_types_permission_and_a_real_person(client, hr_manager_auth, staff, maternity):
    made, heads = staff
    woman = made["woman"]["employee_id"]
    assert client.get(f"/api/leave/types/{maternity['id']}/overrides", headers=heads["woman"]).status_code == 403
    assert client.put(f"/api/leave/types/{maternity['id']}/overrides/{woman}", headers=heads["woman"], json={"allowed": True, "reason": "self-serve"}).status_code == 403
    assert client.put(f"/api/leave/types/{maternity['id']}/overrides/EMP-NOPE", headers=hr_manager_auth, json={"allowed": True, "reason": "ghost"}).status_code == 404
    assert client.put(f"/api/leave/types/2147483000/overrides/{woman}", headers=hr_manager_auth, json={"allowed": True, "reason": "none"}).status_code == 404
    assert client.post("/api/leave/types/eligibility-preview", headers=heads["woman"], json={}).status_code == 403


def test_a_rule_added_later_hides_balances_but_keeps_them(client, hr_manager_auth, staff, make_test_leave_type):
    made, heads = staff
    lt = make_test_leave_type(name=f"ZZ Later {os.urandom(2).hex()}")
    assert lt["name"] in balance_names(client, heads["man"])                      # open: a balance row is created
    body = {k: lt[k] for k in ("name", "annual_entitlement", "requires_approval", "requires_attachment", "is_paid", "is_active", "count_calendar_days", "allow_half_day")}
    assert client.put(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth, json={**body, "eligible_gender": "Female"}).status_code == 200
    assert lt["name"] not in balance_names(client, heads["man"])                  # hidden…
    assert lt["name"] in balance_names(client, hr_manager_auth, employee_id=made["man"]["employee_id"], include_ineligible=True)   # …but kept
    assert client.put(f"/api/leave/types/{lt['id']}", headers=hr_manager_auth, json={**body, "eligible_gender": "Any"}).status_code == 200
    assert lt["name"] in balance_names(client, heads["man"])                      # and back


def test_a_type_that_shares_a_pool_keeps_the_owners_card_for_the_eligible_person(client, hr_manager_auth, staff, make_test_leave_type):
    made, heads = staff
    owner = make_test_leave_type(name=f"ZZ Pool {os.urandom(2).hex()}", annual_entitlement=20, eligible_gender="Female")
    sub = make_test_leave_type(name=f"ZZ Pool Sub {os.urandom(2).hex()}", annual_entitlement=5, shares_entitlement_with_id=owner["id"], eligible_gender="Any")
    # the man may use the sub-type, which draws on the owner's balance, so the owner's card stays visible for him; the woman sees both
    assert owner["name"] in balance_names(client, heads["man"])
    assert apply(client, heads["man"], made["man"], sub).status_code in (201, 400)    # eligibility passes (the balance check is a different rule)
    assert owner["name"] in balance_names(client, heads["woman"])


def test_overtime_cannot_be_credited_to_a_restricted_type_and_vice_versa(client, hr_manager_auth, maternity, make_test_leave_type):
    mode = client.get("/api/overtime/settings", headers=hr_manager_auth).json()
    r = client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "leave", "overtime_leave_type_id": maternity["id"], "overtime_pay_multiplier": 1.5})
    assert r.status_code == 400 and "open to everyone" in r.json()["detail"]
    open_lt = make_test_leave_type(name=f"ZZ OT Credit {os.urandom(2).hex()}")
    try:
        ok = client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "leave", "overtime_leave_type_id": open_lt["id"], "overtime_pay_multiplier": 1.5})
        assert ok.status_code == 200, ok.text
        body = {k: open_lt[k] for k in ("name", "annual_entitlement", "requires_approval", "requires_attachment", "is_paid", "is_active", "count_calendar_days", "allow_half_day")}
        blocked = client.put(f"/api/leave/types/{open_lt['id']}", headers=hr_manager_auth, json={**body, "eligible_gender": "Male"})
        assert blocked.status_code == 400 and "stay open to everyone" in blocked.json()["detail"]
    finally:
        client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": mode.get("overtime_conversion_mode", "pay"),
                                                                            "overtime_leave_type_id": mode.get("overtime_leave_type_id"),
                                                                            "overtime_pay_multiplier": mode.get("overtime_pay_multiplier", 1.5)})


def test_preview_counts_who_a_rule_would_let_in(client, hr_manager_auth, staff):
    made, _ = staff
    # The shared company gains employees from tests running in parallel, so only compare numbers inside ONE response.
    def preview(**rule):
        return client.post("/api/leave/types/eligibility-preview", headers=hr_manager_auth, json=rule).json()
    base = preview()
    assert base["eligible"] == base["total"] >= 4
    women, men = preview(eligible_gender="Female"), preview(eligible_gender="Male")
    assert 1 <= women["eligible"] < women["total"] and 1 <= men["eligible"] < men["total"]
    dads = preview(eligible_gender="Male", require_married=True, min_service_months=12)
    assert 1 <= dads["eligible"] < dads["total"]
    assert client.post("/api/leave/types/eligibility-preview", headers=hr_manager_auth, json={"eligible_gender": "Other"}).status_code == 422


def test_leave_type_validation(client, hr_manager_auth):
    base = {"name": "ZZ Bad", "annual_entitlement": 1}
    assert client.post("/api/leave/types", headers=hr_manager_auth, json={**base, "eligible_gender": "Robot"}).status_code == 422
    assert client.post("/api/leave/types", headers=hr_manager_auth, json={**base, "min_service_months": -1}).status_code == 422
    assert client.post("/api/leave/types", headers=hr_manager_auth, json={**base, "min_service_months": 999}).status_code == 422


def test_attendance_reclassify_to_an_ineligible_type_is_refused(client, hr_manager_auth, staff, maternity, make_test_leave_type):
    from db import get_admin_db
    made, _ = staff
    emp = made["man"]["employee_id"]
    conn = get_admin_db()
    try:
        inst = conn.execute("SELECT id FROM institutions WHERE code='ZZPYTEST'").fetchone()["id"]
        conn.execute("INSERT INTO attendance_records (institution_id, employee_id, work_date, status, suggested_action, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (inst, emp, "2027-02-02", "Absent (Pending Review)", "Full-Day Absence", "2027-02-02T00:00:00", "2027-02-02T00:00:00"))
        conn.commit()
        rec = conn.execute("SELECT id FROM attendance_records WHERE employee_id=? AND work_date='2027-02-02'", (emp,)).fetchone()["id"]
    finally:
        conn.close()
    r = client.put(f"/api/attendance/records/{rec}/resolve", headers=hr_manager_auth, json={"action": "ReclassifyAsLeave", "leave_type_id": maternity["id"]})
    assert r.status_code == 400 and "isn't available to this employee" in r.json()["detail"]
    open_lt = make_test_leave_type(name=f"ZZ Reclass {os.urandom(2).hex()}")
    ok = client.put(f"/api/attendance/records/{rec}/resolve", headers=hr_manager_auth, json={"action": "ReclassifyAsLeave", "leave_type_id": open_lt["id"]})
    assert ok.status_code == 200, ok.text
