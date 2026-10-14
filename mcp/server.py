"""EMS MCP server: lets Claude act as one employee, on their own behalf, for a few self-service things.

It holds no data and no credentials of its own. Each caller arrives with an OAuth access token that EMS itself issued
(routers/oauth.py in the main app: the person signed in to EMS and allowed Claude). This server only (1) checks that token
with EMS, (2) forwards it on the normal EMS API, and (3) turns the answers into something Claude can say. All the rules -
who may clock in, geofence, late detection, which leave balances are theirs - stay in EMS, and EMS re-checks the token and
the company's "Claude access" switch on every call, so HR turning it off or disconnecting someone takes effect at once.

Run: `python server.py` (PORT, default 8080). Config (env): EMS_BASE_URL (the EMS app, also the OAuth issuer),
MCP_PUBLIC_URL (this server's public address, ending in /mcp).
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("ems-mcp")

EMS_BASE_URL = os.environ.get("EMS_BASE_URL", "https://ems-app.fly.dev").rstrip("/")
MCP_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "https://ems-mcp.fly.dev/mcp").rstrip("/")
WHOAMI_CACHE_SECONDS = 10

_http: Optional[httpx.AsyncClient] = None
_whoami_cache: dict = {}


def http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(base_url=EMS_BASE_URL, timeout=20.0, headers={"User-Agent": "ems-mcp/1.0"})
    return _http


def _utc_epoch(ems_time: str) -> int:
    return int(datetime.strptime(ems_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


class EmsTokenVerifier:
    """Asks EMS who a bearer token belongs to. EMS is the only judge: unknown, expired, revoked, or the company switch off."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = _whoami_cache.get(key)
        if hit and hit[0] > time.monotonic():
            who = hit[1]
        else:
            try:
                resp = await http().get("/api/oauth/whoami", headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError:
                logger.exception("EMS unreachable while checking a token")
                return None
            if resp.status_code != 200:
                return None
            who = resp.json()
            _whoami_cache[key] = (time.monotonic() + WHOAMI_CACHE_SECONDS, who)
            if len(_whoami_cache) > 2000:
                _whoami_cache.clear()
        return AccessToken(token=token, client_id=who["employee_id"], scopes=who["scopes"], resource=MCP_PUBLIC_URL,
                           expires_at=_utc_epoch(who["expires_at"]) if who.get("expires_at") else None, claims=who)


mcp = FastMCP(
    "EMS",
    instructions=(
        "Self-service for the signed-in employee in EMS (their company's HR system): clock in and out, see today's "
        "attendance, and see leave balances. Everything acts only as that one person. Clocking in/out records real "
        "attendance, so only do it when the person clearly asks."
    ),
    token_verifier=EmsTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(EMS_BASE_URL),
        resource_server_url=AnyHttpUrl(MCP_PUBLIC_URL),
        required_scopes=[],
        validate_token_resource=False,   # EMS issues the tokens and is the only judge of them; they carry no audience
    ),
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8080")),
    stateless_http=True,       # nothing is remembered between calls, so any Fly machine can answer any request
    json_response=True,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------- calling EMS
def _caller() -> AccessToken:
    tok = get_access_token()
    if tok is None:
        raise ToolError("You're not signed in to EMS. Reconnect the EMS connector in Claude.")
    return tok


async def ems(method: str, path: str, *, json: Any = None, params: Optional[dict] = None) -> Any:
    tok = _caller()
    try:
        resp = await http().request(method, path, json=json, params=params, headers={"Authorization": f"Bearer {tok.token}"})
    except httpx.HTTPError:
        logger.exception("EMS call failed: %s %s", method, path)
        raise ToolError("EMS can't be reached right now. Try again in a moment.")
    if resp.status_code < 300:
        return resp.json()
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    if resp.status_code == 401:
        raise ToolError("Your EMS connection has expired or was disconnected. Reconnect the EMS connector in Claude.")
    if isinstance(detail, str) and resp.status_code in (400, 403, 404, 409):
        raise ToolError(detail)            # EMS's own words, e.g. "Already clocked in for this work day"
    if resp.status_code == 422:
        raise ToolError("That request wasn't valid.")
    if resp.status_code == 429:
        raise ToolError("Too many requests. Try again shortly.")
    logger.error("EMS answered %s for %s %s", resp.status_code, method, path)
    raise ToolError("EMS had a problem handling that. Try again later.")


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo((_caller().claims or {}).get("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _local(ems_utc_iso: Optional[str]) -> Optional[datetime]:
    """EMS stores attendance times as naive UTC; show them in the company's own timezone."""
    if not ems_utc_iso:
        return None
    return datetime.fromisoformat(ems_utc_iso).replace(tzinfo=timezone.utc).astimezone(_tz())


def _hhmm(ems_utc_iso: Optional[str]) -> Optional[str]:
    d = _local(ems_utc_iso)
    return d.strftime("%H:%M") if d else None


def _location(lat: Optional[float], lng: Optional[float]) -> dict:
    if (lat is None) != (lng is None):
        raise ToolError("Give both latitude and longitude, or neither.")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ToolError("That location isn't valid (latitude -90..90, longitude -180..180).")
    return {"lat": lat, "lng": lng}


def _minutes(m: Optional[int]) -> str:
    return "" if m is None else f"{m // 60}h {m % 60:02d}m"


# --------------------------------------------------------------------------- tools
LOCATION_HELP = (
    "Ask the person to share their current location (latitude and longitude) before calling this, because the company may "
    "check it against the workplace. Never guess or invent coordinates. If they decline or can't, call it without them: it "
    "is still recorded, marked as having no location."
)


@mcp.tool(
    description="Clock the signed-in employee in for work now. Records real attendance, so only call when they ask to clock in. " + LOCATION_HELP,
    annotations=ToolAnnotations(title="Clock in", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def clock_in(latitude: Optional[float] = None, longitude: Optional[float] = None) -> dict:
    rec = await ems("POST", "/api/attendance/clock-in", json=_location(latitude, longitude))
    notes = []
    if rec.get("status") == "Late":
        notes.append("marked Late")
    if rec.get("outside_geofence"):
        notes.append("outside the workplace area")
    if not rec.get("clock_in_has_location"):
        notes.append("no location recorded")
    at = _hhmm(rec.get("clock_in_at"))
    return {"message": f"Clocked in at {at}" + (f" ({', '.join(notes)})" if notes else ""), "clock_in_time": at,
            "work_date": rec.get("work_date"), "status": rec.get("status"), "shift": rec.get("shift_name"),
            "outside_geofence": bool(rec.get("outside_geofence")), "location_recorded": bool(rec.get("clock_in_has_location"))}


@mcp.tool(
    description="Clock the signed-in employee out now (ends their open clock-in). Records real attendance, so only call when they ask to clock out. " + LOCATION_HELP,
    annotations=ToolAnnotations(title="Clock out", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def clock_out(latitude: Optional[float] = None, longitude: Optional[float] = None) -> dict:
    rec = await ems("POST", "/api/attendance/clock-out", json=_location(latitude, longitude))
    return {"message": f"Clocked out at {_hhmm(rec.get('clock_out_at'))}. Worked {_minutes(rec.get('worked_minutes'))}.",
            "clock_in_time": _hhmm(rec.get("clock_in_at")), "clock_out_time": _hhmm(rec.get("clock_out_at")),
            "worked_minutes": rec.get("worked_minutes"), "work_date": rec.get("work_date")}


@mcp.tool(annotations=ToolAnnotations(title="Today's attendance", readOnlyHint=True, openWorldHint=False))
async def attendance_today() -> dict:
    """Say whether the signed-in employee is clocked in right now, and when they clocked in/out today. Safe to call any time."""
    rows = await ems("GET", "/api/attendance/mine", params={"limit": 3})
    today = datetime.now(_tz()).date().isoformat()
    # An open clock-in always wins, even if it started on an earlier work day (a shift that crosses midnight).
    open_rec = next((r for r in rows if r.get("clock_in_at") and not r.get("clock_out_at")), None)
    if open_rec:
        since = _hhmm(open_rec["clock_in_at"])
        return {"state": "clocked_in", "message": f"Clocked in since {since} (work date {open_rec['work_date']}).",
                "clock_in_time": since, "work_date": open_rec["work_date"], "status": open_rec.get("status")}
    done = next((r for r in rows if r.get("work_date") == today and r.get("clock_in_at")), None)
    if done:
        return {"state": "clocked_out", "message": f"Clocked in {_hhmm(done['clock_in_at'])}, out {_hhmm(done['clock_out_at'])} "
                                                   f"({_minutes(done.get('worked_minutes'))}).",
                "clock_in_time": _hhmm(done["clock_in_at"]), "clock_out_time": _hhmm(done["clock_out_at"]),
                "worked_minutes": done.get("worked_minutes"), "work_date": today}
    return {"state": "not_clocked_in", "message": "Not clocked in today.", "work_date": today}


@mcp.tool(annotations=ToolAnnotations(title="Leave balance", readOnlyHint=True, openWorldHint=False))
async def leave_balance(year: Optional[int] = None) -> dict:
    """The signed-in employee's own leave balance for each leave type (default: this year): days available, entitled and used, plus any carried-forward days and when they expire. Safe to call any time."""
    rows = await ems("GET", "/api/leave/balances", params={"year": year} if year else None)
    out = []
    for b in rows:
        entitled = b.get("accrued_days") if b.get("accrued_days") is not None else b.get("entitled_days", 0)
        carried = b.get("carried_forward_days") or 0
        available = round(entitled + carried - (b.get("used_days") or 0), 2)
        out.append({"leave_type": b.get("leave_type_name"), "available_days": available,
                    "entitled_days_so_far": entitled, "carried_forward_days": carried,
                    "carried_forward_remaining": b.get("carried_forward_remaining") or 0,
                    "carried_forward_expires_on": b.get("carried_forward_expires_on") or None,
                    "used_days": b.get("used_days") or 0, "year": b.get("year")})
    return {"year": (out[0]["year"] if out else year), "balances": out,
            "message": ("; ".join(f"{o['leave_type']}: {o['available_days']} day(s)" for o in out)) or "No leave balances found."}


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    mcp.run(transport="streamable-http")
