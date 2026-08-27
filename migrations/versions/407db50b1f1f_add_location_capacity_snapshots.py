"""add location_capacity_snapshots table

Revision ID: 407db50b1f1f
Revises: 137e246cb110
Create Date: 2026-08-27

routers/location_phase2.py's utilization-history/utilization-trends
endpoints and routers/location_features.py's capacity-dashboard trend_data
have never had anything to read a real history from — no table anywhere
recorded a capacity reading over time, only the current live count (see
the EMS Debt Ledger's Phase 0 "Location dashboards return hardcoded
placeholder data" finding and its Phase 3 follow-up item). This table is
that missing periodic snapshot.

No cron jobs exist anywhere in this stack (see CLAUDE.md) — snapshots are
written opportunistically by routers/location_features.py's
check_and_trigger_capacity_alerts whenever it's called (once a real
"capacity dashboard" UI exists and calls it regularly, coverage becomes
continuous; until then, history is only as complete as whatever already
calls that endpoint, which today is test coverage only — no frontend page
calls it yet). One row per (institution, location, day) — a same-day
recheck upserts the existing row rather than accumulating duplicates.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '407db50b1f1f'
down_revision: Union[str, Sequence[str], None] = '137e246cb110'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS location_capacity_snapshots (
            id                    SERIAL  PRIMARY KEY,
            institution_id        INTEGER NOT NULL REFERENCES institutions(id),
            location_id           INTEGER NOT NULL REFERENCES locations(id),
            snapshot_date         DATE    NOT NULL,
            employee_count        INTEGER NOT NULL,
            capacity              INTEGER NOT NULL,
            utilization_percent   NUMERIC(5,2) NOT NULL,
            created_at            TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE (institution_id, location_id, snapshot_date)
        )
    """)
    # New tenant tables need their tenant_isolation RLS policy created
    # explicitly (see eb95a484c74a) — the ensure_rls event trigger only
    # flips RLS on, it doesn't grant any access, so without this every
    # query/insert against this table would be denied outright.
    op.execute("""
        CREATE POLICY tenant_isolation ON location_capacity_snapshots
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE location_capacity_snapshots FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE location_capacity_snapshots NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON location_capacity_snapshots")
    op.execute("DROP TABLE IF EXISTS location_capacity_snapshots")
