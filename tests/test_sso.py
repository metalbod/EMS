"""Sign in with Microsoft (Entra ID): routers/sso.py, core/sso.py, migration 20261017_0001.

Microsoft itself is faked: the token exchange and the signing key are replaced, and ID tokens are signed here with a
throwaway RSA key, so every other check (signature, issuer, audience, tenant, nonce, expiry, state, linking) runs for real.
"""
import hashlib
import os
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from core import sso as sso_core
from db import get_admin_db

@pytest.fixture(scope="session")
def test_institution(superadmin_token):
    """These tests switch company-wide sign-in settings on and off (including "require Microsoft", which refuses passwords), so
    they must never share ZZPYTEST with the rest of the suite or with each other across xdist workers: each worker gets its own
    company (ZZSSO + worker id), found-or-created once and reused by later runs."""
    from fastapi.testclient import TestClient
    import main as app_module
    c = TestClient(app_module.app)
    headers = {"Authorization": f"Bearer {superadmin_token}"}
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    code = f"ZZSSO{worker.upper()}"
    for inst in c.get("/api/institutions", headers=headers).json():
        if inst["code"] == code:
            return {"id": inst["id"], "code": code}
    res = c.post("/api/institutions", headers=headers, json={
        "name": f"ZZ SSO Test {worker}", "code": code, "contact_email": "zzsso@example.com",
        "admin_username": f"zzsso_admin_{worker}", "admin_full_name": "ZZ SSO Admin", "admin_password": "ZzPytest@123",
        "plan": "enterprise", "max_employees": 1_000_000})
    if res.status_code == 400 and "already exists" in res.text:
        for inst in c.get("/api/institutions", headers=headers).json():
            if inst["code"] == code:
                return {"id": inst["id"], "code": code}
    assert res.status_code == 201, res.text
    return {"id": res.json()["id"], "code": code}


TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pending_nonce(state):
    conn = get_admin_db()
    try:
        row = conn.execute("SELECT nonce, mode FROM sso_pending WHERE token_hash=?", (hashlib.sha256(state.encode()).hexdigest(),)).fetchone()
        return row["nonce"] if row else None
    finally:
        conn.close()


def id_token(_nonce, key=KEY, **over):
    now = int(time.time())
    claims = {"iss": sso_core.issuer(TENANT), "aud": CLIENT, "sub": "sub-1", "oid": f"oid-{os.urandom(4).hex()}", "tid": TENANT,
              "iat": now, "nbf": now, "exp": now + 3600, "nonce": _nonce, "name": "Some One"}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture(autouse=True)
def fake_microsoft(monkeypatch):
    """Microsoft's token endpoint hands back whatever id_token the test queues; its published key is KEY's public half."""
    box = {"id_token": None, "exchanges": []}

    def fake_exchange(tenant_id, client_id, secret, code, redirect_uri, verifier):
        box["exchanges"].append({"tenant": tenant_id, "client": client_id, "secret": secret, "code": code, "redirect_uri": redirect_uri, "verifier": verifier})
        if box["id_token"] is None:
            raise sso_core.SsoError("failed", "Microsoft refused the sign-in (invalid_grant)")
        return {"id_token": box["id_token"]}

    monkeypatch.setattr(sso_core, "exchange_code", fake_exchange)
    monkeypatch.setattr(sso_core, "signing_key", lambda tenant, token: KEY.public_key())
    return box


@pytest.fixture
def sso_on(client, hr_manager_auth):
    """The test company with Microsoft sign-in configured, tested and switched on; removed afterwards."""
    assert client.put("/api/settings/sso", headers=hr_manager_auth, json={"tenant_id": TENANT, "client_id": CLIENT, "client_secret": "s3cret-value"}).status_code == 200
    yield
    client.delete("/api/settings/sso", headers=hr_manager_auth)


def run_test_signin(client, hr_manager_auth, fake_microsoft, **token_over):
    url = client.post("/api/settings/sso/test-start", headers=hr_manager_auth).json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    fake_microsoft["id_token"] = id_token(_pending_nonce(state), **token_over)
    return client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)


@pytest.fixture
def sso_enabled(client, hr_manager_auth, sso_on, fake_microsoft):
    assert run_test_signin(client, hr_manager_auth, fake_microsoft, email="tester@example.com").status_code == 302
    assert client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": True}).status_code == 200


@pytest.fixture
def make_user(client, hr_manager_auth, test_institution):
    made = []

    def _make(email, role="employee", **over):
        body = {"username": f"zzsso_{os.urandom(4).hex()}", "full_name": "ZZ SSO User", "password": "ZzPytest@123", "role": role, "email": email}
        body.update(over)
        res = client.post("/api/users", headers=hr_manager_auth, json=body)
        assert res.status_code == 201, res.text
        made.append(res.json()["id"])
        return res.json()

    yield _make
    for uid in made:
        client.delete(f"/api/users/{uid}", headers=hr_manager_auth)


def begin_login(client, test_institution):
    res = client.get("/api/auth/sso/start", params={"institution_code": test_institution["code"]}, follow_redirects=False)
    assert res.status_code == 302, res.text
    url = res.headers["location"]
    return parse_qs(urlparse(url).query), url


def sign_in(client, test_institution, fake_microsoft, **token_over):
    q, _ = begin_login(client, test_institution)
    state = q["state"][0]
    fake_microsoft["id_token"] = id_token(_pending_nonce(state), **token_over)
    return client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False), state


def code_from(res):
    loc = res.headers["location"]
    assert loc.startswith("/?sso_code="), loc
    return parse_qs(urlparse(loc).query)["sso_code"][0]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def test_settings_need_hr_manager_and_valid_guids_and_never_return_the_secret(client, hr_manager_auth, sso_on, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    employee = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    assert client.get("/api/settings/sso", headers=employee).status_code == 403
    assert client.put("/api/settings/sso", headers=employee, json={"tenant_id": TENANT, "client_id": CLIENT, "client_secret": "x"}).status_code == 403

    body = client.get("/api/settings/sso", headers=hr_manager_auth).json()
    assert body["configured"] and body["tenant_id"] == TENANT and body["client_id"] == CLIENT and body["has_secret"] is True
    assert "s3cret-value" not in str(body) and "client_secret" not in body
    assert body["enabled"] is False and body["redirect_uri"].endswith("/api/auth/sso/callback")

    for bad in ({"tenant_id": "not-a-guid", "client_id": CLIENT}, {"tenant_id": TENANT, "client_id": "nope"}):
        assert client.put("/api/settings/sso", headers=hr_manager_auth, json={**bad, "client_secret": "x"}).status_code == 400


def test_the_secret_is_stored_encrypted_and_blank_keeps_it(client, hr_manager_auth, sso_on):
    conn = get_admin_db()
    try:
        stored = conn.execute("SELECT client_secret_encrypted FROM institution_sso ORDER BY id DESC LIMIT 1").fetchone()["client_secret_encrypted"]
    finally:
        conn.close()
    assert "s3cret-value" not in stored
    assert client.put("/api/settings/sso", headers=hr_manager_auth, json={"tenant_id": TENANT, "client_id": CLIENT, "client_secret": ""}).status_code == 200


def test_it_cannot_be_turned_on_until_a_test_sign_in_succeeds(client, hr_manager_auth, sso_on, fake_microsoft):
    assert client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": True}).status_code == 400
    failed = run_test_signin(client, hr_manager_auth, fake_microsoft, aud="someone-else")
    assert failed.headers["location"] == "/#settings-sso"
    s = client.get("/api/settings/sso", headers=hr_manager_auth).json()
    assert s["last_test_ok"] is False and s["last_test_detail"]
    assert client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": True}).status_code == 400

    ok = run_test_signin(client, hr_manager_auth, fake_microsoft, email="Kenneth@Example.com")
    assert ok.headers["location"] == "/#settings-sso"
    s = client.get("/api/settings/sso", headers=hr_manager_auth).json()
    assert s["last_test_ok"] is True and "kenneth@example.com" in s["last_test_detail"]
    assert client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": True}).json()["enabled"] is True


def test_changing_the_entra_values_switches_it_off_and_needs_a_new_test(client, hr_manager_auth, sso_enabled):
    assert client.get("/api/settings/sso", headers=hr_manager_auth).json()["enabled"] is True
    client.put("/api/settings/sso", headers=hr_manager_auth, json={"tenant_id": TENANT, "client_id": "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee", "client_secret": ""})
    s = client.get("/api/settings/sso", headers=hr_manager_auth).json()
    assert s["enabled"] is False and s["last_test_ok"] is False
    # re-saving identical values changes nothing
    client.put("/api/settings/sso", headers=hr_manager_auth, json={"tenant_id": TENANT, "client_id": CLIENT, "client_secret": "again"})
    assert client.get("/api/settings/sso", headers=hr_manager_auth).json()["last_test_ok"] is False


def test_the_login_screen_only_offers_microsoft_when_it_is_on(client, hr_manager_auth, sso_on, test_institution, fake_microsoft):
    code = test_institution["code"]
    assert client.get("/api/auth/sso/options", params={"institution_code": code}).json() == {"sso_enabled": False, "sso_required": False}   # saved, not on
    assert client.get("/api/auth/sso/options", params={"institution_code": "NOSUCHCO"}).json() == {"sso_enabled": False, "sso_required": False}
    assert client.get("/api/auth/sso/options").json() == {"sso_enabled": False, "sso_required": False}
    run_test_signin(client, hr_manager_auth, fake_microsoft)
    client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": True})
    assert client.get("/api/auth/sso/options", params={"institution_code": code.lower()}).json() == {"sso_enabled": True, "sso_required": False}
    client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": False})
    assert client.get("/api/auth/sso/options", params={"institution_code": code}).json() == {"sso_enabled": False, "sso_required": False}


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------
def test_start_sends_the_browser_to_the_companys_own_tenant_with_state_nonce_and_pkce(client, sso_enabled, test_institution):
    q, url = begin_login(client, test_institution)
    assert url.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize?")
    assert q["client_id"] == [CLIENT] and q["response_type"] == ["code"] and q["scope"] == ["openid profile email"]
    assert q["redirect_uri"] == ["http://testserver/api/auth/sso/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0] and q["state"][0] and q["nonce"][0]


def test_start_goes_back_to_the_login_screen_when_not_enabled(client, hr_manager_auth, test_institution):
    res = client.get("/api/auth/sso/start", params={"institution_code": test_institution["code"]}, follow_redirects=False)
    assert res.headers["location"] == "/?sso_error=not_enabled"
    res = client.get("/api/auth/sso/start", params={"institution_code": "NOSUCHCO"}, follow_redirects=False)
    assert res.headers["location"] == "/?sso_error=not_enabled"


def test_a_matching_user_signs_in_once_and_the_account_is_linked(client, hr_manager_auth, sso_enabled, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    user = make_user(email, must_change_password=True)
    res, state = sign_in(client, test_institution, fake_microsoft, email=email.upper())    # case doesn't matter
    code = code_from(res)
    assert fake_microsoft["exchanges"][-1]["secret"] == "s3cret-value"        # the stored secret is decrypted for Microsoft
    assert fake_microsoft["exchanges"][-1]["verifier"]                          # PKCE verifier sent

    out = client.post("/api/auth/sso/exchange", json={"code": code})
    assert out.status_code == 200, out.text
    assert out.json()["user"]["username"] == user["username"]
    assert out.json()["user"]["must_change_password"] is False                  # a temp password is moot with Microsoft
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {out.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == user["username"]

    assert client.post("/api/auth/sso/exchange", json={"code": code}).status_code == 401, "a code works once"
    replay = client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert replay.headers["location"] == "/?sso_error=expired", "a state works once"

    listed = next(u for u in client.get("/api/users", headers=hr_manager_auth).json() if u["id"] == user["id"])
    assert listed["sso_linked"] is True


def test_after_linking_the_microsoft_id_is_what_counts_not_the_email(client, sso_enabled, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    user = make_user(email)
    oid = f"oid-{os.urandom(4).hex()}"
    code_from(sign_in(client, test_institution, fake_microsoft, email=email, oid=oid)[0])
    # their Microsoft address changes: same oid still lands on the same EMS user
    res, _ = sign_in(client, test_institution, fake_microsoft, email="renamed@example.com", oid=oid)
    out = client.post("/api/auth/sso/exchange", json={"code": code_from(res)}).json()
    assert out["user"]["username"] == user["username"]
    # a different Microsoft account using that email can't take over the linked user
    res, _ = sign_in(client, test_institution, fake_microsoft, email=email, oid=f"oid-{os.urandom(4).hex()}")
    assert res.headers["location"] == "/?sso_error=no_account"


def test_a_user_can_be_matched_by_their_employee_work_email(client, hr_manager_auth, sso_enabled, make_test_employee, make_user, test_institution, fake_microsoft):
    work = f"zzwork.{os.urandom(3).hex()}@example.com"
    emp = make_test_employee(work_email=work)
    user = make_user(None, employee_id=emp["employee_id"])
    res, _ = sign_in(client, test_institution, fake_microsoft, preferred_username=work)
    assert client.post("/api/auth/sso/exchange", json={"code": code_from(res)}).json()["user"]["username"] == user["username"]


@pytest.mark.parametrize("override,expected", [
    ({"aud": "someone-else"}, "failed"),
    ({"tid": "99999999-2222-3333-4444-555555555555"}, "failed"),
    ({"iss": "https://login.microsoftonline.com/other/v2.0"}, "failed"),
    ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200, "nbf": int(time.time()) - 7200}, "failed"),
    ({"nonce": "not-the-nonce"}, "failed"),
    ({"oid": None}, "failed"),
])
def test_a_bad_id_token_is_refused_and_logged(client, sso_enabled, make_user, test_institution, fake_microsoft, override, expected):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    make_user(email)
    res, _ = sign_in(client, test_institution, fake_microsoft, email=email, **override)
    assert res.headers["location"] == f"/?sso_error={expected}"


def test_a_token_signed_by_someone_elses_key_is_refused(client, sso_enabled, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    make_user(email)
    q, _ = begin_login(client, test_institution)
    state = q["state"][0]
    fake_microsoft["id_token"] = id_token(_pending_nonce(state), key=OTHER_KEY, email=email)
    res = client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert res.headers["location"] == "/?sso_error=failed"


def test_nobody_is_created_for_an_unknown_ambiguous_or_inactive_account(client, hr_manager_auth, sso_enabled, make_user, test_institution, fake_microsoft):
    unknown, _ = sign_in(client, test_institution, fake_microsoft, email="nobody@example.com")
    assert unknown.headers["location"] == "/?sso_error=no_account"

    shared = f"zzshared.{os.urandom(3).hex()}@example.com"
    make_user(shared); make_user(shared)
    ambiguous, _ = sign_in(client, test_institution, fake_microsoft, email=shared)
    assert ambiguous.headers["location"] == "/?sso_error=no_account"

    gone_email = f"zzgone.{os.urandom(3).hex()}@example.com"
    gone = make_user(gone_email)
    assert client.put(f"/api/users/{gone['id']}", headers=hr_manager_auth, json={
        "full_name": "ZZ SSO User", "role": "employee", "email": gone_email, "is_active": False}).status_code == 200
    inactive, _ = sign_in(client, test_institution, fake_microsoft, email=gone_email)
    assert inactive.headers["location"] == "/?sso_error=inactive"


def test_turning_it_off_stops_microsoft_sign_in_straight_away(client, hr_manager_auth, sso_enabled, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    make_user(email)
    q, _ = begin_login(client, test_institution)
    state = q["state"][0]
    fake_microsoft["id_token"] = id_token(_pending_nonce(state), email=email)
    client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": False})
    res = client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert res.headers["location"] == "/?sso_error=not_enabled"


def test_microsoft_saying_no_sends_the_person_back(client, sso_enabled, test_institution):
    q, _ = begin_login(client, test_institution)
    res = client.get("/api/auth/sso/callback", params={"error": "access_denied", "state": q["state"][0]}, follow_redirects=False)
    assert res.headers["location"] == "/?sso_error=denied"


def test_password_sign_in_is_unaffected_and_sso_sign_ins_are_audited(client, hr_manager_auth, sso_enabled, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    user = make_user(email)
    assert client.post("/api/auth/login", json={"username": user["username"], "password": "ZzPytest@123",
                                                "institution_code": test_institution["code"]}).status_code == 200
    code_from(sign_in(client, test_institution, fake_microsoft, email=email)[0])
    conn = get_admin_db()
    try:
        reasons = [r["reason"] for r in conn.execute("SELECT reason FROM login_audit_log WHERE username=? AND success ORDER BY id", (user["username"],)).fetchall()]
    finally:
        conn.close()
    assert "sso" in reasons


def test_unlinking_a_user_makes_their_next_sign_in_match_by_email_again(client, hr_manager_auth, sso_enabled, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    user = make_user(email)
    code_from(sign_in(client, test_institution, fake_microsoft, email=email)[0])
    assert client.post(f"/api/users/{user['id']}/sso-unlink", headers=hr_manager_auth).status_code == 200
    assert next(u for u in client.get("/api/users", headers=hr_manager_auth).json() if u["id"] == user["id"])["sso_linked"] is False
    # a different Microsoft account with the same email can now link
    res, _ = sign_in(client, test_institution, fake_microsoft, email=email, oid=f"oid-{os.urandom(4).hex()}")
    assert client.post("/api/auth/sso/exchange", json={"code": code_from(res)}).status_code == 200
    assert client.post("/api/users/999999999/sso-unlink", headers=hr_manager_auth).status_code == 404


def test_pure_helpers():
    assert sso_core.is_guid(TENANT) and not sso_core.is_guid("tenant") and not sso_core.is_guid("")
    verifier, challenge = sso_core.pkce_pair()
    import base64
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert sso_core.candidate_emails({"email": "A@x.com", "preferred_username": "a@x.com", "upn": "u@x.com", "name": "n"}) == ["a@x.com", "u@x.com"]
    assert sso_core.candidate_emails({"preferred_username": "no-at-sign"}) == []


# ---------------------------------------------------------------------------
# Phase 2: require Microsoft sign-in, emergency password access
# ---------------------------------------------------------------------------
def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()


def set_emergency(client, hr_manager_auth, user_id, on=True):
    u = next(x for x in client.get("/api/users", headers=hr_manager_auth).json() if x["id"] == user_id)
    res = client.put(f"/api/users/{user_id}", headers=hr_manager_auth, json={
        "full_name": u["full_name"], "role": u["role"], "email": u["email"], "is_active": True, "sso_password_ok": on})
    assert res.status_code == 200, res.text


def password_login(client, test_institution, user):
    return client.post("/api/auth/login", json={"username": user["username"], "password": "ZzPytest@123", "institution_code": test_institution["code"]})


@pytest.fixture
def enforced(client, hr_manager_auth, sso_enabled, make_user):
    """Microsoft sign-in required for the test company; the HR caller and one other person keep emergency password access."""
    me_id = _me(client, hr_manager_auth)["id"]
    set_emergency(client, hr_manager_auth, me_id, True)
    res = client.put("/api/settings/sso/enforce", headers=hr_manager_auth, json={"enforce": True, "confirm_unmatched": True})
    assert res.status_code == 200, res.text
    yield
    client.put("/api/settings/sso/enforce", headers=hr_manager_auth, json={"enforce": False})
    set_emergency(client, hr_manager_auth, me_id, False)


def test_requiring_microsoft_has_safeguards(client, hr_manager_auth, sso_on, sso_enabled, make_user):
    me_id = _me(client, hr_manager_auth)["id"]
    url = "/api/settings/sso/enforce"
    no_emergency = client.put(url, headers=hr_manager_auth, json={"enforce": True, "confirm_unmatched": True})
    assert no_emergency.status_code == 400 and "emergency" in no_emergency.json()["detail"].lower()

    other = make_user("zzsso.other@example.com")
    set_emergency(client, hr_manager_auth, other["id"], True)
    locked_out = client.put(url, headers=hr_manager_auth, json={"enforce": True, "confirm_unmatched": True})
    assert locked_out.status_code == 400 and "yourself" in locked_out.json()["detail"].lower()      # the caller could not get back in

    set_emergency(client, hr_manager_auth, me_id, True)
    try:
        nomail = make_user(None, username=f"zzsso_{os.urandom(4).hex()}")
        stuck = client.put(url, headers=hr_manager_auth, json={"enforce": True})
        assert stuck.status_code == 409
        assert nomail["username"] in [u["username"] for u in stuck.json()["detail"]["users"]]
        ok = client.put(url, headers=hr_manager_auth, json={"enforce": True, "confirm_unmatched": True})
        assert ok.status_code == 200 and ok.json()["enforce"] is True
        assert {u["id"] for u in ok.json()["emergency_users"]} >= {other["id"], me_id}
    finally:
        client.put(url, headers=hr_manager_auth, json={"enforce": False})
        set_emergency(client, hr_manager_auth, me_id, False)


def test_enforce_needs_microsoft_sign_in_to_be_on(client, hr_manager_auth, sso_on):
    assert client.put("/api/settings/sso/enforce", headers=hr_manager_auth, json={"enforce": True, "confirm_unmatched": True}).status_code == 400


def test_while_required_passwords_are_refused_except_for_emergency_users_and_microsoft_still_works(
        client, hr_manager_auth, enforced, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    normal = make_user(email)
    emergency = make_user(f"zzsso.{os.urandom(3).hex()}@example.com", sso_password_ok=True)
    res = password_login(client, test_institution, normal)
    assert res.status_code == 403 and "microsoft" in res.json()["detail"].lower()
    assert password_login(client, test_institution, emergency).status_code == 200

    assert client.get("/api/auth/sso/options", params={"institution_code": test_institution["code"]}).json() == {"sso_enabled": True, "sso_required": True}
    token = client.post("/api/auth/sso/exchange", json={"code": code_from(sign_in(client, test_institution, fake_microsoft, email=email)[0])}).json()["access_token"]
    me = _me(client, {"Authorization": f"Bearer {token}"})
    assert me["sso_enabled"] is True and me["sso_linked"] is True and me["password_signin_blocked"] is True

    # the audit trail says why the password was refused
    conn = get_admin_db()
    try:
        assert conn.execute("SELECT 1 FROM login_audit_log WHERE username=? AND NOT success AND reason='sso_required'", (normal["username"],)).fetchone()
    finally:
        conn.close()


def test_only_hr_manager_can_grant_emergency_access(client, hr_manager_auth, make_user, make_test_user, test_institution):
    token, _ = make_test_user(role="hr_admin")
    hr_admin = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    target = make_user("zzsso.t@example.com")
    body = {"full_name": "ZZ SSO User", "role": "employee", "email": "zzsso.t@example.com", "is_active": True, "sso_password_ok": True}
    assert client.put(f"/api/users/{target['id']}", headers=hr_admin, json=body).status_code == 403
    assert client.put(f"/api/users/{target['id']}", headers=hr_manager_auth, json=body).status_code == 200


def test_turning_microsoft_sign_in_off_also_stops_requiring_it(client, hr_manager_auth, enforced, make_user, test_institution):
    normal = make_user("zzsso.n@example.com")
    assert password_login(client, test_institution, normal).status_code == 403
    off = client.put("/api/settings/sso/enabled", headers=hr_manager_auth, json={"enabled": False})
    assert off.status_code == 200 and off.json()["enforce"] is False
    assert password_login(client, test_institution, normal).status_code == 200


def test_policy_acknowledgement_needs_a_fresh_microsoft_confirmation_while_passwords_are_off(
        client, hr_manager_auth, enforced, make_test_employee, make_user, test_institution, fake_microsoft):
    from tests.test_policies import pdf_url
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    emp = make_test_employee()
    user = make_user(email, employee_id=emp["employee_id"])
    pub = client.post("/api/policies", headers=hr_manager_auth, json={
        "title": f"ZZ SSO Policy {os.urandom(3).hex()}", "audience_type": "people", "employee_ids": [emp["employee_id"]],
        "file_name": "p.pdf", "data_url": pdf_url(), "change_note": "x"}).json()
    vid = pub["version_id"]
    login = client.post("/api/auth/sso/exchange", json={"code": code_from(sign_in(client, test_institution, fake_microsoft, email=email, oid="oid-policy-1")[0])})
    me = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get(f"/api/policies/versions/{vid}/file", headers=me).status_code == 200
    ack = f"/api/policies/versions/{vid}/acknowledge"

    # a password is no use to this person, and neither is no proof at all
    assert client.post(ack, headers=me, json={"password": "ZzPytest@123"}).status_code == 403
    assert client.post(ack, headers=me, json={"sso_proof": "made-up"}).status_code == 403

    def reauth(ref=vid, oid="oid-policy-1", purpose="policy_ack"):
        start = client.post("/api/auth/sso/reauth-start", headers=me, json={"purpose": purpose, "ref": str(ref)})
        assert start.status_code == 200, start.text
        q = parse_qs(urlparse(start.json()["authorize_url"]).query)
        assert q["prompt"] == ["login"] and q["login_hint"] == [email]          # Microsoft must ask for credentials again
        state = q["state"][0]
        fake_microsoft["id_token"] = id_token(_pending_nonce(state), oid=oid, email=email)
        return client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False)

    # a different Microsoft account signing in is not a confirmation
    wrong = reauth(oid="oid-someone-else")
    assert wrong.headers["location"] == "/?sso_reauth_error=1"

    good = reauth()
    q = parse_qs(urlparse(good.headers["location"]).query)
    proof = q["sso_reauth"][0]
    assert q["sso_for"] == ["policy_ack"] and q["sso_ref"] == [str(vid)]
    assert client.post(ack, headers=me, json={"sso_proof": proof + "x"}).status_code == 403
    done = client.post(ack, headers=me, json={"sso_proof": proof})
    assert done.status_code == 200 and done.json()["already"] is False
    row = client.get(f"/api/policies/{pub['course_id']}/tracker", headers=hr_manager_auth).json()["rows"][0]
    assert row["method"] == "microsoft"
    assert "Microsoft" in client.get(f"/api/policies/{pub['course_id']}/export.csv", headers=hr_manager_auth).text


def test_a_confirmation_is_single_use_and_only_for_the_thing_it_was_issued_for(
        client, hr_manager_auth, enforced, make_test_employee, make_user, test_institution, fake_microsoft):
    from tests.test_policies import pdf_url
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    emps = [make_test_employee(), make_test_employee()]
    user = make_user(email, employee_id=emps[0]["employee_id"])
    vids = []
    for e in emps[:1] * 2:
        vids.append(client.post("/api/policies", headers=hr_manager_auth, json={
            "title": f"ZZ SSO Policy {os.urandom(3).hex()}", "audience_type": "people", "employee_ids": [e["employee_id"]],
            "file_name": "p.pdf", "data_url": pdf_url(), "change_note": "x"}).json()["version_id"])
    code = code_from(sign_in(client, test_institution, fake_microsoft, email=email, oid="oid-policy-2")[0])
    me = {"Authorization": f"Bearer {client.post('/api/auth/sso/exchange', json={'code': code}).json()['access_token']}"}
    for v in vids:
        client.get(f"/api/policies/versions/{v}/file", headers=me)
    start = client.post("/api/auth/sso/reauth-start", headers=me, json={"purpose": "policy_ack", "ref": str(vids[0])}).json()
    state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
    fake_microsoft["id_token"] = id_token(_pending_nonce(state), oid="oid-policy-2", email=email)
    proof = parse_qs(urlparse(client.get("/api/auth/sso/callback", params={"code": "c", "state": state}, follow_redirects=False).headers["location"]).query)["sso_reauth"][0]
    # issued for the first policy, so it cannot acknowledge the second
    assert client.post(f"/api/policies/versions/{vids[1]}/acknowledge", headers=me, json={"sso_proof": proof}).status_code == 403
    assert client.post(f"/api/policies/versions/{vids[0]}/acknowledge", headers=me, json={"sso_proof": proof}).status_code == 200
    assert client.post(f"/api/policies/versions/{vids[1]}/acknowledge", headers=me, json={"sso_proof": proof}).status_code == 403   # spent


def test_reauth_start_needs_a_linked_account_and_a_known_purpose(client, hr_manager_auth, sso_enabled, make_user, test_institution):
    assert client.post("/api/auth/sso/reauth-start", headers=hr_manager_auth, json={"purpose": "policy_ack", "ref": "1"}).status_code == 400   # not linked
    assert client.post("/api/auth/sso/reauth-start", headers=hr_manager_auth, json={"purpose": "anything", "ref": "1"}).status_code == 400


# ---------------------------------------------------------------------------
# Phase 3: create accounts, roles from groups
# ---------------------------------------------------------------------------
def set_options(client, hr_manager_auth, **kw):
    res = client.put("/api/settings/sso/options", headers=hr_manager_auth, json=kw)
    assert res.status_code == 200, res.text
    return res.json()


def username_for(client, token):
    return _me(client, {"Authorization": f"Bearer {token}"})


def test_first_sign_in_creates_an_employee_account_only_when_switched_on_and_matched_to_one_employee(
        client, hr_manager_auth, sso_enabled, make_test_employee, test_institution, fake_microsoft):
    work = f"zzauto.{os.urandom(3).hex()}@example.com"
    emp = make_test_employee(work_email=work)
    res, _ = sign_in(client, test_institution, fake_microsoft, email=work)
    assert res.headers["location"] == "/?sso_error=no_account"                       # off by default

    set_options(client, hr_manager_auth, auto_create=True)
    try:
        res, _ = sign_in(client, test_institution, fake_microsoft, email=work, oid="oid-auto-1")
        out = client.post("/api/auth/sso/exchange", json={"code": code_from(res)})
        assert out.status_code == 200, out.text
        u = out.json()["user"]
        assert u["role"] == "employee" and u["employee_id"] == emp["employee_id"] and u["username"] == work
        assert u["must_change_password"] is False
        # the random password is unknowable, and a second sign-in reuses the account
        assert password_login(client, test_institution, {"username": work}).status_code == 401
        again, _ = sign_in(client, test_institution, fake_microsoft, email=work, oid="oid-auto-1")
        assert client.post("/api/auth/sso/exchange", json={"code": code_from(again)}).json()["user"]["id"] == u["id"]
        conn = get_admin_db()
        try:
            assert conn.execute("SELECT 1 FROM entity_audit_log WHERE entity_type='user' AND entity_id=? AND action='Created'", (str(u["id"]),)).fetchone()
            assert conn.execute("SELECT 1 FROM login_audit_log WHERE username=? AND reason='sso_created'", (work,)).fetchone()
        finally:
            conn.close()
        # nobody matching an employee: still refused
        res, _ = sign_in(client, test_institution, fake_microsoft, email=f"zzstranger.{os.urandom(3).hex()}@example.com")
        assert res.headers["location"] == "/?sso_error=no_account"
        # an inactive employee gets no account either
        gone = f"zzgone.{os.urandom(3).hex()}@example.com"
        e2 = make_test_employee(work_email=gone)
        client.patch(f"/api/employees/{e2['employee_id']}/status", headers=hr_manager_auth, json={"status": "Inactive"})
        res, _ = sign_in(client, test_institution, fake_microsoft, email=gone)
        assert res.headers["location"] == "/?sso_error=no_account"
    finally:
        set_options(client, hr_manager_auth, auto_create=False)
        conn = get_admin_db()
        try:
            conn.execute("DELETE FROM users WHERE username=?", (work,))
            conn.commit()
        finally:
            conn.close()


def test_two_employees_with_the_same_work_email_create_nobody(client, hr_manager_auth, sso_enabled, make_test_employee, test_institution, fake_microsoft):
    work = f"zzdup.{os.urandom(3).hex()}@example.com"
    make_test_employee(work_email=work)
    make_test_employee(work_email=work)
    set_options(client, hr_manager_auth, auto_create=True)
    try:
        res, _ = sign_in(client, test_institution, fake_microsoft, email=work)
        assert res.headers["location"] == "/?sso_error=no_account"
    finally:
        set_options(client, hr_manager_auth, auto_create=False)


G_HR, G_MGR, G_OTHER = "aaaa1111-0000-0000-0000-000000000001", "aaaa1111-0000-0000-0000-000000000002", "aaaa1111-0000-0000-0000-000000000003"


@pytest.fixture
def group_roles(client, hr_manager_auth, sso_enabled):
    res = client.put("/api/settings/sso/group-roles", headers=hr_manager_auth, json={"mappings": [
        {"group_id": G_HR.upper(), "role": "hr_admin"}, {"group_id": G_MGR, "role": "manager"}]})
    assert res.status_code == 200, res.text
    yield
    client.put("/api/settings/sso/options", headers=hr_manager_auth, json={"role_sync": False})
    client.put("/api/settings/sso/group-roles", headers=hr_manager_auth, json={"mappings": []})


def test_group_role_mappings_are_validated_and_normalised(client, hr_manager_auth, sso_on):
    url = "/api/settings/sso/group-roles"
    assert client.put(url, headers=hr_manager_auth, json={"mappings": [{"group_id": "not-a-guid", "role": "manager"}]}).status_code == 400
    assert client.put(url, headers=hr_manager_auth, json={"mappings": [{"group_id": G_HR, "role": "superadmin"}]}).status_code == 400
    assert client.put(url, headers=hr_manager_auth, json={"mappings": [{"group_id": G_HR, "role": "nonsense"}]}).status_code == 400
    assert client.put(url, headers=hr_manager_auth, json={"mappings": [{"group_id": G_HR, "role": "manager"}, {"group_id": G_HR.upper(), "role": "employee"}]}).status_code == 400
    assert client.put("/api/settings/sso/options", headers=hr_manager_auth, json={"role_sync": True}).status_code == 400    # nothing mapped yet
    ok = client.put(url, headers=hr_manager_auth, json={"mappings": [{"group_id": G_HR.upper(), "role": "hr_admin"}]})
    assert ok.status_code == 200 and ok.json()["group_roles"] == [{"group_id": G_HR, "role": "hr_admin"}]
    client.put(url, headers=hr_manager_auth, json={"mappings": []})


def test_roles_follow_entra_groups_at_sign_in(client, hr_manager_auth, group_roles, make_user, test_institution, fake_microsoft):
    set_options(client, hr_manager_auth, role_sync=True)
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    user = make_user(email, role="employee")

    def go(**over):
        res, _ = sign_in(client, test_institution, fake_microsoft, email=email, oid="oid-roles-1", **over)
        return client.post("/api/auth/sso/exchange", json={"code": code_from(res)}).json()["user"]

    assert go(groups=[G_OTHER])["role"] == "employee"                          # in no mapped group: untouched
    assert go()["role"] == "employee"                                          # no groups claim at all: untouched
    assert go(_claim_names={"groups": "src1"})["role"] == "employee"           # too many groups (overage): untouched
    u = go(groups=[G_MGR.upper(), G_OTHER])
    assert u["role"] == "manager"
    both = go(groups=[G_MGR, G_HR])
    assert both["roles"] == ["hr_admin", "manager"] and both["role"] == "manager"   # stays on a role they still hold
    assert go(groups=[G_HR])["role"] == "hr_admin"
    conn = get_admin_db()
    try:
        assert conn.execute("SELECT 1 FROM entity_audit_log WHERE entity_type='user' AND entity_id=? AND action='Roles set from Microsoft groups'", (str(user["id"]),)).fetchone()
    finally:
        conn.close()


def test_role_sync_is_off_by_default_and_skips_emergency_accounts(client, hr_manager_auth, group_roles, make_user, test_institution, fake_microsoft):
    email = f"zzsso.{os.urandom(3).hex()}@example.com"
    make_user(email, role="employee")
    res, _ = sign_in(client, test_institution, fake_microsoft, email=email, groups=[G_HR])
    assert client.post("/api/auth/sso/exchange", json={"code": code_from(res)}).json()["user"]["role"] == "employee"   # switch still off

    set_options(client, hr_manager_auth, role_sync=True)
    em = f"zzsso.{os.urandom(3).hex()}@example.com"
    make_user(em, role="employee", sso_password_ok=True)
    res, _ = sign_in(client, test_institution, fake_microsoft, email=em, groups=[G_HR])
    assert client.post("/api/auth/sso/exchange", json={"code": code_from(res)}).json()["user"]["role"] == "employee"   # emergency account never changed by Entra


def test_the_test_sign_in_reports_whether_the_token_carries_groups(client, hr_manager_auth, sso_on, fake_microsoft):
    run_test_signin(client, hr_manager_auth, fake_microsoft, email="t@example.com", groups=[G_HR, G_MGR])
    assert "2 groups" in client.get("/api/settings/sso", headers=hr_manager_auth).json()["last_test_detail"]
    run_test_signin(client, hr_manager_auth, fake_microsoft, email="t@example.com")
    assert "no group list" in client.get("/api/settings/sso", headers=hr_manager_auth).json()["last_test_detail"]


def test_group_helpers():
    assert sso_core.token_groups({"groups": ["AA", "bb"]}) == (["aa", "bb"], True)
    assert sso_core.token_groups({}) == ([], False)
    assert sso_core.token_groups({"_claim_names": {"groups": "src1"}})[1] is False
    assert sso_core.token_groups({"groups": []}) == ([], True)
