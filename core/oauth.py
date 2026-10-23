"""Claude / MCP access: the pieces of EMS's OAuth 2.1 authorization server that aren't HTTP routes.

EMS is the authorization server (routers/oauth.py) so the existing sign-in - password, Microsoft, "require Microsoft",
emergency access - is what proves who the person is. The MCP server (mcp/) is only a resource server: it forwards the
caller's access token to the normal EMS API, and core/deps.py's get_current_user recognises it by its prefix.

Access is deliberately narrower than a normal login: a token carries scopes, and SCOPE_ROUTES below is the complete
list of (method, path) pairs each scope may reach. Anything not listed is refused, so a new endpoint is unreachable
from Claude until someone adds it here on purpose.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta

ACCESS_PREFIX = "emsat_"
REFRESH_PREFIX = "emsrt_"
CODE_PREFIX = "emsac_"
CLIENT_PREFIX = "emscl_"

CODE_TTL_SECONDS = 300
ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_DAYS = 30           # sliding: every refresh starts a new 30 days
# Hard limit: a connection stops working this long after the person approved it, however often it is used, and they sign in again
# (so a person disabled in Microsoft Entra, which EMS isn't told about, can't keep a Claude connection alive forever).
GRANT_MAX_DAYS = 30

SCOPES = {
    "attendance:clock": "Clock you in and out",
    "attendance:read": "See your own attendance",
    "leave:read": "See your own leave balances",
    "timesheet:read": "See your own timesheet hours, and the projects you can log to with their tasks, managers and team members",
    "timesheet:write": "Add hours to your own draft timesheet (it never submits it)",
    "leave:colleagues": "See which colleagues are on approved leave (names and dates only, never the type of leave)",
    "holidays:read": "See your company's public holidays",
    "projects:write": "See the projects you manage and add, edit and delete their tasks (only projects you are a listed manager of)",
    "todos:read": "See your To-Do list: what is waiting for you, including requests waiting for your approval (read only; sensitive matters as counts only)",
}
DEFAULT_SCOPES = ("attendance:clock", "attendance:read", "leave:read", "timesheet:read", "timesheet:write", "leave:colleagues", "holidays:read", "projects:write", "todos:read")

# scope -> the only (METHOD, exact path) pairs a token holding that scope may call.
SCOPE_ROUTES = {
    "attendance:clock": {("POST", "/api/attendance/clock-in"), ("POST", "/api/attendance/clock-out")},
    "attendance:read": {("GET", "/api/attendance/mine")},
    "leave:read": {("GET", "/api/leave/balances")},
    "timesheet:read": {("GET", "/api/me/timesheet/projects"), ("GET", "/api/me/week-hours")},
    "timesheet:write": {("POST", "/api/me/timesheet/log-hours")},
    "leave:colleagues": {("GET", "/api/me/leave-colleagues")},
    "holidays:read": {("GET", "/api/me/public-holidays")},
    "projects:write": {("GET", "/api/me/managed-projects"), ("POST", "/api/me/project-tasks/add"),
                       ("POST", "/api/me/project-tasks/update"), ("POST", "/api/me/project-tasks/delete")},
    "todos:read": {("GET", "/api/me/todos")},
}

_REDIRECT_OK = re.compile(r"^(https://[^\s#]+|http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/[^\s#]*)?)$")


def now_str(delta_seconds: int = 0) -> str:
    return (datetime.utcnow() + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def grant_cutoff() -> str:
    """Grants created before this moment have passed GRANT_MAX_DAYS."""
    return now_str(-GRANT_MAX_DAYS * 86400)


def grant_reconnect_by(created_at: str) -> str:
    """The date (YYYY-MM-DD, UTC) a grant created at `created_at` stops working."""
    return (datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S") + timedelta(days=GRANT_MAX_DAYS)).strftime("%Y-%m-%d")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def valid_redirect_uri(uri: str) -> bool:
    """https anywhere, or http only to the local machine (native apps / the MCP Inspector). No fragments."""
    return bool(uri) and len(uri) <= 2000 and bool(_REDIRECT_OK.match(uri))


def parse_scope(raw) -> list:
    """Requested scopes, limited to ones we offer; none requested = all of ours."""
    wanted = [s for s in (raw or "").split() if s in SCOPES]
    out = []
    for s in (wanted or list(DEFAULT_SCOPES)):
        if s not in out:
            out.append(s)
    return out


# Reachable with any valid token whatever its scopes: the MCP server uses it to check a token and to greet the person.
ANY_SCOPE_ROUTES = {("GET", "/api/oauth/whoami")}


def scope_allows(scopes, method: str, path: str) -> bool:
    key = (method.upper(), path.rstrip("/") or "/")
    return key in ANY_SCOPE_ROUTES or any(key in SCOPE_ROUTES.get(s, ()) for s in scopes)


def pkce_s256(verifier: str) -> str:
    import base64
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
