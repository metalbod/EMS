"""API-level tests for Phase 2 of "one candidate, many requisitions"
(routers/recruitment.py using candidate_requisitions — see
migrations/versions/20260930_0002_add_candidate_requisitions.py and
tests/test_candidate_requisitions_schema.py for Phase 1's schema-only
coverage). Covers: POST .../apply, GET .../candidates/search, the new
per-requisition PATCH .../requisitions/{requisition_id}/stage endpoint,
move_stage's ambiguity guard once a candidate has more than one
application, and the transitional dual-write mirror onto
candidates.stage/requisition_id (kept in sync only while a candidate has
exactly one application — see _transition_candidate_stage's docstring).
"""
import os


def _unique_title():
    return f"ZZ Applications Test Role {os.urandom(4).hex()}"


def _make_requisition(client, hr_manager_auth):
    res = client.post("/api/recruitment/requisitions", headers=hr_manager_auth, json={
        "title": _unique_title(), "department": "IT", "headcount": 1,
        "employment_type": "Permanent",
    })
    assert res.status_code == 201, res.text
    return res.json()


def _make_candidate(client, hr_manager_auth, requisition_id=None, **overrides):
    body = {
        "full_name": "ZZ Applications Test Candidate",
        "ic_number": f"ZZ{os.urandom(4).hex()}",
        "requisition_id": requisition_id,
    }
    body.update(overrides)
    res = client.post("/api/recruitment/candidates", headers=hr_manager_auth, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_create_candidate_auto_creates_first_application(client, hr_manager_auth):
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert len(detail["applications"]) == 1
    app = detail["applications"][0]
    assert app["requisition_id"] == req["id"]
    assert app["stage"] == "New"


def test_apply_existing_candidate_to_second_requisition(client, hr_manager_auth):
    """The actual feature: one real person, two independent applications,
    neither duplicating their profile."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    unique_name = f"ZZ Second Req Candidate {os.urandom(4).hex()}"
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"], full_name=unique_name)

    res = client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                       json={"requisition_id": req2["id"], "source": "Referral"})
    assert res.status_code == 201, res.text
    assert res.json()["requisition_id"] == req2["id"]

    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert {a["requisition_id"] for a in detail["applications"]} == {req1["id"], req2["id"]}
    # Only one candidates row exists for this person — apply() must never
    # duplicate the profile.
    listing = client.get("/api/recruitment/candidates/search", headers=hr_manager_auth,
                          params={"q": unique_name}).json()
    assert len(listing) == 1


def test_apply_to_the_same_requisition_twice_is_rejected(client, hr_manager_auth):
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    res = client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                       json={"requisition_id": req["id"]})
    assert res.status_code == 400, res.text


def test_apply_general_interest_twice_is_rejected(client, hr_manager_auth):
    cand = _make_candidate(client, hr_manager_auth, requisition_id=None)
    res = client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                       json={"requisition_id": None})
    assert res.status_code == 400, res.text


def test_stage_independent_across_two_applications(client, hr_manager_auth):
    """Moving one application's stage must not touch the other — the core
    proof that candidate_requisitions (not candidates.stage) is now the
    real source of truth for a multi-application candidate."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"])
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})

    move = client.patch(
        f"/api/recruitment/candidates/{cand['id']}/requisitions/{req1['id']}/stage",
        headers=hr_manager_auth, json={"stage": "Interview"}
    )
    assert move.status_code == 200, move.text
    assert move.json()["stage"] == "Interview"

    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    by_req = {a["requisition_id"]: a["stage"] for a in detail["applications"]}
    assert by_req[req1["id"]] == "Interview"
    assert by_req[req2["id"]] == "New", "the untouched application's stage must not move"


def test_move_stage_ambiguous_for_multi_application_candidate(client, hr_manager_auth):
    """The legacy, candidate-level PATCH .../stage endpoint can't guess
    which application to move once there's more than one — it must point
    the caller at the explicit per-requisition endpoint instead."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"])
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})

    res = client.patch(f"/api/recruitment/candidates/{cand['id']}/stage", headers=hr_manager_auth,
                        json={"stage": "Interview"})
    assert res.status_code == 400, res.text


def test_move_stage_still_works_for_single_application_candidate(client, hr_manager_auth):
    """Every existing single-application candidate (and every current UI
    flow) must keep working unchanged through the legacy endpoint."""
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    res = client.patch(f"/api/recruitment/candidates/{cand['id']}/stage", headers=hr_manager_auth,
                        json={"stage": "Interview"})
    assert res.status_code == 200, res.text
    assert res.json()["stage"] == "Interview"

    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert detail["applications"][0]["stage"] == "Interview"


def test_dual_write_mirrors_stage_for_single_application_candidate(client, hr_manager_auth):
    """candidates.stage (the pre-Phase-3 frontend's own read path) must
    stay in sync as long as the candidate has exactly one application."""
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    client.patch(
        f"/api/recruitment/candidates/{cand['id']}/requisitions/{req['id']}/stage",
        headers=hr_manager_auth, json={"stage": "Screening"}
    )
    legacy = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert legacy["stage"] == "Screening"


def test_dual_write_stops_once_candidate_has_two_applications(client, hr_manager_auth):
    """Once ambiguous, candidates.stage simply stops being updated rather
    than guessing which application it should mirror."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"])
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})
    before = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()["stage"]

    client.patch(
        f"/api/recruitment/candidates/{cand['id']}/requisitions/{req1['id']}/stage",
        headers=hr_manager_auth, json={"stage": "Interview"}
    )
    after = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()["stage"]
    assert after == before, "candidates.stage must not be mutated once the candidate has more than one application"


def test_search_returns_person_with_every_application(client, hr_manager_auth):
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    unique_name = f"ZZ Search Target {os.urandom(4).hex()}"
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"], full_name=unique_name)
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})

    res = client.get("/api/recruitment/candidates/search", headers=hr_manager_auth, params={"q": unique_name})
    assert res.status_code == 200, res.text
    matches = res.json()
    assert len(matches) == 1
    assert {a["requisition_id"] for a in matches[0]["applications"]} == {req1["id"], req2["id"]}


def test_search_rejects_too_short_query(client, hr_manager_auth):
    res = client.get("/api/recruitment/candidates/search", headers=hr_manager_auth, params={"q": "a"})
    assert res.status_code == 400


def test_requisition_candidate_count_counts_applications_not_people(client, hr_manager_auth):
    """A candidate applying to two requisitions must count once at each
    requisition — candidate_count is per-application, not per-person."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"])
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})

    listing = client.get("/api/recruitment/requisitions", headers=hr_manager_auth).json()
    row1 = next(r for r in listing if r["id"] == req1["id"])
    row2 = next(r for r in listing if r["id"] == req2["id"])
    assert row1["candidate_count"] == 1
    assert row2["candidate_count"] == 1
