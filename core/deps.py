"""
Shared FastAPI dependencies: authentication, role/tenant scoping, and the
JWT_SECRET fail-fast check. Every router imports from here rather than from
main.py, so routers can be added without circular imports (main.py mounts
routers; routers must not import from main.py).

This is the first extraction out of main.py's monolith — see the repo's
tech-debt notes. Routers are being split out one at a time, starting with
the smallest/lowest-risk ones, verifying tests pass after each step rather
than doing one large risky rewrite.
"""
import os
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET environment variable is not set. A random secret is deliberately "
        "NOT generated as a fallback — that would silently invalidate all sessions on "
        "every restart, and break auth entirely across multiple worker processes/machines "
        "(each would mint a different secret). Set JWT_SECRET explicitly (see .env.example)."
    )
JWT_ALG = "HS256"
JWT_HOURS = 8

bearer = HTTPBearer(auto_error=False)


def hash_password(p):
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p, h):
    return bcrypt.checkpw(p.encode(), h.encode())


def make_token(user: dict) -> str:
    return jwt.encode({
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"],
        "institution_id": user.get("institution_id"),
        "department": user.get("department"),
        "employee_id": user["employee_id"] if "employee_id" in user else None,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_HOURS),
    }, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(401, "Authentication required")
    payload = decode_token(creds.credentials)
    conn = get_db()
    user = conn.execute(
        "SELECT id, username, full_name, role, roles, department, employee_id, is_active, institution_id "
        "FROM users WHERE id = ?", (payload["sub"],)
    ).fetchone()
    conn.close()
    if not user or not user["is_active"]:
        raise HTTPException(401, "User not found or inactive")
    u = dict(user)
    # users.department is a denormalized copy that can drift out of sync with
    # (or never be set from) the linked employee record. Manager-scoped
    # queries throughout the app rely on this field, so always derive it
    # fresh from employees rather than trusting the possibly-stale column.
    if u.get("employee_id") and u.get("institution_id"):
        conn2 = get_db()
        emp = conn2.execute(
            "SELECT department FROM employees WHERE institution_id=? AND employee_id=?",
            (u["institution_id"], u["employee_id"])
        ).fetchone()
        conn2.close()
        if emp and emp["department"]:
            u["department"] = emp["department"]
    # Honor a switched role from the token (see /auth/switch-role) — the DB's
    # `role` column only holds the primary role, so without this a multi-role
    # user's active-role switch would silently revert on every request.
    token_role = payload.get("role")
    if token_role and token_role != u["role"]:
        allowed = [r.strip() for r in (u.get("roles") or u["role"]).split(",") if r.strip()]
        if token_role in allowed:
            u["role"] = token_role
    # Superadmin can switch institution context via X-Institution-Id header
    if u["role"] == "superadmin":
        hdr = request.headers.get("X-Institution-Id")
        u["active_institution_id"] = int(hdr) if hdr else None
    else:
        u["active_institution_id"] = u["institution_id"]
    return u


def require_roles(*allowed: str):
    def dep(user: dict = Depends(get_current_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return dep


def need_inst(user: dict) -> int:
    """Return active_institution_id or raise 400."""
    iid = user.get("active_institution_id")
    if iid is None:
        raise HTTPException(400, "Select an institution context first")
    return iid
