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
