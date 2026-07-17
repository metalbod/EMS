# CRITICAL Items Implementation Progress

**Start Date**: 2026-07-17  
**Target Completion**: 2026-07-24  
**Status**: 🟡 IN PROGRESS

---

## IMMEDIATE Tasks (1 hour total)

### Task 1: Enable Supabase Automated Backups ⏱️ 5 min

**Status**: 🟡 PENDING

**Steps**:
- [ ] Log in to Supabase dashboard: https://app.supabase.com
- [ ] Select your EMS project
- [ ] Navigate to: Settings → Backups
- [ ] Click "Automated backups" toggle → ON
- [ ] Confirm retention period (7+ days)
- [ ] Wait for first backup to complete (up to 24 hours)
- [ ] Screenshot status page and save reference
- [ ] Verify: Last backup timestamp shows recent time

**Verification**:
```bash
# After enabling, check:
# Supabase Dashboard → Settings → Backups
# Look for:
# ✅ Status: "Enabled"
# ✅ Last backup: [recent timestamp]
# ✅ Next backup: [scheduled time]
```

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

### Task 2: Schedule Quarterly Rotation Reminders ⏱️ 10 min

**Status**: 🟡 PENDING

**Steps**:
- [ ] Open your calendar (Google Calendar, Outlook, etc.)
- [ ] Create recurring event "Q1 Secrets Rotation"
  - Start: January 1, 2027
  - Recurrence: Yearly
  - Time block: 45 minutes
  - Alert: 1 day before
- [ ] Create Q2 rotation
  - Start: April 1, 2026
  - Recurrence: Yearly
- [ ] Create Q3 rotation
  - Start: July 1, 2026
  - Recurrence: Yearly
- [ ] Create Q4 rotation
  - Start: October 1, 2026
  - Recurrence: Yearly
- [ ] Add to team Slack/calendar if applicable

**Verification**:
```bash
# Calendar should show 4 annual reminders
# Example: July 1 every year → "Q3 Secrets Rotation (45 min)"
```

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

### Task 3: Wire Sentry Email Alerts ⏱️ 20 min

**Status**: 🟡 PENDING

**Steps**:
- [ ] Log in to Sentry: https://sentry.io/auth/login/
- [ ] Navigate to: Organizations → [YOUR_ORG] → Projects → EMS
- [ ] Click "Settings" (left sidebar)
- [ ] Click "Alerts"
- [ ] Click "Create Alert Rule"

**Alert #1: High Error Rate**
- [ ] Alert Name: "High Error Rate (EMS)"
- [ ] Conditions:
  - IF: an event is seen
  - THEN: for each issue
  - WHEN: Event count rises above 10 in last 1 hour
- [ ] Actions:
  - Add Action → "Send Email"
  - To: kenneth@users-MacBook-Pro.local
- [ ] Click "Save"

**Alert #2: New Issues**
- [ ] Click "Create Alert Rule"
- [ ] Alert Name: "New Issue (EMS)"
- [ ] Conditions:
  - IF: a new issue is created
  - OR: Resolved issue is seen again
- [ ] Actions:
  - Add Action → "Send Email"
  - To: kenneth@users-MacBook-Pro.local
- [ ] Click "Save"

**Verification**:
```bash
# Sentry → Settings → Alerts
# Should show 2 active rules:
# ✅ "High Error Rate (EMS)" - Email enabled
# ✅ "New Issue (EMS)" - Email enabled

# Test alert (trigger an error):
# curl https://yourdomain.com/api/test-error
# Wait 1-2 minutes for email
```

**Completed**: _____ (Date/Time)  
**Test Email Received**: Yes / No  
**Notes**: ________________________

---

### Task 4: Set Up UptimeRobot Monitoring ⏱️ 10 min

**Status**: 🟡 PENDING

**Steps**:
- [ ] Go to: https://uptimerobot.com
- [ ] Click "Sign Up" (free tier is fine)
- [ ] Create account with email: kenneth@users-MacBook-Pro.local
- [ ] Verify email address
- [ ] Log in to UptimeRobot dashboard
- [ ] Click "Add New Monitor"
- [ ] Monitor Type: "HTTP(s)"
- [ ] Friendly Name: "EMS Health Check"
- [ ] URL: https://yourdomain.com/health
- [ ] Monitoring Interval: 5 minutes
- [ ] Alert Contacts:
  - [ ] Add email: kenneth@users-MacBook-Pro.local
  - [ ] Set to receive "Down" and "Up" alerts
- [ ] Click "Create Monitor"
- [ ] Wait ~5 minutes for first check

**Verification**:
```bash
# UptimeRobot Dashboard
# Should show:
# ✅ "EMS Health Check" - Status "Up"
# ✅ Last check: [within last 5 min]
# ✅ Uptime: ~100%

# Check Fly.io logs for health check requests:
flyctl logs | grep "GET /health"
# Should see recent requests from UptimeRobot
```

**Completed**: _____ (Date/Time)  
**First Check Passed**: Yes / No  
**Notes**: ________________________

---

## Summary: IMMEDIATE Tasks

| Task | Status | Time | Completed |
|------|--------|------|-----------|
| Backup Policy | ⏳ Implementation | 5 min | |
| Rotation Schedule | ⏳ Implementation | 10 min | |
| Sentry Alerts | ⏳ Implementation | 20 min | |
| UptimeRobot | ⏳ Implementation | 10 min | |
| **TOTAL** | | **45 min** | |

**Progress**: 0/4 tasks completed

---

## THIS WEEK Tasks (3 hours total)

### Task 5: Test JWT_SECRET Rotation ⏱️ 45 min

**Status**: 🟡 PENDING

**Prerequisites**:
- [ ] Task 1-4 completed
- [ ] Fly.io CLI installed and authenticated: `flyctl auth login`
- [ ] curl installed (for testing)

**Steps**:
1. [ ] Generate new JWT_SECRET
   ```bash
   NEW_SECRET=$(openssl rand -hex 32)
   echo "New secret: $NEW_SECRET"
   ```

2. [ ] Update Fly.io
   ```bash
   flyctl secrets set JWT_SECRET="$NEW_SECRET"
   ```

3. [ ] Verify update
   ```bash
   flyctl secrets list | grep JWT_SECRET
   # Should show new value
   ```

4. [ ] Monitor logs during rolling restart
   ```bash
   flyctl logs --tail 20
   # Watch for "connection successful" messages
   # Should NOT see "invalid token" errors
   ```

5. [ ] Test application health
   ```bash
   curl -s https://yourdomain.com/health
   # Expected: {"status": "ok"}
   ```

6. [ ] Test login works
   ```bash
   curl -X POST https://yourdomain.com/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{
       "username": "superadmin",
       "password": "Admin@123",
       "institution_code": null
     }'
   # Should return access_token
   ```

7. [ ] Test authenticated request with new token
   ```bash
   TOKEN="<ACCESS_TOKEN_FROM_ABOVE>"
   curl -H "Authorization: Bearer $TOKEN" \
     https://yourdomain.com/api/users
   # Should return 200 (not 401)
   ```

8. [ ] Document results
   - Date: _______________
   - Old secret (first 8 chars): _______________
   - New secret (first 8 chars): _______________
   - Redeploy status: ✅ Success / ❌ Failed
   - Tests passed: ✅ Yes / ❌ No
   - Issues: _______________

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

### Task 6: Test Database Credential Rotation ⏱️ 30 min

**Status**: 🟡 PENDING

**Steps**:
1. [ ] Log in to Supabase dashboard
2. [ ] Go to: Settings → Database → Users
3. [ ] Find user "ems_app" (not postgres)
4. [ ] Click "ems_app" → Edit → "Reset password"
5. [ ] Copy new password (appears in popup)
6. [ ] Build new DATABASE_URL:
   ```
   postgresql://ems_app.YOUR_PROJECT_REF:NEW_PASSWORD@YOUR_POOLER_HOST:6543/postgres
   ```

7. [ ] Update Fly.io
   ```bash
   flyctl secrets set DATABASE_URL="postgresql://..."
   ```

8. [ ] Monitor logs
   ```bash
   flyctl logs --tail 30
   # Look for: "connection successful"
   # NOT: "invalid password", "access denied"
   ```

9. [ ] Test database connectivity
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   # Should return: 1
   ```

10. [ ] Document results
    - Date: _______________
    - Old password (first 8 chars): _______________
    - New password (first 8 chars): _______________
    - Connection test: ✅ Passed / ❌ Failed
    - App health: ✅ OK / ❌ Errors

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

### Task 7: Test Backup Restore Procedure ⏱️ 30 min

**Status**: 🟡 PENDING

**Steps**:
1. [ ] Log in to Supabase dashboard
2. [ ] Go to: Settings → Backups
3. [ ] Find most recent backup (green checkmark)
4. [ ] Click: "Restore to new project"
5. [ ] Name: "ems-restore-test-2026-07-17"
6. [ ] Click "Restore"
7. [ ] Wait 10-15 minutes for restoration
8. [ ] When complete, get new database credentials
9. [ ] Test restored database
   ```bash
   psql "postgresql://..." -c "SELECT COUNT(*) FROM users;"
   # Should return number of users from production
   ```

10. [ ] Spot-check data integrity
    ```bash
    psql "postgresql://..." -c "SELECT COUNT(*) FROM payroll_runs;"
    psql "postgresql://..." -c "SELECT COUNT(*) FROM employees;"
    ```

11. [ ] Document results
    - Date: _______________
    - Backup used: _______________
    - Restore time: _____ minutes
    - User count matches: ✅ Yes / ❌ No
    - Data integrity: ✅ OK / ❌ Issues

12. [ ] Clean up test project
    - Supabase Dashboard → Projects
    - Delete "ems-restore-test-2026-07-17"

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

### Task 8: Print & Post On-Call Runbook ⏱️ 10 min

**Status**: 🟡 PENDING

**Steps**:
- [ ] Print: `docs/ONCALL_RUNBOOK.md` (30 pages)
  ```bash
  # From repo root:
  wc -l docs/ONCALL_RUNBOOK.md  # Verify size
  ```
- [ ] Print quick reference card (end of ONCALL_RUNBOOK.md)
- [ ] Post near desk or monitor
- [ ] Add to team wiki/Confluence if available
- [ ] Share link with team (Slack)

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

### Task 9: Create Secrets Rotation Log ⏱️ 5 min

**Status**: 🟡 PENDING

**Steps**:
- [ ] Create file: `docs/SECRETS_ROTATION_LOG.md`
- [ ] Add entry for Task 5 (JWT_SECRET rotation)
- [ ] Commit to git
  ```bash
  git add docs/SECRETS_ROTATION_LOG.md
  git commit -m "Add secrets rotation log (first entry)"
  git push origin main
  ```

**Completed**: _____ (Date/Time)  
**Notes**: ________________________

---

## Summary: THIS WEEK Tasks

| Task | Status | Time | Completed |
|------|--------|------|-----------|
| JWT Rotation | ⏳ Implementation | 45 min | |
| DB Credentials | ⏳ Implementation | 30 min | |
| Backup Test | ⏳ Implementation | 30 min | |
| Post Runbook | ⏳ Implementation | 10 min | |
| Rotation Log | ⏳ Implementation | 5 min | |
| **TOTAL** | | **2 hours** | |

**Progress**: 0/5 tasks completed

---

## Overall Progress

```
IMMEDIATE (1 hour):    0/4 tasks = 0%
THIS WEEK (2 hours):   0/5 tasks = 0%
─────────────────────────────────
TOTAL:                 0/9 tasks = 0%

Target: Complete all by 2026-07-24 (7 days)
Current pace: On track if starting today
```

---

## Next Steps

1. **Start with Task 1** (Backup enablement) → 5 minutes
2. **Then Task 2** (Calendar reminders) → 10 minutes
3. **Then Task 3** (Sentry alerts) → 20 minutes
4. **Then Task 4** (UptimeRobot) → 10 minutes

You should have IMMEDIATE tasks done by end of today (45 min total).

Then THIS WEEK schedule:
- **Monday (today)**: IMMEDIATE tasks + Task 5 (rotation test)
- **Tuesday**: Task 6 (DB credentials)
- **Thursday**: Task 7 (Backup restore test)
- **Friday**: Task 8-9 (Documentation)

---

**Last Updated**: 2026-07-17  
**By**: Claude (Implementation Guide)
