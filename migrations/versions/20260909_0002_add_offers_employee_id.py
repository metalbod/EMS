"""Add offers.employee_id for Confirmation letters

Revision ID: 20260909_0002
Revises: 20260909_0001
Create Date: 2026-09-09

Probation Confirmation letters (Settings -> Letter Templates' new
"Confirmation" offer_type, triggered from the Employee detail page's new
"Confirm Probation" action) are about an existing *employee*, not a
recruitment *candidate* — offers.candidate_id (NOT NULL) can't represent
that. Rather than forking a second table, this makes candidate_id
nullable and adds a nullable employee_id (TEXT, no FK — matching every
other employee_id column in this schema, e.g. leave_applications,
timesheets: only institution_id+employee_id together are unique on
employees, so a plain single-column FK isn't meaningful here either), with
a CHECK enforcing exactly one of the two is ever set. offer_type='Offer'/
'Decline' rows keep using candidate_id as before; 'Confirmation' rows use
employee_id instead. See routers/recruitment.py's create_offer/get_offer/
list_offers/delete_offer for the branching this enables.
"""
from alembic import op


revision = '20260909_0002'
down_revision = '20260909_0001'
branch_labels = None
depends_on = None

_CHECK_NAME = "offers_candidate_xor_employee_chk"


def upgrade():
    op.execute("ALTER TABLE offers ALTER COLUMN candidate_id DROP NOT NULL")
    op.execute("ALTER TABLE offers ADD COLUMN IF NOT EXISTS employee_id TEXT")
    op.execute(f"""
        ALTER TABLE offers ADD CONSTRAINT {_CHECK_NAME} CHECK (
            (candidate_id IS NOT NULL AND employee_id IS NULL) OR
            (candidate_id IS NULL AND employee_id IS NOT NULL)
        )
    """)


def downgrade():
    op.execute(f"ALTER TABLE offers DROP CONSTRAINT IF EXISTS {_CHECK_NAME}")
    # Employee-only rows (Confirmation letters) have no candidate_id to
    # backfill — deleted rather than left violating the restored NOT NULL,
    # same "lossy downgrade, documented not silent" approach as this
    # project's other downgrades that remove a since-added capability.
    op.execute("DELETE FROM offers WHERE candidate_id IS NULL")
    op.execute("ALTER TABLE offers DROP COLUMN IF EXISTS employee_id")
    op.execute("ALTER TABLE offers ALTER COLUMN candidate_id SET NOT NULL")
