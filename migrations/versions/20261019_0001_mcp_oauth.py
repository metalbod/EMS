"""Claude / MCP access: OAuth authorization server tables and the per-company switch

Revision ID: 20261019_0001
Revises: 20261018_0001
Create Date: 2026-10-19

institutions.mcp_enabled   HR's company-level switch for letting Claude (through the MCP server) act as a signed-in
                           employee. Off by default; turning it off blocks every existing token at once.
oauth_clients              apps that registered themselves (dynamic client registration, RFC 7591). Public clients only
                           (PKCE, no client secret). Not tenant data - a client is registered before anyone has signed in.
oauth_codes                single-use authorization codes (hashed, 5 minutes), bound to the PKCE challenge + redirect URI.
oauth_grants               one row per "this person allowed this app": the thing HR can revoke, and what the 30-day
                           sliding window hangs off (last_used_at).
oauth_tokens               the short-lived access token and the rotating refresh token of a grant (only hashes stored).
"""
from alembic import op

revision = '20261019_0001'
down_revision = '20261018_0001'
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
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS mcp_enabled INTEGER NOT NULL DEFAULT 0")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS oauth_clients (
            id             SERIAL PRIMARY KEY,
            client_id      TEXT   NOT NULL UNIQUE,
            client_name    TEXT   NOT NULL,
            redirect_uris  TEXT   NOT NULL,
            created_at     TEXT   NOT NULL DEFAULT ({_NOW})
        )
    """)
    # No institution_id on this table, so the usual tenant policy doesn't apply: it is shared platform data that is
    # read and written before anyone has signed in. RLS is auto-enabled by the ensure_rls trigger, so without an
    # explicit policy every query would return nothing.
    op.execute("ALTER TABLE oauth_clients ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY open_access ON oauth_clients USING (true) WITH CHECK (true)")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS oauth_grants (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            user_id         INTEGER NOT NULL,
            client_id       TEXT    NOT NULL,
            client_name     TEXT,
            scope           TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT ({_NOW}),
            last_used_at    TEXT    NOT NULL DEFAULT ({_NOW}),
            revoked_at      TEXT,
            revoked_by      TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_oauth_grants_inst ON oauth_grants (institution_id, revoked_at)")
    _tenant_policy("oauth_grants")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS oauth_codes (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            user_id         INTEGER NOT NULL,
            client_id       TEXT    NOT NULL,
            code_hash       TEXT    NOT NULL UNIQUE,
            redirect_uri    TEXT    NOT NULL,
            code_challenge  TEXT    NOT NULL,
            scope           TEXT    NOT NULL,
            expires_at      TEXT    NOT NULL,
            used_at         TEXT,
            created_at      TEXT    NOT NULL DEFAULT ({_NOW})
        )
    """)
    _tenant_policy("oauth_codes")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            grant_id        INTEGER NOT NULL REFERENCES oauth_grants(id) ON DELETE CASCADE,
            kind            TEXT    NOT NULL,
            token_hash      TEXT    NOT NULL UNIQUE,
            expires_at      TEXT    NOT NULL,
            used_at         TEXT,
            created_at      TEXT    NOT NULL DEFAULT ({_NOW})
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_oauth_tokens_grant ON oauth_tokens (grant_id)")
    _tenant_policy("oauth_tokens")


def downgrade():
    op.execute("DROP TABLE IF EXISTS oauth_tokens")
    op.execute("DROP TABLE IF EXISTS oauth_codes")
    op.execute("DROP TABLE IF EXISTS oauth_grants")
    op.execute("DROP TABLE IF EXISTS oauth_clients")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS mcp_enabled")
