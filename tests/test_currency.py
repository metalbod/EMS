"""
Tests for the REAL -> NUMERIC(12,2) currency migration (see main.py's
migration notes and db.py's DEC2FLOAT adapter registration).

These are read-only against the real DB: they verify column types and that
values round-trip as plain Python float, never mutate data.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CURRENCY_COLUMNS = [
    ("employees", "basic_salary"), ("employees", "hourly_rate"),
    ("job_requisitions", "salary_min"), ("job_requisitions", "salary_max"),
    ("candidates", "expected_salary"),
    ("offers", "salary_offered"),
    ("ld_courses", "cost"),
    ("payslips", "basic_salary"), ("payslips", "unpaid_leave_deduction"),
    ("payslips", "gross_pay"), ("payslips", "epf_employee"), ("payslips", "epf_employer"),
    ("payslips", "socso_employee"), ("payslips", "socso_employer"),
    ("payslips", "eis_employee"), ("payslips", "eis_employer"),
    ("payslips", "pcb"), ("payslips", "net_pay"),
    ("payslips", "overtime_pay"), ("payslips", "bonus_amount"),
    ("performance_payouts", "amount"),
]


def test_currency_columns_are_numeric_12_2():
    import db
    conn = db.get_db()
    try:
        for tbl, col in CURRENCY_COLUMNS:
            row = conn.execute(
                "SELECT data_type, numeric_precision, numeric_scale FROM information_schema.columns "
                "WHERE table_name=? AND column_name=?",
                (tbl, col),
            ).fetchone()
            assert row is not None, f"{tbl}.{col} not found"
            assert row["data_type"] == "numeric", f"{tbl}.{col} is {row['data_type']}, expected numeric"
            assert row["numeric_precision"] == 12 and row["numeric_scale"] == 2, (
                f"{tbl}.{col} is numeric({row['numeric_precision']},{row['numeric_scale']}), expected numeric(12,2)"
            )
    finally:
        conn.close()


def test_numeric_columns_round_trip_as_python_float_not_decimal():
    """The DEC2FLOAT adapter in db.py must make NUMERIC columns come back as
    float, not decimal.Decimal — existing payroll_calc.py arithmetic mixes
    these values with float literals, which raises TypeError with Decimal."""
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT net_pay, pcb, gross_pay FROM payslips LIMIT 1").fetchone()
        if row is None:
            import pytest
            pytest.skip("no payslip rows to check in this environment")
        for col in ("net_pay", "pcb", "gross_pay"):
            assert isinstance(row[col], float), f"{col} is {type(row[col]).__name__}, expected float"
    finally:
        conn.close()


def test_payroll_calc_accepts_a_numeric_sourced_value():
    """Confirms the exact failure mode this migration could have introduced
    (Decimal/float TypeError) does not happen end-to-end."""
    import db
    import payroll_calc as pc

    conn = db.get_db()
    try:
        row = conn.execute("SELECT gross_pay FROM payslips LIMIT 1").fetchone()
        if row is None:
            import pytest
            pytest.skip("no payslip rows to check in this environment")
        result = pc.calc_epf(row["gross_pay"])
        assert isinstance(result["employee"], float)
    finally:
        conn.close()
