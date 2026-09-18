"""Add per-project Timesheet/Overtime approval (timesheet_project_approvals, overtime_project_approvals)

Revision ID: 20260917_0001
Revises: 20260915_0001
Create Date: 2026-09-17

Timesheet and Overtime approval used to be one indivisible unit per row
(timesheets.status / overtime_records.status) even though a single
timesheet — or a single day's overtime within it — can span multiple
projects with different Project Managers. A project_manager approval
step resolved as "any manager of any project touched" (a union), so one
project's manager could approve hours belonging entirely to a different
project.

This splits approval to the project level going forward:

  - timesheet_project_approvals: one row per (timesheet, project) a
    Submit creates, each running its own approval_workflow_id/
    approval_step instance (project_manager now resolves against just
    that one project_id, not a union). employee_id is denormalized from
    the parent timesheet so core/approval_workflow.py's generic
    MODULE_EMPLOYEE_COL lookup works without a join.
  - overtime_project_approvals: same idea, one row per (overtime_records
    day, project) — overtime_hours is that project's prorated share of
    the day's total overtime (by hours-logged share), and
    leave_days_credited/pay_amount are computed independently per row on
    approval, mirroring overtime_records' own conversion fields.

Deliberately no backfill: existing timesheets/overtime_records keep
their old whole-record status forever (see core/approval_workflow.py's
project_ids_for_row, which disambiguates old vs new by row shape, and
routers/timesheets.py's dual-path list/read logic) — only rows submitted
after this ships get split. This is a permanent dual-path, not a
temporary migration state; confirmed with the project owner as the
deliberately chosen trade-off over a backfill.

Both tables have their own institution_id, so both get the standard
tenant_isolation RLS policy (same shape as overtime_records itself).
"""
from alembic import op
import sqlalchemy as sa


revision = '20260917_0001'
down_revision = '20260915_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'timesheet_project_approvals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('timesheet_id', sa.Integer(), sa.ForeignKey('timesheets.id'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        # period_start/period_end denormalized from the parent timesheet —
        # routers/dashboard.py's _approval_row_detail (Home page To-Do) and
        # the Timesheet Approvals list both need these on every row without
        # an extra join back to `timesheets` in their hot path.
        sa.Column('period_start', sa.String(10), nullable=False),
        sa.Column('period_end', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Submitted'),
        sa.Column('approval_workflow_id', sa.Integer(), nullable=True),
        sa.Column('approval_step', sa.Integer(), nullable=True),
        sa.Column('approved_by', sa.String(100), nullable=True),
        sa.Column('approved_at', sa.String(19), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
        sa.UniqueConstraint('timesheet_id', 'project_id', name='uq_ts_project_approval'),
    )
    op.create_index('ix_timesheet_project_approvals_timesheet_id', 'timesheet_project_approvals', ['timesheet_id'])
    op.create_index('ix_timesheet_project_approvals_institution_id', 'timesheet_project_approvals', ['institution_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON timesheet_project_approvals
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE timesheet_project_approvals FORCE ROW LEVEL SECURITY")

    op.create_table(
        'overtime_project_approvals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('overtime_record_id', sa.Integer(), sa.ForeignKey('overtime_records.id'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        # work_date denormalized from the parent overtime_records row, same
        # reasoning as timesheet_project_approvals' period_start/period_end.
        sa.Column('work_date', sa.String(10), nullable=False),
        sa.Column('overtime_hours', sa.Numeric(), nullable=False),
        sa.Column('conversion_mode', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),
        sa.Column('approval_workflow_id', sa.Integer(), nullable=True),
        sa.Column('approval_step', sa.Integer(), nullable=True),
        sa.Column('leave_days_credited', sa.Numeric(), nullable=True),
        sa.Column('pay_amount', sa.Numeric(), nullable=True),
        sa.Column('approved_by', sa.String(100), nullable=True),
        sa.Column('approved_at', sa.String(19), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
        sa.UniqueConstraint('overtime_record_id', 'project_id', name='uq_ot_project_approval'),
    )
    op.create_index('ix_overtime_project_approvals_overtime_record_id', 'overtime_project_approvals', ['overtime_record_id'])
    op.create_index('ix_overtime_project_approvals_institution_id', 'overtime_project_approvals', ['institution_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON overtime_project_approvals
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE overtime_project_approvals FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE overtime_project_approvals NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON overtime_project_approvals")
    op.drop_table('overtime_project_approvals')

    op.execute("ALTER TABLE timesheet_project_approvals NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON timesheet_project_approvals")
    op.drop_table('timesheet_project_approvals')
