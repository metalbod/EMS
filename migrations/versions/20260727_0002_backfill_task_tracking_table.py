"""Backfill missing task_tracking table

Revision ID: 20260727_0002
Revises: 20260727_0001
Create Date: 2026-07-27

alembic_version has reported a1b2c3d4e5f6 (and everything after it) as
applied, but task_tracking never actually existed on the live DB —
to_regclass('public.task_tracking') returns NULL. Same root cause noted in
20260727_0001's docstring: this DB was bootstrapped from a schema snapshot
rather than a literal replay of every migration, and that snapshot predated
this table. Every INSERT INTO task_tracking in routers/payroll.py and
routers/employees.py has been silently failing (caught by a bare
`except: pass`) ever since, so task polling has never actually worked.

Uses checkfirst=True so this is safe to re-run / safe if some environment's
snapshot did include the table after all.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260727_0002'
down_revision = '20260727_0001'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'task_tracking' in inspector.get_table_names():
        return

    op.create_table(
        'task_tracking',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=True),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False, server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
        sa.Column('updated_at', sa.String(19), nullable=False, server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('idx_task_tracking_user_id', 'task_tracking', ['user_id'])
    op.create_index('idx_task_tracking_institution_id', 'task_tracking', ['institution_id'])
    op.create_index('idx_task_tracking_task_type', 'task_tracking', ['task_type'])


def downgrade():
    op.drop_table('task_tracking')
