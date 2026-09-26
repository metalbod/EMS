"""Scope timesheets / attendance_records unique keys by institution

Revision ID: 20260927_0001
Revises: 20260926_0001
Create Date: 2026-09-27

employee_id is a per-institution sequence (EMP0001, EMP0002, ... — see
routers/employees.py), so two tenants both have an EMP0001. Two unique
constraints keyed on employee_id alone therefore let one tenant's row block
another tenant's insert (psycopg2 UniqueViolation -> HTTP 500), even though
the endpoints look up "does this row already exist" scoped by institution:

  * timesheets            (employee_id, period_start, period_end)
  * attendance_records    (employee_id, work_date)

Both are replaced by the same key with institution_id first. This only
*relaxes* uniqueness across tenants — within one institution the rule is
unchanged — so it can never fail on existing data. institution_id is NOT NULL
on both tables, so the new key has no NULL loophole.

Other unique indexes that mention employee_id (appraisals, leave_balances,
benefit_enrollments, employee_documents, employee_location_assignments,
location_transfers, ...) pair it with a globally-unique serial parent id
(cycle_id, leave_type_id, benefit_plan_id, ...), so they were already
tenant-safe and are left alone.

routers/attendance.py's absence sweep used `ON CONFLICT (employee_id,
work_date)`, which names the old key; it is now a target-less `ON CONFLICT
DO NOTHING`, valid against either key. Old code running against the new key
(the seconds between `alembic upgrade` and the app restart in deploy.sh)
would fail that one statement, and only that one.

downgrade() restores the old keys; it fails if two tenants now legitimately
share an (employee_id, period) / (employee_id, work_date) pair.
"""
from alembic import op

revision = '20260927_0001'
down_revision = '20260926_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE timesheets DROP CONSTRAINT IF EXISTS timesheets_employee_id_period_start_period_end_key")
    op.execute("""
        ALTER TABLE timesheets
        ADD CONSTRAINT uq_timesheets_inst_employee_period
        UNIQUE (institution_id, employee_id, period_start, period_end)
    """)
    op.execute("ALTER TABLE attendance_records DROP CONSTRAINT IF EXISTS uq_attendance_records_employee_workdate")
    op.execute("""
        ALTER TABLE attendance_records
        ADD CONSTRAINT uq_attendance_records_employee_workdate
        UNIQUE (institution_id, employee_id, work_date)
    """)


def downgrade():
    op.execute("ALTER TABLE attendance_records DROP CONSTRAINT IF EXISTS uq_attendance_records_employee_workdate")
    op.execute("""
        ALTER TABLE attendance_records
        ADD CONSTRAINT uq_attendance_records_employee_workdate
        UNIQUE (employee_id, work_date)
    """)
    op.execute("ALTER TABLE timesheets DROP CONSTRAINT IF EXISTS uq_timesheets_inst_employee_period")
    op.execute("""
        ALTER TABLE timesheets
        ADD CONSTRAINT timesheets_employee_id_period_start_period_end_key
        UNIQUE (employee_id, period_start, period_end)
    """)
