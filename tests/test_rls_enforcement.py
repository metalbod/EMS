"""Verifies Postgres itself enforces tenant isolation via RLS (see
migrations/versions/eb95a484c74a_add_rls_tenant_isolation_policies.py),
independent of any application-level `WHERE institution_id=?` filter.

This is deliberately NOT an HTTP/endpoint-level test: it calls db.py's
set_rls_context() + get_db() directly to simulate a query that "forgot" its
own institution scoping, and confirms Postgres's FORCE ROW LEVEL SECURITY
policy blocks it anyway — proving the defense-in-depth actually works
rather than just existing on paper.
"""
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from db import get_db, set_rls_context


def _unique_code():
    return f"ZZTRLS{os.urandom(4).hex()}".upper()


def test_rls_blocks_cross_institution_row_even_without_a_where_filter(
    client, superadmin_headers, test_institution, make_test_employee
):
    """The real-world failure mode this defends against: an endpoint's own
    query forgets `WHERE institution_id=?` and would otherwise leak another
    institution's row. Here we deliberately query WITHOUT any institution
    filter — matching that mistake exactly — and confirm Postgres's RLS
    policy hides the other institution's row regardless."""
    emp_a = make_test_employee()
    inst_a_id = test_institution["id"]

    # A second, throwaway institution to play the role of "someone else's tenant".
    payload = {
        "name": "ZZ RLS Test Institution",
        "code": _unique_code(),
        "contact_email": "zzrls@example.com",
        "admin_username": f"zzrls_admin_{os.urandom(4).hex()}",
        "admin_full_name": "ZZ RLS Admin",
        "admin_password": "ZzPytest@123",
    }
    create = client.post("/api/institutions", headers=superadmin_headers, json=payload)
    assert create.status_code == 201, create.text
    inst_b_id = create.json()["id"]

    try:
        # Scope this "request" to institution A only (bypass_rls=False), the
        # same as any regular institution-scoped user's request.
        set_rls_context(inst_a_id, bypass_rls=False)
        conn = get_db()
        try:
            # Deliberately no WHERE institution_id filter at all — exactly
            # the bug this policy defends against.
            rows = conn.execute(
                "SELECT employee_id, institution_id FROM employees WHERE employee_id=?",
                (emp_a["employee_id"],)
            ).fetchall()
            assert len(rows) == 1, "sanity check: own institution's row must still be visible"
            assert rows[0]["institution_id"] == inst_a_id

            # Institution B has no employees, but prove the isolation with a
            # broad, unfiltered query too: scoped to A, a query for ALL
            # employees must never include any row tagged with B's id.
            all_visible = conn.execute("SELECT institution_id FROM employees").fetchall()
            assert all(r["institution_id"] == inst_a_id for r in all_visible), (
                "RLS scoped to institution A leaked a row from a different institution"
            )
        finally:
            conn.close()

        # Now scope to institution B: A's employee must NOT be visible, even
        # via an unfiltered query, proving this isn't one-directional luck.
        set_rls_context(inst_b_id, bypass_rls=False)
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT employee_id FROM employees WHERE employee_id=?",
                (emp_a["employee_id"],)
            ).fetchall()
            assert rows == [], "RLS scoped to institution B still saw institution A's employee"
        finally:
            conn.close()

        # bypass_rls=True (the superadmin/global-view case) must still see everything.
        set_rls_context(None, bypass_rls=True)
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT employee_id FROM employees WHERE employee_id=?",
                (emp_a["employee_id"],)
            ).fetchall()
            assert len(rows) == 1, "bypass_rls=True must still see all institutions' rows"
        finally:
            conn.close()
    finally:
        # Restore an unscoped/bypass context so this test doesn't leak a
        # narrowed RLS context into whatever pytest runs next in this
        # process/thread.
        set_rls_context(None, bypass_rls=True)


def test_rls_context_bypass_sees_all_institutions(client, make_test_employee):
    """Code paths that call set_rls_context(None, bypass_rls=True) — the
    same state db.py's contextvar defaults to when never set at all, e.g.
    init_db(), login before authentication, or a plain get_db() call in a
    test fixture — must keep working exactly as before: unrestricted
    access, not a silent lockout. Explicitly reset here (rather than
    relying on the contextvar's untouched default) because contextvars
    persist across plain synchronous pytest calls in the same thread, and
    make_test_employee's own authenticated HTTP request would otherwise
    have already left a real, narrowed context behind from a prior request
    in this same test process."""
    set_rls_context(None, bypass_rls=True)
    emp = make_test_employee()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT employee_id FROM employees WHERE employee_id=?",
            (emp["employee_id"],)
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()
