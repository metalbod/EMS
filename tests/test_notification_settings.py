"""Integration tests for Phase 1 of the email notification engine:
per-institution BYO-SMTP settings and the send/test/log endpoints (see
core/email_engine.py, routers/notifications.py's email-settings section,
and migrations/versions/20260919_0001_email_notifications.py).

Every test here mocks smtplib so no real network connection is ever
attempted — see conftest.py's clean_email_settings/configured_email_settings
fixtures for why the shared test_institution's SMTP config is always
restored to a clean (disabled) state afterward.
"""
from unittest.mock import patch

import pytest

FAKE_SMTP_BODY = {
    "smtp_host": "smtp.zzpytest.example.com",
    "smtp_port": 587,
    "smtp_use_tls": True,
    "smtp_from_address": "hr@zzpytest.example.com",
    "smtp_from_name": "ZZ Pytest HR",
    "smtp_username": "zzuser",
    "smtp_password": "zzpass",
    "notifications_email_enabled": True,
}


def test_email_settings_requires_hr_manager_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="hr_admin")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/email-settings", headers=headers)
    assert res.status_code == 403


def test_put_email_settings_validates_smtp_connection_first(client, hr_manager_auth, clean_email_settings):
    with patch("routers.notifications.verify_smtp_connection", side_effect=Exception("connection refused")):
        res = client.put("/api/notifications/email-settings", headers=hr_manager_auth, json=FAKE_SMTP_BODY)
    assert res.status_code == 400

    still_unconfigured = client.get("/api/notifications/email-settings", headers=hr_manager_auth).json()
    assert still_unconfigured["configured"] is False


def test_put_email_settings_success(client, hr_manager_auth, clean_email_settings):
    with patch("routers.notifications.verify_smtp_connection"):
        res = client.put("/api/notifications/email-settings", headers=hr_manager_auth, json=FAKE_SMTP_BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["configured"] is True
    assert body["notifications_email_enabled"] is True
    assert body["smtp_from_address"] == FAKE_SMTP_BODY["smtp_from_address"]
    assert "smtp_username" not in body
    assert "smtp_password" not in body

    fetched = client.get("/api/notifications/email-settings", headers=hr_manager_auth).json()
    assert fetched["configured"] is True
    assert fetched["smtp_host"] == FAKE_SMTP_BODY["smtp_host"]


def test_put_email_settings_invalid_from_address_returns_422(client, hr_manager_auth, clean_email_settings):
    bad = dict(FAKE_SMTP_BODY, smtp_from_address="not-an-email")
    res = client.put("/api/notifications/email-settings", headers=hr_manager_auth, json=bad)
    assert res.status_code == 422


def test_put_email_settings_missing_username_returns_422(client, hr_manager_auth, clean_email_settings):
    bad = dict(FAKE_SMTP_BODY, smtp_username="   ")
    res = client.put("/api/notifications/email-settings", headers=hr_manager_auth, json=bad)
    assert res.status_code == 422


def test_delete_email_settings_clears_config(client, hr_manager_auth, configured_email_settings):
    res = client.delete("/api/notifications/email-settings", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json()["configured"] is False
    assert client.get("/api/notifications/email-settings", headers=hr_manager_auth).json()["configured"] is False


def test_send_test_email_requires_enabled_and_configured(client, hr_manager_auth, clean_email_settings):
    res = client.post("/api/notifications/email-settings/test", headers=hr_manager_auth,
                       json={"to_email": "someone@zzpytest.example.com"})
    assert res.status_code == 400


def test_send_test_email_invalid_to_address_returns_422(client, hr_manager_auth, clean_email_settings):
    res = client.post("/api/notifications/email-settings/test", headers=hr_manager_auth,
                       json={"to_email": "not-an-email"})
    assert res.status_code == 422


def test_send_test_email_success_and_logged(client, hr_manager_auth, configured_email_settings):
    with patch("core.email_engine.smtplib.SMTP") as mock_smtp:
        res = client.post("/api/notifications/email-settings/test", headers=hr_manager_auth,
                           json={"to_email": "recipient@zzpytest.example.com"})
    assert res.status_code == 200, res.text
    assert res.json()["sent"] is True
    server = mock_smtp.return_value.__enter__.return_value
    server.login.assert_called_once()
    server.sendmail.assert_called_once()

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == "recipient@zzpytest.example.com" and r["category"] == "test")
    assert row["status"] == "sent"


def test_send_test_email_failure_is_logged(client, hr_manager_auth, configured_email_settings):
    with patch("core.email_engine.smtplib.SMTP", side_effect=Exception("connection refused")):
        res = client.post("/api/notifications/email-settings/test", headers=hr_manager_auth,
                           json={"to_email": "recipient2@zzpytest.example.com"})
    assert res.status_code == 400

    log = client.get("/api/notifications/email-log", headers=hr_manager_auth).json()
    row = next(r for r in log if r["recipient_email"] == "recipient2@zzpytest.example.com" and r["category"] == "test")
    assert row["status"] == "failed"
    assert row["error"]


def test_email_log_requires_hr_manager_role(client, make_test_user, test_institution):
    token, _ = make_test_user(role="hr_admin")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    res = client.get("/api/notifications/email-log", headers=headers)
    assert res.status_code == 403
