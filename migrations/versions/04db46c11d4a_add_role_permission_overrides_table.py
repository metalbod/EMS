"""add role_permission_overrides table

Revision ID: 04db46c11d4a
Revises: a3b77dd5688e
Create Date: 2026-08-12

Lets an institution's HR loosen/tighten manager/employee/custom-role
access per action from Settings > Roles > Permission Matrix (see
core/permission_matrix.py). hr_manager/hr_admin/payroll_manager/
compensation_manager are deliberately never overridable — enforced in
routers/roles.py's application code, not the schema — so this table can
only ever contain rows for the roles that ARE eligible, but nothing here
stops a bad INSERT outside the app from adding one for a locked role;
that's an accepted app-layer-only guarantee, matching how role validity
itself is enforced elsewhere in this codebase.
"""
from alembic import op
import sqlalchemy as sa


revision = '04db46c11d4a'
down_revision = 'a3b77dd5688e'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS role_permission_overrides (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            action_key      TEXT    NOT NULL,
            role            TEXT    NOT NULL,
            access_value    TEXT    NOT NULL CHECK (access_value IN ('allow','deny')),
            updated_by      TEXT,
            updated_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE (institution_id, action_key, role)
        )
    """)
    # New tenant tables need their tenant_isolation RLS policy created
    # explicitly (see eb95a484c74a) — the ensure_rls event trigger only
    # flips RLS on, it doesn't grant any access, so without this every
    # query/insert against this table would be denied outright.
    op.execute("""
        CREATE POLICY tenant_isolation ON role_permission_overrides
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE role_permission_overrides FORCE ROW LEVEL SECURITY")
    op.create_index('ix_role_permission_overrides_lookup', 'role_permission_overrides', ['institution_id', 'action_key', 'role'])


def downgrade():
    op.drop_index('ix_role_permission_overrides_lookup', table_name='role_permission_overrides')
    op.execute("ALTER TABLE role_permission_overrides NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON role_permission_overrides")
    op.execute("DROP TABLE IF EXISTS role_permission_overrides")
