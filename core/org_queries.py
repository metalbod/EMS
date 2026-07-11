"""Shared SQL-fragment helpers for querying the reporting-chain hierarchy."""


def is_self_or_subordinate(conn, inst_id, manager_employee_id, target_employee_id):
    """True if target is the manager themselves or anywhere in their downstream reporting chain."""
    row = conn.execute("""
        WITH RECURSIVE subordinates AS (
            SELECT employee_id FROM employees WHERE institution_id=? AND employee_id=?
            UNION ALL
            SELECT e.employee_id FROM employees e
            JOIN subordinates s ON e.reports_to = s.employee_id
            WHERE e.institution_id=?
        )
        SELECT 1 FROM subordinates WHERE employee_id=?
    """, (inst_id, manager_employee_id, inst_id, target_employee_id)).fetchone()
    return row is not None


def subordinates_in_clause(inst_id, manager_employee_id):
    """SQL fragment + params for 'employee_id IN (manager + their full downstream reporting chain)'.
    Usage: frag, fp = subordinates_in_clause(inst_id, mgr_id); q += f" AND e.employee_id IN {frag}"; p.extend(fp)"""
    frag = """(
        WITH RECURSIVE subordinates AS (
            SELECT employee_id FROM employees WHERE institution_id=? AND employee_id=?
            UNION ALL
            SELECT e2.employee_id FROM employees e2
            JOIN subordinates s ON e2.reports_to = s.employee_id
            WHERE e2.institution_id=?
        )
        SELECT employee_id FROM subordinates
    )"""
    return frag, [inst_id, manager_employee_id, inst_id]
