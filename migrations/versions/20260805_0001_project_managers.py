"""Add project managers and project_id routing on Leave/Claims

Revision ID: 20260805_0001
Revises: 20260804_0001
Create Date: 2026-08-05

Adds a "project_manager" approver type (leave/claims/timesheet only —
see core/approval_workflow.py's PROJECT_MANAGER_MODULES):

  - project_managers: many-to-many, a project can have multiple managers.
  - leave_applications.project_id / benefit_claims.project_id: which
    project (of the ones the requester belongs to) a project_manager step
    should route through. Nullable — only used when the applicable
    workflow actually has a project_manager step; NULL just makes that
    step's pool empty and it auto-skips like any other empty step.

Timesheet needs no new column: it already tracks project_id per
timesheet_entries row, and a project_manager step there resolves against
the union of projects logged that week (see
core/approval_workflow.py's _project_ids_for_row).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260805_0001'
down_revision = '20260804_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'project_managers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_project_managers_project_id', 'project_managers', ['project_id'])
    op.create_unique_constraint('uq_project_managers_project_employee', 'project_managers', ['project_id', 'employee_id'])
    # No institution_id of its own — scope through the parent project, same
    # pattern as approval_workflow_steps (see 20260803_0003).
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON project_managers
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM projects p
                WHERE p.id = project_managers.project_id
                  AND p.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE project_managers FORCE ROW LEVEL SECURITY")

    op.add_column('leave_applications', sa.Column('project_id', sa.Integer(), nullable=True))
    op.add_column('benefit_claims', sa.Column('project_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('benefit_claims', 'project_id')
    op.drop_column('leave_applications', 'project_id')

    op.execute("ALTER TABLE project_managers NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON project_managers")
    op.drop_constraint('uq_project_managers_project_employee', 'project_managers', type_='unique')
    op.drop_index('ix_project_managers_project_id', table_name='project_managers')
    op.drop_table('project_managers')
