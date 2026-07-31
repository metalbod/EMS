"""An employee's primary location — the single source of truth for "where is
X currently based," stored as their active 'primary' row in
employee_location_assignments (there is no default_location_id column on
employees; that was dropped once this became the sole source — see the
migration that consolidated it).

Extracted out of routers/employees.py (where get_primary_location and
set_primary_location started as employees-only helpers) once
routers/locations.py needed the same "does X already have a primary
location" read for its own duplicate-assignment check — two real call
sites needing the same fact was the seam, not tidiness for its own sake.
Every read or write of "an employee's primary location" goes through this
module now, so the field can't drift into two different values the way
employees.default_location_id and this table once did (see that
migration's docstring for the bugs that caused).
"""


def get_primary_location(conn, inst_id, employee_id):
    """Returns {"location_id":.., "location_name":..} for employee_id's
    active primary location assignment, or None if they don't have one."""
    row = conn.execute(
        """SELECT ela.location_id, l.name AS location_name
           FROM employee_location_assignments ela
           JOIN locations l ON l.id = ela.location_id
           WHERE ela.institution_id=? AND ela.employee_id=?
             AND ela.assignment_type='primary' AND ela.is_active=1""",
        (inst_id, employee_id)
    ).fetchone()
    return {"location_id": row["location_id"], "location_name": row["location_name"]} if row else None


def get_primary_locations(conn, inst_id, employee_ids):
    """Bulk form of get_primary_location — one query for many employees
    instead of one per employee (see routers/employees.py's list_employees,
    which resolves this for every row in the Employee List)."""
    ids = [e for e in employee_ids if e]
    if not ids:
        return {}
    rows = conn.execute(
        f"""SELECT ela.employee_id, ela.location_id, l.name AS location_name
            FROM employee_location_assignments ela
            JOIN locations l ON l.id = ela.location_id
            WHERE ela.institution_id=? AND ela.assignment_type='primary' AND ela.is_active=1
              AND ela.employee_id IN ({','.join('?' * len(ids))})""",
        [inst_id, *ids]
    ).fetchall()
    return {r["employee_id"]: {"location_id": r["location_id"], "location_name": r["location_name"]} for r in rows}


def has_primary_location(conn, inst_id, employee_id) -> bool:
    """Existence-only check — used by routers/locations.py's
    assign_employee_to_location to reject a second primary assignment
    (that endpoint errors on duplicates rather than upserting; see
    set_primary_location below for the upsert path Edit Employee uses)."""
    return conn.execute(
        "SELECT 1 FROM employee_location_assignments WHERE institution_id=? AND employee_id=? AND assignment_type='primary' AND is_active=1",
        (inst_id, employee_id)
    ).fetchone() is not None


def set_primary_location(conn, inst_id, employee_id, location_id):
    """Set (upsert) or clear (location_id=None) an employee's primary
    location. Called by Add/Edit Employee (routers/employees.py) — the one
    write path for "this employee's location changed" outside of the
    dedicated assignment-management endpoints in routers/locations.py."""
    existing = conn.execute(
        "SELECT id, location_id FROM employee_location_assignments WHERE employee_id=? AND institution_id=? AND assignment_type='primary' AND is_active=1",
        (employee_id, inst_id),
    ).fetchone()
    if location_id is None:
        if existing:
            conn.execute(
                "UPDATE employee_location_assignments SET is_active=0, end_date=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD') WHERE id=?",
                (existing["id"],),
            )
        return
    if existing:
        if existing["location_id"] != location_id:
            conn.execute("UPDATE employee_location_assignments SET location_id=? WHERE id=?", (location_id, existing["id"]))
    else:
        conn.execute(
            "INSERT INTO employee_location_assignments (institution_id, employee_id, location_id, assignment_type, start_date) VALUES (?,?,?,'primary',to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD'))",
            (inst_id, employee_id, location_id),
        )
