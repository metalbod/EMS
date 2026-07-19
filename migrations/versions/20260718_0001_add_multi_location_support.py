"""20260718_0001: Add multi-location support

Revision ID: 20260718_0001
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18 00:00:00.000000

Adds support for multi-location/multi-outlet businesses by introducing:
1. locations table (outlets/branches per institution)
2. employee_location_assignments table (many-to-many relationship)
3. Optional location columns on users and payroll_runs tables
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260718_0001'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create locations table
    op.execute("""
        CREATE TABLE locations (
            id                  SERIAL  PRIMARY KEY,
            institution_id      INTEGER NOT NULL REFERENCES institutions(id),
            name                TEXT    NOT NULL,
            code                TEXT    NOT NULL,
            address             TEXT,
            city                TEXT,
            state               TEXT,
            postal_code         TEXT,
            country             TEXT    DEFAULT 'Malaysia',
            phone               TEXT,
            manager_user_id     INTEGER REFERENCES users(id),
            location_type       TEXT    NOT NULL DEFAULT 'branch',
            is_active           INTEGER NOT NULL DEFAULT 1,
            capacity            INTEGER,
            created_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at          TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, code)
        )
    """)

    # Create indexes on locations table
    op.execute("CREATE INDEX idx_locations_institution ON locations(institution_id, is_active)")
    op.execute("CREATE INDEX idx_locations_active ON locations(is_active)")

    # Create set_updated_at trigger for locations
    op.execute("DROP TRIGGER IF EXISTS trg_locations_upd ON locations")
    op.execute("""
        CREATE TRIGGER trg_locations_upd BEFORE UPDATE ON locations
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # Create employee_location_assignments table
    op.execute("""
        CREATE TABLE employee_location_assignments (
            id                      SERIAL  PRIMARY KEY,
            institution_id          INTEGER NOT NULL,
            employee_id             TEXT    NOT NULL,
            location_id             INTEGER NOT NULL REFERENCES locations(id),
            assignment_type         TEXT    NOT NULL DEFAULT 'primary',
            start_date              TEXT    NOT NULL,
            end_date                TEXT,
            reports_to_id           TEXT,
            department_at_location  TEXT,
            is_active               INTEGER NOT NULL DEFAULT 1,
            created_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at              TEXT    NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            FOREIGN KEY (institution_id, employee_id) REFERENCES employees(institution_id, employee_id),
            UNIQUE(employee_id, location_id, assignment_type)
        )
    """)

    # Create indexes on employee_location_assignments table
    op.execute("CREATE INDEX idx_assignments_employee ON employee_location_assignments(employee_id, is_active)")
    op.execute("CREATE INDEX idx_assignments_location ON employee_location_assignments(location_id, is_active)")
    op.execute("CREATE INDEX idx_assignments_active ON employee_location_assignments(is_active, end_date)")

    # Create set_updated_at trigger for assignments
    op.execute("DROP TRIGGER IF EXISTS trg_assignments_upd ON employee_location_assignments")
    op.execute("""
        CREATE TRIGGER trg_assignments_upd BEFORE UPDATE ON employee_location_assignments
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # Add optional location columns to existing tables
    op.execute("ALTER TABLE employees ADD COLUMN default_location_id INTEGER REFERENCES locations(id)")
    op.execute("ALTER TABLE users ADD COLUMN default_location_id INTEGER REFERENCES locations(id)")
    op.execute("ALTER TABLE payroll_runs ADD COLUMN location_id INTEGER REFERENCES locations(id)")


def downgrade() -> None:
    # Drop columns from existing tables
    op.execute("ALTER TABLE payroll_runs DROP COLUMN location_id")
    op.execute("ALTER TABLE users DROP COLUMN default_location_id")
    op.execute("ALTER TABLE employees DROP COLUMN default_location_id")

    # Drop employee_location_assignments table
    op.execute("DROP TRIGGER IF EXISTS trg_assignments_upd ON employee_location_assignments")
    op.execute("DROP TABLE IF EXISTS employee_location_assignments")

    # Drop locations table
    op.execute("DROP TRIGGER IF EXISTS trg_locations_upd ON locations")
    op.execute("DROP TABLE IF EXISTS locations")
