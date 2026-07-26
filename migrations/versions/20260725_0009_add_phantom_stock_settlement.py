"""Add phantom stock settlement fields to equity vesting events

Revision ID: 20260725_0009
Revises: 20260725_0008
Create Date: 2026-07-25

Phantom stock is cash-settled: the employee never receives actual shares
or options, so "Vested" can't be the terminal state the way it is for
RSU/ISO/NSO/ESPP — there's a further settlement step where the company
pays cash equal to the appreciated value of the phantom units. This adds
that as a second leg on equity_vesting_events (settlement_price,
cash_payout, payout_date) rather than a new table, since it's still one
row per tranche — Scheduled -> Vested -> Paid for phantom grants,
Scheduled -> Vested (terminal) for everything else.

No RLS change needed — these are new nullable columns on an existing
RLS-protected table, not a new table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0009'
down_revision = '20260725_0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('equity_vesting_events', sa.Column('settlement_price', sa.Numeric(12, 4), nullable=True))
    op.add_column('equity_vesting_events', sa.Column('cash_payout', sa.Numeric(12, 2), nullable=True))
    op.add_column('equity_vesting_events', sa.Column('payout_date', sa.String(10), nullable=True))


def downgrade():
    op.drop_column('equity_vesting_events', 'payout_date')
    op.drop_column('equity_vesting_events', 'cash_payout')
    op.drop_column('equity_vesting_events', 'settlement_price')
