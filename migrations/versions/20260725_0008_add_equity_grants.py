"""Add Equity & Long-Term Incentives: stock option / RSU grants + vesting

Revision ID: 20260725_0008
Revises: 20260725_0007
Create Date: 2026-07-25

Two tables:
  - equity_grants: a single grant to an employee (ISO/NSO/RSU/ESPP), with
    quantity, strike price (options only), vesting schedule parameters
    (years + cliff), and a Pending Approval -> Approved/Rejected workflow.
  - equity_vesting_events: the individual tranches the vesting schedule
    expands into once a grant is approved (one cliff tranche + quarterly
    tranches thereafter), each independently markable as Vested.

Vesting events are generated server-side on approval (not stored as a
free-text schedule) so "how many shares are vested as of today" is always
a plain query, not something every caller has to recompute from the raw
years/cliff parameters.

RLS policies are included in THIS migration (not a follow-up) — see
eb95a484c74a_add_rls_tenant_isolation_policies.py for why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0008'
down_revision = '20260725_0007'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'equity_grants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('grant_type', sa.String(20), nullable=False),  # ISO, NSO, RSU, ESPP
        sa.Column('grant_date', sa.String(10), nullable=False),  # YYYY-MM-DD
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('strike_price', sa.Numeric(12, 4), nullable=True),
        sa.Column('fair_market_value_at_grant', sa.Numeric(12, 4), nullable=True),
        sa.Column('vesting_start_date', sa.String(10), nullable=False),
        sa.Column('vesting_years', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('cliff_months', sa.Integer(), nullable=False, server_default='12'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Pending Approval'),
        # Pending Approval, Approved, Rejected, Cancelled
        sa.Column('recommended_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approval_date', sa.String(50), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_equity_grants_institution', 'institution_id'),
        sa.Index('ix_equity_grants_employee', 'employee_id'),
        sa.Index('ix_equity_grants_status', 'status'),
    )

    op.create_table(
        'equity_vesting_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('equity_grant_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('vest_date', sa.String(10), nullable=False),  # YYYY-MM-DD
        sa.Column('quantity_vested', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='Scheduled'),  # Scheduled, Vested, Cancelled
        sa.Column('vested_at', sa.String(50), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['equity_grant_id'], ['equity_grants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_equity_vesting_grant', 'equity_grant_id'),
        sa.Index('ix_equity_vesting_employee', 'employee_id'),
        sa.Index('ix_equity_vesting_status', 'status'),
    )

    for table in ('equity_grants', 'equity_vesting_events'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_upd ON {table}")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_upd BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)

    for table in ('equity_grants', 'equity_vesting_events'):
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {table}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade():
    for table in ('equity_grants', 'equity_vesting_events'):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")
    op.drop_table('equity_vesting_events')
    op.drop_table('equity_grants')
