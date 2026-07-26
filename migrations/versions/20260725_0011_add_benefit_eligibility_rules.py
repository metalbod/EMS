"""Add Benefits module Phase 2: eligibility rules by tier/grade

Revision ID: 20260725_0011
Revises: 20260725_0010
Create Date: 2026-07-25

benefit_plan_eligibility rows scope a plan to specific job levels and/or
pay grades. Semantics: a plan with ZERO eligibility rows is open to every
employee (the common case — most plans like medical/dental apply company-
wide); a plan with one or more rows is restricted to employees matching
ANY of those rows (OR across rows) — e.g. a Life Insurance plan reserved
for Job Level 3+ would have one row per qualifying level.

A CHECK constraint enforces that a rule references at least one of
job_level_id/pay_grade_id — an empty rule would silently match nothing
and no one would notice why an employee isn't eligible for anything.

RLS policies are included in THIS migration (not a follow-up) — see
eb95a484c74a_add_rls_tenant_isolation_policies.py for why that matters.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0011'
down_revision = '20260725_0010'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'benefit_plan_eligibility',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('benefit_plan_id', sa.Integer(), nullable=False),
        sa.Column('job_level_id', sa.Integer(), nullable=True),
        sa.Column('pay_grade_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['benefit_plan_id'], ['benefit_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_level_id'], ['job_levels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pay_grade_id'], ['pay_grades.id'], ondelete='CASCADE'),
        sa.CheckConstraint('job_level_id IS NOT NULL OR pay_grade_id IS NOT NULL', name='ck_eligibility_has_target'),
        sa.Index('ix_benefit_eligibility_plan', 'benefit_plan_id'),
        sa.Index('ix_benefit_eligibility_level', 'job_level_id'),
        sa.Index('ix_benefit_eligibility_grade', 'pay_grade_id'),
    )

    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON benefit_plan_eligibility
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE benefit_plan_eligibility FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE benefit_plan_eligibility NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON benefit_plan_eligibility")
    op.drop_table('benefit_plan_eligibility')
