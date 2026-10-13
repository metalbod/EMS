"""Interview interviewers: link interviews to real employees

Revision ID: 20261016_0001
Revises: 20261015_0001
Create Date: 2026-10-16

interviews.interviewers stays as the display text (and for interviews scheduled before this, whatever HR typed).
interview_interviewers is the real link — one row per employee picked as an interviewer — so each person can get
the interview on their Home To-Do, open it on My Interviews, and have their score matched to them.
"""
from alembic import op

revision = '20261016_0001'
down_revision = '20261015_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS interview_interviewers (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL REFERENCES institutions(id),
            interview_id    INTEGER NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
            employee_id     TEXT    NOT NULL,
            UNIQUE (interview_id, employee_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_interview_interviewers_employee ON interview_interviewers(institution_id, employee_id)")
    op.execute("ALTER TABLE interview_interviewers ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON interview_interviewers
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE interview_interviewers FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("DROP TABLE IF EXISTS interview_interviewers")
