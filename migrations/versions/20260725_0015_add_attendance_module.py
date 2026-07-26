"""Add Attendance module: shifts, shift assignments, attendance settings,
attendance records, and geofence columns on locations

Revision ID: 20260725_0015
Revises: 20260725_0014
Create Date: 2026-07-25

Design notes (see planning discussion):
  - shifts: institution-scoped shift templates. start_time/end_time are
    TIME (no date). crosses_midnight is stored (not just derived) so
    queries don't need to compare start_time > end_time everywhere.
    grace_period_minutes lives here, not on attendance_settings, since
    lateness is a property of the shift being worked.
  - employee_shift_assignments: effective-dated so shift changes don't
    lose history (same effective_from/effective_to pattern used
    elsewhere in this codebase for time-bounded assignments).
  - attendance_settings: "empty target = doesn't apply" convention,
    same as benefit_plan_eligibility (see 20260725_0011). A row with
    department and employee_id both NULL would match everyone, but the
    intended usage is per-department or per-employee opt-in rows only
    (no rule = not required, per product decision). default_shift_id
    is used when a required employee has no row in
    employee_shift_assignments.
  - attendance_records: one row per employee per work_date, where
    work_date is anchored to the day a shift STARTS (see clock-in
    resolution logic in routers/attendance.py) so an overnight shift
    produces exactly one record instead of two fragments split across
    the calendar boundary. Geofence is advisory only (outside_geofence
    flag) per product decision — never blocks a clock-in.
  - locations gains latitude/longitude/radius_meters — nullable, so
    geofencing is opt-in per location (no radius = no geofence check
    for anyone based at that location).

RLS policies for every new table are included in THIS migration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260725_0015'
down_revision = '20260725_0014'
branch_labels = None
depends_on = None

_POLICY_NAME = "tenant_isolation"


def _add_rls(table: str):
    op.execute(f"""
        CREATE POLICY {_POLICY_NAME} ON {table}
        USING (
            current_setting('app.bypass_rls', true) = 'true'
            OR institution_id = NULLIF(current_setting('app.current_institution_id', true), '')::int
        )
    """)
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_rls(table: str):
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")


def upgrade():
    # --- locations: geofence columns -----------------------------------
    op.add_column('locations', sa.Column('latitude', sa.Numeric(10, 7), nullable=True))
    op.add_column('locations', sa.Column('longitude', sa.Numeric(10, 7), nullable=True))
    op.add_column('locations', sa.Column('radius_meters', sa.Integer(), nullable=True))

    # --- shifts ----------------------------------------------------------
    op.create_table(
        'shifts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('crosses_midnight', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('grace_period_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.Index('ix_shifts_institution', 'institution_id', 'is_active'),
    )
    op.execute("DROP TRIGGER IF EXISTS trg_shifts_upd ON shifts")
    op.execute("""
        CREATE TRIGGER trg_shifts_upd BEFORE UPDATE ON shifts
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    _add_rls('shifts')

    # --- employee_shift_assignments --------------------------------------
    op.create_table(
        'employee_shift_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('shift_id', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.String(10), nullable=False),
        sa.Column('effective_to', sa.String(10), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.Index('ix_esa_employee', 'employee_id', 'is_active'),
        sa.Index('ix_esa_shift', 'shift_id'),
    )
    op.execute("DROP TRIGGER IF EXISTS trg_esa_upd ON employee_shift_assignments")
    op.execute("""
        CREATE TRIGGER trg_esa_upd BEFORE UPDATE ON employee_shift_assignments
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    _add_rls('employee_shift_assignments')

    # --- attendance_settings ---------------------------------------------
    op.create_table(
        'attendance_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('employee_id', sa.String(50), nullable=True),
        sa.Column('required', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('default_shift_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['default_shift_id'], ['shifts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.CheckConstraint('department IS NOT NULL OR employee_id IS NOT NULL', name='ck_attendance_settings_target'),
        sa.Index('ix_attendance_settings_institution', 'institution_id', 'is_active'),
    )
    op.execute("DROP TRIGGER IF EXISTS trg_attendance_settings_upd ON attendance_settings")
    op.execute("""
        CREATE TRIGGER trg_attendance_settings_upd BEFORE UPDATE ON attendance_settings
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    _add_rls('attendance_settings')

    # --- attendance_records -----------------------------------------------
    op.create_table(
        'attendance_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.String(50), nullable=False),
        sa.Column('work_date', sa.String(10), nullable=False),
        sa.Column('shift_id', sa.Integer(), nullable=True),
        sa.Column('clock_in_at', sa.String(50), nullable=True),
        sa.Column('clock_out_at', sa.String(50), nullable=True),
        sa.Column('clock_in_lat', sa.Numeric(10, 7), nullable=True),
        sa.Column('clock_in_lng', sa.Numeric(10, 7), nullable=True),
        sa.Column('clock_in_ip', sa.String(64), nullable=True),
        sa.Column('clock_in_distance_meters', sa.Integer(), nullable=True),
        sa.Column('outside_geofence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('clock_out_lat', sa.Numeric(10, 7), nullable=True),
        sa.Column('clock_out_lng', sa.Numeric(10, 7), nullable=True),
        sa.Column('clock_out_ip', sa.String(64), nullable=True),
        sa.Column('worked_minutes', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='Present'),
        # Present, Late, Absent (Pending Review), Excused, Reclassified as Leave, Confirmed Absent
        sa.Column('suggested_action', sa.String(30), nullable=True),
        # Full-Day Absence, Half-Day Leave -- HR-facing hint only, set when status becomes Late/Absent
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.String(50), nullable=True),
        sa.Column('leave_application_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('updated_at', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['institution_id', 'employee_id'], ['employees.institution_id', 'employees.employee_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['leave_application_id'], ['leave_applications.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('employee_id', 'work_date', name='uq_attendance_records_employee_workdate'),
        sa.Index('ix_attendance_records_employee', 'employee_id', 'work_date'),
        sa.Index('ix_attendance_records_status', 'institution_id', 'status'),
    )
    op.execute("DROP TRIGGER IF EXISTS trg_attendance_records_upd ON attendance_records")
    op.execute("""
        CREATE TRIGGER trg_attendance_records_upd BEFORE UPDATE ON attendance_records
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    _add_rls('attendance_records')


def downgrade():
    _drop_rls('attendance_records')
    op.drop_table('attendance_records')

    _drop_rls('attendance_settings')
    op.drop_table('attendance_settings')

    _drop_rls('employee_shift_assignments')
    op.drop_table('employee_shift_assignments')

    _drop_rls('shifts')
    op.drop_table('shifts')

    op.drop_column('locations', 'radius_meters')
    op.drop_column('locations', 'longitude')
    op.drop_column('locations', 'latitude')
