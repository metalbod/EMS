"""Add employees.resign_date

Revision ID: 20260821_0001
Revises: 04db46c11d4a
Create Date: 2026-08-21

Plain, manually-entered date field alongside start_date/probation_end_date
/contract_end_date — nothing here auto-populates it from the employee's
status toggle (Active/Inactive) or the offboarding module; HR fills it in
directly. Editing is gated to CAN_WRITE (superadmin/hr_manager/hr_admin)
in routers/employees.py, same as every other employee field — manager and
employee can view it (same visibility as start_date etc.) but never had
write access to the employee record in the first place, so no separate
per-field permission check was needed.
"""
from alembic import op


revision = '20260821_0001'
down_revision = '04db46c11d4a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS resign_date TEXT")


def downgrade():
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS resign_date")
