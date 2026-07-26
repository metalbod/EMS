"""Add Variable Pay: commission structures

Revision ID: 20260725_0007
Revises: 20260724_0006
Create Date: 2026-07-25

Same container/line-item pattern as bonus_plans/bonus_payouts:
  - commission_plans: a named plan (e.g. "2026 Sales Commission Plan")
    with a rate structure type and a default commission rate.
  - commission_entries: individual sales/attainment entries per employee
    under a plan, with a calculated commission amount and a
    Pending -> Approved/Rejected -> Paid lifecycle (identical shape to
    bonus_payouts, since the payment lifecycle is the same regardless of
    how the amount was derived).

Distinct from bonus_payouts in what drives the amount: a bonus payout is
a discretionary awarded_amount; a commission entry is *calculated* from
sales_amount x commission_rate_percent (optionally against a quota), with
the calculated value stored (not recomputed on read) so a later rate
change on the plan doesn't retroactively alter historical entries.

RLS policies are included in THIS migration (not a follow-up) — see
eb95a484c74a_add_rls_tenant_isolation_policies.py for why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0007'
down_revision = '20260724_0006'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    # Commission Plans
    op.create_table(
        'commission_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('plan_name', sa.String(150), nullable=False),
        sa.Column('plan_type', sa.String(30), nullable=False),  # Flat Rate, Tiered, Quota-based
        sa.Column('default_rate_percent', sa.Numeric(6, 3), nullable=True),
        sa.Column('plan_year', sa.Integer(), nullable=True),
        sa.Column('period_start', sa.String(10), nullable=True),  # YYYY-MM-DD
        sa.Column('period_end', sa.String(10), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),  # Draft, Active, Closed
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_commission_plans_institution', 'institution_id'),
        sa.Index('ix_commission_plans_status', 'status'),
        sa.Index('ix_commission_plans_type', 'plan_type'),
    )

    # Individual commission entries (sales -> calculated commission) per employee under a plan
    op.create_table(
        'commission_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('commission_plan_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('sales_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('quota_target', sa.Numeric(14, 2), nullable=True),
        sa.Column('commission_rate_percent', sa.Numeric(6, 3), nullable=False),
        sa.Column('calculated_commission', sa.Numeric(12, 2), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),  # Pending, Approved, Rejected, Paid
        sa.Column('recommended_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approval_date', sa.String(50), nullable=True),
        sa.Column('payout_date', sa.String(10), nullable=True),  # YYYY-MM-DD, set when marked Paid
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['commission_plan_id'], ['commission_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_commission_entries_plan', 'commission_plan_id'),
        sa.Index('ix_commission_entries_employee', 'employee_id'),
        sa.Index('ix_commission_entries_status', 'status'),
    )

    for table in ('commission_plans', 'commission_entries'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_upd ON {table}")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_upd BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)

    for table in ('commission_plans', 'commission_entries'):
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {table}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade():
    for table in ('commission_plans', 'commission_entries'):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")
    op.drop_table('commission_entries')
    op.drop_table('commission_plans')
