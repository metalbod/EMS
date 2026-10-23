"""Leave type eligibility: who may use a leave type (gender / married / minimum service), plus per-person exceptions

Revision ID: 20261020_0001
Revises: 20261019_0001
Create Date: 2026-10-24

leave_types.eligible_gender     'Any' (default), 'Male' or 'Female' - e.g. Maternity = Female, Paternity = Male.
leave_types.require_married     1 = only employees whose marital status is Married.
leave_types.min_service_months  0 = no minimum; otherwise months from the employee's start date to the leave's start date.
leave_type_eligibility_overrides
                                HR's exception for ONE person and ONE type: allowed = 1 grants it despite the rules, 0 withholds
                                it despite them. A reason is required (it is audited). Tenant-scoped.

Defaults reproduce today's behaviour (everyone may use every type), so nothing changes until HR sets a rule. Old code ignores the
new columns, so rolling the app back after this migration is safe.
"""
from alembic import op

revision = '20261020_0001'
down_revision = '20261019_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE leave_types ADD COLUMN IF NOT EXISTS eligible_gender TEXT NOT NULL DEFAULT 'Any'")
    op.execute("ALTER TABLE leave_types ADD COLUMN IF NOT EXISTS require_married INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE leave_types ADD COLUMN IF NOT EXISTS min_service_months INTEGER NOT NULL DEFAULT 0")
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE leave_types ADD CONSTRAINT leave_types_eligible_gender_check CHECK (eligible_gender IN ('Any','Male','Female'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS leave_type_eligibility_overrides (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            leave_type_id   INTEGER NOT NULL REFERENCES leave_types(id) ON DELETE CASCADE,
            employee_id     TEXT    NOT NULL,
            allowed         INTEGER NOT NULL,
            reason          TEXT    NOT NULL,
            created_by      TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE (leave_type_id, employee_id)
        )
    """)
    # The ensure_rls trigger turns RLS on at creation; with no policy every query would return nothing.
    op.execute("ALTER TABLE leave_type_eligibility_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON leave_type_eligibility_overrides
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE leave_type_eligibility_overrides FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS leave_type_eligibility_overrides")
    op.execute("ALTER TABLE leave_types DROP CONSTRAINT IF EXISTS leave_types_eligible_gender_check")
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS min_service_months")
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS require_married")
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS eligible_gender")
