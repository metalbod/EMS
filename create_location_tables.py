#!/usr/bin/env python3
"""Create multi-location tables directly."""
import psycopg2
import os

ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Use admin URL if available (has permissions to create tables)
connection_url = ADMIN_DATABASE_URL if ADMIN_DATABASE_URL else DATABASE_URL

if not connection_url:
    raise RuntimeError("DATABASE_URL or ADMIN_DATABASE_URL not set")

print(f"Connecting to database...")

conn = psycopg2.connect(connection_url, sslmode='require')
cur = conn.cursor()

try:
    print("Creating locations table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL REFERENCES institutions(id),
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            address TEXT,
            city TEXT,
            state TEXT,
            postal_code TEXT,
            country TEXT DEFAULT 'Malaysia',
            phone TEXT,
            manager_user_id INTEGER REFERENCES users(id),
            location_type TEXT NOT NULL DEFAULT 'branch',
            is_active INTEGER NOT NULL DEFAULT 1,
            capacity INTEGER,
            created_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(institution_id, code)
        )
    """)
    print("✓ Locations table created")

    print("Creating employee_location_assignments table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employee_location_assignments (
            id SERIAL PRIMARY KEY,
            institution_id INTEGER NOT NULL,
            employee_id TEXT NOT NULL,
            location_id INTEGER NOT NULL REFERENCES locations(id),
            assignment_type TEXT NOT NULL DEFAULT 'primary',
            start_date TEXT NOT NULL,
            end_date TEXT,
            reports_to_id TEXT,
            department_at_location TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            updated_at TEXT NOT NULL DEFAULT (to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')),
            FOREIGN KEY (institution_id, employee_id) REFERENCES employees(institution_id, employee_id),
            UNIQUE(employee_id, location_id, assignment_type)
        )
    """)
    print("✓ Employee location assignments table created")

    print("Creating indexes...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_locations_institution ON locations(institution_id, is_active)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_locations_active ON locations(is_active)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assignments_employee ON employee_location_assignments(employee_id, is_active)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assignments_location ON employee_location_assignments(location_id, is_active)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_assignments_active ON employee_location_assignments(is_active, end_date)")
    print("✓ Indexes created")

    print("Creating triggers...")
    cur.execute("DROP TRIGGER IF EXISTS trg_locations_upd ON locations")
    cur.execute("""
        CREATE TRIGGER trg_locations_upd BEFORE UPDATE ON locations
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    cur.execute("DROP TRIGGER IF EXISTS trg_assignments_upd ON employee_location_assignments")
    cur.execute("""
        CREATE TRIGGER trg_assignments_upd BEFORE UPDATE ON employee_location_assignments
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)
    print("✓ Triggers created")

    print("Adding columns to existing tables...")
    cur.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS default_location_id INTEGER REFERENCES locations(id)")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS default_location_id INTEGER REFERENCES locations(id)")
    cur.execute("ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS location_id INTEGER REFERENCES locations(id)")
    print("✓ Columns added")

    conn.commit()
    print("\n✅ All tables and indexes created successfully!")

except Exception as e:
    conn.rollback()
    print(f"❌ Error: {e}")
    raise

finally:
    cur.close()
    conn.close()
