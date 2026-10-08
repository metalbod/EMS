"""Deferred (background) approval emails — core/email_engine.py's queue_email,
db.py's Conn.after_commit. The rules: an email is handed to
the sender only after the change that triggered it has COMMITTED, goes out over
one SMTP session per batch, and a failure never reaches the caller."""
import os
from unittest.mock import MagicMock, patch

import pytest

import core.email_engine as ee
import db
from db import get_db, get_admin_db

SMTP_SETTINGS = {"host": "smtp.zz.example.com", "port": 587, "use_tls": True,
                 "from_address": "hr@zz.example.com", "from_name": "ZZ", "username": "u", "password": "p"}


@pytest.fixture
def smtp_ready(monkeypatch):
    """Pretend the institution has working SMTP settings and capture the SMTP
    client; returns the mock class (calls == sessions opened)."""
    monkeypatch.setattr(ee, "_smtp_settings", lambda conn, inst_id: SMTP_SETTINGS)
    with patch("core.email_engine.smtplib.SMTP") as smtp:
        yield smtp


@pytest.fixture
def conn_and_cleanup(test_institution):
    conn = get_db()
    yield conn, test_institution["id"]
    conn.close()
    admin = get_admin_db()
    admin.execute("DELETE FROM email_log WHERE recipient_email LIKE ?", ("zzasync-%",))
    admin.commit()
    admin.close()


def _log_rows(prefix_tag):
    admin = get_admin_db()
    try:
        return [dict(r) for r in admin.execute(
            "SELECT recipient_email,status,error FROM email_log WHERE recipient_email LIKE ? ORDER BY id",
            (f"zzasync-{prefix_tag}-%",)).fetchall()]
    finally:
        admin.close()


def _server(smtp):
    return smtp.return_value.__enter__.return_value


def test_nothing_is_sent_until_the_transaction_commits(conn_and_cleanup, smtp_ready):
    conn, inst = conn_and_cleanup
    ee.queue_email(conn, inst, "zzasync-a-1@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    smtp_ready.assert_not_called()
    conn.commit()
    smtp_ready.assert_called_once()
    _server(smtp_ready).sendmail.assert_called_once()
    assert [r["status"] for r in _log_rows("a")] == ["sent"]


def test_rollback_or_close_discards_queued_emails(test_institution, smtp_ready):
    inst = test_institution["id"]
    conn = get_db()
    ee.queue_email(conn, inst, "zzasync-b-1@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn.rollback()
    conn.commit()
    conn.close()
    conn2 = get_db()
    ee.queue_email(conn2, inst, "zzasync-b-2@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn2.close()  # closed without ever committing
    smtp_ready.assert_not_called()
    assert _log_rows("b") == []


def test_a_batch_uses_one_smtp_session(conn_and_cleanup, smtp_ready):
    conn, inst = conn_and_cleanup
    for n in range(3):
        ee.queue_email(conn, inst, f"zzasync-c-{n}@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn.commit()
    assert smtp_ready.call_count == 1                      # one connection, not three
    server = _server(smtp_ready)
    assert server.login.call_count == 1 and server.sendmail.call_count == 3
    assert [r["status"] for r in _log_rows("c")] == ["sent"] * 3


def test_one_failed_message_does_not_stop_the_rest(conn_and_cleanup, smtp_ready):
    conn, inst = conn_and_cleanup
    _server(smtp_ready).sendmail.side_effect = [None, Exception("mailbox full"), None]
    for n in range(3):
        ee.queue_email(conn, inst, f"zzasync-d-{n}@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn.commit()
    rows = _log_rows("d")
    assert [r["status"] for r in rows] == ["sent", "failed", "sent"]
    assert "mailbox full" in rows[1]["error"]


def test_login_failure_logs_every_message_failed_and_never_raises(conn_and_cleanup, smtp_ready):
    conn, inst = conn_and_cleanup
    _server(smtp_ready).login.side_effect = Exception("bad credentials")
    for n in range(2):
        ee.queue_email(conn, inst, f"zzasync-e-{n}@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn.commit()                                          # must not raise
    rows = _log_rows("e")
    assert [r["status"] for r in rows] == ["failed", "failed"] and "bad credentials" in rows[0]["error"]


def test_unconfigured_institution_logs_skipped(conn_and_cleanup, monkeypatch):
    conn, inst = conn_and_cleanup
    monkeypatch.setattr(ee, "_smtp_settings", lambda c, i: None)
    ee.queue_email(conn, inst, "zzasync-f-1@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn.commit()
    assert [r["status"] for r in _log_rows("f")] == ["skipped"]


def test_background_mode_hands_the_batch_to_the_pool_without_sending_in_the_request(
        conn_and_cleanup, smtp_ready, monkeypatch):
    monkeypatch.delenv("EMAIL_DISPATCH", raising=False)
    jobs = []
    monkeypatch.setattr(ee, "_executor", MagicMock(submit=lambda fn, *a: jobs.append((fn, a))))
    conn, inst = conn_and_cleanup
    ee.queue_email(conn, inst, "zzasync-g-1@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    ee.queue_email(conn, inst, "zzasync-g-2@example.com", "Hi", "<p>x</p>", "approval_decided", "leave")
    conn.commit()
    assert len(jobs) == 1                                  # one batch per institution
    smtp_ready.assert_not_called()                         # the request did no mail work
    assert _log_rows("g") == []
    fn, args = jobs[0]
    fn(*args)                                              # what the pool thread would do
    assert smtp_ready.call_count == 1
    assert [r["status"] for r in _log_rows("g")] == ["sent", "sent"]


def test_sender_does_not_change_the_requests_rls_context(conn_and_cleanup, smtp_ready):
    conn, inst = conn_and_cleanup
    db.set_rls_context(None, True)
    before = db._rls_context.get()
    ee.queue_email(conn, inst, "zzasync-h-1@example.com", "Hi", "<p>x</p>", "approval_needed", "leave")
    conn.commit()                                          # inline mode: runs in this thread
    assert db._rls_context.get() == before


def test_filing_a_resignation_returns_before_any_email_is_sent(
        client, hr_manager_auth, make_test_employee, configured_email_settings, monkeypatch):
    monkeypatch.delenv("EMAIL_DISPATCH", raising=False)
    jobs = []
    monkeypatch.setattr(ee, "_executor", MagicMock(submit=lambda fn, *a: jobs.append((fn, a))))
    tag = os.urandom(3).hex()
    mgr = make_test_employee(full_name="ZZ Async Manager", personal_email=f"zzasync-i-{tag}-mgr@example.com")
    emp = make_test_employee(full_name="ZZ Async Report", reports_to=mgr["employee_id"],
                             personal_email=f"zzasync-i-{tag}-emp@example.com")
    with patch("core.email_engine.smtplib.SMTP") as smtp:
        res = client.post("/api/resignations", headers=hr_manager_auth, json={
            "employee_id": emp["employee_id"], "reason": "async test",
            "effective_date": "2027-06-01", "last_working_day": "2027-06-30"})
        assert res.status_code == 201, res.text
        smtp.assert_not_called()                           # nothing sent during the request
        assert len(jobs) == 1                              # ...but the notification is queued
        fn, args = jobs[0]
        fn(*args)
        assert smtp.call_count == 1
    rows = _log_rows(f"i-{tag}")
    assert any(r["recipient_email"].endswith("-mgr@example.com") and r["status"] == "sent" for r in rows)
    client.patch(f"/api/resignations/{res.json()['id']}", headers=hr_manager_auth, json={"status": "Rejected"})
    admin = get_admin_db()
    admin.execute("DELETE FROM email_log WHERE recipient_email LIKE ?", ("zzasync-%",))
    admin.commit()
    admin.close()
