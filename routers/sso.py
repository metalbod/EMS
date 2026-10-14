"""Sign in with Microsoft (Entra ID) — see core/sso.py for the protocol steps and the SSO plan in CLAUDE.md.

Each company brings its own Entra app registration (tenant id, client id, client secret), saved on Settings → Single
Sign-On and stored encrypted. Sign-in is the OpenID Connect authorization-code flow with PKCE:

  login screen --/api/auth/sso/start--> Microsoft --/api/auth/sso/callback--> EMS --?sso_code=--> login screen
  --POST /api/auth/sso/exchange--> EMS token (the same token a password login issues)

The browser never sees the EMS token in a URL: the callback hands it a one-time code (valid 60 s) which the page trades
for the token. Nobody is created by signing in: a Microsoft account must match an existing EMS user (by email, first time),
after which it is linked by Entra's permanent ids (tenant id + object id). The pre-login endpoints below run with the
default (bypass) RLS context, like the password login.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from core import sso
from core.audit import write_entity_audit
from core.db_session import db_session
from core.deps import build_current_user_out, get_current_user, make_token, need_inst, require_roles
from core.permission_matrix import require_permission
from core.secrets_encryption import decrypt_secret, encrypt_secret
from routers.auth import _check_login_rate_limit, _record_login_audit, _record_login_failure

logger = logging.getLogger("ems")
router = APIRouter()

SETTINGS_ROLES = ("hr_manager", "superadmin")


def _now(delta_seconds: int = 0) -> str:
    return (datetime.utcnow() + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def _base_url(request: Request) -> str:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _redirect_uri(request: Request) -> str:
    return f"{_base_url(request)}/api/auth/sso/callback"


def _go(request: Request, path_and_query: str) -> RedirectResponse:
    return RedirectResponse(url=path_and_query, status_code=302)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _sso_row(conn, inst_id: int):
    return conn.execute("SELECT * FROM institution_sso WHERE institution_id=?", (inst_id,)).fetchone()


def _begin(conn, request: Request, inst_id: int, row, mode: str, started_by: Optional[str]) -> str:
    """Create the single-use 'state' record and return the Microsoft authorize URL."""
    state, nonce = sso.new_token(), sso.new_token()
    verifier, challenge = sso.pkce_pair()
    redirect_uri = _redirect_uri(request)
    conn.execute("DELETE FROM sso_pending WHERE expires_at < ?", (_now(-86400),))
    conn.execute(
        "INSERT INTO sso_pending (institution_id,kind,token_hash,mode,nonce,code_verifier,redirect_uri,started_by,expires_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (inst_id, "state", sso.hash_token(state), mode, nonce, verifier, redirect_uri, started_by, _now(sso.PENDING_TTL_SECONDS)))
    conn.commit()
    return sso.build_authorize_url(row["tenant_id"], row["client_id"], redirect_uri, state, nonce, challenge)


# ---------------------------------------------------------------------------
# Login screen (no session yet)
# ---------------------------------------------------------------------------
@router.get("/api/auth/sso/options", tags=["auth"])
@db_session
def sso_options(conn, institution_code: Optional[str] = None) -> Dict[str, Any]:
    """Whether the company with this code offers 'Sign in with Microsoft'. False for an unknown code too, so it
    doesn't reveal which codes exist."""
    code = (institution_code or "").strip().upper()
    if not code:
        return {"sso_enabled": False}
    row = conn.execute(
        "SELECT s.enabled FROM institution_sso s JOIN institutions i ON i.id=s.institution_id WHERE i.code=? AND i.status='Active'",
        (code,)).fetchone()
    return {"sso_enabled": bool(row and row["enabled"])}


@router.get("/api/auth/sso/start", tags=["auth"])
@db_session
def sso_start(conn, request: Request, institution_code: str = ""):
    inst = conn.execute("SELECT id, status FROM institutions WHERE code=?", ((institution_code or "").strip().upper(),)).fetchone()
    row = _sso_row(conn, inst["id"]) if inst else None
    if not inst or inst["status"] != "Active" or not row or not row["enabled"]:
        return _go(request, "/?sso_error=not_enabled")
    return _go(request, _begin(conn, request, inst["id"], row, "login", None))


def _fail(conn, request, inst_id, username, user_id, reason, redirect_code, mode, started_by=None, detail=""):
    """Log a failed Microsoft sign-in and send the person back with a short code. A failed *test* is recorded on the
    settings row instead (that is what the SSO page shows)."""
    if mode == "test":
        conn.execute("UPDATE institution_sso SET last_test_at=?, last_test_ok=0, last_test_detail=? WHERE institution_id=?",
                     (_now(), (detail or reason)[:300], inst_id))
        conn.commit()
        return _go(request, "/#settings-sso")
    _record_login_audit(conn, request, inst_id, username or "(microsoft)", user_id, False, reason)
    return _go(request, f"/?sso_error={redirect_code}")


def _resolve_user(conn, inst_id: int, claims: Dict[str, Any]):
    """The EMS user this Microsoft identity is. Returns (user, how, problem): problem is None, 'no_account' or 'ambiguous'.
    A linked identity wins; otherwise exactly one EMS user whose email (or whose employee record's work email) matches
    one of the account's addresses, and who isn't already linked to some other Microsoft account."""
    tid, oid = claims["tid"], claims["oid"]
    linked = conn.execute("SELECT * FROM users WHERE institution_id=? AND sso_oid=? AND sso_tenant_id=?", (inst_id, oid, tid)).fetchone()
    if linked:
        return linked, "linked", None
    emails = sso.candidate_emails(claims)
    if not emails:
        return None, None, "no_account"
    marks = ",".join("?" * len(emails))
    ids = {r["id"] for r in conn.execute(
        f"""SELECT u.id FROM users u
            LEFT JOIN employees e ON e.employee_id=u.employee_id AND e.institution_id=u.institution_id
            WHERE u.institution_id=? AND u.sso_oid IS NULL AND (LOWER(u.email) IN ({marks}) OR LOWER(e.work_email) IN ({marks}))""",
        [inst_id, *emails, *emails]).fetchall()}
    if not ids:
        return None, None, "no_account"
    if len(ids) > 1:
        return None, None, "ambiguous"
    return conn.execute("SELECT * FROM users WHERE id=?", (next(iter(ids)),)).fetchone(), "email", None


@router.get("/api/auth/sso/callback", tags=["auth"])
@db_session
def sso_callback(conn, request: Request, code: Optional[str] = None, state: Optional[str] = None,
                 error: Optional[str] = None, error_description: Optional[str] = None):
    rate_key = f"sso:{_ip(request)}"
    try:
        _check_login_rate_limit(rate_key)
    except HTTPException:
        return _go(request, "/?sso_error=failed")
    pend = conn.execute("SELECT * FROM sso_pending WHERE token_hash=? AND kind='state'", (sso.hash_token(state or ""),)).fetchone() if state else None
    if not pend or pend["used_at"] or pend["expires_at"] < _now():
        _record_login_failure(rate_key)
        return _go(request, "/?sso_error=expired")
    conn.execute("UPDATE sso_pending SET used_at=? WHERE id=?", (_now(), pend["id"]))   # single use, even if this fails
    conn.commit()
    inst_id, mode = pend["institution_id"], pend["mode"]
    inst = conn.execute("SELECT id, status FROM institutions WHERE id=?", (inst_id,)).fetchone()
    row = _sso_row(conn, inst_id)
    if not inst or not row or (mode == "login" and not row["enabled"]):
        return _go(request, "/?sso_error=not_enabled")
    if error or not code:
        return _fail(conn, request, inst_id, None, None, "sso_denied", "denied", mode,
                     detail=f"Microsoft returned: {error or 'no code'} {(error_description or '')[:150]}")
    try:
        secret = decrypt_secret(row["client_secret_encrypted"])
        tokens = sso.exchange_code(row["tenant_id"], row["client_id"], secret, code, pend["redirect_uri"], pend["code_verifier"])
        claims = sso.validate_id_token(tokens.get("id_token") or "", row["tenant_id"], row["client_id"], pend["nonce"])
    except sso.SsoError as e:
        _record_login_failure(rate_key)
        logger.warning("SSO sign-in failed for institution %s: %s", inst_id, e.detail)
        return _fail(conn, request, inst_id, None, None, "sso_invalid_token", "failed", mode, detail=e.detail)
    except ValueError:
        return _fail(conn, request, inst_id, None, None, "sso_bad_secret", "failed", mode, detail="The saved client secret could not be read; save it again")

    who = (sso.candidate_emails(claims) or [claims.get("name") or claims["oid"]])[0]
    if mode == "test":
        conn.execute("UPDATE institution_sso SET last_test_at=?, last_test_ok=1, last_test_detail=? WHERE institution_id=?",
                     (_now(), f"Signed in as {who}", inst_id))
        write_entity_audit(conn, {"username": pend["started_by"], "role": "hr_manager"}, inst_id, "Settings", "sso", inst_id,
                           "Test sign-in OK", detail=f"Test sign-in succeeded as {who}", entity_label="Single sign-on")
        conn.commit()
        return _go(request, "/#settings-sso")

    user, how, problem = _resolve_user(conn, inst_id, claims)
    if problem:
        return _fail(conn, request, inst_id, who, None, f"sso_{problem}", "no_account", mode)
    if not user["is_active"]:
        return _fail(conn, request, inst_id, who, user["id"], "sso_inactive", "inactive", mode)
    if inst["status"] != "Active":
        return _fail(conn, request, inst_id, who, user["id"], "sso_institution_suspended", "suspended", mode)
    if how == "email":
        conn.execute("UPDATE users SET sso_tenant_id=?, sso_oid=? WHERE id=?", (claims["tid"], claims["oid"], user["id"]))
        write_entity_audit(conn, {"id": user["id"], "username": user["username"], "role": user["role"]}, inst_id, "Users", "user", user["id"],
                           "Microsoft account linked", detail=f"Linked to {who} on first Microsoft sign-in", entity_label=user["username"])
    _record_login_audit(conn, request, inst_id, user["username"], user["id"], True, "sso")
    login_code = sso.new_token()
    conn.execute("INSERT INTO sso_pending (institution_id,kind,token_hash,user_id,expires_at) VALUES (?,?,?,?,?)",
                 (inst_id, "code", sso.hash_token(login_code), user["id"], _now(sso.CODE_TTL_SECONDS)))
    conn.commit()
    return _go(request, f"/?sso_code={quote(login_code)}")


class SsoExchangeIn(BaseModel):
    code: str


@router.post("/api/auth/sso/exchange", tags=["auth"])
@db_session
def sso_exchange(conn, body: SsoExchangeIn) -> Dict[str, Any]:
    """Trade the one-time code from the redirect for the EMS token (same shape as POST /api/auth/login)."""
    pend = conn.execute("SELECT * FROM sso_pending WHERE token_hash=? AND kind='code'", (sso.hash_token(body.code or ""),)).fetchone()
    if not pend or pend["used_at"] or pend["expires_at"] < _now():
        raise HTTPException(401, "That sign-in link has expired. Please try again.")
    conn.execute("UPDATE sso_pending SET used_at=? WHERE id=?", (_now(), pend["id"]))
    user = conn.execute("SELECT * FROM users WHERE id=? AND institution_id=?", (pend["user_id"], pend["institution_id"])).fetchone()
    inst = conn.execute("SELECT status FROM institutions WHERE id=?", (pend["institution_id"],)).fetchone()
    if not user or not user["is_active"] or not inst or inst["status"] != "Active":
        conn.commit()
        raise HTTPException(403, "This account can't sign in right now.")
    now = _now()
    conn.execute("UPDATE users SET last_login=?, last_active=? WHERE id=?", (now, now, user["id"]))
    conn.commit()
    u = dict(user)
    u["must_change_password"] = False   # a temporary password is irrelevant when Microsoft proved who they are
    return {"access_token": make_token(u), "token_type": "bearer", "user": build_current_user_out(conn, u)}


# ---------------------------------------------------------------------------
# Settings → Single Sign-On (HR Manager)
# ---------------------------------------------------------------------------
class SsoSettingsIn(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: Optional[str] = None       # blank = keep the saved one


class SsoEnabledIn(BaseModel):
    enabled: bool


def _settings_out(conn, request: Request, inst_id: int) -> Dict[str, Any]:
    row = _sso_row(conn, inst_id)
    linked = conn.execute("SELECT COUNT(*) FROM users WHERE institution_id=? AND sso_oid IS NOT NULL", (inst_id,)).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM users WHERE institution_id=? AND is_active=1", (inst_id,)).fetchone()[0]
    return {
        "configured": row is not None,
        "tenant_id": row["tenant_id"] if row else "", "client_id": row["client_id"] if row else "",
        "has_secret": row is not None,
        "enabled": bool(row and row["enabled"]),
        "last_test_at": row["last_test_at"] if row else None,
        "last_test_ok": bool(row and row["last_test_ok"]),
        "last_test_detail": row["last_test_detail"] if row else None,
        "redirect_uri": _redirect_uri(request),
        "linked_users": linked, "active_users": total,
    }


@router.get("/api/settings/sso")
@db_session
def get_sso_settings(conn, request: Request, user: dict = Depends(require_roles(*SETTINGS_ROLES))) -> Dict[str, Any]:
    return _settings_out(conn, request, need_inst(user))


@router.put("/api/settings/sso")
@db_session
def save_sso_settings(conn, request: Request, body: SsoSettingsIn, user: dict = Depends(require_roles(*SETTINGS_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    tenant, client = body.tenant_id.strip(), body.client_id.strip()
    if not sso.is_guid(tenant):
        raise HTTPException(400, "The Directory (tenant) ID must be a GUID like 11111111-2222-3333-4444-555555555555")
    if not sso.is_guid(client):
        raise HTTPException(400, "The Application (client) ID must be a GUID like 11111111-2222-3333-4444-555555555555")
    row = _sso_row(conn, inst_id)
    secret = (body.client_secret or "").strip()
    if not secret and not row:
        raise HTTPException(400, "Enter the client secret value")
    changed = (not row) or row["tenant_id"] != tenant or row["client_id"] != client or bool(secret)
    if row:
        conn.execute(
            "UPDATE institution_sso SET tenant_id=?, client_id=?, client_secret_encrypted=?, updated_by=?, updated_at=? WHERE institution_id=?",
            (tenant, client, encrypt_secret(secret) if secret else row["client_secret_encrypted"], user["username"], _now(), inst_id))
        if changed:   # new values have not been tested, so the switch goes back off until they are
            conn.execute("UPDATE institution_sso SET enabled=0, last_test_at=NULL, last_test_ok=0, last_test_detail=NULL WHERE institution_id=?", (inst_id,))
    else:
        conn.execute("INSERT INTO institution_sso (institution_id,tenant_id,client_id,client_secret_encrypted,updated_by) VALUES (?,?,?,?,?)",
                     (inst_id, tenant, client, encrypt_secret(secret), user["username"]))
    write_entity_audit(conn, user, inst_id, "Settings", "sso", inst_id, "Saved",
                       detail="Single sign-on settings saved" + (" (client secret replaced)" if secret else ""),
                       entity_label="Single sign-on")
    conn.commit()
    return _settings_out(conn, request, inst_id)


@router.post("/api/settings/sso/test-start")
@db_session
def sso_test_start(conn, request: Request, user: dict = Depends(require_roles(*SETTINGS_ROLES))) -> Dict[str, Any]:
    """Begin a test sign-in as the person clicking: returns the Microsoft URL to open. Success is recorded on the
    settings row (it is what allows the switch to be turned on); no EMS session is created."""
    inst_id = need_inst(user)
    row = _sso_row(conn, inst_id)
    if not row:
        raise HTTPException(400, "Save the Entra details first")
    return {"authorize_url": _begin(conn, request, inst_id, row, "test", user["username"])}


@router.put("/api/settings/sso/enabled")
@db_session
def set_sso_enabled(conn, request: Request, body: SsoEnabledIn, user: dict = Depends(require_roles(*SETTINGS_ROLES))) -> Dict[str, Any]:
    inst_id = need_inst(user)
    row = _sso_row(conn, inst_id)
    if not row:
        raise HTTPException(400, "Save the Entra details first")
    if body.enabled and not row["last_test_ok"]:
        raise HTTPException(400, "Run a test sign-in successfully before turning Microsoft sign-in on")
    conn.execute("UPDATE institution_sso SET enabled=?, updated_by=?, updated_at=? WHERE institution_id=?",
                 (1 if body.enabled else 0, user["username"], _now(), inst_id))
    write_entity_audit(conn, user, inst_id, "Settings", "sso", inst_id, "Enabled" if body.enabled else "Disabled",
                       detail=f"Microsoft sign-in turned {'on' if body.enabled else 'off'}", entity_label="Single sign-on")
    conn.commit()
    return _settings_out(conn, request, inst_id)


@router.delete("/api/settings/sso", status_code=204)
@db_session
def delete_sso_settings(conn, user: dict = Depends(require_roles(*SETTINGS_ROLES))) -> None:
    """Remove the company's Microsoft sign-in configuration (and so the button). Linked users stay linked."""
    inst_id = need_inst(user)
    conn.execute("DELETE FROM institution_sso WHERE institution_id=?", (inst_id,))
    write_entity_audit(conn, user, inst_id, "Settings", "sso", inst_id, "Removed", detail="Single sign-on settings removed", entity_label="Single sign-on")
    conn.commit()


@router.post("/api/users/{user_id}/sso-unlink")
@db_session
def sso_unlink_user(conn, user_id: int, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Forget a user's Microsoft link (e.g. they changed account): their next Microsoft sign-in matches by email again."""
    require_permission(conn, user, "users.list_create_update_user")
    inst_id = need_inst(user)
    target = conn.execute("SELECT id, username, sso_oid FROM users WHERE id=? AND institution_id=?", (user_id, inst_id)).fetchone()
    if not target:
        raise HTTPException(404, "User not found")
    conn.execute("UPDATE users SET sso_tenant_id=NULL, sso_oid=NULL WHERE id=?", (user_id,))
    write_entity_audit(conn, user, inst_id, "Users", "user", user_id, "Microsoft account unlinked",
                       detail=f"Microsoft link removed from {target['username']}", entity_label=target["username"])
    conn.commit()
    return {"ok": True}
