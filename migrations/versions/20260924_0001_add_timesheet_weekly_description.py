"""Add one description per timesheet (weekly), replacing per-entry description

Revision ID: 20260924_0001
Revises: 20260923_0001
Create Date: 2026-09-24

My Timesheet's entry screen moves from a flat list (one row per logged
entry, each with its own free-text description) to a weekly grid (rows
= project/task, columns = the 7 days) — see static/js/timesheet.js's
grid rewrite. A description per day-cell doesn't fit that shape, and
per the project owner's own call, there's only ever one description for
the whole week now, not one per row either.

`timesheets.description` is new and employee-authored (distinct from
the existing `timesheets.notes` / `timesheet_project_approvals.notes`,
which are the *reviewer's* approve/reject comment — never conflate the
two, they have different authors and different purposes).

`timesheet_entries.description` is intentionally left in place, not
dropped: already-saved entries keep whatever per-day description they
were given under the old flat-list screen (no data loss), the grid's
own entry create/update calls just stop populating it going forward.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260924_0001'
down_revision = '20260923_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('timesheets', sa.Column('description', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('timesheets', 'description')
