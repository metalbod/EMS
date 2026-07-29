"""Add accrual_mode, max_days_per_application, max_days_per_month to leave_types

Revision ID: 20260729_0001
Revises: 20260728_0003
Create Date: 2026-07-29

accrual_mode: 'full_year' (default — the whole annual_entitlement is
available from day one, today's only behavior) or 'monthly' (earn-as-
-you-work — available balance accrues 1/12th per calendar month,
pro-rated from the employee's join date in their first year).

max_days_per_application / max_days_per_month: 0 (default) means
unconfigured/unlimited, matching how annual_entitlement already treats
0 as "no real entitlement" rather than needing a separate nullable
sentinel — consistent with the rest of this table's numeric columns.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260729_0001'
down_revision = '20260728_0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('leave_types', sa.Column('accrual_mode', sa.String(20), nullable=False, server_default='full_year'))
    op.add_column('leave_types', sa.Column('max_days_per_application', sa.Float(), nullable=False, server_default='0'))
    op.add_column('leave_types', sa.Column('max_days_per_month', sa.Float(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('leave_types', 'max_days_per_month')
    op.drop_column('leave_types', 'max_days_per_application')
    op.drop_column('leave_types', 'accrual_mode')
