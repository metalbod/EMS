"""Add ob_checklist_item_dependencies (a started checklist's snapshot of its template's links)

Revision ID: 20261008_0002
Revises: 20261008_0001
Create Date: 2026-10-08

"Phase 2b" of the onboarding/offboarding template dependencies. When a
checklist starts, each of its items copies the template's "starts after"
links (ob_template_dependencies) onto the new checklist items, the same
snapshot-at-start rule everything else on a checklist follows — editing the
template afterwards never touches a checklist already running.

A checklist item with an unfinished prerequisite (status other than Done or
N/A) is "blocked": only HR Manager/HR Admin can tick it, and it stays out of
the To-Do list and overdue reminders until its prerequisites are done.
"""
from alembic import op

revision = '20261008_0002'
down_revision = '20261008_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ob_checklist_item_dependencies (
            id                 SERIAL  PRIMARY KEY,
            institution_id     INTEGER NOT NULL REFERENCES institutions(id),
            item_id            INTEGER NOT NULL REFERENCES ob_checklist_items(id) ON DELETE CASCADE,
            depends_on_item_id INTEGER NOT NULL REFERENCES ob_checklist_items(id) ON DELETE CASCADE,
            CONSTRAINT ob_checklist_item_dependencies_not_self CHECK (item_id <> depends_on_item_id),
            CONSTRAINT ob_checklist_item_dependencies_unique UNIQUE (item_id, depends_on_item_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ob_checklist_item_dependencies_depends_on "
               "ON ob_checklist_item_dependencies(depends_on_item_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ob_checklist_item_dependencies_institution "
               "ON ob_checklist_item_dependencies(institution_id)")

    op.execute("ALTER TABLE ob_checklist_item_dependencies ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON ob_checklist_item_dependencies
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE ob_checklist_item_dependencies FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ob_checklist_item_dependencies")
