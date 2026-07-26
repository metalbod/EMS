"""Add Benefits module Phase 5: carrier/vendor fields + claims tracking

Revision ID: 20260725_0014
Revises: 20260725_0013
Create Date: 2026-07-25

No real insurance carrier to integrate with in this environment, so this
models the "Carrier & Vendor Integration" feature the way this project
models statutory payroll figures elsewhere: internal reference data and
calculations, not live external API calls.

  - benefit_plans gains carrier_name, carrier_group_policy_number, and a
    payroll_sync_enabled flag — new nullable columns on the existing
    RLS-protected table, no policy change needed.
  - benefit_claims: a claims log per employee per plan, with a
    Submitted -> Under Review -> Approved/Rejected -> Paid lifecycle
    (same shape as bonus_payouts/commission_entries: propose, decide,
    pay). amount_approved is separate from amount_claimed since a claim
    is often partially approved.

RLS policies for the new table are included in THIS migration (not a
follow-up) — see eb95a484c74a_add_rls_tenant_isolation_policies.py for
why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0014'
down_revision = '20260725_0013'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.add_column('benefit_plans', sa.Column('carrier_name', sa.String(150), nullable=True))
    op.add_column('benefit_plans', sa.Column('carrier_group_policy_number', sa.String(100), nullable=True))
    op.add_column('benefit_plans', sa.Column('payroll_sync_enabled', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'benefit_claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('benefit_plan_id', sa.Integer(), nullable=False),
        sa.Column('claim_date', sa.String(10), nullable=False),
        sa.Column('amount_claimed', sa.Numeric(12, 2), nullable=False),
        sa.Column('amount_approved', sa.Numeric(12, 2), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Submitted'),
        # Submitted, Under Review, Approved, Rejected, Paid
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('review_date', sa.String(50), nullable=True),
        sa.Column('payout_date', sa.String(10), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['benefit_plan_id'], ['benefit_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_benefit_claims_employee', 'employee_id'),
        sa.Index('ix_benefit_claims_plan', 'benefit_plan_id'),
        sa.Index('ix_benefit_claims_status', 'status'),
    )

    op.execute("DROP TRIGGER IF EXISTS trg_benefit_claims_upd ON benefit_claims")
    op.execute("""
        CREATE TRIGGER trg_benefit_claims_upd BEFORE UPDATE ON benefit_claims
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON benefit_claims
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE benefit_claims FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE benefit_claims NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON benefit_claims")
    op.drop_table('benefit_claims')
    op.drop_column('benefit_plans', 'payroll_sync_enabled')
    op.drop_column('benefit_plans', 'carrier_group_policy_number')
    op.drop_column('benefit_plans', 'carrier_name')
