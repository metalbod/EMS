"""
Shared pytest fixtures.

These tests import the real `main.app` and, for the auth tests, hit the real
database configured via .env (DATABASE_URL) — there is no local test DB yet
(see tech-debt notes). Keep DB-touching tests strictly read-only or scoped to
disposable, clearly-prefixed data with guaranteed teardown; never assume it's
safe to mutate arbitrary rows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import main as app_module


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """The login rate limiter is process-local in-memory state (see main.py).
    Clear it before and after every test so one test's failed-login attempts
    can't trip the 429 lockout in an unrelated test."""
    app_module._login_failures.clear()
    yield
    app_module._login_failures.clear()
