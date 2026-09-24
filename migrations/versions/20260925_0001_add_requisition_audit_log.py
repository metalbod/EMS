"""Add requisition_audit_log

Revision ID: 20260925_0001
Revises: 20260924_0001
Create Date: 2026-09-25

Job requisitions had no audit trail at all — not for edits to the JD/
fields, and not for the approval trail beyond the single, self-
overwriting job_requisitions.approval_comments column (each new
approval step's comment destroyed the previous one, and the default
sequential approval-workflow mode never recorded *who* cleared an
intermediate step, only the final approved_by). See routers/
recruitment.py's _log_requisition and its call sites in create/update/
submit/approve/close_requisition — every step of the approval chain now
gets its own row here, not just the final decision.

Same shape as candidate_audit_log (20260717_0001), plus performer_role
(matching the richer timesheet_audit_log/leave_audit_log shape) since
which role acted at which approval step is exactly the kind of detail
this exists to surface.
"""
from alembic import op

revision = '20260925_0001'
down_revision = '20260924_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS requisition_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER NOT NULL,
            requisition_id  INTEGER NOT NULL REFERENCES job_requisitions(id),
            action          TEXT    NOT NULL,
            detail          TEXT,
            performed_by    TEXT    NOT NULL,
            performer_role  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_requisition_audit_log_requisition ON requisition_audit_log(requisition_id)")

    op.execute("ALTER TABLE requisition_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON requisition_audit_log
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE requisition_audit_log FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE requisition_audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON requisition_audit_log")
    op.execute("DROP TABLE IF EXISTS requisition_audit_log")
