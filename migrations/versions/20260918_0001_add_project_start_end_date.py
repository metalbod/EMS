"""Add start_date/end_date to projects (informational only)

Revision ID: 20260918_0001
Revises: 20260917_0001
Create Date: 2026-09-18

Project-level start_date/end_date are informational only — they are not
checked against timesheet entries. Project tasks' own start_date/end_date
(added earlier) are validated against these project dates instead, in
routers/projects.py's create_project_task/update_project_task.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260918_0001'
down_revision = '20260917_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('start_date', sa.String(10), nullable=True))
    op.add_column('projects', sa.Column('end_date', sa.String(10), nullable=True))


def downgrade():
    op.drop_column('projects', 'end_date')
    op.drop_column('projects', 'start_date')
