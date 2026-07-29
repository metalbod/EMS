"""Add approved_at to leave_applications

Revision ID: 20260728_0003
Revises: 20260728_0002
Create Date: 2026-07-28

leave_applications had no timestamp for when an application was actually
approved — only approved_by (username, no time) and created_at (when it
was applied for). The employee-facing "My Leave" dashboard needs both
"applied when" and "approved when" for its history table, so this adds
a proper column instead of parsing leave_audit_log's free-text detail
strings for an "Approved" entry.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260728_0003'
down_revision = '20260728_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('leave_applications', sa.Column('approved_at', sa.String(19), nullable=True))


def downgrade():
    op.drop_column('leave_applications', 'approved_at')
