"""Add attendance_devices (API-key auth for external clock-in/out
integrations, e.g. facial-recognition office cameras)

Revision ID: 20260725_0018
Revises: 20260725_0017
Create Date: 2026-07-25

A device's API key is generated once as `adk_<prefix>_<secret>` and shown
to HR exactly once at creation time — only `key_prefix` (indexed, looked
up in plaintext to find the candidate row) and `key_hash` (bcrypt hash of
the full key, verified with the same primitive as user passwords —
core/deps.py's hash_password/verify_password) are ever persisted. This
mirrors how GitHub/Stripe-style tokens are looked up without needing an
index over a hash.

attendance_records gains clock_in_source/clock_out_source ('web' or
'device') and clock_in_device_id/clock_out_device_id, so a device-reported
punch is distinguishable from a browser self-service one in the HR review
and history views.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0018'
down_revision = '20260725_0017'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def upgrade():
    op.create_table(
        'attendance_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column('key_hash', sa.String(200), nullable=False),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_used_at', sa.String(50), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('key_prefix', name='uq_attendance_devices_key_prefix'),
        sa.Index('ix_attendance_devices_institution', 'institution_id', 'is_active'),
    )
    op.execute("DROP TRIGGER IF EXISTS trg_attendance_devices_upd ON attendance_devices")
    op.execute("""
        CREATE TRIGGER trg_attendance_devices_upd BEFORE UPDATE ON attendance_devices
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON attendance_devices
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute("ALTER TABLE attendance_devices FORCE ROW LEVEL SECURITY")

    op.add_column('attendance_records', sa.Column('clock_in_source', sa.String(20), nullable=False, server_default='web'))
    op.add_column('attendance_records', sa.Column('clock_out_source', sa.String(20), nullable=True))
    op.add_column('attendance_records', sa.Column('clock_in_device_id', sa.Integer(), nullable=True))
    op.add_column('attendance_records', sa.Column('clock_out_device_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_attendance_records_clock_in_device', 'attendance_records', 'attendance_devices', ['clock_in_device_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_attendance_records_clock_out_device', 'attendance_records', 'attendance_devices', ['clock_out_device_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_attendance_records_clock_out_device', 'attendance_records', type_='foreignkey')
    op.drop_constraint('fk_attendance_records_clock_in_device', 'attendance_records', type_='foreignkey')
    op.drop_column('attendance_records', 'clock_out_device_id')
    op.drop_column('attendance_records', 'clock_in_device_id')
    op.drop_column('attendance_records', 'clock_out_source')
    op.drop_column('attendance_records', 'clock_in_source')

    op.execute("ALTER TABLE attendance_devices NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON attendance_devices")
    op.drop_table('attendance_devices')
