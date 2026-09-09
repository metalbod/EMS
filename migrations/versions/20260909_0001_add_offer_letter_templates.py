"""Add offer_letter_templates

Revision ID: 20260909_0001
Revises: 20260902_0001
Create Date: 2026-09-09

Recruitment's Offer/Decline letters were previously generated from a
single hardcoded Python f-string per type (_gen_offer_letter in
routers/recruitment.py) — no way for HR to edit the wording without a
code change. This table lets each institution maintain named,
placeholder-driven templates per offer_type ('Offer' or 'Decline'),
managed from a new "Manage Templates" tab on the Offers & Letters page.

No backfill: a default template per offer_type is created lazily, the
first time it's needed, by
routers/recruitment.py's _get_or_create_default_offer_template — same
resolve-or-create-default pattern already used for approval workflows
(get_or_create_default_workflow) and onboarding template sets
(_get_or_create_default_template_set), rather than seeding a row for
every institution up front. The lazily-created default's body is the
exact wording _gen_offer_letter used to hardcode, just parameterized
with ${placeholder} substitutions (string.Template) instead of an
f-string, so nothing about existing generated letters changes.

offers.letter_content stays a plain snapshot of the rendered text at
creation time (unchanged) — this table is intentionally NOT referenced
by a foreign key from offers, so editing or deleting a template never
retroactively changes an already-generated letter.
"""
from alembic import op


revision = '20260909_0001'
down_revision = '20260902_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS offer_letter_templates (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            offer_type      TEXT    NOT NULL,
            name            TEXT    NOT NULL,
            body            TEXT    NOT NULL,
            is_default      INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_offer_letter_templates_institution_type "
               "ON offer_letter_templates(institution_id, offer_type)")

    op.execute("ALTER TABLE offer_letter_templates ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON offer_letter_templates
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE offer_letter_templates FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE offer_letter_templates NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON offer_letter_templates")
    op.execute("DROP TABLE IF EXISTS offer_letter_templates")
