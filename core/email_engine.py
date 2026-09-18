"""Email sending engine — Phase 1 of the notification system (see
migrations/versions/20260919_0001_email_notifications.py). Each
institution configures its own SMTP mailbox (BYO-SMTP — same
encrypted-credential pattern as the AI assistant's Anthropic BYOK key,
see core/secrets_encryption.py) rather than a shared platform sender, so
emails come from that company's own domain/identity, not "EMS Platform."

send_email() never raises: an SMTP failure (bad credentials, server
down, network blip, malformed recipient) must never break the
approval/application action that triggered it — every caller treats
this as a best-effort side effect, same philosophy as this codebase's
existing task_tracking inserts. Every attempt (sent, failed, or skipped
— disabled, unconfigured, no usable recipient) is recorded in email_log
for debugging; that INSERT is deliberately not committed here (mirrors
_log_leave/_log_timesheet's own audit-log helpers) — it rides the
caller's own eventual commit, so a log row only persists if whatever
triggered it does too.
"""
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from core.secrets_encryption import decrypt_secret

logger = logging.getLogger("ems")


def _smtp_settings(conn, inst_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT smtp_host, smtp_port, smtp_use_tls, smtp_from_address, smtp_from_name, "
        "smtp_credentials_encrypted, notifications_email_enabled FROM institutions WHERE id=?",
        (inst_id,)
    ).fetchone()
    if not row or not row["notifications_email_enabled"]:
        return None
    if not (row["smtp_host"] and row["smtp_port"] and row["smtp_from_address"] and row["smtp_credentials_encrypted"]):
        return None
    try:
        creds = json.loads(decrypt_secret(row["smtp_credentials_encrypted"]))
    except ValueError:
        return None
    return {
        "host": row["smtp_host"], "port": row["smtp_port"], "use_tls": bool(row["smtp_use_tls"]),
        "from_address": row["smtp_from_address"], "from_name": row["smtp_from_name"],
        "username": creds["username"], "password": creds["password"],
    }


def _log(conn, inst_id, module, category, recipient_email, subject, status, error=None, dedupe_key=None):
    try:
        conn.execute(
            "INSERT INTO email_log (institution_id,module,category,recipient_email,subject,status,error,dedupe_key) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (inst_id, module, category, recipient_email, subject, status, error, dedupe_key)
        )
    except Exception:
        logger.exception("email_engine: failed to write email_log row")


def send_email(conn, inst_id: int, to_email: str, subject: str, html_body: str,
               category: str, module: Optional[str] = None, dedupe_key: Optional[str] = None) -> bool:
    """Best-effort send — returns True/False for callers that want to know,
    but NEVER raises. No-ops (logged as 'skipped') if the institution has
    email notifications disabled, has no SMTP configured, or `to_email`
    is empty/obviously invalid. `dedupe_key` identifies the specific item
    this email is about (e.g. 'item:123') for callers that need to check
    "have I already sent this" before calling — see
    scripts/send_reminders.py; Phase 1's approval-workflow emails leave
    it unset, since each of those is inherently a one-shot event."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        _log(conn, inst_id, module, category, to_email or "(none)", subject, "skipped", "no usable recipient address", dedupe_key)
        return False

    settings = _smtp_settings(conn, inst_id)
    if not settings:
        _log(conn, inst_id, module, category, to_email, subject, "skipped", "email notifications disabled or not configured", dedupe_key)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f'{settings["from_name"]} <{settings["from_address"]}>' if settings["from_name"] else settings["from_address"]
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings["host"], settings["port"], timeout=10) as server:
            if settings["use_tls"]:
                server.starttls()
            server.login(settings["username"], settings["password"])
            server.sendmail(settings["from_address"], [to_email], msg.as_string())

        _log(conn, inst_id, module, category, to_email, subject, "sent", dedupe_key=dedupe_key)
        return True
    except Exception as e:
        logger.warning(f"email_engine: send failed for institution {inst_id} category {category}: {e}")
        _log(conn, inst_id, module, category, to_email, subject, "failed", str(e), dedupe_key)
        return False


def already_sent_recently(conn, inst_id: int, category: str, dedupe_key: str, cooldown_days: float) -> bool:
    """Whether a 'sent' email_log row already exists for this exact
    (institution, category, dedupe_key) within the last `cooldown_days`
    — the dedupe check scripts/send_reminders.py uses before sending a
    reminder, so the same overdue item/missed period isn't re-emailed
    every time the sweep runs. cooldown_days=0 means "ever" (never
    re-send at all, e.g. a missed-timesheet-period reminder)."""
    cutoff = _cooldown_cutoff(cooldown_days)
    row = conn.execute(
        "SELECT 1 FROM email_log WHERE institution_id=? AND category=? AND dedupe_key=? "
        "AND status='sent' AND created_at >= ? LIMIT 1",
        (inst_id, category, dedupe_key, cutoff)
    ).fetchone()
    return row is not None


def _cooldown_cutoff(cooldown_days: float) -> str:
    from datetime import datetime, timedelta, timezone
    if cooldown_days <= 0:
        return "0000-01-01 00:00:00"
    return (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).strftime("%Y-%m-%d %H:%M:%S")


def verify_smtp_connection(host: str, port: int, use_tls: bool, username: str, password: str) -> None:
    """Raises on failure — used by the settings endpoint to validate
    credentials at save time (same "catch the typo here, not on the next
    real send" philosophy as routers/assistant.py's Anthropic key check)."""
    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        server.login(username, password)
