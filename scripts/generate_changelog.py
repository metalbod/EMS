#!/usr/bin/env python3
"""Writes CHANGELOG.json at the repo root from git tag/commit history — run
by deploy.sh right after it computes the pending deploy's version number,
before `fly deploy` builds the image (so the file is present in the build
context and gets baked in via the Dockerfile's COPY . .). See
core/changelog.py for the actual logic (shared with routers/frontend.py's
local-dev fallback) and CHANGELOG.json's own role (gitignored — regenerated
fresh on every deploy, not source-controlled, same as APP_VERSION itself).

Usage: generate_changelog.py <pending-app-version>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.changelog import compute_changelog


def main():
    if len(sys.argv) != 2:
        print("usage: generate_changelog.py <pending-app-version>", file=sys.stderr)
        sys.exit(1)

    changelog = compute_changelog(pending_version=sys.argv[1])
    with open("CHANGELOG.json", "w") as f:
        json.dump(changelog, f, indent=2)
        f.write("\n")
    total_commits = sum(len(e["commits"]) for e in changelog)
    print(f"==> CHANGELOG.json: {len(changelog)} version(s), {total_commits} commit(s)")


if __name__ == "__main__":
    main()
