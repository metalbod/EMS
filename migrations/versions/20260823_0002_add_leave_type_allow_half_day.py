"""Add per-leave-type allow_half_day setting

Revision ID: 20260823_0002
Revises: 20260823_0001
Create Date: 2026-08-23

Half-day (AM/PM) applications previously used an implicit rule — only
offered for leave types that don't count calendar days
(count_calendar_days). This replaces that implicit rule with an explicit,
HR-configurable checkbox: allow_half_day is now the SOLE control over
whether a leave type supports half-day applications, defaulting to
allowed (checked) for every leave type, including existing calendar-day
types like Maternity/Paternity — HR can uncheck it per type if they want
the old restriction back.

A constant DEFAULT populates every existing row as part of the same
metadata-only ADD COLUMN, so no separate backfill UPDATE is needed.

No RLS policy change needed: leave_types already has a tenant_isolation
policy, and this migration only adds a column to that existing table.
"""
from alembic import op


revision = '20260823_0002'
down_revision = '20260823_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE leave_types ADD COLUMN IF NOT EXISTS allow_half_day INTEGER NOT NULL DEFAULT 1")


def downgrade():
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS allow_half_day")
