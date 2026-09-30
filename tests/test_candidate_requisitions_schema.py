"""Schema-level tests for candidate_requisitions (migrations/versions/
20260930_0002_add_candidate_requisitions.py) — Phase 1 of "one candidate,
many requisitions". Deliberately NOT endpoint-level: these call db.py
directly, the same pattern tests/test_rls_enforcement.py uses to verify RLS
independent of any endpoint's own query, so this file's job is only to prove
the table itself — constraints, trigger, RLS — behaves as the migration
intends, and stays that way if it's ever touched again. Phase 2's own
API-level behavior (apply/search/move-stage endpoints, dual-write mirror) is
covered separately in tests/test_recruitment_applications.py.
"""
import os

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from db import get_admin_db, get_db, set_rls_context

from conftest import _valid_employee_payload


@pytest.fixture
def two_requisitions_and_a_candidate(client, hr_manager_auth, test_institution):
    """One candidate, two disposable requisitions for that same institution
    — the exact shape this whole feature exists for ("can 1 candidate try
    for 2 job requisitions?"). Requisitions/candidates have no delete
    endpoint (only status changes), so — same as every other such entity
    in this codebase (employees, institutions) — these are left behind
    rather than torn down; only the candidate_requisitions rows this file
    inserts directly get cleaned up, since nothing else depends on them
    yet."""
    inst_id = test_institution["id"]
    reqs = []
    for _ in range(2):
        res = client.post("/api/recruitment/requisitions", headers=hr_manager_auth, json={
            "title": "ZZ Schema Test Role", "department": "IT", "headcount": 1,
            "employment_type": "Permanent",
        })
        assert res.status_code == 201, res.text
        reqs.append(res.json())

    cand_res = client.post("/api/recruitment/candidates", headers=hr_manager_auth, json={
        "full_name": "ZZ Schema Test Candidate", "ic_number": f"ZZ{os.urandom(4).hex()}",
        "requisition_id": reqs[0]["id"],
    })
    assert cand_res.status_code == 201, cand_res.text
    return {"institution_id": inst_id, "candidate": cand_res.json(), "requisitions": reqs}


def _cleanup(conn, candidate_id):
    conn.execute("DELETE FROM candidate_requisitions WHERE candidate_id=?", (candidate_id,))
    conn.commit()


def test_table_shape_matches_the_migration(two_requisitions_and_a_candidate):
    conn = get_admin_db()
    try:
        rls = conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='candidate_requisitions'"
        ).fetchone()
        assert rls["relrowsecurity"] and rls["relforcerowsecurity"], "RLS must be both enabled and forced, like every other tenant-scoped table"
        policies = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_policies WHERE tablename='candidate_requisitions'"
        ).fetchone()
        assert policies["n"] == 1
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='candidate_requisitions'"
        ).fetchall()}
        assert cols >= {"id", "institution_id", "candidate_id", "requisition_id", "stage",
                        "source", "notes", "expected_salary", "notice_period", "referral_by",
                        "created_by", "created_at", "updated_at"}
        # Phase 2's create_candidate inserts a matching candidate_requisitions
        # row as the candidate's first application (see
        # test_recruitment_applications.py for the full behavioral coverage) —
        # just a sanity check here that the fixture's own candidate got one.
        cand_id = two_requisitions_and_a_candidate["candidate"]["id"]
        auto_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM candidate_requisitions WHERE candidate_id=?", (cand_id,)
        ).fetchone()["n"]
        assert auto_rows == 1, "create_candidate should insert exactly one candidate_requisitions row"
    finally:
        conn.close()


def test_same_candidate_can_have_two_different_requisitions(two_requisitions_and_a_candidate):
    """The actual feature: this is what today's create_candidate cannot do
    (one candidates row, one requisition_id) but the new join table can.
    create_candidate (Phase 2) already inserted the req1 application as
    part of the fixture; this only adds the second."""
    data = two_requisitions_and_a_candidate
    cand_id = data["candidate"]["id"]
    req1, req2 = data["requisitions"][0]["id"], data["requisitions"][1]["id"]
    conn = get_admin_db()
    try:
        conn.execute(
            "INSERT INTO candidate_requisitions (institution_id,candidate_id,requisition_id,created_by) VALUES (?,?,?,?)",
            (data["institution_id"], cand_id, req2, "zz_pytest")
        )
        conn.commit()
        rows = conn.execute(
            "SELECT requisition_id FROM candidate_requisitions WHERE candidate_id=? ORDER BY requisition_id", (cand_id,)
        ).fetchall()
        assert {r["requisition_id"] for r in rows} == {req1, req2}
    finally:
        _cleanup(conn, cand_id)
        conn.close()


def test_cannot_apply_the_same_candidate_to_the_same_requisition_twice(two_requisitions_and_a_candidate):
    """create_candidate (Phase 2) already inserted the (cand_id, req_id)
    application as part of the fixture — this just proves a second one
    for the exact same pair is rejected."""
    data = two_requisitions_and_a_candidate
    cand_id, req_id = data["candidate"]["id"], data["requisitions"][0]["id"]
    conn = get_admin_db()
    try:
        with pytest.raises(psycopg2.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO candidate_requisitions (institution_id,candidate_id,requisition_id,created_by) VALUES (?,?,?,?)",
                (data["institution_id"], cand_id, req_id, "zz_pytest")
            )
            conn.commit()
    finally:
        conn._raw.rollback()
        _cleanup(conn, cand_id)
        conn.close()


def test_only_one_general_interest_application_per_candidate(two_requisitions_and_a_candidate):
    """requisition_id IS NULL ("general interest, not tied to a specific
    opening") — plain SQL UNIQUE treats every NULL as distinct, so this
    needs (and gets, via the migration's partial index) its own
    enforcement: at most one such row per candidate."""
    data = two_requisitions_and_a_candidate
    cand_id = data["candidate"]["id"]
    conn = get_admin_db()
    try:
        conn.execute(
            "INSERT INTO candidate_requisitions (institution_id,candidate_id,requisition_id,created_by) VALUES (?,?,NULL,?)",
            (data["institution_id"], cand_id, "zz_pytest")
        )
        conn.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO candidate_requisitions (institution_id,candidate_id,requisition_id,created_by) VALUES (?,?,NULL,?)",
                (data["institution_id"], cand_id, "zz_pytest")
            )
            conn.commit()
    finally:
        conn._raw.rollback()
        _cleanup(conn, cand_id)
        conn.close()


def test_updated_at_trigger_is_wired_up():
    """Checks the trigger is actually attached and points at set_updated_at
    — not by comparing before/after timestamps, since that function only
    has 1-second resolution (to_char(..., 'YYYY-MM-DD HH24:MI:SS')) and an
    INSERT immediately followed by an UPDATE routinely lands in the same
    second on a fast local DB, which made an earlier version of this test
    flaky rather than actually broken. set_updated_at() itself is already
    exercised by every other trg_*_upd trigger in this schema."""
    conn = get_admin_db()
    try:
        trg = conn.execute("""
            SELECT t.tgname, p.proname AS calls
            FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE t.tgrelid = 'candidate_requisitions'::regclass AND NOT t.tgisinternal
        """).fetchone()
        assert trg is not None, "candidate_requisitions has no UPDATE trigger"
        assert trg["calls"] == "set_updated_at"
    finally:
        conn.close()


def test_rls_isolates_candidate_requisitions_by_institution(two_requisitions_and_a_candidate, superadmin_headers, client):
    """Same proof shape as test_rls_enforcement.py: scope a connection to
    one institution with no WHERE filter at all, confirm another
    institution's row is invisible regardless. Reuses the (cand_id, req_id)
    application create_candidate (Phase 2) already inserted as part of the
    fixture, rather than inserting a duplicate."""
    data = two_requisitions_and_a_candidate
    inst_a_id, cand_id, req_id = data["institution_id"], data["candidate"]["id"], data["requisitions"][0]["id"]

    payload = {
        "name": "ZZ CandReq RLS Institution", "code": f"ZZCR{os.urandom(4).hex()}".upper(),
        "contact_email": "zzcandreqrls@example.com",
        "admin_username": f"zzcandreqrls_admin_{os.urandom(4).hex()}",
        "admin_full_name": "ZZ CandReq RLS Admin", "admin_password": "ZzPytest@123",
    }
    create = client.post("/api/institutions", headers=superadmin_headers, json=payload)
    assert create.status_code == 201, create.text
    inst_b_id = create.json()["id"]

    admin_conn = get_admin_db()
    try:
        try:
            set_rls_context(inst_b_id, bypass_rls=False)
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT id FROM candidate_requisitions WHERE candidate_id=?", (cand_id,)
                ).fetchall()
                assert rows == [], "RLS scoped to a different institution still saw this row"
            finally:
                conn.close()

            set_rls_context(inst_a_id, bypass_rls=False)
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT id FROM candidate_requisitions WHERE candidate_id=?", (cand_id,)
                ).fetchall()
                assert len(rows) == 1, "sanity check: own institution's row must still be visible"
            finally:
                conn.close()
        finally:
            set_rls_context(None, bypass_rls=True)
    finally:
        _cleanup(admin_conn, cand_id)
        admin_conn.close()
