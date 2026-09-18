"""Add flat/sequential mode to approval workflows

Revision ID: 20260918_0002
Revises: 20260918_0001
Create Date: 2026-09-18

Every approval workflow was purely sequential: step 1 must clear before
step 2 becomes actionable, and so on. This adds a per-workflow `mode`
('sequential' | 'flat') — 'sequential' is the default, so every existing
workflow keeps its exact current behavior. 'flat' lets every step with a
nonempty approver pool act at once, finalizing once all of them have
approved (a reject at any one is still immediately terminal).

A flat row's own approval_step column can't represent "several steps
open at once" — it stays a non-null "still pending" placeholder only —
so approval_step_decisions tracks each individual step's decision,
generically keyed by (request_table, request_id, step_order) the same
way approval_workflow_steps is generically keyed by workflow_id. See
core/approval_workflow.py's module docstring and advance_or_finalize.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260918_0002'
down_revision = '20260918_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.add_column('approval_workflows', sa.Column(
        'mode', sa.String(20), nullable=False, server_default='sequential'
    ))

    op.create_table(
        'approval_step_decisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('module', sa.String(30), nullable=False),
        sa.Column('request_table', sa.String(60), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),  # 'approved' | 'rejected'
        sa.Column('decided_by', sa.String(100), nullable=False),
        sa.Column('decided_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
        sa.UniqueConstraint('request_table', 'request_id', 'step_order', name='uq_approval_step_decision'),
    )
    op.create_index('ix_approval_step_decisions_request', 'approval_step_decisions', ['request_table', 'request_id'])
    op.create_index('ix_approval_step_decisions_institution_id', 'approval_step_decisions', ['institution_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON approval_step_decisions
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE approval_step_decisions FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE approval_step_decisions NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON approval_step_decisions")
    op.drop_table('approval_step_decisions')
    op.drop_column('approval_workflows', 'mode')
