# CRITICAL Items Implementation - Quick Reference

**Copy & paste the commands below to implement each task.**

---

## IMMEDIATE: Task 1 - Enable Supabase Backups

**⏱️ 5 minutes - No commands needed**

Manual steps:
1. Open: https://app.supabase.com
2. Select your EMS project
3. Go to: Settings → Backups → Automated backups
4. Toggle: ON
5. Wait 24 hours for first backup

---

## IMMEDIATE: Task 2 - Schedule Rotation Reminders

**⏱️ 10 minutes - No commands needed**

Calendar setup:
```
Create 4 recurring yearly events:
- January 1  → "Q1 Secrets Rotation" (45 min block)
- April 1    → "Q2 Secrets Rotation" (45 min block)
- July 1     → "Q3 Secrets Rotation" (45 min block)
- October 1  → "Q4 Secrets Rotation" (45 min block)
```

---

## IMMEDIATE: Task 3 - Wire Sentry Alerts

**⏱️ 20 minutes - Manual steps in Sentry dashboard**

Steps:
1. Open: https://sentry.io/auth/login/
2. Project Settings → Alerts → Create Alert Rule
3. Rule 1: "High Error Rate"
   - Condition: Event count > 10 in 1 hour
   - Action: Email to kenneth@users-MacBook-Pro.local
4. Rule 2: "New Issue"
   - Condition: New issue is created
   - Action: Email to kenneth@users-MacBook-Pro.local

Test:
```bash
# Trigger test error (pick appropriate URL)
curl https://yourdomain.com/api/users/invalid

# Wait 1-2 minutes for email
```

---

## IMMEDIATE: Task 4 - Set Up UptimeRobot

**⏱️ 10 minutes - Manual steps in UptimeRobot**

Steps:
1. Sign up: https://uptimerobot.com (free tier)
2. Add Monitor:
   - Type: HTTP(s)
   - URL: https://yourdomain.com/health
   - Interval: 5 minutes
   - Alert: Email to kenneth@users-MacBook-Pro.local
3. Save and wait for first check

---

## THIS WEEK: Task 5 - Test JWT_SECRET Rotation

**⏱️ 45 minutes - Follow these commands**

### Step 1: Generate new secret
```bash
NEW_SECRET=$(openssl rand -hex 32)
echo "New JWT_SECRET: $NEW_SECRET"
echo "Save this somewhere safe!"
```

### Step 2: Update Fly.io
```bash
# Make sure you're logged in
flyctl auth login

# Verify app exists
flyctl status

# Set new secret (replace with your actual secret)
flyctl secrets set JWT_SECRET="$NEW_SECRET"

# Verify it was set
flyctl secrets list | grep JWT_SECRET
```

### Step 3: Monitor rolling restart
```bash
# Watch logs during restart
flyctl logs --tail 50

# Watch for these (good):
# - "connection successful"
# - "instance starting"
# - "health check passed"

# Watch for these (bad):
# - "invalid token"
# - "authentication failed"
# - "ERROR"
```

### Step 4: Test app health
```bash
# Wait 30 seconds for restart to complete

# Check health endpoint
curl -s https://yourdomain.com/health
# Expected: {"status": "ok"}

# Check if alive
curl -v https://yourdomain.com/health
# Expected: HTTP/1.1 200 OK
```

### Step 5: Test login with new secret
```bash
# Login to get new token (issued with new secret)
TOKEN_RESPONSE=$(curl -s -X POST https://yourdomain.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superadmin",
    "password": "Admin@123",
    "institution_code": null
  }')

# Extract token
TOKEN=$(echo $TOKEN_RESPONSE | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
echo "New token: ${TOKEN:0:20}..."

# Test authenticated request
curl -H "Authorization: Bearer $TOKEN" \
  https://yourdomain.com/api/users

# Expected: 200 OK with user list (not 401 Unauthorized)
```

### Step 6: Document results
```bash
# Edit and save:
# docs/IMPLEMENTATION_PROGRESS.md
# → Task 5 section
# - Date: [today]
# - Old secret: [first 8 chars]
# - New secret: [first 8 chars]
# - Tests: ✅ PASSED
```

---

## THIS WEEK: Task 6 - Test Database Credential Rotation

**⏱️ 30 minutes - Follow these commands**

### Step 1: Reset DB password in Supabase
```
1. Open: https://app.supabase.com
2. Settings → Database → Users
3. Click "ems_app" user (NOT "postgres")
4. Click "Edit" → "Reset password"
5. Copy the new password from popup
6. Save: NEW_DB_PASSWORD="paste_here"
```

### Step 2: Build new DATABASE_URL
```bash
# Get your connection details from Supabase
# Settings → Database → Connection pooling → Connection string
# The format is: postgresql://ems_app.PROJECT_REF:PASSWORD@POOLER_HOST:6543/postgres

# Replace PASSWORD with your new password
NEW_DB_URL="postgresql://ems_app.YOUR_PROJECT_REF:NEW_PASSWORD@YOUR_POOLER_HOST:6543/postgres"

echo "New DATABASE_URL: $NEW_DB_URL"
```

### Step 3: Update Fly.io
```bash
# Set new DATABASE_URL
flyctl secrets set DATABASE_URL="$NEW_DB_URL"

# Verify it was set
flyctl secrets list | grep DATABASE_URL
```

### Step 4: Monitor for errors
```bash
# Watch logs for connection status
flyctl logs --tail 50

# Watch for:
# ✅ "connection successful" or "pooled 10 connections"
# ❌ "invalid password", "access denied", "authentication failed"
```

### Step 5: Test database connection
```bash
# If you have psql installed:
psql "$NEW_DB_URL" -c "SELECT 1;"
# Expected: 1

# Or test via Fly.io logs:
curl https://yourdomain.com/health
# Should return 200 OK (means DB connection works)
```

### Step 6: Document results
```bash
# Edit and save:
# docs/IMPLEMENTATION_PROGRESS.md
# → Task 6 section
# - Date: [today]
# - Connection test: ✅ PASSED
# - App health: ✅ OK
```

---

## THIS WEEK: Task 7 - Test Backup Restore

**⏱️ 30 minutes - Manual in Supabase dashboard**

### Step 1: Clone backup to test project
```
1. Open: https://app.supabase.com
2. Go to: Settings → Backups
3. Select most recent backup (has green checkmark)
4. Click: "Restore to new project"
5. Name: "ems-restore-test-2026-07-17"
6. Click: "Restore"
7. Wait 10-15 minutes for restoration
```

### Step 2: Get test database credentials
```
1. When restore completes, note new connection string
2. Save: TEST_DB_URL="postgresql://..."
3. This is your temporary test database
```

### Step 3: Test database integrity
```bash
# Query user count
psql "$TEST_DB_URL" -c "SELECT COUNT(*) FROM users;"
# Note the count (should match production ~5-10 users for test institution)

# Query payroll runs
psql "$TEST_DB_URL" -c "SELECT COUNT(*) FROM payroll_runs;"

# Query employees
psql "$TEST_DB_URL" -c "SELECT COUNT(*) FROM employees;"

# All counts should match production (or be expected variance)
```

### Step 4: Spot check data
```bash
# Check superadmin user exists
psql "$TEST_DB_URL" -c "SELECT username, role FROM users WHERE role='superadmin';"
# Expected: superadmin | superadmin

# Check recent audit logs exist
psql "$TEST_DB_URL" -c "SELECT COUNT(*) FROM audit_logs WHERE created_at > NOW() - INTERVAL '30 days';"
# Expected: > 0 (some recent activity)
```

### Step 5: Clean up test project
```
1. Open: https://app.supabase.com
2. Go to: Projects
3. Find: "ems-restore-test-2026-07-17"
4. Click: ... → Delete project
5. Confirm deletion
```

### Step 6: Document results
```bash
# Edit and save:
# docs/IMPLEMENTATION_PROGRESS.md
# → Task 7 section
# - Date: [today]
# - User count: [matches production]
# - Data integrity: ✅ OK
# - Restore time: [X minutes]
```

---

## THIS WEEK: Task 8 - Print & Post Runbook

**⏱️ 10 minutes**

```bash
# Print runbook
wc -l docs/ONCALL_RUNBOOK.md  # Verify it's ~1500 lines
# Print first 30 pages

# Create quick reference card
# Print end of ONCALL_RUNBOOK.md (the card section)

# Post near desk
# Share link: ./docs/ONCALL_RUNBOOK.md
# Send Slack message to team
```

---

## THIS WEEK: Task 9 - Create Rotation Log

**⏱️ 5 minutes**

```bash
# Create rotation log file
cat > docs/SECRETS_ROTATION_LOG.md << 'EOF'
# Secrets Rotation Log

## 2026-07-17 - JWT_SECRET Rotation

**Type**: JWT_SECRET  
**Status**: ✅ COMPLETED  
**Duration**: 45 minutes  

**Details**:
- Old secret (first 8 chars): a1b2c3d4
- New secret (first 8 chars): f0e9d8c7
- Fly.io deployment: ✅ Succeeded (rolling restart)
- Health check: ✅ Passed
- Login test: ✅ Passed
- API tests: ✅ Passed

**Incidents**: None

---
EOF

# Commit to git
git add docs/SECRETS_ROTATION_LOG.md
git commit -m "Add secrets rotation log (first entry 2026-07-17)"
git push origin main
```

---

## Verification Commands

### Check everything is working
```bash
# Run verification script
./scripts/verify-implementation.sh

# Or manual checks:
curl https://yourdomain.com/health
flyctl status
flyctl secrets list
```

### Monitor after each task
```bash
# Always check logs for errors
flyctl logs --tail 20

# Always test health endpoint
curl https://yourdomain.com/health

# Always verify Sentry has no new errors
# → Go to: https://sentry.io → Issues
```

---

## Troubleshooting

### Fly.io deploy fails
```bash
# Check logs
flyctl logs --source app

# Redeploy
flyctl deploy

# Scale up if needed
flyctl scale count=2
```

### Database connection fails after rotation
```bash
# Check env var is set correctly
flyctl secrets list | grep DATABASE_URL

# Test connection directly
psql $DATABASE_URL -c "SELECT 1;"

# If fails, revert to old password:
flyctl secrets set DATABASE_URL="<OLD_PASSWORD>"
```

### Health endpoint not responding
```bash
# Check if app is running
flyctl status

# Check logs
flyctl logs --tail 50

# Restart if needed
flyctl scale count=0
sleep 5
flyctl scale count=1
```

---

## Quick Checklist

Print this and check off as you complete:

```
IMMEDIATE (1 hour):
☐ Enable Supabase backups (5 min)
☐ Schedule rotations (10 min)
☐ Wire Sentry alerts (20 min)
☐ Set up UptimeRobot (10 min)

THIS WEEK (2 hours):
☐ Test JWT rotation (45 min)
☐ Test DB credentials (30 min)
☐ Test backup restore (30 min)
☐ Print runbook (10 min)
☐ Create rotation log (5 min)

Total: ~3 hours for 100% implementation
```

---

## Support

If you get stuck:
1. Check: docs/CRITICAL_ITEMS_IMPLEMENTATION_CHECKLIST.md
2. Check: docs/[TASK_NAME].md (e.g., BACKUP_POLICY.md)
3. Review troubleshooting section above
4. Check: flyctl logs for errors
5. Check: Sentry for application errors

**Goal**: Zero downtime, all tests pass, all tasks documented ✅
