"""Integration tests for routers/payroll.py.

Uses far-future, counter-spaced periods so period_start/period_end never
collide across repeated runs in the shared ZZPYTEST institution (payroll_runs
has a unique constraint on institution_id+period_start+period_end).
Payroll runs have no delete-on-teardown for most tests here, so they
accumulate permanently — a small fixed year x month space (as this file
originally used) will eventually collide after enough repeated full-suite
runs; a per-call counter spanning many years avoids that.
"""
import itertools
import random
from datetime import date, timedelta

import payroll_calc

# A day-granularity random offset (not just a small year range) gives a vastly
# larger no-collision space than picking among ~800 years — after enough
# repeated full-suite runs in a day, a small fixed set of (year, month)
# combinations is exactly the kind of space that eventually collides by the
# pigeonhole principle (as happened here).
_base_date = date(2100, 1, 1) + timedelta(days=random.randint(0, 2_000_000))
_period_counter = itertools.count()


def _period(month=None):
    """A unique 4-week period far in the future. `month` is accepted-but-ignored
    for call-site readability; periods are actually spaced out via a counter
    from a randomized base date so no two calls collide."""
    base = _base_date + timedelta(days=35 * next(_period_counter))
    start = base.isoformat()
    end = (base + timedelta(days=27)).isoformat()
    return start, end


def test_list_payroll_runs_requires_auth(client):
    res = client.get("/api/payroll/runs")
    assert res.status_code == 401


def test_create_payroll_run_requires_payroll_manager_role(hr_manager_auth, client):
    start, end = _period(1)
    res = client.post("/api/payroll/runs", headers=hr_manager_auth,
                       json={"period_start": start, "period_end": end})
    assert res.status_code == 403


def test_create_payroll_run_end_before_start_returns_400(payroll_manager_auth, client):
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": "2100-02-01", "period_end": "2100-01-01"})
    assert res.status_code == 400


def test_create_payroll_run_generates_payslip_for_monthly_employee(
    payroll_manager_auth, client, make_test_employee
):
    emp = make_test_employee(
        salary_type="Monthly", basic_salary=5200.0, date_of_birth="1990-05-15",
        marital_status="Single", num_children=0,
    )
    start, end = _period(2)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    assert res.status_code == 201, res.text
    run = res.json()
    assert run["status"] == "Draft"

    detail = client.get(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth)
    assert detail.status_code == 200
    payslips = {p["employee_id"]: p for p in detail.json()["payslips"]}
    assert emp["employee_id"] in payslips
    slip = payslips[emp["employee_id"]]

    assert slip["basic_salary"] == 5200.0
    assert slip["unpaid_leave_days"] == 0.0
    assert slip["gross_pay"] == 5200.0

    epf = payroll_calc.calc_epf(5200.0)
    socso = payroll_calc.calc_socso(5200.0, 34)  # ~34 in these far-future years, well under 60
    eis = payroll_calc.calc_eis(5200.0, 34)
    pcb = payroll_calc.calc_pcb(5200.0, "Single", 0, epf["employee"])
    assert slip["epf_employee"] == epf["employee"]
    assert slip["epf_employer"] == epf["employer"]
    assert slip["socso_employee"] == socso["employee"]
    assert slip["eis_employee"] == eis["employee"]
    assert slip["pcb"] == pcb
    expected_net = round(5200.0 - epf["employee"] - socso["employee"] - eis["employee"] - pcb, 2)
    assert slip["net_pay"] == expected_net


def test_create_payroll_run_duplicate_period_returns_400(payroll_manager_auth, client):
    start, end = _period(3)
    res1 = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                        json={"period_start": start, "period_end": end})
    assert res1.status_code == 201, res1.text
    res2 = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                        json={"period_start": start, "period_end": end})
    assert res2.status_code == 400


def test_get_payroll_run_not_found_returns_404(payroll_manager_auth, client):
    res = client.get("/api/payroll/runs/999999999", headers=payroll_manager_auth)
    assert res.status_code == 404


def test_hourly_employee_payslip_splits_overtime(
    payroll_manager_auth, client, hr_manager_auth, test_institution, make_test_employee
):
    emp = make_test_employee(salary_type="Hourly", hourly_rate=20.0, date_of_birth="1985-01-01")
    username = f"zztpayroll_{emp['employee_id'].lower()}"
    password = "ZzPytest@123"
    user_res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": "ZZ Payroll Test Employee",
        "password": password, "role": "employee", "employee_id": emp["employee_id"],
    })
    assert user_res.status_code == 201, user_res.text
    user_id = user_res.json()["id"]
    login = client.post("/api/auth/login", json={
        "username": username, "password": password, "institution_code": test_institution["code"],
    })
    assert login.status_code == 200
    emp_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    project_res = client.post("/api/projects", headers=hr_manager_auth, json={"name": "ZZ Payroll Project", "status": "Active"})
    assert project_res.status_code == 201, project_res.text
    project = project_res.json()
    task_res = client.post(f"/api/projects/{project['id']}/tasks", headers=hr_manager_auth,
                            json={"name": "ZZ Payroll Task", "status": "Not Started"})
    assert task_res.status_code == 201, task_res.text
    task = task_res.json()
    open_res = client.patch(f"/api/projects/{project['id']}/tasks/{task['id']}/open-to-all",
                             headers=hr_manager_auth, json={"open_to_all": True})
    assert open_res.status_code == 200, open_res.text

    start, end = _period(4)
    ts = client.post("/api/timesheets", headers=emp_headers,
                      json={"employee_id": emp["employee_id"], "period_start": start, "period_end": end})
    assert ts.status_code == 201, ts.text
    timesheet = ts.json()

    entry = client.post(f"/api/timesheets/{timesheet['id']}/entries", headers=emp_headers, json={
        "project_id": project["id"], "task_id": task["id"], "date": start, "hours": 8.0,
    })
    assert entry.status_code == 201, entry.text

    submit = client.patch(f"/api/timesheets/{timesheet['id']}/status", headers=emp_headers, json={"status": "Submitted"})
    assert submit.status_code == 200, submit.text
    approve = client.patch(f"/api/timesheets/{timesheet['id']}/status", headers=hr_manager_auth, json={"status": "Approved"})
    assert approve.status_code == 200, approve.text

    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    assert res.status_code == 201, res.text
    run = res.json()
    detail = client.get(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth)
    payslips = {p["employee_id"]: p for p in detail.json()["payslips"]}
    slip = payslips[emp["employee_id"]]
    assert slip["salary_type"] == "Hourly"
    assert slip["regular_hours"] == 8.0
    assert slip["overtime_hours"] == 0.0
    assert slip["basic_salary"] == round(8.0 * 20.0, 2)

    client.delete(f"/api/projects/{project['id']}/tasks/{task['id']}", headers=hr_manager_auth)
    client.delete(f"/api/projects/{project['id']}", headers=hr_manager_auth)
    client.delete(f"/api/users/{user_id}", headers=hr_manager_auth)


def test_adjust_payslip_recomputes_deductions(
    payroll_manager_auth, client, make_test_employee
):
    emp = make_test_employee(salary_type="Monthly", basic_salary=4000.0, date_of_birth="1988-01-01")
    start, end = _period(5)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    run = res.json()
    detail = client.get(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth).json()
    slip = next(p for p in detail["payslips"] if p["employee_id"] == emp["employee_id"])

    adjust = client.put(f"/api/payroll/payslips/{slip['id']}", headers=payroll_manager_auth,
                         json={"basic_salary": 4500.0})
    assert adjust.status_code == 200, adjust.text
    updated = adjust.json()
    assert updated["basic_salary"] == 4500.0
    epf = payroll_calc.calc_epf(4500.0)
    assert updated["epf_employee"] == epf["employee"]


def test_adjust_payslip_not_found_returns_404(payroll_manager_auth, client):
    res = client.put("/api/payroll/payslips/999999999", headers=payroll_manager_auth,
                      json={"basic_salary": 1000.0})
    assert res.status_code == 404


def test_finalize_payroll_run_locks_editing(payroll_manager_auth, client, make_test_employee):
    emp = make_test_employee(salary_type="Monthly", basic_salary=3000.0)
    start, end = _period(6)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    run = res.json()

    finalize = client.patch(f"/api/payroll/runs/{run['id']}/finalize", headers=payroll_manager_auth)
    assert finalize.status_code == 200, finalize.text
    assert finalize.json()["status"] == "Finalized"

    detail = client.get(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth).json()
    slip = next(p for p in detail["payslips"] if p["employee_id"] == emp["employee_id"])
    adjust = client.put(f"/api/payroll/payslips/{slip['id']}", headers=payroll_manager_auth,
                         json={"basic_salary": 9999.0})
    assert adjust.status_code == 400

    finalize_again = client.patch(f"/api/payroll/runs/{run['id']}/finalize", headers=payroll_manager_auth)
    assert finalize_again.status_code == 400


def test_finalize_payroll_run_not_found_returns_404(payroll_manager_auth, client):
    res = client.patch("/api/payroll/runs/999999999/finalize", headers=payroll_manager_auth)
    assert res.status_code == 404


def test_delete_payroll_run_success(payroll_manager_auth, client):
    start, end = _period(7)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    run = res.json()
    delete = client.delete(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth)
    assert delete.status_code == 204
    get = client.get(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth)
    assert get.status_code == 404


def test_delete_finalized_payroll_run_returns_400(payroll_manager_auth, client):
    start, end = _period(8)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    run = res.json()
    client.patch(f"/api/payroll/runs/{run['id']}/finalize", headers=payroll_manager_auth)
    delete = client.delete(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth)
    assert delete.status_code == 400


def test_export_bank_csv_success(payroll_manager_auth, client, make_test_employee):
    emp = make_test_employee(salary_type="Monthly", basic_salary=3500.0, bank_name="Maybank", bank_account="1234567890")
    start, end = _period(9)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    run = res.json()
    csv_res = client.get(f"/api/payroll/runs/{run['id']}/bank-csv", headers=payroll_manager_auth)
    assert csv_res.status_code == 200
    assert emp["employee_id"] in csv_res.text
    assert "Maybank" in csv_res.text


def test_export_bank_csv_requires_payroll_manager_role(hr_manager_auth, client):
    res = client.get("/api/payroll/runs/1/bank-csv", headers=hr_manager_auth)
    assert res.status_code == 403


def test_my_payslips_empty_when_no_employee_record(payroll_manager_auth, client):
    res = client.get("/api/payroll/payslips/mine", headers=payroll_manager_auth)
    assert res.status_code == 200
    assert res.json() == []


def test_get_payslip_not_found_returns_404(payroll_manager_auth, client):
    res = client.get("/api/payroll/payslips/999999999", headers=payroll_manager_auth)
    assert res.status_code == 404


def test_get_payslip_view_only_role_can_access_any(payroll_manager_auth, hr_manager_auth, client, make_test_employee):
    make_test_employee(salary_type="Monthly", basic_salary=3000.0)
    start, end = _period(10)
    res = client.post("/api/payroll/runs", headers=payroll_manager_auth,
                       json={"period_start": start, "period_end": end})
    run = res.json()
    detail = client.get(f"/api/payroll/runs/{run['id']}", headers=payroll_manager_auth).json()
    slip_id = detail["payslips"][0]["id"]

    # hr_manager is in PAYROLL_VIEW_ROLES, so it can view any payslip
    res = client.get(f"/api/payroll/payslips/{slip_id}", headers=hr_manager_auth)
    assert res.status_code == 200
