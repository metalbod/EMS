"""Add Benefits module Phase 4: dependent/beneficiary management

Revision ID: 20260725_0013
Revises: 20260725_0012
Create Date: 2026-07-25

Two tables:
  - benefit_dependents: an employee's roster of dependents/beneficiaries
    (spouse, children, etc.) — independent of any specific plan, since
    the same spouse might be covered under medical, dental, and vision
    all at once, or just listed as a life-insurance beneficiary with no
    medical coverage at all.
  - benefit_enrollment_dependents: a join table attaching a dependent to
    a specific enrollment (election) — this is what actually says "my
    spouse is covered under THIS medical plan." A dependent with zero
    attachments is still tracked (e.g. purely a beneficiary designation
    for life insurance, or someone HR is aware of before open enrollment
    even happens).

RLS policies are included in THIS migration (not a follow-up) — see
eb95a484c74a_add_rls_tenant_isolation_policies.py for why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0013'
down_revision = '20260725_0012'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"
_TABLES = ('benefit_dependents', 'benefit_enrollment_dependents')


def upgrade():
    op.create_table(
        'benefit_dependents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('full_name', sa.String(150), nullable=False),
        sa.Column('relationship', sa.String(30), nullable=False),
        # Spouse, Child, Domestic Partner, Parent, Other
        sa.Column('date_of_birth', sa.String(10), nullable=True),
        sa.Column('national_id', sa.String(50), nullable=True),
        sa.Column('is_beneficiary', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('beneficiary_percentage', sa.Numeric(5, 2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='Active'),  # Active, Removed
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_benefit_dependents_employee', 'employee_id'),
    )

    op.create_table(
        'benefit_enrollment_dependents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('enrollment_id', sa.Integer(), nullable=False),
        sa.Column('dependent_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['enrollment_id'], ['benefit_enrollments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['dependent_id'], ['benefit_dependents.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('enrollment_id', 'dependent_id', name='uq_enrollment_dependent'),
        sa.Index('ix_enrollment_dependents_enrollment', 'enrollment_id'),
    )

    op.execute("DROP TRIGGER IF EXISTS trg_benefit_dependents_upd ON benefit_dependents")
    op.execute("""
        CREATE TRIGGER trg_benefit_dependents_upd BEFORE UPDATE ON benefit_dependents
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
    op.drop_table('benefit_enrollment_dependents')
    op.drop_table('benefit_dependents')
