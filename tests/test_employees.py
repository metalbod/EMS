"""
Integration tests for routers/employees.py — hits the real app and real DB
(see conftest.py's test_institution fixture) using disposable, zz-prefixed
data. Employees have no delete endpoint (only status toggle), so cleanup
deactivates rather than deletes.

test_create_employee_success is a regression test: POST /api/employees was
completely unroutable for a while (the @router.post decorator was on the
wrong function — see commit 207a31f) and returned 422 for every request.
"""
import itertools
import random

import pytest

# Salted with a fresh random value per process (not the PID, which can
# recycle across separate CI runs) plus a per-process counter, so IC numbers
# are unique both within a run and across separate pytest invocations — a
# prior run's leftover test employees (e.g. from an interrupted run) must
# never collide with a fresh run's.
_ic_counter = itertools.count(1)
_ic_run_salt = random.randint(0, 9999)


def _unique_ic():
    """A syntactically valid, per-call-unique 12-digit IC number, so tests
    that check IC-based matching (related-contracts) don't collide with
    other employees created by other tests or other runs in the same shared
    institution."""
    n = next(_ic_counter)
    return f"9001{_ic_run_salt:04d}{n:04d}"


def _valid_employee_payload(**overrides):
    payload = {
        "full_name": "ZZ Test Employee",
        "ic_number": _unique_ic(),
        "race": "Malay",
        "religion": "Islam",
        "gender": "Male",
        "date_of_birth": "1990-01-01",
        "marital_status": "Single",
        "phone": "+60123456789",
        "department": "IT",
        "designation": "Tester",
        "employment_type": "Permanent",
        "start_date": "2026-01-01",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def hr_manager_auth(make_test_user, test_institution):
    token, _ = make_test_user(role="hr_manager")
    return {
        "Authorization": f"Bearer {token}",
        "X-Institution-Id": str(test_institution["id"]),
    }


@pytest.fixture
def make_test_employee(client, hr_manager_auth):
    """Factory: creates a disposable employee, deactivates it on teardown
    (employees have no delete endpoint)."""
    created_ids = []

    def _make(**overrides):
        res = client.post("/api/employees", headers=hr_manager_auth, json=_valid_employee_payload(**overrides))
        assert res.status_code == 201, f"failed to create test employee: {res.text}"
        emp = res.json()
        created_ids.append(emp["employee_id"])
        return emp

    yield _make

    for emp_id in created_ids:
        client.patch(f"/api/employees/{emp_id}/status", headers=hr_manager_auth, json={"status": "Inactive"})


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
# Update
# ---------------------------------------------------------------------------
def test_update_employee_success(client, hr_manager_auth, make_test_employee):
    emp = make_test_employee()
    updated = _valid_employee_payload(full_name="ZZ Updated Name", department="Sales")
    res = client.put(f"/api/employees/{emp['employee_id']}", headers=hr_manager_auth, json=updated)
    assert res.status_code == 200
    assert res.json()["full_name"] == "ZZ Updated Name"
    assert res.json()["department"] == "Sales"


def test_update_employee_not_found_returns_404(client, hr_manager_auth):
    res = client.put(
        "/api/employees/EMP_ZZ_NONEXISTENT", headers=hr_manager_auth, json=_valid_employee_payload()
    )
    assert res.status_code == 404


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
    row = ",ZZ Bulk Employee,900101-14-5678,,Malaysian,Chinese,Buddhism,Female,1992-05-05,Single,,+60129998888,,Sales,Sales Rep,Permanent,2026-02-01,,,,,,,,,3000,0,Monthly,0,"
    csv_content = header + "\n" + row + "\n"
    res = client.post("/api/employees/bulk-upload", headers=hr_manager_auth, json={"csv_content": csv_content})
    assert res.status_code == 200
    body = res.json()
    assert len(body["created"]) == 1
    assert body["errors"] == []
    new_emp_id = body["created"][0]["employee_id"]

    # cleanup: deactivate the bulk-created employee
    client.patch(f"/api/employees/{new_emp_id}/status", headers=hr_manager_auth, json={"status": "Inactive"})


def test_bulk_upload_reports_row_errors_without_failing_whole_request(client, hr_manager_auth):
    header = "employee_id,full_name,ic_number,passport_number,nationality,race,religion,gender,date_of_birth,marital_status,personal_email,phone,address,department,designation,employment_type,start_date,probation_end_date,contract_end_date,work_email,epf_number,socso_number,income_tax_number,bank_name,bank_account,basic_salary,num_children,salary_type,hourly_rate,reports_to"
    bad_row = ",,bad-ic,,Malaysian,Chinese,Buddhism,Female,1992-05-05,Single,,+60129998888,,Sales,Sales Rep,Permanent,2026-02-01,,,,,,,,,3000,0,Monthly,0,"
    csv_content = header + "\n" + bad_row + "\n"
    res = client.post("/api/employees/bulk-upload", headers=hr_manager_auth, json={"csv_content": csv_content})
    assert res.status_code == 200
    body = res.json()
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
