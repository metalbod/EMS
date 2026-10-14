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
