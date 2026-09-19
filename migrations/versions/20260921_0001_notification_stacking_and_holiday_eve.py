"""Add institution timezone and holiday-eve announcement toggle

Revision ID: 20260921_0001
Revises: 20260920_0001
Create Date: 2026-09-21

Two additions, both on `institutions`:

- `timezone` (IANA name, e.g. 'Asia/Kuala_Lumpur') — a genuinely new
  concept for this codebase; every date/time comparison elsewhere is
  naive UTC. Defaults to 'UTC' so the holiday-eve check below still
  degrades gracefully (just computed against UTC midnight) for an
  institution that hasn't set this yet, rather than being disabled
  outright.
- `holiday_eve_announcements_enabled` — the Settings -> Notifications
  toggle for the "public holiday tomorrow" banner (see
  routers/notifications.py's _holiday_eve_virtual_notification). That
  banner is computed live on every GET /api/notifications/active call,
  never stored as a real institution_notifications row — no schema
  needed for the announcement itself, only for whether it's turned on
  and which timezone "tomorrow" is computed in.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260921_0001'
down_revision = '20260920_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('institutions', sa.Column('timezone', sa.String(60), nullable=False, server_default='UTC'))
    op.add_column('institutions', sa.Column('holiday_eve_announcements_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('institutions', 'holiday_eve_announcements_enabled')
    op.drop_column('institutions', 'timezone')
