"""Drop employees.default_location_id

Revision ID: 20260730_0001
Revises: 20260729_0002
Create Date: 2026-07-30

employees.default_location_id and employee_location_assignments
(assignment_type='primary') were two parallel, unsynced ways of tracking
an employee's location — the Edit Employee form wrote the former while
transfers/capacity/payroll-dashboard features wrote and read the latter.
Consolidating to one column: employee_location_assignments is the richer
table (history, transfers, capacity — see routers/locations.py,
location_phase2.py) so it's kept as the single source of truth, and this
drops the now-redundant employees column. Every touchpoint (Add/Edit
Employee, the employee list, attendance's shift-location lookup) now reads
and writes through employee_location_assignments exclusively — see
_resolve_primary_locations / _set_primary_location in routers/employees.py.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260730_0001'
down_revision = '20260729_0002'
branch_labels = None
depends_on = None


def upgrade():
    # Backfill: some employees had default_location_id set but had never gone
    # through a routers/locations.py endpoint, so no matching primary assignment
    # row exists yet. Without this, dropping the column below would silently
    # lose their location.
    op.execute("""
        INSERT INTO employee_location_assignments
            (institution_id, employee_id, location_id, assignment_type, start_date)
        SELECT e.institution_id, e.employee_id, e.default_location_id, 'primary',
               to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD')
        FROM employees e
        WHERE e.default_location_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM employee_location_assignments ela
            WHERE ela.employee_id = e.employee_id AND ela.institution_id = e.institution_id
              AND ela.assignment_type = 'primary' AND ela.is_active = 1
          )
    """)
    op.drop_column('employees', 'default_location_id')


def downgrade():
    op.add_column('employees', sa.Column('default_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True))
    op.execute("""
        UPDATE employees e SET default_location_id = ela.location_id
        FROM employee_location_assignments ela
        WHERE ela.employee_id = e.employee_id AND ela.institution_id = e.institution_id
          AND ela.assignment_type = 'primary' AND ela.is_active = 1
    """)
