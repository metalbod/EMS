"""Add per-institution SMTP settings and an email send log

Revision ID: 20260919_0001
Revises: 20260918_0002
Create Date: 2026-09-19

Phase 1 of the email notification engine: each institution configures
its own SMTP mailbox (BYO-SMTP, same encrypted-credential pattern as the
AI assistant's Anthropic BYOK key — see core/secrets_encryption.py) to
send approval/application emails from. Only username/password are
encrypted; host/port/from-address/use_tls are plain columns so the
Settings UI can show a non-secret preview without decrypting anything
(mirrors institutions.anthropic_api_key_last4's role for the Anthropic
key).

notifications_email_enabled is the institution-level on/off toggle
(defaults false — a newly-configured institution doesn't start emailing
anyone until HR explicitly turns it on).

email_log records every attempted send (sent/failed/skipped) for
debugging — core/email_engine.py's send_email() never raises, so this is
the only place a silently-swallowed failure becomes visible.

Deliberately no changes to any of the 7 request tables — notification
triggers hook into the shared core/approval_workflow.py engine only.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260919_0001'
down_revision = '20260918_0002'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_host TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_port INTEGER")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_use_tls BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_from_address TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_from_name TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_credentials_encrypted TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS smtp_configured_at TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS notifications_email_enabled BOOLEAN NOT NULL DEFAULT false")

    op.create_table(
        'email_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('module', sa.String(30), nullable=True),
        sa.Column('category', sa.String(40), nullable=False),  # e.g. 'approval_submitted' | 'approval_decided' | 'test'
        sa.Column('recipient_email', sa.String(255), nullable=False),
        sa.Column('subject', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),  # 'sent' | 'failed' | 'skipped'
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_email_log_institution_id', 'email_log', ['institution_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON email_log
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE email_log FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE email_log NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON email_log")
    op.drop_table('email_log')

    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS notifications_email_enabled")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_configured_at")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_credentials_encrypted")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_from_name")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_from_address")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_use_tls")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_port")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS smtp_host")
