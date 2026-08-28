"""Add employees.tax_category (bootstrap-clean fix)

Revision ID: de442e62352a
Revises: 407db50b1f1f
Create Date: 2026-08-29 00:19:54.566890

Every real, already-migrated database (prod, the test Supabase project)
already has this column — it's live-used in EmployeeOut/routers/
employees.py and every `SELECT * FROM employees` call. It was never
actually added by any Alembic migration though, only out-of-band on real
databases at some point, which only surfaced while diagnosing the
from-scratch-bootstrap debt-ledger item: a fresh `alembic upgrade head`
against an empty database produces an employees table missing this
column, and every employee-listing endpoint 500s on the resulting
Pydantic ValidationError.

IF NOT EXISTS makes this a no-op everywhere it already exists; only a
brand-new from-scratch environment actually gets the column added.
routers/payroll.py separately derives an equivalent value from
marital_status for PCB calculation — this column is the one the API
response model itself reads, not payroll's calculation.
"""
from alembic import op


revision = 'de442e62352a'
down_revision = '407db50b1f1f'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS tax_category TEXT NOT NULL DEFAULT 'Single'")


def downgrade():
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS tax_category")
