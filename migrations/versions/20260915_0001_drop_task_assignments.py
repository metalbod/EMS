"""Drop task_assignments (per-task expected-effort scheduling removed)

Revision ID: 20260915_0001
Revises: 20260914_0002
Create Date: 2026-09-15

task_assignments (per-project-member "expected effort" — start datetime +
duration hours — on a single task) has been dead weight since
20260911_0001 moved "who can log time against a project" to
project_members: that migration's own docstring already said
task_assignments was being kept purely as a capacity-planning schedule,
not an access-control mechanism. Confirmed nothing else in the app reads
it — not timesheet entry eligibility (project_members/is_open_to_all),
not the Project Utilization dashboard (derives hours from
timesheet_entries + project_tasks.estimated_hours, never this table),
no report, payroll, or overtime calculation. Removed by product decision
(2026-09-15) rather than left as an unused UI dead-end.

Downgrade recreates the table (matching the original CREATE TABLE in
20260717_0001_full_schema_ddl.py), its RLS policy, and its
institution_id index (8fc32f58e44f) — but not its data, which this
migration does not attempt to back up. Same lossy-but-documented
tradeoff this codebase already accepted for 20260911_0001's own
project_tasks.open_to_all removal.
"""
from alembic import op


revision = '20260915_0001'
down_revision = '20260914_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    # DROP TABLE implicitly drops its policies and indexes too — no
    # separate DROP POLICY / DROP INDEX needed.
    op.execute("DROP TABLE IF EXISTS task_assignments")


def downgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_assignments (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL,
            task_id             INTEGER NOT NULL REFERENCES project_tasks(id),
            employee_id         TEXT    NOT NULL,
            start_datetime      TEXT    NOT NULL,
            duration_hours      REAL    NOT NULL,
            assigned_by         TEXT    NOT NULL,
            assigned_at         TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(task_id, employee_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_assignments_institution_id ON public.task_assignments(institution_id)")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON task_assignments
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE task_assignments FORCE ROW LEVEL SECURITY")
