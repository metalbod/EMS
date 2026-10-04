"""Tests for AI token-usage recording (core/ai_usage.py) and the Settings ->
AI Assistant -> Usage report (routers/assistant.py's get_assistant_usage).
The Anthropic client is always mocked — no test hits the real API.
"""
import types
from unittest.mock import Mock

import pytest

import routers.assistant as assistant_module
import routers.recruitment as recruitment_module
from db import get_admin_db

WIDE = {"date_from": "2000-01-01", "date_to": "2100-01-01"}


def _usage(input_tokens, output_tokens):
    return types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _text_response(text, usage=None):
    r = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)])
    if usage:
        r.usage = usage
    return r


def _tool_use_response(tool_name, usage=None):
    r = types.SimpleNamespace(
        stop_reason="tool_use",
        content=[types.SimpleNamespace(type="tool_use", name=tool_name, input={}, id="toolu_01")],
    )
    if usage:
        r.usage = usage
    return r


def _mock_assistant_client(monkeypatch, create_fn):
    fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=create_fn))
    monkeypatch.setattr(assistant_module, "get_client_for_institution", lambda conn, inst_id: fake)


def _mock_recruitment_client(monkeypatch, create_fn):
    fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=create_fn))
    monkeypatch.setattr(recruitment_module, "get_client_for_institution", lambda conn, inst_id: fake)


@pytest.fixture(autouse=True)
def _cleanup_usage_rows():
    yield
    conn = get_admin_db()
    try:
        conn.execute("DELETE FROM ai_usage_log WHERE username LIKE ?", ("zz%",))
        conn.commit()
    finally:
        conn.close()


def _report(client, headers, **params):
    return client.get("/api/assistant/usage", headers=headers, params={**WIDE, **params})


def _row_for(report, name):
    return next((r for r in report["by_user"] if r["name"] == name), None)


def _insert_row(inst_id, user_id, username, feature, input_tokens, output_tokens, created_at):
    conn = get_admin_db()
    try:
        conn.execute(
            "INSERT INTO ai_usage_log (institution_id,user_id,username,feature,model,input_tokens,output_tokens,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (inst_id, user_id, username, feature, "claude-haiku-4-5", input_tokens, output_tokens, created_at),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def test_chat_records_summed_tokens_across_tool_rounds(client, hr_manager_auth, employee_with_login, monkeypatch):
    emp, headers = employee_with_login(full_name="ZZ Usage Chat Person")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _tool_use_response("get_leave_balance", _usage(100, 20))
        return _text_response("done", _usage(150, 30))

    _mock_assistant_client(monkeypatch, fake_create)
    res = client.post("/api/assistant/chat", headers=headers, json={"message": "my leave?"})
    assert res.status_code == 200, res.text

    row = _row_for(_report(client, hr_manager_auth).json(), "ZZ Usage Chat Person")
    assert row is not None
    assert row["chat_requests"] == 1  # one chat message, not one per Claude call
    assert row["chat_tokens"] == 100 + 20 + 150 + 30
    assert row["resume_requests"] == 0


def test_chat_without_usage_info_records_nothing(client, hr_manager_auth, employee_with_login, monkeypatch):
    emp, headers = employee_with_login(full_name="ZZ Usage No Info Person")
    _mock_assistant_client(monkeypatch, lambda **kw: _text_response("ok"))
    res = client.post("/api/assistant/chat", headers=headers, json={"message": "hi"})
    assert res.status_code == 200, res.text
    assert _row_for(_report(client, hr_manager_auth).json(), "ZZ Usage No Info Person") is None


def test_chat_canned_reply_for_unlinked_account_records_nothing(client, hr_manager_auth, monkeypatch):
    mock_create = Mock()
    _mock_assistant_client(monkeypatch, mock_create)
    before = _report(client, hr_manager_auth).json()["total"]["requests"]
    res = client.post("/api/assistant/chat", headers=hr_manager_auth, json={"message": "hi"})
    assert res.status_code == 200, res.text
    mock_create.assert_not_called()
    assert _report(client, hr_manager_auth).json()["total"]["requests"] == before


def test_resume_extraction_records_tokens_even_when_response_unusable(client, hr_manager_auth, monkeypatch):
    def fake_create(**kwargs):
        r = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="no tool call")])
        r.usage = _usage(500, 40)
        return r

    _mock_recruitment_client(monkeypatch, fake_create)
    before = _report(client, hr_manager_auth).json()["resume_extraction"]
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth,
                      json={"data_url": "data:application/pdf;base64,JVBERi0xLjQK"})
    assert res.status_code == 502, res.text
    after = _report(client, hr_manager_auth).json()["resume_extraction"]
    assert after["requests"] == before["requests"] + 1
    assert after["total_tokens"] == before["total_tokens"] + 540


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_usage_report_totals_and_per_person_breakdown(client, hr_manager_auth, employee_with_login, monkeypatch):
    emp, headers = employee_with_login(full_name="ZZ Usage Report Person")
    users = client.get("/api/users", headers=hr_manager_auth).json()
    user = next(u for u in users if u["employee_id"] == emp["employee_id"])
    inst_id = user["institution_id"]
    _insert_row(inst_id, user["id"], user["username"], "chat", 10, 5, "2031-03-10 04:00:00")
    _insert_row(inst_id, user["id"], user["username"], "chat", 20, 5, "2031-03-11 04:00:00")
    _insert_row(inst_id, user["id"], user["username"], "resume_extraction", 1000, 100, "2031-03-12 04:00:00")

    body = _report(client, hr_manager_auth, date_from="2031-03-01", date_to="2031-03-31").json()
    row = _row_for(body, "ZZ Usage Report Person")
    assert row["chat_requests"] == 2 and row["chat_tokens"] == 40
    assert row["resume_requests"] == 1 and row["resume_tokens"] == 1100
    assert row["total_tokens"] == 1140
    assert body["chat"]["requests"] >= 2 and body["resume_extraction"]["total_tokens"] >= 1100
    assert body["total"]["total_tokens"] == body["chat"]["total_tokens"] + body["resume_extraction"]["total_tokens"]
    assert body["total"]["input_tokens"] >= 1030 and body["total"]["output_tokens"] >= 110


def test_usage_report_date_range_is_inclusive_and_excludes_outside(client, hr_manager_auth, employee_with_login):
    emp, _ = employee_with_login(full_name="ZZ Usage Range Person")
    users = client.get("/api/users", headers=hr_manager_auth).json()
    user = next(u for u in users if u["employee_id"] == emp["employee_id"])
    inst_id = user["institution_id"]
    _insert_row(inst_id, user["id"], user["username"], "chat", 1, 1, "2032-05-15 04:00:00")
    _insert_row(inst_id, user["id"], user["username"], "chat", 100, 100, "2032-06-20 04:00:00")

    may = _row_for(_report(client, hr_manager_auth, date_from="2032-05-01", date_to="2032-05-31").json(), "ZZ Usage Range Person")
    assert may["chat_tokens"] == 2
    same_day = _row_for(_report(client, hr_manager_auth, date_from="2032-06-20", date_to="2032-06-20").json(), "ZZ Usage Range Person")
    assert same_day["chat_tokens"] == 200
    assert _row_for(_report(client, hr_manager_auth, date_from="2032-07-01", date_to="2032-07-31").json(), "ZZ Usage Range Person") is None


def test_usage_report_falls_back_to_username_for_unlinked_account(client, hr_manager_auth, test_institution):
    _insert_row(test_institution["id"], None, "zz_no_such_user", "chat", 3, 4, "2033-01-05 04:00:00")
    row = _row_for(_report(client, hr_manager_auth, date_from="2033-01-01", date_to="2033-01-31").json(), "zz_no_such_user")
    assert row["chat_tokens"] == 7


def test_usage_report_validates_dates(client, hr_manager_auth):
    assert _report(client, hr_manager_auth, date_from="nope").status_code == 400
    assert _report(client, hr_manager_auth, date_from="2030-02-01", date_to="2030-01-01").status_code == 400


def test_usage_report_hr_manager_only(client, make_test_user, test_institution):
    for role in ("hr_admin", "manager", "employee", "payroll_manager"):
        token, _ = make_test_user(role=role)
        headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
        assert _report(client, headers).status_code == 403, role


def test_usage_report_requires_auth(client):
    assert client.get("/api/assistant/usage", params=WIDE).status_code in (401, 403)


def test_usage_report_never_includes_another_institutions_rows(client, hr_manager_auth, superadmin_headers, test_institution):
    insts = client.get("/api/institutions", headers=superadmin_headers).json()
    other = next((i for i in insts if i["id"] != test_institution["id"]), None)
    if other is None:
        pytest.skip("needs a second institution in the test database")
    _insert_row(other["id"], None, "zz_other_inst_user", "chat", 999, 999, "2034-02-02 04:00:00")
    body = _report(client, hr_manager_auth, date_from="2034-01-01", date_to="2034-12-31").json()
    assert _row_for(body, "zz_other_inst_user") is None
    assert body["total"]["total_tokens"] == 0
