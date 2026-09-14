"""Add login_audit_log

Revision ID: 20260914_0002
Revises: 20260914_0001
Create Date: 2026-09-14

Records every login attempt (success and failure) — previously only a
process-local logger.warning() (routers/auth.py's _record_login_failure),
with no in-app trail an HR manager or superadmin could actually review.

Not folded into the existing audit_logs table: that table's
institution_id, actor_id, target_employee_name are all NOT NULL, which
can't represent a failed login (no resolvable user) or a superadmin/
platform login (no institution) — the same reason candidate_audit_log,
ob_audit_log, etc. are each their own dedicated table rather than
force-fit into audit_logs.

username is stored as typed (not just user_id) since a failed attempt on
a nonexistent username never resolves to a real users row.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260914_0002'
down_revision = '20260914_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS login_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER REFERENCES institutions(id) ON DELETE SET NULL,
            username        TEXT    NOT NULL,
            user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
            success         BOOLEAN NOT NULL,
            reason          TEXT,
            ip_address      TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_login_audit_log_institution_created "
               "ON login_audit_log(institution_id, created_at DESC)")

    op.execute("ALTER TABLE login_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON login_audit_log
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE login_audit_log FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE login_audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON login_audit_log")
    op.execute("DROP TABLE IF EXISTS login_audit_log")
