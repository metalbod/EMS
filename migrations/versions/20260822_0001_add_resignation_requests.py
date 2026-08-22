"""Add Employee Resignation module (last_working_day + resignation_requests)

Revision ID: 20260822_0001
Revises: 20260821_0002
Create Date: 2026-08-22

Employee (self-service, Home dashboard "Resign" button) or HR (on an
employee's behalf, from Employee detail) files a resignation — reason,
effective date (default "immediately"), a required last working day
(distinct from effective date: a notice period can push the actual last
day out weeks past when the resignation becomes effective), and an
optional attachment (resignation letter). Routed through its own
configurable approval workflow (module='resignation' in
core/approval_workflow.py, same generic engine as Leave/Overtime/etc.).

On final approval (core/resignation.py's _finalize_resignation):
employees.resign_date = effective_date, employees.last_working_day =
last_working_day, and an Offboarding checklist is auto-started from the
institution's default Offboarding template (routers/onboarding.py's
_create_ob_checklist, factored out of start_ob_checklist for this).
Employee status is left untouched — no cron job in this codebase to act
on a future last_working_day automatically, so HR deactivates manually,
on/after that date, same as they do today.

resignation_requests has its own institution_id, so it gets the standard
tenant_isolation RLS policy, same shape as overtime_records
(20260806_0001).
"""
from alembic import op
import sqlalchemy as sa


revision = '20260822_0001'
down_revision = '20260821_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS last_working_day TEXT")

    op.create_table(
        'resignation_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('effective_date', sa.String(10), nullable=False),
        sa.Column('last_working_day', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),
        sa.Column('attachment_file_name', sa.Text(), nullable=True),
        sa.Column('attachment_mime_type', sa.Text(), nullable=True),
        sa.Column('attachment_data_url', sa.Text(), nullable=True),
        sa.Column('submitted_by', sa.String(100), nullable=False),
        sa.Column('approval_workflow_id', sa.Integer(), nullable=True),
        sa.Column('approval_step', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('ob_checklist_id', sa.Integer(), nullable=True),
        sa.Column('decided_by', sa.String(100), nullable=True),
        sa.Column('decided_at', sa.String(19), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_resignation_requests_employee_id', 'resignation_requests', ['employee_id'])
    op.create_index('ix_resignation_requests_institution_id', 'resignation_requests', ['institution_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON resignation_requests
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE resignation_requests FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE resignation_requests NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON resignation_requests")
    op.drop_index('ix_resignation_requests_institution_id', table_name='resignation_requests')
    op.drop_index('ix_resignation_requests_employee_id', table_name='resignation_requests')
    op.drop_table('resignation_requests')

    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS last_working_day")
