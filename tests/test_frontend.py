"""Tests for the SPA index.html serving + automatic cache-busting."""
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
