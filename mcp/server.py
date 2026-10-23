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
        "attendance, see leave balances, log hours to their draft timesheet, see the week's clocked and missing hours, see which colleagues are on approved leave, (for projects they manage) add, edit and delete project tasks, and read their To-Do list. Everything acts only as that one person. Clocking in/out records real "
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


@mcp.tool(
    description=(
        "List the projects the signed-in employee can log hours against, each with its tasks (with the ids log_hours needs), its project "
        "managers and its team members (names only), and whether the person is a manager or member of it. Pass search to narrow by project "
        "name, e.g. to answer who the managers or team of one project are. Call this before log_hours so the person can pick the project "
        "and task. Tasks have no individual assignee in EMS, only the project team: don't say who is assigned to a task. Safe to call any time."),
    annotations=ToolAnnotations(title="My projects, tasks and teams", readOnlyHint=True, openWorldHint=False))
async def my_projects(search: Optional[str] = None) -> dict:
    rows = await ems("GET", "/api/me/timesheet/projects", params={"search": search} if search else None)
    def line(p):
        mg = ", ".join(m["name"] for m in p["managers"]) or "none set"
        team = f"{len(p['members'])} member(s)" if p["members"] else ("open to all employees" if p["open_to_all"] else "no members set")
        return f"{p['project_name']}: managers {mg}; {team}; {len(p['tasks'])} task(s)"
    return {"projects": rows, "message": ("\n".join(line(p) for p in rows)) or (f"No projects matching '{search}'." if search else "No projects to log hours against.")}


@mcp.tool(
    description=(
        "Add hours the signed-in employee worked on one project task to their DRAFT timesheet for this week (default: today; any earlier day "
        "this week is allowed, future days and other weeks are not). If that task already has hours that day, these are added to them. "
        "Ask the person which project and task and how many hours; call my_projects for the choices and ids. Never guess a project, task or "
        "number of hours. This only saves a draft: it never submits the timesheet, which the person does in EMS."),
    annotations=ToolAnnotations(title="Log hours", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def log_hours(project_id: int, task_id: int, hours: float, date: Optional[str] = None) -> dict:
    rec = await ems("POST", "/api/me/timesheet/log-hours", json={"project_id": project_id, "task_id": task_id, "hours": hours, "date": date})
    more = " (added to hours already logged there)" if rec["added_to_existing"] else ""
    return {**rec, "message": (f"Logged {rec['hours_added']}h on {rec['project_name']} / {rec['task_name']} for {rec['date']}{more}. "
                               f"That task: {rec['task_hours_that_day']}h that day. All tasks that day: {rec['day_total_hours']}h. "
                               f"This week logged: {rec['week_logged_hours']}h. Timesheet status: {rec['timesheet_status']} (not submitted).")}


@mcp.tool(annotations=ToolAnnotations(title="This week's hours", readOnlyHint=True, openWorldHint=False))
async def week_hours(date: Optional[str] = None) -> dict:
    """The signed-in employee's hours for a Monday-to-Sunday week (default: this week; pass any date in the week as YYYY-MM-DD): hours clocked in, hours logged on the timesheet, public-holiday and approved-leave hours, expected hours and the missing hours still to be accounted for (the same figure as My Timesheet), plus a per-day breakdown. Safe to call any time."""
    w = await ems("GET", "/api/me/week-hours", params={"date": date} if date else None)
    now_note = " Currently clocked in (counted so far)." if w.get("clocked_in_now") else ""
    return {**w, "message": (f"Week {w['week_start']} to {w['week_end']}: clocked {w['clocked_hours']}h, logged {w['logged_hours']}h, "
                             f"holidays {w['holiday_hours']}h, leave {w['leave_hours']}h, expected {w['expected_hours']}h, "
                             f"missing {w['missing_hours']}h. Timesheet: {w['timesheet_status']}.{now_note}")}


@mcp.tool(
    description=(
        "Say which colleagues in the company are on approved leave on a day (default: today) or over a short range of up to 31 days "
        "(date and end_date, YYYY-MM-DD). Optionally limit to one department. Returns names, departments and whether the leave is "
        "only half a day, for each day. It never says what kind of leave anyone is on, and it can't see pending requests: don't "
        "guess or speculate about reasons. Weekends and public holidays are reported as non-working days with nobody listed. "
        "The person asking is left out of the list."),
    annotations=ToolAnnotations(title="Colleagues on leave", readOnlyHint=True, openWorldHint=False))
async def colleagues_on_leave(date: Optional[str] = None, end_date: Optional[str] = None, department: Optional[str] = None) -> dict:
    params = {k: v for k, v in {"date": date, "end_date": end_date, "department": department}.items() if v}
    res = await ems("GET", "/api/me/leave-colleagues", params=params or None)
    lines = []
    for day in res["days"]:
        if day["non_working_day"]:
            lines.append(f"{day['weekday']} {day['date']}: {day['non_working_day']}")
        elif not day["on_leave"]:
            lines.append(f"{day['weekday']} {day['date']}: nobody on approved leave")
        else:
            who = ", ".join(p["name"] + (f" ({p['half_day']} only)" if p["half_day"] else "") for p in day["on_leave"])
            lines.append(f"{day['weekday']} {day['date']}: {who}")
    scope = f" in {department}" if department else ""
    return {**res, "message": f"On approved leave{scope}:\n" + "\n".join(lines)}


@mcp.tool(
    description=(
        "The company's public holidays. With no arguments: the next 5 from today. Use date (YYYY-MM-DD) to start from another day and "
        "limit (up to 50) for more; give end_date to list every holiday up to that day, e.g. the rest of the year. To check whether one "
        "particular day is a public holiday, pass the same day as date and end_date: an empty list means it isn't."),
    annotations=ToolAnnotations(title="Public holidays", readOnlyHint=True, openWorldHint=False))
async def public_holidays(date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 5) -> dict:
    params = {k: v for k, v in {"date": date, "end_date": end_date, "limit": limit if not end_date else None}.items() if v}
    res = await ems("GET", "/api/me/public-holidays", params=params)
    def when(h):
        n = h["days_from_start"]
        rel = "on the start day" if n == 0 and (date or end_date) else "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"
        return f"{h['weekday']} {h['date']}: {h['name']} ({rel})"
    if res["holidays"]:
        msg = "Public holidays:\n" + "\n".join(when(h) for h in res["holidays"])
    else:
        msg = f"No public holidays {'on ' + res['from'] if res['to'] == res['from'] else 'between ' + res['from'] + ' and ' + res['to'] if res['to'] else 'listed from ' + res['from'] + ' onward'}."
    return {**res, "message": msg}


CONFIRM_FIRST = (
    "This changes real project data that other people see. Never call it until the person has confirmed the exact change you read back to "
    "them in this conversation (project, task, and what changes). Only for projects the person is a listed manager of.")


@mcp.tool(annotations=ToolAnnotations(title="Projects I manage", readOnlyHint=True, openWorldHint=False))
async def my_managed_projects() -> dict:
    """List the projects the signed-in employee is a listed project MANAGER of (including On Hold and Completed ones), with every task: its id, status, estimated hours, dates, hours already logged on it, and whether it can be deleted (a task with logged hours can't be). Call this to find ids before adding, editing or deleting a task. Safe to call any time."""
    rows = await ems("GET", "/api/me/managed-projects")
    def line(p):
        tasks = ", ".join(f"{t['task_name']} ({t['status']})" for t in p["tasks"]) or "no tasks yet"
        return f"{p['project_name']} [{p['status']}]: {tasks}"
    return {"projects": rows, "message": ("\n".join(line(p) for p in rows)) or "You aren't listed as a manager of any project."}


@mcp.tool(
    description=("Add a task to a project the signed-in employee manages. " + CONFIRM_FIRST + " Needs the project_id from my_managed_projects and a "
                 "name; description, estimated_hours, start_date and end_date (YYYY-MM-DD, within the project's own dates) are optional; status is "
                 "'Not Started' (default), 'In Progress' or 'Completed'. A task with the same name already in the project is refused."),
    annotations=ToolAnnotations(title="Add a project task", readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def add_project_task(project_id: int, name: str, description: Optional[str] = None, estimated_hours: Optional[float] = None,
                           start_date: Optional[str] = None, end_date: Optional[str] = None, status: str = "Not Started") -> dict:
    body = {k: v for k, v in {"project_id": project_id, "name": name, "description": description, "estimated_hours": estimated_hours,
                              "start_date": start_date, "end_date": end_date, "status": status}.items() if v is not None}
    res = await ems("POST", "/api/me/project-tasks/add", json=body)
    bits = [res["status"]] + ([f"{res['estimated_hours']}h estimated"] if res.get("estimated_hours") else []) + (
        [f"{res['start_date']} to {res['end_date'] or '?'}"] if res.get("start_date") else [])
    return {**res, "message": f"Added task '{res['task_name']}' to {res['project_name']} ({', '.join(bits)})."}


@mcp.tool(
    description=("Change a task in a project the signed-in employee manages: only the fields you pass are changed. " + CONFIRM_FIRST + " "
                 "Pass project_id and task_id (from my_managed_projects) and any of name, description, estimated_hours, start_date, end_date, status. "
                 "To empty a field (description, estimated_hours, start_date, end_date) list its name in clear_fields instead of passing a value."),
    annotations=ToolAnnotations(title="Edit a project task", readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def update_project_task(project_id: int, task_id: int, name: Optional[str] = None, description: Optional[str] = None,
                              estimated_hours: Optional[float] = None, start_date: Optional[str] = None, end_date: Optional[str] = None,
                              status: Optional[str] = None, clear_fields: Optional[list[str]] = None) -> dict:
    body: dict = {"project_id": project_id, "task_id": task_id}
    body.update({k: v for k, v in {"name": name, "description": description, "estimated_hours": estimated_hours, "start_date": start_date,
                                   "end_date": end_date, "status": status}.items() if v is not None})
    for f in clear_fields or []:
        if f not in ("description", "estimated_hours", "start_date", "end_date"):
            raise ToolError("clear_fields can only list: description, estimated_hours, start_date, end_date.")
        body[f] = None
    res = await ems("POST", "/api/me/project-tasks/update", json=body)
    renamed = f" (was '{res['previous_name']}')" if "name" in res["changed"] else ""
    return {**res, "message": f"Updated task '{res['task_name']}'{renamed} in {res['project_name']}: changed {', '.join(res['changed'])}."}


@mcp.tool(
    description=("Permanently delete a task from a project the signed-in employee manages. " + CONFIRM_FIRST + " Deleting can't be undone, so say "
                 "so when you ask. A task that already has hours logged on it can't be deleted: set its status to 'Completed' instead."),
    annotations=ToolAnnotations(title="Delete a project task", readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
async def delete_project_task(project_id: int, task_id: int) -> dict:
    res = await ems("POST", "/api/me/project-tasks/delete", json={"project_id": project_id, "task_id": task_id})
    return {**res, "message": f"Deleted task '{res['task_name']}' from {res['project_name']}."}


@mcp.tool(
    description=(
        "The signed-in employee's To-Do list: everything outstanding right now, the same list as the Home To-Do in EMS, in three groups: "
        "overdue, today (due or happening today) and everything else waiting. It includes requests waiting for the person's approval, "
        "interviews, onboarding tasks, a draft timesheet and so on. Resignation and PIP approvals and offboarding tasks come back as COUNTS "
        "ONLY: never guess or ask for who they are, tell the person to open EMS for those. Read only: you cannot approve or reject anything "
        "from here, so don't offer to. Safe to call any time."),
    annotations=ToolAnnotations(title="My To-Do list", readOnlyHint=True, openWorldHint=False))
async def my_todos() -> dict:
    res = await ems("GET", "/api/me/todos")
    def line(i):
        extra = []
        if i.get("days_overdue"):
            extra.append(f"{i['days_overdue']} day(s) overdue")
        elif i.get("days_waiting"):
            extra.append(f"waiting {i['days_waiting']} day(s)")
        if i.get("due_date") and not i.get("days_overdue"):
            extra.append(f"due {i['due_date']}")
        if i.get("event_date") and i["event_date"] != i.get("due_date"):
            extra.append(f"on {i['event_date']}")
        return f"- {i['title']}" + (f" [{', '.join(extra)}]" if extra else "")
    parts = [f"To-Do for {res['date']}: {res['total_items']} item(s) outstanding."]
    for key, name in (("overdue", "Overdue"), ("today", "Today"), ("waiting", "Waiting")):
        if res[key]:
            parts.append(f"{name} ({len(res[key])}):\n" + "\n".join(line(i) for i in res[key]))
    if res["sensitive_counts"]:
        parts.append("Also waiting in EMS (names not shown here): " + ", ".join(f"{n} {k.lower()}" for k, n in res["sensitive_counts"].items()) + ".")
    if res["truncated"]:
        parts.append(f"Showing the first {res['listed']} of {res['total_items']}; the rest are in EMS.")
    if res["total_items"] == 0:
        parts = [f"Nothing outstanding on your To-Do list ({res['date']})."]
    return {**res, "message": "\n".join(parts)}


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    mcp.run(transport="streamable-http")
