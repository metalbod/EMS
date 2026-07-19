"""Add RLS tenant-isolation policies to compensation framework tables

Revision ID: 20260719_0005
Revises: 20260719_0004
Create Date: 2026-07-19

This project's Postgres (Supabase-managed) auto-enables Row Level Security
on every new table created in the public schema, with zero policies —
which denies ALL access by default (see eb95a484c74a's docstring for the
same story on the original tables). The compensation framework tables from
20260719_0003 were created without any policy, so every insert failed with
"new row violates row-level security policy" once the app's connection
role (non-owner, non-bypass) tried to write to them.

Mirrors the exact tenant_isolation policy pattern from
eb95a484c74a_add_rls_tenant_isolation_policies.py.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260719_0005'
down_revision = '20260719_0004'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"

# Tables with a direct institution_id column.
_STANDARD_TABLES = [
    "pay_grades", "job_levels", "job_roles", "salary_structures",
    "salary_components", "employee_compensation", "salary_changes",
    "merit_review_cycles", "merit_recommendations", "pay_equity_analysis",
]


def upgrade():
    for tbl in _STANDARD_TABLES:
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {tbl}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")

    # job_role_pay_grades is a pure junction table with no institution_id of
    # its own — scoped via its parent job_roles row (job_role_id FK), same
    # pattern as okr_key_results -> goals.
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON job_role_pay_grades
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM job_roles r
                WHERE r.id = job_role_pay_grades.job_role_id
                  AND r.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE job_role_pay_grades FORCE ROW LEVEL SECURITY")


def downgrade():
    for tbl in _STANDARD_TABLES + ["job_role_pay_grades"]:
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {tbl}")
