"""Add institutions.statutory_remittance_day

Revision ID: 20260928_0001
Revises: 20260927_0001
Create Date: 2026-09-28

The Home page's payroll strip shows a reminder for the day of each month by
which EPF / SOCSO / EIS / PCB remittances are due. Payroll itself models no
statutory dates (payroll_calc.py only approximates the amounts), so this is a
per-institution, payroll-manager-editable setting, defaulting to the 15th — a
reminder day, not a compliance calculation. Limited to 1..28 so it exists in
every month without clamping.

`institutions.pay_day` already exists (NOT NULL DEFAULT 25) but had no writer
anywhere in the app; it becomes editable alongside this setting (see
routers/payroll.py's /api/payroll/settings), so no schema change is needed for it.
"""
from alembic import op

revision = '20260928_0001'
down_revision = '20260927_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS statutory_remittance_day INTEGER NOT NULL DEFAULT 15")
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE institutions ADD CONSTRAINT institutions_statutory_remittance_day_range
                CHECK (statutory_remittance_day BETWEEN 1 AND 28);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)


def downgrade():
    op.execute("ALTER TABLE institutions DROP CONSTRAINT IF EXISTS institutions_statutory_remittance_day_range")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS statutory_remittance_day")
