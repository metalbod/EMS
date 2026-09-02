"""Add employees consent flags (FR integration)

Revision ID: 20260902_0001
Revises: de442e62352a
Create Date: 2026-09-02

Three per-employee consent flags backing the FR (facial-recognition
attendance kiosk) integration's roster feed — see
docs/FR_INTEGRATION.md for the full API contract. All default to 0
(not consented): an employee is not recognisable, not greeted by name,
and not given a birthday greeting until HR explicitly opts them in via
the Employee detail page's new consent panel. This is a deliberate
opt-in-only default for biometric-adjacent data (PDPA), not an
oversight — every existing employee starts fully opted out too.

- consent_recognition:  false -> FR must not enrol or match this person at all
- consent_display_name: false -> they clock in silently, no greeting card
- consent_dob:           false -> no birthday greeting even if DOB is present

INTEGER 0/1, matching this codebase's existing boolean-column
convention (is_active etc. across the schema), not native BOOLEAN.
"""
from alembic import op


revision = '20260902_0001'
down_revision = 'de442e62352a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS consent_recognition INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS consent_display_name INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS consent_dob INTEGER NOT NULL DEFAULT 0")


def downgrade():
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS consent_dob")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS consent_display_name")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS consent_recognition")
