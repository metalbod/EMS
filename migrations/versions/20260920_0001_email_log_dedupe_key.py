"""Add dedupe_key to email_log (Phase 2 reminder sweep)

Revision ID: 20260920_0001
Revises: 20260919_0001
Create Date: 2026-09-20

Phase 1's email_log has no column identifying which specific *item* an
email was about (only institution_id/module/category/recipient_email) —
fine for one-shot approval emails, but Phase 2's reminder sweep
(scripts/send_reminders.py) needs to answer "have I already reminded
this person about this exact overdue checklist item / this exact
missed timesheet period recently?" without re-sending every time it
runs. dedupe_key carries that identity (e.g. 'item:123' or
'EMP001:2026-09-14') — nullable and unused by Phase 1's own approval
emails, which never set it.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260920_0001'
down_revision = '20260919_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('email_log', sa.Column('dedupe_key', sa.String(100), nullable=True))
    op.create_index('ix_email_log_dedupe', 'email_log', ['institution_id', 'category', 'dedupe_key'])


def downgrade():
    op.drop_index('ix_email_log_dedupe', table_name='email_log')
    op.drop_column('email_log', 'dedupe_key')
