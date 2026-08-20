"""Org chart (institution-scoped)."""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from core.deps import get_current_user, need_inst

from db import get_db
from core.db_session import db_session

router = APIRouter()


@router.get("/api/org-chart")
@db_session
def get_org_chart(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute("""
        SELECT e.employee_id, e.full_name, e.preferred_name, e.designation, e.department,
               e.status, e.reports_to, m.full_name AS manager_name, m.preferred_name AS manager_preferred_name
        FROM employees e
        LEFT JOIN employees m ON m.institution_id = e.institution_id AND m.employee_id = e.reports_to
        WHERE e.institution_id = ?
        ORDER BY e.full_name
    """, (inst_id,)).fetchall()
    return [dict(r) for r in rows]
