"""Add manager-initiated Performance Improvement Plan (PIP) support

Revision ID: 20260825_0001
Revises: 20260824_0001
Create Date: 2026-08-25

A direct manager can propose a PIP for one of their reports — like
Probation Review, this is another employee-scoped performance_cycles
row (cycle_type='pip'), reusing the same goals-tracking machinery rather
than a parallel schema. Unlike probation, a PIP:
  - Must clear HR approval before it takes effect — routed through the
    shared approval-workflow engine (new "pip" module, see
    core/approval_workflow.py) via new nullable approval_workflow_id/
    approval_step columns, only ever populated for cycle_type='pip' rows
    (standard/probation cycles never use this engine, so there is no
    collision risk sharing the table — every approval-workflow query
    already filters on these columns being NOT NULL).
  - Has manager-defined start/end dates (period_start/period_end,
    columns that already exist) instead of Probation's fixed Month
    1/2/3 windows.
  - Never gets an appraisals row — its "final assessment" is a plain
    recorded outcome (outcome/outcome_notes/outcome_decided_by/
    outcome_decided_at), not a numeric rating.
  - Gets a lightweight periodic check-in log (new pip_checkins table)
    instead of the Self->Manager->Calibration->Final review flow.

New status value used only by PIP: 'PendingApproval' (manager has
proposed, awaiting HR decision) and 'Rejected' (terminal, HR declined) —
existing cycle_type values never use either string, so no ambiguity
with the standard Draft/Active/Calibration/Closed progression.

pip_checkins carries its own institution_id directly (matching
employee_documents' migration, not the rarer EXISTS-through-parent
pattern), so it needs its own explicit tenant_isolation RLS policy — a
table gets RLS auto-enabled with zero policies the moment it's created,
which fails closed (every query returns nothing) until a policy exists.
"""
from alembic import op


revision = '20260825_0001'
down_revision = '20260824_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS approval_workflow_id INTEGER")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS approval_step INTEGER")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS reason TEXT")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS outcome TEXT")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS outcome_notes TEXT")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS outcome_decided_by TEXT")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS outcome_decided_at TEXT")

    op.execute("ALTER TABLE performance_cycles DROP CONSTRAINT IF EXISTS performance_cycles_cycle_type_check")
    op.execute(
        "ALTER TABLE performance_cycles ADD CONSTRAINT performance_cycles_cycle_type_check "
        "CHECK (cycle_type IN ('standard','probation','pip'))"
    )
    op.execute("ALTER TABLE performance_cycles DROP CONSTRAINT IF EXISTS performance_cycles_outcome_check")
    op.execute(
        "ALTER TABLE performance_cycles ADD CONSTRAINT performance_cycles_outcome_check "
        "CHECK (outcome IS NULL OR outcome IN ('Successful','Extended','Failed'))"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS pip_checkins (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            cycle_id        INTEGER NOT NULL REFERENCES performance_cycles(id),
            checkin_date    TEXT    NOT NULL,
            notes           TEXT    NOT NULL,
            created_by      TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pip_checkins_institution_id ON pip_checkins(institution_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pip_checkins_cycle_id ON pip_checkins(cycle_id)")

    op.execute("ALTER TABLE pip_checkins ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON pip_checkins
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE pip_checkins FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE pip_checkins NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON pip_checkins")
    op.execute("DROP TABLE IF EXISTS pip_checkins")

    op.execute("ALTER TABLE performance_cycles DROP CONSTRAINT IF EXISTS performance_cycles_outcome_check")
    op.execute("ALTER TABLE performance_cycles DROP CONSTRAINT IF EXISTS performance_cycles_cycle_type_check")
    op.execute(
        "ALTER TABLE performance_cycles ADD CONSTRAINT performance_cycles_cycle_type_check "
        "CHECK (cycle_type IN ('standard','probation'))"
    )
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS outcome_decided_at")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS outcome_decided_by")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS outcome_notes")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS outcome")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS reason")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS approval_step")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS approval_workflow_id")
