"""Add per-institution, per-category reminder sweep hours

Revision ID: 20260922_0003
Revises: 20260922_0002
Create Date: 2026-09-22

The reminder sweeps (core/tasks.py's Celery beat tasks) used to fire at
one hardcoded hour (08:00 Asia/Kuala_Lumpur) baked into the beat
schedule, the same for every institution. This makes that hour a
per-institution, per-category setting instead (Settings -> Notifications
-> Reminders tab), read in the institution's own `timezone` column.

No `reminder_acknowledgement_hour` — that category's toggle is already
disabled/unused (see routers/notifications.py's
`update_reminder_settings` docstring; nothing reads it, the feature it
will gate doesn't exist yet), so it gets no hour column either until it
does something.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260922_0003'
down_revision = '20260922_0002'
branch_labels = None
depends_on = None

_COLUMNS = (
    'reminder_timesheet_hour', 'reminder_onboarding_hour',
    'reminder_offboarding_hour', 'reminder_holidays_hour',
)


def upgrade():
    for col in _COLUMNS:
        op.add_column('institutions', sa.Column(col, sa.Integer(), nullable=False, server_default='8'))
        op.create_check_constraint(f'ck_institutions_{col}_range', 'institutions', f'{col} >= 0 AND {col} <= 23')


def downgrade():
    for col in _COLUMNS:
        op.drop_constraint(f'ck_institutions_{col}_range', 'institutions', type_='check')
        op.drop_column('institutions', col)
