"""add institution_id indexes for RLS-filtered tables

Revision ID: 8fc32f58e44f
Revises: eb95a484c74a
Create Date: 2026-07-15 15:37:31.159947

Every table covered by the tenant_isolation RLS policy (see
eb95a484c74a) is now implicitly filtered by `WHERE institution_id = ...`
on every query, via the policy predicate — but only 3 of those tables
(employees, holidays, payroll_runs) happen to have institution_id as the
leading column of an existing UNIQUE constraint, and therefore an index.
The other tables have no index backing that filter at all, meaning every
RLS-scoped query on them is a full table scan. This was invisible before
RLS was actually enforced (the old `postgres` connection role had
BYPASSRLS, so the policy predicate was never evaluated in practice).

Tables are small in the current dataset, so this hasn't shown up as a
measurable slowdown yet, but there's no reason to leave the gap now that
it's a straightforward, low-risk migration.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8fc32f58e44f'
down_revision: Union[str, Sequence[str], None] = 'eb95a484c74a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# _STANDARD_TABLES from eb95a484c74a, minus the three that already have
# institution_id as the leading column of a UNIQUE constraint (employees,
# holidays, payroll_runs), and minus institutions/okr_key_results, which
# eb95a484c74a special-cases (no direct institution_id column on either).
_TABLES_NEEDING_INDEX = [
    "users", "audit_logs", "job_requisitions",
    "candidates", "interviews", "interview_scores", "offers",
    "candidate_audit_log", "ob_audit_log", "hr_notes",
    "ob_templates", "ob_checklists", "ob_checklist_items",
    "ld_courses", "ld_enrollments", "ld_audit_log",
    "ld_quizzes", "ld_quiz_questions", "ld_quiz_attempts",
    "ld_course_modules", "ld_lesson_progress",
    "leave_types", "leave_balances", "leave_applications", "leave_audit_log",
    "projects", "project_tasks", "timesheets", "timesheet_entries", "timesheet_audit_log",
    "task_assignments", "institution_notifications",
    "payslips",
    "performance_cycles", "goals", "appraisals", "appraisal_audit_log", "performance_payouts",
]


def upgrade() -> None:
    """Upgrade schema."""
    # Schema-qualified deliberately: "users" collides with Supabase's own
    # auth.users table, and search_path resolution isn't worth relying on
    # for a migration that runs against a live shared database.
    for tbl in _TABLES_NEEDING_INDEX:
        op.execute(f'CREATE INDEX IF NOT EXISTS idx_{tbl}_institution_id ON public.{tbl}(institution_id)')


def downgrade() -> None:
    """Downgrade schema."""
    for tbl in _TABLES_NEEDING_INDEX:
        op.execute(f'DROP INDEX IF EXISTS public.idx_{tbl}_institution_id')
