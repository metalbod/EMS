"""Add ob_template_dependencies (checklist template items that start after others)

Revision ID: 20261008_0001
Revises: 20261004_0001
Create Date: 2026-10-08

"Phase 2a" of the onboarding/offboarding template board: HR can say "item B
starts after item A". A row is one such link. Links are only drawn and
edited on the template board for now; nothing at checklist run time reads
them yet (a later phase will snapshot them onto started checklists).

ob_templates rows are soft-deleted (is_active=0), so the FKs only matter for
hard deletes; the delete endpoint also removes a removed item's links.
"""
from alembic import op

revision = '20261008_0001'
down_revision = '20261004_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ob_template_dependencies (
            id                       SERIAL  PRIMARY KEY,
            institution_id           INTEGER NOT NULL REFERENCES institutions(id),
            template_id              INTEGER NOT NULL REFERENCES ob_templates(id) ON DELETE CASCADE,
            depends_on_template_id   INTEGER NOT NULL REFERENCES ob_templates(id) ON DELETE CASCADE,
            created_at               TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            CONSTRAINT ob_template_dependencies_not_self CHECK (template_id <> depends_on_template_id),
            CONSTRAINT ob_template_dependencies_unique UNIQUE (template_id, depends_on_template_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ob_template_dependencies_depends_on "
               "ON ob_template_dependencies(depends_on_template_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ob_template_dependencies_institution "
               "ON ob_template_dependencies(institution_id)")

    op.execute("ALTER TABLE ob_template_dependencies ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON ob_template_dependencies
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE ob_template_dependencies FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ob_template_dependencies")
