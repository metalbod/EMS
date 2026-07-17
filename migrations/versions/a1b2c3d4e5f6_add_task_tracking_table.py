"""Add task tracking table for async operations.

Task tracking enables monitoring long-running async operations (payroll runs,
bulk uploads) and returning 202 Accepted to clients immediately, with a way
to poll for completion via GET /api/tasks/{task_id}.

Revision ID: a1b2c3d4e5f6
Revises: 9e7c3b2d1a4f
Create Date: 2026-07-17 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9e7c3b2d1a4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'task_tracking',
        sa.Column('id', sa.String(36), primary_key=True),  # Celery task UUID
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=True),
        sa.Column('task_type', sa.String(50), nullable=False),  # 'payroll_run', 'bulk_upload', etc.
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending, started, success, failure
        sa.Column('result', sa.Text(), nullable=True),  # JSON serialized result
        sa.Column('error', sa.Text(), nullable=True),  # Error message if failed
        sa.Column('created_at', sa.String(19), nullable=False, server_default="to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
        sa.Column('updated_at', sa.String(19), nullable=False, server_default="to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"),
    )
    op.create_index('idx_task_tracking_user_id', 'task_tracking', ['user_id'])
    op.create_index('idx_task_tracking_institution_id', 'task_tracking', ['institution_id'])
    op.create_index('idx_task_tracking_task_type', 'task_tracking', ['task_type'])


def downgrade() -> None:
    op.drop_table('task_tracking')
