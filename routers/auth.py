"""
Auth routes: login, role switching, current-user lookup.

Login rate limiting — in-memory sliding window. This is intentionally
process-local (no Redis/shared store): the app currently runs as a single
uvicorn worker/machine, so this is a real backstop against brute-forcing a
single username, not just decoration. If this ever runs as multiple
workers/machines, move this to a shared store or it silently stops working
per-instance.
"""
import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.deps import (
    MIN_PASSWORD_LENGTH, build_current_user_out, get_current_user, hash_password, make_token,
    verify_password, verify_password_or_dummy,
)
from core.schemas import CurrentUserOut, TokenResponse

from db import get_db

from core.db_session import db_session

router = APIRouter()
logger = logging.getLogger("ems")


class LoginIn(BaseModel):
    username: str
    password: str
    institution_code: Optional[str] = None  # required for institution users, blank for superadmin


class SwitchRoleIn(BaseModel):
    role: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes
_login_failures: dict = defaultdict(deque)


def _login_rate_key(request: Request, username: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{username.strip().lower()}"


def _check_login_rate_limit(key: str):
    now = time.monotonic()
    attempts = _login_failures[key]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        retry_after = max(1, int(LOGIN_WINDOW_SECONDS - (now - attempts[0])))
        raise HTTPException(429, f"Too many failed login attempts. Try again in {retry_after} seconds.")


def _record_login_failure(key: str):
    _login_failures[key].append(time.monotonic())
    logger.warning("Failed login attempt for %s (%d in window)", key, len(_login_failures[key]))


def _clear_login_failures(key: str):
    _login_failures.pop(key, None)


def _record_login_audit(conn, request: Request, institution_id, username: str, user_id, success: bool, reason: str = None):
    """Persists one login attempt (success or failure) to login_audit_log —
    the in-app-visible counterpart to _record_login_failure's process-local
    logger.warning, see GET /api/login-audit-log. Best-effort: a failure
    here must never block or fail the login itself, so any error is logged
    and swallowed rather than propagated."""
    try:
        ip = request.client.host if request.client else None
        conn.execute(
            "INSERT INTO login_audit_log (institution_id, username, user_id, success, reason, ip_address) "
            "VALUES (?,?,?,?,?,?)",
            (institution_id, username, user_id, success, reason, ip)
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to record login audit entry for %s", username)


@router.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
@db_session
def login(conn, body: LoginIn, request: Request) -> dict:
    rate_key = _login_rate_key(request, body.username)
    _check_login_rate_limit(rate_key)

    code = body.institution_code.strip().upper() if body.institution_code and body.institution_code.strip() else None

    user = None
    inst = None
    if code:
        # Institution user: look up institution first, then find user scoped to it
        inst_row = conn.execute(
            "SELECT id, name, code, status, logo_url FROM institutions WHERE code=?", (code,)
        ).fetchone()
        inst = inst_row
        if inst_row:
            user = conn.execute(
                "SELECT * FROM users WHERE username=? AND institution_id=?",
                (body.username, inst_row["id"])
            ).fetchone()
    else:
        # Superadmin or platform-level login (no institution)
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND institution_id IS NULL", (body.username,)
        ).fetchone()

    # verify_password_or_dummy runs a real bcrypt comparison even when
    # `user` is None (bad company code or unknown username) — see its own
    # docstring. Calling it unconditionally, before branching on whether
    # `user` exists, is what actually closes the timing gap: a bad
    # username and a bad password now cost the same regardless of which
    # branch above produced `user`.
    password_ok = verify_password_or_dummy(body.password, user["password_hash"] if user else None)
    if not user or not password_ok:
        _record_login_failure(rate_key)
        _record_login_audit(conn, request, inst["id"] if inst else None, body.username, user["id"] if user else None, False, "invalid_credentials")
        raise HTTPException(401, "Invalid company code, username or password")
    if not user["is_active"]:
        _record_login_audit(conn, request, inst["id"] if inst else None, body.username, user["id"], False, "inactive")
        raise HTTPException(403, "Account is deactivated")
    if inst and inst["status"] != "Active":
        _record_login_audit(conn, request, inst["id"], body.username, user["id"], False, "institution_suspended")
        raise HTTPException(403, "Your company account has been suspended. Please contact platform support.")
    _clear_login_failures(rate_key)
    _record_login_audit(conn, request, inst["id"] if inst else None, body.username, user["id"], True)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET last_login=?, last_active=? WHERE id=?", (now, now, user["id"]))
    conn.commit()
    token = make_token(dict(user))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": build_current_user_out(conn, dict(user)),
    }


@router.post("/api/auth/switch-role", response_model=TokenResponse, tags=["auth"])
@db_session
def switch_role(conn, body: SwitchRoleIn, user: dict = Depends(get_current_user)) -> dict:
    row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    allowed = [r.strip() for r in (row["roles"] or row["role"]).split(",") if r.strip()]
    if body.role not in allowed:
        raise HTTPException(403, f"Role '{body.role}' is not assigned to this user")
    user_dict = dict(row)
    user_dict["role"] = body.role
    token = make_token(user_dict)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": build_current_user_out(conn, dict(row), role_override=body.role),
    }


@router.get("/api/auth/me", response_model=CurrentUserOut)
@db_session
def me(conn, user: dict = Depends(get_current_user)) -> CurrentUserOut:
    # Session-restore path (called on every page refresh) — build_current_user_out
    # is the same builder /login and /switch-role use, so this can't drift into
    # its own shape again (see CurrentUserOut's docstring for the two real bugs
    # that drift caused: a crash on every F5, and institution branding silently
    # reverting to the default on refresh).
    return build_current_user_out(conn, user)


@router.post("/api/auth/change-password", response_model=TokenResponse, tags=["auth"])
@db_session
def change_password(conn, body: ChangePasswordIn, user: dict = Depends(get_current_user)) -> dict:
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"New password must be at least {MIN_PASSWORD_LENGTH} characters")
    # token_epoch=token_epoch+1 invalidates every token issued before this
    # change — including, deliberately, the one making this very request —
    # so a stolen token can't keep working past a password change someone
    # made specifically because they suspected it was compromised. The
    # response mints and returns a fresh token on the new epoch so the
    # caller's own session continues seamlessly instead of being logged
    # out by its own next request.
    conn.execute(
        "UPDATE users SET password_hash=?, must_change_password=0, token_epoch=token_epoch+1 WHERE id=?",
        (hash_password(body.new_password), user["id"])
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return {
        "access_token": make_token(dict(updated)),
        "token_type": "bearer",
        "user": build_current_user_out(conn, dict(updated)),
    }
