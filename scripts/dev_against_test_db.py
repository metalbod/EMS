"""One-off dev-server launcher for browser-testing against the local test
Postgres instead of prod. Not part of the app itself — the default
.claude/launch.json config runs `main:app` directly against .env's plain
DATABASE_URL/ADMIN_DATABASE_URL (prod Supabase), which is fine for real
deploys but wrong for poking at an in-progress feature through the browser.

Mirrors the explicit env-swap safety pattern from CLAUDE.md's local
Postgres section: never rely on shell-exported state, swap inside the
process itself right after load_dotenv() and before importing db/main, and
assert the resolved host before anything can touch it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ADMIN_DATABASE_URL"] = os.environ["TEST_ADMIN_DATABASE_URL"]
assert "localhost:5433" in os.environ["DATABASE_URL"], "refusing to start: DATABASE_URL is not the local test DB"
assert "localhost:5433" in os.environ["ADMIN_DATABASE_URL"], "refusing to start: ADMIN_DATABASE_URL is not the local test DB"
print(f"Starting dev server against TEST DB: {os.environ['DATABASE_URL'].split('@')[-1]}", file=sys.stderr)

import uvicorn
uvicorn.run("main:app", host="0.0.0.0", port=8010)
