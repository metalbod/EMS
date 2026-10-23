"""Claude / MCP access: routers/oauth.py, core/oauth.py, the OAuth branch of core/deps.py's get_current_user, migration
20261019_0001. The whole OAuth dance is driven through the real endpoints; only the browser is missing.
"""
import base64
import hashlib
import os
from urllib.parse import parse_qs, urlparse

import pytest

from core import oauth as oauth_core

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture(scope="session")
def test_institution(superadmin_token):
    """These tests switch the company-wide Claude access setting on and off, so they get their own company per xdist worker
    (found-or-created once and reused by later runs) instead of sharing ZZPYTEST."""
    from fastapi.testclient import TestClient
    import main as app_module
    c = TestClient(app_module.app)
    headers = {"Authorization": f"Bearer {superadmin_token}"}
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    code = f"ZZMCP{worker.upper()}"
    for inst in c.get("/api/institutions", headers=headers).json():
        if inst["code"] == code:
            return {"id": inst["id"], "code": code}
    res = c.post("/api/institutions", headers=headers, json={
        "name": f"ZZ MCP Test {worker}", "code": code, "contact_email": "zzmcp@example.com",
        "admin_username": f"zzmcp_admin_{worker}", "admin_full_name": "ZZ MCP Admin", "admin_password": "ZzPytest@123",
        "plan": "enterprise", "max_employees": 1_000_000})
    if res.status_code == 400 and "already exists" in res.text:
        for inst in c.get("/api/institutions", headers=headers).json():
            if inst["code"] == code:
                return {"id": inst["id"], "code": code}
    assert res.status_code == 201, res.text
    return {"id": res.json()["id"], "code": code}


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """The OAuth endpoints rate-limit per IP in process memory; every test here comes from the same address."""
    from routers import oauth as oauth_router
    oauth_router._hits.clear()
    yield


def test_registration_is_rate_limited(client):
    for _ in range(20):
        assert _register(client).status_code == 201
    assert _register(client).status_code == 429


def _set_enabled(client, hr_manager_auth, on: bool):
    res = client.put("/api/settings/mcp/enabled", headers=hr_manager_auth, json={"enabled": on})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def mcp_on(client, hr_manager_auth):
    _set_enabled(client, hr_manager_auth, True)
    yield
    _set_enabled(client, hr_manager_auth, False)


def _pkce():
    verifier = base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register(client, uris=(REDIRECT,), name="Claude"):
    res = client.post("/oauth/register", json={"client_name": name, "redirect_uris": list(uris)})
    return res


def _authorize(client, user_headers, client_id, challenge, scope="", state="st123", approve=True):
    return client.post("/api/oauth/authorize/approve", headers=user_headers, json={
        "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": challenge, "scope": scope,
        "state": state, "approve": approve})


def _connect(client, user_headers, scope=""):
    """Full flow up to tokens. Returns (token_json, client_id)."""
    client_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    res = _authorize(client, user_headers, client_id, challenge, scope)
    assert res.status_code == 200, res.text
    q = parse_qs(urlparse(res.json()["redirect_url"]).query)
    assert q["state"] == ["st123"]
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0], "client_id": client_id,
                                            "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    return tok.json(), client_id


def _bearer(t):
    return {"Authorization": f"Bearer {t['access_token']}"}


# --------------------------------------------------------------------------- discovery + registration
def test_metadata_advertises_pkce_and_endpoints(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint"].endswith("/oauth/token") and body["registration_endpoint"].endswith("/oauth/register")


def test_register_rejects_plain_http_and_accepts_https_and_localhost(client):
    assert _register(client, ("http://evil.example.com/cb",)).status_code == 400
    assert _register(client, ("javascript:alert(1)",)).status_code == 400
    assert _register(client, ("https://claude.ai/api/mcp/auth_callback",)).status_code == 201
    assert _register(client, ("http://localhost:6274/oauth/callback",)).status_code == 201


def test_authorize_page_refuses_unregistered_redirect(client):
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    base = {"client_id": client_id, "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256"}
    assert client.get("/oauth/authorize", params={**base, "redirect_uri": REDIRECT}).status_code == 200
    assert client.get("/oauth/authorize", params={**base, "redirect_uri": "https://evil.example.com/cb"}).status_code == 400
    assert client.get("/oauth/authorize", params={**base, "redirect_uri": REDIRECT, "code_challenge_method": "plain"}).status_code == 400
    assert client.get("/oauth/authorize", params={**base, "client_id": "nope", "redirect_uri": REDIRECT}).status_code == 400


# --------------------------------------------------------------------------- the happy path + what a token may reach
def test_full_flow_clock_in_out_and_leave_balance(client, mcp_on, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ MCP Clocker")
    tokens, _ = _connect(client, headers)
    assert tokens["token_type"] == "Bearer" and tokens["access_token"].startswith(oauth_core.ACCESS_PREFIX)
    assert set(tokens["scope"].split()) == set(oauth_core.DEFAULT_SCOPES)

    # No location shared: it's recorded as such, and the record shows it came from Claude.
    cin = client.post("/api/attendance/clock-in", headers=_bearer(tokens), json={})
    assert cin.status_code == 201, cin.text
    assert cin.json()["clock_in_source"] == "mcp" and cin.json()["clock_in_has_location"] is False
    assert cin.json()["employee_id"] == emp["employee_id"]

    mine = client.get("/api/attendance/mine", headers=_bearer(tokens))
    assert mine.status_code == 200 and mine.json()[0]["employee_id"] == emp["employee_id"]

    cout = client.post("/api/attendance/clock-out", headers=_bearer(tokens), json={"lat": 3.1, "lng": 101.7})
    assert cout.status_code == 200, cout.text
    assert cout.json()["clock_out_source"] == "mcp"

    bal = client.get("/api/leave/balances", headers=_bearer(tokens))
    assert bal.status_code == 200 and isinstance(bal.json(), list)


def test_token_cannot_reach_anything_outside_its_scopes(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Narrow")
    tokens, _ = _connect(client, headers)
    for method, path in [("GET", "/api/auth/me"), ("GET", "/api/employees"), ("GET", "/api/payroll/runs"), ("DELETE", "/api/attendance/mine")]:
        res = client.request(method, path, headers=_bearer(tokens))
        assert res.status_code in (403, 404, 405), (method, path, res.status_code)
        assert res.status_code != 200
    # and the approve endpoint can't be used with a token to mint a wider one
    res = client.post("/api/oauth/authorize/approve", headers=_bearer(tokens), json={
        "client_id": "x", "redirect_uri": REDIRECT, "code_challenge": "c" * 43})
    assert res.status_code == 403


def test_only_requested_scopes_are_granted(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Scoped")
    tokens, _ = _connect(client, headers, scope="leave:read bogus:scope")
    assert tokens["scope"] == "leave:read"
    assert client.get("/api/leave/balances", headers=_bearer(tokens)).status_code == 200
    assert client.post("/api/attendance/clock-in", headers=_bearer(tokens), json={}).status_code == 403


# --------------------------------------------------------------------------- the company switch
def test_off_by_default_and_blocks_approval(client, hr_manager_auth, employee_with_login):
    _set_enabled(client, hr_manager_auth, False)
    _, headers = employee_with_login(full_name="ZZ MCP Off")
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    res = _authorize(client, headers, client_id, challenge)
    assert res.status_code == 403 and "turned on" in res.json()["detail"]
    prev = client.get("/api/oauth/authorize/preview", headers=headers, params={"client_id": client_id, "redirect_uri": REDIRECT})
    assert prev.status_code == 403


def test_turning_it_off_kills_existing_tokens_at_once(client, hr_manager_auth, employee_with_login):
    _set_enabled(client, hr_manager_auth, True)
    _, headers = employee_with_login(full_name="ZZ MCP Killswitch")
    tokens, client_id = _connect(client, headers)
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 200
    _set_enabled(client, hr_manager_auth, False)
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 403
    refresh = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
    assert refresh.status_code == 400 and refresh.json()["error"] == "invalid_grant"
    # back on: the same access token works again (nothing was deleted, the switch is just checked per call)
    _set_enabled(client, hr_manager_auth, True)
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 200
    _set_enabled(client, hr_manager_auth, False)


def test_settings_are_hr_manager_only(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Plain")
    assert client.get("/api/settings/mcp", headers=headers).status_code == 403
    assert client.put("/api/settings/mcp/enabled", headers=headers, json={"enabled": True}).status_code == 403


# --------------------------------------------------------------------------- code + PKCE rules
def test_wrong_pkce_verifier_and_code_reuse_are_refused(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Pkce")
    client_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    code = parse_qs(urlparse(_authorize(client, headers, client_id, challenge).json()["redirect_url"]).query)["code"][0]
    base = {"grant_type": "authorization_code", "code": code, "client_id": client_id, "redirect_uri": REDIRECT}
    bad = client.post("/oauth/token", data={**base, "code_verifier": _pkce()[0]})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    # the failed attempt burned the code - even the right verifier can't use it now
    again = client.post("/oauth/token", data={**base, "code_verifier": verifier})
    assert again.status_code == 400


def test_code_is_bound_to_redirect_uri_and_client(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Bound")
    client_id = _register(client).json()["client_id"]
    other_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    code = parse_qs(urlparse(_authorize(client, headers, client_id, challenge).json()["redirect_url"]).query)["code"][0]
    res = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": other_id,
                                            "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert res.status_code == 400


def test_denying_redirects_with_access_denied(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Deny")
    client_id = _register(client).json()["client_id"]
    res = _authorize(client, headers, client_id, _pkce()[1], approve=False)
    q = parse_qs(urlparse(res.json()["redirect_url"]).query)
    assert q["error"] == ["access_denied"] and q["state"] == ["st123"]


def test_user_without_employee_record_cannot_connect(client, mcp_on, make_test_user):
    token, _ = make_test_user(role="hr_manager")      # a login with no linked employee
    client_id = _register(client).json()["client_id"]
    res = _authorize(client, {"Authorization": f"Bearer {token}"}, client_id, _pkce()[1])
    assert res.status_code == 403 and "employee record" in res.json()["detail"]


def test_superadmin_cannot_connect(client, mcp_on, superadmin_headers):
    client_id = _register(client).json()["client_id"]
    res = _authorize(client, superadmin_headers, client_id, _pkce()[1])
    assert res.status_code == 403


# --------------------------------------------------------------------------- refresh (30-day sliding) + revocation
def test_refresh_rotates_and_reuse_revokes_the_grant(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Refresh")
    first, client_id = _connect(client, headers)
    res = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client_id})
    assert res.status_code == 200, res.text
    second = res.json()
    assert second["access_token"] != first["access_token"] and second["refresh_token"] != first["refresh_token"]
    assert client.get("/api/attendance/mine", headers=_bearer(second)).status_code == 200

    # Presenting the old (already used) refresh token again = it leaked: the whole connection is cut.
    replay = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client_id})
    assert replay.status_code == 400
    assert client.get("/api/attendance/mine", headers=_bearer(second)).status_code == 401
    assert client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": client_id}).status_code == 400


def test_refresh_window_is_30_days_from_each_refresh(client, mcp_on, employee_with_login):
    from db import get_admin_db
    _, headers = employee_with_login(full_name="ZZ MCP Sliding")
    tokens, client_id = _connect(client, headers)
    conn = get_admin_db()
    try:
        row = conn.execute("SELECT expires_at, created_at FROM oauth_tokens WHERE token_hash=?",
                           (oauth_core.hash_token(tokens["refresh_token"]),)).fetchone()
        # an expired refresh token is refused
        conn.execute("UPDATE oauth_tokens SET expires_at=? WHERE token_hash=?", ("2000-01-01 00:00:00", oauth_core.hash_token(tokens["refresh_token"])))
        conn.commit()
    finally:
        conn.close()
    from datetime import datetime
    delta = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") - datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    assert 29 <= delta.days <= 30
    res = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
    assert res.status_code == 400


def test_expired_access_token_is_401(client, mcp_on, employee_with_login):
    from db import get_admin_db
    _, headers = employee_with_login(full_name="ZZ MCP Expired")
    tokens, _ = _connect(client, headers)
    conn = get_admin_db()
    try:
        conn.execute("UPDATE oauth_tokens SET expires_at=? WHERE token_hash=?", ("2000-01-01 00:00:00", oauth_core.hash_token(tokens["access_token"])))
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 401


def test_hr_can_list_and_disconnect_a_connection(client, mcp_on, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Listed")
    tokens, client_id = _connect(client, headers)
    listing = client.get("/api/settings/mcp", headers=hr_manager_auth).json()
    mine = [c for c in listing["connections"] if c["person"] == "ZZ MCP Listed"]
    assert len(mine) == 1 and mine[0]["app"] == "Claude"
    assert listing["enabled"] is True and listing["mcp_url"].endswith("/mcp")

    assert client.delete(f"/api/settings/mcp/connections/{mine[0]['id']}", headers=hr_manager_auth).status_code == 200
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 401
    assert client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}).status_code == 400
    assert client.delete(f"/api/settings/mcp/connections/{mine[0]['id']}", headers=hr_manager_auth).status_code == 404


def test_client_revocation_endpoint(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Revoke")
    tokens, _ = _connect(client, headers)
    assert client.post("/oauth/revoke", data={"token": tokens["refresh_token"]}).status_code == 200
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 401
    assert client.post("/oauth/revoke", data={"token": "not-a-token"}).status_code == 200


def test_deactivated_user_loses_access(client, mcp_on, hr_manager_auth, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ MCP Leaver")
    tokens, _ = _connect(client, headers)
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 200
    users = client.get("/api/users", headers=hr_manager_auth).json()
    uid = next(u["id"] for u in users if u.get("employee_id") == emp["employee_id"])
    res = client.put(f"/api/users/{uid}", headers=hr_manager_auth, json={"full_name": "ZZ MCP Leaver", "role": "employee", "employee_id": emp["employee_id"], "is_active": False})
    assert res.status_code == 200, res.text
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 401


def test_tokens_are_stored_hashed(client, mcp_on, employee_with_login):
    from db import get_admin_db
    _, headers = employee_with_login(full_name="ZZ MCP Hashed")
    tokens, _ = _connect(client, headers)
    conn = get_admin_db()
    try:
        assert conn.execute("SELECT 1 FROM oauth_tokens WHERE token_hash=?", (tokens["access_token"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM oauth_tokens WHERE token_hash=?", (oauth_core.hash_token(tokens["access_token"]),)).fetchone()
    finally:
        conn.close()


def test_whoami_works_for_any_scope_and_only_for_tokens(client, mcp_on, employee_with_login):
    emp, headers = employee_with_login(full_name="ZZ MCP Who")
    tokens, _ = _connect(client, headers, scope="leave:read")
    who = client.get("/api/oauth/whoami", headers=_bearer(tokens))
    assert who.status_code == 200
    body = who.json()
    assert body["employee_id"] == emp["employee_id"] and body["scopes"] == ["leave:read"] and body["timezone"]
    assert client.get("/api/oauth/whoami", headers=headers).status_code == 403          # a normal login isn't a Claude connection
    assert client.get("/api/oauth/whoami", headers={"Authorization": "Bearer emsat_nope"}).status_code == 401


def test_leave_balances_through_claude_are_own_only_even_for_hr(client, mcp_on, hr_manager_auth, make_test_employee, test_institution):
    """HR's normal view of /api/leave/balances is the whole company; a Claude token must still only see its owner's."""
    mine, other = make_test_employee(), make_test_employee()
    username = f"zzmcphr_{mine['employee_id'].lower()}"
    res = client.post("/api/users", headers=hr_manager_auth, json={
        "username": username, "full_name": mine["full_name"], "password": "ZzPytest@123", "role": "hr_manager",
        "employee_id": mine["employee_id"]})
    assert res.status_code == 201, res.text
    try:
        login = client.post("/api/auth/login", json={"username": username, "password": "ZzPytest@123", "institution_code": test_institution["code"]})
        hr_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        # sanity: this HR login can see more than one person normally
        client.get("/api/leave/balances", headers=hr_headers)
        tokens, _ = _connect(client, hr_headers)
        rows = client.get("/api/leave/balances", headers=_bearer(tokens)).json()
        assert {r["employee_id"] for r in rows} <= {mine["employee_id"]}
        assert other["employee_id"] not in {r["employee_id"] for r in rows}
        # and asking for someone else's by id doesn't widen it
        rows = client.get("/api/leave/balances", headers=_bearer(tokens), params={"employee_id": other["employee_id"], "team": "true"}).json()
        assert {r["employee_id"] for r in rows} <= {mine["employee_id"]}
    finally:
        client.delete(f"/api/users/{res.json()['id']}", headers=hr_manager_auth)


def test_timesheet_tools_through_claude_respect_their_scopes(client, mcp_on, employee_with_login, make_test_project, make_test_project_task):
    emp, headers = employee_with_login(full_name="ZZ MCP Timesheet")
    project = make_test_project(name="ZZ MCP Project", is_open_to_all=True)
    task = make_test_project_task(project["id"])
    log = {"project_id": project["id"], "task_id": task["id"], "hours": 2}

    # a connection made before timesheets existed (read-only attendance) is told to reconnect, and nothing is written
    old, _ = _connect(client, headers, scope="attendance:read")
    res = client.post("/api/me/timesheet/log-hours", headers=_bearer(old), json=log)
    assert res.status_code == 403 and "reconnect" in res.json()["detail"]
    assert client.get("/api/me/week-hours", headers=_bearer(old)).status_code == 403

    read_only, _ = _connect(client, headers, scope="timesheet:read")
    assert client.get("/api/me/timesheet/projects", headers=_bearer(read_only)).status_code == 200
    assert client.get("/api/me/week-hours", headers=_bearer(read_only)).status_code == 200
    assert client.post("/api/me/timesheet/log-hours", headers=_bearer(read_only), json=log).status_code == 403

    full, _ = _connect(client, headers)                                           # default scopes include both
    res = client.post("/api/me/timesheet/log-hours", headers=_bearer(full), json=log)
    assert res.status_code == 201, res.text
    assert client.get("/api/me/week-hours", headers=_bearer(full)).json()["logged_hours"] == 2
    # the general timesheet endpoints stay closed to a Claude token
    assert client.get("/api/timesheets", headers=_bearer(full)).status_code == 403
    assert client.post("/api/timesheets", headers=_bearer(full), json={"employee_id": emp["employee_id"], "period_start": "2026-01-05", "period_end": "2026-01-11"}).status_code == 403


def test_colleagues_on_leave_needs_its_own_scope(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Colleagues")
    narrow, _ = _connect(client, headers, scope="leave:read")
    res = client.get("/api/me/leave-colleagues", headers=_bearer(narrow))
    assert res.status_code == 403 and "reconnect" in res.json()["detail"]
    scoped, _ = _connect(client, headers, scope="leave:colleagues")
    assert client.get("/api/me/leave-colleagues", headers=_bearer(scoped)).status_code == 200
    # holding it doesn't open anything else about other people
    assert client.get("/api/leave/calendar", headers=_bearer(scoped), params={"year": 2031, "month": 3}).status_code == 403
    assert client.get("/api/leave/applications", headers=_bearer(scoped)).status_code == 403


def test_public_holidays_needs_its_own_scope(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Holidays")
    narrow, _ = _connect(client, headers, scope="leave:read")
    res = client.get("/api/me/public-holidays", headers=_bearer(narrow))
    assert res.status_code == 403 and "reconnect" in res.json()["detail"]
    scoped, _ = _connect(client, headers, scope="holidays:read")
    assert client.get("/api/me/public-holidays", headers=_bearer(scoped)).status_code == 200
    assert client.get("/api/holidays", headers=_bearer(scoped)).status_code == 403       # the general list stays closed to Claude


# --------------------------------------------------------------------------- hard 30-day limit
def _age_grant(token_json, days):
    """Make the grant behind these tokens `days` old, the way time passing would (used_at/expiry columns are untouched)."""
    from db import get_admin_db
    conn = get_admin_db()
    try:
        row = conn.execute("SELECT grant_id FROM oauth_tokens WHERE token_hash=?", (oauth_core.hash_token(token_json["access_token"]),)).fetchone()
        conn.execute("UPDATE oauth_grants SET created_at=? WHERE id=?", (oauth_core.now_str(-days * 86400), row["grant_id"]))
        conn.commit()
        return row["grant_id"]
    finally:
        conn.close()


def test_a_connection_stops_at_the_hard_limit_however_often_it_is_used(client, mcp_on, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Old")
    tokens, client_id = _connect(client, headers)
    assert oauth_core.GRANT_MAX_DAYS == 30
    _age_grant(tokens, 29)
    assert client.get("/api/attendance/mine", headers=_bearer(tokens)).status_code == 200          # day 29: still fine
    refreshed = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
    assert refreshed.status_code == 200
    fresh = refreshed.json()

    _age_grant(fresh, 31)                                                                           # day 31, in constant use
    assert client.get("/api/attendance/mine", headers=_bearer(fresh)).status_code == 401
    again = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": fresh["refresh_token"], "client_id": client_id})
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant" and "30-day limit" in again.json()["error_description"]
    # and it is gone from HR's list rather than lingering as a dead connection
    assert not [c for c in client.get("/api/settings/mcp", headers=hr_manager_auth).json()["connections"] if c["person"] == "ZZ MCP Old"]


def test_connecting_again_after_the_limit_starts_a_fresh_window(client, mcp_on, hr_manager_auth, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Again")
    old, _ = _connect(client, headers)
    _age_grant(old, 40)
    assert client.get("/api/attendance/mine", headers=_bearer(old)).status_code == 401
    new, _ = _connect(client, headers)
    assert client.get("/api/attendance/mine", headers=_bearer(new)).status_code == 200
    mine = [c for c in client.get("/api/settings/mcp", headers=hr_manager_auth).json()["connections"] if c["person"] == "ZZ MCP Again"]
    assert len(mine) == 1
    from datetime import datetime, timedelta
    assert mine[0]["reconnect_by"] == (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")


def test_authorize_page_handles_a_company_that_requires_microsoft(client):
    """The Allow page itself is server-sent HTML: check the pieces the Microsoft-required mode relies on are in it."""
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    page = client.get("/oauth/authorize", params={"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code",
                                                  "code_challenge": challenge, "code_challenge_method": "S256"}).text
    for marker in ("sso_required", "pwFields", "emergencyLink", "Use emergency password access", "Your company requires Microsoft sign-in."):
        assert marker in page


# --------------------------------------------------------------------------- project managers' task tools
def _task_setup(client, employee_with_login, make_test_project):
    boss, boss_h = employee_with_login(full_name="ZZ MCP Pm Boss")
    project = make_test_project(name="ZZ MCP Pm Project", manager_ids=[boss["employee_id"]], is_open_to_all=False, start_date="2027-01-01", end_date="2027-06-30")
    return boss, boss_h, project


def test_project_manager_adds_edits_and_deletes_tasks_through_claude(client, mcp_on, employee_with_login, make_test_project):
    from db import get_admin_db
    boss, boss_h, project = _task_setup(client, employee_with_login, make_test_project)
    tokens, _ = _connect(client, boss_h)
    auth = _bearer(tokens)

    managed = client.get("/api/me/managed-projects", headers=auth).json()
    mine = next(p for p in managed if p["project_id"] == project["id"])          # listed although the boss isn't a member of it
    assert mine["tasks"] == [] and mine["start_date"] == "2027-01-01"

    add = client.post("/api/me/project-tasks/add", headers=auth, json={"project_id": project["id"], "name": "  ZZ Claude Task  ", "estimated_hours": 8,
                                                                       "start_date": "2027-02-01", "description": "Built by Claude"})
    assert add.status_code == 201, add.text
    tid = add.json()["task_id"]
    assert add.json()["task_name"] == "ZZ Claude Task" and add.json()["status"] == "Not Started"

    dup = client.post("/api/me/project-tasks/add", headers=auth, json={"project_id": project["id"], "name": "zz claude task"})
    assert dup.status_code == 400 and "already has a task" in dup.json()["detail"]

    # partial update: only the status changes, the rest stays; null clears a field
    upd = client.post("/api/me/project-tasks/update", headers=auth, json={"project_id": project["id"], "task_id": tid, "status": "In Progress"})
    assert upd.status_code == 200 and upd.json()["changed"] == ["status"] and upd.json()["estimated_hours"] == 8
    cleared = client.post("/api/me/project-tasks/update", headers=auth, json={"project_id": project["id"], "task_id": tid, "estimated_hours": None, "end_date": "2027-02-20"})
    assert cleared.json()["estimated_hours"] is None and cleared.json()["end_date"] == "2027-02-20" and cleared.json()["status"] == "In Progress"
    renamed = client.post("/api/me/project-tasks/update", headers=auth, json={"project_id": project["id"], "task_id": tid, "name": "ZZ Claude Renamed"})
    assert renamed.json()["task_name"] == "ZZ Claude Renamed" and renamed.json()["previous_name"] == "ZZ Claude Task"
    assert client.post("/api/me/project-tasks/update", headers=auth, json={"project_id": project["id"], "task_id": tid}).status_code == 400   # nothing to change

    gone = client.post("/api/me/project-tasks/delete", headers=auth, json={"project_id": project["id"], "task_id": tid})
    assert gone.status_code == 200 and gone.json()["deleted"] is True
    assert client.post("/api/me/project-tasks/delete", headers=auth, json={"project_id": project["id"], "task_id": tid}).status_code == 404

    conn = get_admin_db()                                         # every change is recorded as made via Claude
    try:
        rows = conn.execute("SELECT action, detail FROM entity_audit_log WHERE module='Projects' AND entity_id=? ORDER BY id", (str(project["id"]),)).fetchall()
    finally:
        conn.close()
    assert [r["action"] for r in rows][-6:].count("Task added") >= 1 and all("(via Claude)" in r["detail"] for r in rows if r["action"].startswith("Task"))


@pytest.mark.parametrize("body,fragment", [
    ({"name": ""}, "needs a name"),
    ({"name": "ZZ X", "status": "Done-ish"}, "Status must be one of"),
    ({"name": "ZZ X", "estimated_hours": -1}, "between 0 and 10000"),
    ({"name": "ZZ X", "start_date": "tomorrow"}, "Start date must look like"),
    ({"name": "ZZ X", "start_date": "2026-01-01"}, "before the project's start date"),
    ({"name": "ZZ X", "start_date": "2027-03-01", "end_date": "2027-02-01"}, "End date must be on or after"),
])
def test_task_tool_input_rules(client, mcp_on, employee_with_login, make_test_project, body, fragment):
    _, boss_h, project = _task_setup(client, employee_with_login, make_test_project)
    tokens, _ = _connect(client, boss_h)
    res = client.post("/api/me/project-tasks/add", headers=_bearer(tokens), json={"project_id": project["id"], **body})
    assert res.status_code == 400 and fragment in res.json()["detail"], res.text


def test_only_the_projects_own_manager_may_use_the_task_tools(client, mcp_on, hr_manager_auth, employee_with_login, make_test_project,
                                                              make_test_employee, test_institution):
    _, boss_h, project = _task_setup(client, employee_with_login, make_test_project)
    _, stranger_h = employee_with_login(full_name="ZZ MCP Pm Stranger")
    tokens, _ = _connect(client, stranger_h)
    auth = _bearer(tokens)
    assert client.get("/api/me/managed-projects", headers=auth).json() == []
    for path, body in (("add", {"name": "ZZ Nope"}), ("update", {"task_id": 1, "name": "ZZ Nope"}), ("delete", {"task_id": 1})):
        res = client.post(f"/api/me/project-tasks/{path}", headers=auth, json={"project_id": project["id"], **body})
        assert res.status_code == 403 and "own managers" in res.json()["detail"], (path, res.text)
    assert client.post("/api/me/project-tasks/add", headers=auth, json={"project_id": 999999999, "name": "ZZ Nope"}).status_code == 403   # same answer: no existence leak

    # even an HR Manager who is not one of the project's managers is sent to the web screen: the Claude rule is the narrower one
    emp = make_test_employee(full_name="ZZ MCP Hr Emp")
    uname = f"zzmcphr_{emp['employee_id'].lower()}"
    created = client.post("/api/users", headers=hr_manager_auth, json={"username": uname, "full_name": emp["full_name"], "password": "ZzPytest@123",
                                                                       "role": "hr_manager", "employee_id": emp["employee_id"]})
    assert created.status_code == 201, created.text
    try:
        login = client.post("/api/auth/login", json={"username": uname, "password": "ZzPytest@123", "institution_code": test_institution["code"]})
        assert login.status_code == 200, login.text
        hr_h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.post(f"/api/projects/{project['id']}/tasks", headers=hr_h, json={"name": "ZZ Web Ok"}).status_code == 201   # the web rule allows HR
        hr_tokens, _ = _connect(client, hr_h)
        res = client.post("/api/me/project-tasks/add", headers=_bearer(hr_tokens), json={"project_id": project["id"], "name": "ZZ Claude No"})
        assert res.status_code == 403 and "own managers" in res.json()["detail"]
    finally:
        client.delete(f"/api/users/{created.json()['id']}", headers=hr_manager_auth)


def test_task_tools_need_their_scope_and_the_general_endpoints_stay_closed(client, mcp_on, employee_with_login, make_test_project):
    boss, boss_h, project = _task_setup(client, employee_with_login, make_test_project)
    narrow, _ = _connect(client, boss_h, scope="timesheet:read")                 # a connection made before projects:write existed
    res = client.get("/api/me/managed-projects", headers=_bearer(narrow))
    assert res.status_code == 403 and "reconnect" in res.json()["detail"]
    assert client.post("/api/me/project-tasks/add", headers=_bearer(narrow), json={"project_id": project["id"], "name": "ZZ No"}).status_code == 403

    scoped, _ = _connect(client, boss_h, scope="projects:write")
    assert client.get("/api/me/managed-projects", headers=_bearer(scoped)).status_code == 200
    # holding it opens nothing else: the web endpoints (ids in their paths) are still unreachable for a Claude token
    assert client.post(f"/api/projects/{project['id']}/tasks", headers=_bearer(scoped), json={"name": "ZZ Sneaky"}).status_code == 403
    assert client.get("/api/projects", headers=_bearer(scoped)).status_code == 403


def test_a_task_with_logged_hours_cannot_be_deleted_through_claude(client, mcp_on, employee_with_login, make_test_project, hr_manager_auth):
    boss, boss_h, project = _task_setup(client, employee_with_login, make_test_project)
    mate, mate_h = employee_with_login(full_name="ZZ MCP Pm Mate")
    assert client.put(f"/api/projects/{project['id']}", headers=hr_manager_auth, json={
        "name": project["name"], "status": "Active", "manager_ids": [boss["employee_id"]], "member_ids": [mate["employee_id"]],
        "start_date": "2027-01-01", "end_date": "2027-06-30"}).status_code == 200
    tokens, _ = _connect(client, boss_h)
    auth = _bearer(tokens)
    task = client.post("/api/me/project-tasks/add", headers=auth, json={"project_id": project["id"], "name": "ZZ MCP Worked"}).json()
    assert client.post("/api/me/timesheet/log-hours", headers=mate_h, json={"project_id": project["id"], "task_id": task["task_id"], "hours": 1}).status_code == 201
    managed = next(p for p in client.get("/api/me/managed-projects", headers=auth).json() if p["project_id"] == project["id"])
    t = next(t for t in managed["tasks"] if t["task_id"] == task["task_id"])
    assert t["logged_hours"] == 1 and t["can_delete"] is False
    res = client.post("/api/me/project-tasks/delete", headers=auth, json={"project_id": project["id"], "task_id": task["task_id"]})
    assert res.status_code == 400 and "Completed" in res.json()["detail"]


def test_todo_tool_needs_its_scope_and_cannot_reach_the_approval_actions(client, mcp_on, employee_with_login):
    _, headers = employee_with_login(full_name="ZZ MCP Todo")
    narrow, _ = _connect(client, headers, scope="leave:read")
    res = client.get("/api/me/todos", headers=_bearer(narrow))
    assert res.status_code == 403 and "reconnect" in res.json()["detail"]
    scoped, _ = _connect(client, headers, scope="todos:read")
    ok = client.get("/api/me/todos", headers=_bearer(scoped))
    assert ok.status_code == 200 and {"overdue", "today", "waiting", "sensitive_counts"} <= set(ok.json())
    # read only: the widget's own endpoint and every approve/reject route stay closed to a Claude token
    assert client.get("/api/todos", headers=_bearer(scoped)).status_code == 403
    assert client.patch("/api/leave/applications/1/status", headers=_bearer(scoped), json={"status": "Approved"}).status_code == 403
