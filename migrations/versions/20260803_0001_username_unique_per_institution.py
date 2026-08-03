"""Make username unique per institution instead of system-wide

Revision ID: 20260803_0001
Revises: 20260802_0001
Create Date: 2026-08-03

Login already resolves the institution (via company code) before
looking up the user by username — see routers/auth.py's login() — so a
global UNIQUE(username) constraint was stricter than the product
actually needs: two unrelated institutions couldn't both have an
employee named "amanda" logging in with that username, even though
each login attempt is already scoped to one institution.

Replaces UNIQUE(username) with UNIQUE(institution_id, username) for
institution-scoped users, plus a separate partial unique index on
username WHERE institution_id IS NULL to keep platform-level
(superadmin) usernames globally unique — a plain composite constraint
wouldn't do that on its own, since SQL UNIQUE constraints treat NULL
institution_id values as all distinct from each other.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260803_0001'
down_revision = '20260802_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('users_username_key', 'users', type_='unique')
    op.create_unique_constraint('users_institution_id_username_key', 'users', ['institution_id', 'username'])
    op.execute("""
        CREATE UNIQUE INDEX users_username_platform_key ON users (username)
        WHERE institution_id IS NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS users_username_platform_key")
    op.drop_constraint('users_institution_id_username_key', 'users', type_='unique')
    op.create_unique_constraint('users_username_key', 'users', ['username'])
