"""Add RLS tenant-isolation policies to location-module tables

Revision ID: 20260725_0016
Revises: 20260725_0015
Create Date: 2026-07-25

Six tables from the multi-location feature (20260718_0001 and
20260719_0002) were never added to eb95a484c74a's _STANDARD_TABLES list,
so they've had RLS enabled with zero policies (a no-op for the app's
non-superuser connection, per that migration's own reasoning) ever since
— flagged by Supabase's linter as "RLS Disabled in Public".

  - locations, employee_location_assignments, location_transfers,
    report_schedules: have a direct institution_id column, so they get
    the same tenant_isolation policy as every other standard table.
  - location_capacity_alerts, location_budgets: no institution_id column
    (only location_id) — scoped via an EXISTS against locations, same
    pattern eb95a484c74a used for okr_key_results (goal_id -> goals).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0016'
down_revision = '20260725_0015'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"

_STANDARD_TABLES = [
    "locations", "employee_location_assignments", "location_transfers", "report_schedules",
]


def upgrade():
    for tbl in _STANDARD_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {tbl}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE location_capacity_alerts ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON location_capacity_alerts
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM locations l
                WHERE l.id = location_capacity_alerts.location_id
                  AND l.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE location_capacity_alerts FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE location_budgets ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON location_budgets
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM locations l
                WHERE l.id = location_budgets.location_id
                  AND l.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE location_budgets FORCE ROW LEVEL SECURITY")


def downgrade():
    for tbl in _STANDARD_TABLES + ["location_capacity_alerts", "location_budgets"]:
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
