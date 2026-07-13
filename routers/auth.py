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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

try:
    from core.deps import get_current_user, make_token, verify_password
except ImportError:
    from ems.core.deps import get_current_user, make_token, verify_password

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

router = APIRouter()
logger = logging.getLogger("ems")


class LoginIn(BaseModel):
    username: str
    password: str
    institution_code: Optional[str] = None  # required for institution users, blank for superadmin


class SwitchRoleIn(BaseModel):
    role: str


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


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    rate_key = _login_rate_key(request, body.username)
    _check_login_rate_limit(rate_key)

    conn = get_db()
    code = body.institution_code.strip().upper() if body.institution_code and body.institution_code.strip() else None

    if code:
        # Institution user: look up institution first, then find user scoped to it
        inst_row = conn.execute(
            "SELECT id, name, code, status, logo_url FROM institutions WHERE code=?", (code,)
        ).fetchone()
        if not inst_row:
            conn.close()
            _record_login_failure(rate_key)
            raise HTTPException(401, "Invalid company code, username or password")
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND institution_id=?",
            (body.username, inst_row["id"])
        ).fetchone()
        inst = inst_row
    else:
        # Superadmin or platform-level login (no institution)
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND institution_id IS NULL", (body.username,)
        ).fetchone()
        inst = None

    conn.close()
    if not user or not verify_password(body.password, user["password_hash"]):
        _record_login_failure(rate_key)
        raise HTTPException(401, "Invalid company code, username or password")
    if not user["is_active"]:
        raise HTTPException(403, "Account is deactivated")
    if inst and inst["status"] != "Active":
        raise HTTPException(403, "Your company account has been suspended. Please contact platform support.")
    _clear_login_failures(rate_key)
    token = make_token(dict(user))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "roles": [r.strip() for r in (user["roles"] or user["role"]).split(",") if r.strip()],
            "institution_id": user["institution_id"],
            "department": user["department"],
            "employee_id": user["employee_id"],
            "institution": dict(inst) if inst else None,
            "must_change_password": bool(user["must_change_password"]),
        }
    }


@router.post("/api/auth/switch-role")
def switch_role(body: SwitchRoleIn, user: dict = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")
    allowed = [r.strip() for r in (row["roles"] or row["role"]).split(",") if r.strip()]
    if body.role not in allowed:
        conn.close()
        raise HTTPException(403, f"Role '{body.role}' is not assigned to this user")
    inst_row = conn.execute(
        "SELECT id, name, code, status, logo_url FROM institutions WHERE id=?", (row["institution_id"],)
    ).fetchone() if row["institution_id"] else None
    conn.close()
    user_dict = dict(row)
    user_dict["role"] = body.role
    token = make_token(user_dict)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": row["id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": body.role,
            "roles": allowed,
            "institution_id": row["institution_id"],
            "department": row["department"],
            "employee_id": row["employee_id"],
            "institution": dict(inst_row) if inst_row else None,
        }
    }


@router.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return user
