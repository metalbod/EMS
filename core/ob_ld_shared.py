"""
Shared helpers between the Onboarding/Offboarding and Learning & Development
modules. An onboarding checklist item can auto-enroll an employee in an L&D
course (_auto_enroll_ld_course), and finishing that course can auto-complete
the linked checklist item (_complete_linked_ob_items) — each module needs to
call into the other's audit-log helper, so all four live together here
rather than duplicating logic or creating a circular import between
routers/onboarding.py and the not-yet-extracted L&D routes in main.py.
"""


def log_ob(conn, inst_id: int, cl_id: int, emp_id: str, ob_type: str,
           action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO ob_audit_log
           (institution_id,checklist_id,employee_id,ob_type,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?,?)""",
        (inst_id, cl_id, emp_id, ob_type, action, detail,
         user["username"], user["role"])
    )


def log_ld(conn, inst_id: int, enr_id: int, emp_id: str,
           action: str, detail: str, user: dict):
    conn.execute(
        """INSERT INTO ld_audit_log
           (institution_id,enrollment_id,employee_id,action,detail,performed_by,performer_role)
           VALUES (?,?,?,?,?,?,?)""",
        (inst_id, enr_id, emp_id, action, detail, user["username"], user["role"])
    )


def auto_enroll_ld_course(conn, inst_id: int, employee_id: str, course_id: int, user: dict):
    """Enroll an employee in a course as part of an onboarding checklist item. Skips the
    cost-approval gate since HR is explicitly triggering the checklist. Returns the enrollment id."""
    existing = conn.execute(
        "SELECT id FROM ld_enrollments WHERE employee_id=? AND course_id=? AND institution_id=? "
        "AND status NOT IN ('Rejected','Completed') ORDER BY created_at DESC LIMIT 1",
        (employee_id, course_id, inst_id)
    ).fetchone()
    if existing:
        return existing["id"]
    course = conn.execute("SELECT * FROM ld_courses WHERE id=? AND institution_id=?", (course_id, inst_id)).fetchone()
    if not course:
        return None
    conn.execute(
        "INSERT INTO ld_enrollments (institution_id,course_id,employee_id,status,requested_by,notes) VALUES (?,?,?,?,?,?)",
        (inst_id, course_id, employee_id, "In Progress", user["username"], "Auto-enrolled via onboarding checklist")
    )
    enr_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_ld(conn, inst_id, enr_id, employee_id, "Enrolled",
           f"Auto-enrolled in '{course['title']}' via onboarding checklist", user)
    return enr_id


def complete_linked_ob_items(conn, inst_id: int, employee_id: str, course_id: int, user: dict):
    """When an L&D enrollment for this employee+course completes, auto-mark any onboarding
    checklist items linked to that course as Done, and close out the checklist if that
    was the last pending item."""
    items = conn.execute(
        """SELECT i.*, c.type AS ob_type FROM ob_checklist_items i
           JOIN ob_checklists c ON c.id = i.checklist_id
           WHERE i.linked_ld_course_id=? AND i.institution_id=? AND i.status='Pending'
             AND c.employee_id=? AND c.status='In Progress'""",
        (course_id, inst_id, employee_id)
    ).fetchall()
    for item in items:
        conn.execute(
            "UPDATE ob_checklist_items SET status='Done',completed_by=?,"
            "completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'),notes=? WHERE id=?",
            (user["username"], "Auto-completed: linked course finished", item["id"])
        )
        cl_id = item["checklist_id"]
        log_ob(conn, inst_id, cl_id, employee_id, item["ob_type"],
               "Item Auto-Completed",
               f"'{item['title']}' auto-completed after finishing the linked course", user)
        total = conn.execute("SELECT COUNT(*) FROM ob_checklist_items WHERE checklist_id=?", (cl_id,)).fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM ob_checklist_items WHERE checklist_id=? AND status IN ('Done','N/A')", (cl_id,)).fetchone()[0]
        if total > 0 and done == total:
            conn.execute(
                "UPDATE ob_checklists SET status='Completed',completed_at=to_char(NOW() AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS') WHERE id=?",
                (cl_id,)
            )
            log_ob(conn, inst_id, cl_id, employee_id, item["ob_type"],
                   "Checklist Completed",
                   f"All {total} items completed — checklist auto-closed", user)
