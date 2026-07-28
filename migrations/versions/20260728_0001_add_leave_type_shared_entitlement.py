"""Add shares_entitlement_with_id to leave_types

Revision ID: 20260728_0001
Revises: 20260727_0004
Create Date: 2026-07-28

Lets a leave type (e.g. "Emergency Leave") draw down the same balance
pool as another leave type (e.g. "Annual Leave") instead of tracking its
own entitlement. The application record still stores the specific leave
type applied for (so history/reports show "Emergency Leave" distinctly);
only the balance check and days-used deduction resolve to the shared
type. Deliberately one level deep only — a type that already shares with
something can't itself be chosen as a share target, and a type that's
already a share target can't be set to share with something else. Both
directions are enforced in the API layer (routers/leave.py), not here.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260728_0001'
down_revision = '20260727_0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('leave_types', sa.Column('shares_entitlement_with_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'leave_types_shares_entitlement_with_id_fkey', 'leave_types',
        'leave_types', ['shares_entitlement_with_id'], ['id'], ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('leave_types_shares_entitlement_with_id_fkey', 'leave_types', type_='foreignkey')
    op.drop_column('leave_types', 'shares_entitlement_with_id')
