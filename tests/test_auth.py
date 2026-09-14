"""
Integration tests for authentication — hits the real app (and real DB via
.env) but stays strictly read-only with respect to real application data:
no test ever creates, mutates, or deletes a row outside of the disposable
zz-prefixed users make_test_user creates and tears down itself. Uses a
nonexistent username so failed-login tests can't collide with real
accounts.
"""
from core.deps import hash_password, verify_password, verify_password_or_dummy

NONEXISTENT_USER = "zz_pytest_nonexistent_user"


def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_login_missing_fields_returns_422(client):
    res = client.post("/api/auth/login", json={"username": "x"})
    assert res.status_code == 422


def test_login_wrong_password_returns_401(client):
    res = client.post("/api/auth/login", json={
        "username": NONEXISTENT_USER, "password": "wrong", "institution_code": None,
    })
    assert res.status_code == 401
    assert "Invalid" in res.json()["detail"]


def test_login_unknown_institution_code_returns_401(client):
    res = client.post("/api/auth/login", json={
        "username": NONEXISTENT_USER, "password": "wrong", "institution_code": "ZZ_NO_SUCH_CODE",
    })
    assert res.status_code == 401


def test_protected_endpoint_without_token_returns_401_or_403(client):
    res = client.get("/api/auth/me")
    assert res.status_code in (401, 403)


def test_protected_endpoint_with_garbage_token_returns_401(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


class TestLoginRateLimit:
    def test_locks_out_after_max_attempts(self, client):
        from routers.auth import LOGIN_MAX_ATTEMPTS

        for _ in range(LOGIN_MAX_ATTEMPTS):
            res = client.post("/api/auth/login", json={
                "username": NONEXISTENT_USER, "password": "wrong", "institution_code": None,
            })
            assert res.status_code == 401

        locked = client.post("/api/auth/login", json={
            "username": NONEXISTENT_USER, "password": "wrong", "institution_code": None,
        })
        assert locked.status_code == 429
        assert "Too many failed login attempts" in locked.json()["detail"]

    def test_rate_limit_is_scoped_per_username_not_global(self, client):
        from routers.auth import LOGIN_MAX_ATTEMPTS

        for _ in range(LOGIN_MAX_ATTEMPTS):
            client.post("/api/auth/login", json={
                "username": NONEXISTENT_USER, "password": "wrong", "institution_code": None,
            })

        # A different username from the same client should not be locked out.
        res = client.post("/api/auth/login", json={
            "username": NONEXISTENT_USER + "_other", "password": "wrong", "institution_code": None,
        })
        assert res.status_code == 401  # not 429


class TestVerifyPasswordOrDummy:
    """See core/deps.py's verify_password_or_dummy docstring — login() calls
    this unconditionally (real hash or None) so a nonexistent username and a
    wrong password on a real one cost the same bcrypt comparison, closing
    the timing side-channel that used to distinguish them."""

    def test_none_hash_still_runs_a_real_comparison_and_returns_false(self):
        assert verify_password_or_dummy("anything", None) is False

    def test_real_hash_behaves_exactly_like_verify_password(self):
        h = hash_password("ZzPytest@123")
        assert verify_password_or_dummy("ZzPytest@123", h) == verify_password("ZzPytest@123", h) is True
        assert verify_password_or_dummy("wrong", h) == verify_password("wrong", h) is False


class TestTokenEpochRevocation:
    def test_token_issued_before_password_change_is_rejected_after(self, client, make_test_user):
        old_token, _ = make_test_user(role="employee")
        old_headers = {"Authorization": f"Bearer {old_token}"}
        assert client.get("/api/auth/me", headers=old_headers).status_code == 200

        change_res = client.post("/api/auth/change-password", headers=old_headers, json={
            "current_password": "ZzPytest@123", "new_password": "ZzNewPassword@456",
        })
        assert change_res.status_code == 200, change_res.text

        # The old token's signature/expiry are still valid, but its
        # token_epoch is now stale — it must be rejected, not honored.
        assert client.get("/api/auth/me", headers=old_headers).status_code == 401

        # The fresh token the response minted keeps the caller's own
        # session working instead of logging them out of their own request.
        new_headers = {"Authorization": f"Bearer {change_res.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=new_headers).status_code == 200
