# Backup & Disaster Recovery Policy

## Overview

The EMS database is hosted on Supabase (PostgreSQL). This document outlines the backup strategy, recovery procedures, and testing schedule.

## Backup Strategy

### Automated Backups (Supabase)

**Status**: ⚠️ Must be enabled manually (not enabled by default on free tier)

Supabase provides automated daily backups via pgBackRest, stored in their secure S3 infrastructure:

- **Retention**: 7 days (free tier), 30 days (paid tier)
- **Frequency**: Daily automatic backups
- **Restore window**: Any point within retention period
- **RPO** (Recovery Point Objective): 24 hours
- **RTO** (Recovery Time Objective): ~5 minutes

### How to Enable Supabase Automated Backups

1. **Log in to Supabase dashboard** → https://app.supabase.com
2. **Select your EMS project**
3. **Go to Settings → Backups**
4. **Click "Automated backups"** → Toggle ON
5. **Set retention period**: 
   - Free tier: 7 days (default)
   - Paid tier: Choose 7, 14, or 30 days
6. **Confirm and wait for first backup** (typically within 24 hours)

**Note**: Backups are automatic after enablement; no additional action needed.

### Verification Checklist

After enabling, verify backups are running:

```bash
# Log in to Supabase dashboard
# Settings → Backups → Automated backups
# You should see:
# - ✅ Status: "Enabled"
# - ✅ Last backup timestamp (within last 24 hours)
# - ✅ Next scheduled backup
```

---

## Manual Backup Procedure

For pre-deployment or high-risk changes, create an on-demand backup:

### Step 1: Trigger Manual Backup

```bash
# Supabase Dashboard → Settings → Backups → Automated backups
# Click "Backup now" button
# Wait 2-5 minutes for completion
```

### Step 2: Verify Backup Created

```bash
# Settings → Backups → Automated backups
# Confirm new backup appears in the list with recent timestamp
```

### Step 3: Label for Reference (optional)

Backup name format: `ems_backup_YYYY-MM-DD_HH-MM_reason`
Example: `ems_backup_2026-07-17_14-30_pre_payroll_release`

---

## Restore Procedure

### Scenario 1: Restore to Most Recent Backup

**Time to restore**: 5-10 minutes
**Downtime**: Full service unavailable during restore

```bash
# Supabase Dashboard → Settings → Backups
# Select the backup you want to restore (usually most recent)
# Click "Restore" button
# Confirm the warning (cannot undo during restore)
# Wait for restore to complete (status will show "Restoring")
# Verify service health:
#   - GET http://yourdomain.com/health (should return 200)
#   - Check Sentry for errors
#   - Check Fly.io logs for startup errors
```

### Scenario 2: Restore to Specific Point-in-Time

If you need to recover from a specific time (e.g., 3 hours ago):

```bash
# Supabase Dashboard → Settings → Backups → Point-in-time recovery
# Select date/time within retention window
# Click "Restore to this point"
# Confirm (this is destructive)
# Wait for restore
```

### Scenario 3: Clone Database to Staging for Testing

Before restoring to production, you can test the restore on a clone:

```bash
# Supabase Dashboard → Settings → Backups
# Select backup → "Restore to new project"
# Create test project name (e.g., "ems-restore-test-2026-07-17")
# Wait ~15 minutes for full clone + restore
# Test thoroughly (run test suite, verify data)
# If tests pass: note the connection string
# If tests fail: delete test project and try different backup
# Delete test project when done
```

---

## Recovery Scenarios & Runbooks

### Scenario A: User Reports Data Loss or Corruption

1. **Assess impact** (ask user):
   - When did they notice the issue?
   - Which records are affected?
   - Is issue ongoing or was it one-time?

2. **Check application health**:
   ```bash
   curl https://yourdomain.com/health
   # Should return {"status": "ok"}
   
   # Check Sentry for recent errors
   # Check Fly.io logs: flyctl logs
   ```

3. **Calculate restore point**:
   - If issue noticed 1 hour ago, restore to 2-3 hours ago (buffer for detection lag)
   - Confirm this falls within backup retention window

4. **Perform restore** (see Scenario 1 above):
   - Take screenshot of current data for investigation
   - Restore from backup
   - Verify all services come back up
   - Test critical paths (login, payroll run, bulk upload)

5. **Post-incident analysis**:
   - Root cause: Data corruption? Accidental delete? Application bug?
   - Fix root cause before resuming
   - Document timeline in incident report

### Scenario B: Database Connection Failures

If the database becomes unreachable:

```bash
# Step 1: Check Supabase dashboard status
# https://status.supabase.com

# Step 2: Check Fly.io logs
flyctl logs

# Step 3: If Supabase is down, wait for their recovery
# If local issue (connection string wrong, firewall, etc.), fix and redeploy:
flyctl deploy

# Step 4: If no response after 30 mins, escalate to Supabase support
```

### Scenario C: Accidental Schema Corruption

If `init_db()` or migration went wrong:

```bash
# Step 1: Stop the app to prevent further damage
flyctl scale count=0

# Step 2: Identify the last good backup
# (Look at timestamps in Supabase dashboard)

# Step 3: Restore to that backup
# (See Scenario 1 above)

# Step 4: Redeploy app
flyctl scale count=1

# Step 5: Monitor logs and health endpoint
flyctl logs
curl https://yourdomain.com/health
```

---

## Testing Schedule

### Monthly Restore Test (Recommended)

**Purpose**: Verify backups are actually restorable (not corrupted or missing)

**Frequency**: 1st of every month

**Procedure**:

1. **Create test project** (clone latest backup to staging)
   ```bash
   # Supabase Dashboard → Settings → Backups
   # Select most recent backup
   # "Restore to new project" → "ems-restore-test-YYYY-MM-DD"
   ```

2. **Run verification checks**:
   ```bash
   # Update .env.test with new test database connection
   DATABASE_URL="postgresql://..." (from clone)
   
   # Run tests against cloned database
   pytest tests/test_auth.py::test_login_success
   pytest tests/test_employees.py -k "test_create_employee"
   pytest tests/test_payroll.py -k "test_list_payroll_runs"
   
   # Spot-check data
   # - Count users (should match production)
   # - Check recent payroll runs
   # - Verify audit logs
   ```

3. **Document results**:
   ```bash
   # Create monthly test record:
   # docs/BACKUP_TESTS.md
   # 
   # 2026-07-01: ✅ PASS
   # - Backup: 2026-06-30
   # - Tests passed: 5/5
   # - Data verified: 42 users, 5 payroll runs
   # - Notes: None
   ```

4. **Clean up test project**:
   ```bash
   # Supabase Dashboard → Settings → Projects
   # Delete "ems-restore-test-YYYY-MM-DD" project
   ```

**Success criteria**:
- ✅ Restore completes without errors
- ✅ All tests pass on restored database
- ✅ Data counts match production (within expected variance)

**Failure response**:
- ❌ Contact Supabase support immediately
- ❌ Do not delete backup
- ❌ Create incident ticket

---

## Backup Test Record

Track monthly restore tests here:

| Date | Backup Date | Result | Tests Passed | Data Verified | Notes |
|------|-------------|--------|--------------|---------------|-------|
| 2026-08-01 | 2026-07-31 | PENDING | - | - | First scheduled test |
| | | | | | |

---

## Runbook Quick Reference

### 🚨 Emergency Restore Checklist

```
[ ] Assess impact (how much data lost? how old is issue?)
[ ] Check Supabase status (https://status.supabase.com)
[ ] Check Fly.io logs (flyctl logs)
[ ] Screenshot current broken state (for incident report)
[ ] Identify restore point (safe? within retention?)
[ ] Take app offline (flyctl scale count=0)
[ ] Trigger restore in Supabase dashboard
[ ] Wait for restore completion (5-10 minutes)
[ ] Bring app back online (flyctl scale count=1)
[ ] Verify health endpoint (curl /health)
[ ] Run smoke tests (login, key operations)
[ ] Monitor Sentry and logs for errors
[ ] Post-incident analysis (root cause?)
[ ] Document incident timeline
```

---

## Contact & Escalation

### Supabase Support

- **Dashboard**: https://app.supabase.com → Settings → Contact Support
- **Status Page**: https://status.supabase.com
- **Community**: https://discord.supabase.io

### Internal Escalation

- **Primary**: Kenneth Yong (kenneth@users-MacBook-Pro.local)
- **Secondary**: (Add team member if applicable)
- **Oncall**: Check team Slack channel #oncall

---

## Configuration Summary

```yaml
Backup Provider: Supabase (pgBackRest)
Frequency: Daily (automatic)
Retention: 7-30 days (depends on plan)
RPO: 24 hours (one day of data loss acceptable?)
RTO: 5-10 minutes (acceptable downtime?)
Last Test: (To be filled on first test)
Test Schedule: Monthly (1st of month)
Status: ✅ Enabled
```

---

## Related Documentation

- [README.md](../README.md) — General project documentation
- [ONCALL_RUNBOOK.md](ONCALL_RUNBOOK.md) — Incident response procedures
- Supabase docs: https://supabase.com/docs/guides/database/backups
