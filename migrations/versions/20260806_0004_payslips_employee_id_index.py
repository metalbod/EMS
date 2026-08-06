"""Add missing index on payslips.employee_id

Revision ID: 20260806_0004
Revises: 20260806_0003
Create Date: 2026-08-06

The institution-wide payroll-by-location summary (routers/location_phase2.py)
joins employee_location_assignments to payslips on employee_id, but
payslips only had indexes on id, institution_id, and the composite
(payroll_run_id, employee_id) — none usable for a plain employee_id
lookup, forcing a full (parallel) sequential scan. Confirmed via
EXPLAIN ANALYZE against the shared Supabase DB (Query Performance
report): ~1.2s execution before this index.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260806_0004'
down_revision = '20260806_0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('idx_payslips_employee_id', 'payslips', ['employee_id'])


def downgrade():
    op.drop_index('idx_payslips_employee_id', table_name='payslips')
