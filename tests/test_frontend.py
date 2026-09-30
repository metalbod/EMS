"""Tests for the SPA index.html serving + automatic cache-busting."""
import json
import re


def test_root_serves_html_with_cache_bust_version(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    versions = set(re.findall(r'\?v=([a-z0-9]+)"', res.text))
    assert versions, "expected at least one ?v=<hash> asset reference"
    assert len(versions) == 1, f"expected a single consistent version, got {versions}"


def test_version_is_stable_across_requests_without_file_changes(client):
    first = client.get("/").text
    second = client.get("/").text
    assert first == second


def test_spa_fallback_serves_index_for_unknown_client_routes(client):
    res = client.get("/some/deep/client/side/route")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_api_routes_are_not_swallowed_by_spa_fallback(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_login_screen_shows_a_resolved_app_version(client):
    """The {{APP_VERSION}} placeholder must always be substituted — never
    leak the literal placeholder text to a real user's login screen."""
    res = client.get("/")
    assert "{{APP_VERSION}}" not in res.text
    assert "Version " in res.text


# ---------------------------------------------------------------------------
# GET /api/changelog — backs the in-app About panel (user menu -> About).
# routers/frontend.py's _changelog() caches its result for the process's
# whole lifetime (same reasoning as _app_version/_static_asset_version), so
# every test here resets that cache via monkeypatch (auto-reverted after
# the test) rather than trusting whatever's really on disk — CHANGELOG.json
# only exists at all when deploy.sh's scripts/generate_changelog.py wrote
# one, never during a real pytest run.
# ---------------------------------------------------------------------------
def test_changelog_requires_auth(client):
    res = client.get("/api/changelog")
    assert res.status_code == 401


def test_changelog_reads_the_baked_file_when_present(client, hr_manager_auth, monkeypatch, tmp_path):
    """Any authenticated role can read it — same info the repo's own public
    GitHub Tags/Releases page already shows, nothing sensitive."""
    import routers.frontend as frontend
    fake_file = tmp_path / "CHANGELOG.json"
    fake_file.write_text(json.dumps([
        {"version": "0.2", "date": "2026-10-02", "commits": [{"sha": "abc1234", "summary": "ZZ Second thing"}]},
        {"version": "0.1", "date": "2026-10-01", "commits": [{"sha": "def5678", "summary": "ZZ First thing"}]},
    ]))
    monkeypatch.setattr(frontend, "CHANGELOG_FILE", str(fake_file))
    monkeypatch.setitem(frontend._changelog_cache, "value", None)

    res = client.get("/api/changelog", headers=hr_manager_auth)
    assert res.status_code == 200
    body = res.json()
    assert [e["version"] for e in body] == ["0.2", "0.1"], "must stay newest-first, exactly as the file has it"
    assert body[0]["commits"] == [{"sha": "abc1234", "summary": "ZZ Second thing"}]


def test_changelog_falls_back_to_live_git_when_no_baked_file(client, hr_manager_auth, monkeypatch, tmp_path):
    """Local dev has no CHANGELOG.json (only deploy.sh ever writes one) but
    does have .git, unlike the deployed container — falls back to computing
    the same shape live via core.changelog.compute_changelog."""
    import routers.frontend as frontend
    monkeypatch.setattr(frontend, "CHANGELOG_FILE", str(tmp_path / "does-not-exist.json"))
    monkeypatch.setitem(frontend._changelog_cache, "value", None)
    monkeypatch.setattr(frontend, "compute_changelog", lambda: [
        {"version": "0.9", "date": "2026-10-03", "commits": [{"sha": "1234abc", "summary": "ZZ Local commit"}]},
    ])

    res = client.get("/api/changelog", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == [{"version": "0.9", "date": "2026-10-03", "commits": [{"sha": "1234abc", "summary": "ZZ Local commit"}]}]


def test_changelog_tolerates_git_itself_failing(client, hr_manager_auth, monkeypatch, tmp_path):
    """No CHANGELOG.json and git unavailable/erroring (e.g. not a repo) must
    never break the About panel — falls back to an empty list."""
    import routers.frontend as frontend
    monkeypatch.setattr(frontend, "CHANGELOG_FILE", str(tmp_path / "does-not-exist.json"))
    monkeypatch.setitem(frontend._changelog_cache, "value", None)

    def _boom():
        raise RuntimeError("git not installed")
    monkeypatch.setattr(frontend, "compute_changelog", _boom)

    res = client.get("/api/changelog", headers=hr_manager_auth)
    assert res.status_code == 200
    assert res.json() == []
