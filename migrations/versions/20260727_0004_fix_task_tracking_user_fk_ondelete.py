"""Fix task_tracking.user_id FK to ON DELETE CASCADE

Revision ID: 20260727_0004
Revises: 20260727_0003
Create Date: 2026-07-27

Same category of bug as 20260726_0001/20260727_0001, just discovered via a
fresh CI failure right after task_tracking was backfilled: user_id has no
ON DELETE clause (defaulting to NO ACTION), so deleting a disposable test
user fails with ForeignKeyViolation on task_tracking_user_id_fkey the
moment that user has ever queued a payroll run or bulk upload.

Unlike those other columns, user_id is NOT NULL here (every task_tracking
row must have an owning user), so SET NULL isn't an option — a task
record whose owner was deleted has no remaining meaning, so CASCADE is
the right choice instead.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260727_0004'
down_revision = '20260727_0003'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('task_tracking_user_id_fkey', 'task_tracking', type_='foreignkey')
    op.create_foreign_key(
        'task_tracking_user_id_fkey', 'task_tracking',
        'users', ['user_id'], ['id'], ondelete='CASCADE',
    )


def downgrade():
    op.drop_constraint('task_tracking_user_id_fkey', 'task_tracking', type_='foreignkey')
    op.create_foreign_key(
        'task_tracking_user_id_fkey', 'task_tracking',
        'users', ['user_id'], ['id'],
    )
