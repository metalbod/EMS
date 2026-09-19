"""
Institution Notifications — configured by HR Manager/HR Admin, shown as
dashboard banners to all non-superadmin roles while within each one's own
[start_time, end_time]. Any number can be simultaneously active — they
stack on the dashboard, each independently dismissible (see
static/js/notifications.js). This used to reject a new/edited window that
overlapped an existing one, on the premise that at most one notification
should ever be active at a time; that restriction is gone.

System-Wide Notifications — configured by superadmin only, shown as a red
"urgency" banner above the institution notification banner(s), to ALL
users across ALL institutions (including superadmin), e.g. system
downtime. Deliberately NOT stackable — still at most one active at a
time, overlap-rejected at save time exactly as before; this is reserved
for rare, singular platform-wide announcements, not routine messaging.

Email notification settings (Phase 1 of the email notification engine —
see core/email_engine.py, core/approval_workflow.py's notification hooks,
and migrations/versions/20260919_0001_email_notifications.py): each
institution configures its own SMTP mailbox (BYO-SMTP, same
encrypted-credential pattern as the AI assistant's Anthropic BYOK key)
to send approval/application emails from.

Notification general settings (institution timezone + the "announce a
public holiday on its eve" toggle — migrations/versions/
20260921_0001_notification_stacking_and_holiday_eve.py): the holiday-eve
banner is never a real institution_notifications row — it's computed
fresh on every GET /api/notifications/active call (see
_holiday_eve_virtual_notification) and merged into that same stackable
list, the same "compute lazily on read" philosophy this codebase uses
everywhere else rather than a scheduled job. `timezone` is a genuinely
new concept here — every other date/time in this app is naive UTC — but
is only actually consulted by that one holiday-eve check today.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.deps import get_current_user, need_inst, require_roles

from core.secrets_encryption import encrypt_secret

from core.email_engine import send_email, verify_smtp_connection

from db import get_db

from core.db_session import db_session

logger = logging.getLogger("ems")

router = APIRouter()

NOTIFICATION_MANAGE_ROLES = ("hr_manager", "hr_admin")

# Same risk category as the AI assistant's Anthropic BYOK key (an
# institution's own third-party credential) — see routers/assistant.py's
# ASSISTANT_SETTINGS_ROLES for the identical reasoning. Deliberately a
# hardcoded require_roles gate, not routed through the permission-matrix
# override system.
EMAIL_SETTINGS_ROLES = ("hr_manager",)


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
# Email notification settings (Phase 1 — BYO-SMTP per institution).
# Registered before the parameterized /api/notifications/{notification_id}
# routes below on purpose — FastAPI/Starlette matches path templates in
# registration order, and {notification_id} would otherwise greedily
# match the literal segment "email-settings" (or "email-log"), 422'ing
# on the int conversion instead of ever reaching these handlers.
# ---------------------------------------------------------------------------
def _validate_email_format(v: str, field_name: str) -> str:
    v = v.strip()
    if not v or "@" not in v or v.startswith("@") or v.endswith("@"):
        raise ValueError(f"{field_name} must be a valid email address")
    return v


class EmailSettingsIn(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool = True
    smtp_from_address: str
    smtp_from_name: Optional[str] = None
    smtp_username: str
    smtp_password: str
    notifications_email_enabled: bool = True

    @field_validator("smtp_host", "smtp_username", "smtp_password")
    @classmethod
    def _not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("This field is required")
        return v

    @field_validator("smtp_from_address")
    @classmethod
    def _valid_from_address(cls, v):
        return _validate_email_format(v, "smtp_from_address")


class EmailSettingsOut(BaseModel):
    configured: bool
    notifications_email_enabled: bool = False
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_use_tls: bool = True
    smtp_from_address: Optional[str] = None
    smtp_from_name: Optional[str] = None
    smtp_configured_at: Optional[str] = None


class TestEmailIn(BaseModel):
    to_email: str

    @field_validator("to_email")
    @classmethod
    def _valid_to_email(cls, v):
        return _validate_email_format(v, "to_email")


_EMAIL_SETTINGS_COLS = (
    "smtp_host, smtp_port, smtp_use_tls, smtp_from_address, smtp_from_name, "
    "smtp_credentials_encrypted, smtp_configured_at, notifications_email_enabled"
)


def _email_settings_response(row) -> EmailSettingsOut:
    if not row:
        return EmailSettingsOut(configured=False)
    return EmailSettingsOut(
        configured=bool(row["smtp_credentials_encrypted"]),
        notifications_email_enabled=bool(row["notifications_email_enabled"]),
        smtp_host=row["smtp_host"], smtp_port=row["smtp_port"], smtp_use_tls=bool(row["smtp_use_tls"]),
        smtp_from_address=row["smtp_from_address"], smtp_from_name=row["smtp_from_name"],
        smtp_configured_at=row["smtp_configured_at"],
    )


@router.get("/api/notifications/email-settings")
@db_session
def get_email_settings(conn, user: dict = Depends(require_roles(*EMAIL_SETTINGS_ROLES))) -> EmailSettingsOut:
    inst_id = need_inst(user)
    row = conn.execute(f"SELECT {_EMAIL_SETTINGS_COLS} FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return _email_settings_response(row)


@router.put("/api/notifications/email-settings")
@db_session
def update_email_settings(
    conn, body: EmailSettingsIn, user: dict = Depends(require_roles(*EMAIL_SETTINGS_ROLES))
) -> EmailSettingsOut:
    """Saves an institution's own SMTP mailbox — validated with a real
    login attempt first (mirrors routers/assistant.py's Anthropic key
    check: catch a typo'd host/password here, not on the first real
    approval email that silently fails)."""
    inst_id = need_inst(user)
    try:
        verify_smtp_connection(body.smtp_host, body.smtp_port, body.smtp_use_tls, body.smtp_username, body.smtp_password)
    except Exception as e:
        logger.warning(f"notification settings: SMTP validation failed for institution {inst_id}: {e}")
        raise HTTPException(400, detail="Couldn't connect/log in with those SMTP details — double-check them and try again.")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    credentials = encrypt_secret(json.dumps({"username": body.smtp_username, "password": body.smtp_password}))
    conn.execute(
        "UPDATE institutions SET smtp_host=?, smtp_port=?, smtp_use_tls=?, smtp_from_address=?, smtp_from_name=?, "
        "smtp_credentials_encrypted=?, smtp_configured_at=?, notifications_email_enabled=? WHERE id=?",
        (body.smtp_host, body.smtp_port, body.smtp_use_tls, body.smtp_from_address, body.smtp_from_name,
         credentials, now, body.notifications_email_enabled, inst_id)
    )
    conn.commit()
    row = conn.execute(f"SELECT {_EMAIL_SETTINGS_COLS} FROM institutions WHERE id=?", (inst_id,)).fetchone()
    return _email_settings_response(row)


@router.delete("/api/notifications/email-settings")
@db_session
def delete_email_settings(conn, user: dict = Depends(require_roles(*EMAIL_SETTINGS_ROLES))) -> EmailSettingsOut:
    """Clears the institution's SMTP config — email notifications simply
    stop going out (no platform-wide fallback sender, unlike the AI
    assistant's Anthropic key, since emails need to come from THIS
    institution's own identity, not a shared one)."""
    inst_id = need_inst(user)
    conn.execute(
        "UPDATE institutions SET smtp_host=NULL, smtp_port=NULL, smtp_from_address=NULL, smtp_from_name=NULL, "
        "smtp_credentials_encrypted=NULL, smtp_configured_at=NULL, notifications_email_enabled=false WHERE id=?",
        (inst_id,)
    )
    conn.commit()
    return EmailSettingsOut(configured=False)


@router.post("/api/notifications/email-settings/test")
@db_session
def send_test_email(conn, body: TestEmailIn, user: dict = Depends(require_roles(*EMAIL_SETTINGS_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    sent = send_email(
        conn, inst_id, body.to_email, "EMS test email",
        "<p>This is a test email from your EMS notification settings. If you're reading this, it works.</p>",
        "test",
    )
    conn.commit()
    if not sent:
        raise HTTPException(400, detail="Couldn't send the test email — check that notifications are enabled and your SMTP settings are correct.")
    return {"sent": True}


@router.get("/api/notifications/email-log")
@db_session
def list_email_log(conn, limit: int = 50, user: dict = Depends(require_roles(*EMAIL_SETTINGS_ROLES))) -> List[Dict[str, Any]]:
    """Recent send attempts (sent/failed/skipped) for this institution —
    the only visibility into core/email_engine.py's best-effort, never-
    raises sends, since a silently-swallowed failure otherwise has no
    other way to surface to HR."""
    inst_id = need_inst(user)
    limit = min(max(1, limit), 200)
    rows = conn.execute(
        "SELECT * FROM email_log WHERE institution_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
        (inst_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Notification general settings (institution timezone + holiday-eve
# announcement toggle) — same early-registration reasoning as the
# email-settings block above: /api/notifications/general-settings would
# otherwise be swallowed by /api/notifications/{notification_id} below.
# ---------------------------------------------------------------------------
class NotificationGeneralSettingsIn(BaseModel):
    timezone: str
    holiday_eve_announcements_enabled: bool = False

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v):
        v = v.strip()
        if v not in available_timezones():
            raise ValueError("Not a recognized IANA timezone name (e.g. 'Asia/Kuala_Lumpur')")
        return v


class NotificationGeneralSettingsOut(BaseModel):
    timezone: str
    holiday_eve_announcements_enabled: bool


@router.get("/api/notifications/general-settings")
@db_session
def get_notification_general_settings(
    conn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))
) -> NotificationGeneralSettingsOut:
    inst_id = need_inst(user)
    row = conn.execute(
        "SELECT timezone, holiday_eve_announcements_enabled FROM institutions WHERE id=?", (inst_id,)
    ).fetchone()
    return NotificationGeneralSettingsOut(
        timezone=row["timezone"], holiday_eve_announcements_enabled=bool(row["holiday_eve_announcements_enabled"])
    )


@router.put("/api/notifications/general-settings")
@db_session
def update_notification_general_settings(
    conn, body: NotificationGeneralSettingsIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))
) -> NotificationGeneralSettingsOut:
    inst_id = need_inst(user)
    conn.execute(
        "UPDATE institutions SET timezone=?, holiday_eve_announcements_enabled=? WHERE id=?",
        (body.timezone, body.holiday_eve_announcements_enabled, inst_id)
    )
    conn.commit()
    row = conn.execute(
        "SELECT timezone, holiday_eve_announcements_enabled FROM institutions WHERE id=?", (inst_id,)
    ).fetchone()
    return NotificationGeneralSettingsOut(
        timezone=row["timezone"], holiday_eve_announcements_enabled=bool(row["holiday_eve_announcements_enabled"])
    )


def _holiday_eve_virtual_notification(conn, inst_id: int) -> Optional[Dict[str, Any]]:
    """A synthetic "notification" for a public holiday exactly one
    calendar day away in the institution's own timezone — computed fresh
    on every call, never a real institution_notifications row. Its `id`
    is a namespaced string ("holiday-eve-<holiday id>"), which can never
    collide with a real row's integer id, so the frontend's existing
    per-id dismiss-key scheme (static/js/notifications.js) works
    unchanged for it — dismissing it today doesn't suppress a *different*
    holiday's eve announcement next month, since each holiday's own id is
    baked into the key."""
    row = conn.execute(
        "SELECT timezone, holiday_eve_announcements_enabled FROM institutions WHERE id=?", (inst_id,)
    ).fetchone()
    if not row or not row["holiday_eve_announcements_enabled"]:
        return None
    try:
        tz = ZoneInfo(row["timezone"] or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    tomorrow = (datetime.now(tz).date() + timedelta(days=1)).isoformat()
    holiday = conn.execute(
        "SELECT id, name FROM holidays WHERE institution_id=? AND date=?", (inst_id, tomorrow)
    ).fetchone()
    if not holiday:
        return None
    return {
        "id": f"holiday-eve-{holiday['id']}",
        "message": f"Reminder: {holiday['name']} is tomorrow ({tomorrow}).",
        "start_time": None, "end_time": None, "is_virtual": True,
    }


# ---------------------------------------------------------------------------
# Institution notifications
# ---------------------------------------------------------------------------
@router.get("/api/notifications")
@db_session
def list_notifications(conn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))) -> List[Dict[str, Any]]:
    inst_id = need_inst(user)
    rows = conn.execute(
        "SELECT * FROM institution_notifications WHERE institution_id=? ORDER BY start_time DESC", (inst_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/notifications/active")
@db_session
def get_active_notifications(conn, user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Every currently-active institution notification (any number can
    overlap — see module docstring), plus the holiday-eve announcement
    when applicable, all in one stackable list."""
    inst_id = user.get("active_institution_id")
    if not inst_id or user["role"] == "superadmin":
        return []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    rows = conn.execute(
        "SELECT * FROM institution_notifications WHERE institution_id=? AND start_time<=? AND end_time>=? "
        "ORDER BY start_time DESC",
        (inst_id, now, now)
    ).fetchall()
    result = [dict(r) for r in rows]
    holiday_eve = _holiday_eve_virtual_notification(conn, inst_id)
    if holiday_eve:
        result.append(holiday_eve)
    return result


@router.post("/api/notifications", status_code=201)
@db_session
def create_notification(conn, body: NotificationIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if body.end_time <= body.start_time:
        raise HTTPException(400, "End time must be after start time")
    conn.execute(
        "INSERT INTO institution_notifications (institution_id,message,start_time,end_time,created_by) VALUES (?,?,?,?,?)",
        (inst_id, body.message, body.start_time, body.end_time, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institution_notifications WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/notifications/{notification_id}")
@db_session
def update_notification(conn, notification_id: int, body: NotificationIn, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    if not conn.execute("SELECT id FROM institution_notifications WHERE id=? AND institution_id=?", (notification_id, inst_id)).fetchone():
        raise HTTPException(404, "Notification not found")
    if body.end_time <= body.start_time:
        raise HTTPException(400, "End time must be after start time")
    conn.execute(
        "UPDATE institution_notifications SET message=?,start_time=?,end_time=? WHERE id=?",
        (body.message, body.start_time, body.end_time, notification_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM institution_notifications WHERE id=?", (notification_id,)).fetchone()
    return dict(row)


@router.delete("/api/notifications/{notification_id}", status_code=204)
@db_session
def delete_notification(conn, notification_id: int, user: dict = Depends(require_roles(*NOTIFICATION_MANAGE_ROLES))) -> None:
    inst_id = need_inst(user)
    conn.execute("DELETE FROM institution_notifications WHERE id=? AND institution_id=?", (notification_id, inst_id))
    conn.commit()


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
@db_session
def list_system_notifications(conn, user: dict = Depends(require_roles("superadmin"))) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM system_notifications ORDER BY start_time DESC").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/system-notifications/active")
@db_session
def get_active_system_notification(conn, user: dict = Depends(get_current_user)) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    row = conn.execute(
        "SELECT * FROM system_notifications WHERE start_time<=? AND end_time>=? ORDER BY start_time DESC LIMIT 1",
        (now, now)
    ).fetchone()
    return dict(row) if row else None


@router.post("/api/system-notifications", status_code=201)
@db_session
def create_system_notification(conn, body: NotificationIn, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    if body.end_time <= body.start_time:
        raise HTTPException(400, "End time must be after start time")
    if _system_notification_overlaps(conn, body.start_time, body.end_time):
        raise HTTPException(400, "Another system notification is already active/scheduled during this window")
    conn.execute(
        "INSERT INTO system_notifications (message,start_time,end_time,created_by) VALUES (?,?,?,?)",
        (body.message, body.start_time, body.end_time, user["username"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM system_notifications WHERE id=last_insert_rowid()").fetchone()
    return dict(row)


@router.put("/api/system-notifications/{notification_id}")
@db_session
def update_system_notification(conn, notification_id: int, body: NotificationIn, user: dict = Depends(require_roles("superadmin"))) -> Dict[str, Any]:
    if not conn.execute("SELECT id FROM system_notifications WHERE id=?", (notification_id,)).fetchone():
        raise HTTPException(404, "Notification not found")
    if body.end_time <= body.start_time:
        raise HTTPException(400, "End time must be after start time")
    if _system_notification_overlaps(conn, body.start_time, body.end_time, exclude_id=notification_id):
        raise HTTPException(400, "Another system notification is already active/scheduled during this window")
    conn.execute(
        "UPDATE system_notifications SET message=?,start_time=?,end_time=? WHERE id=?",
        (body.message, body.start_time, body.end_time, notification_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM system_notifications WHERE id=?", (notification_id,)).fetchone()
    return dict(row)


@router.delete("/api/system-notifications/{notification_id}", status_code=204)
@db_session
def delete_system_notification(conn, notification_id: int, user: dict = Depends(require_roles("superadmin"))) -> None:
    conn.execute("DELETE FROM system_notifications WHERE id=?", (notification_id,))
    conn.commit()

