"""Add employee document compliance tracking (work permit/passport/etc expiry)

Revision ID: 20260824_0001
Revises: 20260823_0002
Create Date: 2026-08-24

HR Manager/HR Admin want reminders for time-sensitive employee document
expiries — e.g. a foreign employee's work permit renewal or passport
expiry. The set of tracked document types is HR-configurable per
institution (employee_document_types, one row per type e.g. "Work
Permit"/"Passport", each with its own reminder_window_days), and each
employee can have zero or more tracked instances (employee_documents,
one row per (employee, document type) — UNIQUE constraint, since renewing
a document means updating its expiry_date in place rather than creating
a new row; a full renewal-history table is left as a future extension if
ever needed).

No cron job computes "expiring soon" — per this project's established
pattern (see core/leave_balance_ops.py's carry-forward expiry sweep),
status is computed fresh on every read via SQL CURRENT_DATE comparisons
in routers/employee_documents.py, reused by the Dashboard To-Do count and
the Dashboard monthly Leave Calendar's document-expiry chips.

Both tables carry their own institution_id directly (same shape as
candidate_documents/leave_types), so both need their own explicit
tenant_isolation RLS policy — a table gets RLS auto-enabled by the
ensure_rls event trigger the moment it's created, with zero policies,
which means every query returns nothing until a policy exists.
"""
from alembic import op


revision = '20260824_0001'
down_revision = '20260823_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_document_types (
            id                      SERIAL  PRIMARY KEY,
            institution_id          INTEGER NOT NULL REFERENCES institutions(id),
            name                    TEXT    NOT NULL,
            reminder_window_days    INTEGER NOT NULL DEFAULT 30,
            is_active               INTEGER NOT NULL DEFAULT 1,
            created_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_employee_document_types_institution_id ON employee_document_types(institution_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_documents (
            id                      SERIAL  PRIMARY KEY,
            institution_id          INTEGER NOT NULL REFERENCES institutions(id),
            employee_id             TEXT    NOT NULL,
            document_type_id        INTEGER NOT NULL REFERENCES employee_document_types(id),
            document_number         TEXT,
            issue_date              TEXT,
            expiry_date             TEXT    NOT NULL,
            notes                   TEXT,
            attachment_file_name    TEXT,
            attachment_mime_type    TEXT,
            attachment_data_url     TEXT,
            created_by              TEXT    NOT NULL,
            updated_by              TEXT,
            created_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(employee_id, document_type_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_employee_documents_institution_id ON employee_documents(institution_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_employee_documents_employee_id ON employee_documents(employee_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_employee_documents_expiry_date ON employee_documents(expiry_date)")

    op.execute("DROP TRIGGER IF EXISTS trg_employee_documents_upd ON employee_documents")
    op.execute("""
        CREATE TRIGGER trg_employee_documents_upd BEFORE UPDATE ON employee_documents
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    for tbl in ("employee_document_types", "employee_documents"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {_POLICY_NAME} ON {tbl}
            USING (
                current_setting('app.bypass_rls', true) = 'true'
                OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
            )
        """)
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")


def downgrade():
    for tbl in ("employee_documents", "employee_document_types"):
        op.execute(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {tbl}")
    op.execute("DROP TRIGGER IF EXISTS trg_employee_documents_upd ON employee_documents")
    op.execute("DROP TABLE IF EXISTS employee_documents")
    op.execute("DROP TABLE IF EXISTS employee_document_types")
