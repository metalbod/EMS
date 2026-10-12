"""Policies: link documents and password-confirmed acknowledgement

Revision ID: 20261015_0001
Revises: 20261014_0001
Create Date: 2026-10-15

A policy version can now point at a link instead of (or as well as) an uploaded file: file_id becomes
nullable, link_url is added, and at least one of the two is required. When both are given the file is
the PDF copy kept as evidence of what the link showed. policy_acknowledgements.method records how a
person confirmed — 'password' from now on; NULL means an earlier tick-box acknowledgement.
"""
from alembic import op

revision = '20261015_0001'
down_revision = '20261014_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE policy_versions ALTER COLUMN file_id DROP NOT NULL")
    op.execute("ALTER TABLE policy_versions ADD COLUMN IF NOT EXISTS link_url TEXT")
    op.execute("ALTER TABLE policy_versions ADD CONSTRAINT ck_policy_versions_file_or_link "
               "CHECK (file_id IS NOT NULL OR link_url IS NOT NULL)")
    op.execute("ALTER TABLE policy_acknowledgements ADD COLUMN IF NOT EXISTS method TEXT")


def downgrade():
    op.execute("ALTER TABLE policy_acknowledgements DROP COLUMN IF EXISTS method")
    op.execute("ALTER TABLE policy_versions DROP CONSTRAINT IF EXISTS ck_policy_versions_file_or_link")
    op.execute("ALTER TABLE policy_versions DROP COLUMN IF EXISTS link_url")
