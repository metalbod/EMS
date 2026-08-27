"""Tests for the AI assistant's BYOK settings endpoints
(GET/PUT/DELETE /api/assistant/settings, routers/assistant.py) and the
resulting institution-level visibility (routers/institutions.py's
ai_key_status, superadmin-only). The real Anthropic API is never hit —
the validation call in the PUT handler is always mocked.
"""
import httpx
import pytest

import anthropic
import routers.assistant as assistant_module


def _fake_anthropic_ok(monkeypatch):
    class _FakeModels:
        def list(self):
            return {"data": []}

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.models = _FakeModels()

    monkeypatch.setattr(assistant_module.anthropic, "Anthropic", _FakeClient)


def _fake_anthropic_auth_error(monkeypatch):
    response = httpx.Response(401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models"))

    class _FakeModels:
        def list(self):
            raise anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    monkeypatch.setattr(assistant_module.anthropic, "Anthropic", _FakeClient)


@pytest.fixture(autouse=True)
def _clear_byok_key(client, hr_manager_auth):
    """Every test starts from "no BYOK key configured" and cleans up after
    itself — the test_institution fixture is session-scoped (see
    CLAUDE.md), so a key saved by one test would otherwise leak into the
    next."""
    yield
    client.delete("/api/assistant/settings", headers=hr_manager_auth)


def test_settings_requires_hr_manager_role(client, hr_manager_auth):
    res = client.get("/api/assistant/settings", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json() == {"configured": False, "key_last4": None, "added_at": None}


@pytest.mark.parametrize("role", ["hr_admin", "manager", "employee", "payroll_manager"])
def test_settings_rejects_non_hr_manager_roles(client, make_test_user, test_institution, role):
    token, _ = make_test_user(role=role)
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    for method, path, kwargs in [
        ("get", "/api/assistant/settings", {}),
        ("put", "/api/assistant/settings", {"json": {"api_key": "sk-ant-doesnt-matter"}}),
        ("delete", "/api/assistant/settings", {}),
    ]:
        res = getattr(client, method)(path, headers=headers, **kwargs)
        assert res.status_code == 403, f"{role} {method} {path}: {res.text}"


def test_settings_rejects_superadmin(client, superadmin_headers):
    # Superadmin gets read-only ai_key_status visibility on the institutions
    # list instead (see test_institutions_list_exposes_ai_key_status_not_raw_key
    # below) — never access to the settings endpoints themselves.
    for method, path, kwargs in [
        ("get", "/api/assistant/settings", {}),
        ("put", "/api/assistant/settings", {"json": {"api_key": "sk-ant-doesnt-matter"}}),
        ("delete", "/api/assistant/settings", {}),
    ]:
        res = getattr(client, method)(path, headers=superadmin_headers, **kwargs)
        assert res.status_code == 403, f"superadmin {method} {path}: {res.text}"


def test_put_rejects_invalid_key(client, hr_manager_auth, monkeypatch):
    _fake_anthropic_auth_error(monkeypatch)
    res = client.put("/api/assistant/settings", headers=hr_manager_auth, json={"api_key": "sk-ant-bad-key"})
    assert res.status_code == 400, res.text
    assert "rejected" in res.json()["detail"].lower()

    # Rejected key must never be persisted.
    get_res = client.get("/api/assistant/settings", headers=hr_manager_auth)
    assert get_res.json()["configured"] is False


def test_put_saves_valid_key_and_never_echoes_it(client, hr_manager_auth, monkeypatch):
    _fake_anthropic_ok(monkeypatch)
    res = client.put("/api/assistant/settings", headers=hr_manager_auth, json={"api_key": "sk-ant-api03-abcd1234WXYZ"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["configured"] is True
    assert body["key_last4"] == "WXYZ"
    assert body["added_at"]
    assert "sk-ant" not in str(body)

    get_res = client.get("/api/assistant/settings", headers=hr_manager_auth)
    assert get_res.json()["configured"] is True
    assert get_res.json()["key_last4"] == "WXYZ"


def test_delete_clears_key(client, hr_manager_auth, monkeypatch):
    _fake_anthropic_ok(monkeypatch)
    client.put("/api/assistant/settings", headers=hr_manager_auth, json={"api_key": "sk-ant-api03-abcd1234WXYZ"})

    res = client.delete("/api/assistant/settings", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json() == {"configured": False, "key_last4": None, "added_at": None}

    get_res = client.get("/api/assistant/settings", headers=hr_manager_auth)
    assert get_res.json()["configured"] is False


def test_institutions_list_exposes_ai_key_status_not_raw_key(client, superadmin_headers, hr_manager_auth, monkeypatch):
    _fake_anthropic_ok(monkeypatch)
    client.put("/api/assistant/settings", headers=hr_manager_auth, json={"api_key": "sk-ant-api03-abcd1234WXYZ"})

    res = client.get("/api/institutions", headers=superadmin_headers)
    assert res.status_code == 200, res.text
    inst_id = int(superadmin_headers["X-Institution-Id"])
    row = next(r for r in res.json() if r["id"] == inst_id)
    assert row["ai_key_status"] == "byok"
    assert "anthropic_api_key_encrypted" not in row
    assert "anthropic_api_key_last4" not in row

    detail_res = client.get(f"/api/institutions/{inst_id}", headers=superadmin_headers)
    assert detail_res.json()["ai_key_status"] == "byok"
    assert "anthropic_api_key_encrypted" not in detail_res.json()

    client.delete("/api/assistant/settings", headers=hr_manager_auth)
    res2 = client.get(f"/api/institutions/{inst_id}", headers=superadmin_headers)
    assert res2.json()["ai_key_status"] in ("platform", "none")
