"""Add ai_usage_log for the Settings -> AI Assistant -> Usage tab

Revision ID: 20261004_0001
Revises: 20261001_0002
Create Date: 2026-10-04

One row per AI request (a chat message — however many Claude calls its tool
loop made, summed — or one resume extraction), recording the token counts
Anthropic returns on every response. Nothing was recorded before this
table existed, so the Usage tab can only report from the day this shipped.

user_id deliberately has no FK to users: deleting a user must not be
blocked by (or erase) their historical usage — `username` is a snapshot so
the report can still label a deleted account's rows.
"""
from alembic import op

revision = '20261004_0001'
down_revision = '20261001_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            user_id         INTEGER,
            username        TEXT,
            feature         TEXT    NOT NULL CHECK (feature IN ('chat', 'resume_extraction')),
            model           TEXT,
            input_tokens    INTEGER NOT NULL DEFAULT 0,
            output_tokens   INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_usage_log_institution_created "
               "ON ai_usage_log(institution_id, created_at)")

    op.execute("ALTER TABLE ai_usage_log ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON ai_usage_log
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE ai_usage_log FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ai_usage_log")
