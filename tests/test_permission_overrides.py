"""Integration tests for the Settings > Roles > Permission Matrix override
system (core/permission_matrix.py's has_permission, routers/roles.py's
PUT/DELETE .../permission-matrix/override) — the pilot retrofit of
routers/employees.py's 6 flat-gated actions. See permission_matrix.py's
module docstring for why this started as a small pilot instead of every
router at once.
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


def test_attendance_override_lets_manager_view_review_queue(client, hr_manager_auth, make_test_user, test_institution):
    mgr_token, _ = make_test_user(role="manager")
    mgr_headers = {"Authorization": f"Bearer {mgr_token}", "X-Institution-Id": str(test_institution["id"])}

    before = client.get("/api/attendance/review", headers=mgr_headers)
    assert before.status_code == 403, before.text

    override = client.put("/api/roles/permission-matrix/override", headers=hr_manager_auth, json={
        "action_key": "attendance.review_queue_resolve_attendance_record", "role": "manager", "access_value": "allow",
    })
    assert override.status_code == 200, override.text
    try:
        after = client.get("/api/attendance/review", headers=mgr_headers)
        assert after.status_code == 200, after.text
    finally:
        client.delete("/api/roles/permission-matrix/override", headers=hr_manager_auth,
                       params={"action_key": "attendance.review_queue_resolve_attendance_record", "role": "manager"})


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
