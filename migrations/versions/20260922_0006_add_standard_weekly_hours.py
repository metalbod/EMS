"""Add standard weekly hours setting for the Missing Hours calculation

Revision ID: 20260922_0006
Revises: 20260922_0005
Create Date: 2026-09-22

Institution-wide, single value (Mon-Fri working days assumed, matching
how routers/leave.py's _compute_leave_days already treats weekends/
holidays elsewhere in this app) — not per-employee. See
routers/timesheets.py's _weekly_hours_breakdown, which uses this to
compute My Timesheet's new "Missing hours" line and the auto-populated
public-holiday/approved-leave rows.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260922_0006'
down_revision = '20260922_0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('institutions', sa.Column('standard_weekly_hours', sa.Numeric(5, 2), nullable=False, server_default='40.00'))


def downgrade():
    op.drop_column('institutions', 'standard_weekly_hours')
