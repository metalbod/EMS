"""Add count_calendar_days to leave_types

Revision ID: 20260728_0002
Revises: 20260728_0001
Create Date: 2026-07-28

Most leave types (Annual, Medical, etc.) deduct working days — weekends
and public holidays don't count. Malaysian law counts Maternity/
Paternity leave in calendar days instead (every day in the range counts,
weekends and holidays included). Defaults to false (working days) so
every existing leave type keeps its current behavior unchanged.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260728_0002'
down_revision = '20260728_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'leave_types',
        sa.Column('count_calendar_days', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_column('leave_types', 'count_calendar_days')
