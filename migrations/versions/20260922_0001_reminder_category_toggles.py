"""Add per-category email reminder toggles

Revision ID: 20260922_0001
Revises: 20260921_0001
Create Date: 2026-09-22

Five new booleans on `institutions`, one per reminder category
(scripts/send_reminders.py). Each narrows — never replaces — the
existing master `notifications_email_enabled` toggle: a category's
email only ever sends when both it and the master toggle are on.

`reminder_timesheet_enabled` / `reminder_onboarding_enabled` /
`reminder_offboarding_enabled` default true — these three reminders
already run live in production today, so shipping this migration must
not silently stop them for institutions that already opted in via the
master toggle.

`reminder_holidays_enabled` (a new email reminder, independent of the
pre-existing `holiday_eve_announcements_enabled` dashboard-banner
toggle) and `reminder_acknowledgement_enabled` (stored ahead of the
"document acknowledgement" feature it will eventually gate — nothing
reads it yet) default false since both are net-new, opt-in surfaces.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260922_0001'
down_revision = '20260921_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('institutions', sa.Column('reminder_timesheet_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('institutions', sa.Column('reminder_onboarding_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('institutions', sa.Column('reminder_offboarding_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('institutions', sa.Column('reminder_holidays_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('institutions', sa.Column('reminder_acknowledgement_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('institutions', 'reminder_acknowledgement_enabled')
    op.drop_column('institutions', 'reminder_holidays_enabled')
    op.drop_column('institutions', 'reminder_offboarding_enabled')
    op.drop_column('institutions', 'reminder_onboarding_enabled')
    op.drop_column('institutions', 'reminder_timesheet_enabled')
