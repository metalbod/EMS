"""Add institutions.reminder_acknowledgement_hour

Revision ID: 20261014_0001
Revises: 20261013_0001
Create Date: 2026-10-14

Policy acknowledgement reminders (scripts/send_reminders.py's sweep_pending_policies, run by
core/tasks.py's reminder_sweep_policies) now exist, so the Acknowledgement category gets the
same per-institution sweep hour as the others (Settings -> Notifications -> Reminders). Default
9 (a working-hours nudge); the toggle itself stays opt-in (default off).
"""
from alembic import op
import sqlalchemy as sa

revision = '20261014_0001'
down_revision = '20261013_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('institutions', sa.Column('reminder_acknowledgement_hour', sa.Integer(), nullable=False, server_default='9'))
    op.create_check_constraint('ck_institutions_reminder_acknowledgement_hour_range', 'institutions',
                               'reminder_acknowledgement_hour >= 0 AND reminder_acknowledgement_hour <= 23')


def downgrade():
    op.drop_constraint('ck_institutions_reminder_acknowledgement_hour_range', 'institutions', type_='check')
    op.drop_column('institutions', 'reminder_acknowledgement_hour')
