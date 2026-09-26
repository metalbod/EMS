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


MASK = "***"


def diff_fields(old, new, labels, sensitive=()):
    """Structured before/after diff: [{field,label,old,new}] for every key in
    `labels` whose stringified value differs between the two dicts. Values
    for keys in `sensitive` are masked (never stored) — same convention as
    routers/employees.py's diff_employee, generalized for any entity."""
    out = []
    for f, label in labels.items():
        ov = "" if old.get(f) is None else str(old.get(f))
        nv = "" if new.get(f) is None else str(new.get(f))
        if ov != nv:
            out.append({"field": f, "label": label,
                        "old": MASK if f in sensitive else ov,
                        "new": MASK if f in sensitive else nv})
    return out


def write_entity_audit(conn, actor, inst_id, module, entity_type, entity_id, action,
                       detail=None, changes=None, entity_label=None, ip=None):
    """Generic audit row into `entity_audit_log` (see migration
    20260926_0001) — the shared trail for every module that has no
    dedicated *_audit_log table of its own. Call it right before the
    endpoint's own conn.commit(), so the audit row and the change it
    describes land (or roll back) together. `inst_id` may be None for
    platform-level entities (e.g. a superadmin account). Never pass secret
    values (passwords, API keys) in `detail`/`changes` — mask them first
    (diff_fields' `sensitive` argument does this for diffs)."""
    conn.execute("""
        INSERT INTO entity_audit_log
            (institution_id, module, entity_type, entity_id, entity_label, action,
             detail, changes, actor_id, actor_username, actor_role, ip_address)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (inst_id, module, entity_type, None if entity_id is None else str(entity_id),
          entity_label, action, detail, json.dumps(changes) if changes else None,
          actor.get("id"), actor.get("username"), actor.get("role"), ip))
