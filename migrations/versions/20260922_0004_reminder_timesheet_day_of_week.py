"""Add configurable day-of-week for the timesheet reminder sweep

Revision ID: 20260922_0004
Revises: 20260922_0003
Create Date: 2026-09-22

The timesheet reminder was hardcoded to fire on Monday only
(core/tasks.py's reminder_sweep_timesheets checked
`local_now.weekday() != 0`) — this makes that day configurable per
institution too, alongside the hour added in 20260922_0003. 0=Monday..
6=Sunday, matching Python's own `date.weekday()` (what the task already
compares against), not ISO-8601's 1-7.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260922_0004'
down_revision = '20260922_0003'
branch_labels = None
depends_on = None

_COLUMN = 'reminder_timesheet_day_of_week'


def upgrade():
    op.add_column('institutions', sa.Column(_COLUMN, sa.Integer(), nullable=False, server_default='0'))
    op.create_check_constraint(f'ck_institutions_{_COLUMN}_range', 'institutions', f'{_COLUMN} >= 0 AND {_COLUMN} <= 6')


def downgrade():
    op.drop_constraint(f'ck_institutions_{_COLUMN}_range', 'institutions', type_='check')
    op.drop_column('institutions', _COLUMN)
