"""backfill ob_template_sets for institutions still missing one

Revision ID: a3b77dd5688e
Revises: 20260807_0002
Create Date: 2026-08-10 17:18:20.976785

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b77dd5688e'
down_revision: Union[str, Sequence[str], None] = '20260807_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""Follow-up to 20260802_0001, which backfilled an ob_template_sets row for
every institution_id+type that had ob_templates rows *at that time* — but
nothing kept new institutions in sync afterward. seed_ob_templates (run for
every institution created since) only ever inserts legacy, un-set-scoped
templates (template_set_id left NULL), never a matching ob_template_sets
row. Combined with a since-fixed app bug (`template_set_id = ?` with a
bound None, which never matches even a genuinely-NULL column), this meant
every institution created after 20260802_0001 shipped got zero items on
every onboarding/offboarding checklist — 293 institutions in prod as of
2026-08-10. The app-level bug is already fixed and doesn't strictly need
this to work, but institutions in this state show an empty
GET /api/ob/template-sets, which is misleading. This mirrors
20260802_0001's exact backfill query, scoped to institution_id+type combos
that still have none.

Confirmed via a direct query before writing this that no institution had
already independently created its own default set alongside leftover
legacy items (which would need those legacy items merged into the
existing set instead of a new one) — every affected combo has zero
ob_template_sets rows, so a plain backfill is safe."""


def upgrade() -> None:
    op.execute("""
        INSERT INTO ob_template_sets (institution_id, type, name, is_default, is_active)
        SELECT DISTINCT t.institution_id, t.type, 'Default', 1, 1
        FROM ob_templates t
        WHERE t.template_set_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM ob_template_sets s
              WHERE s.institution_id = t.institution_id AND s.type = t.type
          )
    """)
    op.execute("""
        UPDATE ob_templates t
        SET template_set_id = s.id
        FROM ob_template_sets s
        WHERE s.institution_id = t.institution_id AND s.type = t.type AND s.name = 'Default'
          AND t.template_set_id IS NULL
    """)


def downgrade() -> None:
    # Irreversible by design: undoing this would mean guessing which
    # ob_template_sets rows this migration created vs. ones a user created
    # or modified afterward (renamed, changed is_default, added more
    # templates to). Not attempted, matching this codebase's existing
    # convention for backfill-style data migrations.
    pass
