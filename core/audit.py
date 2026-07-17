"""Shared audit-log writer for the general `audit_logs` table (employee-record changes).

Used by both the not-yet-extracted Employee routes in main.py and
routers/performance.py (merit increments write an audit entry too), so it
lives here rather than in either module to avoid a circular import.
"""
import json


def write_audit(conn, actor, inst_id, emp_id, emp_name, action, changes, ip=None):
    conn.execute("""
        INSERT INTO audit_logs
            (institution_id, actor_id, actor_username, actor_role,
             target_employee_id, target_employee_name, action, changes, ip_address)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (inst_id, actor.get("id"), actor.get("username"), actor.get("role"),
          emp_id, emp_name, action, json.dumps(changes) if changes else None, ip))
