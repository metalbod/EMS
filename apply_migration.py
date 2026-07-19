#!/usr/bin/env python3
"""Apply multi-location migration manually."""
import os
from db import _get_admin_pool

DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL", DATABASE_URL)

if not ADMIN_DATABASE_URL:
    raise RuntimeError("ADMIN_DATABASE_URL not set")

# Migration SQL from 20260718_0001_add_multi_location_support.py
MIGRATION_SQL = """
-- Create locations table
CREATE TABLE IF NOT EXISTS locations (
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
);

-- Create indexes on locations table
CREATE INDEX IF NOT EXISTS idx_locations_institution ON locations(institution_id, is_active);
CREATE INDEX IF NOT EXISTS idx_locations_active ON locations(is_active);

-- Create set_updated_at trigger for locations
DROP TRIGGER IF EXISTS trg_locations_upd ON locations;
CREATE TRIGGER trg_locations_upd BEFORE UPDATE ON locations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Create employee_location_assignments table
CREATE TABLE IF NOT EXISTS employee_location_assignments (
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
);

-- Create indexes on employee_location_assignments table
CREATE INDEX IF NOT EXISTS idx_assignments_employee ON employee_location_assignments(employee_id, is_active);
CREATE INDEX IF NOT EXISTS idx_assignments_location ON employee_location_assignments(location_id, is_active);
CREATE INDEX IF NOT EXISTS idx_assignments_active ON employee_location_assignments(is_active, end_date);

-- Create set_updated_at trigger for assignments
DROP TRIGGER IF EXISTS trg_assignments_upd ON employee_location_assignments;
CREATE TRIGGER trg_assignments_upd BEFORE UPDATE ON employee_location_assignments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Add optional location columns to existing tables
ALTER TABLE employees ADD COLUMN IF NOT EXISTS default_location_id INTEGER REFERENCES locations(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_location_id INTEGER REFERENCES locations(id);
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS location_id INTEGER REFERENCES locations(id);
"""

def apply_migration():
    """Apply the migration SQL."""
    pool = _get_admin_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        # Execute the migration SQL
        cur.execute(MIGRATION_SQL)
        conn.commit()
        print("✅ Migration applied successfully!")
        print("- Created locations table")
        print("- Created employee_location_assignments table")
        print("- Created indexes and triggers")
        print("- Added columns to existing tables")
    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        cur.close()
        pool.putconn(conn)

if __name__ == "__main__":
    apply_migration()
