"""Add ob_template_sets for multiple onboarding/offboarding templates

Revision ID: 20260802_0001
Revises: 20260730_0002
Create Date: 2026-08-02

ob_templates was a flat, singleton checklist per institution_id+type —
one onboarding template and one offboarding template per institution,
with no way to have e.g. separate "Engineering Onboarding" and "Sales
Onboarding" checklists. This adds ob_template_sets (a named, orderable
group of template items, one of which can be flagged default per
institution_id+type) and points ob_templates.template_set_id at it.
Existing template rows are backfilled into a "Default" set per
institution_id+type so nothing already configured is lost.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260802_0001'
down_revision = '20260730_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ob_template_sets (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            type            TEXT    NOT NULL DEFAULT 'onboarding',
            name            TEXT    NOT NULL,
            is_default      INTEGER NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    # New tenant tables need their tenant_isolation RLS policy created
    # explicitly (see eb95a484c74a) — the ensure_rls event trigger only
    # flips RLS on, it doesn't grant any access, so without this every
    # query/insert against ob_template_sets would be denied outright.
    op.execute("""
        CREATE POLICY tenant_isolation ON ob_template_sets
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE ob_template_sets FORCE ROW LEVEL SECURITY")
    op.add_column('ob_templates', sa.Column('template_set_id', sa.Integer(), sa.ForeignKey('ob_template_sets.id'), nullable=True))
    op.create_index('ix_ob_templates_template_set_id', 'ob_templates', ['template_set_id'])

    # Backfill: one "Default" set per institution_id+type that already has template items.
    op.execute("""
        INSERT INTO ob_template_sets (institution_id, type, name, is_default, is_active)
        SELECT DISTINCT institution_id, type, 'Default', 1, 1
        FROM ob_templates
    """)
    op.execute("""
        UPDATE ob_templates t
        SET template_set_id = s.id
        FROM ob_template_sets s
        WHERE s.institution_id = t.institution_id AND s.type = t.type AND s.name = 'Default'
    """)


def downgrade():
    op.drop_index('ix_ob_templates_template_set_id', table_name='ob_templates')
    op.drop_column('ob_templates', 'template_set_id')
    op.execute("ALTER TABLE ob_template_sets NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ob_template_sets")
    op.execute("DROP TABLE IF EXISTS ob_template_sets")
