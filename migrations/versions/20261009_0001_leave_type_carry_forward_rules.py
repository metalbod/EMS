"""Leave type carry-forward: percentage base and how the two limits combine

Revision ID: 20261009_0001
Revises: 20261008_0002
Create Date: 2026-10-09

carry_forward_percent_basis: what "Max % carried" is a percentage OF —
  'balance'     the employee's unused balance at year end (the behaviour
                before this migration, so it is the default)
  'entitlement' the employee's own annual entitlement for the year being
                carried from, however much of it was used
carry_forward_cap_rule: when both "Max days carried" and "Max %" are set —
  'lower'  carry the lower of the two (the behaviour before this migration)
  'higher' carry the higher of the two
Either way the carry never exceeds the unused balance (see
core/leave_balance_ops.py's _compute_carry_forward). Defaults keep every
existing leave type behaving exactly as it did.
"""
from alembic import op

revision = '20261009_0001'
down_revision = '20261008_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leave_types
            ADD COLUMN IF NOT EXISTS carry_forward_percent_basis TEXT NOT NULL DEFAULT 'balance',
            ADD COLUMN IF NOT EXISTS carry_forward_cap_rule TEXT NOT NULL DEFAULT 'lower'
    """)
    op.execute("""
        ALTER TABLE leave_types
            ADD CONSTRAINT leave_types_carry_forward_percent_basis_check
                CHECK (carry_forward_percent_basis IN ('balance', 'entitlement')),
            ADD CONSTRAINT leave_types_carry_forward_cap_rule_check
                CHECK (carry_forward_cap_rule IN ('lower', 'higher'))
    """)


def downgrade():
    op.execute("ALTER TABLE leave_types DROP CONSTRAINT IF EXISTS leave_types_carry_forward_percent_basis_check")
    op.execute("ALTER TABLE leave_types DROP CONSTRAINT IF EXISTS leave_types_carry_forward_cap_rule_check")
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS carry_forward_percent_basis")
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS carry_forward_cap_rule")
