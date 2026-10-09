"""L&D course documents: ld_module_files + ld_course_modules.file_id

Revision ID: 20261010_0001
Revises: 20261009_0003
Create Date: 2026-10-10

A course's content can now include "document" lessons — a PDF, Word or
PowerPoint file employees download and read. The file bytes live in their own
table (BYTEA, ~20 MB cap enforced by the API) rather than inside the lesson
row, because the lessons are rewritten wholesale every time HR saves Course
Content and a file must survive that. ld_course_modules.file_id points at it;
saving the lessons keeps the link and deletes files no lesson uses any more.
"""
from alembic import op

revision = '20261010_0001'
down_revision = '20261009_0003'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ld_module_files (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            course_id       INTEGER NOT NULL REFERENCES ld_courses(id),
            file_name       TEXT    NOT NULL,
            mime_type       TEXT    NOT NULL,
            size_bytes      INTEGER NOT NULL,
            data            BYTEA   NOT NULL,
            uploaded_by     TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ld_module_files_course ON ld_module_files(institution_id, course_id)")
    op.execute("ALTER TABLE ld_module_files ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON ld_module_files
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE ld_module_files FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ld_course_modules ADD COLUMN IF NOT EXISTS file_id INTEGER REFERENCES ld_module_files(id) ON DELETE SET NULL")


def downgrade():
    op.execute("ALTER TABLE ld_course_modules DROP COLUMN IF EXISTS file_id")
    op.execute("DROP TABLE IF EXISTS ld_module_files")
