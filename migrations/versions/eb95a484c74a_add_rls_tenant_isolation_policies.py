"""add RLS tenant-isolation policies

Revision ID: eb95a484c74a
Revises: 75b14e73962f
Create Date: 2026-07-13 20:19:27.718641

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb95a484c74a'
down_revision: Union[str, Sequence[str], None] = '75b14e73962f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""RLS was enabled (ENABLE ROW LEVEL SECURITY) on every tenant table years
ago (see main.py's init_db()), but with zero policies defined — meaning it
had no actual effect, since Postgres denies all access by default once RLS
is enabled UNLESS a policy grants it, and this app's own connection (the
`postgres` role, confirmed non-superuser but the table OWNER) bypasses RLS
entirely unless FORCE ROW LEVEL SECURITY is also applied. Net effect before
this migration: RLS was a no-op, and tenant isolation was 100%
application-level (every query's own `WHERE institution_id=?`).

This adds real policies plus FORCE, using two per-transaction Postgres GUCs
(app.bypass_rls, app.current_institution_id) that db.py sets on every
connection borrow based on core/deps.py's get_current_user — see db.py's
_apply_rls_context for the full reasoning, including why FORCE is safe here
(the app's role is confirmed non-superuser, so FORCE actually applies) and
why SET LOCAL's per-transaction reset is handled (Conn.commit()/rollback()
reapply the GUCs for the next transaction).

Net effect: a regular institution-scoped user's query that forgets its own
WHERE institution_id filter now gets zero rows back from Postgres directly,
instead of every institution's data. superadmin's cross-institution
behavior (bypass_rls=true when no institution is selected) is unaffected.

Three tables need non-standard policies:
  - institutions: has no institution_id column — its own `id` IS the tenant.
  - okr_key_results: has no institution_id column — scoped via its parent
    goals row (goal_id FK), so the policy checks that via EXISTS.
  - system_notifications: intentionally global/platform-wide by design (see
    routers/notifications.py) — deliberately excluded from tenant scoping,
    left exactly as before (RLS enabled, no policy, no FORCE => fully open).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb95a484c74a'
down_revision: Union[str, Sequence[str], None] = '75b14e73962f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables with a direct institution_id column.
_STANDARD_TABLES = [
    "users", "employees", "audit_logs", "job_requisitions",
    "candidates", "interviews", "interview_scores", "offers",
    "candidate_audit_log", "ob_audit_log", "hr_notes",
    "ob_templates", "ob_checklists", "ob_checklist_items",
    "ld_courses", "ld_enrollments", "ld_audit_log",
    "ld_quizzes", "ld_quiz_questions", "ld_quiz_attempts",
    "ld_course_modules", "ld_lesson_progress",
    "holidays", "leave_types", "leave_balances", "leave_applications", "leave_audit_log",
    "projects", "project_tasks", "timesheets", "timesheet_entries", "timesheet_audit_log",
    "task_assignments", "institution_notifications",
    "payroll_runs", "payslips",
    "performance_cycles", "goals", "appraisals", "appraisal_audit_log", "performance_payouts",
]

_POLICY_NAME = "tenant_isolation"


def upgrade() -> None:
    for tbl in _STANDARD_TABLES:
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {tbl}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")

    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON institutions
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE institutions FORCE ROW LEVEL SECURITY")

    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON okr_key_results
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM goals g
                WHERE g.id = okr_key_results.goal_id
                  AND g.institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        )
    """)
    op.execute("ALTER TABLE okr_key_results FORCE ROW LEVEL SECURITY")

    # system_notifications is intentionally global/unscoped by design (see
    # routers/notifications.py) — no tenant policy should apply here.
    # IMPORTANT: "RLS enabled, zero policies" is NOT a no-op for a
    # non-owner/non-bypass role (which the app's runtime connection now is
    # — see db.py's ADMIN_DATABASE_URL split) — Postgres denies ALL access
    # by default once RLS is enabled unless some policy explicitly grants
    # it. This table had RLS enabled years ago (see main.py's original
    # ENABLE ROW LEVEL SECURITY loop) with no policy ever defined, which
    # was silently a no-op only because the connecting role had BYPASSRLS.
    # Disabling RLS here entirely is the honest fix, matching what this
    # table actually needs (no tenant boundary at all) rather than adding a
    # permissive USING (true) policy that would misleadingly imply RLS is
    # "in effect" for a table that was never meant to have one.
    op.execute("ALTER TABLE system_notifications DISABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for tbl in _STANDARD_TABLES + ["institutions", "okr_key_results"]:
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {tbl}")
    op.execute("ALTER TABLE system_notifications ENABLE ROW LEVEL SECURITY")
