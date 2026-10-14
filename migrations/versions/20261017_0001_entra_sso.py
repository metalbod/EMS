"""Microsoft Entra ID single sign-on: per-company settings, in-flight sign-ins, user links

Revision ID: 20261017_0001
Revises: 20261016_0001
Create Date: 2026-10-17

institution_sso     one row per company: its own Entra tenant/app (BYO app registration, like its own SMTP or AI key),
                    the client secret encrypted, the on/off switch, and the result of the last test sign-in (the switch
                    can only be turned on after a test succeeded).
sso_pending         short-lived, single-use rows for a sign-in in flight: the 'state' of a redirect to Microsoft (with its
                    nonce and PKCE verifier) and the one-time 'code' EMS hands the browser afterwards. Only a hash of the
                    random token is stored.
users.sso_tenant_id / users.sso_oid   the Entra identity a user is linked to (set on their first Microsoft sign-in);
                    unique per company.
"""
from alembic import op

revision = '20261017_0001'
down_revision = '20261016_0001'
branch_labels = None
depends_on = None

_NOW = "to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"


def _tenant_policy(table):
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade():
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS institution_sso (
            id                       SERIAL  PRIMARY KEY,
            institution_id           INTEGER NOT NULL UNIQUE REFERENCES institutions(id),
            tenant_id                TEXT    NOT NULL,
            client_id                TEXT    NOT NULL,
            client_secret_encrypted  TEXT    NOT NULL,
            enabled                  INTEGER NOT NULL DEFAULT 0,
            last_test_at             TEXT,
            last_test_ok             INTEGER NOT NULL DEFAULT 0,
            last_test_detail         TEXT,
            updated_by               TEXT,
            updated_at               TEXT    NOT NULL DEFAULT ({_NOW})
        )
    """)
    _tenant_policy("institution_sso")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS sso_pending (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            kind            TEXT    NOT NULL,
            token_hash      TEXT    NOT NULL UNIQUE,
            mode            TEXT,
            nonce           TEXT,
            code_verifier   TEXT,
            redirect_uri    TEXT,
            user_id         INTEGER,
            started_by      TEXT,
            expires_at      TEXT    NOT NULL,
            used_at         TEXT,
            created_at      TEXT    NOT NULL DEFAULT ({_NOW})
        )
    """)
    _tenant_policy("sso_pending")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sso_tenant_id TEXT")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sso_oid TEXT")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_sso_oid ON users (institution_id, sso_oid) WHERE sso_oid IS NOT NULL")


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_users_sso_oid")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sso_oid")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sso_tenant_id")
    op.execute("DROP TABLE IF EXISTS sso_pending")
    op.execute("DROP TABLE IF EXISTS institution_sso")
