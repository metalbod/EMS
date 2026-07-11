"""
Integration tests for authentication — hits the real app (and real DB via
.env) but stays strictly read-only: no test ever creates, mutates, or
deletes a row. Uses a nonexistent username so failed-login tests can't
collide with real accounts.
"""
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
