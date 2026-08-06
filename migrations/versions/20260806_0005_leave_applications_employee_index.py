"""Add composite index on leave_applications(institution_id, employee_id)

Revision ID: 20260806_0005
Revises: 20260806_0004
Create Date: 2026-08-06

routers/payroll.py's per-employee unpaid-leave deduction lookup (called
once per employee per payroll run — _compute_pay) filters by
institution_id + employee_id + status + date range, but
leave_applications only had an institution_id index, forcing a Seq Scan
per call. Confirmed via EXPLAIN ANALYZE (Query Performance report).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260806_0005'
down_revision = '20260806_0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('idx_leave_applications_inst_employee', 'leave_applications', ['institution_id', 'employee_id'])


def downgrade():
    op.drop_index('idx_leave_applications_inst_employee', table_name='leave_applications')
