"""Add Benefits module Phase 1: benefit plan catalog

Revision ID: 20260725_0010
Revises: 20260725_0009
Create Date: 2026-07-25

First phase of a new top-level Benefits menu (separate from Compensation,
same HR/Payroll/Compensation Manager access gate). This table is just the
plan catalog — "what benefit plans exist" (Medical, Dental, Vision, Life,
Disability, Retirement, Wellness, Perks). Deliberately excludes Leave —
annual/medical/parental leave already has its own full module (leave_*
tables, routers/leave.py) and duplicating it here would fork two sources
of truth for the same thing.

Cost modeling is intentionally simple for v1: one flat employee_cost /
employer_cost per plan (not tiered by Employee-Only vs Family coverage
level) via a contribution_type discriminator, since real premium-tier
tables and carrier integration are out of scope until later phases.

Eligibility rules, enrollment, dependents, carrier/claims, and compliance
reporting are separate, later migrations — this is only the catalog they
all reference.

RLS policies are included in THIS migration (not a follow-up) — see
eb95a484c74a_add_rls_tenant_isolation_policies.py for why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0010'
down_revision = '20260725_0009'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'benefit_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('plan_name', sa.String(150), nullable=False),
        sa.Column('plan_category', sa.String(30), nullable=False),
        # Medical, Dental, Vision, Life, Disability, Retirement, Wellness, Perks
        sa.Column('contribution_type', sa.String(30), nullable=False),
        # Fixed Premium (RM/month), Percent of Salary, Reimbursement Cap (RM/year)
        sa.Column('employee_cost', sa.Numeric(12, 4), nullable=True),
        sa.Column('employer_cost', sa.Numeric(12, 4), nullable=True),
        sa.Column('plan_year', sa.Integer(), nullable=True),
        sa.Column('effective_date', sa.String(10), nullable=True),  # YYYY-MM-DD
        sa.Column('end_date', sa.String(10), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Draft'),  # Draft, Active, Closed
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_benefit_plans_institution', 'institution_id'),
        sa.Index('ix_benefit_plans_category', 'plan_category'),
        sa.Index('ix_benefit_plans_status', 'status'),
    )

    op.execute("DROP TRIGGER IF EXISTS trg_benefit_plans_upd ON benefit_plans")
    op.execute("""
        CREATE TRIGGER trg_benefit_plans_upd BEFORE UPDATE ON benefit_plans
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON benefit_plans
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE benefit_plans FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE benefit_plans NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON benefit_plans")
    op.drop_table('benefit_plans')
