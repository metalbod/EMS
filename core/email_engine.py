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


def _log(conn, inst_id, module, category, recipient_email, subject, status, error=None):
    try:
        conn.execute(
            "INSERT INTO email_log (institution_id,module,category,recipient_email,subject,status,error) "
            "VALUES (?,?,?,?,?,?,?)",
            (inst_id, module, category, recipient_email, subject, status, error)
        )
    except Exception:
        logger.exception("email_engine: failed to write email_log row")


def send_email(conn, inst_id: int, to_email: str, subject: str, html_body: str,
               category: str, module: Optional[str] = None) -> bool:
    """Best-effort send — returns True/False for callers that want to know,
    but NEVER raises. No-ops (logged as 'skipped') if the institution has
    email notifications disabled, has no SMTP configured, or `to_email`
    is empty/obviously invalid."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        _log(conn, inst_id, module, category, to_email or "(none)", subject, "skipped", "no usable recipient address")
        return False

    settings = _smtp_settings(conn, inst_id)
    if not settings:
        _log(conn, inst_id, module, category, to_email, subject, "skipped", "email notifications disabled or not configured")
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

        _log(conn, inst_id, module, category, to_email, subject, "sent")
        return True
    except Exception as e:
        logger.warning(f"email_engine: send failed for institution {inst_id} category {category}: {e}")
        _log(conn, inst_id, module, category, to_email, subject, "failed", str(e))
        return False


def verify_smtp_connection(host: str, port: int, use_tls: bool, username: str, password: str) -> None:
    """Raises on failure — used by the settings endpoint to validate
    credentials at save time (same "catch the typo here, not on the next
    real send" philosophy as routers/assistant.py's Anthropic key check)."""
    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        server.login(username, password)
