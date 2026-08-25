"""split rejected candidate stage into rejected by candidate and company

Revision ID: a05baafa6355
Revises: 20260825_0001
Create Date: 2026-08-25 15:10:34.203846

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a05baafa6355'
down_revision: Union[str, Sequence[str], None] = '20260825_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""Adds 'Pending Checks' after 'Interview' and splits the single
'Rejected' candidate stage into 'Rejected by Candidate' and 'Rejected by
Company' (routers/recruitment.py's CANDIDATE_STAGES). candidates.stage is
a plain TEXT column with no CHECK constraint (application-level
validation only, see 20260717_0001's DDL), so this is a pure data
backfill, not a schema change.

Every existing 'Rejected' row is backfilled to 'Rejected by Company':
this codebase has no candidate-facing self-service portal, so every
historical stage='Rejected' was set by HR staff either directly (the
generic Move Stage action) or via the offer-decline flow (create_offer's
new_stage='Rejected' branch, sending a regret letter) — both
company-initiated, never something a candidate did themselves. There is
no data-driven way to retroactively distinguish a would-be
'Rejected by Candidate' case, so backfilling everything to
'Rejected by Company' is not a guess, it's the only case that has ever
actually happened here."""


def upgrade() -> None:
    op.execute("UPDATE candidates SET stage='Rejected by Company' WHERE stage='Rejected'")


def downgrade() -> None:
    # Lossy for any 'Rejected by Candidate' row created after this
    # migration ran (there was no such distinction before it) — collapses
    # both back to the single legacy value, matching this codebase's
    # existing convention of not over-engineering backfill-migration
    # downgrades (see a3b77dd5688e).
    op.execute("UPDATE candidates SET stage='Rejected' WHERE stage IN ('Rejected by Candidate','Rejected by Company')")
