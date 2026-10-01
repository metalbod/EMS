"""Integration tests for Add Candidate's "Extract with AI" resume parsing
(routers/recruitment.py's extract_resume_fields). The Anthropic client is
always mocked here — no test hits the real API, same convention as
tests/test_assistant.py.
"""
import types

import anthropic
import httpx
import pytest

import routers.recruitment as recruitment_module

TINY_PDF_DATA_URL = "data:application/pdf;base64,JVBERi0xLjQK"
TINY_PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgo="
TINY_WORD_DATA_URL = "data:application/msword;base64,0M8R4KGxGuE="


def _tool_use_response(tool_input, block_id="toolu_01"):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", name="extract_candidate_fields", input=tool_input, id=block_id)],
    )


def _text_only_response(text="not a tool call"):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])


def _mock_client(monkeypatch, create_fn):
    fake_client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create_fn))
    monkeypatch.setattr(recruitment_module, "get_client_for_institution", lambda conn, inst_id: fake_client)
    return fake_client


def test_extract_resume_requires_auth(client):
    res = client.post("/api/recruitment/candidates/extract-resume", json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code in (401, 403)


def test_extract_resume_requires_write_role(client, make_test_user, test_institution, monkeypatch):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    _mock_client(monkeypatch, lambda **kw: _tool_use_response({"full_name": "Should Not Reach Here"}))
    res = client.post("/api/recruitment/candidates/extract-resume", headers=headers, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 403


def test_extract_resume_rejects_word_document(client, hr_manager_auth):
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_WORD_DATA_URL})
    assert res.status_code == 422, res.text


def test_extract_resume_rejects_oversized_file(client, hr_manager_auth):
    oversized = "data:application/pdf;base64," + ("A" * 9_000_000)
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": oversized})
    assert res.status_code == 422, res.text


def test_extract_resume_no_ai_configured(client, hr_manager_auth, monkeypatch):
    monkeypatch.setattr(recruitment_module, "get_client_for_institution", lambda conn, inst_id: None)
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 400, res.text
    assert "AI extraction isn't set up" in res.json()["detail"]


def test_extract_resume_happy_path_pdf(client, hr_manager_auth, monkeypatch):
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _tool_use_response({
            "full_name": "ZZ Extracted Candidate",
            "email": "zz.extracted@example.com",
            "experience_years": 5,
            "highest_qualification": "Bachelor's Degree",
            "skills": "Python, SQL, React",
        })

    _mock_client(monkeypatch, fake_create)
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 200, res.text
    fields = res.json()["fields"]
    assert fields["full_name"] == "ZZ Extracted Candidate"
    assert fields["email"] == "zz.extracted@example.com"
    assert fields["experience_years"] == 5
    assert fields["highest_qualification"] == "Bachelor's Degree"
    assert fields["phone"] is None  # omitted by the model, not guessed

    # The content block sent to Claude must use "document" for a PDF, be
    # forced to the single extraction tool, and request only the one tool.
    sent = calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "extract_candidate_fields"}
    assert len(sent["tools"]) == 1
    content_block = sent["messages"][0]["content"][0]
    assert content_block["type"] == "document"
    assert content_block["source"]["media_type"] == "application/pdf"


def test_extract_resume_happy_path_image(client, hr_manager_auth, monkeypatch):
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _tool_use_response({"full_name": "ZZ Image Resume Candidate"})

    _mock_client(monkeypatch, fake_create)
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PNG_DATA_URL})
    assert res.status_code == 200, res.text
    content_block = calls[0]["messages"][0]["content"][0]
    assert content_block["type"] == "image"
    assert content_block["source"]["media_type"] == "image/png"


def test_extract_resume_no_tool_use_returns_502(client, hr_manager_auth, monkeypatch):
    _mock_client(monkeypatch, lambda **kw: _text_only_response())
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 502, res.text


def test_extract_resume_invalid_tool_input_returns_502(client, hr_manager_auth, monkeypatch):
    # graduation_year must be an int — a model misbehaving (or a schema
    # drift) must fail cleanly, not 500.
    _mock_client(monkeypatch, lambda **kw: _tool_use_response({"graduation_year": "not-a-year"}))
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 502, res.text


def test_extract_resume_anthropic_error_returns_502(client, hr_manager_auth, monkeypatch):
    def fake_create(**kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    _mock_client(monkeypatch, fake_create)
    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 502, res.text


def test_extract_resume_rate_limit_returns_429(client, hr_manager_auth, monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.counts = {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, ttl):
            pass

    monkeypatch.setattr(recruitment_module, "_redis", _FakeRedis())
    _mock_client(monkeypatch, lambda **kw: _tool_use_response({"full_name": "ZZ Rate Limit Candidate"}))

    for _ in range(recruitment_module.EXTRACT_RESUME_RATE_LIMIT_PER_HOUR):
        res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
        assert res.status_code == 200, res.text

    res = client.post("/api/recruitment/candidates/extract-resume", headers=hr_manager_auth, json={"data_url": TINY_PDF_DATA_URL})
    assert res.status_code == 429, res.text
