"""Add Overtime module (records + institution conversion settings)

Revision ID: 20260806_0001
Revises: 20260805_0001
Create Date: 2026-08-06

When a submitted timesheet has a day logged beyond that employee's
resolved Attendance shift (core/attendance_helpers.resolve_shift — an
employee with no shift on file gets no overtime detection at all), the
excess becomes an overtime_records row, routed through its own
configurable approval workflow (module='overtime' in
core/approval_workflow.py, project_manager-eligible via the parent
timesheet's own logged projects — see core/overtime.py). On approval it's
either credited as leave (institutions.overtime_leave_type_id) or tracked
as a pay amount (tracking only this round — no payroll wiring yet).

overtime_records has its own institution_id (unlike approval_workflow_steps
/ project_managers), so it gets the standard tenant_isolation RLS policy.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260806_0001'
down_revision = '20260805_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS overtime_conversion_mode TEXT NOT NULL DEFAULT 'pay'")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS overtime_leave_type_id INTEGER")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS overtime_pay_multiplier NUMERIC NOT NULL DEFAULT 1.5")

    op.create_table(
        'overtime_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('timesheet_id', sa.Integer(), sa.ForeignKey('timesheets.id'), nullable=False),
        sa.Column('work_date', sa.String(10), nullable=False),
        sa.Column('shift_id', sa.Integer(), nullable=True),
        sa.Column('threshold_hours', sa.Numeric(), nullable=False),
        sa.Column('logged_hours', sa.Numeric(), nullable=False),
        sa.Column('overtime_hours', sa.Numeric(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),
        sa.Column('approval_workflow_id', sa.Integer(), nullable=True),
        sa.Column('approval_step', sa.Integer(), nullable=True),
        sa.Column('conversion_mode', sa.String(10), nullable=False),
        sa.Column('leave_days_credited', sa.Numeric(), nullable=True),
        sa.Column('pay_amount', sa.Numeric(), nullable=True),
        sa.Column('approved_by', sa.String(100), nullable=True),
        sa.Column('approved_at', sa.String(19), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_overtime_records_timesheet_id', 'overtime_records', ['timesheet_id'])
    op.create_index('ix_overtime_records_inst_employee', 'overtime_records', ['institution_id', 'employee_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON overtime_records
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE overtime_records FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE overtime_records NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON overtime_records")
    op.drop_index('ix_overtime_records_inst_employee', table_name='overtime_records')
    op.drop_index('ix_overtime_records_timesheet_id', table_name='overtime_records')
    op.drop_table('overtime_records')

    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS overtime_pay_multiplier")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS overtime_leave_type_id")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS overtime_conversion_mode")
