"""Microsoft sign-in phases 2 and 3: require-SSO switch, emergency password access, auto-create, group-to-role mapping

Revision ID: 20261018_0001
Revises: 20261017_0001
Create Date: 2026-10-18

institution_sso.enforce       'Require Microsoft sign-in': password sign-in is refused for everyone except users marked
                              sso_password_ok (emergency access) and platform admins.
institution_sso.auto_create   create the EMS account on first Microsoft sign-in when exactly one active employee has that
                              work email and no login yet (basic Employee role).
institution_sso.role_sync     apply institution_sso_group_roles at each Microsoft sign-in.
users.sso_password_ok         emergency access: may still sign in with a password while Microsoft sign-in is required.
institution_sso_group_roles   Entra group object id -> EMS role, per company.
"""
from alembic import op

revision = '20261018_0001'
down_revision = '20261017_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE institution_sso ADD COLUMN IF NOT EXISTS enforce INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE institution_sso ADD COLUMN IF NOT EXISTS auto_create INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE institution_sso ADD COLUMN IF NOT EXISTS role_sync INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sso_password_ok INTEGER NOT NULL DEFAULT 0")
    op.execute("""
        CREATE TABLE IF NOT EXISTS institution_sso_group_roles (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            group_id        TEXT    NOT NULL,
            role            TEXT    NOT NULL,
            position        INTEGER NOT NULL DEFAULT 0,
            UNIQUE (institution_id, group_id)
        )
    """)
    op.execute("ALTER TABLE institution_sso_group_roles ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON institution_sso_group_roles
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE institution_sso_group_roles FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS institution_sso_group_roles")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sso_password_ok")
    op.execute("ALTER TABLE institution_sso DROP COLUMN IF EXISTS role_sync")
    op.execute("ALTER TABLE institution_sso DROP COLUMN IF EXISTS auto_create")
    op.execute("ALTER TABLE institution_sso DROP COLUMN IF EXISTS enforce")
