"""Tests for the public (no-login) job application flow —
routers/public_careers.py and the enable/disable-public-link endpoints in
routers/recruitment.py. See 20261001_0002_add_requisition_public_token.

No fixture provides an unauthenticated-but-institution-scoped client (by
design — nothing else in this app works that way), so every `client.get`/
`client.post` call to a `/api/public/...` path below is made with NO
`headers` kwarg at all, exactly as a real anonymous browser request would.
"""
import os


def _unique_title():
    return f"ZZ Public Careers Test Role {os.urandom(4).hex()}"


def _approved_requisition(client, hr_manager_auth, **overrides):
    body = {"title": _unique_title(), "department": "Engineering"}
    body.update(overrides)
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth, json=body).json()
    client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)
    approved = client.patch(f"/api/recruitment/requisitions/{req['id']}/approve", headers=hr_manager_auth,
                             json={"action": "approve"}).json()
    assert approved["status"] == "Approved", approved
    return approved


def _enable_public_link(client, hr_manager_auth, req_id):
    res = client.post(f"/api/recruitment/requisitions/{req_id}/public-link", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    return res.json()["public_token"]


def _find_candidate_by_email(client, hr_manager_auth, email):
    """search_candidates' own summary omits `source` (it only needs
    requisition_id/stage/requisition_title for the duplicate-detection
    panel) — fetch the full candidate detail for anything needing more."""
    matches = client.get("/api/recruitment/candidates/search", headers=hr_manager_auth,
                          params={"q": email}).json()
    assert len(matches) == 1, matches
    return client.get(f"/api/recruitment/candidates/{matches[0]['id']}", headers=hr_manager_auth).json()


# ---------------------------------------------------------------------------
# Enabling/disabling the link (HR-authenticated)
# ---------------------------------------------------------------------------
def test_enable_public_link_requires_approved_status(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Engineering"}).json()
    res = client.post(f"/api/recruitment/requisitions/{req['id']}/public-link", headers=hr_manager_auth)
    assert res.status_code == 400


def test_enable_public_link_is_idempotent(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token1 = _enable_public_link(client, hr_manager_auth, req["id"])
    token2 = _enable_public_link(client, hr_manager_auth, req["id"])
    assert token1 == token2, "enabling twice must not generate a second token"


def test_disable_public_link_clears_token(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])

    disable = client.delete(f"/api/recruitment/requisitions/{req['id']}/public-link", headers=hr_manager_auth)
    assert disable.status_code == 200, disable.text

    res = client.get(f"/api/public/careers/apply/{token}")
    assert res.status_code == 404


def test_closing_requisition_blocks_public_apply_even_with_live_token(client, hr_manager_auth):
    """The public endpoints re-check status live — closing a requisition
    must take effect immediately without HR needing to separately revoke
    the link."""
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])
    client.patch(f"/api/recruitment/requisitions/{req['id']}/close", headers=hr_manager_auth)

    res = client.get(f"/api/public/careers/apply/{token}")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Public listing + detail (anonymous)
# ---------------------------------------------------------------------------
def test_careers_listing_includes_only_approved_and_public_enabled(client, hr_manager_auth, test_institution):
    draft = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                         json={"title": _unique_title(), "department": "Engineering"}).json()
    approved_not_public = _approved_requisition(client, hr_manager_auth)
    approved_and_public = _approved_requisition(client, hr_manager_auth)
    _enable_public_link(client, hr_manager_auth, approved_and_public["id"])

    res = client.get(f"/api/public/careers/{test_institution['code']}")
    assert res.status_code == 200, res.text
    titles = {p["title"] for p in res.json()["positions"]}
    assert approved_and_public["title"] in titles
    assert draft["title"] not in titles
    assert approved_not_public["title"] not in titles


def test_careers_listing_unknown_institution_code_404s(client):
    res = client.get("/api/public/careers/ZZNOSUCHCODE999")
    assert res.status_code == 404


def test_get_public_requisition_unknown_token_404s(client):
    res = client.get("/api/public/careers/apply/not-a-real-token")
    assert res.status_code == 404


def test_get_public_requisition_returns_public_safe_fields(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth, department="Finance")
    token = _enable_public_link(client, hr_manager_auth, req["id"])

    res = client.get(f"/api/public/careers/apply/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == req["title"]
    assert body["department"] == "Finance"
    assert "id" not in body and "institution_id" not in body, "must never leak internal ids to an anonymous caller"


# ---------------------------------------------------------------------------
# Submitting an application (anonymous)
# ---------------------------------------------------------------------------
def test_submit_application_creates_candidate_and_application(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])
    email = f"zz.public.{os.urandom(4).hex()}@example.com"

    res = client.post(f"/api/public/careers/apply/{token}", json={
        "full_name": "ZZ Public Applicant", "email": email, "phone": "012-3456789",
    })
    assert res.status_code == 201, res.text
    assert res.json() == {"ok": True, "message": "Application received"}

    found = _find_candidate_by_email(client, hr_manager_auth, email)
    assert found["applications"][0]["source"] == "Direct"
    assert found["applications"][0]["requisition_id"] == req["id"]


def test_submit_twice_same_job_does_not_duplicate_or_error(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])
    email = f"zz.public.{os.urandom(4).hex()}@example.com"
    body = {"full_name": "ZZ Resubmitter", "email": email}

    first = client.post(f"/api/public/careers/apply/{token}", json=body)
    second = client.post(f"/api/public/careers/apply/{token}", json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json(), "a resubmission must look identical to the caller, not reveal it already existed"

    found = client.get("/api/recruitment/candidates/search", headers=hr_manager_auth,
                        params={"q": email}).json()
    assert len(found) == 1
    assert len(found[0]["applications"]) == 1


def test_submit_same_email_different_job_reuses_candidate(client, hr_manager_auth):
    req1 = _approved_requisition(client, hr_manager_auth)
    req2 = _approved_requisition(client, hr_manager_auth)
    token1 = _enable_public_link(client, hr_manager_auth, req1["id"])
    token2 = _enable_public_link(client, hr_manager_auth, req2["id"])
    email = f"zz.public.{os.urandom(4).hex()}@example.com"

    client.post(f"/api/public/careers/apply/{token1}", json={"full_name": "ZZ Multi Applicant", "email": email})
    client.post(f"/api/public/careers/apply/{token2}", json={"full_name": "ZZ Multi Applicant", "email": email})

    found = client.get("/api/recruitment/candidates/search", headers=hr_manager_auth,
                        params={"q": email}).json()
    assert len(found) == 1, "same email across two jobs must be ONE candidate, not two"
    assert {a["requisition_id"] for a in found[0]["applications"]} == {req1["id"], req2["id"]}


def test_submit_rejects_non_pdf_word_resume(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])
    res = client.post(f"/api/public/careers/apply/{token}", json={
        "full_name": "ZZ Image Resume Applicant", "email": f"zz.public.{os.urandom(4).hex()}@example.com",
        "resume_file_name": "photo.png", "resume_mime_type": "image/png",
        "resume_data_url": "data:image/png;base64,aGVsbG8=",
    })
    assert res.status_code == 422


def test_submit_accepts_pdf_resume(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])
    email = f"zz.public.{os.urandom(4).hex()}@example.com"
    res = client.post(f"/api/public/careers/apply/{token}", json={
        "full_name": "ZZ PDF Resume Applicant", "email": email,
        "resume_file_name": "resume.pdf", "resume_mime_type": "application/pdf",
        "resume_data_url": "data:application/pdf;base64,aGVsbG8=",
    })
    assert res.status_code == 201, res.text


def test_submit_unknown_token_404s(client):
    res = client.post("/api/public/careers/apply/not-a-real-token", json={
        "full_name": "ZZ Nobody", "email": "zz.nobody@example.com",
    })
    assert res.status_code == 404


def test_submit_internal_tagged_when_logged_in_to_same_institution(client, hr_manager_auth):
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])
    email = f"zz.public.{os.urandom(4).hex()}@example.com"

    res = client.post(f"/api/public/careers/apply/{token}",
                       headers={"Authorization": hr_manager_auth["Authorization"]},
                       json={"full_name": "ZZ Internal Applicant", "email": email})
    assert res.status_code == 201, res.text

    found = _find_candidate_by_email(client, hr_manager_auth, email)
    assert found["applications"][0]["source"] == "Internal"


def test_submit_not_tagged_internal_for_a_different_institutions_session(client, hr_manager_auth, superadmin_headers):
    """An employee logged into Company B must not have their application to
    Company A's public posting silently tagged as if they're a Company A
    insider."""
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])

    other_code = f"ZZPUBOTHER{os.urandom(4).hex()}".upper()
    other_username = f"zzpubother_admin_{os.urandom(4).hex()}"
    other = client.post("/api/institutions", headers=superadmin_headers, json={
        "name": "ZZ Public Careers Other Institution", "code": other_code,
        "contact_email": "zzpubother@example.com",
        "admin_username": other_username,
        "admin_full_name": "ZZ Other Admin", "admin_password": "ZzPytest@123",
    })
    assert other.status_code == 201, other.text
    other_login = client.post("/api/auth/login", json={
        "username": other_username, "password": "ZzPytest@123", "institution_code": other_code,
    })
    assert other_login.status_code == 200, other_login.text
    other_token = other_login.json()["access_token"]

    email = f"zz.public.{os.urandom(4).hex()}@example.com"
    res = client.post(f"/api/public/careers/apply/{token}",
                       headers={"Authorization": f"Bearer {other_token}"},
                       json={"full_name": "ZZ Cross-Institution Applicant", "email": email})
    assert res.status_code == 201, res.text

    found = _find_candidate_by_email(client, hr_manager_auth, email)
    assert found["applications"][0]["source"] == "Direct", \
        "an employee of a DIFFERENT institution must not be tagged Internal here"


def test_rate_limit_eventually_blocks_repeated_submissions(client, hr_manager_auth):
    """The in-memory limiter is keyed by client IP, and Starlette's
    TestClient always reports the same fixed host — shared across every
    test in this file that's landed on the same pytest-xdist worker, by
    design (same tradeoff as routers/auth.py's login limiter). So this
    doesn't assert an exact call count; it just submits enough requests to
    guarantee the limit is hit somewhere in the run and checks a 429
    actually appears, with the right shape, rather than every call
    silently succeeding forever."""
    req = _approved_requisition(client, hr_manager_auth)
    token = _enable_public_link(client, hr_manager_auth, req["id"])

    statuses = []
    for _ in range(20):
        res = client.post(f"/api/public/careers/apply/{token}", json={
            "full_name": "ZZ Rate Limit Test", "email": f"zz.ratelimit.{os.urandom(4).hex()}@example.com",
        })
        statuses.append(res.status_code)
        if res.status_code == 429:
            assert "Try again" in res.json()["detail"]
            break
    assert 429 in statuses, f"expected a 429 somewhere in {statuses}"
