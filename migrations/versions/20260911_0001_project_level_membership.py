"""Move team member assignment from task level to project level; add billable flag

Revision ID: 20260911_0001
Revises: 20260909_0002
Create Date: 2026-09-11

Team membership ("who can log time against this project") moves from
per-task (task_assignments + project_tasks.open_to_all) to per-project:

  - New project_members table (project_id + employee_id, many-to-many —
    same shape as project_managers, added 20260805_0001), managed
    alongside Project Manager(s) in the Edit Project modal.
  - projects.is_open_to_all replaces project_tasks.open_to_all — the
    escape hatch ("any employee can log time, no membership needed") now
    applies to the whole project rather than one task at a time.
  - projects.is_billable — a plain boolean flag for now. Project-cost
    calculations built on top of it are separate, later work — not part
    of this migration.

task_assignments itself is UNCHANGED (kept, by product decision) — it's
now purely a per-task "expected effort" schedule (start_datetime +
duration_hours) for people already on the project's member list, no
longer the mechanism that decides who CAN log time. See
routers/projects.py's add_task_assignment (now requires project
membership first) and routers/timesheets.py's add_timesheet_entry (now
checks project_members/is_open_to_all instead of task_assignments/
task-level open_to_all).

Backfill: every employee_id currently reachable via
task_assignments -> project_tasks (i.e. everyone who could clock time
under the old model) is inserted into project_members for that project,
so no one loses timesheet access when this ships. Any project that had
at least one open_to_all task is marked is_open_to_all=true, for the
same reason — both are documented approximations of "keep current
access working," not a data-preserving 1:1 mapping (there wasn't one).
"""
from alembic import op
import sqlalchemy as sa


revision = '20260911_0001'
down_revision = '20260909_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_open_to_all BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_billable BOOLEAN NOT NULL DEFAULT false")

    op.create_table(
        'project_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_project_members_project_id', 'project_members', ['project_id'])
    op.create_unique_constraint('uq_project_members_project_employee', 'project_members', ['project_id', 'employee_id'])
    # No institution_id of its own — scope through the parent project, same
    # pattern as project_managers (20260805_0001).
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON project_members
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM projects p
                WHERE p.id = project_members.project_id
                  AND p.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE project_members FORCE ROW LEVEL SECURITY")

    # Backfill from the old task-level model so no one loses timesheet access.
    op.execute("""
        INSERT INTO project_members (project_id, employee_id)
        SELECT DISTINCT t.project_id, ta.employee_id
        FROM task_assignments ta JOIN project_tasks t ON t.id = ta.task_id
        ON CONFLICT (project_id, employee_id) DO NOTHING
    """)
    # project_tasks.open_to_all is a plain INTEGER 0/1 (see
    # 20260717_0001_full_schema_ddl.py), not a real boolean column — hence
    # comparing against 1, not true/false, below.
    op.execute("""
        UPDATE projects SET is_open_to_all = true
        WHERE id IN (SELECT DISTINCT project_id FROM project_tasks WHERE open_to_all = 1)
    """)

    op.execute("ALTER TABLE project_tasks DROP COLUMN IF EXISTS open_to_all")


def downgrade():
    op.execute("ALTER TABLE project_tasks ADD COLUMN IF NOT EXISTS open_to_all INTEGER NOT NULL DEFAULT 0")
    # Lossy/approximate, same direction as the forward backfill: every task
    # in a formerly-open project is marked open again, rather than trying
    # to reconstruct which specific tasks were open before.
    op.execute("""
        UPDATE project_tasks SET open_to_all = 1
        WHERE project_id IN (SELECT id FROM projects WHERE is_open_to_all = true)
    """)

    op.execute("ALTER TABLE project_members NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON project_members")
    op.drop_constraint('uq_project_members_project_employee', 'project_members', type_='unique')
    op.drop_index('ix_project_members_project_id', table_name='project_members')
    op.drop_table('project_members')

    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_billable")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_open_to_all")
