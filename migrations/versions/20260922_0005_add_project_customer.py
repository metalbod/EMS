"""Add optional customer tag to projects

Revision ID: 20260922_0005
Revises: 20260922_0004
Create Date: 2026-09-22

Free-text, optional (`nullable=True`, no default) — no dedicated
customers table, mirrors how `description` already works. The
Timesheet -> Projects screen's "previously tagged customer names"
suggestion list is derived client-side from already-loaded projects
(static/js/timesheet.js), not a separate endpoint, so no supporting
table/index is needed here.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260922_0005'
down_revision = '20260922_0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('customer', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('projects', 'customer')
