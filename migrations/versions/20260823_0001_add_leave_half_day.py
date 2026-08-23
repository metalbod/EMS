"""Add half-day (AM/PM) support to leave applications

Revision ID: 20260823_0001
Revises: 20260822_0002
Create Date: 2026-08-23

Leave applications previously only supported whole-day increments across
a date range. This adds start_day_period / end_day_period (NULL / 'AM' /
'PM') to leave_applications so an employee can mark the start and/or end
date of a range as a half-day, independently of each other. A single-day
application (start_date == end_date) only ever uses start_day_period —
end_day_period is constrained to NULL in that case, enforced below.

No RLS policy change needed: leave_applications already has a
tenant_isolation policy from eb95a484c74a_add_rls_tenant_isolation_
policies.py, and this migration only adds columns to that existing
table, not a new one. No backfill needed either — existing rows get
NULL/NULL, identical to today's implicit "full day" behavior.
"""
from alembic import op


revision = '20260823_0001'
down_revision = '20260822_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE leave_applications ADD COLUMN IF NOT EXISTS start_day_period TEXT")
    op.execute("ALTER TABLE leave_applications ADD COLUMN IF NOT EXISTS end_day_period TEXT")
    op.execute("ALTER TABLE leave_applications DROP CONSTRAINT IF EXISTS leave_applications_start_day_period_check")
    op.execute(
        "ALTER TABLE leave_applications ADD CONSTRAINT leave_applications_start_day_period_check "
        "CHECK (start_day_period IS NULL OR start_day_period IN ('AM','PM'))"
    )
    op.execute("ALTER TABLE leave_applications DROP CONSTRAINT IF EXISTS leave_applications_end_day_period_check")
    op.execute(
        "ALTER TABLE leave_applications ADD CONSTRAINT leave_applications_end_day_period_check "
        "CHECK (end_day_period IS NULL OR end_day_period IN ('AM','PM'))"
    )
    op.execute("ALTER TABLE leave_applications DROP CONSTRAINT IF EXISTS leave_applications_end_day_period_single_day_check")
    op.execute(
        "ALTER TABLE leave_applications ADD CONSTRAINT leave_applications_end_day_period_single_day_check "
        "CHECK (end_day_period IS NULL OR start_date <> end_date)"
    )


def downgrade():
    op.execute("ALTER TABLE leave_applications DROP CONSTRAINT IF EXISTS leave_applications_end_day_period_single_day_check")
    op.execute("ALTER TABLE leave_applications DROP CONSTRAINT IF EXISTS leave_applications_end_day_period_check")
    op.execute("ALTER TABLE leave_applications DROP CONSTRAINT IF EXISTS leave_applications_start_day_period_check")
    op.execute("ALTER TABLE leave_applications DROP COLUMN IF EXISTS end_day_period")
    op.execute("ALTER TABLE leave_applications DROP COLUMN IF EXISTS start_day_period")
