"""Integration tests for the Settings > Roles > Permission Matrix override
system (core/permission_matrix.py's has_permission, routers/roles.py's
PUT/DELETE .../permission-matrix/override) — the pilot retrofit of
routers/employees.py's 6 flat-gated actions. See permission_matrix.py's
module docstring for why this started as a small pilot instead of every
router at once.
"""
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
