"""Add candidate_documents table for resume/attachment uploads

Revision ID: 20260729_0002
Revises: 20260729_0001
Create Date: 2026-07-29

Candidates can now attach more than one file (resume, portfolio, cert
scans, etc.). Stored the same way the institution logo and leave
attachment already are — as a data:...;base64 URI in a TEXT column,
one row per file — rather than introducing S3/blob storage this app
doesn't otherwise have.

Follows the tenant-isolation RLS pattern from eb95a484c74a for every
other institution-scoped table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260729_0002'
down_revision = '20260729_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS candidate_documents (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
            file_name       TEXT    NOT NULL,
            mime_type       TEXT    NOT NULL,
            data_url        TEXT    NOT NULL,
            uploaded_by     TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_documents_candidate_id ON candidate_documents(candidate_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidate_documents_institution_id ON candidate_documents(institution_id)")

    op.execute("ALTER TABLE candidate_documents ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON candidate_documents
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE candidate_documents FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS candidate_documents")
