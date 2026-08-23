"""Add onboarding Probation Review support (employee-scoped Performance cycles)

Revision ID: 20260822_0002
Revises: 20260822_0001
Create Date: 2026-08-22

An HR Manager can opt a specific employee's onboarding checklist into
"Probation Review" (Month 1/2/3) — not automatic for every employee, and
not template-driven; a per-employee decision, since not everyone goes
through probation. When enabled, three performance_cycles rows are
created up front, each scoped to that one employee (cycle_type=
'probation', employee_id set) rather than the institution-wide batch
cycles HR creates manually via POST /api/performance/cycles (which stay
cycle_type='standard', employee_id NULL — this migration changes
nothing about their existing behavior). Each probation cycle gets
exactly one appraisal (not the org-wide fan-out
activate_performance_cycle does for standard cycles) and 6 fixed-rubric
KPI goals, then goes through the same Self -> Manager -> Calibration ->
Final flow as any other appraisal, fully reusing that engine.

source_ob_checklist_id lets Onboarding's Checklist Detail query "this
employee's 3 probation cycles" directly, independent of whatever
checklist items that institution's template happens to have.
"""
from alembic import op


revision = '20260822_0002'
down_revision = '20260822_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE ob_checklists ADD COLUMN IF NOT EXISTS probation_enabled INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS employee_id TEXT")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS cycle_type TEXT NOT NULL DEFAULT 'standard'")
    op.execute("ALTER TABLE performance_cycles ADD COLUMN IF NOT EXISTS source_ob_checklist_id INTEGER")
    op.execute("ALTER TABLE performance_cycles DROP CONSTRAINT IF EXISTS performance_cycles_cycle_type_check")
    op.execute(
        "ALTER TABLE performance_cycles ADD CONSTRAINT performance_cycles_cycle_type_check "
        "CHECK (cycle_type IN ('standard','probation'))"
    )


def downgrade():
    op.execute("ALTER TABLE performance_cycles DROP CONSTRAINT IF EXISTS performance_cycles_cycle_type_check")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS source_ob_checklist_id")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS cycle_type")
    op.execute("ALTER TABLE performance_cycles DROP COLUMN IF EXISTS employee_id")
    op.execute("ALTER TABLE ob_checklists DROP COLUMN IF EXISTS probation_enabled")
