"""Add leave carry-forward policy and tracking columns

Revision ID: 20260803_0002
Revises: 20260803_0001
Create Date: 2026-08-03

Two new leave_types policy fields govern how much unused balance rolls
into the next year:
  - carry_forward_enabled: off by default — most leave types (Medical,
    Maternity, etc.) shouldn't carry forward at all.
  - carry_forward_max_days / carry_forward_max_percent: both 0 means
    "uncapped" (matches how max_days_per_application/max_days_per_month
    already treat 0 as unconfigured on this table — see 20260729_0001).
    When either is set, the actual amount carried is
    min(unused_balance, max_days if set, unused_balance * max_percent/100
    if set) — whichever cap bites hardest.
  - carry_forward_expiry_days: 0 means the carried-forward balance never
    expires; otherwise it must be used within that many days of the new
    year (Jan 1) before being forfeited.

On leave_balances, three columns track a given year's carried-forward
bucket separately from the running `used_days` total (which stays the
combined figure — see routers/leave.py's _consume_balance/_release_balance):
  - carried_forward_used_days: how much of carried_forward_days has been
    consumed — carry-forward is always drawn down before the fresh
    annual_entitlement (see the deduction helpers), so this is also what
    determines how much is left to expire.
  - carried_forward_expires_on: computed once, at the row's creation
    (rollover) time, from the leave type's carry_forward_expiry_days —
    NULL means no expiry.
  - carried_forward_forfeited_days: running total of carried-forward days
    that expired unused, for audit/reporting — set once by the lazy
    expiry sweep (see routers/leave.py's _sweep_expired_carry_forward),
    which also zeroes out the remaining carried_forward_days so it stops
    counting toward available balance.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260803_0002'
down_revision = '20260803_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('leave_types', sa.Column('carry_forward_enabled', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('leave_types', sa.Column('carry_forward_max_days', sa.Float(), nullable=False, server_default='0'))
    op.add_column('leave_types', sa.Column('carry_forward_max_percent', sa.Float(), nullable=False, server_default='0'))
    op.add_column('leave_types', sa.Column('carry_forward_expiry_days', sa.Integer(), nullable=False, server_default='0'))

    op.add_column('leave_balances', sa.Column('carried_forward_used_days', sa.Float(), nullable=False, server_default='0'))
    op.add_column('leave_balances', sa.Column('carried_forward_expires_on', sa.String(10), nullable=True))
    op.add_column('leave_balances', sa.Column('carried_forward_forfeited_days', sa.Float(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('leave_balances', 'carried_forward_forfeited_days')
    op.drop_column('leave_balances', 'carried_forward_expires_on')
    op.drop_column('leave_balances', 'carried_forward_used_days')

    op.drop_column('leave_types', 'carry_forward_expiry_days')
    op.drop_column('leave_types', 'carry_forward_max_percent')
    op.drop_column('leave_types', 'carry_forward_max_days')
    op.drop_column('leave_types', 'carry_forward_enabled')
