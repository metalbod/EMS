#!/usr/bin/env bash
# Deploy EMS to Fly.io. Runs pending Alembic migrations against the shared
# DB first (see migrations/env.py — uses ADMIN_DATABASE_URL from .env) so a
# migration never ships silently un-applied, then `fly deploy`. Run from the
# repo root: ./deploy.sh
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

echo "==> Deploying to Fly.io..."
app_version="$(git rev-parse --short HEAD)"
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

# The "reminders" process group (scripts/send_reminders.py, Phase 2 of the
# email notification engine) runs on a Fly-native schedule, which is a
# per-machine property set via `fly machine update --schedule` — NOT
# something fly.toml can express, and `fly deploy` can silently drop it
# from an existing machine on redeploy (a known Fly quirk). Re-asserting
# it here, every deploy, means it's never left unscheduled without
# anyone noticing. Provisioning the process group/machine itself (adding
# it to fly.toml, `fly scale count reminders=1`) is a one-time manual
# step, not done by this script — if that hasn't happened yet, this
# block finds nothing and says so, without failing the deploy.
echo "==> Re-applying schedule to the 'reminders' process (if provisioned)..."
reminder_machine_ids=$(fly machine list --app ems-app --json 2>/dev/null | jq -r '.[] | select(.config.metadata.fly_process_group=="reminders") | .id') || true
if [ -z "$reminder_machine_ids" ]; then
  echo "    No 'reminders' process group machine found — skipping (not provisioned yet, or fly.toml has no such process group)."
else
  while IFS= read -r mid; do
    [ -z "$mid" ] && continue
    echo "    Setting schedule=daily on machine $mid..."
    if ! fly machine update "$mid" --schedule=daily --app ems-app --yes; then
      echo "    WARNING: failed to (re)set schedule=daily on reminders machine $mid — verify manually: fly machine status $mid --app ems-app" >&2
    fi
  done <<< "$reminder_machine_ids"
fi
