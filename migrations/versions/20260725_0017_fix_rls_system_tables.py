"""Fix-forward: ensure alembic_version and system_notifications actually
have RLS enabled with a permissive policy

Revision ID: 20260725_0017
Revises: 20260725_0016
Create Date: 2026-07-25

9e7c3b2d1a4f ("Add RLS policies to alembic_version and system_notifications")
is recorded as applied in this database's migration history, but a direct
pg_class/pg_policies check found both tables with relrowsecurity = false and
zero policies — i.e. that migration's DDL never actually executed here,
most likely because this database's schema was originally bootstrapped via
20260717_0001's full-schema-DDL baseline (a stamp-style bootstrap) rather
than by replaying every incremental migration in order, and 20260717_0001
explicitly excludes these two tables from its own RLS-enabling loop (by
design, since the "correct" policy for them was decided in a later
migration on a different branch).

This migration is idempotent (DROP POLICY IF EXISTS + ENABLE, safe to
re-run) and fixes the actual database state to match what 9e7c3b2d1a4f and
eb95a484c74a always intended: RLS enabled, with an explicit permissive
policy, on both tables — silencing Supabase's "RLS Disabled in Public"
linter warning without changing their real access behavior (both were
already fully open in practice).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0017'
down_revision = '20260725_0016'
branch_labels = None
depends_on = None

_TABLES = ["alembic_version", "system_notifications"]


def upgrade():
    for tbl in _TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS permissive_access ON {tbl}")
        op.execute(f"""
            CREATE POLICY permissive_access ON {tbl}
            USING (true)
            WITH CHECK (true)
        """)


def downgrade():
    for tbl in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS permissive_access ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
