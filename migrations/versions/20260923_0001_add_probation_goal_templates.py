"""Add probation_goal_templates

Revision ID: 20260923_0001
Revises: 20260922_0006
Create Date: 2026-09-23

The 6 goals seeded onto every Probation Review (Month 1/2/3) cycle were
a fixed Python tuple (core/performance_probation.py's PROBATION_RUBRIC),
the same wording for every institution, with no way for HR to change
it. This table lets each institution maintain its own named list of
criteria (name, description, a relative weight), managed from a new
Settings -> Performance page (hr_manager only, matching
routers/performance.py's existing PERFORMANCE_MANAGE_ROLES for every
other Performance admin action).

`weight` is a *relative* weight, not required to sum to 100 across a
given institution's rows — create_probation_reviews (core/
performance_probation.py) normalizes proportionally to 100% across
whichever criteria are active at the moment a cycle is actually
created, so editing/adding/removing one criterion never requires
re-balancing every other row by hand in a separate request first.

No backfill: an institution with zero rows here falls back to the
original hardcoded PROBATION_RUBRIC wording at cycle-creation time
(create_probation_reviews), not a seeded copy — same lazy-default
pattern as 20260909_0001's offer_letter_templates. This table is
intentionally NOT referenced by a foreign key from goals/performance_
cycles — editing or deleting a template criterion never retroactively
changes an already-created employee's probation goals, only cycles
created from this point on.
"""
from alembic import op

revision = '20260923_0001'
down_revision = '20260922_0006'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS probation_goal_templates (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            name            TEXT    NOT NULL,
            description     TEXT,
            weight          NUMERIC(6,2) NOT NULL DEFAULT 1,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_probation_goal_templates_institution "
               "ON probation_goal_templates(institution_id, sort_order)")

    op.execute("ALTER TABLE probation_goal_templates ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON probation_goal_templates
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE probation_goal_templates FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE probation_goal_templates NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON probation_goal_templates")
    op.execute("DROP TABLE IF EXISTS probation_goal_templates")
