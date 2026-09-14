"""Add token_epoch to users

Revision ID: 20260914_0001
Revises: 20260911_0001
Create Date: 2026-09-14

JWTs issued by this app are otherwise purely self-verifying — a token
captured before a password change (or an explicit "log out everywhere")
stays valid until its own 8-hour expiry regardless, since nothing on the
server tracks which tokens should still be honored. token_epoch is
embedded in every newly-minted JWT (core/deps.py's make_token) and
re-checked against the DB's current value on every request
(get_current_user, right alongside the existing is_active recheck) —
bumping it on the server instantly invalidates every token issued before
that point, without needing a token blacklist. Defaults to 0 so every
existing token (embedding no token_epoch claim, read as 0 by
get_current_user) keeps working unchanged until the next password
change.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260914_0001'
down_revision = '20260911_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('token_epoch', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('users', 'token_epoch')
