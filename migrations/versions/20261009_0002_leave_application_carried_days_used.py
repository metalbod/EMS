"""Record how many days of each leave application came from carried-forward leave

Revision ID: 20261009_0002
Revises: 20261009_0001
Create Date: 2026-10-09

leave_applications.carried_days_used: of the application's days_count, how
many were deducted from the carried-forward bucket (the rest came out of the
year's entitlement). Set when the leave is approved/auto-approved; NULL on
applications approved before this migration, which fall back to the old
"give back to the carried bucket first" behaviour on cancellation. Cancelling
returns exactly this split — and, if the carry has expired by then, lets those
days lapse instead of resurrecting them.
"""
from alembic import op

revision = '20261009_0002'
down_revision = '20261009_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE leave_applications ADD COLUMN IF NOT EXISTS carried_days_used REAL")


def downgrade():
    op.execute("ALTER TABLE leave_applications DROP COLUMN IF EXISTS carried_days_used")
