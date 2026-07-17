"""Audit log viewing (superadmin/hr_manager only)."""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

try:
    from core.deps import need_inst, require_roles
except ImportError:
    from ems.core.deps import need_inst, require_roles

try:
    from db import get_db
except ImportError:
    from ems.db import get_db
try:
    from core.db_session import db_session
except ImportError:
    from ems.core.db_session import db_session

router = APIRouter()


@router.get("/api/audit-logs")
@db_session
def list_audit_logs(
    conn,
    employee_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_roles("superadmin", "hr_manager")),
) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = "SELECT * FROM audit_logs WHERE institution_id=?"
    p = [inst_id]
    if employee_id: q += " AND target_employee_id=?"; p.append(employee_id)
    if action:      q += " AND action=?";             p.append(action)
    q += " ORDER BY timestamp DESC LIMIT ?"
    p.append(limit)
    rows = conn.execute(q, p).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["changes"] = json.loads(d["changes"]) if d["changes"] else []
        result.append(d)
    return result
