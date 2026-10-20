"""Claude / MCP access: EMS as an OAuth 2.1 authorization server, plus HR's switch and connection list.

Why EMS itself: a person proves who they are with the sign-in they already use (password, Microsoft, "require Microsoft",
emergency access) on an EMS page, so none of that is re-implemented and the MCP server never sees a password. The MCP
server (mcp/) is only a resource server; it forwards the access token and core/deps.py's get_current_user does the rest
(grant not revoked, company switch on, scope allows this exact route). See core/oauth.py.

A connection also has a HARD limit (core/oauth.py's GRANT_MAX_DAYS, 30): that long after the person approved it, it stops
working however often it is used and they connect again.

Flow: Claude registers itself (POST /oauth/register) -> opens /oauth/authorize in the browser -> the page signs the person
in and asks them to allow -> POST /api/oauth/authorize/approve returns a redirect carrying a one-time code -> Claude trades
it at POST /oauth/token (PKCE S256, public client) for a 1-hour access token + a refresh token. Every refresh rotates the
refresh token and starts a new 30 days (sliding window); presenting an already-used refresh token revokes the whole grant.

Pre-login routes (register / token / revoke / the metadata) run with the default bypass RLS context, like the password
login. Company scoping is then explicit: every token and grant row carries its institution_id.
"""
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import List, Optional
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from core import oauth
from core.audit import write_entity_audit
from core.db_session import db_session
from core.deps import get_current_user, need_inst, require_roles

logger = logging.getLogger("ems")
router = APIRouter()

SETTINGS_ROLES = ("hr_manager", "superadmin")
DEFAULT_MCP_URL = "https://ems-mcp.fly.dev/mcp"

# Process-local sliding windows, same deliberate single-process tradeoff as routers/auth.py's login limiter.
_hits: dict = defaultdict(deque)


def _rate_limit(bucket: str, request: Request, limit: int, window_seconds: int):
    key = f"{bucket}:{request.client.host if request.client else 'unknown'}"
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests. Try again later.")
    q.append(now)


def _base_url(request: Request) -> str:
    base = os.environ.get("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/")
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    return f"{proto}://{request.headers.get('host') or request.url.netloc}"


def _oauth_error(error: str, description: str = "", status: int = 400) -> JSONResponse:
    body = {"error": error}
    if description:
        body["error_description"] = description
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


# ---------------------------------------------------------------------------
# Discovery + dynamic client registration
# ---------------------------------------------------------------------------
@router.get("/.well-known/oauth-authorization-server", tags=["oauth"])
def authorization_server_metadata(request: Request):
    base = _base_url(request)
    return {
        # With a trailing slash because that is how the MCP server advertises this server (a bare-origin URL always
        # serializes that way); the issuer must match the one the metadata was looked up for.
        "issuer": base + "/",
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": list(oauth.SCOPES),
    }


class RegisterIn(BaseModel):
    client_name: Optional[str] = None
    redirect_uris: List[str]
    token_endpoint_auth_method: Optional[str] = "none"


@router.post("/oauth/register", status_code=201, tags=["oauth"])
@db_session
def register_client(conn, body: RegisterIn, request: Request):
    _rate_limit("oauth-register", request, 20, 3600)
    uris = [u.strip() for u in body.redirect_uris if u and u.strip()]
    if not uris or len(uris) > 10 or not all(oauth.valid_redirect_uri(u) for u in uris):
        return _oauth_error("invalid_redirect_uri", "Redirect URIs must be https (or http to localhost).")
    if (body.token_endpoint_auth_method or "none") != "none":
        return _oauth_error("invalid_client_metadata", "Only public clients (token_endpoint_auth_method=none) are supported.")
    client_id = oauth.new_token(oauth.CLIENT_PREFIX)
    name = (body.client_name or "An app").strip()[:100] or "An app"
    conn.execute("INSERT INTO oauth_clients (client_id, client_name, redirect_uris) VALUES (?,?,?)",
                 (client_id, name, json.dumps(uris)))
    conn.commit()
    return JSONResponse({
        "client_id": client_id, "client_name": name, "redirect_uris": uris,
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }, status_code=201, headers={"Cache-Control": "no-store"})


def _client(conn, client_id: str):
    row = conn.execute("SELECT * FROM oauth_clients WHERE client_id=?", (client_id or "",)).fetchone()
    if not row:
        return None
    c = dict(row)
    c["uris"] = json.loads(c["redirect_uris"])
    return c


# ---------------------------------------------------------------------------
# Authorization page + approval
# ---------------------------------------------------------------------------
_PAGE_HEADERS = {
    "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}

_AUTH_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect Claude to EMS</title>
<style>
 body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f1f5f9;color:#0f172a;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px;box-sizing:border-box}
 .card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:28px;max-width:420px;width:100%;box-shadow:0 4px 18px rgba(15,23,42,.06)}
 h1{font-size:20px;margin:0 0 6px} p{font-size:14px;color:#475569;line-height:1.5;margin:6px 0}
 label{display:block;font-size:12px;font-weight:600;margin:12px 0 4px;color:#334155}
 input{width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px}
 button{cursor:pointer;font-size:14px;border-radius:999px;padding:9px 18px;border:1px solid #8c979e;background:transparent;color:#0f172a}
 button.primary{background:#0f172a;color:#fff;border-color:#0f172a} .row{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}
 ul{padding-left:18px;font-size:14px;color:#334155} .err{color:#b91c1c;font-size:13px;margin-top:10px} .muted{font-size:12px;color:#64748b}
 .hidden{display:none} a{color:#0f172a}
</style></head><body><div class="card">
<div id="viewError" class="hidden"><h1>Can't connect</h1><p id="errText"></p></div>
<div id="viewLogin" class="hidden">
 <h1>Sign in to EMS</h1><p><b id="clientNameL"></b> wants to connect to your EMS account. Sign in first.</p>
 <form id="loginForm">
  <label for="code">Company code</label><input id="code" autocomplete="organization" required>
  <p id="ssoNote" class="muted hidden">Your company requires Microsoft sign-in.</p>
  <div id="pwFields">
   <label for="user">Username or email</label><input id="user" autocomplete="username" required>
   <label for="pass">Password</label><input id="pass" type="password" autocomplete="current-password" required>
  </div>
  <div class="row"><button class="primary" type="submit" id="signInBtn">Sign in</button>
  <button type="button" id="msBtn" class="hidden">Sign in with Microsoft</button></div>
  <p class="muted hidden" id="emergencyWrap"><a href="#" id="emergencyLink">Use emergency password access</a></p>
 </form><div id="loginErr" class="err hidden"></div>
</div>
<div id="viewConsent" class="hidden">
 <h1>Allow <span id="clientNameC"></span>?</h1>
 <p>Signed in as <b id="who"></b> (<span id="company"></span>). If you allow this, <span id="clientNameC2"></span> can:</p>
 <ul id="scopes"></ul>
 <p class="muted">It cannot see anyone else's data, your payslips, or anything not listed. You can ask HR to disconnect it at any time.</p>
 <div class="row"><button class="primary" id="allowBtn">Allow</button><button id="denyBtn">Cancel</button></div>
 <p class="muted"><a href="#" id="switchUser">Not you? Use a different account</a></p>
 <div id="consentErr" class="err hidden"></div>
</div>
<script>
const P = __PARAMS__;
const $ = id => document.getElementById(id);
const show = v => { for (const x of ['viewError','viewLogin','viewConsent']) $(x).classList.toggle('hidden', x !== v); };
$('clientNameL').textContent = P.client_name;
function fail(msg){ $('errText').textContent = msg; show('viewError'); }
const q = new URLSearchParams({client_id:P.client_id, redirect_uri:P.redirect_uri, scope:P.scope});
async function init(){
  const t = localStorage.getItem('token');
  if(!t){ show('viewLogin'); return; }
  const r = await fetch('/api/oauth/authorize/preview?'+q, {headers:{Authorization:'Bearer '+t}});
  if(r.status===401){ localStorage.removeItem('token'); show('viewLogin'); return; }
  const d = await r.json().catch(()=>({}));
  if(!r.ok){ fail(d.detail || 'Something went wrong.'); return; }
  $('clientNameC').textContent = $('clientNameC2').textContent = d.client_name;
  $('who').textContent = d.full_name; $('company').textContent = d.company;
  $('scopes').innerHTML = ''; for(const s of d.scopes){ const li=document.createElement('li'); li.textContent=s; $('scopes').appendChild(li); }
  show('viewConsent');
}
$('loginForm').addEventListener('submit', async e => {
  e.preventDefault(); $('loginErr').classList.add('hidden');
  if($('pwFields').classList.contains('hidden')) return;
  const r = await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:$('user').value.trim(),password:$('pass').value,institution_code:$('code').value.trim()||null})});
  const d = await r.json().catch(()=>({}));
  if(!r.ok){ $('loginErr').textContent = d.detail || 'Sign-in failed'; $('loginErr').classList.remove('hidden'); return; }
  localStorage.setItem('token', d.access_token); $('pass').value=''; init();
});
let ssoTimer=null;
function showLoginMode(enabled, required, showPw){
  $('msBtn').classList.toggle('hidden', !enabled);
  $('ssoNote').classList.toggle('hidden', !(enabled && required));
  const hidePw = enabled && required && !showPw;
  $('pwFields').classList.toggle('hidden', hidePw);
  $('signInBtn').classList.toggle('hidden', hidePw);
  $('user').required = $('pass').required = !hidePw;
  $('emergencyWrap').classList.toggle('hidden', !hidePw);
  if(enabled && required) $('msBtn').classList.add('primary');
}
$('code').addEventListener('input', () => { clearTimeout(ssoTimer); ssoTimer=setTimeout(async()=>{
  const c=$('code').value.trim(); if(!c){ showLoginMode(false,false,true); return; }
  try{ const r=await fetch('/api/auth/sso/options?institution_code='+encodeURIComponent(c)); const d=r.ok?await r.json():{};
    showLoginMode(!!d.sso_enabled, !!d.sso_required, false);}catch(_){ showLoginMode(false,false,true); } }, 350); });
$('emergencyLink').addEventListener('click', e => { e.preventDefault(); showLoginMode(true, true, true); $('emergencyWrap').classList.add('hidden'); $('user').focus(); });
$('msBtn').addEventListener('click', () => {
  localStorage.setItem('oauth_resume', JSON.stringify({url: location.href, at: Date.now()}));
  location.href = '/api/auth/sso/start?institution_code='+encodeURIComponent($('code').value.trim());
});
$('switchUser').addEventListener('click', e => { e.preventDefault(); localStorage.removeItem('token'); show('viewLogin'); });
async function decide(approve){
  $('consentErr').classList.add('hidden');
  const r = await fetch('/api/oauth/authorize/approve',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('token')},
    body:JSON.stringify({client_id:P.client_id,redirect_uri:P.redirect_uri,code_challenge:P.code_challenge,scope:P.scope,state:P.state,approve})});
  const d = await r.json().catch(()=>({}));
  if(!r.ok){ $('consentErr').textContent = d.detail || 'Something went wrong.'; $('consentErr').classList.remove('hidden'); return; }
  location.href = d.redirect_url;
}
$('allowBtn').addEventListener('click', () => decide(true));
$('denyBtn').addEventListener('click', () => decide(false));
init();
</script></div></body></html>"""


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    # Shown on the authorization server itself, never redirected to the app: the redirect_uri can't be trusted yet.
    from html import escape
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<body style='font-family:system-ui;max-width:420px;margin:60px auto;padding:0 16px'>"
        f"<h2>Can't connect</h2><p>{escape(message)}</p></body>", status_code=status, headers=_PAGE_HEADERS)


@router.get("/oauth/authorize", tags=["oauth"])
@db_session
def authorize_page(conn, request: Request, client_id: str = "", redirect_uri: str = "", response_type: str = "",
                   code_challenge: str = "", code_challenge_method: str = "", scope: str = "", state: str = ""):
    client = _client(conn, client_id)
    if not client:
        return _error_page("This app isn't registered. Remove the connection in Claude and add it again.")
    if redirect_uri not in client["uris"]:
        return _error_page("This app's return address doesn't match what it registered.")
    if response_type != "code" or code_challenge_method != "S256" or not (43 <= len(code_challenge) <= 128):
        return _error_page("This app didn't send a valid sign-in request (PKCE with S256 is required).")
    params = {"client_id": client_id, "client_name": client["client_name"], "redirect_uri": redirect_uri,
              "code_challenge": code_challenge, "scope": " ".join(oauth.parse_scope(scope)), "state": state}
    blob = json.dumps(params).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return HTMLResponse(_AUTH_PAGE.replace("__PARAMS__", blob), headers=_PAGE_HEADERS)


def _eligibility_error(conn, user: dict) -> Optional[str]:
    """Why this person can't connect Claude, or None. Same rules the token check applies on every call."""
    if user.get("oauth_scopes"):
        return "Sign in with your own account to connect an app."
    inst_id = user.get("institution_id")
    if user["role"] == "superadmin" or not inst_id:
        return "Platform admin accounts can't be connected."
    if not user.get("employee_id"):
        return "Your account isn't linked to an employee record, so there's nothing for Claude to act on."
    inst = conn.execute("SELECT mcp_enabled, status FROM institutions WHERE id=?", (inst_id,)).fetchone()
    if not inst or inst["status"] != "Active" or not inst["mcp_enabled"]:
        return "Claude access isn't turned on for your company. Ask HR to enable it in Settings."
    return None


@router.get("/api/oauth/authorize/preview", tags=["oauth"])
@db_session
def authorize_preview(conn, client_id: str = "", redirect_uri: str = "", scope: str = "",
                      user: dict = Depends(get_current_user)):
    client = _client(conn, client_id)
    if not client or redirect_uri not in client["uris"]:
        raise HTTPException(400, "This app isn't registered.")
    err = _eligibility_error(conn, user)
    if err:
        raise HTTPException(403, err)
    inst = conn.execute("SELECT name FROM institutions WHERE id=?", (user["institution_id"],)).fetchone()
    return {"client_name": client["client_name"], "full_name": user["full_name"], "company": inst["name"] if inst else "",
            "scopes": [oauth.SCOPES[s] for s in oauth.parse_scope(scope)]}


@router.get("/api/oauth/whoami", tags=["oauth"])
@db_session
def whoami(conn, user: dict = Depends(get_current_user)):
    """For the MCP server: proves a Claude token is live and says who it acts as. Only answers to an OAuth token."""
    if not user.get("oauth_scopes"):
        raise HTTPException(403, "Only for Claude connections")
    inst = conn.execute("SELECT name, timezone FROM institutions WHERE id=?", (user["institution_id"],)).fetchone()
    return {"full_name": user["full_name"], "employee_id": user["employee_id"], "scopes": user["oauth_scopes"],
            "company": inst["name"] if inst else "", "timezone": (inst["timezone"] if inst else None) or "UTC",
            "expires_at": user.get("oauth_expires_at")}


class ApproveIn(BaseModel):
    client_id: str
    redirect_uri: str
    code_challenge: str
    scope: str = ""
    state: str = ""
    approve: bool = True


def _redirect(base: str, **params) -> str:
    sep = "&" if "?" in base else "?"
    return base + sep + urlencode({k: v for k, v in params.items() if v})


@router.post("/api/oauth/authorize/approve", tags=["oauth"])
@db_session
def authorize_approve(conn, body: ApproveIn, request: Request, user: dict = Depends(get_current_user)):
    client = _client(conn, body.client_id)
    if not client or body.redirect_uri not in client["uris"]:
        raise HTTPException(400, "This app isn't registered.")
    if not (43 <= len(body.code_challenge) <= 128):
        raise HTTPException(400, "Invalid request.")
    if not body.approve:
        return {"redirect_url": _redirect(body.redirect_uri, error="access_denied", state=body.state)}
    err = _eligibility_error(conn, user)
    if err:
        raise HTTPException(403, err)
    scopes = oauth.parse_scope(body.scope)
    code = oauth.new_token(oauth.CODE_PREFIX)
    conn.execute(
        "INSERT INTO oauth_codes (institution_id,user_id,client_id,code_hash,redirect_uri,code_challenge,scope,expires_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (user["institution_id"], user["id"], body.client_id, oauth.hash_token(code), body.redirect_uri,
         body.code_challenge, " ".join(scopes), oauth.now_str(oauth.CODE_TTL_SECONDS)))
    conn.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (oauth.now_str(-86400),))
    conn.commit()
    return {"redirect_url": _redirect(body.redirect_uri, code=code, state=body.state)}


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------
def _issue(conn, grant_id: int, inst_id: int, scope: str) -> dict:
    access, refresh = oauth.new_token(oauth.ACCESS_PREFIX), oauth.new_token(oauth.REFRESH_PREFIX)
    conn.execute("INSERT INTO oauth_tokens (institution_id,grant_id,kind,token_hash,expires_at) VALUES (?,?,?,?,?)",
                 (inst_id, grant_id, "access", oauth.hash_token(access), oauth.now_str(oauth.ACCESS_TTL_SECONDS)))
    conn.execute("INSERT INTO oauth_tokens (institution_id,grant_id,kind,token_hash,expires_at) VALUES (?,?,?,?,?)",
                 (inst_id, grant_id, "refresh", oauth.hash_token(refresh), oauth.now_str(oauth.REFRESH_TTL_DAYS * 86400)))
    conn.execute("UPDATE oauth_grants SET last_used_at=? WHERE id=?", (oauth.now_str(), grant_id))
    conn.execute("DELETE FROM oauth_tokens WHERE expires_at < ?", (oauth.now_str(-86400),))
    return {"access_token": access, "token_type": "Bearer", "expires_in": oauth.ACCESS_TTL_SECONDS,
            "refresh_token": refresh, "scope": scope}


def _revoke_grant(conn, grant_id: int, by: str):
    conn.execute("UPDATE oauth_grants SET revoked_at=?, revoked_by=? WHERE id=? AND revoked_at IS NULL",
                 (oauth.now_str(), by, grant_id))


def _user_can_still_connect(conn, user_id: int, inst_id: int) -> bool:
    row = conn.execute(
        "SELECT u.is_active, u.employee_id, u.role, i.mcp_enabled, i.status FROM users u "
        "JOIN institutions i ON i.id = u.institution_id WHERE u.id=? AND u.institution_id=?", (user_id, inst_id)).fetchone()
    return bool(row and row["is_active"] and row["employee_id"] and row["role"] != "superadmin"
                and row["mcp_enabled"] and row["status"] == "Active")


async def _form(request: Request) -> dict:
    """application/x-www-form-urlencoded body (what OAuth clients send), parsed by hand so no multipart dependency is needed."""
    try:
        raw = (await request.body())[:20000].decode()
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    except Exception:
        return {}


@router.post("/oauth/token", tags=["oauth"])
async def token_endpoint(request: Request):
    form = await _form(request)
    return await _run_sync(_token, form, request)


async def _run_sync(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)


def _token(form: dict, request: Request):
    from db import get_db
    _rate_limit("oauth-token", request, 60, 300)
    conn = get_db()
    try:
        grant_type = form.get("grant_type")
        client = _client(conn, form.get("client_id", ""))
        if not client:
            return _oauth_error("invalid_client", "Unknown client_id.", 401)
        if grant_type == "authorization_code":
            return _exchange_code(conn, form, client)
        if grant_type == "refresh_token":
            return _refresh(conn, form, client)
        return _oauth_error("unsupported_grant_type")
    finally:
        conn.close()


def _exchange_code(conn, form: dict, client: dict):
    row = conn.execute("SELECT * FROM oauth_codes WHERE code_hash=?", (oauth.hash_token(form.get("code", "")),)).fetchone()
    if not row or row["client_id"] != client["client_id"] or row["expires_at"] < oauth.now_str():
        return _oauth_error("invalid_grant", "The code is invalid or has expired.")
    # Single use: only the request that flips used_at from NULL gets to continue.
    if conn.execute("UPDATE oauth_codes SET used_at=? WHERE id=? AND used_at IS NULL", (oauth.now_str(), row["id"])).rowcount != 1:
        conn.commit()
        return _oauth_error("invalid_grant", "The code was already used.")
    conn.commit()
    if form.get("redirect_uri") != row["redirect_uri"]:
        return _oauth_error("invalid_grant", "redirect_uri doesn't match.")
    verifier = form.get("code_verifier", "")
    if not (43 <= len(verifier) <= 128) or oauth.pkce_s256(verifier) != row["code_challenge"]:
        return _oauth_error("invalid_grant", "PKCE verification failed.")
    if not _user_can_still_connect(conn, row["user_id"], row["institution_id"]):
        return _oauth_error("access_denied", "This account can't use Claude access right now.", 403)
    conn.execute("INSERT INTO oauth_grants (institution_id,user_id,client_id,client_name,scope) VALUES (?,?,?,?,?)",
                 (row["institution_id"], row["user_id"], client["client_id"], client["client_name"], row["scope"]))
    grant_id = conn._last_id
    user = conn.execute("SELECT id, username, role FROM users WHERE id=?", (row["user_id"],)).fetchone()
    write_entity_audit(conn, dict(user), row["institution_id"], "Claude access", "oauth_grant", grant_id, "Connected",
                       detail=f"{client['client_name']} connected ({row['scope']})", entity_label=user["username"])
    out = _issue(conn, grant_id, row["institution_id"], row["scope"])
    conn.commit()
    return JSONResponse(out, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _refresh(conn, form: dict, client: dict):
    tok = conn.execute(
        "SELECT t.*, g.client_id AS g_client, g.scope AS g_scope, g.user_id AS g_user, g.revoked_at, g.created_at AS g_created "
        "FROM oauth_tokens t JOIN oauth_grants g ON g.id = t.grant_id WHERE t.token_hash=? AND t.kind='refresh'",
        (oauth.hash_token(form.get("refresh_token", "")),)).fetchone()
    if not tok or tok["g_client"] != client["client_id"] or tok["revoked_at"]:
        return _oauth_error("invalid_grant", "The refresh token is invalid.")
    if tok["g_created"] < oauth.grant_cutoff():
        _revoke_grant(conn, tok["grant_id"], f"system: {oauth.GRANT_MAX_DAYS}-day limit")
        conn.commit()
        return _oauth_error("invalid_grant", f"This connection reached its {oauth.GRANT_MAX_DAYS}-day limit. Connect again.")
    # An already-used refresh token coming back means it leaked (or the app lost track of rotation): kill the grant.
    if tok["used_at"] or tok["expires_at"] < oauth.now_str():
        if tok["used_at"]:
            _revoke_grant(conn, tok["grant_id"], "system: refresh token reuse")
            conn.commit()
        return _oauth_error("invalid_grant", "The refresh token is no longer valid. Connect again.")
    if conn.execute("UPDATE oauth_tokens SET used_at=? WHERE id=? AND used_at IS NULL", (oauth.now_str(), tok["id"])).rowcount != 1:
        conn.commit()
        return _oauth_error("invalid_grant", "The refresh token was already used.")
    if not _user_can_still_connect(conn, tok["g_user"], tok["institution_id"]):
        conn.commit()
        return _oauth_error("invalid_grant", "This account can't use Claude access right now.")
    out = _issue(conn, tok["grant_id"], tok["institution_id"], tok["g_scope"])
    conn.commit()
    return JSONResponse(out, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/revoke", tags=["oauth"])
async def revoke_endpoint(request: Request):
    form = await _form(request)
    return await _run_sync(_revoke, form, request)


def _revoke(form: dict, request: Request):
    from db import get_db
    _rate_limit("oauth-revoke", request, 60, 300)
    token = form.get("token", "")
    conn = get_db()
    try:
        tok = conn.execute("SELECT grant_id FROM oauth_tokens WHERE token_hash=?", (oauth.hash_token(token),)).fetchone()
        if tok:
            _revoke_grant(conn, tok["grant_id"], "client")
            conn.commit()
        return JSONResponse({}, status_code=200)   # RFC 7009: same answer whether or not the token existed
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Settings -> Claude / MCP (HR Manager)
# ---------------------------------------------------------------------------
class McpEnabledIn(BaseModel):
    enabled: bool


def _settings_out(conn, inst_id: int) -> dict:
    inst = conn.execute("SELECT mcp_enabled FROM institutions WHERE id=?", (inst_id,)).fetchone()
    grants = conn.execute(
        "SELECT g.id, g.client_name, g.scope, g.created_at, g.last_used_at, u.username, u.full_name, e.full_name AS employee_name "
        "FROM oauth_grants g LEFT JOIN users u ON u.id = g.user_id "
        "LEFT JOIN employees e ON e.institution_id = g.institution_id AND e.employee_id = u.employee_id "
        "WHERE g.institution_id=? AND g.revoked_at IS NULL AND g.created_at>=? ORDER BY g.last_used_at DESC",
        (inst_id, oauth.grant_cutoff())).fetchall()
    return {
        "enabled": bool(inst and inst["mcp_enabled"]),
        "mcp_url": os.environ.get("MCP_PUBLIC_URL", DEFAULT_MCP_URL),
        "connections": [{
            "id": g["id"], "person": g["employee_name"] or g["full_name"] or g["username"], "username": g["username"],
            "app": g["client_name"], "scope": g["scope"], "connected_at": g["created_at"], "last_used_at": g["last_used_at"],
            "reconnect_by": oauth.grant_reconnect_by(g["created_at"]),
        } for g in grants],
    }


@router.get("/api/settings/mcp", tags=["oauth"])
@db_session
def get_mcp_settings(conn, user: dict = Depends(require_roles(*SETTINGS_ROLES))):
    return _settings_out(conn, need_inst(user))


@router.put("/api/settings/mcp/enabled", tags=["oauth"])
@db_session
def set_mcp_enabled(conn, body: McpEnabledIn, request: Request, user: dict = Depends(require_roles(*SETTINGS_ROLES))):
    inst_id = need_inst(user)
    old = conn.execute("SELECT mcp_enabled FROM institutions WHERE id=?", (inst_id,)).fetchone()
    conn.execute("UPDATE institutions SET mcp_enabled=? WHERE id=?", (1 if body.enabled else 0, inst_id))
    write_entity_audit(conn, user, inst_id, "Claude access", "setting", "mcp_enabled",
                       "Turned on" if body.enabled else "Turned off",
                       detail="Claude access " + ("turned on" if body.enabled else "turned off (existing connections stop working at once)"),
                       changes=[{"field": "mcp_enabled", "label": "Claude access", "old": bool(old and old["mcp_enabled"]), "new": body.enabled}],
                       ip=request.client.host if request.client else None)
    conn.commit()
    return _settings_out(conn, inst_id)


@router.delete("/api/settings/mcp/connections/{grant_id}", tags=["oauth"])
@db_session
def disconnect(conn, grant_id: int, request: Request, user: dict = Depends(require_roles(*SETTINGS_ROLES))):
    inst_id = need_inst(user)
    g = conn.execute("SELECT id, client_name, user_id FROM oauth_grants WHERE id=? AND institution_id=? AND revoked_at IS NULL",
                     (grant_id, inst_id)).fetchone()
    if not g:
        raise HTTPException(404, "Connection not found")
    _revoke_grant(conn, grant_id, user["username"])
    target = conn.execute("SELECT username FROM users WHERE id=?", (g["user_id"],)).fetchone()
    write_entity_audit(conn, user, inst_id, "Claude access", "oauth_grant", grant_id, "Disconnected",
                       detail=f"{g['client_name']} disconnected for {target['username'] if target else 'a user'}",
                       entity_label=target["username"] if target else None, ip=request.client.host if request.client else None)
    conn.commit()
    return _settings_out(conn, inst_id)
