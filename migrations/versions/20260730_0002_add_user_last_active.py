"""Add last_login/last_active to users

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30

Superadmin has no way to see how many users currently hold a valid
session before performing maintenance — auth is stateless JWT with no
session table, so "logged in now" has to be approximated from activity
timestamps instead. last_login is set on successful login; last_active
is refreshed (throttled) on every authenticated request in
core/deps.py's get_current_user, so "active in the last N minutes" is a
reasonable proxy for "currently using the system."
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260730_0002'
down_revision = '20260730_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('last_login', sa.String(19), nullable=True))
    op.add_column('users', sa.Column('last_active', sa.String(19), nullable=True))


def downgrade():
    op.drop_column('users', 'last_active')
    op.drop_column('users', 'last_login')
