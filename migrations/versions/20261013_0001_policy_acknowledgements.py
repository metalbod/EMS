"""Policy acknowledgements: policy_versions + policy_acknowledgements

Revision ID: 20261013_0001
Revises: 20261012_0001
Create Date: 2026-10-13

A policy (company handbook, memo, code of conduct...) is an ld_courses row with category
'policy' — it shows in the L&D Course Catalog under the Policies filter. Each published
version of it is a policy_versions row (document in ld_module_files, acknowledge-by date,
audience), and each person it is assigned to gets a policy_acknowledgements row recording
when they opened the document and when they acknowledged it. Both tables are tenant-scoped.
"""
from alembic import op

revision = '20261013_0001'
down_revision = '20261012_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"
_NOW = "to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"


def _tenant_policy(table):
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON {table}
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade():
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS policy_versions (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            course_id       INTEGER NOT NULL REFERENCES ld_courses(id),
            version         INTEGER NOT NULL,
            file_id         INTEGER NOT NULL REFERENCES ld_module_files(id),
            change_note     TEXT,
            due_date        TEXT,
            require_open    INTEGER NOT NULL DEFAULT 1,
            audience_type   TEXT    NOT NULL DEFAULT 'all',
            audience_ref    TEXT,
            published_by    TEXT,
            created_at      TEXT    NOT NULL DEFAULT ({_NOW}),
            UNIQUE (course_id, version)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_versions_inst_course ON policy_versions(institution_id, course_id)")
    _tenant_policy("policy_versions")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS policy_acknowledgements (
            id               SERIAL  PRIMARY KEY,
            institution_id   INTEGER NOT NULL REFERENCES institutions(id),
            version_id       INTEGER NOT NULL REFERENCES policy_versions(id) ON DELETE CASCADE,
            employee_id      TEXT    NOT NULL,
            assigned_at      TEXT    NOT NULL DEFAULT ({_NOW}),
            first_opened_at  TEXT,
            acknowledged_at  TEXT,
            statement        TEXT,
            acknowledged_by  TEXT,
            UNIQUE (version_id, employee_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_policy_acks_employee ON policy_acknowledgements(institution_id, employee_id)")
    _tenant_policy("policy_acknowledgements")


def downgrade():
    op.execute("DROP TABLE IF EXISTS policy_acknowledgements")
    op.execute("DROP TABLE IF EXISTS policy_versions")
