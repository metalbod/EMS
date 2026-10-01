"""Add job_requisitions.public_token for public job applications

Revision ID: 20261001_0002
Revises: 20261001_0001
Create Date: 2026-10-01

A requisition's public application link is entirely this one random,
unguessable value — not its sequential `id` (a plain SERIAL shared across
every institution; exposing it in a public URL would let someone enumerate
other companies' postings by changing a number) and not the institution's
own `code` plus the requisition id. HR generates it via
`POST /api/recruitment/requisitions/{req_id}/public-link` (only for an
Approved requisition) and can revoke it via the matching DELETE — see
routers/recruitment.py. routers/public_careers.py is the only place this
column is ever read by an unauthenticated caller.

NULL = public applications disabled for this requisition (the default,
and also what "revoke" resets it to — never reused for a different
requisition once issued, so an old shared link always either still means
exactly this job or means nothing).
"""
from alembic import op
import sqlalchemy as sa

revision = '20261001_0002'
down_revision = '20261001_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('job_requisitions', sa.Column('public_token', sa.Text(), nullable=True))
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_job_requisitions_public_token
        ON job_requisitions(public_token) WHERE public_token IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_job_requisitions_public_token")
    op.drop_column('job_requisitions', 'public_token')
