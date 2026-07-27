"""Add RLS tenant-isolation policy to task_tracking

Revision ID: 20260727_0003
Revises: 20260727_0002
Create Date: 2026-07-27

This project's Postgres (Supabase-managed) auto-enables Row Level Security
on every new table created in the public schema, with zero policies —
which denies ALL access by default (see eb95a484c74a's docstring, and
20260719_0005 for the exact same story on the compensation tables). The
20260727_0002 migration created task_tracking without a policy, so every
insert immediately started failing with "new row violates row-level
security policy for table task_tracking" as soon as it applied.

Mirrors the standard tenant_isolation policy pattern. institution_id is
nullable on this table (platform-level tasks have none), so the policy
only enforces the match when institution_id is set — a NULL row is only
reachable via app.bypass_rls, same as every other superadmin-only path.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260727_0003'
down_revision = '20260727_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON task_tracking
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id IS NULL
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE task_tracking FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE task_tracking NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON task_tracking")
