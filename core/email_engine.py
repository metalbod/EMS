"""Email sending engine — Phase 1 of the notification system (see
migrations/versions/20260919_0001_email_notifications.py). Each
institution configures its own SMTP mailbox (BYO-SMTP — same
encrypted-credential pattern as the AI assistant's Anthropic BYOK key,
see core/secrets_encryption.py) rather than a shared platform sender, so
emails come from that company's own domain/identity, not "EMS Platform."

Two entry points: send_email() sends synchronously and tells the caller how
it went; queue_email() (bottom of this file) defers the send until the
caller's transaction commits and runs it in the background — used for approval
notifications so a user's click doesn't wait on the mail server.

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
import contextvars
import json
import logging
import os
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from core.secrets_encryption import decrypt_secret
from db import get_db, set_rls_context

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


def _deliver(conn, inst_id: int, messages: List[dict]) -> List[bool]:
    """Delivers `messages` — dicts with to/subject/html/category/module/
    dedupe_key/cc — over ONE SMTP session (connect, TLS and login once, then
    one sendmail per message) and writes an email_log row for each. Never
    raises. Returns a per-message success list. The log rows are inserted on
    `conn` and not committed here (see the module docstring)."""
    results = [False] * len(messages)
    todo = []  # (index, to_email) for messages that have a usable recipient
    for n, m in enumerate(messages):
        to = (m["to"] or "").strip()
        if not to or "@" not in to:
            _log(conn, inst_id, m.get("module"), m["category"], to or "(none)", m["subject"], "skipped",
                 "no usable recipient address", m.get("dedupe_key"))
        else:
            todo.append((n, to))
    if not todo:
        return results

    settings = _smtp_settings(conn, inst_id)
    if not settings:
        for n, to in todo:
            m = messages[n]
            _log(conn, inst_id, m.get("module"), m["category"], to, m["subject"], "skipped",
                 "email notifications disabled or not configured", m.get("dedupe_key"))
        return results

    sender = f'{settings["from_name"]} <{settings["from_address"]}>' if settings["from_name"] else settings["from_address"]
    logged = set()  # indices that already have their sent/failed log row
    try:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=10) as server:
            if settings["use_tls"]:
                server.starttls()
            server.login(settings["username"], settings["password"])
            for n, to in todo:
                m = messages[n]
                try:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = m["subject"]
                    msg["From"] = sender
                    msg["To"] = to
                    recipients = [to]
                    cc = (m.get("cc") or "").strip()
                    if cc and "@" in cc and cc.lower() != to.lower():
                        msg["Cc"] = cc
                        recipients.append(cc)
                    msg.attach(MIMEText(m["html"], "html"))
                    server.sendmail(settings["from_address"], recipients, msg.as_string())
                    results[n] = True
                    logged.add(n)
                    _log(conn, inst_id, m.get("module"), m["category"], to, m["subject"], "sent",
                         dedupe_key=m.get("dedupe_key"))
                except Exception as e:
                    logger.warning(f"email_engine: send failed for institution {inst_id} category {m['category']}: {e}")
                    logged.add(n)
                    _log(conn, inst_id, m.get("module"), m["category"], to, m["subject"], "failed", str(e), m.get("dedupe_key"))
    except Exception as e:
        # Couldn't connect / start TLS / log in: nothing was sent, so every
        # message without a log row yet fails with this error.
        logger.warning(f"email_engine: send failed for institution {inst_id}: {e}")
        for n, to in todo:
            if n not in logged:
                m = messages[n]
                _log(conn, inst_id, m.get("module"), m["category"], to, m["subject"], "failed", str(e), m.get("dedupe_key"))
    return results


def send_email(conn, inst_id: int, to_email: str, subject: str, html_body: str,
               category: str, module: Optional[str] = None, dedupe_key: Optional[str] = None,
               cc: Optional[str] = None) -> bool:
    """Best-effort, SYNCHRONOUS send — returns True/False for callers that
    want to know, but NEVER raises. No-ops (logged as 'skipped') if the
    institution has email notifications disabled, has no SMTP configured, or
    `to_email` is empty/obviously invalid. `dedupe_key` identifies the
    specific item this email is about (e.g. 'item:123') for callers that need
    to check "have I already sent this" before calling — see
    scripts/send_reminders.py. `cc` adds one visible Cc recipient (same SMTP
    transaction, so a failure to reach either address fails the whole send).

    Use queue_email() instead when the caller must not wait for the mail
    server (approval notifications)."""
    return _deliver(conn, inst_id, [{
        "to": to_email, "subject": subject, "html": html_body, "category": category,
        "module": module, "dedupe_key": dedupe_key, "cc": cc,
    }])[0]


# ---------------------------------------------------------------------------
# Deferred sending — approval notifications.
#
# Talking to the mail server costs ~3 s per email (a fresh connection, TLS and
# login each time), and an approval step can notify several people, so doing it
# inside the request made "Resign" / "Approve" take several seconds. queue_email()
# only remembers the message on the request's connection; the moment that
# connection COMMITS (never on a rollback, so an email can't announce a change
# that didn't persist) the whole batch is handed to a small background pool,
# which sends it over a single SMTP session on its own DB connection and writes
# the email_log rows there. A failure there is logged, never shown to the user.
#
# EMAIL_DISPATCH=inline runs the batch right in the committing thread instead
# (tests set this so they can assert on email_log straight after the request).
# ---------------------------------------------------------------------------
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ems-email")


def queue_email(conn, inst_id: int, to_email: str, subject: str, html_body: str,
                category: str, module: Optional[str] = None, dedupe_key: Optional[str] = None,
                cc: Optional[str] = None) -> None:
    queue = getattr(conn, "_queued_emails", None)
    if queue is None:
        queue = conn._queued_emails = {}
        # One hook per connection; it drains whatever is queued at commit time.
        conn.after_commit(lambda: _flush_queued_emails(conn))
    queue.setdefault(inst_id, []).append({
        "to": to_email, "subject": subject, "html": html_body, "category": category,
        "module": module, "dedupe_key": dedupe_key, "cc": cc,
    })


def _flush_queued_emails(conn) -> None:
    queue, conn._queued_emails = getattr(conn, "_queued_emails", None) or {}, None
    for inst_id, messages in queue.items():
        # copy_context(): the sender sets its own RLS context, which must not
        # leak into the request that is still running (inline mode) — and a pool
        # thread otherwise starts with none.
        ctx = contextvars.copy_context()
        if os.environ.get("EMAIL_DISPATCH") == "inline":
            ctx.run(_send_queued, inst_id, messages)
        else:
            _executor.submit(ctx.run, _send_queued, inst_id, messages)


def _send_queued(inst_id: int, messages: List[dict]) -> None:
    try:
        set_rls_context(inst_id, False)
        conn = get_db()
        try:
            _deliver(conn, inst_id, messages)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("email_engine: background send failed for institution %s", inst_id)


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
