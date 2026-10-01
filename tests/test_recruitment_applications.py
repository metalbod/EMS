"""API-level tests for "one candidate, many requisitions"
(routers/recruitment.py using candidate_requisitions — see
migrations/versions/20260930_0002_add_candidate_requisitions.py and
tests/test_candidate_requisitions_schema.py for Phase 1's schema-only
coverage). Covers: POST .../apply, GET .../candidates/search, the new
per-requisition PATCH .../requisitions/{requisition_id}/stage endpoint,
move_stage's ambiguity guard once a candidate has more than one
application, and get_candidate's derived top-level stage/requisition
fields (_candidate_with_derived_fields in routers/recruitment.py) now that
candidates itself carries no application-level columns of its own (Phase
4 — see 20261001_0001_drop_candidates_legacy_application_columns).
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


def test_candidate_detail_stage_derives_from_sole_application(client, hr_manager_auth):
    """get_candidate's top-level `stage` (Candidate Detail's header badge
    and legacy single stage-select both read this) is derived from the
    candidate's one application, since candidates itself carries no stage
    column of its own anymore."""
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    client.patch(
        f"/api/recruitment/candidates/{cand['id']}/requisitions/{req['id']}/stage",
        headers=hr_manager_auth, json={"stage": "Screening"}
    )
    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert detail["stage"] == "Screening"
    assert detail["requisition"]["id"] == req["id"]


def test_candidate_detail_stage_is_none_once_ambiguous(client, hr_manager_auth):
    """Once a candidate has more than one application, get_candidate's
    top-level `stage`/`requisition` have no single answer to derive — None
    rather than guessing which application they mean. The Applications
    section (not these top-level fields) is the real multi-application
    view."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"])
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})
    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert detail["stage"] is None
    assert detail["requisition"] is None

    client.patch(
        f"/api/recruitment/candidates/{cand['id']}/requisitions/{req1['id']}/stage",
        headers=hr_manager_auth, json={"stage": "Interview"}
    )
    after = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert after["stage"] is None


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


def test_candidate_list_shows_one_row_per_application(client, hr_manager_auth):
    """list_candidates (the Candidate Bank table, and the Interview/Offer
    "select candidate" pickers that reuse it) is per-APPLICATION since
    Phase 4, not per-person — a candidate with two applications appears
    twice, once per requisition, each with its own stage."""
    req1 = _make_requisition(client, hr_manager_auth)
    req2 = _make_requisition(client, hr_manager_auth)
    unique_name = f"ZZ List Shape Candidate {os.urandom(4).hex()}"
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req1["id"], full_name=unique_name)
    client.post(f"/api/recruitment/candidates/{cand['id']}/apply", headers=hr_manager_auth,
                json={"requisition_id": req2["id"]})

    rows = client.get("/api/recruitment/candidates", headers=hr_manager_auth,
                       params={"search": unique_name}).json()
    assert len(rows) == 2
    assert all(r["id"] == cand["id"] for r in rows)
    assert {r["requisition_id"] for r in rows} == {req1["id"], req2["id"]}


def test_schedule_interview_resolves_requisition_from_sole_application(client, hr_manager_auth):
    """The Interview modal has no requisition picker of its own — the
    backend resolves it from the candidate's one application so the
    interview (and the auto stage-move it triggers) ties to the real
    requisition instead of silently landing on NULL/general-interest."""
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    res = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "interview_type": "Phone",
        "scheduled_date": "2027-01-15", "scheduled_time": "10:00",
    })
    assert res.status_code == 201, res.text
    assert res.json()["requisition_id"] == req["id"]

    detail = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert detail["stage"] == "Interview"


def test_create_offer_resolves_requisition_from_sole_application_when_unset(client, hr_manager_auth):
    """Same resolution as scheduling an interview, for the Offer form's own
    requisition picker when HR leaves it blank (defaults to None)."""
    req = _make_requisition(client, hr_manager_auth)
    cand = _make_candidate(client, hr_manager_auth, requisition_id=req["id"])
    res = client.post("/api/recruitment/offers", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "offer_type": "Offer", "salary_offered": 5000,
    })
    assert res.status_code == 201, res.text
    assert res.json()["requisition_id"] == req["id"]
