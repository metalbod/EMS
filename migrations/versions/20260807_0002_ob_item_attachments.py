"""Add ob_item_attachments (optional proof-of-completion uploads)

Revision ID: 20260807_0002
Revises: 20260807_0001
Create Date: 2026-08-07

Onboarding/offboarding checklist items can now have file(s) attached as
proof of completion (e.g. a photo of laptop handover, a signed form) —
same shape as candidate_documents (20260729_0002): stored as
data:...;base64 URIs, one row per file, multiple files per item, upload
optional (not required to mark an item Done).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260807_0002'
down_revision = '20260807_0001'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'ob_item_attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('institution_id', sa.Integer(), sa.ForeignKey('institutions.id'), nullable=False),
        sa.Column('checklist_item_id', sa.Integer(), sa.ForeignKey('ob_checklist_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('data_url', sa.Text(), nullable=False),
        sa.Column('uploaded_by', sa.String(100), nullable=False),
        sa.Column('created_at', sa.String(19), nullable=False,
                  server_default=sa.text("to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")),
    )
    op.create_index('ix_ob_item_attachments_item_id', 'ob_item_attachments', ['checklist_item_id'])
    op.create_index('ix_ob_item_attachments_institution_id', 'ob_item_attachments', ['institution_id'])
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON ob_item_attachments
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE ob_item_attachments FORCE ROW LEVEL SECURITY")


def downgrade():
    op.execute("ALTER TABLE ob_item_attachments NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON ob_item_attachments")
    op.drop_index('ix_ob_item_attachments_institution_id', table_name='ob_item_attachments')
    op.drop_index('ix_ob_item_attachments_item_id', table_name='ob_item_attachments')
    op.drop_table('ob_item_attachments')
