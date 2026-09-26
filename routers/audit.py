"""Audit log viewing (superadmin/hr_manager only)."""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Response

from core.deps import get_current_user, need_inst

from core.permission_matrix import require_permission

from db import get_db
from core.db_session import db_session

router = APIRouter()


@router.get("/api/audit-logs")
@db_session
def list_audit_logs(
    conn,
    response: Response,
    employee_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Institution audit log, server-paginated (limit/offset — this
    institution's full history can run into the thousands of rows once a
    tenant's been active a while, and used to be silently capped at the
    most recent 200 with no way to see anything older). Still returns a
    plain list, not {items, total} — the total row count is surfaced via
    an X-Total-Count response header instead, so this stays a
    drop-in-compatible response shape for every existing caller (the
    frontend's own table just reads the new header; nothing else calls
    this endpoint expecting a wrapped shape)."""
    require_permission(conn, user, "audit_log.view_institution_audit_log")
    inst_id = need_inst(user)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    q = "SELECT * FROM audit_logs WHERE institution_id=?"
    p = [inst_id]
    if employee_id: q += " AND target_employee_id=?"; p.append(employee_id)
    if action:      q += " AND action=?";             p.append(action)
    total = conn.execute(q.replace("SELECT *", "SELECT COUNT(*)", 1), p).fetchone()[0]
    response.headers["X-Total-Count"] = str(total)
    q += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    rows = conn.execute(q, p + [limit, offset]).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["changes"] = json.loads(d["changes"]) if d["changes"] else []
        result.append(d)
    return result


@router.get("/api/login-audit-log")
@db_session
def list_login_audit_log(
    conn,
    response: Response,
    success: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Login attempts (success and failure) for this institution — see
    routers/auth.py's _record_login_audit. Superadmin with no institution
    context selected sees every institution's attempts, matching
    list_audit_logs' own global-view behavior below."""
    require_permission(conn, user, "audit_log.view_login_audit_log")
    inst_id = user.get("active_institution_id")
    q = "SELECT * FROM login_audit_log"
    p = []
    clauses = []
    if inst_id:
        clauses.append("institution_id=?"); p.append(inst_id)
    if success is not None:
        clauses.append("success=?"); p.append(success)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    total = conn.execute(q.replace("SELECT *", "SELECT COUNT(*)", 1), p).fetchone()[0]
    response.headers["X-Total-Count"] = str(total)
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    rows = conn.execute(q, p + [limit, offset]).fetchall()
    return [dict(r) for r in rows]


# Read-only mapping of the older per-module audit tables into the same
# shape as entity_audit_log, so the Activity view shows one unified trail
# without duplicating writes. (module, entity_type, entity id column,
# label expr, actor role expr, table). Order is irrelevant — results are
# sorted by created_at afterwards.
_LEGACY_TRAILS = (
    ("Recruitment", "candidate", "candidate_id", "NULL", "NULL", "candidate_audit_log"),
    ("Recruitment", "requisition", "requisition_id", "NULL", "performer_role", "requisition_audit_log"),
    ("Onboarding", "checklist", "checklist_id", "employee_id", "performer_role", "ob_audit_log"),
    ("L&D", "enrollment", "enrollment_id", "employee_id", "performer_role", "ld_audit_log"),
    ("Leave", "application", "application_id", "employee_id", "performer_role", "leave_audit_log"),
    ("Timesheet", "timesheet", "timesheet_id", "employee_id", "performer_role", "timesheet_audit_log"),
    ("Performance", "appraisal", "appraisal_id", "employee_id", "performer_role", "appraisal_audit_log"),
)


@router.get("/api/entity-audit-log")
@db_session
def list_entity_audit_log(
    conn,
    response: Response,
    module: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_legacy: bool = True,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """System Activity log: the generic entity_audit_log (see
    core/audit.py's write_entity_audit) plus — unless include_legacy=false —
    a read-only union of the older per-module trails. Server-paginated with
    an X-Total-Count header, like list_audit_logs above. Passing
    entity_type + entity_id gives one record's own history (what the
    per-record History popups call)."""
    require_permission(conn, user, "audit_log.view_system_activity_log")
    inst_id = need_inst(user)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)

    parts = ["""SELECT created_at, module, entity_type, entity_id, entity_label, action, detail, changes,
                        actor_username, actor_role, 'entity' AS source
                 FROM entity_audit_log WHERE institution_id=?"""]
    params: list = [inst_id]
    if include_legacy:
        for mod, etype, id_col, label, role, table in _LEGACY_TRAILS:
            parts.append(f"""SELECT created_at, '{mod}' AS module, '{etype}' AS entity_type,
                                    CAST({id_col} AS TEXT) AS entity_id, {label} AS entity_label, action, detail,
                                    NULL AS changes, performed_by AS actor_username, {role} AS actor_role,
                                    'legacy' AS source
                             FROM {table} WHERE institution_id=?""")
            params.append(inst_id)
    base = "SELECT * FROM (" + " UNION ALL ".join(parts) + ") u WHERE 1=1"
    if module:      base += " AND module=?";      params.append(module)
    if entity_type: base += " AND entity_type=?"; params.append(entity_type)
    if entity_id:   base += " AND entity_id=?";   params.append(str(entity_id))
    if actor:       base += " AND LOWER(actor_username) LIKE ?"; params.append(f"%{actor.lower()}%")
    if date_from:   base += " AND SUBSTR(created_at,1,10) >= ?"; params.append(date_from)
    if date_to:     base += " AND SUBSTR(created_at,1,10) <= ?"; params.append(date_to)

    total = conn.execute(base.replace("SELECT *", "SELECT COUNT(*)", 1), params).fetchone()[0]
    response.headers["X-Total-Count"] = str(total)
    rows = conn.execute(base + " ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["changes"] = json.loads(d["changes"]) if d["changes"] else []
        result.append(d)
    return result
