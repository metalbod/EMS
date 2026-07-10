"""
Institution Notifications — configured by HR Manager/HR Admin, shown as a
dashboard banner to all non-superadmin roles while within [start_time, end_time].
Overlapping active windows are rejected at save time so at most one
notification is ever active for an institution at a given moment.

System-Wide Notifications — configured by superadmin only, shown as a red
"urgency" banner above the institution notification banner, to ALL users
across ALL institutions (including superadmin), e.g. system downtime.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

try:
    from core.deps import get_current_user, need_inst, require_roles
except ImportError:
    from ems.core.deps import get_current_user, need_inst, require_roles

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

router = APIRouter()

NOTIFICATION_MANAGE_ROLES = ("hr_manager", "hr_admin")


class NotificationIn(BaseModel):
    message: str
    start_time: str  # ISO datetime, e.g. 2026-07-08T09:00
    end_time: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message is required")
        word_count = len(v.split())
        if word_count > 500:
            raise ValueError(f"Message must be 500 words or fewer (currently {word_count})")
        return v


# ---------------------------------------------------------------------------
# Institution notifications
# ---------------------------------------------------------------------------
def _notification_overlaps(conn, inst_id, start_time, end_time, exclude_id=None):
    q = """
        SELECT id FROM institution_notifications
        WHERE institution_id=? AND NOT (end_time <= ? OR start_time >= ?)
    """
    params: list = [inst_id, start_time, end_time]
    if exclude_id is not None:
        q += " AND id != ?"; params.append(exclude_id)
    return conn.execute(q, params).fetchone() is not None


@router.get("/api/notifications")
def list_notifications(user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM institution_notifications WHERE institution_id=? ORDER BY start_time DESC", (inst_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/notifications/active")
def get_active_notification(user: dict = Depends(get_current_user)):
    inst_id = user.get("active_institution_id")
    if not inst_id or user["role"] == "superadmin":
        return None
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    row = conn.execute(
        "SELECT * FROM institution_notifications WHERE institution_id=? AND start_time<=? AND end_time>=? "
        "ORDER BY start_time DESC LIMIT 1",
        (inst_id, now, now)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


@router.post("/api/notifications", status_code=201)
def create_notification(body: NotificationIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _notification_overlaps(conn, inst_id, body.start_time, body.end_time):
        conn.close(); raise HTTPException(400, "Another notification is already active/scheduled during this window")
    conn.execute(
        "INSERT INTO institution_notifications (institution_id,message,start_time,end_time,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.message, body.start_time, body.end_time, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institution_notifications WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)


@router.put("/api/notifications/{notification_id}")
def update_notification(notification_id: int, body: NotificationIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    if not conn.execute("SELECT id FROM institution_notifications WHERE id=? AND institution_id=?", (notification_id, inst_id)).fetchone():
        conn.close(); raise HTTPException(404, "Notification not found")
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _notification_overlaps(conn, inst_id, body.start_time, body.end_time, exclude_id=notification_id):
        conn.close(); raise HTTPException(400, "Another notification is already active/scheduled during this window")
    conn.execute(
        "UPDATE institution_notifications SET message=?,start_time=?,end_time=? WHERE id=?",
        (body.message, body.start_time, body.end_time, notification_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institution_notifications WHERE id=?", (notification_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/notifications/{notification_id}", status_code=204)
def delete_notification(notification_id: int, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))):
    inst_id = need_inst(user)
    conn = get_db()
    conn.execute("DELETE FROM institution_notifications WHERE id=? AND institution_id=?", (notification_id, inst_id))
    conn.commit(); conn.close()


# ---------------------------------------------------------------------------
# System-wide notifications
# ---------------------------------------------------------------------------
def _system_notification_overlaps(conn, start_time, end_time, exclude_id=None):
    q = "SELECT id FROM system_notifications WHERE NOT (end_time <= ? OR start_time >= ?)"
    params: list = [start_time, end_time]
    if exclude_id is not None:
        q += " AND id != ?"; params.append(exclude_id)
    return conn.execute(q, params).fetchone() is not None


@router.get("/api/system-notifications")
def list_system_notifications(user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    rows = conn.execute("SELECT * FROM system_notifications ORDER BY start_time DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/system-notifications/active")
def get_active_system_notification(user: dict = Depends(get_current_user)):
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    row = conn.execute(
        "SELECT * FROM system_notifications WHERE start_time<=? AND end_time>=? ORDER BY start_time DESC LIMIT 1",
        (now, now)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


@router.post("/api/system-notifications", status_code=201)
def create_system_notification(body: NotificationIn, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _system_notification_overlaps(conn, body.start_time, body.end_time):
        conn.close(); raise HTTPException(400, "Another system notification is already active/scheduled during this window")
    conn.execute(
        "INSERT INTO system_notifications (message,start_time,end_time,created_by) VALUES (?,?,?,?)",
        (body.message, body.start_time, body.end_time, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM system_notifications WHERE id=last_insert_rowid()").fetchone()
    conn.close()
    return dict(row)


@router.put("/api/system-notifications/{notification_id}")
def update_system_notification(notification_id: int, body: NotificationIn, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    if not conn.execute("SELECT id FROM system_notifications WHERE id=?", (notification_id,)).fetchone():
        conn.close(); raise HTTPException(404, "Notification not found")
    if body.end_time <= body.start_time:
        conn.close(); raise HTTPException(400, "End time must be after start time")
    if _system_notification_overlaps(conn, body.start_time, body.end_time, exclude_id=notification_id):
        conn.close(); raise HTTPException(400, "Another system notification is already active/scheduled during this window")
    conn.execute(
        "UPDATE system_notifications SET message=?,start_time=?,end_time=? WHERE id=?",
        (body.message, body.start_time, body.end_time, notification_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM system_notifications WHERE id=?", (notification_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/system-notifications/{notification_id}", status_code=204)
def delete_system_notification(notification_id: int, user: dict = Depends(require_roles("superadmin"))):
    conn = get_db()
    conn.execute("DELETE FROM system_notifications WHERE id=?", (notification_id,))
    conn.commit(); conn.close()
