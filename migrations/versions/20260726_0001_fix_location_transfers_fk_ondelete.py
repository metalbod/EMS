"""Fix location_transfers user FKs to ON DELETE SET NULL

Revision ID: 20260726_0001
Revises: 20260725_0018
Create Date: 2026-07-26

requested_by_user_id and approved_by_user_id on location_transfers were
created (20260719_0002) with no ON DELETE clause, defaulting to RESTRICT —
both columns are nullable, so SET NULL is the correct behavior: a transfer
request/approval record should survive the referenced user being deleted,
just losing the "who did this" attribution, same as every other nullable
user-reference FK added since (e.g. attendance_devices.location_id,
attendance_records.clock_in_device_id). Confirmed by CI: deleting a
disposable test user who had requested a location transfer failed with
psycopg2.errors.ForeignKeyViolation on location_transfers_requested_by_user_id_fkey.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260726_0001'
down_revision = '20260725_0018'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('location_transfers_requested_by_user_id_fkey', 'location_transfers', type_='foreignkey')
    op.create_foreign_key(
        'location_transfers_requested_by_user_id_fkey', 'location_transfers',
        'users', ['requested_by_user_id'], ['id'], ondelete='SET NULL',
    )
    op.drop_constraint('location_transfers_approved_by_user_id_fkey', 'location_transfers', type_='foreignkey')
    op.create_foreign_key(
        'location_transfers_approved_by_user_id_fkey', 'location_transfers',
        'users', ['approved_by_user_id'], ['id'], ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('location_transfers_approved_by_user_id_fkey', 'location_transfers', type_='foreignkey')
    op.create_foreign_key(
        'location_transfers_approved_by_user_id_fkey', 'location_transfers',
        'users', ['approved_by_user_id'], ['id'],
    )
    op.drop_constraint('location_transfers_requested_by_user_id_fkey', 'location_transfers', type_='foreignkey')
    op.create_foreign_key(
        'location_transfers_requested_by_user_id_fkey', 'location_transfers',
        'users', ['requested_by_user_id'], ['id'],
    )
