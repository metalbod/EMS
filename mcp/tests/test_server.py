"""Unit tests for the MCP server with EMS faked by an httpx MockTransport. Run from this folder: `pytest` (needs mcp, httpx, pytest).
The real round trip against EMS is covered by the main repo's tests/test_mcp_oauth.py plus a manual end-to-end run (see README)."""
import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fake_ems(monkeypatch):
    """Routes EMS calls to `handlers[(METHOD, path)]`, each returning (status, json). Records the calls it got."""
    box = {"handlers": {}, "calls": []}

    def handler(request: httpx.Request):
        box["calls"].append((request.method, request.url.path, dict(request.url.params), request.headers.get("authorization"), request.content))
        status, body = box["handlers"].get((request.method, request.url.path), (404, {"detail": "no handler"}))
        return httpx.Response(status, json=body)

    monkeypatch.setattr(server, "_http", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ems.test"))
    server._whoami_cache.clear()
    monkeypatch.setattr(server, "get_access_token", lambda: AccessToken(
        token="emsat_abc", client_id="EMP1", scopes=["attendance:clock"], claims={"timezone": "Asia/Kuala_Lumpur"}))
    return box


def test_verifier_accepts_what_ems_accepts_and_caches(fake_ems):
    fake_ems["handlers"][("GET", "/api/oauth/whoami")] = (200, {"employee_id": "EMP1", "scopes": ["leave:read"], "timezone": "UTC", "expires_at": "2030-01-01 00:00:00"})
    v = server.EmsTokenVerifier()
    tok = run(v.verify_token("emsat_good"))
    assert tok.client_id == "EMP1" and tok.scopes == ["leave:read"] and tok.expires_at > 1_800_000_000
    run(v.verify_token("emsat_good"))
    assert len([c for c in fake_ems["calls"] if c[1] == "/api/oauth/whoami"]) == 1      # second one came from the short cache


def test_verifier_rejects_what_ems_rejects(fake_ems):
    fake_ems["handlers"][("GET", "/api/oauth/whoami")] = (401, {"detail": "Invalid or expired access token"})
    assert run(server.EmsTokenVerifier().verify_token("emsat_bad")) is None
    fake_ems["handlers"][("GET", "/api/oauth/whoami")] = (403, {"detail": "Claude access is turned off for your company."})
    assert run(server.EmsTokenVerifier().verify_token("emsat_off")) is None


def test_clock_in_without_location_forwards_the_callers_token_and_says_so(fake_ems):
    fake_ems["handlers"][("POST", "/api/attendance/clock-in")] = (201, {
        "clock_in_at": "2026-10-14T01:05:00", "work_date": "2026-10-14", "status": "Late", "shift_name": "Day",
        "outside_geofence": False, "clock_in_has_location": False})
    out = run(server.clock_in())
    assert out["clock_in_time"] == "09:05"                       # 01:05 UTC shown in the company's timezone
    assert "marked Late" in out["message"] and "no location recorded" in out["message"]
    method, path, _, auth, body = fake_ems["calls"][0]
    assert (method, path, auth) == ("POST", "/api/attendance/clock-in", "Bearer emsat_abc")
    assert b'"lat":null' in body.replace(b" ", b"")


def test_clock_in_passes_location_and_flags_outside_geofence(fake_ems):
    fake_ems["handlers"][("POST", "/api/attendance/clock-in")] = (201, {
        "clock_in_at": "2026-10-14T00:55:00", "work_date": "2026-10-14", "status": "Present", "outside_geofence": True, "clock_in_has_location": True})
    out = run(server.clock_in(3.139, 101.6869))
    assert out["outside_geofence"] is True and "outside the workplace area" in out["message"]
    assert b"3.139" in fake_ems["calls"][0][4]


@pytest.mark.parametrize("lat,lng", [(3.1, None), (None, 101.6), (91, 0), (0, 181)])
def test_bad_locations_are_refused_before_calling_ems(fake_ems, lat, lng):
    with pytest.raises(ToolError):
        run(server.clock_in(lat, lng))
    assert fake_ems["calls"] == []


def test_ems_messages_pass_through_and_expiry_asks_to_reconnect(fake_ems):
    fake_ems["handlers"][("POST", "/api/attendance/clock-in")] = (400, {"detail": "Already clocked in for this work day"})
    with pytest.raises(ToolError, match="Already clocked in"):
        run(server.clock_in())
    fake_ems["handlers"][("POST", "/api/attendance/clock-in")] = (401, {"detail": "Invalid or expired access token"})
    with pytest.raises(ToolError, match="Reconnect"):
        run(server.clock_in())
    fake_ems["handlers"][("POST", "/api/attendance/clock-in")] = (403, {"detail": "Claude access is turned off for your company. Ask HR to enable it in Settings."})
    with pytest.raises(ToolError, match="turned off"):
        run(server.clock_in())
    fake_ems["handlers"][("POST", "/api/attendance/clock-in")] = (500, {"detail": "boom: internal stack trace"})
    with pytest.raises(ToolError) as e:
        run(server.clock_in())
    assert "boom" not in str(e.value)                              # server internals are never shown to the person


def test_clock_out_reports_worked_time(fake_ems):
    fake_ems["handlers"][("POST", "/api/attendance/clock-out")] = (200, {
        "clock_in_at": "2026-10-14T01:00:00", "clock_out_at": "2026-10-14T10:30:00", "worked_minutes": 570, "work_date": "2026-10-14"})
    out = run(server.clock_out())
    assert out["message"] == "Clocked out at 18:30. Worked 9h 30m." and out["worked_minutes"] == 570


def _today_utc_row(**kw):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    local_today = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
    return {"work_date": local_today, "clock_in_at": "2026-10-14T01:00:00", "clock_out_at": None, "worked_minutes": None, "status": "Present", **kw}


def test_attendance_today_states(fake_ems):
    path = ("GET", "/api/attendance/mine")
    fake_ems["handlers"][path] = (200, [])
    assert run(server.attendance_today())["state"] == "not_clocked_in"
    fake_ems["handlers"][path] = (200, [_today_utc_row()])
    out = run(server.attendance_today())
    assert out["state"] == "clocked_in" and out["clock_in_time"] == "09:00"
    fake_ems["handlers"][path] = (200, [_today_utc_row(clock_out_at="2026-10-14T09:00:00", worked_minutes=480)])
    out = run(server.attendance_today())
    assert out["state"] == "clocked_out" and out["worked_minutes"] == 480
    # an open clock-in from an earlier work day (shift crossing midnight) still counts as clocked in
    fake_ems["handlers"][path] = (200, [_today_utc_row(work_date="2000-01-01")])
    assert run(server.attendance_today())["state"] == "clocked_in"


def test_leave_balance_matches_the_web_screens_arithmetic(fake_ems):
    fake_ems["handlers"][("GET", "/api/leave/balances")] = (200, [
        {"leave_type_name": "Annual", "year": 2026, "entitled_days": 14, "accrued_days": 7.0, "carried_forward_days": 3, "carried_forward_remaining": 2,
         "carried_forward_expires_on": "2026-03-31", "used_days": 4},
        {"leave_type_name": "Sick", "year": 2026, "entitled_days": 14, "accrued_days": None, "carried_forward_days": 0, "used_days": 1}])
    out = run(server.leave_balance(2026))
    annual, sick = out["balances"]
    assert annual["available_days"] == 6.0 and annual["carried_forward_remaining"] == 2      # accrued 7 + carried 3 - used 4
    assert sick["available_days"] == 13.0
    assert fake_ems["calls"][0][2] == {"year": "2026"}
    assert "Annual: 6.0 day(s)" in out["message"]
