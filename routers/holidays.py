"""Holiday Manager (institution-scoped)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.deps import get_current_user, need_inst

from core.permission_matrix import require_permission

from db import get_db, IntegrityError
from core.db_session import db_session

router = APIRouter()


class HolidayIn(BaseModel):
    name: str
    date: str  # YYYY-MM-DD
    year: int


@router.get("/api/holidays")
@db_session
def list_holidays(conn, year: Optional[int] = None, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    q = "SELECT * FROM holidays WHERE institution_id=?"
    p = [inst_id]
    if year:
        q += " AND year=?"; p.append(year)
    q += " ORDER BY date"
    rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/holidays", status_code=201)
@db_session
def create_holiday(conn, body: HolidayIn, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    require_permission(conn, user, "leave.manage_public_holidays")
    inst_id = need_inst(user)
    try:
        conn.execute(
            "INSERT INTO holidays (institution_id,name,date,year,created_by) VALUES (?,?,?,?,?)",
            (inst_id, body.name, body.date, body.year, user["username"])
        )
        conn.commit()
    except IntegrityError as e:
        raise HTTPException(400, "A holiday already exists on this date")
    row = conn.execute("SELECT * FROM holidays WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.delete("/api/holidays/{holiday_id}", status_code=204)
@db_session
def delete_holiday(conn, holiday_id: int, user: dict = Depends(get_current_user)) -> None:
    require_permission(conn, user, "leave.manage_public_holidays")
    inst_id = need_inst(user)
    conn.execute("DELETE FROM holidays WHERE id=? AND institution_id=?", (holiday_id, inst_id))
    conn.commit()
