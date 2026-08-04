"""Add generic approval-workflow engine (workflows, steps, per-record tracking)

Revision ID: 20260803_0003
Revises: 20260803_0002
Create Date: 2026-08-03

Every approval gate in this codebase (Leave, Benefits Claims, Job
Requisition, Timesheet, L&D Enrollment) previously hardcoded its own
single-step role check — e.g. "user.role in (manager, hr_manager,
hr_admin)" — with no check that an approving "manager" was the
requester's *actual* manager. This adds a real, per-institution
configurable engine:

  - approval_workflows: one named, orderable chain per institution+module
    (module = 'leave'|'claims'|'requisition'|'timesheet'|'ld_enrollment').
    Lazily created with a 2-step default (Direct Manager -> HR) the first
    time a module needs one — see core/approval_workflow.py's
    get_or_create_default_workflow — not seeded here.
  - approval_workflow_steps: ordered steps within a workflow. approver_type
    is one of direct_manager / skip_level_manager / hr_manager /
    specific_employee (the last using specific_employee_id).

Each of the 5 request tables gets two columns to track progress against
whichever workflow it's running: approval_workflow_id (snapshotted at
submission so editing the workflow later doesn't reshuffle in-flight
requests) and approval_step (which step is currently pending; NULL once
the request leaves Pending-ish states). Both nullable/defaulted so
existing rows aren't broken — see core/approval_workflow.py for how
already-pending rows get backfilled onto the default workflow lazily.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260803_0003'
down_revision = '20260803_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"
_REQUEST_TABLES = ("leave_applications", "benefit_claims", "job_requisitions", "timesheets", "ld_enrollments")


def upgrade():
    op.create_table(
        'approval_workflows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('module', sa.String(30), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('is_default', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_approval_workflows_inst_module', 'approval_workflows', ['institution_id', 'module'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON approval_workflows
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE approval_workflows FORCE ROW LEVEL SECURITY")

    op.create_table(
        'approval_workflow_steps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('approval_workflows.id'), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column('approver_type', sa.String(30), nullable=False),
        sa.Column('specific_employee_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_approval_workflow_steps_workflow_id', 'approval_workflow_steps', ['workflow_id'])
    # approval_workflow_steps has no institution_id of its own, but the
    # ensure_rls event trigger enables RLS on every new table regardless —
    # with zero policies that fails CLOSED (every query gets 0 rows / every
    # insert is denied), not open. Needs an explicit EXISTS-based policy
    # scoped through its parent workflow, same pattern as okr_key_results'
    # policy in eb95a484c74a_add_rls_tenant_isolation_policies.py.
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON approval_workflow_steps
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM approval_workflows w
                WHERE w.id = approval_workflow_steps.workflow_id
                  AND w.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE approval_workflow_steps FORCE ROW LEVEL SECURITY")

    for tbl in _REQUEST_TABLES:
        op.add_column(tbl, sa.Column('approval_workflow_id', sa.Integer(), nullable=True))
        op.add_column(tbl, sa.Column('approval_step', sa.Integer(), nullable=True))


def downgrade():
    for tbl in _REQUEST_TABLES:
        op.drop_column(tbl, 'approval_step')
        op.drop_column(tbl, 'approval_workflow_id')

    op.execute("ALTER TABLE approval_workflow_steps NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON approval_workflow_steps")
    op.drop_index('ix_approval_workflow_steps_workflow_id', table_name='approval_workflow_steps')
    op.drop_table('approval_workflow_steps')

    op.execute("ALTER TABLE approval_workflows NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON approval_workflows")
    op.drop_index('ix_approval_workflows_inst_module', table_name='approval_workflows')
    op.drop_table('approval_workflows')
