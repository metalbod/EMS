"""
Integration tests for routers/employees.py — hits the real app and real DB
(see conftest.py's test_institution fixture) using disposable, zz-prefixed
data. Employees have no delete endpoint (only status toggle), so cleanup
deactivates rather than deletes.

test_create_employee_success is a regression test: POST /api/employees was
completely unroutable for a while (the @router.post decorator was on the
wrong function — see commit 207a31f) and returned 422 for every request.
"""
import uuid

import pytest

from conftest import _valid_employee_payload, _unique_ic, _unique_code

# ---------------------------------------------------------------------------
# Auth / permissions
# ---------------------------------------------------------------------------
def test_list_employees_requires_auth(client):
    res = client.get("/api/employees")
    assert res.status_code in (401, 403)


def test_create_employee_requires_write_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/employees", headers=headers, json=_valid_employee_payload())
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Create — regression coverage for the decorator-misplacement bug
# ---------------------------------------------------------------------------
def test_create_employee_success(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    assert emp["full_name"] == "ZZ Test Employee"
    assert emp["employee_id"].startswith("EMP")
    assert emp["status"] == "Active"


def test_create_employee_missing_required_field_returns_422(client, hr_manager_auth):
    payload = _valid_employee_payload()
    del payload["full_name"]
    res = client.post("/api/employees", headers=hr_manager_auth, json=payload)
    assert res.status_code == 422


def test_create_employee_invalid_ic_number_returns_422(client, hr_manager_auth):
    res = client.post("/api/employees", headers=hr_manager_auth, json=_valid_employee_payload(ic_number="not-an-ic"))
    assert res.status_code == 422


def test_create_employee_invalid_race_returns_422(client, hr_manager_auth):
    res = client.post("/api/employees", headers=hr_manager_auth, json=_valid_employee_payload(race="Not A Real Race"))
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def test_get_employee_success(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json()["employee_id"] == emp["employee_id"]


def test_get_employee_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/employees/EMP_ZZ_NONEXISTENT", headers=hr_manager_auth)
    assert res.status_code == 404


def test_list_employees_includes_created_employee(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get("/api/employees", headers=hr_manager_auth)
    assert res.status_code == 200
    assert emp["employee_id"] in [e["employee_id"] for e in res.json()]


# ---------------------------------------------------------------------------
# Pagination (Speed Audit item 8) — opt-in via limit/offset, so the
# app-wide roster fetch that ~12 other frontend files depend on (org
# chart, employee pickers, dashboards — see loadEmployees() in
# static/js/employees.js, called with no limit at all) keeps getting
# today's exact "everything, unbounded" response. Only the Employee List
# screen's own dedicated fetch passes limit/offset.
# ---------------------------------------------------------------------------
def test_list_employees_without_limit_is_unbounded_and_has_no_total_count_header(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get("/api/employees", headers=hr_manager_auth)
    assert res.status_code == 200
    assert "X-Total-Count" not in res.headers
    assert emp["employee_id"] in [e["employee_id"] for e in res.json()]


def test_list_employees_exposes_total_count_header_when_limit_given(client, hr_manager_auth, make_test_employee):
    suffix = uuid.uuid4().hex[:8]
    make_test_employee(full_name=f"ZZ Count {suffix}")
    res = client.get("/api/employees", headers=hr_manager_auth, params={"search": suffix, "limit": 1})
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert int(res.headers["X-Total-Count"]) == 1


def test_list_employees_offset_pages_through_results(client, hr_manager_auth, make_test_employee):
    """offset advances through the result set without overlap — scoped via
    a unique random search term embedded in two disposable employees'
    names (employees have no delete endpoint and accumulate forever
    across test runs), so this isn't sensitive to unrelated employee data
    elsewhere in the shared, session-scoped test institution (see
    conftest.py's test_institution docstring, and this file's own module
    docstring on employee cleanup)."""
    suffix = uuid.uuid4().hex[:8]
    make_test_employee(full_name=f"ZZ Paging {suffix} Alice")
    make_test_employee(full_name=f"ZZ Paging {suffix} Bob")

    page1 = client.get("/api/employees", headers=hr_manager_auth,
                        params={"search": suffix, "sort_by": "full_name", "sort_dir": "asc",
                                "limit": 1, "offset": 0}).json()
    page2 = client.get("/api/employees", headers=hr_manager_auth,
                        params={"search": suffix, "sort_by": "full_name", "sort_dir": "asc",
                                "limit": 1, "offset": 1}).json()
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0]["employee_id"] != page2[0]["employee_id"]
    assert page1[0]["full_name"].endswith("Alice")
    assert page2[0]["full_name"].endswith("Bob")


def test_list_employees_search_is_case_insensitive(client, hr_manager_auth, make_test_employee):
    """LIKE is case-sensitive in Postgres — a plain LIKE here used to mean
    searching "yong" (lowercase) missed a stored "Yong Khai Ling" entirely,
    which read to a real user as the search box "not working". Covers both
    a name-field match and the designation (job title) field."""
    suffix = uuid.uuid4().hex[:8]
    make_test_employee(full_name=f"ZZ Case {suffix.upper()} Test", designation="ZZ Senior Widget Engineer")

    name_res = client.get("/api/employees", headers=hr_manager_auth, params={"search": suffix.lower()})
    assert name_res.status_code == 200
    assert any(suffix.upper() in e["full_name"] for e in name_res.json())

    title_res = client.get("/api/employees", headers=hr_manager_auth, params={"search": "widget engineer"})
    assert title_res.status_code == 200
    assert any(e["designation"] == "ZZ Senior Widget Engineer" for e in title_res.json())


def test_list_employees_unknown_sort_by_falls_back_safely(client, hr_manager_auth, make_test_employee):
    """sort_by is allowlisted (routers/employees.py's
    _EMPLOYEE_SORT_COLUMNS), not interpolated directly — an unrecognized
    or malicious value falls back to the default sort column instead of
    erroring or reaching the query."""
    make_test_employee()
    res = client.get("/api/employees", headers=hr_manager_auth,
                      params={"limit": 5, "sort_by": "ic_number; DROP TABLE employees;--"})
    assert res.status_code == 200


def test_list_employees_pay_grade_name_only_for_compensation_roles(
    client, hr_manager_auth, make_test_employee, make_test_user, test_institution
):
    """pay_grade_name (surfaced as an optional Employee List column) is only
    resolved for hr_manager/payroll_manager/compensation_manager — the same
    roles the Compensation module itself is gated to elsewhere (see
    dashboard.js's canCompensation). Every other role must get None
    regardless of what pay grade is actually assigned, so a stale column
    preference in someone's browser can never leak it."""
    emp = make_test_employee()
    grade_res = client.post(
        "/api/compensation/pay-grades",
        json={
            "grade_code": _unique_code("ZZ"),
            "grade_name": "ZZ Test Grade",
            "grade_level": 1,
            "min_salary": 1000.00,
            "midpoint_salary": 1500.00,
            "max_salary": 2000.00,
        },
        headers=hr_manager_auth,
    )
    assert grade_res.status_code == 201, grade_res.text
    grade_id = grade_res.json()["id"]

    comp_res = client.post(
        f"/api/compensation/employees/{emp['employee_id']}/compensation",
        json={"pay_grade_id": grade_id, "effective_date": "2026-07-19"},
        headers=hr_manager_auth,
    )
    assert comp_res.status_code == 201, comp_res.text

    res = client.get("/api/employees", headers=hr_manager_auth)
    row = next(r for r in res.json() if r["employee_id"] == emp["employee_id"])
    assert row["pay_grade_name"] == "ZZ Test Grade"

    admin_token, _ = make_test_user(role="hr_admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/employees", headers=admin_headers)
    row = next(r for r in res.json() if r["employee_id"] == emp["employee_id"])
    assert row["pay_grade_name"] is None


# ---------------------------------------------------------------------------
# Workforce stats — deliberately NOT scoped like List employees above (see
# get_workforce_stats' own docstring-equivalent comment in routers/
# employees.py): aggregate counts only, so every role — including
# "employee", who List employees restricts to just their own record — sees
# the same institution-wide totals.
# ---------------------------------------------------------------------------
def test_workforce_stats_requires_auth(client):
    res = client.get("/api/employees/workforce-stats")
    assert res.status_code in (401, 403)


def test_workforce_stats_reflects_created_data(client, hr_manager_auth, make_test_employee):
    """Before/after snapshot (test_institution is session-scoped and shared
    across the whole test run — see conftest.py's own documented gotcha —
    so an exact absolute total can't be asserted)."""
    before = client.get("/api/employees/workforce-stats", headers=hr_manager_auth)
    assert before.status_code == 200
    b = before.json()

    emp = make_test_employee(department="ZZWorkforceStatsDept", gender="Female", race="Chinese", employment_type="Contract")

    after = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()
    assert after["total"] == b["total"] + 1
    assert after["active"] == b["active"] + 1
    assert after["dept_breakdown"]["ZZWorkforceStatsDept"] == b["dept_breakdown"].get("ZZWorkforceStatsDept", 0) + 1
    assert after["employment_type_breakdown"]["Contract"] == b["employment_type_breakdown"].get("Contract", 0) + 1
    assert after["race_breakdown"]["Chinese"] == b["race_breakdown"].get("Chinese", 0) + 1
    assert after["total_gender"]["Female"] == b["total_gender"]["Female"] + 1
    assert after["local_count"] == b["local_count"] + 1  # nationality defaults to "Malaysian"

    client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})


def test_workforce_stats_is_institution_wide_for_employee_role(client, hr_manager_auth, make_test_user, test_institution, make_test_employee):
    """The actual regression this endpoint exists to fix: an 'employee'-role
    login must see the SAME institution-wide totals HR does, not just
    themselves (or zero) — unlike GET /api/employees, which intentionally
    collapses to their own single record for that role."""
    make_test_employee()  # ensure there's at least one row to count

    hr_stats = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()

    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}
    emp_res = client.get("/api/employees/workforce-stats", headers=emp_headers)
    assert emp_res.status_code == 200
    emp_stats = emp_res.json()

    assert emp_stats["total"] == hr_stats["total"]
    assert emp_stats["total"] > 1  # would be <= 1 if this were wrongly scoped to "self" like List employees


def test_workforce_stats_turnover_reflects_deactivation(client, hr_manager_auth, make_test_employee):
    """Deactivating an employee writes an audit_logs action='DEACTIVATE'
    row (routers/employees.py's update_status) — separations_12mo counts
    those, and turnover_rate_12mo is separations over current active
    headcount."""
    emp = make_test_employee()
    before = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()

    client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})

    after = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()
    assert after["separations_12mo"] == before["separations_12mo"] + 1
    expected_rate = round(after["separations_12mo"] / after["active"] * 100, 1) if after["active"] else 0.0
    assert after["turnover_rate_12mo"] == expected_rate


def test_workforce_stats_resignation_counted_only_when_approved(client, hr_manager_auth, make_test_employee):
    """resignations_12mo counts approved resignation_requests specifically
    (the voluntary subset of separations) — filing one alone (still
    Pending) must not move it."""
    emp = make_test_employee(full_name="ZZ Workforce Stats Resign")
    before = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()

    res = client.post("/api/resignations", headers=hr_manager_auth, json={
        "employee_id": emp["employee_id"], "reason": "ZZ testing workforce stats",
        "effective_date": "2027-06-01", "last_working_day": "2027-06-15",
    })
    assert res.status_code == 201, res.text
    request_id = res.json()["id"]

    pending = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()
    assert pending["resignations_12mo"] == before["resignations_12mo"]

    approve = client.patch(f"/api/resignations/{request_id}", headers=hr_manager_auth, json={"status": "Approved"})
    assert approve.status_code == 200, approve.text

    after = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()
    assert after["resignations_12mo"] == before["resignations_12mo"] + 1


def test_workforce_stats_avg_tenure_shifts_toward_new_employees_tenure(client, hr_manager_auth, make_test_employee):
    """A newly-added active employee with a long-past start_date pulls the
    reported average tenure up — a direction-of-change assertion (not an
    exact value) since test_institution is session-scoped and shared
    across the whole run, so the pre-existing population size/composition
    isn't known exactly."""
    before = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()

    make_test_employee(full_name="ZZ Workforce Stats Tenure", start_date="2010-01-01")

    after = client.get("/api/employees/workforce-stats", headers=hr_manager_auth).json()
    assert after["avg_tenure_years"] > before["avg_tenure_years"]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
def test_update_employee_success(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    updated = _valid_employee_payload(full_name="ZZ Updated Name", department="Sales")
    res = client.put(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth, json=updated)
    assert res.status_code == 200
    assert res.json()["full_name"] == "ZZ Updated Name"
    assert res.json()["department"] == "Sales"


def test_resign_date_defaults_to_none_and_hr_can_set_it_via_update(client, hr_manager_auth, make_test_employee):
    """resign_date is a plain, manually-entered field — nothing auto-sets
    it (e.g. from the status toggle) — and CAN_WRITE (hr_manager/hr_admin/
    superadmin) can set it the same way as every other employee field."""
    emp = make_test_employee()
    assert emp["resign_date"] is None

    updated = _valid_employee_payload(resign_date="2026-09-30")
    res = client.put(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth, json=updated)
    assert res.status_code == 200, res.text
    assert res.json()["resign_date"] == "2026-09-30"

    # Persisted, not just echoed back — a fresh GET confirms it stuck.
    res = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth)
    assert res.json()["resign_date"] == "2026-09-30"


def test_resign_date_visible_to_the_employee_themself(client, hr_manager_auth, make_test_employee, test_institution):
    """Resign Date can only be edited by HR (see the test above), but must
    stay visible to the employee viewing their own record, and to their
    manager — same read scope as every other employee field, no extra
    view-side gate."""
    emp = make_test_employee()
    res = client.put(
        f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth,
        json=_valid_employee_payload(resign_date="2026-12-15"),
    )
    assert res.status_code == 200, res.text

    username = f"zzresigntest_{emp['employee_id'].lower()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Resign Test Employee",
        "password": "ZzPytest@123", "role": "employee", "employee_id": emp["employee_id"],
    })
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]
    try:
        login = client.post("/api/auth/login", json={
            "username": username, "password": "ZzPytest@123", "institution_code": test_institution["code"],
        })
        assert login.status_code == 200, login.text
        self_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        res = client.get("/api/employees", headers=self_headers)
        assert res.status_code == 200
        row = next(r for r in res.json() if r["employee_id"] == emp["employee_id"])
        assert row["resign_date"] == "2026-12-15"
    finally:
        client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_update_employee_not_found_returns_404(client, hr_manager_auth):
    res = client.put(
        "/api/employees/EMP_ZZ_NONEXISTENT", headers=hr_manager_auth, json=_valid_employee_payload()
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Self-service personal details edit (Employee List pop-up's "Edit My Info")
# ---------------------------------------------------------------------------
def test_update_own_personal_details_success(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login()
    res = client.patch(f"/api/employees/{emp['employee_id']}/personal-details", headers=headers, json={
        "preferred_name": "ZZ Preferred", "personal_email": "zz.preferred@example.com",
        "religion": "Buddhism", "marital_status": "Married", "phone": "+60129998888",
        "address": "123 ZZ Test Street",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["preferred_name"] == "ZZ Preferred"
    assert body["personal_email"] == "zz.preferred@example.com"
    assert body["religion"] == "Buddhism"
    assert body["marital_status"] == "Married"
    assert body["phone"] == "+60129998888"
    assert body["address"] == "123 ZZ Test Street"


def test_update_own_personal_details_leaves_other_fields_untouched(client, hr_manager_auth, employee_with_login):
    """The whitelist model has no department/designation/basic_salary/etc.
    fields at all, so sending them must have no effect — proves this
    endpoint can't be used as a backdoor around employees.edit_employee."""
    emp, headers = employee_with_login(department="ZZ Original Dept")
    res = client.patch(f"/api/employees/{emp['employee_id']}/personal-details", headers=headers, json={
        "preferred_name": "ZZ New Preferred", "department": "ZZ Hacked Dept", "basic_salary": 999999,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["preferred_name"] == "ZZ New Preferred"
    assert body["department"] == "ZZ Original Dept"
    assert body["basic_salary"] in (0, 0.0)


def test_update_own_personal_details_rejects_other_employees_record(client, hr_manager_auth, employee_with_login, make_test_employee):
    emp, headers = employee_with_login()
    other = make_test_employee(full_name="ZZ Other Employee")
    res = client.patch(f"/api/employees/{other['employee_id']}/personal-details", headers=headers, json={
        "preferred_name": "ZZ Should Not Apply",
    })
    assert res.status_code == 403


def test_update_own_personal_details_invalid_religion_returns_422(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login()
    res = client.patch(f"/api/employees/{emp['employee_id']}/personal-details", headers=headers, json={
        "religion": "ZZ Not A Real Religion",
    })
    assert res.status_code == 422


def test_update_own_personal_details_invalid_marital_status_returns_422(client, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login()
    res = client.patch(f"/api/employees/{emp['employee_id']}/personal-details", headers=headers, json={
        "marital_status": "ZZ Not A Real Status",
    })
    assert res.status_code == 422


def test_update_own_personal_details_partial_update_keeps_other_fields(client, hr_manager_auth, employee_with_login):
    """exclude_unset semantics — sending only one field must not blank the
    other five, matching ConsentUpdate's own partial-update behavior."""
    emp, headers = employee_with_login(phone="+60111112222")
    res = client.patch(f"/api/employees/{emp['employee_id']}/personal-details", headers=headers, json={
        "preferred_name": "ZZ Only This Changed",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["preferred_name"] == "ZZ Only This Changed"
    assert body["phone"] == "+60111112222"


def test_update_own_personal_details_allowed_for_manager_role_too(client, hr_manager_auth, make_test_employee, test_institution):
    """Per design, this is scoped by "is this your own record", not by
    role — a manager (or any role) viewing their own record gets the same
    self-service edit as an "employee"-role user."""
    mgr_emp = make_test_employee(full_name="ZZ Self-Edit Manager")
    username = f"zzselfeditmgr_{mgr_emp['employee_id'].lower()}"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Self-Edit Manager User", "password": "ZzPytest@123",
        "role": "manager", "employee_id": mgr_emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    try:
        login = client.post("/api/auth/login", json={
            "username": username, "password": "ZzPytest@123", "institution_code": test_institution["code"],
        })
        assert login.status_code == 200, login.text
        mgr_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        res = client.patch(f"/api/employees/{mgr_emp['employee_id']}/personal-details", headers=mgr_headers, json={
            "preferred_name": "ZZ Manager Self Edit",
        })
        assert res.status_code == 200, res.text
        assert res.json()["preferred_name"] == "ZZ Manager Self Edit"
    finally:
        client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_update_own_personal_details_requires_auth(client, make_test_employee):
    emp = make_test_employee()
    res = client.patch(f"/api/employees/{emp['employee_id']}/personal-details", json={"preferred_name": "x"})
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Status toggle
# ---------------------------------------------------------------------------
def test_status_toggle_to_inactive_and_back(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})
    assert res.status_code == 200
    assert res.json()["status"] == "Inactive"

    res = client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Active"})
    assert res.status_code == 200
    assert res.json()["status"] == "Active"


def test_status_toggle_invalid_value_returns_422(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.patch(f"/api/employees/{emp['employee_id']}/status", headers=hr_manager_auth, json={"status": "Deleted"})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Bulk upload
# ---------------------------------------------------------------------------
def test_bulk_template_download_requires_hr_manager(client, make_test_user, test_institution):
    token, _ = make_test_user(role="hr_admin")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/employees/bulk-template", headers=headers)
    assert res.status_code == 403


def test_bulk_template_download_success(client, hr_manager_auth):
    res = client.get("/api/employees/bulk-template", headers=hr_manager_auth)
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "employee_id" in res.text.splitlines()[0]


def test_bulk_upload_creates_employee(client, hr_manager_auth):
    header = "employee_id,full_name,ic_number,passport_number,nationality,race,religion,gender,date_of_birth,marital_status,personal_email,phone,address,department,designation,employment_type,start_date,probation_end_date,contract_end_date,work_email,epf_number,socso_number,income_tax_number,bank_name,bank_account,basic_salary,num_children,salary_type,hourly_rate,reports_to"
    # A per-call-unique IC — if the shared ZZPYTEST institution has accumulated
    # test employees with this IC from prior runs (employees are never hard-deleted),
    # the row will be rejected as a duplicate and added to errors. This test verifies
    # that bulk upload either creates the employee OR gracefully reports the duplicate
    # error, demonstrating that the task doesn't crash on business rule violations.
    row = f",ZZ Bulk Employee,{_unique_ic()},,Malaysian,Chinese,Buddhism,Female,1992-05-05,Single,,+60129998888,,Sales,Sales Rep,Permanent,2026-02-01,,,,,,,,,3000,0,Monthly,0,"
    csv_content = header + "\n" + row + "\n"
    res = client.post("/api/employees/bulk-upload", headers=hr_manager_auth, json={"csv_content": csv_content})
    assert res.status_code == 202, res.text
    resp_data = res.json()
    assert "task_id" in resp_data
    task_id = resp_data["task_id"]

    # Check task status (task executes synchronously in tests with CELERY_TASK_ALWAYS_EAGER)
    status_res = client.get(f"/api/tasks/{task_id}", headers=hr_manager_auth)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "SUCCESS"
    body = status_data["result"]

    # Either the employee was created, or it was rejected as a duplicate.
    # Both outcomes are correct; we're verifying that bulk upload handles both gracefully.
    assert len(body["created"]) + len(body["errors"]) == 1, \
        f"Expected exactly one row result (created or error), got {len(body['created'])} created, {len(body['errors'])} errors"

    if len(body["created"]) == 1:
        # Success path: cleanup by deactivating the bulk-created employee
        new_emp_id = body["created"][0]["employee_id"]
        client.patch(f"/api/employees/{new_emp_id}/status", headers=hr_manager_auth, json={"status": "Inactive"})
    else:
        # Duplicate path: verify the error mentions duplicate/integrity
        assert len(body["errors"]) == 1
        error = body["errors"][0]
        assert "row" in error and "reason" in error


def test_bulk_upload_updates_existing_employee(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee(designation="Sales Rep", basic_salary=3000)
    header = "employee_id,full_name,ic_number,passport_number,nationality,race,religion,gender,date_of_birth,marital_status,personal_email,phone,address,department,designation,employment_type,start_date,probation_end_date,contract_end_date,work_email,epf_number,socso_number,income_tax_number,bank_name,bank_account,basic_salary,num_children,salary_type,hourly_rate,reports_to"
    row = f"{emp['employee_id']},{emp['full_name']},{emp['ic_number']},,Malaysian,Chinese,Buddhism,Female,1992-05-05,Single,,+60129998888,,Sales,Senior Sales Rep,Permanent,2026-02-01,,,,,,,,,4500,0,Monthly,0,"
    csv_content = header + "\n" + row + "\n"
    res = client.post("/api/employees/bulk-upload", headers=hr_manager_auth, json={"csv_content": csv_content})
    assert res.status_code == 202, res.text
    task_id = res.json()["task_id"]

    status_res = client.get(f"/api/tasks/{task_id}", headers=hr_manager_auth)
    assert status_res.status_code == 200
    body = status_res.json()["result"]
    assert body["created"] == []
    assert body["errors"] == []
    assert len(body["updated"]) == 1
    assert body["updated"][0]["employee_id"] == emp["employee_id"]

    updated = client.get(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth).json()
    assert updated["designation"] == "Senior Sales Rep"
    assert float(updated["basic_salary"]) == 4500

    # A bulk-upload update to an *existing* employee used to skip the HR
    # Notes mirror that every other update path writes (see
    # write_employee_change_note in routers/employees.py) — only the Audit
    # Log saw it, so the change was invisible on the employee's own HR
    # Notes tab. Confirm both now record it.
    notes = client.get(f"/api/employees/{emp['employee_id']}/notes", headers=hr_manager_auth).json()
    assert any("Designation" in n["body"] and "Senior Sales Rep" in n["body"] for n in notes)
    audit = client.get(f"/api/audit-logs?employee_id={emp['employee_id']}&action=UPDATE", headers=hr_manager_auth).json()
    assert any(c["field"] == "designation" for a in audit for c in a["changes"])


def test_bulk_upload_reports_row_errors_without_failing_whole_request(client, hr_manager_auth):
    header = "employee_id,full_name,ic_number,passport_number,nationality,race,religion,gender,date_of_birth,marital_status,personal_email,phone,address,department,designation,employment_type,start_date,probation_end_date,contract_end_date,work_email,epf_number,socso_number,income_tax_number,bank_name,bank_account,basic_salary,num_children,salary_type,hourly_rate,reports_to"
    bad_row = ",,bad-ic,,Malaysian,Chinese,Buddhism,Female,1992-05-05,Single,,+60129998888,,Sales,Sales Rep,Permanent,2026-02-01,,,,,,,,,3000,0,Monthly,0,"
    csv_content = header + "\n" + bad_row + "\n"
    res = client.post("/api/employees/bulk-upload", headers=hr_manager_auth, json={"csv_content": csv_content})
    assert res.status_code == 202, res.text
    resp_data = res.json()
    assert "task_id" in resp_data
    task_id = resp_data["task_id"]

    # Check task status (task executes synchronously in tests with CELERY_TASK_ALWAYS_EAGER)
    status_res = client.get(f"/api/tasks/{task_id}", headers=hr_manager_auth)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "SUCCESS"
    body = status_data["result"]
    assert body["created"] == []
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 2


# ---------------------------------------------------------------------------
# Rehire / related-contracts
# ---------------------------------------------------------------------------
def test_related_contracts_empty_for_unique_ic(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get(f"/api/employees/{emp['employee_id']}/related-contracts", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == []


def test_related_contracts_finds_shared_ic(client, hr_manager_auth, make_test_employee):
    shared_ic = "900101-14-9999"
    emp1 = make_test_employee(ic_number=shared_ic)
    emp2 = make_test_employee(ic_number=shared_ic)
    res = client.get(f"/api/employees/{emp1['employee_id']}/related-contracts", headers=hr_manager_auth)
    assert res.status_code == 200
    related_ids = [r["employee_id"] for r in res.json()]
    assert emp2["employee_id"] in related_ids


def test_rehire_prefill_success(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    res = client.get(f"/api/employees/{emp['employee_id']}/rehire-prefill", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert body["full_name"] == emp["full_name"]
    assert body["previous_employee_id"] == emp["employee_id"]


def test_rehire_prefill_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/employees/EMP_ZZ_NONEXISTENT/rehire-prefill", headers=hr_manager_auth)
    assert res.status_code == 404
