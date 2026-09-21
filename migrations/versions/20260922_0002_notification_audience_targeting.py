"""Add audience targeting to institution notifications

Revision ID: 20260922_0002
Revises: 20260922_0001
Create Date: 2026-09-22

Institution notifications (dashboard-banner announcements) were always
institution-wide. Adds a per-notification choice between 'everyone'
(unchanged default, existing rows all default here) and 'under' —
scoped to one or more anchor employees' entire downstream reporting
chain (each anchor included), unioned when multiple anchors are picked.

`institution_notifications.target_type` — plain column, since it's a
fixed institution-wide toggle-shaped value on the row itself, same
pattern as everything else on this table.

`institution_notification_targets` — a child table holding the picked
anchor employee_id(s) for 'under'-type notifications. Has no
institution_id of its own (like approval_workflow_steps), so it needs
an EXISTS-based RLS policy scoped through its parent notification
instead of the plain tenant_isolation form — see CLAUDE.md's "RLS fails
closed" gotcha and approval_workflow_steps' own policy
(20260803_0003_approval_workflow.py) for the pattern this mirrors.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260922_0002'
down_revision = '20260922_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.add_column('institution_notifications', sa.Column(
        'target_type', sa.String(10), nullable=False, server_default='everyone'
    ))

    op.create_table(
        'institution_notification_targets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('notification_id', sa.Integer(),
                  sa.ForeignKey('institution_notifications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
    )
    op.create_index('ix_institution_notification_targets_notification_id',
                    'institution_notification_targets', ['notification_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON institution_notification_targets
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM institution_notifications n
                WHERE n.id = institution_notification_targets.notification_id
                  AND n.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE institution_notification_targets FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE institution_notification_targets NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON institution_notification_targets")
    op.drop_index('ix_institution_notification_targets_notification_id', table_name='institution_notification_targets')
    op.drop_table('institution_notification_targets')
    op.drop_column('institution_notifications', 'target_type')
