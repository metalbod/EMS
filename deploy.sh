#!/usr/bin/env bash
# Deploy EMS to Fly.io. Runs pending Alembic migrations against the shared
# DB first (see migrations/env.py — uses ADMIN_DATABASE_URL from .env) so a
# migration never ships silently un-applied, then `fly deploy`. Run from the
# repo root: ./deploy.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "==> Running pending migrations (alembic upgrade head)..."
.venv/bin/python3 -m alembic upgrade head

echo "==> Deploying to Fly.io..."
fly deploy --app ems-app

echo "==> Verifying..."
code=$(curl -s -o /dev/null -w "%{http_code}" https://ems-app.fly.dev/)
if [ "$code" != "200" ]; then
  echo "WARNING: https://ems-app.fly.dev/ returned $code, expected 200" >&2
  exit 1
fi
echo "==> Deploy verified: 200 OK"
