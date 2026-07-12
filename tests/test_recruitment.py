"""Integration tests for routers/recruitment.py."""
import os


def _unique_title():
    return f"ZZ Test Role {os.urandom(4).hex()}"


# ---------------------------------------------------------------------------
# Job Requisitions
# ---------------------------------------------------------------------------
def test_list_requisitions_requires_auth(client):
    res = client.get("/api/recruitment/requisitions")
    assert res.status_code in (401, 403)


def test_create_requisition_requires_write_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/recruitment/requisitions", headers=headers,
                       json={"title": _unique_title(), "department": "Engineering"})
    assert res.status_code == 403


def test_create_requisition_success_and_appears_in_list(client, hr_manager_auth):
    title = _unique_title()
    res = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": title, "department": "Engineering", "headcount": 2})
    assert res.status_code == 201, res.text
    req = res.json()
    assert req["status"] == "Draft"

    listing = client.get("/api/recruitment/requisitions", headers=hr_manager_auth,
                          params={"department": "Engineering"})
    assert listing.status_code == 200
    assert any(r["id"] == req["id"] for r in listing.json())


def test_get_requisition_includes_candidates(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    res = client.get(f"/api/recruitment/requisitions/{req['id']}", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json()["candidates"] == []


def test_get_requisition_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/recruitment/requisitions/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_update_requisition_only_draft_editable(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    submit = client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)
    assert submit.status_code == 200, submit.text

    res = client.put(f"/api/recruitment/requisitions/{req['id']}", headers=hr_manager_auth, json={
        "title": "ZZ Cannot Edit", "department": "Sales",
    })
    assert res.status_code == 400


def test_update_requisition_success_while_draft(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    res = client.put(f"/api/recruitment/requisitions/{req['id']}", headers=hr_manager_auth, json={
        "title": "ZZ Updated Title", "department": "Sales", "headcount": 3,
    })
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "ZZ Updated Title"


def test_submit_requisition_wrong_status_returns_400(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)
    res = client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)
    assert res.status_code == 400


def test_approve_requisition_requires_superadmin_or_hr_manager(client, make_test_user, test_institution, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)

    token, _ = make_test_user(role="hr_admin")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.patch(f"/api/recruitment/requisitions/{req['id']}/approve", headers=headers,
                        json={"action": "approve"})
    assert res.status_code == 403


def test_approve_requisition_wrong_status_returns_400(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    res = client.patch(f"/api/recruitment/requisitions/{req['id']}/approve", headers=hr_manager_auth,
                        json={"action": "approve"})
    assert res.status_code == 400


def test_approve_requisition_invalid_action_returns_400(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)
    res = client.patch(f"/api/recruitment/requisitions/{req['id']}/approve", headers=hr_manager_auth,
                        json={"action": "bogus"})
    assert res.status_code == 400


def test_approve_requisition_success(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    client.patch(f"/api/recruitment/requisitions/{req['id']}/submit", headers=hr_manager_auth)
    res = client.patch(f"/api/recruitment/requisitions/{req['id']}/approve", headers=hr_manager_auth,
                        json={"action": "approve", "comments": "ZZ looks good"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Approved"


def test_close_requisition_success(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Sales"}).json()
    res = client.patch(f"/api/recruitment/requisitions/{req['id']}/close", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Closed"


# ---------------------------------------------------------------------------
# Candidates / ATS
# ---------------------------------------------------------------------------
def test_list_candidates_requires_auth(client):
    res = client.get("/api/recruitment/candidates")
    assert res.status_code in (401, 403)


def test_create_candidate_requires_write_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.post("/api/recruitment/candidates", headers=headers, json={"full_name": "ZZ Candidate"})
    assert res.status_code == 403


def test_create_candidate_success_and_appears_in_list(client, hr_manager_auth):
    res = client.post("/api/recruitment/candidates", headers=hr_manager_auth, json={
        "full_name": "ZZ Jane Candidate", "email": "zzjane@example.com", "source": "LinkedIn",
    })
    assert res.status_code == 201, res.text
    cand = res.json()
    assert cand["stage"] == "New"

    listing = client.get("/api/recruitment/candidates", headers=hr_manager_auth, params={"search": "ZZ Jane"})
    assert listing.status_code == 200
    assert any(c["id"] == cand["id"] for c in listing.json())


def test_get_candidate_includes_interviews_and_offers(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Candidate Detail"}).json()
    res = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert body["interviews"] == []
    assert body["offers"] == []


def test_get_candidate_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/recruitment/candidates/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_update_candidate_success(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Before Update"}).json()
    res = client.put(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth,
                      json={"full_name": "ZZ After Update", "source": "Referral"})
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "ZZ After Update"


def test_move_stage_invalid_stage_returns_400(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Stage Candidate"}).json()
    res = client.patch(f"/api/recruitment/candidates/{cand['id']}/stage", headers=hr_manager_auth,
                        json={"stage": "Bogus"})
    assert res.status_code == 400


def test_move_stage_success(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Stage Candidate 2"}).json()
    res = client.patch(f"/api/recruitment/candidates/{cand['id']}/stage", headers=hr_manager_auth,
                        json={"stage": "Screening", "notes": "ZZ looks promising"})
    assert res.status_code == 200, res.text
    assert res.json()["stage"] == "Screening"


def test_candidate_audit_log_records_creation_and_stage_change(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Audit Candidate"}).json()
    client.patch(f"/api/recruitment/candidates/{cand['id']}/stage", headers=hr_manager_auth,
                 json={"stage": "Screening"})
    res = client.get(f"/api/recruitment/candidates/{cand['id']}/audit-log", headers=hr_manager_auth)
    assert res.status_code == 200
    actions = [a["action"] for a in res.json()]
    assert "Created" in actions
    assert "Stage Changed" in actions


def test_candidate_audit_log_requires_manage_role(client, hr_manager_auth, make_test_user, test_institution):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Restricted Audit Candidate"}).json()
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get(f"/api/recruitment/candidates/{cand['id']}/audit-log", headers=headers)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------
def test_schedule_interview_candidate_not_found_returns_404(client, hr_manager_auth):
    res = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": 999999999, "scheduled_date": "2030-01-01", "scheduled_time": "10:00",
    })
    assert res.status_code == 404


def test_schedule_interview_success_moves_candidate_to_interview_stage(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Interview Candidate"}).json()
    res = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "interview_type": "Video",
        "scheduled_date": "2030-01-01", "scheduled_time": "10:00", "interviewers": "ZZ Interviewer",
    })
    assert res.status_code == 201, res.text
    interview = res.json()
    assert interview["candidate_name"] == "ZZ Interview Candidate"

    cand_check = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert cand_check["stage"] == "Interview"


def test_update_interview_not_found_returns_404(client, hr_manager_auth):
    res = client.put("/api/recruitment/interviews/999999999", headers=hr_manager_auth, json={
        "candidate_id": 1, "scheduled_date": "2030-01-01", "scheduled_time": "10:00",
    })
    assert res.status_code == 404


def test_update_interview_status_invalid_returns_400(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Status Candidate"}).json()
    interview = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "scheduled_date": "2030-01-01", "scheduled_time": "10:00",
    }).json()
    res = client.patch(f"/api/recruitment/interviews/{interview['id']}/status", headers=hr_manager_auth,
                        json={"status": "Bogus"})
    assert res.status_code == 400


def test_update_interview_status_success(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Status Candidate 2"}).json()
    interview = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "scheduled_date": "2030-01-01", "scheduled_time": "10:00",
    }).json()
    res = client.patch(f"/api/recruitment/interviews/{interview['id']}/status", headers=hr_manager_auth,
                        json={"status": "Completed", "notes": "ZZ went well"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Completed"


def test_list_interviews_filters_by_candidate(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ List Candidate"}).json()
    interview = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "scheduled_date": "2030-02-01", "scheduled_time": "11:00",
    }).json()
    res = client.get("/api/recruitment/interviews", headers=hr_manager_auth,
                      params={"candidate_id": cand["id"]})
    assert res.status_code == 200
    assert any(i["id"] == interview["id"] for i in res.json())


def test_submit_score_interview_not_found_returns_404(client, hr_manager_auth):
    res = client.post("/api/recruitment/interviews/999999999/scores", headers=hr_manager_auth,
                       json={"overall_score": 8, "recommendation": "Yes"})
    assert res.status_code == 404


def test_submit_score_success_and_upserts_on_resubmit(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Score Candidate"}).json()
    interview = client.post("/api/recruitment/interviews", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "scheduled_date": "2030-03-01", "scheduled_time": "09:00",
    }).json()
    res = client.post(f"/api/recruitment/interviews/{interview['id']}/scores", headers=hr_manager_auth, json={
        "technical_score": 7, "communication_score": 8, "overall_score": 7, "recommendation": "Yes",
    })
    assert res.status_code == 201, res.text

    # Re-submitting as the same scorer upserts rather than creating a duplicate row
    res2 = client.post(f"/api/recruitment/interviews/{interview['id']}/scores", headers=hr_manager_auth, json={
        "technical_score": 9, "overall_score": 9, "recommendation": "Strong Yes",
    })
    assert res2.status_code == 201, res2.text

    scores = client.get(f"/api/recruitment/interviews/{interview['id']}/scores", headers=hr_manager_auth)
    assert scores.status_code == 200
    rows = scores.json()
    assert len(rows) == 1
    assert rows[0]["technical_score"] == 9


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------
def test_list_offers_requires_write_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/recruitment/offers", headers=headers)
    assert res.status_code == 403


def test_create_offer_auto_generates_letter_and_moves_stage(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": _unique_title(), "department": "Engineering"}).json()
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Offer Candidate", "requisition_id": req["id"]}).json()
    res = client.post("/api/recruitment/offers", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "requisition_id": req["id"],
        "offer_type": "Offer", "salary_offered": 6000.0, "start_date": "2030-01-01",
    })
    assert res.status_code == 201, res.text
    offer = res.json()
    assert "LETTER OF OFFER" in offer["letter_content"]
    assert "ZZ Offer Candidate" in offer["letter_content"]

    cand_check = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert cand_check["stage"] == "Offer"


def test_create_decline_offer_moves_candidate_to_rejected(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Decline Candidate"}).json()
    res = client.post("/api/recruitment/offers", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "offer_type": "Decline",
    })
    assert res.status_code == 201, res.text
    assert "regret to inform" in res.json()["letter_content"]

    cand_check = client.get(f"/api/recruitment/candidates/{cand['id']}", headers=hr_manager_auth).json()
    assert cand_check["stage"] == "Rejected"


def test_get_offer_not_found_returns_404(client, hr_manager_auth):
    res = client.get("/api/recruitment/offers/999999999", headers=hr_manager_auth)
    assert res.status_code == 404


def test_update_offer_status_invalid_returns_400(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Offer Status Candidate"}).json()
    offer = client.post("/api/recruitment/offers", headers=hr_manager_auth,
                         json={"candidate_id": cand["id"]}).json()
    res = client.patch(f"/api/recruitment/offers/{offer['id']}/status", headers=hr_manager_auth,
                        json={"status": "Bogus"})
    assert res.status_code == 400


def test_update_offer_status_not_found_returns_404(client, hr_manager_auth):
    res = client.patch("/api/recruitment/offers/999999999/status", headers=hr_manager_auth,
                        json={"status": "Sent"})
    assert res.status_code == 404


def test_update_offer_status_success(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Offer Status Candidate 2"}).json()
    offer = client.post("/api/recruitment/offers", headers=hr_manager_auth,
                         json={"candidate_id": cand["id"], "salary_offered": 5000.0}).json()
    res = client.patch(f"/api/recruitment/offers/{offer['id']}/status", headers=hr_manager_auth,
                        json={"status": "Accepted"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Accepted"


def test_generate_letter_regenerates_content(client, hr_manager_auth):
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth,
                        json={"full_name": "ZZ Regen Candidate"}).json()
    offer = client.post("/api/recruitment/offers", headers=hr_manager_auth,
                         json={"candidate_id": cand["id"], "salary_offered": 4000.0}).json()
    res = client.post(f"/api/recruitment/offers/{offer['id']}/generate-letter", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    assert "ZZ Regen Candidate" in res.json()["letter_content"]


def test_generate_letter_not_found_returns_404(client, hr_manager_auth):
    res = client.post("/api/recruitment/offers/999999999/generate-letter", headers=hr_manager_auth)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Convert-to-employee prefill, meta, dashboard stats
# ---------------------------------------------------------------------------
def test_convert_prefill_pulls_accepted_offer_details(client, hr_manager_auth):
    req = client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                       json={"title": "ZZ Prefill Role", "department": "Engineering",
                             "employment_type": "Permanent"}).json()
    cand = client.post("/api/recruitment/candidates", headers=hr_manager_auth, json={
        "full_name": "ZZ Prefill Candidate", "ic_number": "900101015555",
        "requisition_id": req["id"],
    }).json()
    offer = client.post("/api/recruitment/offers", headers=hr_manager_auth, json={
        "candidate_id": cand["id"], "requisition_id": req["id"], "salary_offered": 5500.0, "start_date": "2030-02-01",
    }).json()
    client.patch(f"/api/recruitment/offers/{offer['id']}/status", headers=hr_manager_auth, json={"status": "Accepted"})

    res = client.get(f"/api/recruitment/candidates/{cand['id']}/convert-prefill", headers=hr_manager_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["full_name"] == "ZZ Prefill Candidate"
    assert body["department"] == "Engineering"
    assert body["basic_salary"] == 5500.0
    assert body["candidate_id"] == cand["id"]


def test_recruitment_meta_contains_expected_lists(client, hr_manager_auth):
    res = client.get("/api/recruitment/meta", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert "New" in body["stages"]
    assert "Offer" in body["offer_types"]


def test_dashboard_stats_reflects_created_data(client, hr_manager_auth):
    before = client.get("/api/recruitment/dashboard-stats", headers=hr_manager_auth).json()
    before_total = before["total_requisitions"]

    client.post("/api/recruitment/requisitions", headers=hr_manager_auth,
                json={"title": _unique_title(), "department": "Marketing"})

    res = client.get("/api/recruitment/dashboard-stats", headers=hr_manager_auth)
    assert res.status_code == 200
    after = res.json()
    assert after["total_requisitions"] == before_total + 1
    assert after["req_by_status"].get("Draft", 0) >= 1
    assert "cand_by_stage" in after
