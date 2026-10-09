"""Integration tests for the Settings > Roles > Permission Matrix override
system (core/permission_matrix.py's has_permission, routers/roles.py's
PUT/DELETE .../permission-matrix/override) — started as a pilot retrofit of
routers/employees.py's 6 flat-gated actions, since joined by Recruitment's
"View requisitions / candidates / interviews / offers" action (see the
dedicated tests below). See permission_matrix.py's module docstring for why
this is an incremental rollout rather than every router at once.
"""
import os

from conftest import _valid_employee_payload


def test_override_actually_changes_behavior_not_just_the_matrix(client, hr_manager_auth, make_test_user, test_institution):
    """The core claim of this feature: overriding manager's access to
    "Create employee" from Denied to Allowed must really let a manager
    create an employee, not just change what the matrix displays."""
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/employees", headers=mgr_headers, json=_valid_employee_payload())
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "employees.create_employee", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text

    try:
        after = client.post("/api/employees", headers=mgr_headers, json=_valid_employee_payload())
        assert after.status_code == 201, after.text
        client.patch(f"/api/employees/{after.json()['employee_id']}/status",
                     headers=hr_manager_auth, json={"status": "Inactive"})
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "employees.create_employee", "role": "manager"})

    after_reset = client.post("/api/employees", headers=mgr_headers, json=_valid_employee_payload())
    assert after_reset.status_code == 403, after_reset.text


def test_matrix_reflects_override_default_and_editable_flag(client, hr_manager_auth):
    action_key = "employees.create_employee"
    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": action_key, "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        matrix = client.get("/api/roles/permission-matrix", headers=hr_manager_auth)
        assert matrix.status_code == 200, matrix.text
        mod = next(m for m in matrix.json()["modules"] if m["module"] == "Employees")
        action = next(a for a in mod["actions"] if a["key"] == action_key)
        assert action["access"]["manager"] == "allow"
        assert action["access_default"]["manager"] == "deny"
        assert action["editable"]["manager"] is True
        assert action["enforced"] is True
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": action_key, "role": "manager"})


def test_locked_roles_cannot_be_overridden(client, hr_manager_auth):
    for role in ("hr_manager", "hr_admin", "payroll_manager", "compensation_manager"):
        res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
            "action_key": "employees.create_employee", "role": role, "access_value": "allow",
        })
        assert res.status_code == 400, f"{role} should be locked: {res.text}"


def test_non_enforced_action_cannot_be_overridden(client, hr_manager_auth):
    """"List employees" is relationship-scoped (manager=subordinate,
    employee=own) — not a flat allow/deny row, so it's never enforced."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "employees.list_employees", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


def test_override_requires_role_manage_permission(client, make_test_user, test_institution):
    token, _ = make_test_user(role="manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.put("/api/roles/permission-matrix/override", headers=headers, json={
        "action_key": "employees.create_employee", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 403, res.text


# ---------------------------------------------------------------------------
# Second pilot module: Leave (routers/leave.py, routers/holidays.py) —
# leave.manage_leave_types, leave.adjust_leave_balance,
# leave.view_leave_audit_history, leave.manage_public_holidays.
# (leave.leave_utilization_dashboard is deliberately NOT enforced — see
# permission_matrix.py's ENFORCED_ACTION_KEYS comment on that key.)
# ---------------------------------------------------------------------------
def test_leave_override_lets_employee_manage_leave_types(client, hr_manager_auth, make_test_user, test_institution):
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/leave/types", headers=emp_headers, json={"name": "ZZ Perm Test LT", "annual_entitlement": 10})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "leave.manage_leave_types", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text

    try:
        after = client.post("/api/leave/types", headers=emp_headers, json={"name": "ZZ Perm Test LT 2", "annual_entitlement": 10})
        assert after.status_code == 201, after.text
        client.delete(f"/api/leave/types/{after.json()['id']}", headers=hr_manager_auth)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "leave.manage_leave_types", "role": "employee"})

    after_reset = client.post("/api/leave/types", headers=emp_headers, json={"name": "ZZ Perm Test LT 3", "annual_entitlement": 10})
    assert after_reset.status_code == 403, after_reset.text


def test_leave_override_lets_manager_manage_public_holidays(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/holidays", headers=mgr_headers, json={"name": "ZZ Perm Holiday", "date": "2027-03-03", "year": 2027})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "leave.manage_public_holidays", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/holidays", headers=mgr_headers, json={"name": "ZZ Perm Holiday 2", "date": "2027-03-04", "year": 2027})
        assert after.status_code == 201, after.text
        client.delete(f"/api/holidays/{after.json()['id']}", headers=mgr_headers)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "leave.manage_public_holidays", "role": "manager"})


def test_leave_approval_action_stays_non_enforced(client, hr_manager_auth):
    """The approve/reject action has a flat-looking access dict but its
    real gate is the approval-workflow engine — must never be added to
    ENFORCED_ACTION_KEYS no matter how it looks structurally (see
    permission_matrix.py's comment on this exact key)."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "leave.approve_reject_leave_application", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


def test_leave_utilization_dashboard_stays_non_enforced(client, hr_manager_auth):
    """This one's default access dict is a plain flat allow/deny, unlike
    the approval-workflow rows above — but excluding superadmin from it is
    a deliberate, separately-tested app behavior (see
    test_leave.py::test_leave_utilization_dashboard_superadmin_denied),
    which require_permission()'s standard superadmin-always-passes rule
    would silently break. Confirms it's kept out of ENFORCED_ACTION_KEYS."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "leave.leave_utilization_dashboard", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Third pilot module: Onboarding / Offboarding (routers/onboarding.py) —
# manage_template_sets_templates, start_delete_checklist,
# add_edit_delete_checklist_item_hr, view_onboarding_offboarding_history.
# (view_checklist, complete_update_checklist_item, and
# attach_view_delete_item_proof_file stay non-enforced — assigned_role
# matched per item, not a flat role list.)
# ---------------------------------------------------------------------------
def test_onboarding_override_lets_employee_manage_template_sets(client, hr_manager_auth, make_test_user, test_institution):
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/ob/template-sets", headers=emp_headers, json={"type": "onboarding", "name": "ZZ Perm Set"})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "onboarding_offboarding.manage_template_sets_templates", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/ob/template-sets", headers=emp_headers, json={"type": "onboarding", "name": "ZZ Perm Set 2"})
        assert after.status_code == 201, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "onboarding_offboarding.manage_template_sets_templates", "role": "employee"})

    after_reset = client.post("/api/ob/template-sets", headers=emp_headers, json={"type": "onboarding", "name": "ZZ Perm Set 3"})
    assert after_reset.status_code == 403, after_reset.text


def test_onboarding_override_lets_manager_start_checklist(client, hr_manager_auth, make_test_user, make_test_employee, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}
    emp = make_test_employee()

    before = client.post("/api/ob/checklists", headers=mgr_headers, json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "onboarding_offboarding.start_delete_checklist", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/ob/checklists", headers=mgr_headers, json={"employee_id": emp["employee_id"], "type": "onboarding"})
        assert after.status_code == 201, after.text
        client.delete(f"/api/ob/checklists/{after.json()['id']}", headers=mgr_headers)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "onboarding_offboarding.start_delete_checklist", "role": "manager"})


def test_onboarding_item_edit_actions_stay_non_enforced_by_default_but_can_be_enforced(client, hr_manager_auth, make_test_user, make_test_employee, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}
    emp = make_test_employee()
    started = client.post("/api/ob/checklists", headers=hr_manager_auth,
                           json={"employee_id": emp["employee_id"], "type": "onboarding"})
    assert started.status_code == 201, started.text
    checklist = started.json()

    try:
        before = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=mgr_headers,
                              json={"title": "ZZ Perm Item", "assigned_role": "employee"})
        assert before.status_code == 403, before.text

        override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
            "action_key": "onboarding_offboarding.add_edit_delete_checklist_item_hr", "role": "manager", "access_value": "allow",
        })
        assert override.status_code == 200, override.text
        try:
            after = client.post(f"/api/ob/checklists/{checklist['id']}/items", headers=mgr_headers,
                                 json={"title": "ZZ Perm Item 2", "assigned_role": "employee"})
            assert after.status_code == 201, after.text
            client.delete(f"/api/ob/checklists/{checklist['id']}/items/{after.json()['id']}", headers=hr_manager_auth)
        finally:
            client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                           params={"action_key": "onboarding_offboarding.add_edit_delete_checklist_item_hr", "role": "manager"})
    finally:
        client.delete(f"/api/ob/checklists/{checklist['id']}", headers=hr_manager_auth)


def test_onboarding_complete_item_action_stays_non_enforced(client, hr_manager_auth):
    """Assigned_role-matched, not a flat role list — must be rejected."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "onboarding_offboarding.complete_update_checklist_item", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Fourth pilot module: Learning & Development (routers/ld.py) —
# manage_courses_quizzes, view_l_d_history_for_an_employee.
# (approve_reject_enrollment stays non-enforced — approval-workflow engine,
# same as the other *.approve_reject_* keys.)
# ---------------------------------------------------------------------------
def test_ld_override_lets_manager_manage_courses(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/ld/courses", headers=mgr_headers,
                          json={"title": "ZZ Perm Course", "category": "professional_development", "cost": 0.0})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "learning_development.manage_courses_quizzes", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/ld/courses", headers=mgr_headers,
                             json={"title": "ZZ Perm Course 2", "category": "professional_development", "cost": 0.0})
        assert after.status_code == 201, after.text
        client.delete(f"/api/ld/courses/{after.json()['id']}", headers=hr_manager_auth)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "learning_development.manage_courses_quizzes", "role": "manager"})

    after_reset = client.post("/api/ld/courses", headers=mgr_headers,
                               json={"title": "ZZ Perm Course 3", "category": "professional_development", "cost": 0.0})
    assert after_reset.status_code == 403, after_reset.text


def test_ld_enrollment_approval_action_stays_non_enforced(client, hr_manager_auth):
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "learning_development.approve_reject_enrollment", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Fifth pilot module: Attendance (routers/attendance.py) —
# manage_shifts_assignments_settings, review_queue_resolve_attendance_record,
# manage_attendance_devices.
# ---------------------------------------------------------------------------
def test_attendance_override_lets_employee_manage_shifts(client, hr_manager_auth, make_test_user, test_institution):
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}
    payload = {"name": "ZZ Perm Shift", "start_time": "09:00", "end_time": "18:00", "grace_period_minutes": 15}

    before = client.post("/api/attendance/shifts", headers=emp_headers, json=payload)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "attendance.manage_shifts_assignments_settings", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/attendance/shifts", headers=emp_headers, json=payload)
        assert after.status_code == 201, after.text
        client.delete(f"/api/attendance/shifts/{after.json()['id']}", headers=hr_manager_auth)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "attendance.manage_shifts_assignments_settings", "role": "employee"})

    after_reset = client.post("/api/attendance/shifts", headers=emp_headers, json=payload)
    assert after_reset.status_code == 403, after_reset.text


def test_attendance_override_lets_employee_view_review_queue(client, hr_manager_auth, make_test_user, test_institution):
    """manager was this test's original example role, but it's now
    ALLOW-by-default for this action (a manager reviews their own team's
    late/absent days — see core/permission_matrix.py's Attendance module
    and tests/test_attendance.py's manager-scoping coverage), so it no
    longer demonstrates "override lets a normally-denied role in". employee
    is still DENY-by-default and override-eligible, so it now plays that
    role instead."""
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get("/api/attendance/review", headers=emp_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "attendance.review_queue_resolve_attendance_record", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get("/api/attendance/review", headers=emp_headers)
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "attendance.review_queue_resolve_attendance_record", "role": "employee"})


def test_attendance_override_lets_employee_manage_devices(client, hr_manager_auth, make_test_user, test_institution):
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get("/api/attendance/devices", headers=emp_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "attendance.manage_attendance_devices", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get("/api/attendance/devices", headers=emp_headers)
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "attendance.manage_attendance_devices", "role": "employee"})


def test_attendance_clock_in_out_action_stays_non_enforced(client, hr_manager_auth):
    """Self-serve, NO_RESTRICTION — not a flat role list, must be rejected."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "attendance.clock_in_out_view_own_attendance", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Sixth pilot module: HR Notes (routers/hr_notes.py) — view_create_hr_note,
# delete_hr_note. (This module has no other test coverage yet, so this is
# also the first exercise of its endpoints.)
# ---------------------------------------------------------------------------
def test_hr_notes_override_lets_manager_view_and_create_notes(client, hr_manager_auth, make_test_user, make_test_employee, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}
    emp = make_test_employee()

    before = client.get(f"/api/employees/{emp['employee_id']}/notes", headers=mgr_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "hr_notes.view_create_hr_note", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        created = client.post(f"/api/employees/{emp['employee_id']}/notes", headers=mgr_headers,
                               json={"body": "ZZ perm test note"})
        assert created.status_code == 201, created.text
        listed = client.get(f"/api/employees/{emp['employee_id']}/notes", headers=mgr_headers)
        assert listed.status_code == 200, listed.text
        assert any(n["body"] == "ZZ perm test note" for n in listed.json())
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "hr_notes.view_create_hr_note", "role": "manager"})

    after_reset = client.get(f"/api/employees/{emp['employee_id']}/notes", headers=mgr_headers)
    assert after_reset.status_code == 403, after_reset.text


def test_hr_notes_override_lets_employee_delete_notes(client, hr_manager_auth, make_test_user, make_test_employee, test_institution):
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}
    emp = make_test_employee()
    created = client.post(f"/api/employees/{emp['employee_id']}/notes", headers=hr_manager_auth,
                           json={"body": "ZZ perm delete test note"})
    assert created.status_code == 201, created.text
    notes = client.get(f"/api/employees/{emp['employee_id']}/notes", headers=hr_manager_auth).json()
    note_id = next(n["id"] for n in notes if n["body"] == "ZZ perm delete test note")

    before = client.delete(f"/api/employees/{emp['employee_id']}/notes/{note_id}", headers=emp_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "hr_notes.delete_hr_note", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.delete(f"/api/employees/{emp['employee_id']}/notes/{note_id}", headers=emp_headers)
        assert after.status_code == 204, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "hr_notes.delete_hr_note", "role": "employee"})


# ---------------------------------------------------------------------------
# Seventh pilot module: Approval Workflows
# (routers/approval_workflow_settings.py) — manage_approval_workflows_steps.
# Institution-scoped, unlike Institutions/system-wide Notifications (see
# ENFORCED_ACTION_KEYS notes on why those two are deliberately excluded).
# ---------------------------------------------------------------------------
def test_approval_workflows_override_lets_manager_manage_workflows(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/approval-workflows", headers=mgr_headers, json={"module": "leave", "name": "ZZ Perm Workflow"})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "approval_workflows.manage_approval_workflows_steps", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/approval-workflows", headers=mgr_headers, json={"module": "leave", "name": "ZZ Perm Workflow 2"})
        assert after.status_code == 201, after.text
        client.delete(f"/api/approval-workflows/{after.json()['id']}", headers=hr_manager_auth)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "approval_workflows.manage_approval_workflows_steps", "role": "manager"})

    after_reset = client.post("/api/approval-workflows", headers=mgr_headers, json={"module": "leave", "name": "ZZ Perm Workflow 3"})
    assert after_reset.status_code == 403, after_reset.text


# ---------------------------------------------------------------------------
# Eighth pilot module: Custom Roles (routers/roles.py) —
# create_delete_custom_role ONLY. get_permission_matrix,
# set_permission_override, and reset_permission_override deliberately stay
# outside the override system entirely (see ENFORCED_ACTION_KEYS notes) —
# the escalation-guard test below proves that holds even once a role has
# create/delete-custom-role access.
# ---------------------------------------------------------------------------
def test_custom_roles_override_lets_manager_create_and_delete_roles(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/roles", headers=mgr_headers, json={"display_name": "ZZ Perm Role"})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "custom_roles.create_delete_custom_role", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/roles", headers=mgr_headers, json={"display_name": "ZZ Perm Role 2"})
        assert after.status_code == 201, after.text

        # Escalation guard: manager still can't touch the matrix itself,
        # even with create/delete-custom-role access.
        matrix_res = client.get("/api/roles/permission-matrix", headers=mgr_headers)
        assert matrix_res.status_code == 403, matrix_res.text
        override_res = client.put("/api/roles/permission-matrix/override", headers=mgr_headers, json={
            "action_key": "custom_roles.create_delete_custom_role", "role": "employee", "access_value": "allow",
        })
        assert override_res.status_code == 403, override_res.text

        delete_res = client.delete(f"/api/roles/{after.json()['id']}", headers=mgr_headers)
        assert delete_res.status_code == 204, delete_res.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "custom_roles.create_delete_custom_role", "role": "manager"})

    after_reset = client.post("/api/roles", headers=mgr_headers, json={"display_name": "ZZ Perm Role 3"})
    assert after_reset.status_code == 403, after_reset.text


# ---------------------------------------------------------------------------
# Ninth pilot module: Audit Log (routers/audit.py) —
# view_institution_audit_log.
# ---------------------------------------------------------------------------
def test_audit_log_override_lets_employee_view_log(client, hr_manager_auth, make_test_user, test_institution):
    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get("/api/audit-logs", headers=emp_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "audit_log.view_institution_audit_log", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get("/api/audit-logs", headers=emp_headers)
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "audit_log.view_institution_audit_log", "role": "employee"})

    after_reset = client.get("/api/audit-logs", headers=emp_headers)
    assert after_reset.status_code == 403, after_reset.text


# ---------------------------------------------------------------------------
# Tenth pilot module: Users (routers/users.py) —
# list_create_update_user, delete_user. Retrofitting this required first
# fixing a real bug: update_user's/delete_user's extra protections were
# gated on the literal role "hr_manager", not "any non-superadmin actor" —
# see the escalation-guard test below, which is the whole reason this
# module needed extra care.
# ---------------------------------------------------------------------------
def test_users_override_lets_manager_create_and_update_users(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}
    username = f"zzpermov_user_{os.urandom(3).hex()}"

    before = client.post("/api/users", headers=mgr_headers, json={
        "username": username, "full_name": "ZZ Perm User", "password": "ZzPytest@123", "role": "employee",
    })
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "users.list_create_update_user", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/users", headers=mgr_headers, json={
            "username": username, "full_name": "ZZ Perm User", "password": "ZzPytest@123", "role": "employee",
        })
        assert after.status_code == 201, after.text
        list_res = client.get("/api/users", headers=mgr_headers)
        assert list_res.status_code == 200, list_res.text
        client.delete(f"/api/users/{after.json()['id']}", headers=hr_manager_auth)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "users.list_create_update_user", "role": "manager"})


def test_users_override_escalation_guard_manager_cannot_touch_superadmin(client, hr_manager_auth, superadmin_headers, make_test_user, test_institution):
    """The whole reason this module needed extra care before retrofitting:
    a manager granted list_create_update_user access must still be unable
    to assign the Platform Admin role, edit the seeded superadmin account,
    or delete it."""
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    global_list = client.get("/api/users", headers={"Authorization": superadmin_headers["Authorization"]}).json()
    superadmin_row = next(u for u in global_list if u["role"] == "superadmin")

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "users.list_create_update_user", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    override2 = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "users.delete_user", "role": "manager", "access_value": "allow",
    })
    assert override2.status_code == 200, override2.text
    try:
        # Cannot create a new Platform Admin account.
        create_res = client.post("/api/users", headers=mgr_headers, json={
            "username": f"zzpermov_sa_{os.urandom(3).hex()}",
            "full_name": "ZZ Escalation Attempt", "password": "ZzPytest@123", "role": "superadmin",
        })
        assert create_res.status_code == 403, create_res.text

        # Cannot edit the existing Platform Admin account.
        edit_res = client.put(f"/api/users/{superadmin_row['id']}", headers=mgr_headers, json={
            "full_name": "ZZ Hacked", "role": "superadmin",
        })
        assert edit_res.status_code in (403, 404), edit_res.text

        # Cannot delete the existing Platform Admin account.
        delete_res = client.delete(f"/api/users/{superadmin_row['id']}", headers=mgr_headers)
        assert delete_res.status_code in (403, 404), delete_res.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "users.list_create_update_user", "role": "manager"})
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "users.delete_user", "role": "manager"})


def test_projects_override_lets_manager_manage_projects(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/projects", headers=mgr_headers, json={"name": "ZZ Perm Project", "status": "Active"})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "projects_tasks.manage_projects_tasks_assignments", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/projects", headers=mgr_headers, json={"name": "ZZ Perm Project", "status": "Active"})
        assert after.status_code == 201, after.text
        util = client.get("/api/projects/utilization", headers=mgr_headers)
        assert util.status_code == 403, util.text  # separate action key, not granted here
        client.delete(f"/api/projects/{after.json()['id']}", headers=hr_manager_auth)
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "projects_tasks.manage_projects_tasks_assignments", "role": "manager"})


def test_recruitment_override_lets_manager_create_requisition(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.post("/api/recruitment/requisitions", headers=mgr_headers, json={
        "title": "ZZ Perm Role", "department": "Engineering",
    })
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "recruitment.create_edit_requisition_candidate_interview_offer", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/recruitment/requisitions", headers=mgr_headers, json={
            "title": "ZZ Perm Role", "department": "Engineering",
        })
        assert after.status_code == 201, after.text
        audit = client.get(f"/api/recruitment/candidates/999999999/audit-log", headers=mgr_headers)
        assert audit.status_code == 403, audit.text  # separate action key, not granted here
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "recruitment.create_edit_requisition_candidate_interview_offer", "role": "manager"})


def test_compensation_override_lets_manager_create_pay_grade(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}
    payload = {
        "grade_code": f"ZZPG{os.urandom(3).hex()}", "grade_name": "ZZ Perm Grade",
        "grade_level": 1, "min_salary": 3000, "midpoint_salary": 4000, "max_salary": 5000,
    }

    before = client.post("/api/compensation/pay-grades", headers=mgr_headers, json=payload)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "compensation.manage_pay_grades_job_levels_roles", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/compensation/pay-grades", headers=mgr_headers, json=payload)
        assert after.status_code == 201, after.text
        bonus = client.post("/api/compensation/bonus-plans", headers=mgr_headers, json={
            "plan_name": "ZZ Perm Bonus", "plan_type": "Spot", "plan_year": 2026,
            "period_start": "2026-01-01", "period_end": "2026-12-31",
        })
        assert bonus.status_code == 403, bonus.text  # separate action key, not granted here
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "compensation.manage_pay_grades_job_levels_roles", "role": "manager"})


def test_benefits_override_lets_manager_manage_plans(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}
    payload = {
        "plan_name": "ZZ Perm Plan", "plan_category": "Medical", "contribution_type": "Fixed Premium",
        "employer_cost": 100, "employee_cost": 0,
    }

    before = client.post("/api/benefits/plans", headers=mgr_headers, json=payload)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "benefits.manage_benefit_plans_eligibility_enrollment_periods", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.post("/api/benefits/plans", headers=mgr_headers, json=payload)
        assert after.status_code == 201, after.text
        dashboard = client.get("/api/benefits/reports/dashboard", headers=mgr_headers)
        assert dashboard.status_code == 200, dashboard.text  # manager already has this by default (require_benefits_dashboard_role)
        dependents = client.post(f"/api/benefits/employees/ZZNOPE/dependents", headers=mgr_headers, json={
            "full_name": "ZZ Dep", "relationship": "Spouse", "date_of_birth": "1990-01-01",
        })
        assert dependents.status_code == 403, dependents.text  # separate action key, not granted here
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "benefits.manage_benefit_plans_eligibility_enrollment_periods", "role": "manager"})


# ---------------------------------------------------------------------------
# Overtime (routers/overtime.py) — configure_overtime_settings only. See
# permission_matrix.py's ENFORCED_ACTION_KEYS notes on this module: the
# other three rows (view settings, view records, approve/reject) stay
# unenforced (NO_RESTRICTION/CONFIGURABLE), same reasoning as every other
# module's non-enforced rows.
# ---------------------------------------------------------------------------
def test_overtime_override_lets_manager_configure_settings(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.put("/api/overtime/settings", headers=mgr_headers, json={"overtime_conversion_mode": "pay"})
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "overtime.configure_overtime_settings", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.put("/api/overtime/settings", headers=mgr_headers, json={"overtime_conversion_mode": "pay"})
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "overtime.configure_overtime_settings", "role": "manager"})
        # Restore the institution's overtime settings to a state later tests
        # in this shared institution expect, mirroring test_overtime.py's
        # own cleanup convention for this same endpoint.
        client.put("/api/overtime/settings", headers=hr_manager_auth, json={"overtime_conversion_mode": "pay"})


def test_overtime_approval_action_stays_non_enforced(client, hr_manager_auth):
    """approve_reject_overtime has a flat-looking access dict but its real
    gate is the approval-workflow engine — must never be added to
    ENFORCED_ACTION_KEYS no matter how it looks structurally, same
    reasoning as every other *.approve_reject_* key in this file."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "overtime.approve_reject_overtime", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# Recruitment — "View requisitions / candidates / interviews / offers"
# ---------------------------------------------------------------------------
def _unique_title():
    import os
    return f"ZZ Perm Override Test Role {os.urandom(4).hex()}"


def test_recruitment_view_denied_by_default_for_manager(client, hr_manager_auth, make_test_user, test_institution):
    """list_requisitions/get_requisition/list_candidates/get_candidate/
    list_interviews/list_offers/get_offer previously had either no gate at
    all (the first five) or were tied to the write action's key (offers) —
    all seven now default-deny manager (and payroll_manager/
    compensation_manager/employee) via their own view-specific key."""
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Engineering"}).json()
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Perm Override Candidate", "email": "zzpytest.cand1.12886@example.com",}).json()

    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    assert client.get("/api/recruitment/requisitions", headers=mgr_headers).status_code == 403
    assert client.get(f"/api/recruitment/requisitions/{req['id']}", headers=mgr_headers).status_code == 403
    assert client.get("/api/recruitment/candidates", headers=mgr_headers).status_code == 403
    assert client.get(f"/api/recruitment/candidates/{cand['id']}", headers=mgr_headers).status_code == 403
    assert client.get("/api/recruitment/interviews", headers=mgr_headers).status_code == 403
    assert client.get("/api/recruitment/offers", headers=mgr_headers).status_code == 403


def test_recruitment_view_override_actually_changes_behavior(client, hr_manager_auth, make_test_user, test_institution):
    """The core claim of this feature, same as the Employees-module test
    above: overriding manager's access here must really let them view
    requisitions, not just change what the matrix displays."""
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get("/api/recruitment/requisitions", headers=mgr_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "recruitment.view_requisitions_candidates_interviews_offers",
        "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get("/api/recruitment/requisitions", headers=mgr_headers)
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "recruitment.view_requisitions_candidates_interviews_offers", "role": "manager"})

    after_reset = client.get("/api/recruitment/requisitions", headers=mgr_headers)
    assert after_reset.status_code == 403, after_reset.text


def test_recruitment_view_hr_manager_and_hr_admin_unaffected(client, hr_manager_auth, make_test_user, test_institution):
    """hr_manager/hr_admin are LOCKED_ROLES — always allowed here, same as
    every other recruitment write action, regardless of any override."""
    assert client.get("/api/recruitment/requisitions", headers=hr_manager_auth).status_code == 200

    admin_token, _ = make_test_user(role="hr_admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Institution-Id": str(test_institution["id"])}
    assert client.get("/api/recruitment/requisitions", headers=admin_headers).status_code == 200


def test_current_user_can_view_recruitment_field_reflects_override(client, hr_manager_auth, make_test_user, test_institution):
    """GET /api/auth/me's can_view_recruitment (core/deps.py's
    build_current_user_out) is what static/js/core.js's applyRoleUI uses to
    decide whether to show the Recruitment nav group — must track the same
    override, not just the static role."""
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get("/api/auth/me", headers=mgr_headers)
    assert before.status_code == 200, before.text
    assert before.json()["can_view_recruitment"] is False

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "recruitment.view_requisitions_candidates_interviews_offers",
        "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get("/api/auth/me", headers=mgr_headers)
        assert after.json()["can_view_recruitment"] is True
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "recruitment.view_requisitions_candidates_interviews_offers", "role": "manager"})

    hr_me = client.get("/api/auth/me", headers=hr_manager_auth)
    assert hr_me.json()["can_view_recruitment"] is True


def test_candidate_stage_timing_override_eligible_for_other_roles(client, hr_manager_auth, make_test_user, test_institution):
    """get_candidate_stage_history already called require_permission() with
    this key before it was added to ENFORCED_ACTION_KEYS — manager is
    flat-ALLOW by default already (unaffected by this test). employee is
    the role this actually unlocks: denied by default, with no way to
    grant an override until the key was added to ENFORCED_ACTION_KEYS.
    payroll_manager/compensation_manager are LOCKED_ROLES (see
    test_permission_overrides' module docstring) and can never be
    overridden regardless — not what this key change affects."""
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Stage Timing Override Candidate", "email": "zzpytest.cand2.83916@example.com",}).json()

    emp_token, _ = make_test_user(role="employee")
    emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get(f"/api/recruitment/candidates/{cand['id']}/stage-history", headers=emp_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "recruitment.view_candidate_stage_timing", "role": "employee", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get(f"/api/recruitment/candidates/{cand['id']}/stage-history", headers=emp_headers)
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "recruitment.view_candidate_stage_timing", "role": "employee"})

    after_reset = client.get(f"/api/recruitment/candidates/{cand['id']}/stage-history", headers=emp_headers)
    assert after_reset.status_code == 403, after_reset.text


def test_custom_role_denied_by_default_then_override_actually_works(client, hr_manager_auth, make_test_user, test_institution):
    """Regression test for a real production bug (institution 4, custom
    role "Hiring Manager"): has_permission() used to check the raw custom
    role string directly against MATRIX's static access dicts, which are
    only ever built from ALL_ROLES — so a custom role could never match
    an access-default key AND is_override_eligible() also always failed
    for it, meaning has_permission() returned False unconditionally and
    never even queried role_permission_overrides. The Settings > Roles
    matrix UI (routers/roles.py's get_permission_matrix/
    _validate_overridable, via eligibility_proxy_role) already proxied
    custom roles to "employee" for display/write-validation, so HR could
    create an override for the custom role's own literal role_key and see
    it reflected in the matrix — but it silently never took effect at the
    actual enforcement point. This test creates a real custom role (not
    just a user whose .role happens to be a custom string), confirms it's
    denied by the same default as Employee, then confirms a per-custom-
    role override granted via the matrix actually changes real endpoint
    behavior, not just the matrix's own display."""
    role_res = client.post("/api/roles", headers=hr_manager_auth,
                            json={"display_name": f"ZZ Hiring Manager {os.urandom(3).hex()}"})
    assert role_res.status_code == 201, role_res.text
    role_key = role_res.json()["role_key"]
    role_id = role_res.json()["id"]
    try:
        hm_token, _ = make_test_user(role=role_key)
        hm_headers = {"Authorization": f"Bearer {hm_token}", "X-Institution-Id": str(test_institution["id"])}

        before = client.get("/api/recruitment/requisitions", headers=hm_headers)
        assert before.status_code == 403, before.text

        matrix = client.get("/api/roles/permission-matrix", headers=hr_manager_auth).json()
        action = next(a for m in matrix["modules"] for a in m["actions"]
                       if a["key"] == "recruitment.view_requisitions_candidates_interviews_offers")
        assert action["editable"][role_key] is True, "custom role must display as override-eligible, proxied to employee"

        override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
            "action_key": "recruitment.view_requisitions_candidates_interviews_offers",
            "role": role_key, "access_value": "allow",
        })
        assert override.status_code == 200, override.text
        try:
            after = client.get("/api/recruitment/requisitions", headers=hm_headers)
            assert after.status_code == 200, after.text
        finally:
            client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                           params={"action_key": "recruitment.view_requisitions_candidates_interviews_offers", "role": role_key})

        after_reset = client.get("/api/recruitment/requisitions", headers=hm_headers)
        assert after_reset.status_code == 403, after_reset.text
    finally:
        client.delete(f"/api/roles/{role_id}", headers=hr_manager_auth)


def test_custom_role_override_is_independent_of_employee_override(client, hr_manager_auth, make_test_user, test_institution):
    """A custom role's override is stored/looked-up by its own literal
    role_key, not silently merged into "employee"'s override row — HR
    must be able to grant the custom role access without that also
    granting every real Employee the same access, and vice versa."""
    role_res = client.post("/api/roles", headers=hr_manager_auth,
                            json={"display_name": f"ZZ IT Infra {os.urandom(3).hex()}"})
    assert role_res.status_code == 201, role_res.text
    role_key = role_res.json()["role_key"]
    role_id = role_res.json()["id"]
    try:
        hm_token, _ = make_test_user(role=role_key)
        hm_headers = {"Authorization": f"Bearer {hm_token}", "X-Institution-Id": str(test_institution["id"])}
        emp_token, _ = make_test_user(role="employee")
        emp_headers = {"Authorization": f"Bearer {emp_token}", "X-Institution-Id": str(test_institution["id"])}

        override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
            "action_key": "recruitment.view_requisitions_candidates_interviews_offers",
            "role": role_key, "access_value": "allow",
        })
        assert override.status_code == 200, override.text
        try:
            assert client.get("/api/recruitment/requisitions", headers=hm_headers).status_code == 200
            assert client.get("/api/recruitment/requisitions", headers=emp_headers).status_code == 403
        finally:
            client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                           params={"action_key": "recruitment.view_requisitions_candidates_interviews_offers", "role": role_key})
    finally:
        client.delete(f"/api/roles/{role_id}", headers=hr_manager_auth)


def test_approve_requisition_stays_non_enforced(client, hr_manager_auth):
    """CONFIGURABLE (the approval-workflow engine resolves the real
    approver per-institution) — an override here would let someone "grant"
    approval rights the engine would still completely ignore, since
    advance_or_finalize never consults role_permission_overrides. Must
    never be added to ENFORCED_ACTION_KEYS, same reasoning as every other
    *.approve_reject_*/approve_* key in this file."""
    res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "recruitment.approve_requisition", "role": "manager", "access_value": "allow",
    })
    assert res.status_code == 400, res.text


def test_current_user_recruitment_write_and_history_flags_follow_overrides_for_a_custom_role(
        client, hr_manager_auth, make_test_user, test_institution):
    """GET /api/auth/me's can_manage_recruitment / can_view_candidate_history /
    can_view_candidate_stage_time drive the Recruitment screens' write buttons
    (static/js/recruitment.js) — they used to be a hardcoded role list, so a
    custom 'Hiring Manager' role granted 'Create / edit requisition, ...' got
    the API but never saw the '+ New Requisition' button."""
    role_res = client.post("/api/roles", headers=hr_manager_auth,
                            json={"display_name": f"ZZ Hiring Manager {os.urandom(3).hex()}"})
    assert role_res.status_code == 201, role_res.text
    role_key, role_id = role_res.json()["role_key"], role_res.json()["id"]
    flags = ("can_manage_recruitment", "can_view_candidate_history", "can_view_candidate_stage_time")
    keys = {"can_manage_recruitment": "recruitment.create_edit_requisition_candidate_interview_offer",
            "can_view_candidate_history": "recruitment.view_candidate_audit_log",
            "can_view_candidate_stage_time": "recruitment.view_candidate_stage_timing"}
    granted = []
    try:
        token, _ = make_test_user(role=role_key)
        headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
        me = client.get("/api/auth/me", headers=headers).json()
        assert [me[f] for f in flags] == [False, False, False]

        for flag in flags:
            res = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
                "action_key": keys[flag], "role": role_key, "access_value": "allow"})
            assert res.status_code == 200, res.text
            granted.append(keys[flag])
            me = client.get("/api/auth/me", headers=headers).json()
            assert me[flag] is True and [me[f] for f in flags].count(True) == len(granted)   # each grant flips only its own flag
        # ...and the API agrees with the flag
        created = client.post("/api/recruitment/requisitions", headers=headers,
                              json={"title": f"ZZ HM Req {os.urandom(3).hex()}", "department": "Engineering"})
        assert created.status_code == 201, created.text
    finally:
        for key in granted:
            client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                          params={"action_key": key, "role": role_key})
        client.delete(f"/api/roles/{role_id}", headers=hr_manager_auth)


def test_current_user_recruitment_flags_for_the_built_in_roles(client, hr_manager_auth, make_test_user, test_institution):
    hr_me = client.get("/api/auth/me", headers=hr_manager_auth).json()
    assert (hr_me["can_manage_recruitment"], hr_me["can_view_candidate_history"], hr_me["can_view_candidate_stage_time"]) == (True, True, True)
    token, _ = make_test_user(role="manager")
    mgr = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}).json()
    assert mgr["can_manage_recruitment"] is False and mgr["can_view_candidate_history"] is False
    assert mgr["can_view_candidate_stage_time"] is True       # managers already had this one by default
