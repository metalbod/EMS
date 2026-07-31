"""An employee's current compensation record — the single source of "what is
X's current job_role/job_level/pay_grade/salary_structure/base_salary,"
stored as their `is_current=1` row in employee_compensation.

Extracted out of routers/compensation.py, where "SELECT ... WHERE
employee_id=? AND institution_id=? AND is_current=1" was hand-written at
4 separate read sites, and the retire-then-insert transition (UPDATE the
old row to is_current=0, INSERT a new is_current=1 row) was duplicated
near-identically in set_employee_compensation and
approve_merit_recommendation. Two call sites needing the identical
transition — and the real risk that they'd drift (one already differs
slightly in what it defaults job_role_id/job_level_id/pay_grade_id to
when there's no previous record) — is what justified pulling this out,
not tidiness for its own sake.

Aggregate/bulk queries over employee_compensation (pay equity's gender/
department GROUP BY, for example) stay in routers/compensation.py — this
module is specifically the single-employee "current record" shape.
"""
from datetime import datetime


def get_current(conn, inst_id, employee_id):
    """Returns the employee's current (is_current=1) employee_compensation
    row as a dict, or None if they don't have one yet."""
    row = conn.execute(
        "SELECT * FROM employee_compensation WHERE employee_id=? AND institution_id=? AND is_current=1",
        (employee_id, inst_id),
    ).fetchone()
    return dict(row) if row else None


def retire_and_replace(conn, inst_id, employee_id, *, job_role_id, job_level_id, pay_grade_id,
                        salary_structure_id, base_salary, effective_date):
    """Ends the employee's current compensation record (is_current=0,
    end_date=effective_date) and inserts a new is_current=1 row with the
    given fields. Returns the new row's id.

    employee_id alone is not a safe filter for the retiring UPDATE — it's
    only unique per institution (composite unique with institution_id), so
    a bare WHERE employee_id=? could match a same-numbered employee in a
    different institution for a superadmin (bypass_rls=true) connection,
    where RLS itself won't catch the cross-tenant row. Always scope by
    both.
    """
    conn.execute(
        "UPDATE employee_compensation SET is_current=0, end_date=? WHERE employee_id=? AND institution_id=? AND is_current=1",
        (effective_date, employee_id, inst_id),
    )
    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO employee_compensation
        (institution_id, employee_id, job_role_id, job_level_id, pay_grade_id,
         salary_structure_id, base_salary, effective_date, is_current, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (inst_id, employee_id, job_role_id, job_level_id, pay_grade_id,
         salary_structure_id, base_salary, effective_date, now, now),
    )
    return conn._last_id
