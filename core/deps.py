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
import asyncio
import os
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    from db import get_db, set_rls_context
except ImportError:
    from ems.db import get_db, set_rls_context

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


def _load_current_user_row(user_id) -> dict | None:
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, username, full_name, role, roles, department, employee_id, is_active, institution_id, "
            "must_change_password FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user or not user["is_active"]:
            return None
        u = dict(user)
        # users.department is a denormalized copy that can drift out of sync
        # with (or never be set from) the linked employee record.
        # Manager-scoped queries throughout the app rely on this field, so
        # always derive it fresh from employees rather than trusting the
        # possibly-stale column.
        if u.get("employee_id") and u.get("institution_id"):
            emp = conn.execute(
                "SELECT department FROM employees WHERE institution_id=? AND employee_id=?",
                (u["institution_id"], u["employee_id"])
            ).fetchone()
            if emp and emp["department"]:
                u["department"] = emp["department"]
        return u
    finally:
        conn.close()


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    # Deliberately async, not a plain sync `def`: FastAPI runs sync
    # dependencies via a threadpool (anyio.to_thread.run_sync), and a
    # contextvars.ContextVar.set() made inside that threadpool call does
    # NOT propagate back out to the request's own async context — verified
    # empirically, this silently broke set_rls_context() below (every
    # subsequent get_db() call in the request saw the default/unset
    # context, not what this function computed). An async def runs
    # directly on the request's own asyncio Task, so a .set() here
    # actually mutates the live context that later threadpool calls (e.g.
    # a sync endpoint body's own get_db() calls) copy from. The blocking DB
    # work itself is still offloaded via asyncio.to_thread so it doesn't
    # stall the event loop for other concurrent requests — only the final
    # set_rls_context() call runs directly in this function's own live
    # context, after the thread's result comes back.
    if not creds:
        raise HTTPException(401, "Authentication required")
    payload = decode_token(creds.credentials)
    u = await asyncio.to_thread(_load_current_user_row, payload["sub"])
    if u is None:
        raise HTTPException(401, "User not found or inactive")
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
    # Scope this request's DB queries to active_institution_id at the
    # Postgres level (see db.py's RLS context) — defense-in-depth against
    # an endpoint's own query forgetting a WHERE institution_id filter.
    #
    # bypass=True for EVERY superadmin request, regardless of whether
    # X-Institution-Id is set: that header is a convenience filter superadmin's
    # own endpoints optionally read to narrow a query (e.g. "list this one
    # institution's users"), not a security boundary — superadmin is already
    # legitimately cross-institution throughout this app (creating new
    # institutions, auditing across tenants, etc.), and scoping it at the DB
    # level too broke exactly that: creating a brand-new institution while
    # "scoped" to an existing one failed RLS's INSERT check, since the new
    # row's own id could never match the header's institution_id. Every
    # non-superadmin (tenant) user IS scoped — that's the actual risk this
    # policy defends against (a regular user's endpoint forgetting its own
    # WHERE institution_id filter).
    bypass = u["role"] == "superadmin"
    set_rls_context(u["active_institution_id"], bypass_rls=bypass)
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
