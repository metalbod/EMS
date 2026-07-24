"""Add Variable Pay: bonus/incentive plan management

Revision ID: 20260724_0006
Revises: 20260719_0005
Create Date: 2026-07-24

Two tables, following the exact same container/line-item pattern already
proven by merit_review_cycles/merit_recommendations:
  - bonus_plans: a named plan (e.g. "2026 Annual Performance Bonus",
    "Q3 Spot Awards", "Sign-on Bonus Pool") with a type, period, and
    optional budget pool.
  - bonus_payouts: individual awards to employees under a plan, with a
    Pending -> Approved/Rejected -> Paid lifecycle.

RLS policies are included in THIS migration (not a follow-up) — the
compensation framework's original migration shipped without them and
caused a real production incident (every insert failed with
'new row violates row-level security policy' until a second migration
added the missing policies). Not repeating that here.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260724_0006'
down_revision = '20260719_0005'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    # Bonus / Incentive Plans
    op.create_table(
        'bonus_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('plan_name', sa.String(150), nullable=False),
        sa.Column('plan_type', sa.String(30), nullable=False),  # Annual, Spot, Sign-on, Retention, Referral, Other
        sa.Column('plan_year', sa.Integer(), nullable=True),
        sa.Column('period_start', sa.String(10), nullable=True),  # YYYY-MM-DD
        sa.Column('period_end', sa.String(10), nullable=True),
        sa.Column('budget_pool_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),  # Draft, Active, Closed
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_bonus_plans_institution', 'institution_id'),
        sa.Index('ix_bonus_plans_status', 'status'),
        sa.Index('ix_bonus_plans_type', 'plan_type'),
    )

    # Individual payouts awarded to employees under a plan
    op.create_table(
        'bonus_payouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('bonus_plan_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('target_amount', sa.Numeric(12, 2), nullable=True),  # eligible/target amount, if plan defines one
        sa.Column('awarded_amount', sa.Numeric(12, 2), nullable=False),  # actual payout amount
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending'),  # Pending, Approved, Rejected, Paid
        sa.Column('recommended_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approval_date', sa.String(50), nullable=True),
        sa.Column('payout_date', sa.String(10), nullable=True),  # YYYY-MM-DD, set when marked Paid
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bonus_plan_id'], ['bonus_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_bonus_payouts_plan', 'bonus_plan_id'),
        sa.Index('ix_bonus_payouts_employee', 'employee_id'),
        sa.Index('ix_bonus_payouts_status', 'status'),
    )

    # Timestamp triggers, reusing the shared set_updated_at() plpgsql
    # function already defined in 20260717_0001_full_schema_ddl.py.
    for table in ('bonus_plans', 'bonus_payouts'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_upd ON {table}")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_upd BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)

    # RLS tenant-isolation policies — see eb95a484c74a_add_rls_tenant_isolation_policies.py
    # for the full reasoning (Supabase-managed Postgres auto-enables RLS
    # with zero policies on every new table, which denies ALL access by
    # default for a non-owner/non-bypass role).
    for table in ('bonus_plans', 'bonus_payouts'):
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {table}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade():
    for table in ('bonus_plans', 'bonus_payouts'):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")
    op.drop_table('bonus_payouts')
    op.drop_table('bonus_plans')
