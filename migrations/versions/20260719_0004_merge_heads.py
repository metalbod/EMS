"""Merge divergent migration heads (full_schema_ddl branch + compensation branch)

Revision ID: 20260719_0004
Revises: 20260717_0001, 20260719_0003
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260719_0004'
down_revision = ('20260717_0001', '20260719_0003')
branch_labels = None
depends_on = None


def upgrade():
    """No-op merge to unify two divergent migration heads."""
    pass


def downgrade():
    """No-op merge downgrade."""
    pass
