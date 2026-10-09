"""Zero the (previously ignored) annual_entitlement of leave types that share another type's entitlement

Revision ID: 20261009_0003
Revises: 20261009_0002
Create Date: 2026-10-09

A leave type with shares_entitlement_with_id draws its days from the other
type's pool, and until now its own annual_entitlement was hidden in the UI and
never read. It now means "this type's own yearly limit, inside the pool"
(0 = no limit of its own), so any figure those rows still hold (usually the
dialog's default of 14) would suddenly start capping people. Setting them to 0
keeps every existing shared type behaving exactly as before until HR enters a
real limit.
"""
from alembic import op

revision = '20261009_0003'
down_revision = '20261009_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE leave_types SET annual_entitlement = 0 WHERE shares_entitlement_with_id IS NOT NULL")


def downgrade():
    # The previous values were meaningless (never read), so there is nothing to restore.
    pass
