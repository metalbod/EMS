"""Add Benefits module Phase 3: enrollment periods, life events, enrollments

Revision ID: 20260725_0012
Revises: 20260725_0011
Create Date: 2026-07-25

Three tables model the two ways an employee can change their benefit
elections:
  - benefit_enrollment_periods: HR-defined open enrollment windows
    (e.g. "2026 Open Enrollment", Nov 1 - Nov 30). Self-service elections
    are only allowed while a period's status is 'Open'.
  - benefit_life_events: employee-submitted qualifying life events
    (marriage, childbirth, etc.) that HR reviews. An Approved event opens
    a personal enrollment window for that employee, independent of
    whether a company-wide open enrollment period is active — the whole
    point of a life event is enrolling outside the normal cycle.
  - benefit_enrollments: the actual elections — one row per employee per
    plan, Enrolled or Waived, linked to whichever window (period or life
    event) authorized it. employee_cost/employer_cost are snapshotted
    from the plan at election time (same pattern as commission_entries'
    calculated_commission) so a later plan cost change doesn't silently
    rewrite what an employee actually agreed to pay.

RLS policies are included in THIS migration (not a follow-up) — see
eb95a484c74a_add_rls_tenant_isolation_policies.py for why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0012'
down_revision = '20260725_0011'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"
_TABLES = ('benefit_enrollment_periods', 'benefit_life_events', 'benefit_enrollments')


def upgrade():
    op.create_table(
        'benefit_enrollment_periods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('period_name', sa.String(150), nullable=False),
        sa.Column('plan_year', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.String(10), nullable=False),
        sa.Column('end_date', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),  # Draft, Open, Closed
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_benefit_periods_institution', 'institution_id'),
        sa.Index('ix_benefit_periods_status', 'status'),
    )

    op.create_table(
        'benefit_life_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('event_type', sa.String(30), nullable=False),
        # Marriage, Divorce, Childbirth, Adoption, Death of Dependent, Loss of Other Coverage, Other
        sa.Column('event_date', sa.String(10), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending Review'),  # Pending Review, Approved, Rejected
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('review_date', sa.String(50), nullable=True),
        sa.Column('window_end_date', sa.String(10), nullable=True),  # set on approval: event_date + 30 days
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_benefit_life_events_employee', 'employee_id'),
        sa.Index('ix_benefit_life_events_status', 'status'),
    )

    op.create_table(
        'benefit_enrollments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('benefit_plan_id', sa.Integer(), nullable=False),
        sa.Column('enrollment_period_id', sa.Integer(), nullable=True),
        sa.Column('life_event_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),  # Enrolled, Waived, Cancelled
        sa.Column('employee_cost_snapshot', sa.Numeric(12, 4), nullable=True),
        sa.Column('employer_cost_snapshot', sa.Numeric(12, 4), nullable=True),
        sa.Column('effective_date', sa.String(10), nullable=True),
        sa.Column('elected_at', sa.String(50), nullable=False),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['benefit_plan_id'], ['benefit_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['enrollment_period_id'], ['benefit_enrollment_periods.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['life_event_id'], ['benefit_life_events.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('employee_id', 'benefit_plan_id', name='uq_benefit_enrollment_employee_plan'),
        sa.Index('ix_benefit_enrollments_employee', 'employee_id'),
        sa.Index('ix_benefit_enrollments_plan', 'benefit_plan_id'),
    )

    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_upd ON {table}")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_upd BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)

    for table in _TABLES:
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {table}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade():
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")
    op.drop_table('benefit_enrollments')
    op.drop_table('benefit_life_events')
    op.drop_table('benefit_enrollment_periods')
