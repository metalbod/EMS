"""Add entity_audit_log

Revision ID: 20260926_0001
Revises: 20260925_0001
Create Date: 2026-09-26

One generic, tenant-scoped audit trail for every module that had none
(payroll, users/roles, approval workflows, institution/secret settings,
and the later phases' compensation/leave/attendance/benefits/etc.) —
instead of ~20 more per-module *_audit_log tables. Each row names the
module, the entity type and id it touched, an action, a human-readable
detail and/or a structured field diff (`changes`, JSON text of
[{field,label,old,new}], same shape core/audit.py's write_audit already
stores for employees, with sensitive values masked before they get here).

institution_id is nullable on purpose: platform-level actions (e.g.
creating a superadmin account) have no tenant. Such rows are only ever
visible to a bypass-RLS (superadmin) session, same as login_audit_log.
"""
from alembic import op

revision = '20260926_0001'
down_revision = '20260925_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS entity_audit_log (
            id              SERIAL  PRIMARY KEY,
            institution_id  INTEGER,
            module          TEXT    NOT NULL,
            entity_type     TEXT    NOT NULL,
            entity_id       TEXT,
            entity_label    TEXT,
            action          TEXT    NOT NULL,
            detail          TEXT,
            changes         TEXT,
            actor_id        INTEGER,
            actor_username  TEXT,
            actor_role      TEXT,
            ip_address      TEXT,
            created_at      TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_entity_audit_log_inst_created ON entity_audit_log(institution_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entity_audit_log_entity ON entity_audit_log(entity_type, entity_id)")

    op.execute("ALTER TABLE entity_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON entity_audit_log
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE entity_audit_log FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE entity_audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON entity_audit_log")
    op.execute("DROP TABLE IF EXISTS entity_audit_log")
