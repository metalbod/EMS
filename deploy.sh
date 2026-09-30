#!/usr/bin/env bash
# Deploy EMS to Fly.io. Runs pending Alembic migrations against the shared
# DB first (see migrations/env.py — uses ADMIN_DATABASE_URL from .env) so a
# migration never ships silently un-applied, then `fly deploy`. Run from the
# repo root: ./deploy.sh
#
# Each successful deploy is tagged v0.1, v0.2, v0.3, ... on GitHub (annotated
# tag, pushed to origin) — the same "major.minor" is baked into the image as
# APP_VERSION and shown on the login screen (routers/frontend.py's
# _app_version), so "what's live right now" is a plain incrementing number
# you can look up directly under the repo's Tags/Releases page, no `fly
# releases` trip needed. The minor number is derived from the highest
# existing v<major>.<minor> tag on origin, so it keeps incrementing correctly
# regardless of which clone runs the deploy. The major number only ever
# changes by hand — create/push a vN.0 tag yourself (e.g. `git tag -a v1.0
# -m "..." && git push origin v1.0`) when ready to bump it; this script never
# rolls the minor over into a new major on its own. major/minor are parsed
# and incremented as plain integers (never floating-point arithmetic), so
# there's no risk of 0.1 + 0.1 drifting to something like 0.1999999999.
#
# scripts/generate_changelog.py runs right after (writing CHANGELOG.json,
# gitignored, baked into the image) so the in-app About panel (user menu ->
# About; GET /api/changelog) can show every version's commits without the
# deployed container needing .git, which it doesn't have.
#
# If the post-deploy health check fails, this automatically redeploys the
# previous release's exact image (fast — no rebuild) rather than leaving
# prod on a broken release until someone notices and rolls back by hand.
# That rollback is APP-ONLY — the migration that already ran above is not
# undone (Alembic downgrades aren't run automatically; several migrations
# in this chain aren't safely reversible — see CLAUDE.md). If the new
# migration isn't backward-compatible with the previous code, a rolled-
# back app can still misbehave against the new schema — the rollback
# messages below call this out so it isn't mistaken for a full fix.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "==> Running pending migrations (alembic upgrade head)..."
.venv/bin/python3 -m alembic upgrade head

echo "==> Capturing current live image (for rollback if this deploy's health check fails)..."
prev_image=$(fly releases --image --json -a ems-app | jq -r '[.[] | select(.Status=="complete")][0].ImageRef // empty')
if [ -z "$prev_image" ]; then
  echo "WARNING: could not determine the current live image — automatic rollback won't be available if this deploy fails its health check." >&2
fi

echo "==> Computing next deploy version number..."
git fetch origin --tags --quiet || echo "WARNING: could not fetch tags from origin — the version number below may collide with one already pushed from elsewhere." >&2
# Highest existing v<major>.<minor> tag, numeric on both fields (so v0.9
# correctly sorts before v0.10) — anything not matching that exact shape
# (an old bare "v<N>" tag, say) is ignored rather than breaking the parse.
# `|| true` on the whole pipeline: with `pipefail`, grep matching zero tags
# (the very first deploy under this scheme, or any repo with no tags yet)
# exits 1, which would otherwise silently kill the script here under `set
# -e` before `fly deploy` ever runs — an empty result is exactly the
# legitimate "no tags yet" case the `-z` check below already handles.
last_version=$( { git tag -l | grep -E '^v[0-9]+\.[0-9]+$' | sed 's/^v//' | sort -t. -k1,1n -k2,2n | tail -1; } || true)
if [ -z "$last_version" ]; then
  major=0; minor=0
else
  major="${last_version%.*}"
  minor="${last_version#*.}"
fi
app_version="$major.$((minor + 1))"

echo "==> Generating CHANGELOG.json for the About panel..."
.venv/bin/python3 scripts/generate_changelog.py "$app_version"

echo "==> Deploying to Fly.io (v$app_version)..."
fly deploy --app ems-app --build-arg "APP_VERSION=$app_version"

echo "==> Verifying..."
code=$(curl -s -o /dev/null -w "%{http_code}" https://ems-app.fly.dev/)
if [ "$code" != "200" ]; then
  echo "WARNING: https://ems-app.fly.dev/ returned $code, expected 200" >&2

  if [ -z "$prev_image" ]; then
    echo "No previous image was captured — cannot auto-rollback. Roll back manually: fly releases -a ems-app, then fly deploy -a ems-app --image <ref>." >&2
    exit 1
  fi

  echo "==> Rolling back app tier to previous image: $prev_image" >&2
  echo "    NOTE: this rolls back the APP only, not the database migration run above." >&2
  echo "    If the new migration isn't backward-compatible with the previous code," >&2
  echo "    the rolled-back app may still misbehave — check the migration, don't" >&2
  echo "    assume the rollback alone makes everything fine." >&2

  if fly deploy --app ems-app --image "$prev_image"; then
    rollback_code=$(curl -s -o /dev/null -w "%{http_code}" https://ems-app.fly.dev/)
    if [ "$rollback_code" == "200" ]; then
      echo "==> Rolled back successfully — app is serving the previous release again." >&2
    else
      echo "WARNING: rollback deploy completed but the health check still returns $rollback_code — investigate manually." >&2
    fi
  else
    echo "WARNING: the rollback deploy itself failed — investigate manually, the app may be in a broken state." >&2
  fi
  exit 1
fi
echo "==> Deploy verified: 200 OK"

echo "==> Tagging v$app_version on GitHub..."
if git tag -a "v$app_version" -m "Deploy v$app_version ($(git rev-parse --short HEAD))" && git push origin "v$app_version"; then
  # Portable slug extraction (avoids sed regex-dialect differences between
  # BSD/macOS and GNU sed) for both the SSH and HTTPS remote URL forms.
  origin_url=$(git remote get-url origin)
  repo_slug="${origin_url#git@github.com:}"
  repo_slug="${repo_slug#https://github.com/}"
  repo_slug="${repo_slug%.git}"
  echo "==> https://github.com/$repo_slug/releases/tag/v$app_version"
else
  echo "WARNING: deploy succeeded, but tagging/pushing v$app_version failed — it won't show up on GitHub. The next deploy will retry this same version number." >&2
fi
