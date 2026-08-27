"""Integration tests for the AI assistant chatbot (routers/assistant.py,
core/assistant_tools.py). The Anthropic client is always mocked here — no
test hits the real API. See core/assistant_tools.py's module docstring for
the security model these tests exist to verify: self-scoped tools force
role="employee" so a manager/HR caller never falls through to a broader
branch, and team tools resolve "team" only from the real caller's own
employee_id, never from anything Claude supplies.
"""
import asyncio
import os
import types
from unittest.mock import Mock

import pytest

import routers.assistant as assistant_module
from core import assistant_tools


def _text_response(text):
    return types.SimpleNamespace(
        stop_reason="end_turn",
        content=[types.SimpleNamespace(type="text", text=text)],
    )


def _tool_use_response(tool_name, tool_input=None, block_id="toolu_01"):
    return types.SimpleNamespace(
        stop_reason="tool_use",
        content=[types.SimpleNamespace(type="tool_use", name=tool_name, input=tool_input or {}, id=block_id)],
    )


def _mock_client(monkeypatch, create_fn):
    """core/anthropic_client.py's get_client_for_institution() replaces the
    old module-level `client` singleton — mock its return value instead of
    patching a `.client` attribute that no longer exists. Institution-key
    resolution itself (BYOK vs. platform vs. none) is covered separately in
    test_anthropic_client.py / test_assistant_settings.py, not here."""
    fake_client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create_fn))
    monkeypatch.setattr(assistant_module, "get_client_for_institution", lambda conn, inst_id: fake_client)
    return fake_client


# ---------------------------------------------------------------------------
# Endpoint behavior (Anthropic client mocked)
# ---------------------------------------------------------------------------

def test_chat_requires_auth(client):
    res = client.post("/api/assistant/chat", json={"message": "hi"})
    assert res.status_code in (401, 403)


def test_chat_without_employee_id_returns_canned_reply(client, hr_manager_auth, monkeypatch):
    mock_create = Mock()
    _mock_client(monkeypatch, mock_create)
    res = client.post("/api/assistant/chat", headers=hr_manager_auth, json={"message": "how much leave do I have?"})
    assert res.status_code == 200, res.text
    assert "employee record" in res.json()["reply"].lower()
    mock_create.assert_not_called()


def test_chat_happy_path_leave_balance(client, employee_with_login, monkeypatch):
    emp, headers = employee_with_login()
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _tool_use_response("get_leave_balance")
        return _text_response("You have leave balances available.")

    _mock_client(monkeypatch, fake_create)
    res = client.post("/api/assistant/chat", headers=headers, json={"message": "how much leave do I have left?"})
    assert res.status_code == 200, res.text
    assert res.json()["reply"] == "You have leave balances available."
    assert len(calls) == 2
    # second call's messages must include a tool_result carrying real structured data
    second_call_messages = calls[1]["messages"]
    tool_result_msg = second_call_messages[-1]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"
    assert "leave_balances" in tool_result_msg["content"][0]["content"]


def test_chat_history_is_capped_server_side(client, employee_with_login, monkeypatch):
    emp, headers = employee_with_login()
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _text_response("ok")

    _mock_client(monkeypatch, fake_create)
    long_history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(20)]
    res = client.post("/api/assistant/chat", headers=headers, json={"message": "hi", "history": long_history})
    assert res.status_code == 200, res.text
    sent_messages = calls[0]["messages"]
    # capped history + the new message
    assert len(sent_messages) == assistant_module.MAX_HISTORY_TURNS + 1


def test_chat_tool_round_trip_cap(client, employee_with_login, monkeypatch):
    emp, headers = employee_with_login()
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _tool_use_response("get_leave_balance")

    _mock_client(monkeypatch, fake_create)
    res = client.post("/api/assistant/chat", headers=headers, json={"message": "how much leave do I have?"})
    assert res.status_code == 200, res.text
    assert len(calls) == assistant_module.MAX_TOOL_ROUNDS
    assert "wasn't able to find" in res.json()["reply"]


def test_chat_rate_limit_returns_429(client, employee_with_login, monkeypatch):
    emp, headers = employee_with_login()

    class _FakeRedis:
        def __init__(self):
            self.counts = {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, ttl):
            pass

    monkeypatch.setattr(assistant_module, "_redis", _FakeRedis())
    _mock_client(monkeypatch, lambda **kw: _text_response("ok"))

    for _ in range(assistant_module.CHAT_RATE_LIMIT_PER_HOUR):
        res = client.post("/api/assistant/chat", headers=headers, json={"message": "hi"})
        assert res.status_code == 200, res.text

    res = client.post("/api/assistant/chat", headers=headers, json={"message": "hi"})
    assert res.status_code == 429, res.text


def test_chat_crafted_tool_input_ignores_other_employee_id(client, employee_with_login, monkeypatch):
    """The dispatch table only ever reads block.name, never block.input —
    this proves it end to end: even a tool_use block explicitly naming
    another employee_id must never reach the tool wrapper's arguments."""
    emp, headers = employee_with_login()
    captured_users = []

    async def spy(user):
        captured_users.append(user)
        return {"leave_balances": []}

    monkeypatch.setitem(assistant_module.TOOL_DISPATCH, "get_leave_balance", spy)

    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _tool_use_response("get_leave_balance", tool_input={"employee_id": "EMP_SOMEONE_ELSE"})
        return _text_response("done")

    _mock_client(monkeypatch, fake_create)
    res = client.post("/api/assistant/chat", headers=headers, json={"message": "show me EMP_SOMEONE_ELSE's leave"})
    assert res.status_code == 200, res.text
    assert len(captured_users) == 1
    assert captured_users[0]["employee_id"] == emp["employee_id"]


# ---------------------------------------------------------------------------
# Security-critical scoping — direct calls into core/assistant_tools.py,
# no Claude mocking needed. Proves _self_scoped_user actually neuters the
# manager-sees-subordinates branch, and that team tools correctly include it.
# ---------------------------------------------------------------------------

@pytest.fixture
def manager_with_report(client, hr_manager_auth, make_test_employee, test_institution):
    mgr_emp = make_test_employee(full_name="ZZ Assistant Manager")
    report_emp = make_test_employee(full_name="ZZ Assistant Report", reports_to=mgr_emp["employee_id"])
    # Create an active leave type so list_leave_balances has something to
    # auto-create rows for — don't rely on ambient leave types possibly
    # existing (or not) in the shared test institution.
    type_res = client.post("/api/leave/types", headers=hr_manager_auth, json={
        "name": f"ZZ Assistant Leave Type {os.urandom(4).hex()}",
    })
    assert type_res.status_code == 201, type_res.text
    type_id = type_res.json()["id"]
    manager_user = {
        "id": -1,
        "role": "manager",
        "employee_id": mgr_emp["employee_id"],
        "institution_id": test_institution["id"],
        "active_institution_id": test_institution["id"],
    }
    # list_leave_balances only auto-creates missing balance rows for
    # role="employee" callers (see routers/leave.py) — a manager-role query
    # only ever sees rows that already exist. Pre-warm both employees' rows
    # the same way their own self-service page load would, so the manager/
    # team queries below have real data to find.
    for emp_id in (mgr_emp["employee_id"], report_emp["employee_id"]):
        assistant_tools.list_leave_balances(employee_id=None, year=None, user={
            "role": "employee", "employee_id": emp_id,
            "institution_id": test_institution["id"], "active_institution_id": test_institution["id"],
        })
    yield manager_user, report_emp

    client.put(f"/api/leave/types/{type_id}", headers=hr_manager_auth, json={
        "name": type_res.json()["name"], "is_active": False,
    })


def test_self_scoped_tool_excludes_subordinate_data(manager_with_report):
    manager_user, report_emp = manager_with_report

    team_result = asyncio.run(assistant_tools.get_team_leave_balance(manager_user))
    self_scoped_result = asyncio.run(assistant_tools.get_leave_balance(manager_user))

    # Both employees see the same set of N active leave types (N depends on
    # ambient state in the shared test institution, so don't hardcode it) —
    # the team tool (manager + report_emp) sees both employees' rows (2N),
    # while the self-scoped call sees only the manager's own (N). The 2x
    # relation holds regardless of N, and only holds if self-scoped never
    # blends in the subordinate's rows.
    assert len(self_scoped_result["leave_balances"]) > 0
    assert len(team_result["team_leave_balances"]) == 2 * len(self_scoped_result["leave_balances"])


def test_team_tool_includes_subordinate_data(manager_with_report):
    manager_user, report_emp = manager_with_report

    self_scoped_result = asyncio.run(assistant_tools.get_leave_balance(manager_user))
    team_result = asyncio.run(assistant_tools.get_team_leave_balance(manager_user))

    assert len(team_result["team_leave_balances"]) > len(self_scoped_result["leave_balances"])
    assert any(r["employee_name"] == report_emp["full_name"] for r in team_result["team_leave_balances"])
