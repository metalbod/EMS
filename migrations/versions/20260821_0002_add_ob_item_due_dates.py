"""Add due-date support to onboarding/offboarding templates and checklist items

Revision ID: 20260821_0002
Revises: 20260821_0001
Create Date: 2026-08-21

ob_templates.due_date_rule is a relative-date RULE (one of a fixed set —
see routers/onboarding.py's OB_DUE_DATE_RULES), picked when defining a
template item — there's no concrete employee yet to compute an actual
date against. ob_checklist_items.due_date is the concrete, per-employee
datetime: resolved from the template's rule (against that employee's
start_date/date_of_birth and the checklist's start date) the moment
start_ob_checklist() snapshots template items into checklist items, and
freely editable afterwards per employee (also settable directly on an
ad-hoc item added straight to one employee's checklist, which has no
template/rule to resolve from). Any checklist item with a due_date set
is surfaced on the Leave Calendar (see routers/onboarding.py's
get_ob_calendar) for whichever role it's assigned to.
"""
from alembic import op


revision = '20260821_0002'
down_revision = '20260821_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE ob_templates ADD COLUMN IF NOT EXISTS due_date_rule TEXT")
    op.execute("ALTER TABLE ob_checklist_items ADD COLUMN IF NOT EXISTS due_date TEXT")


def downgrade():
    op.execute("ALTER TABLE ob_checklist_items DROP COLUMN IF EXISTS due_date")
    op.execute("ALTER TABLE ob_templates DROP COLUMN IF EXISTS due_date_rule")
