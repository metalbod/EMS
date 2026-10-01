"""Phase 4: drop candidates' now-legacy application-level columns

Revision ID: 20261001_0001
Revises: 20260930_0002
Create Date: 2026-10-01

Final phase of "one candidate, many requisitions" (see
20260930_0002_add_candidate_requisitions for Phase 1, and
routers/recruitment.py's git history for Phases 2-3). candidate_requisitions
has been the real per-application record — stage/source/notes/
expected_salary/notice_period/referral_by, plus requisition_id itself —
since Phase 2 shipped; candidates.requisition_id/stage/source/notes/
expected_salary/notice_period/referral_by have been a read-only-by-nothing,
write-only transitional mirror since then (see
_transition_candidate_stage's old docstring in routers/recruitment.py,
removed in the same commit as this migration), kept in sync only while a
candidate had exactly one application. Every remaining backend/frontend
read of those columns was rewired (list_candidates, get_candidate,
convert_to_employee_prefill, schedule_interview's/create_offer's
requisition_id resolution, the Candidate Bank table, the Interview/Offer
candidate pickers) in the same commit as this migration — this file only
removes the now genuinely dead columns and their index.

candidates.full_name/email/phone/ic_number/nationality/gender/
date_of_birth/address/current_position/current_company/experience_years/
employment_history/highest_qualification/field_of_study/institution_name/
graduation_year/certifications/skills/resume_text/linkedin_url stay
untouched — those are true person-level fields, never application-level.
"""
from alembic import op

revision = '20261001_0001'
down_revision = '20260930_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX IF EXISTS idx_candidates_requisition_id")
    op.execute("""
        ALTER TABLE candidates
            DROP COLUMN IF EXISTS requisition_id,
            DROP COLUMN IF EXISTS stage,
            DROP COLUMN IF EXISTS source,
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS expected_salary,
            DROP COLUMN IF EXISTS notice_period,
            DROP COLUMN IF EXISTS referral_by
    """)


def downgrade():
    op.execute("""
        ALTER TABLE candidates
            ADD COLUMN requisition_id INTEGER REFERENCES job_requisitions(id),
            ADD COLUMN stage TEXT NOT NULL DEFAULT 'New',
            ADD COLUMN source TEXT NOT NULL DEFAULT 'Direct',
            ADD COLUMN notes TEXT,
            ADD COLUMN expected_salary NUMERIC(12,2),
            ADD COLUMN notice_period TEXT,
            ADD COLUMN referral_by TEXT
    """)
    # Best-effort backfill from each candidate's oldest application, so a
    # downgrade doesn't silently reset every candidate to 'New'/'Direct'
    # regardless of real state — same spirit as Phase 1's own forward
    # backfill, just run in reverse.
    op.execute("""
        UPDATE candidates c SET
            requisition_id = cr.requisition_id,
            stage = cr.stage,
            source = cr.source,
            notes = cr.notes,
            expected_salary = cr.expected_salary,
            notice_period = cr.notice_period,
            referral_by = cr.referral_by
        FROM candidate_requisitions cr
        WHERE cr.candidate_id = c.id
          AND cr.id = (SELECT MIN(id) FROM candidate_requisitions WHERE candidate_id = c.id)
    """)
    op.create_index('idx_candidates_requisition_id', 'candidates', ['requisition_id'])
