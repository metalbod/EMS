"""Re-date legacy Sunday-start timesheets to Monday starts

Revision ID: 20261012_0001
Revises: 20261010_0001
Create Date: 2026-10-12

My Timesheet used toISOString() to format the week's dates, which shifts a Monday to the
Sunday in UTC+ zones, so timesheets were filed Sun-Sat (see CLAUDE.md). The page now sends
Mon-Sun; this moves existing Sun-Sat rows (and the period copied onto
timesheet_project_approvals) forward one day so they line up with it. Entries keep their own
dates, so nothing about the hours changes.

A row is left alone (and listed in the migration log) when shifting it would be wrong:
  - the same employee already has a timesheet starting on the Monday (a clash), or
  - it has an entry dated on the old Sunday, which would fall outside the new range.
Those need a person to decide. The downgrade is a no-op: after the shift a re-dated row
can't be told apart from one that was always Monday-start.
"""
from alembic import op

revision = '20261012_0001'
down_revision = '20261010_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TEMP TABLE _ts_shift ON COMMIT DROP AS
        SELECT t.id FROM timesheets t
        WHERE EXTRACT(DOW FROM t.period_start::date) = 0
          AND t.period_end::date = t.period_start::date + 6
          AND NOT EXISTS (
              SELECT 1 FROM timesheets m
              WHERE m.institution_id = t.institution_id AND m.employee_id = t.employee_id
                AND m.id <> t.id AND m.period_start::date = t.period_start::date + 1)
          AND NOT EXISTS (
              SELECT 1 FROM timesheet_entries e
              WHERE e.timesheet_id = t.id
                AND (e.date::date < t.period_start::date + 1 OR e.date::date > t.period_end::date + 1))
    """)
    op.execute("""
        UPDATE timesheet_project_approvals a
        SET period_start = (a.period_start::date + 1)::text,
            period_end   = (a.period_end::date + 1)::text
        FROM timesheets t
        WHERE a.timesheet_id = t.id AND t.id IN (SELECT id FROM _ts_shift)
          AND a.period_start = t.period_start AND a.period_end = t.period_end
    """)
    op.execute("""
        UPDATE timesheets
        SET period_start = (period_start::date + 1)::text,
            period_end   = (period_end::date + 1)::text
        WHERE id IN (SELECT id FROM _ts_shift)
    """)


def downgrade():
    pass
