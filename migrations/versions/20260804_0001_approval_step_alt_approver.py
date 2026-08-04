"""Add alternative ("OR") approver to approval_workflow_steps

Revision ID: 20260804_0001
Revises: 20260803_0003
Create Date: 2026-08-04

Each step can now optionally name a second, alternative approver type
(alt_approver_type, using the same values as approver_type, plus
alt_specific_employee_id for the specific_employee case) — the step is
satisfied by whichever of the two acts first. Both nullable: a step with
no alt configured behaves exactly as before.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260804_0001'
down_revision = '20260803_0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('approval_workflow_steps', sa.Column('alt_approver_type', sa.String(30), nullable=True))
    op.add_column('approval_workflow_steps', sa.Column('alt_specific_employee_id', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('approval_workflow_steps', 'alt_specific_employee_id')
    op.drop_column('approval_workflow_steps', 'alt_approver_type')
