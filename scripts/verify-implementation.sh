#!/bin/bash
# Verify CRITICAL items implementation
# Usage: ./scripts/verify-implementation.sh

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     EMS CRITICAL Items Implementation Verification         ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

passed=0
failed=0

# Function to print results
check_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((passed++))
}

check_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((failed++))
}

check_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SECTION 1: Environment Checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if .env exists
if [ -f ".env" ]; then
    check_pass ".env file exists"
else
    check_fail ".env file not found"
fi

# Check if required env vars are set
if [ -n "$DATABASE_URL" ]; then
    check_pass "DATABASE_URL is set"
else
    check_fail "DATABASE_URL not set (source .env)"
fi

if [ -n "$JWT_SECRET" ]; then
    check_pass "JWT_SECRET is set"
else
    check_fail "JWT_SECRET not set (source .env)"
fi

# Check Fly.io CLI
if command -v flyctl &> /dev/null; then
    check_pass "Fly.io CLI (flyctl) is installed"
    if flyctl auth whoami &> /dev/null; then
        check_pass "Fly.io CLI is authenticated"
    else
        check_fail "Fly.io CLI not authenticated (run: flyctl auth login)"
    fi
else
    check_fail "Fly.io CLI not installed"
fi

# Check psql
if command -v psql &> /dev/null; then
    check_pass "psql client is installed"
else
    check_warn "psql not installed (optional, for DB testing)"
fi

# Check curl
if command -v curl &> /dev/null; then
    check_pass "curl is installed"
else
    check_fail "curl not installed"
fi

# Check openssl
if command -v openssl &> /dev/null; then
    check_pass "openssl is installed"
else
    check_fail "openssl not installed"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SECTION 2: Application Health"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if app is running (local dev)
if [ -z "$APP_URL" ]; then
    APP_URL="https://yourdomain.com"
    check_warn "APP_URL not set, using default: $APP_URL (update as needed)"
fi

# Try health endpoint
if curl -s "$APP_URL/health" &> /dev/null; then
    health_response=$(curl -s "$APP_URL/health")
    if echo "$health_response" | grep -q "ok"; then
        check_pass "Health endpoint returns OK"
    else
        check_fail "Health endpoint returned: $health_response"
    fi
else
    check_warn "Could not reach health endpoint (app may not be running)"
fi

# Check Fly.io app status
if flyctl status &> /dev/null; then
    check_pass "Fly.io app is running"
else
    check_fail "Could not check Fly.io status"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SECTION 3: Documentation Files"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if documentation files exist
docs=(
    "docs/BACKUP_POLICY.md"
    "docs/SECRETS_ROTATION_POLICY.md"
    "docs/ONCALL_RUNBOOK.md"
    "docs/MONITORING_SETUP.md"
    "docs/CRITICAL_ITEMS_IMPLEMENTATION_CHECKLIST.md"
    "docs/IMPLEMENTATION_PROGRESS.md"
)

for doc in "${docs[@]}"; do
    if [ -f "$doc" ]; then
        lines=$(wc -l < "$doc")
        check_pass "$doc exists ($lines lines)"
    else
        check_fail "$doc missing"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SECTION 4: Implementation Checklist"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "IMMEDIATE Tasks:"
echo "  [ ] Backup enablement"
echo "  [ ] Rotation schedule"
echo "  [ ] Sentry alerts"
echo "  [ ] UptimeRobot setup"
echo ""

echo "THIS WEEK Tasks:"
echo "  [ ] JWT rotation test"
echo "  [ ] DB credentials test"
echo "  [ ] Backup restore test"
echo "  [ ] Print runbook"
echo "  [ ] Create rotation log"
echo ""

echo "Use docs/IMPLEMENTATION_PROGRESS.md to track completion"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

total=$((passed + failed))
if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed! ($passed/$total)${NC}"
    echo ""
    echo "You're ready to implement CRITICAL items."
    echo "Start with: docs/CRITICAL_ITEMS_IMPLEMENTATION_CHECKLIST.md"
    exit 0
else
    echo -e "${RED}⚠️  Some checks failed ($passed/$total passed, $failed failed)${NC}"
    echo ""
    echo "Please fix issues above before proceeding."
    exit 1
fi
