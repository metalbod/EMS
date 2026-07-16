"""Add RLS policies to alembic_version and system_notifications.

alembic_version is a system table that tracks applied migrations (created by
Alembic). system_notifications is intentionally platform-wide with no tenant
boundary. Both tables need RLS enabled (to silence Supabase warnings about
"rls disabled in public") but with permissive policies that allow unrestricted
access — they're not tenant-scoped.

Revision ID: 9e7c3b2d1a4f
Revises: 8fc32f58e44f
Create Date: 2026-07-16 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e7c3b2d1a4f'
down_revision: Union[str, Sequence[str], None] = '8fc32f58e44f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable RLS on alembic_version (system migration tracking table)
    op.execute("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY permissive_access ON alembic_version
        USING (true)
        WITH CHECK (true)
    """)

    # Re-enable RLS on system_notifications with a permissive policy
    # (was intentionally disabled in the previous RLS migration, but
    # Supabase warns about "rls disabled in public" — this policy allows
    # unrestricted access while satisfying RLS requirements)
    op.execute("ALTER TABLE system_notifications ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY permissive_access ON system_notifications
        USING (true)
        WITH CHECK (true)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS permissive_access ON alembic_version")
    op.execute("ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS permissive_access ON system_notifications")
    op.execute("ALTER TABLE system_notifications DISABLE ROW LEVEL SECURITY")
